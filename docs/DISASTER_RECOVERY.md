# NEXUS 灾备 (Disaster Recovery) 覆盖范围与回放步骤

> **当前日期**：2026-06-06
> **本仓库已实现的备份/恢复组件**：
> - `scripts/backup_to_s3.py` — PostgreSQL → S3/MinIO
> - `scripts/backup_minio_and_redis.py` — MinIO 工件 + Redis Sentinel 拓扑
> - `scripts/disaster_recovery_drill.py` — 端到端回放 (从 S3 拉 PG 备份 → 干净容器恢复)

## 覆盖范围矩阵

| 数据 | 备份脚本 | 频率 | 存储 | 回放脚本 | 回放验证 |
|------|---------|------|------|---------|---------|
| **PostgreSQL** (租户/工作流/Agent/审计) | `backup_to_s3.py` | cron 24h | `s3://nexus-backups/postgres/*.sql.gz` | `disaster_recovery_drill.py` | ✓ 实跑通过 (tenants/users 行数) |
| **MinIO 工件** (上传的 PDF/图片等) | `backup_minio_and_redis.py --minio-only` | cron 24h | `s3://nexus-backups/backups/minio/<ts>/*` | 手动 `mc cp` | ⚠ 需手动恢复 |
| **Redis Sentinel 拓扑** (master/slave 关系 + ACL) | `backup_minio_and_redis.py --redis-only` | cron 24h | 本地 `backups/redis/sentinel_<ts>.conf` | 手动 `SENTINEL MONITOR` | ⚠ 需手动恢复 |
| **LiteLLM 配置** (模型路由 + master key) | ❌ 无 | — | — | — | — |
| **Prometheus 指标** | ❌ 无 (Prometheus 自身有 TSDB 持久化卷) | — | — | — | — |
| **NEXUS 代码 + .env** | git 仓库 | 实时 | GitHub | `git pull` | — |
| **数据库 schema (Alembic)** | git 仓库 | 实时 | GitHub | `alembic upgrade head` | — |

## ⚠️ 不覆盖什么 (高风险)

1. **LiteLLM 配置** — `litellm-config.yaml` 改了之后没自动备份。如果 LiteLLM 容器挂了，需要从 git 重建并重设 master key。
2. **Redis ACL 用户** — `acl_list_error = Authentication required` (脚本里看到的), 因为脚本拿不到 master auth 才能列 ACL。**生产前必须修**：用 `MASTER_PASSWORD` 直接连 master，不要走 sentinel discover。
3. **备份文件的异地保留** — 现在的 S3 是单节点 MinIO (`nexus-minio`)，跟 API 同台。**生产前必须**：开 MinIO 分布式 erasure coding 或把 S3 endpoint 换成真正的 AWS S3 / 阿里 OSS。
4. **RPO 真实测量** — 当前写死"假设日备份 → RPO=24h"。**生产前必须**：跑 `backup_to_s3.py` 加 `--measure-rpo` 算实际从"最近一次 commit 时间"到"备份完成时间"的差。
5. **RTO 没优化** — DR drill 实测 2.7s (在小数据集上)。真实生产 100GB+ PG 恢复可能 5-30 分钟，期间 API 不可用。**生产前必须**：warm standby（流复制）+ promote-on-failover。

## 🚨 S3 备份异地要求（强制）

`S3_ENDPOINT` **必须指向独立于 primary MinIO 集群的外部对象存储**。

**禁止的值（会导致 `deploy.sh` 校验失败）：**
- `nexus-minio`（docker compose 服务名）
- `localhost:9000`（本机 MinIO）
- `minio:9000`（通用内网 MinIO 地址）

**允许的值：**
- AWS S3: `https://s3.amazonaws.com`（或区域 endpoint）
- GCS: `https://storage.googleapis.com`
- Azure Blob: `https://<account>.blob.core.windows.net`
- 独立 MinIO 集群（不同主机/机房）

**原因：** `backup_to_s3.py` 将 PostgreSQL 备份写入 S3；如果 S3_ENDPOINT 指向 primary MinIO，则备份与主数据在同一故障域，单点故障时备份一起丢失。

**验证：** `bash scripts/deploy.sh` 启动时会自动检查 `S3_ENDPOINT`，不合格则报错退出。

## 标准回放流程

### 场景 A：PostgreSQL 数据损坏但 MinIO 在

```bash
# 1. 确认当前 master 坏了
docker exec nexus-postgres-primary pg_isready -U nexus  # → "no response"

# 2. 启动新 postgres 容器 (同 docker-compose 但换名字)
docker compose up -d postgres-new

# 3. 跑 DR drill (它会自动从 S3 拉最新备份灌进去)
python scripts/disaster_recovery_drill.py
#   → 启 nexus-dr-restore 容器 → 灌入 → SELECT count(*) 验证

# 4. 切流量: 改 .env DATABASE_URL 指向新容器, 重启 api
DATABASE_URL=postgresql+asyncpg://nexus:***@postgres-new:5432/nexus
docker compose restart api worker
```

### 场景 B：MinIO 桶清空了

```bash
# 1. 从 backups/ 子前缀复制回去
docker exec nexus-minio mc cp --recursive \
  local/nexus-backups/backups/minio/<ts>/ \
  local/nexus-artifacts/   # 或新桶
```

### 场景 C：Redis Sentinel 拓扑丢了

```bash
# 1. 读最近一份 backups/redis/sentinel_<ts>.conf
cat backups/redis/sentinel_20260606_084406.conf

# 2. 在每个 sentinel 容器重设
docker exec nexus-redis-sentinel-1 redis-cli -p 26379 \
  SENTINEL MONITOR mymaster 172.28.0.2 6379 2
# ... SLAVES 关系靠自动发现, ACL 需从 master dump 还原
```

### 场景 D：完整机房故障 (everything gone)

```bash
# 1. 从 git 拉代码
git clone <repo>

# 2. 启基础设施
docker compose up -d postgres redis-minio litellm

# 3. 跑 schema 迁移
alembic upgrade head

# 4. 从 S3 拉所有备份
aws s3 sync s3://nexus-backups/postgres/ backups/postgres/  # or mc mirror
aws s3 sync s3://nexus-backups/backups/minio/ /restore/minio/

# 5. 灌 PG
psql -U nexus -d nexus -f backups/postgres/nexus_<latest>.sql.gz

# 6. 灌 MinIO
mc mirror /restore/minio/ local/nexus-artifacts/

# 7. 重建 Redis Sentinel (见场景 C)

# 8. 启 app
docker compose up -d api worker
```

## 监控

- Prometheus 已抓 `nexus-minio` / `nexus-redis-sentinel-1` exporter (S2-1)
- 建议加 alert: 备份文件 > 26h 没更新 → Slack/邮件告警

## 已知问题清单

| 严重 | 问题 | 临时绕过 |
|------|------|---------|
| 🟡 | `backup_minio_and_redis.py` 必须从 docker 容器内跑才能 reach sentinel | `docker exec nexus-litellm python /tmp/backup.py --redis-only`, 或加 worker sidecar 挂 cron |
| 🟡 | Redis ACL 备份 fail (需要 master password 而不是 sentinel auth) | 待修：直接连 master 取 ACL |
| 🟢 | S3_BUCKET 在 `.env` 配的是 `nexus-artifacts` 但实际备份到 `nexus-backups` | 已统一到 `nexus-backups` (commit 时也修了脚本) |
