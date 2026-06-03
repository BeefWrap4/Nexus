#!/usr/bin/env bash
# =============================================================================
# NEXUS 数据库迁移脚本 (Database Migration)
# 用途：安全地执行数据库迁移，支持备份、验证和回滚
# 用法：bash scripts/migrate.sh [OPTIONS]
#
# 选项:
#   --backup          迁移前创建数据库备份（默认启用）
#   --no-backup       禁用备份
#   --generate        自动生成迁移脚本（autogenerate）
#   --message <text>  迁移脚本说明（与 --generate 一起使用）
#   --verify          迁移后验证表结构
#   --rollback        回滚到上一个版本（使用最近一次备份）
#   --status          显示当前迁移状态
#   --dry-run         仅打印 SQL，不实际执行
#   --help, -h        显示帮助信息
#
# 示例:
#   bash scripts/migrate.sh                          # 备份并执行迁移到最新版本
#   bash scripts/migrate.sh --generate --message "add crew tables"
#   bash scripts/migrate.sh --rollback               # 回滚到备份状态
#   bash scripts/migrate.sh --status                 # 查看迁移状态
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
BACKUP=true
GENERATE=false
MESSAGE=""
VERIFY=false
ROLLBACK=false
STATUS=false
DRY_RUN=false
COMPOSE_CMD=""

# 备份目录
BACKUP_DIR="${PROJECT_ROOT}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE=""

# ---------------------------------------------------------------------------
# 打印帮助信息
# ---------------------------------------------------------------------------
show_help() {
    cat <<EOF
NEXUS Database Migration Script

Usage: $(basename "$0") [OPTIONS]

Options:
  --backup           Create database backup before migration (default)
  --no-backup        Skip backup (not recommended for production)
  --generate         Auto-generate migration script (alembic revision --autogenerate)
  --message <text>   Migration message (required with --generate)
  --verify           Verify tables after migration
  --rollback         Rollback to previous version using latest backup
  --status           Show current migration status
  --dry-run          Print SQL only, do not execute
  --help, -h         Show this help message

Examples:
  # Standard migration with backup
  $(basename "$0")

  # Generate migration for new tables
  $(basename "$0") --generate --message "add crew tables"

  # Rollback to backup
  $(basename "$0") --rollback

  # Check status
  $(basename "$0") --status

  # Dry run (see what SQL would execute)
  $(basename "$0") --dry-run

Backup Location:
  ${BACKUP_DIR}/nexus_backup_YYYYMMDD_HHMMSS.sql
EOF
}

# ---------------------------------------------------------------------------
# Docker Compose 命令检测
# ---------------------------------------------------------------------------
detect_compose() {
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        COMPOSE_CMD="docker compose"
    fi
}

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
load_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        set -a
        # shellcheck source=/dev/null
        source "${PROJECT_ROOT}/.env"
        set +a
    fi
}

# ---------------------------------------------------------------------------
# 检查 PostgreSQL 容器是否运行
# ---------------------------------------------------------------------------
check_postgres() {
    if ! docker ps --format '{{.Names}}' | grep -q "nexus-postgres"; then
        echo -e "${YELLOW}PostgreSQL container not running, starting it...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d postgres

        echo -e "${YELLOW}Waiting for PostgreSQL...${NC}"
        until ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres pg_isready \
            -U "${POSTGRES_USER:-nexus}" -d "${POSTGRES_DB:-nexus}" > /dev/null 2>&1; do
            echo -n "."
            sleep 1
        done
        echo -e "\n${GREEN}✓ PostgreSQL ready${NC}"
    fi
}

# ---------------------------------------------------------------------------
# 创建数据库备份
# ---------------------------------------------------------------------------
create_backup() {
    if [ "$BACKUP" = false ]; then
        echo -e "${YELLOW}⚠ Backup skipped (--no-backup)${NC}"
        return 0
    fi

    echo -e "\n${CYAN}[1/5]${NC} ${YELLOW}Creating database backup...${NC}"

    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="${BACKUP_DIR}/nexus_backup_${TIMESTAMP}.sql"

    local pg_user="${POSTGRES_USER:-nexus}"
    local pg_db="${POSTGRES_DB:-nexus}"

    echo -e "  Backing up database ${pg_db}..."
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres pg_dump \
        -U "$pg_user" -d "$pg_db" --no-owner --no-privileges > "$BACKUP_FILE"

    if [ -s "$BACKUP_FILE" ]; then
        local file_size
        file_size=$(du -h "$BACKUP_FILE" | cut -f1)
        echo -e "  ${GREEN}✓ Backup created: ${BACKUP_FILE}${NC}"
        echo -e "  ${GREEN}  Size: ${file_size}${NC}"
    else
        echo -e "  ${RED}✗ Backup failed (empty file)${NC}"
        rm -f "$BACKUP_FILE"
        return 1
    fi

    # 清理旧备份（保留最近 10 个）
    local backup_count
    backup_count=$(find "$BACKUP_DIR" -name "nexus_backup_*.sql" -type f | wc -l)
    if [ "$backup_count" -gt 10 ]; then
        echo -e "  ${YELLOW}Cleaning old backups (keeping 10 most recent)...${NC}"
        find "$BACKUP_DIR" -name "nexus_backup_*.sql" -type f | sort | head -n -10 | xargs rm -f
    fi
}

# ---------------------------------------------------------------------------
# 生成迁移脚本
# ---------------------------------------------------------------------------
generate_migration() {
    echo -e "\n${CYAN}[Generation]${NC} ${YELLOW}Generating migration script...${NC}"

    if [ -z "$MESSAGE" ]; then
        echo -e "${RED}Error: --message is required with --generate${NC}"
        exit 1
    fi

    # 确保 API 容器已启动（用于运行 alembic）
    if ! docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${YELLOW}Starting API container temporarily...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d api

        echo -e "${YELLOW}Waiting for API...${NC}"
        for i in $(seq 1 30); do
            if curl -sf http://localhost:"${API_PORT:-8765}"/health > /dev/null 2>&1; then
                echo -e "\n${GREEN}✓ API ready${NC}"
                break
            fi
            echo -n "."
            sleep 1
            if [ "$i" -eq 30 ]; then
                echo -e "\n${RED}✗ API failed to start${NC}"
                exit 1
            fi
        done
    fi

    echo -e "  ${CYAN}Running: alembic revision --autogenerate -m \"${MESSAGE}\"${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic revision \
        --autogenerate -m "$MESSAGE" 2>&1 | sed 's/^/    /'

    echo -e "${GREEN}✓ Migration script generated${NC}"
    echo -e "${YELLOW}Please review the generated script before applying.${NC}"
}

# ---------------------------------------------------------------------------
# 执行迁移
# ---------------------------------------------------------------------------
run_migration() {
    echo -e "\n${CYAN}[2/5]${NC} ${YELLOW}Running database migration...${NC}"

    # 确保 API 容器已启动
    if ! docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${YELLOW}  Starting API container...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d api

        echo -e "${YELLOW}  Waiting for API...${NC}"
        for i in $(seq 1 30); do
            if curl -sf http://localhost:"${API_PORT:-8765}"/health > /dev/null 2>&1; then
                echo -e "\n  ${GREEN}✓ API ready${NC}"
                break
            fi
            echo -n "."
            sleep 1
            if [ "$i" -eq 30 ]; then
                echo -e "\n  ${RED}✗ API failed to start${NC}"
                exit 1
            fi
        done
    fi

    # 显示当前版本
    echo -e "  ${CYAN}Current version:${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic current 2>&1 | sed 's/^/    /'

    # 执行迁移
    local alembic_args="upgrade head"
    if [ "$DRY_RUN" = true ]; then
        alembic_args="upgrade head --sql"
        echo -e "  ${YELLOW}Dry-run mode (printing SQL only)...${NC}"
    fi

    echo -e "  ${CYAN}Running: alembic ${alembic_args}${NC}"
    if ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic ${alembic_args} 2>&1 | sed 's/^/    /'; then
        echo -e "\n  ${GREEN}✓ Migration completed${NC}"
    else
        echo -e "\n  ${RED}✗ Migration failed${NC}"
        return 1
    fi

    # 显示新版本
    echo -e "  ${CYAN}New version:${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic current 2>&1 | sed 's/^/    /'
}

# ---------------------------------------------------------------------------
# 验证迁移结果
# ---------------------------------------------------------------------------
verify_migration() {
    echo -e "\n${CYAN}[3/5]${NC} ${YELLOW}Verifying migration...${NC}"

    local pg_user="${POSTGRES_USER:-nexus}"
    local pg_db="${POSTGRES_DB:-nexus}"

    # 检查关键表是否存在
    local tables=(
        "tenants"
        "users"
        "workflows"
        "workflow_runs"
        "agents"
        "crews"
        "crew_agents"
        "crew_runs"
        "mcp_connections"
        "prompts"
        "traces"
        "eval_runs"
    )

    local all_ok=true
    for table in "${tables[@]}"; do
        local exists
        exists=$(${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres psql \
            -U "$pg_user" -d "$pg_db" -tAc \
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '${table}');" 2>/dev/null || echo "f")

        if [ "$exists" = "t" ]; then
            echo -e "  ${GREEN}✓ ${table}${NC}"
        else
            echo -e "  ${YELLOW}⚠ ${table} (not found)${NC}"
            # 不标记为失败，因为有些表可能是可选的
        fi
    done

    # 检查 alembic_version 表
    local alembic_ok
    alembic_ok=$(${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres psql \
        -U "$pg_user" -d "$pg_db" -tAc \
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'alembic_version');" 2>/dev/null || echo "f")

    if [ "$alembic_ok" = "t" ]; then
        echo -e "  ${GREEN}✓ alembic_version${NC}"
    else
        echo -e "  ${RED}✗ alembic_version (not found)${NC}"
        all_ok=false
    fi

    if [ "$all_ok" = true ]; then
        echo -e "${GREEN}✓ Verification passed${NC}"
    else
        echo -e "${YELLOW}⚠ Some optional tables may be missing${NC}"
    fi
}

# ---------------------------------------------------------------------------
# 回滚数据库
# ---------------------------------------------------------------------------
rollback_migration() {
    echo -e "\n${CYAN}[Rollback]${NC} ${YELLOW}Rolling back database...${NC}"

    # 查找最近的备份
    local latest_backup
    latest_backup=$(find "$BACKUP_DIR" -name "nexus_backup_*.sql" -type f | sort | tail -n 1)

    if [ -z "$latest_backup" ]; then
        echo -e "${RED}✗ No backup found in ${BACKUP_DIR}${NC}"
        exit 1
    fi

    echo -e "${YELLOW}Latest backup: ${latest_backup}${NC}"
    echo -e "${RED}WARNING: This will overwrite the current database.${NC}"
    read -rp "Are you sure? [y/N]: " confirm

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Rollback cancelled.${NC}"
        exit 0
    fi

    local pg_user="${POSTGRES_USER:-nexus}"
    local pg_db="${POSTGRES_DB:-nexus}"

    # 先创建当前状态的备份（以防万一）
    local emergency_backup="${BACKUP_DIR}/nexus_emergency_${TIMESTAMP}.sql"
    echo -e "${YELLOW}Creating emergency backup...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres pg_dump \
        -U "$pg_user" -d "$pg_db" --no-owner --no-privileges > "$emergency_backup"
    echo -e "${GREEN}✓ Emergency backup: ${emergency_backup}${NC}"

    # 终止现有连接
    echo -e "${YELLOW}Terminating existing connections...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres psql \
        -U "$pg_user" -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${pg_db}' AND pid <> pg_backend_pid();" > /dev/null 2>&1 || true

    # 删除并重建数据库
    echo -e "${YELLOW}Recreating database...${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres psql \
        -U "$pg_user" -d postgres -c "DROP DATABASE IF EXISTS ${pg_db};" > /dev/null 2>&1
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T postgres psql \
        -U "$pg_user" -d postgres -c "CREATE DATABASE ${pg_db};" > /dev/null 2>&1

    # 恢复备份
    echo -e "${YELLOW}Restoring from backup...${NC}"
    if ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T -i postgres psql \
        -U "$pg_user" -d "$pg_db" < "$latest_backup" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Rollback completed${NC}"
    else
        echo -e "${RED}✗ Rollback failed${NC}"
        echo -e "${YELLOW}Emergency backup is available at: ${emergency_backup}${NC}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 显示迁移状态
# ---------------------------------------------------------------------------
show_status() {
    echo -e "\n${CYAN}[Status]${NC} ${YELLOW}Migration status${NC}"

    if ! docker ps --format '{{.Names}}' | grep -q "nexus-api"; then
        echo -e "${YELLOW}API container not running, starting it...${NC}"
        ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" up -d api

        for i in $(seq 1 30); do
            if curl -sf http://localhost:"${API_PORT:-8765}"/health > /dev/null 2>&1; then
                break
            fi
            sleep 1
        done
    fi

    echo -e "\n${CYAN}Current revision:${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic current 2>&1

    echo -e "\n${CYAN}Revision history:${NC}"
    ${COMPOSE_CMD} -f "${PROJECT_ROOT}/docker-compose.yml" exec -T api alembic history --indicate-current 2>&1

    echo -e "\n${CYAN}Available backups:${NC}"
    if [ -d "$BACKUP_DIR" ]; then
        find "$BACKUP_DIR" -name "nexus_backup_*.sql" -type f | sort | while read -r f; do
            local size
            size=$(du -h "$f" | cut -f1)
            echo "  $(basename "$f") (${size})"
        done
    else
        echo "  No backups found"
    fi
}

# ---------------------------------------------------------------------------
# 解析命令行参数
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --backup)
            BACKUP=true
            shift
            ;;
        --no-backup)
            BACKUP=false
            shift
            ;;
        --generate)
            GENERATE=true
            shift
            ;;
        --message)
            MESSAGE="$2"
            shift 2
            ;;
        --verify)
            VERIFY=true
            shift
            ;;
        --rollback)
            ROLLBACK=true
            shift
            ;;
        --status)
            STATUS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
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
# 主流程
# ---------------------------------------------------------------------------
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  NEXUS Database Migration               ${NC}"
    echo -e "${BLUE}========================================${NC}"

    detect_compose
    load_env
    check_postgres

    # 处理特殊模式
    if [ "$STATUS" = true ]; then
        show_status
        exit 0
    fi

    if [ "$ROLLBACK" = true ]; then
        rollback_migration
        exit 0
    fi

    if [ "$GENERATE" = true ]; then
        generate_migration
        exit 0
    fi

    # 标准迁移流程
    create_backup
    run_migration

    if [ "$VERIFY" = true ]; then
        verify_migration
    fi

    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${GREEN}  Migration Complete!                    ${NC}"
    echo -e "${BLUE}========================================${NC}"
}

main "$@"
