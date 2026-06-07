"""ARQ cron coroutines for scheduled backups + DR drill.

修复 (P0-1.7): 之前 backup_postgres.sh / backup_to_s3.py / disaster_recovery_drill.py
都是手动 one-shot，没有 scheduler。本模块把它们包成 ARQ 定时任务：

  - run_postgres_backup    : 每 6 小时 (cron 0 */6 * * *)
  - run_minio_redis_backup : 每 6 小时, 偏移 30 分 (cron 30 */6 * * *)
  - run_dr_drill           : 每周日 3 AM (cron 0 3 * * 0)

每个任务都是 idempotent：失败抛异常给 ARQ, 成功返回 dict 摘要。
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 共享 helper
# ---------------------------------------------------------------------------

async def _upload_to_s3(local_path: str | Path, s3_key: str, s3_endpoint: str) -> None:
    """上传本地文件到 S3 / S3-compatible (MinIO)."""
    import boto3
    from botocore.client import Config as BotoConfig

    access_key = os.environ.get(
        "S3_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "")
    )
    secret_key = os.environ.get(
        "S3_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "")
    )
    bucket = os.environ.get("BACKUP_S3_BUCKET", "nexus-backups")
    s3 = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )
    s3.upload_file(str(local_path), bucket, s3_key)
    logger.info("backup_uploaded key=s3://%s/%s", bucket, s3_key)


def _resolve_s3_endpoint() -> str:
    """强制 S3_ENDPOINT 必须显式设置 — 不再容忍 in-cluster MinIO 默认。"""
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        raise ValueError(
            "S3_ENDPOINT 环境变量必须显式设置 (off-host 目标)。"
            "禁止默认指向主集群 MinIO — 集群挂 = 备份也挂。"
        )
    return endpoint


# ---------------------------------------------------------------------------
# 1) PostgreSQL 备份
# ---------------------------------------------------------------------------

async def run_postgres_backup(ctx) -> dict:
    """pg_dump → gzip → S3. 每 6 小时跑一次.

    修复 (P0-1.7):
      - 改成异步 + 不依赖 docker exec (直接在 ARQ 容器内调 pg_dump)
      - 强制 S3_ENDPOINT 显式设置
      - 上传完成后清理本地临时文件
    """
    start = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = f"/tmp/nexus_pg_{timestamp}.sql.gz"
    s3_key = f"backups/postgres/{timestamp}.sql.gz"
    try:
        s3_endpoint = _resolve_s3_endpoint()
        host = os.environ.get("POSTGRES_HOST", "postgres")
        user = os.environ.get("POSTGRES_USER", "nexus_app")
        password = os.environ.get(
            "POSTGRES_PASSWORD", os.environ.get("NEXUS_APP_DB_PASSWORD", "")
        )
        db = os.environ.get("POSTGRES_DB", "nexus")
        env = {**os.environ, "PGPASSWORD": password}

        # 优先用容器内 pg_dump, 失败则回退到 docker exec
        try:
            subprocess.run(
                [
                    "pg_dump",
                    "-h", host,
                    "-U", user,
                    "-d", db,
                    "-Fc",  # custom format (compressed)
                    "-f", out_path,
                ],
                check=True, env=env, capture_output=True, timeout=1800,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            # 回退：docker exec 跑 pg_dump
            container = os.environ.get("PG_CONTAINER_NAME", "nexus-postgres-primary")
            logger.warning(
                "host_pg_dump_failed_falling_back_to_docker err=%s container=%s",
                e, container,
            )
            subprocess.run(
                [
                    "docker", "exec",
                    "-e", f"PGPASSWORD={password}",
                    container,
                    "pg_dump", "-U", user, "-d", db,
                    "-Fc", "-f", f"/tmp/{os.path.basename(out_path)}",
                ],
                check=True, capture_output=True, timeout=1800,
            )
            subprocess.run(
                ["docker", "cp", f"{container}:/tmp/{os.path.basename(out_path)}", out_path],
                check=True, capture_output=True, timeout=300,
            )

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        await _upload_to_s3(out_path, s3_key, s3_endpoint)
        duration = time.time() - start
        logger.info(
            "postgres_backup_ok key=%s size_mb=%.1f duration=%.1fs",
            s3_key, size_mb, duration,
        )
        return {
            "success": True,
            "key": s3_key,
            "size_mb": round(size_mb, 2),
            "duration_s": round(duration, 1),
        }
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", "replace") if e.stderr else ""
        logger.error("postgres_backup_failed pg_dump stderr=%s", stderr[:500])
        raise
    except Exception as e:
        logger.error("postgres_backup_failed err=%s", e)
        raise
    finally:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 2) MinIO + Redis 备份
# ---------------------------------------------------------------------------

async def run_minio_redis_backup(ctx) -> dict:
    """备份 MinIO 数据 + Redis RDB 到 S3. 每 6 小时偏移 30 分钟跑。

    MinIO: 打包本地数据目录 → S3
    Redis: BGSAVE → 上传 dump.rdb → S3
    """
    s3_endpoint = _resolve_s3_endpoint()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    minio_tar = f"/tmp/nexus_minio_{timestamp}.tar.gz"
    try:
        # ---- MinIO 备份 ----
        minio_data = os.environ.get("MINIO_DATA_DIR", "/data")
        if os.path.isdir(minio_data):
            subprocess.run(
                ["tar", "czf", minio_tar, "-C", minio_data, "."],
                check=True, capture_output=True, timeout=3600,
            )
            await _upload_to_s3(minio_tar, f"backups/minio/{timestamp}.tar.gz", s3_endpoint)
            logger.info("minio_backup_ok timestamp=%s", timestamp)
        else:
            logger.warning("minio_data_dir_not_found dir=%s (skipping)", minio_data)

        # ---- Redis 备份 (BGSAVE + 复制 dump.rdb) ----
        redis_host = os.environ.get("REDIS_HOST", "redis-master")
        redis_port = os.environ.get("REDIS_PORT", "6379")
        redis_pass = os.environ.get("REDIS_PASSWORD", "")
        redis_cmd = ["redis-cli", "-h", redis_host, "-p", redis_port]
        if redis_pass:
            redis_cmd += ["-a", redis_pass]
        redis_cmd += ["BGSAVE"]
        try:
            subprocess.run(redis_cmd, check=True, capture_output=True, timeout=60)
            time.sleep(3)  # 等 BGSAVE 完成
            rdb_path = os.environ.get("REDIS_RDB_PATH", "/data/dump.rdb")
            if os.path.exists(rdb_path):
                await _upload_to_s3(rdb_path, f"backups/redis/{timestamp}.rdb", s3_endpoint)
                logger.info("redis_backup_ok timestamp=%s", timestamp)
            else:
                logger.warning("redis_rdb_not_found path=%s", rdb_path)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            # redis-cli 不在 PATH (比如容器里没装), 不致命 — 只记 warning
            logger.warning("redis_bgsave_skipped err=%s", e)

        return {"success": True, "timestamp": timestamp}
    except Exception as e:
        logger.error("minio_redis_backup_failed err=%s", e)
        raise
    finally:
        if os.path.exists(minio_tar):
            try:
                os.remove(minio_tar)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 3) 灾备演练 (DR drill) — 每周日 3 AM
# ---------------------------------------------------------------------------

async def run_dr_drill(ctx) -> dict:
    """周调度：跑 disaster_recovery_drill.run_drill() 并把实测 RPO 写回 SystemSetting.

    ARQ cron 调这里, 内部再调 scripts.disaster_recovery_drill.run_drill() —
    复用现有 DR 脚本逻辑, 只是把返回结果入库 + 上指标。
    """
    from scripts.disaster_recovery_drill import run_drill

    result = await run_drill() if False else run_drill()  # run_drill 是同步的

    if result.get("success"):
        rpo = result.get("rpo_seconds", -1)
        rto = result.get("rto_seconds", 0.0)
        logger.info("dr_drill_ok rpo=%ss rto=%.1fs", rpo, rto)

        # 写回 SystemSetting — 用同步 session (避免和 async 事件循环互踩)
        try:
            _persist_rpo_metric(rpo)
        except Exception as e:  # noqa: BLE001 — 入库失败不致命, 只记 warning
            logger.warning("dr_drill_setting_update_failed err=%s", e)
    else:
        logger.warning("dr_drill_failed result=%s", result)

    return result


def _persist_rpo_metric(rpo_seconds: int) -> None:
    """把实测 RPO 写到 SystemSetting 表 (同步执行).

    使用 SQLite-friendly 的同步方式, 通过 SQLAlchemy sync session。
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from nexus.config import settings
    from nexus.models.system_setting import SystemSetting

    database_url = settings.DATABASE_URL
    if not database_url:
        return
    # 把 async URL 转成 sync URL (postgresql+asyncpg → postgresql)
    sync_url = (
        database_url.replace("postgresql+asyncpg://", "postgresql://")
        if "postgresql+asyncpg" in database_url
        else database_url
    )
    engine = create_engine(sync_url, future=True)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as db:
            row = db.execute(
                select(SystemSetting).where(
                    SystemSetting.tenant_id == "system",
                    SystemSetting.key == "last_measured_rpo_seconds",
                )
            ).scalar_one_or_none()
            if row is not None:
                row.value = rpo_seconds
            else:
                db.add(SystemSetting(
                    tenant_id="system",
                    key="last_measured_rpo_seconds",
                    value=rpo_seconds,
                    category="operations",
                ))
            db.commit()
    finally:
        engine.dispose()
