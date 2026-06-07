#!/usr/bin/env bash
# =============================================================================
# NEXUS 增量部署脚本 (Incremental Deployment)
# 用途：基于变更检测的分层增量部署，支持国内源加速
# 用法：bash scripts/deploy.sh [OPTIONS]
#
# 选项:
#   --layer <layer>  指定部署层 (infra|backend|frontend|all)
#   --build          强制重新构建镜像
#   --migrate        执行数据库迁移
#   --verify         部署后运行功能验证
#   --full           全量部署（等价于 --layer all --build --migrate --verify）
#   --no-cn-mirror   禁用国内源（海外部署时使用）
#   --help, -h       显示帮助信息
#
# 示例:
#   bash scripts/deploy.sh --layer backend --build --migrate
#   bash scripts/deploy.sh --full
#   bash scripts/deploy.sh --layer frontend
# =============================================================================
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 默认值
LAYER=""
BUILD=false
MIGRATE=false
VERIFY=false
NO_CN_MIRROR=false
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yml"
# 默认 production image — 防止漏一个 env var 跑出 dev (--reload)
export DOCKER_BUILD_TARGET="${DOCKER_BUILD_TARGET:-production}"

# 变更检测结果
INFRA_CHANGED=false
BACKEND_CHANGED=false
FRONTEND_CHANGED=false

# ---------------------------------------------------------------------------
# 打印帮助信息
# ---------------------------------------------------------------------------
show_help() {
    cat <<EOF
NEXUS Incremental Deployment Script

Usage: $(basename "$0") [OPTIONS]

Options:
  --layer <layer>   Deploy specific layer: infra | backend | frontend | all
                    Default: auto-detect from git diff
  --build           Force rebuild Docker images
  --migrate         Run database migrations
  --verify          Run post-deployment verification
  --full            Full deployment (--layer all --build --migrate --verify)
  --no-cn-mirror    Disable China mirrors (for overseas deployment)
  --help, -h        Show this help message

Examples:
  # Full production deployment
  $(basename "$0") --full

  # Deploy only backend with migration
  $(basename "$0") --layer backend --build --migrate

  # Deploy frontend only (fastest)
  $(basename "$0") --layer frontend

  # Auto-detect changes and deploy affected layers
  $(basename "$0")

  # Overseas deployment without China mirrors
  $(basename "$0") --full --no-cn-mirror

Layers:
  infra     - PostgreSQL, Redis, MinIO, LiteLLM (low change frequency)
  backend   - API server, ARQ Worker (medium change frequency)
  frontend  - Vue3 UI (high change frequency)
  all       - All layers in dependency order
EOF
}

# ---------------------------------------------------------------------------
# 解析命令行参数
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --layer)
            LAYER="$2"
            shift 2
            ;;
        --build)
            BUILD=true
            shift
            ;;
        --migrate)
            MIGRATE=true
            shift
            ;;
        --verify)
            VERIFY=true
            shift
            ;;
        --full)
            LAYER="all"
            BUILD=true
            MIGRATE=true
            VERIFY=true
            shift
            ;;
        --no-cn-mirror)
            NO_CN_MIRROR=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Docker Compose 命令检测
# ---------------------------------------------------------------------------
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
load_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        # 用 python 解析 .env，跳过 <...> 占位符（避免 bash 把 < 当 stdin 重定向）
        # 然后导出为合法的 KEY=VAL 形式
        local env_tmp
        env_tmp=$(mktemp)
        trap 'rm -f "$env_tmp"' RETURN

        python3 - "$PROJECT_ROOT/.env" > "$env_tmp" <<'PYEOF'
import re, shlex, sys
with open(sys.argv[1]) as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k = k.strip()
        v = v.strip()
        # 跳过模板占位符（如 <REPLACE_...>、<YOUR_...>、<LEAVE_BLANK_...>）
        if re.match(r'^<[A-Z0-9_]+>$', v):
            continue
        # 用 shlex.quote 防止值里的空格、$ 等造成注入
        print(f'export {k}={shlex.quote(v)}')
PYEOF

        set -a
        # shellcheck source=/dev/null
        source "$env_tmp"
        set +a
        echo -e "${GREEN}✓ .env loaded (placeholders skipped)${NC}"
    else
        echo -e "${YELLOW}⚠ .env file not found${NC}"
    fi

    # 设置国内源开关
    if [ "$NO_CN_MIRROR" = true ]; then
        export USE_CN_MIRROR="false"
        echo -e "${YELLOW}⚠ China mirrors disabled${NC}"
    else
        export USE_CN_MIRROR="${USE_CN_MIRROR:-true}"
        echo -e "${GREEN}✓ China mirrors enabled (USE_CN_MIRROR=${USE_CN_MIRROR})${NC}"
    fi
}

# ---------------------------------------------------------------------------
# 检测各层变更
# ---------------------------------------------------------------------------
detect_changes() {
    echo -e "\n${CYAN}[1/5]${NC} ${YELLOW}Detecting changes...${NC}"

    # 检查是否在 git 仓库中
    if ! git -C "${PROJECT_ROOT}" rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "${YELLOW}  ⚠ Not a git repository, skipping auto-detect${NC}"
        return
    fi

    # 获取上次部署的 commit（通过 tag 或文件记录）
    LAST_DEPLOY_COMMIT=""
    if [ -f "${PROJECT_ROOT}/.last-deploy" ]; then
        LAST_DEPLOY_COMMIT=$(cat "${PROJECT_ROOT}/.last-deploy")
    fi

    if [ -z "$LAST_DEPLOY_COMMIT" ]; then
        # 没有上次部署记录，检查最近的变更
        DIFF_BASE="HEAD~1"
        echo -e "${YELLOW}  No previous deployment found, checking HEAD~1${NC}"
    else
        DIFF_BASE="$LAST_DEPLOY_COMMIT"
        echo -e "  Last deploy: ${CYAN}${LAST_DEPLOY_COMMIT:0:8}${NC}"
    fi

    # 检测基础设施变更 (docker-compose, Dockerfile, .env)
    if git -C "${PROJECT_ROOT}" diff --name-only "$DIFF_BASE" HEAD 2>/dev/null | grep -qE "^(docker-compose|Dockerfile|\.env|\.docker/)"; then
        INFRA_CHANGED=true
        echo -e "  ${GREEN}✓ INFRA layer changed${NC}"
    else
        echo -e "  ${YELLOW}- INFRA layer unchanged${NC}"
    fi

    # 检测后端变更 (nexus/, tests/, alembic/, pyproject.toml, requirements.txt)
    if git -C "${PROJECT_ROOT}" diff --name-only "$DIFF_BASE" HEAD 2>/dev/null | grep -qE "^(nexus/|tests/|alembic/|pyproject\.toml|requirements\.txt|alembic\.ini|nexus_cli\.py)"; then
        BACKEND_CHANGED=true
        echo -e "  ${GREEN}✓ BACKEND layer changed${NC}"
    else
        echo -e "  ${YELLOW}- BACKEND layer unchanged${NC}"
    fi

    # 检测前端变更 (nexus-ui/)
    if git -C "${PROJECT_ROOT}" diff --name-only "$DIFF_BASE" HEAD 2>/dev/null | grep -qE "^nexus-ui/"; then
        FRONTEND_CHANGED=true
        echo -e "  ${GREEN}✓ FRONTEND layer changed${NC}"
    else
        echo -e "  ${YELLOW}- FRONTEND layer unchanged${NC}"
    fi
}

# ---------------------------------------------------------------------------
# 确定部署层
# ---------------------------------------------------------------------------
resolve_layer() {
    if [ -n "$LAYER" ]; then
        # 用户手动指定了层
        echo -e "  ${CYAN}Layer manually specified: ${LAYER}${NC}"
        return
    fi

    # 自动检测
    if [ "$INFRA_CHANGED" = true ] && [ "$BACKEND_CHANGED" = true ] && [ "$FRONTEND_CHANGED" = true ]; then
        LAYER="all"
    elif [ "$INFRA_CHANGED" = true ]; then
        LAYER="infra"
    elif [ "$BACKEND_CHANGED" = true ]; then
        LAYER="backend"
    elif [ "$FRONTEND_CHANGED" = true ]; then
        LAYER="frontend"
    else
        echo -e "${YELLOW}No changes detected. Use --layer to force deploy a specific layer.${NC}"
        echo -e "${YELLOW}Or use --build to force rebuild.${NC}"
        exit 0
    fi

    echo -e "  ${CYAN}Auto-detected layer: ${LAYER}${NC}"
}

# ---------------------------------------------------------------------------
# 部署基础设施层
# ---------------------------------------------------------------------------
deploy_infra() {
    echo -e "\n${CYAN}[2/5]${NC} ${YELLOW}Deploying INFRA layer...${NC}"

    local build_flag=""
    if [ "$BUILD" = true ]; then
        build_flag="--build"
    fi

    # 启动基础设施服务
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" up -d ${build_flag} postgres redis minio litellm

    # 等待 PostgreSQL 就绪
    echo -e "${YELLOW}  Waiting for PostgreSQL...${NC}"
    until ${COMPOSE_CMD} -f "$COMPOSE_FILE" exec -T postgres pg_isready -U "${POSTGRES_USER:-nexus}" -d "${POSTGRES_DB:-nexus}" > /dev/null 2>&1; do
        echo -n "."
        sleep 1
    done
    echo -e "\n  ${GREEN}✓ PostgreSQL ready${NC}"

    # 等待 Redis 就绪
    echo -e "${YELLOW}  Waiting for Redis...${NC}"
    until ${COMPOSE_CMD} -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; do
        echo -n "."
        sleep 1
    done
    echo -e "\n  ${GREEN}✓ Redis ready${NC}"

    # 等待 MinIO 就绪
    echo -e "${YELLOW}  Waiting for MinIO...${NC}"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:"${MINIO_API_PORT:-9000}"/minio/health/live > /dev/null 2>&1; then
            echo -e "\n  ${GREEN}✓ MinIO ready${NC}"
            break
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 30 ]; then
            echo -e "\n  ${RED}✗ MinIO failed to start${NC}"
            return 1
        fi
    done

    # 等待 LiteLLM 就绪
    echo -e "${YELLOW}  Waiting for LiteLLM...${NC}"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:"${LITELLM_PORT:-4000}"/health/liveliness > /dev/null 2>&1; then
            echo -e "\n  ${GREEN}✓ LiteLLM ready${NC}"
            break
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 30 ]; then
            echo -e "\n  ${RED}✗ LiteLLM failed to start${NC}"
            return 1
        fi
    done

    echo -e "${GREEN}✓ INFRA layer deployed${NC}"
}

# ---------------------------------------------------------------------------
# 数据库迁移
# ---------------------------------------------------------------------------
run_migrations() {
    echo -e "\n${CYAN}[Migration]${NC} ${YELLOW}Running database migrations...${NC}"

    # 检查 API 容器是否运行
    if ! docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${YELLOW}  API container not running, starting it first...${NC}"
        ${COMPOSE_CMD} -f "$COMPOSE_FILE" up -d api

        echo -e "${YELLOW}  Waiting for API to be healthy...${NC}"
        for i in $(seq 1 60); do
            if curl -sf http://localhost:"${API_PORT:-8765}"/health > /dev/null 2>&1; then
                echo -e "\n  ${GREEN}✓ API healthy${NC}"
                break
            fi
            echo -n "."
            sleep 1
            if [ "$i" -eq 60 ]; then
                echo -e "\n  ${RED}✗ API failed to start${NC}"
                return 1
            fi
        done
    fi

    # 执行 Alembic 迁移
    echo -e "${YELLOW}  Running alembic upgrade head...${NC}"
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" exec -T api alembic upgrade head 2>&1 | sed 's/^/    /'

    echo -e "${GREEN}✓ Database migration complete${NC}"
}

# ---------------------------------------------------------------------------
# 部署后端层（滚动更新：先 worker 后 api）
# ---------------------------------------------------------------------------
deploy_backend() {
    echo -e "\n${CYAN}[3/5]${NC} ${YELLOW}Deploying BACKEND layer...${NC}"

    local build_flag=""
    if [ "$BUILD" = true ]; then
        build_flag="--build"
    fi

    # 先更新 worker（避免中断正在执行的 job）
    echo -e "${YELLOW}  Updating worker...${NC}"
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" up -d ${build_flag} worker

    # 等待 worker 就绪
    echo -e "${YELLOW}  Waiting for worker to be ready...${NC}"
    sleep 5
    if docker ps --format '{{.Names}}' | grep -q "nexus-worker"; then
        echo -e "  ${GREEN}✓ Worker updated${NC}"
    else
        echo -e "  ${YELLOW}⚠ Worker status unknown, continuing...${NC}"
    fi

    # 再更新 API
    echo -e "${YELLOW}  Updating API...${NC}"
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" up -d ${build_flag} api

    # 等待 API 健康检查通过
    echo -e "${YELLOW}  Waiting for API health check...${NC}"
    for i in $(seq 1 60); do
        if curl -sf http://localhost:"${API_PORT:-8765}"/health > /dev/null 2>&1; then
            echo -e "\n  ${GREEN}✓ API healthy${NC}"
            break
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 60 ]; then
            echo -e "\n  ${RED}✗ API failed health check${NC}"
            ${COMPOSE_CMD} -f "$COMPOSE_FILE" logs api --tail=50
            return 1
        fi
    done

    echo -e "${GREEN}✓ BACKEND layer deployed${NC}"
}

# ---------------------------------------------------------------------------
# 部署前端层
# ---------------------------------------------------------------------------
deploy_frontend() {
    echo -e "\n${CYAN}[4/5]${NC} ${YELLOW}Deploying FRONTEND layer...${NC}"

    local build_flag=""
    if [ "$BUILD" = true ]; then
        build_flag="--build"
    fi

    # 更新前端（生产环境使用 ui profile）
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" up -d ${build_flag} ui

    # 等待前端就绪
    echo -e "${YELLOW}  Waiting for UI to be ready...${NC}"
    for i in $(seq 1 30); do
        if curl -sf http://localhost:"${UI_PORT:-80}" > /dev/null 2>&1; then
            echo -e "\n  ${GREEN}✓ UI ready${NC}"
            break
        fi
        echo -n "."
        sleep 1
        if [ "$i" -eq 30 ]; then
            echo -e "\n  ${YELLOW}⚠ UI health check timeout (may still be starting)${NC}"
        fi
    done

    echo -e "${GREEN}✓ FRONTEND layer deployed${NC}"
}

# ---------------------------------------------------------------------------
# 部署后验证
# ---------------------------------------------------------------------------
run_verification() {
    echo -e "\n${CYAN}[5/5]${NC} ${YELLOW}Running post-deployment verification...${NC}"

    local verify_script="${PROJECT_ROOT}/scripts/verify_deployment.py"

    if [ ! -f "$verify_script" ]; then
        echo -e "${YELLOW}  ⚠ verify_deployment.py not found, skipping verification${NC}"
        return 0
    fi

    # 安装验证脚本依赖
    pip install -q httpx 2>/dev/null || true

    # 运行验证
    local api_url="http://localhost:${API_PORT:-8765}"
    echo -e "${YELLOW}  Running verification against ${api_url}...${NC}"

    if python "$verify_script" --url "$api_url" 2>&1 | sed 's/^/    /'; then
        echo -e "${GREEN}✓ Verification passed${NC}"
    else
        echo -e "${RED}✗ Verification failed${NC}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 记录部署版本
# ---------------------------------------------------------------------------
record_deployment() {
    local current_commit
    current_commit=$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo "unknown")
    echo "$current_commit" > "${PROJECT_ROOT}/.last-deploy"
    echo -e "\n${GREEN}✓ Deployment recorded: ${current_commit:0:8}${NC}"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  NEXUS Incremental Deployment           ${NC}"
    echo -e "${BLUE}========================================${NC}"

    # 检查 Docker
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}✗ Docker is not running.${NC}"
        exit 1
    fi

    # 加载环境
    load_env

    # 检测变更
    detect_changes

    # 确定部署层
    resolve_layer

    # 执行部署
    case "$LAYER" in
        infra)
            deploy_infra
            ;;
        backend)
            deploy_infra
            if [ "$MIGRATE" = true ]; then
                run_migrations
            fi
            deploy_backend
            ;;
        frontend)
            deploy_frontend
            ;;
        all)
            deploy_infra
            if [ "$MIGRATE" = true ]; then
                run_migrations
            fi
            deploy_backend
            deploy_frontend
            ;;
        *)
            echo -e "${RED}Unknown layer: ${LAYER}${NC}"
            show_help
            exit 1
            ;;
    esac

    # 部署后验证
    if [ "$VERIFY" = true ]; then
        run_verification
    fi

    # 记录部署
    record_deployment

    # 显示服务状态
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${GREEN}  Deployment Complete!                  ${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    ${COMPOSE_CMD} -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
        ${COMPOSE_CMD} -f "$COMPOSE_FILE" ps
    echo ""
    echo -e "${CYAN}Access URLs:${NC}"
    echo -e "  ${GREEN}Frontend:${NC}    http://localhost:${UI_PORT:-80}"
    echo -e "  ${GREEN}API Docs:${NC}    http://localhost:${API_PORT:-8765}/docs"
    echo -e "  ${GREEN}API Health:${NC}  http://localhost:${API_PORT:-8765}/health"
    echo ""
    echo -e "${YELLOW}Useful commands:${NC}"
    echo -e "  View logs:    ${COMPOSE_CMD} -f ${COMPOSE_FILE} logs -f"
    echo -e "  Restart API:  ${COMPOSE_CMD} -f ${COMPOSE_FILE} restart api"
    echo -e "  Stop all:     ${COMPOSE_CMD} -f ${COMPOSE_FILE} down"
}

main "$@"
