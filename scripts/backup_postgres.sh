#!/bin/bash
# ============================================================================
# NEXUS PostgreSQL 自动备份脚本 (Linux/Unix 版本)
# ============================================================================
# 功能:
#   - 每日自动备份 PostgreSQL 数据库
#   - 支持增量备份和全量备份
#   - 自动清理过期备份(默认保留30天)
#   - 备份文件压缩(gzip)
#   - 详细的日志记录
#   - 备份验证(可选)
#
# 使用方法:
#   ./backup_postgres.sh [选项]
#
# 选项:
#   --full          执行全量备份(默认是增量)
#   --verify        备份后验证完整性
#   --retention=N   设置保留天数(默认30天)
#   --help          显示帮助信息
#
# 环境变量:
#   BACKUP_DIR      备份目录路径(默认: ./backups/postgres)
#   DB_HOST         数据库主机(默认: localhost)
#   DB_PORT         数据库端口(默认: 5432)
#   DB_NAME         数据库名称(默认: nexus)
#   DB_USER         数据库用户(默认: nexus)
#   DB_PASSWORD     数据库密码(从 .env 读取或使用 PGPASSWORD)
#   RETENTION_DAYS  备份保留天数(默认: 30)
#   LOG_FILE        日志文件路径(默认: ./logs/backup.log)
# ============================================================================

set -euo pipefail

# ==================== 配置部分 ====================
BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
# 修复 (S2-4): 默认 port 与 docker-compose 的 POSTGRES_PORT=5433 对齐，
# 否则每次都要手敲 DB_PORT=5433 才会连上。
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-nexus}"
DB_USER="${DB_USER:-nexus}"
# 修复 (S2-4): 默认走 docker exec（容器内有 pg_dump），避免依赖宿主有 pg_dump
# 设置 USE_HOST_PG_DUMP=1 强制走 host pg_dump 路径
USE_DOCKER_EXEC="${USE_DOCKER_EXEC:-1}"
PG_CONTAINER_NAME="${PG_CONTAINER_NAME:-nexus-postgres-primary}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
LOG_FILE="${LOG_FILE:-./logs/backup.log}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATE_STAMP=$(date +%Y-%m-%d)
BACKUP_FILE="nexus_${TIMESTAMP}.sql"
COMPRESSED_FILE="${BACKUP_FILE}.gz"

# 备份类型标志
FULL_BACKUP=false
VERIFY_BACKUP=false

# ==================== 函数定义 ====================

# 日志函数
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "$@"; }
log_error() { log "ERROR" "$@"; }

# 显示帮助信息
show_help() {
    cat <<EOF
NEXUS PostgreSQL 自动备份脚本

用法: $(basename "$0") [选项]

选项:
  --full          执行全量备份(默认是增量)
  --verify        备份后验证完整性
  --retention=N   设置保留天数(默认30天)
  --help          显示此帮助信息

环境变量:
  BACKUP_DIR       备份目录路径(默认: ./backups/postgres)
  DB_HOST          数据库主机(默认: localhost)
  DB_PORT          数据库端口(默认: 5433,匹配 docker-compose)
  DB_NAME          数据库名称(默认: nexus)
  DB_USER          数据库用户(默认: nexus)
  USE_DOCKER_EXEC  走 docker exec 模式(默认: 1,推荐)
  PG_CONTAINER_NAME Postgres 容器名(默认: nexus-postgres-primary)
  RETENTION_DAYS   备份保留天数(默认: 30)
  LOG_FILE         日志文件路径(默认: ./logs/backup.log)

示例:
  $(basename "$0")                          # 执行增量备份
  $(basename "$0") --full                   # 执行全量备份
  $(basename "$0") --full --verify          # 全量备份并验证
  $(basename "$0") --retention=60           # 保留60天备份
EOF
    exit 0
}

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."

    local deps=("gzip" "find" "date")
    # pg_dump 仅在 USE_DOCKER_EXEC=0 时才需要
    if [ "$USE_DOCKER_EXEC" != "1" ]; then
        deps+=("pg_dump")
    else
        # docker exec 模式：需要 docker 命令和 Postgres 容器在跑
        if ! command -v "docker" &> /dev/null; then
            log_error "缺少依赖: docker（USE_DOCKER_EXEC=1 需要）"
            exit 1
        fi
        if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${PG_CONTAINER_NAME}$"; then
            log_warn "Postgres 容器 ${PG_CONTAINER_NAME} 不在跑，备份会失败"
        fi
    fi

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            log_error "缺少依赖: $dep"
            exit 1
        fi
    done

    log_info "所有依赖检查通过"
}

# 创建备份目录
create_backup_dir() {
    if [ ! -d "$BACKUP_DIR" ]; then
        log_info "创建备份目录: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
        if [ $? -ne 0 ]; then
            log_error "无法创建备份目录: $BACKUP_DIR"
            exit 1
        fi
    fi
}

# 创建日志目录
create_log_dir() {
    local log_dir=$(dirname "$LOG_FILE")
    if [ ! -d "$log_dir" ]; then
        mkdir -p "$log_dir"
    fi
}

# 加载 .env 文件中的数据库密码
load_env() {
    if [ -f ".env" ]; then
        log_info "从 .env 文件加载配置..."
        export $(grep -v '^#' .env | grep -E '^(DB_|POSTGRES_)' | xargs)
    else
        log_warn ".env 文件不存在,使用默认配置或环境变量"
    fi
}

# 执行数据库备份
perform_backup() {
    log_info "开始备份数据库..."
    log_info "数据库: ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
    log_info "备份文件: ${BACKUP_DIR}/${COMPRESSED_FILE}"

    # 构建 pg_dump 命令（修复 S2-4：默认走 docker exec，避免依赖宿主有 pg_dump）
    local pg_dump_args="-U ${DB_USER} -d ${DB_NAME}"
    local dump_cmd

    if [ "$USE_DOCKER_EXEC" = "1" ]; then
        log_info "使用 docker exec 模式 (容器: ${PG_CONTAINER_NAME})"
        dump_cmd="docker exec -e PGPASSWORD=\"${DB_PASSWORD:-}\" ${PG_CONTAINER_NAME} pg_dump ${pg_dump_args}"
    else
        log_info "使用 host pg_dump 模式"
        export PGPASSWORD="${DB_PASSWORD:-}"
        dump_cmd="pg_dump -h ${DB_HOST} -p ${DB_PORT} ${pg_dump_args}"
    fi

    # 如果是全量备份,添加完整模式
    if [ "$FULL_BACKUP" = true ]; then
        log_info "执行全量备份..."
        dump_cmd="${dump_cmd} --format=custom --compress=9"
        BACKUP_FILE="nexus_${TIMESTAMP}.dump"
        COMPRESSED_FILE="${BACKUP_FILE}"
    else
        log_info "执行标准 SQL 备份..."
        dump_cmd="${dump_cmd} --format=plain --no-owner --no-privileges"
    fi

    # 执行备份
    log_info "执行命令: $dump_cmd"

    if [ "$FULL_BACKUP" = true ]; then
        # 自定义格式直接输出到文件
        eval "$dump_cmd > ${BACKUP_DIR}/${COMPRESSED_FILE}" 2>> "$LOG_FILE"
    else
        # SQL 格式需要压缩
        eval "$dump_cmd | gzip > ${BACKUP_DIR}/${COMPRESSED_FILE}" 2>> "$LOG_FILE"
    fi

    local exit_code=$?

    # 清除密码环境变量
    unset PGPASSWORD 2>/dev/null || true

    if [ $exit_code -eq 0 ]; then
        local file_size=$(du -h "${BACKUP_DIR}/${COMPRESSED_FILE}" | cut -f1)
        log_info "✓ 备份成功完成"
        log_info "备份文件大小: $file_size"
        return 0
    else
        log_error "✗ 备份失败,退出码: $exit_code"
        log_error "提示: 设置 USE_DOCKER_EXEC=0 强制走 host pg_dump，或检查 ${PG_CONTAINER_NAME} 是否在跑"
        return 1
    fi
}

# 验证备份文件
verify_backup() {
    if [ "$VERIFY_BACKUP" = false ]; then
        return 0
    fi
    
    log_info "验证备份文件完整性..."
    
    local backup_path="${BACKUP_DIR}/${COMPRESSED_FILE}"
    
    if [ ! -f "$backup_path" ]; then
        log_error "备份文件不存在: $backup_path"
        return 1
    fi
    
    # 检查文件大小
    local file_size=$(stat -f%z "$backup_path" 2>/dev/null || stat -c%s "$backup_path" 2>/dev/null)
    if [ "$file_size" -eq 0 ]; then
        log_error "备份文件为空"
        return 1
    fi
    
    # 对于 gzip 文件,测试解压
    if [[ "$COMPRESSED_FILE" == *.gz ]]; then
        if gzip -t "$backup_path" 2>/dev/null; then
            log_info "✓ GZIP 完整性检查通过"
        else
            log_error "✗ GZIP 完整性检查失败"
            return 1
        fi
    fi
    
    log_info "✓ 备份验证通过"
    return 0
}

# 清理过期备份
cleanup_old_backups() {
    log_info "清理 ${RETENTION_DAYS} 天前的旧备份..."
    
    local deleted_count=0
    
    # 查找并删除过期备份
    while IFS= read -r -d '' file; do
        log_info "删除过期备份: $(basename "$file")"
        rm -f "$file"
        ((deleted_count++))
    done < <(find "$BACKUP_DIR" -name "nexus_*.sql.gz" -o -name "nexus_*.dump" -mtime +${RETENTION_DAYS} -print0 2>/dev/null)
    
    if [ $deleted_count -gt 0 ]; then
        log_info "已删除 $deleted_count 个过期备份"
    else
        log_info "没有需要清理的过期备份"
    fi
}

# 发送通知(可选)
send_notification() {
    local status="$1"
    local message="$2"
    
    # 这里可以集成邮件、Slack、钉钉等通知
    # 示例: 发送邮件通知
    # echo "$message" | mail -s "NEXUS 备份${status}" admin@example.com
    
    log_info "通知: 备份${status} - $message"
}

# ==================== 主程序 ====================

main() {
    log_info "=========================================="
    log_info "NEXUS PostgreSQL 备份开始"
    log_info "=========================================="
    
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --full)
                FULL_BACKUP=true
                shift
                ;;
            --verify)
                VERIFY_BACKUP=true
                shift
                ;;
            --retention=*)
                RETENTION_DAYS="${1#*=}"
                shift
                ;;
            --help)
                show_help
                ;;
            *)
                log_error "未知参数: $1"
                show_help
                ;;
        esac
    done
    
    # 初始化
    create_log_dir
    load_env
    check_dependencies
    create_backup_dir
    
    # 执行备份
    if perform_backup; then
        # 验证备份
        if verify_backup; then
            # 清理旧备份
            cleanup_old_backups
            
            # 发送成功通知
            send_notification "成功" "备份文件: ${COMPRESSED_FILE}"
            
            log_info "=========================================="
            log_info "NEXUS PostgreSQL 备份完成 ✓"
            log_info "=========================================="
            exit 0
        else
            log_error "备份验证失败"
            send_notification "失败" "备份验证未通过"
            exit 1
        fi
    else
        log_error "备份执行失败"
        send_notification "失败" "备份过程出错"
        exit 1
    fi
}

# 执行主程序
main "$@"
