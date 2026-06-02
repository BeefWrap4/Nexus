#!/usr/bin/env bash
# =============================================================================
# NEXUS 快速启动脚本 (Quickstart)
# 用途：一键检查环境、初始化数据库、启动后端，给出前端启动命令
# 用法：bash scripts/quickstart.sh [--skip-docker-check] [--local]
# =============================================================================
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  NEXUS Quickstart - 快速启动向导       ${NC}"
echo -e "${BLUE}========================================${NC}"

# ---------------------------------------------------------------------------
# 解析参数
# ---------------------------------------------------------------------------
SKIP_DOCKER_CHECK=false
LOCAL_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-docker-check)
            SKIP_DOCKER_CHECK=true
            shift
            ;;
        --local)
            LOCAL_MODE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-docker-check   Skip Docker daemon check"
            echo "  --local               Start backend locally (without Docker Compose)"
            echo "  --help, -h            Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Step 1: 检查 Docker 是否运行
# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[1/5]${NC} ${YELLOW}Checking Docker daemon...${NC}"

if [ "$SKIP_DOCKER_CHECK" = false ]; then
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}  ✗ Docker is not running.${NC}"
        echo -e "${RED}    Please start Docker Desktop and re-run this script.${NC}"
        echo -e "${YELLOW}    Or use --skip-docker-check if you have started services manually.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  ✓ Docker is running${NC}"
else
    echo -e "${YELLOW}  ⚠ Docker check skipped (--skip-docker-check)${NC}"
fi

# ---------------------------------------------------------------------------
# Docker Compose 命令检测
# ---------------------------------------------------------------------------
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

# ---------------------------------------------------------------------------
# Step 2: 加载环境变量
# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[2/5]${NC} ${YELLOW}Loading environment variables...${NC}"

if [ -f "${PROJECT_ROOT}/.env" ]; then
    # 安全地加载 .env 文件（只加载格式正确的行）
    set -a
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/.env"
    set +a
    echo -e "${GREEN}  ✓ .env loaded${NC}"
else
    echo -e "${YELLOW}  ⚠ .env file not found. Run: cp .env.example .env${NC}"
    echo -e "${YELLOW}    Then edit .env with your API keys.${NC}"
fi

# 检查关键配置
WARNINGS=0
if [ -z "${DEEPSEEK_API_KEY:-}" ] || [ "${DEEPSEEK_API_KEY:-}" = "sk-..." ]; then
    echo -e "${YELLOW}  ⚠ DEEPSEEK_API_KEY is not configured${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
if [ -z "${OPENAI_API_KEY:-}" ] || [ "${OPENAI_API_KEY:-}" = "sk-..." ]; then
    echo -e "${YELLOW}  ⚠ OPENAI_API_KEY is not configured${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ] || [ "${ANTHROPIC_API_KEY:-}" = "sk-ant-..." ]; then
    echo -e "${YELLOW}  ⚠ ANTHROPIC_API_KEY is not configured${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

if [ "$WARNINGS" -gt 0 ]; then
    echo -e "${YELLOW}  ⚠ ${WARNINGS} API key(s) not set. Some LLM providers will be unavailable.${NC}"
fi

# ---------------------------------------------------------------------------
# Step 3: 初始化数据库
# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[3/5]${NC} ${YELLOW}Initializing database...${NC}"

if [ "$SKIP_DOCKER_CHECK" = false ]; then
    # 检查 PostgreSQL 容器是否已运行
    if docker ps --format '{{.Names}}' | grep -q "nexus-postgres"; then
        echo -e "${GREEN}  ✓ PostgreSQL container is running${NC}"
    else
        echo -e "${YELLOW}  Starting PostgreSQL and Redis...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d postgres redis 2>&1 | sed 's/^/    /'
        echo -e "${YELLOW}  Waiting for PostgreSQL to be ready...${NC}"
        until ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres pg_isready -U "${POSTGRES_USER:-nexus}" -d "${POSTGRES_DB:-nexus}" > /dev/null 2>&1; do
            echo -n "."
            sleep 1
        done
        echo ""
        echo -e "${GREEN}  ✓ PostgreSQL is ready${NC}"
    fi

    # 运行数据库初始化
    if docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${YELLOW}  API container already running, initializing via container...${NC}"
        docker exec nexus-api python scripts/init_db.py 2>&1 | sed 's/^/    /' || true
    else
        echo -e "${YELLOW}  Running init_db.py locally...${NC}"
        cd "${PROJECT_ROOT}"
        pip install -q python-dotenv sqlalchemy asyncpg 2>/dev/null || true
        python scripts/init_db.py 2>&1 | sed 's/^/    /' || {
            echo -e "${YELLOW}  ⚠ Local init failed. Will be initialized when API starts.${NC}"
        }
    fi
else
    echo -e "${YELLOW}  ⚠ Docker check skipped — ensure database is running manually.${NC}"
fi

# ---------------------------------------------------------------------------
# Step 4: 启动后端
# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[4/5]${NC} ${YELLOW}Starting backend API...${NC}"

if [ "$LOCAL_MODE" = true ]; then
    echo -e "${YELLOW}  Starting locally (no Docker Compose)...${NC}"
    echo -e "${YELLOW}  Run: python nexus_cli.py run --port 8000${NC}"
    echo -e "${YELLOW}  Or:  uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload${NC}"

    # 尝试直接启动
    cd "${PROJECT_ROOT}"
    if command -v python &> /dev/null; then
        echo -e "${GREEN}  Starting uvicorn...${NC}"
        python -m uvicorn nexus.api.main:app --host 0.0.0.0 --port 8000 --reload &
        API_PID=$!
        echo -e "${GREEN}  ✓ API started (PID: ${API_PID})${NC}"
        sleep 2
    fi
else
    if docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${GREEN}  ✓ API container is already running${NC}"
    else
        echo -e "${YELLOW}  Starting API via Docker Compose...${NC}"
        # 先启动基础设施
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d postgres redis minio litellm 2>&1 | sed 's/^/    /'

        # 等待就绪
        echo -e "${YELLOW}  Waiting for LiteLLM...${NC}"
        for i in $(seq 1 30); do
            if curl -sf http://localhost:4000/health/liveliness > /dev/null 2>&1; then
                echo -e "${GREEN}  ✓ LiteLLM is ready${NC}"
                break
            fi
            sleep 1
        done

        # 启动API
        echo -e "${YELLOW}  Starting API and Worker...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d api worker 2>&1 | sed 's/^/    /'

        # 等待API健康检查
        echo -e "${YELLOW}  Waiting for API to be healthy...${NC}"
        for i in $(seq 1 60); do
            if curl -sf http://localhost:8765/health > /dev/null 2>&1; then
                echo -e "${GREEN}  ✓ API is healthy${NC}"
                break
            fi
            echo -n "."
            sleep 1
            if [ "$i" -eq 60 ]; then
                echo -e "\n${RED}  ✗ API failed to start within 60 seconds${NC}"
                echo -e "${YELLOW}    Check logs: ${COMPOSE_CMD} logs api${NC}"
            fi
        done
    fi
fi

# ---------------------------------------------------------------------------
# Step 5: 给出前端启动命令
# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[5/5]${NC} ${YELLOW}Frontend startup instructions:${NC}"
echo ""
echo -e "  ${GREEN}Option A - Docker Compose (recommended):${NC}"
echo -e "    ${COMPOSE_CMD} -f ${PROJECT_ROOT}/docker-compose.yml up -d ui"
echo ""
echo -e "  ${GREEN}Option B - Local dev server:${NC}"
echo -e "    cd ${PROJECT_ROOT}/nexus-ui"
echo -e "    npm install          # (first time only)"
echo -e "    npm run dev          # → http://localhost:5173"
echo ""

# ---------------------------------------------------------------------------
# 服务访问地址
# ---------------------------------------------------------------------------
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  Service Access URLs:                   ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "  ${GREEN}Frontend:${NC}      http://localhost:${UI_PORT:-5173}"
echo -e "  ${GREEN}API Docs:${NC}      http://localhost:${API_PORT:-8765}/docs"
echo -e "  ${GREEN}API Health:${NC}    http://localhost:${API_PORT:-8765}/health"
echo -e "  ${GREEN}LiteLLM:${NC}       http://localhost:${LITELLM_PORT:-4000}"
echo -e "  ${GREEN}MinIO Console:${NC} http://localhost:${MINIO_CONSOLE_PORT:-9001}"
echo -e "  ${GREEN}PostgreSQL:${NC}    localhost:${POSTGRES_PORT:-5432}"
echo -e "  ${GREEN}Redis:${NC}         localhost:${REDIS_PORT:-6379}"
echo ""

echo -e "${YELLOW}Useful commands:${NC}"
echo -e "  View API logs:  ${COMPOSE_CMD} -f ${PROJECT_ROOT}/docker-compose.yml logs -f api"
echo -e "  Stop all:       ${COMPOSE_CMD} -f ${PROJECT_ROOT}/docker-compose.yml down"
echo -e "  CLI info:       python ${PROJECT_ROOT}/nexus_cli.py info"
echo -e "  Seed data:      python ${PROJECT_ROOT}/nexus_cli.py db seed"
echo ""
