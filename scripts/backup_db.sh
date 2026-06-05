#!/bin/bash
# NEXUS Database Backup — 自动每日备份 + 30天保留
set -e
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
docker compose exec -T postgres pg_dump -U nexus nexus > "$BACKUP_DIR/nexus_$TIMESTAMP.sql"
echo "Backup: nexus_$TIMESTAMP.sql ($(wc -c < "$BACKUP_DIR/nexus_$TIMESTAMP.sql") bytes)"
find "$BACKUP_DIR" -name "nexus_*.sql" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
echo "Cleanup: removed backups older than $RETENTION_DAYS days"
