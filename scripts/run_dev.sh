#!/usr/bin/env bash
# =============================================================================
# NEXUS 开发环境启动脚本
# =============================================================================
set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  NEXUS Development Environment Startup  ${NC}"
echo -e "${BLUE}========================================${NC}"

# ---------------------------------------------------------------------------
# 检查依赖
# ---------------------------------------------------------------------------
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed.${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ $1 found${NC}"
}

echo -e "\n${YELLOW}Checking dependencies...${NC}"
check_command docker
check_command docker-compose || check_command "docker compose"

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo -e "\n${YELLOW}Loading environment variables from .env...${NC}"
    set -a
    # shellcheck source=/dev/null
    source "${PROJECT_ROOT}/.env"
    set +a
else
    echo -e "${YELLOW}Warning: .env file not found, using defaults.${NC}"
fi

# ---------------------------------------------------------------------------
# 解析参数
# ---------------------------------------------------------------------------
BUILD=false
RESET_DB=false
SEED=false
LOGS=false
SERVICES=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --build|-b)
            BUILD=true
            shift
            ;;
        --reset-db)
            RESET_DB=true
            shift
            ;;
        --seed)
            SEED=true
            shift
            ;;
        --logs|-l)
            LOGS=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS] [SERVICES]"
            echo ""
            echo "Options:"
            echo "  --build, -b      Rebuild Docker images before starting"
            echo "  --reset-db       Reset database (drop and recreate tables)"
            echo "  --seed           Seed database with sample data after startup"
            echo "  --logs, -l       Follow logs after startup"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Services:"
            echo "  Space-separated list of services to start (default: all)"
            echo "  Examples: postgres redis api ui"
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
        *)
            SERVICES="$SERVICES $1"
            shift
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
# 构建镜像
# ---------------------------------------------------------------------------
if [ "$BUILD" = true ]; then
    echo -e "\n${YELLOW}Building Docker images...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" build --no-cache
fi

# ---------------------------------------------------------------------------
# 启动基础设施服务
# ---------------------------------------------------------------------------
echo -e "\n${YELLOW}Starting infrastructure services...${NC}"
${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d postgres redis minio litellm

# 等待数据库就绪
echo -e "\n${YELLOW}Waiting for PostgreSQL to be ready...${NC}"
until ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres pg_isready -U "${POSTGRES_USER:-nexus}" -d "${POSTGRES_DB:-nexus}" > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo -e "\n${GREEN}✓ PostgreSQL is ready${NC}"

# 等待 Redis 就绪
echo -e "\n${YELLOW}Waiting for Redis to be ready...${NC}"
until ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T redis redis-cli ping > /dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo -e "\n${GREEN}✓ Redis is ready${NC}"

# ---------------------------------------------------------------------------
# 重置数据库（如指定）
# ---------------------------------------------------------------------------
if [ "$RESET_DB" = true ]; then
    echo -e "\n${YELLOW}Resetting database...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api python scripts/init_db.py --drop <<EOF
yes
EOF
    echo -e "${GREEN}✓ Database reset complete${NC}"
fi

# ---------------------------------------------------------------------------
# 初始化数据库表
# ---------------------------------------------------------------------------
echo -e "\n${YELLOW}Initializing database tables...${NC}"
${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api python scripts/init_db.py
echo -e "${GREEN}✓ Database initialized${NC}"

# ---------------------------------------------------------------------------
# 启动 API 和 Worker
# ---------------------------------------------------------------------------
echo -e "\n${YELLOW}Starting API and Worker services...${NC}"
${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d api worker beat

# 等待 API 健康检查通过
echo -e "\n${YELLOW}Waiting for API to be healthy...${NC}"
for i in {1..60}; do
    if ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "\n${GREEN}✓ API is healthy${NC}"
        break
    fi
    echo -n "."
    sleep 1
    if [ "$i" -eq 60 ]; then
        echo -e "\n${RED}✗ API failed to start within 60 seconds${NC}"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 种子数据（如指定）
# ---------------------------------------------------------------------------
if [ "$SEED" = true ]; then
    echo -e "\n${YELLOW}Seeding database...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api python scripts/seed_data.py
    echo -e "${GREEN}✓ Database seeded${NC}"
fi

# ---------------------------------------------------------------------------
# 启动前端（如未指定特定服务）
# ---------------------------------------------------------------------------
if [ -z "$SERVICES" ] || echo "$SERVICES" | grep -q "ui"; then
    echo -e "\n${YELLOW}Starting frontend UI...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d ui
    echo -e "${GREEN}✓ UI started${NC}"
fi

# ---------------------------------------------------------------------------
# 显示服务状态
# ---------------------------------------------------------------------------
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}  NEXUS is running!                     ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "  ${GREEN}API:${NC}        http://localhost:${API_PORT:-8765}"
echo -e "  ${GREEN}API Docs:${NC}   http://localhost:${API_PORT:-8765}/docs"
echo -e "  ${GREEN}UI:${NC}         http://localhost:${UI_PORT:-5173}"
echo -e "  ${GREEN}MinIO:${NC}      http://localhost:${MINIO_CONSOLE_PORT:-9001}"
echo -e "  ${GREEN}LiteLLM:${NC}    http://localhost:${LITELLM_PORT:-4000}"
echo -e "  ${GREEN}PostgreSQL:${NC} localhost:${POSTGRES_PORT:-5432}"
echo -e "  ${GREEN}Redis:${NC}      localhost:${REDIS_PORT:-6379}"
echo ""
echo -e "  ${YELLOW}Useful commands:${NC}"
echo -e "    View logs:     ${COMPOSE_CMD} logs -f api"
echo -e "    Stop all:      ${COMPOSE_CMD} down"
echo -e "    Restart API:   ${COMPOSE_CMD} restart api"
echo ""

# ---------------------------------------------------------------------------
# 跟随日志（如指定）
# ---------------------------------------------------------------------------
if [ "$LOGS" = true ]; then
    echo -e "${YELLOW}Following logs (Ctrl+C to exit)...${NC}\n"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" logs -f
fi
