"""Off-host backup script: pg_dump → gzip → S3/MinIO push + 30 day retention.

修复 (S5 收尾): 之前 backup_postgres.sh 只把 .sql.gz 写到容器本地 ./backups/，
容器挂了备份就没了。现在推一份到 S3 (MinIO) 异地保留，30 天自动清理。

修复 (P0-1.7): S3_ENDPOINT 不再有 MinIO 默认值 — 必须显式设置，
强制 operator 指向 off-host S3，避免主集群和备份同生共死。

用法:
    python scripts/backup_to_s3.py

环境变量 (无 S3_ENDPOINT 默认值, 必须显式指定 off-host 目标):
    DATABASE_URL    (默认: postgresql://nexus:nexus_test_pwd@postgres:5432/nexus)
    S3_ENDPOINT     (REQUIRED, e.g. https://s3.amazonaws.com — 必须 off-host)
    S3_ACCESS_KEY   (默认: nexus)
    S3_SECRET_KEY   (默认: nexus-secret-key)
    S3_BUCKET       (默认: nexus-backups)
    BACKUP_PREFIX   (默认: postgres/)
    RETENTION_DAYS  (默认: 30)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 依赖：boto3 (S3 SDK)。开发环境 requirements.txt 已有。
try:
    import boto3
    from botocore.client import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    logger.error("需要 boto3 库: pip install boto3")
    sys.exit(1)


DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://nexus:nexus_test_pwd@postgres:5432/nexus"
)
# 修复 (P0-1.7): S3_ENDPOINT 不再默认指向 nexus-minio (主集群里的 MinIO)。
# 必须显式设置 off-host 目标 (S3 / OSS / COS / 远端 MinIO cluster)，
# 否则主集群故障 = 数据 + 备份同时丢失。
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
if not S3_ENDPOINT:
    raise ValueError(
        "S3_ENDPOINT 环境变量必须显式设置 (off-host 目标, e.g. https://s3.amazonaws.com)。"
        "禁止默认指向主集群 MinIO (http://nexus-minio:9000) — 集群挂 = 备份也挂。"
    )
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "nexus")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "nexus-secret-key")
S3_BUCKET = os.environ.get("S3_BUCKET", "nexus-backups")
BACKUP_PREFIX = os.environ.get("BACKUP_PREFIX", "postgres/")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


def _parse_db_url(url: str) -> dict:
    """解析 postgresql://user:pass@host:port/dbname 格式."""
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"仅支持 postgresql:// 协议，得到 {u.scheme}://")
    return {
        "user": u.username or "nexus",
        "password": u.password or "",
        "host": u.hostname or "postgres",
        "port": u.port or 5432,
        "dbname": (u.path or "/").lstrip("/") or "nexus",
    }


def pg_dump_compress() -> Path:
    """跑 pg_dump 用 docker exec (容器内路径)，gzip 到本地 temp 文件.

    Returns:
        Path to .sql.gz file
    """
    db = _parse_db_url(DATABASE_URL)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path("./backups/postgres")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nexus_{timestamp}.sql.gz"

    # 容器名（pg_dump 在容器内跑）
    container = os.environ.get("PG_CONTAINER_NAME", "nexus-postgres-primary")
    # 用 docker exec 在容器内跑 pg_dump → stdout → gzip
    cmd = [
        "docker", "exec",
        "-e", f"PGPASSWORD={db['password']}",
        container,
        "pg_dump",
        "-U", db["user"],
        "-d", db["dbname"],
        "--format=plain",
        "--no-owner",
        "--no-privileges",
    ]
    logger.info("pg_dump 启动: %s", " ".join(cmd))
    try:
        # 修复 (DR 收尾)：用 Python gzip 压缩 (跨平台) — 不依赖 gunzip
        import gzip as _gzip
        dump_proc = subprocess.run(cmd, capture_output=True, check=True)
        with _gzip.open(out_path, "wt", encoding="utf-8", compresslevel=6) as f:
            f.write(dump_proc.stdout.decode("utf-8", errors="replace"))
    except subprocess.CalledProcessError as e:
        logger.error("pg_dump 失败: stderr=%s", e.stderr.decode("utf-8", "replace"))
        raise

    size_mb = out_path.stat().st_size / 1024 / 1024
    logger.info("备份完成: %s (%.2f MB)", out_path, size_mb)
    return out_path


def s3_client():
    """构造 boto3 S3 客户端 (S3v4 签名，MinIO 兼容)."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
        region_name="us-east-1",  # MinIO 不在乎
    )


def ensure_bucket(s3) -> None:
    """创建桶（如果不存在）."""
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        logger.info("桶已存在: %s", S3_BUCKET)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            logger.info("桶不存在，创建: %s", S3_BUCKET)
            s3.create_bucket(Bucket=S3_BUCKET)
        else:
            raise


def upload_backup(s3, local_path: Path) -> str:
    """上传 .sql.gz 到 S3 (异地保留), 返回 s3 key."""
    s3_key = f"{BACKUP_PREFIX}{local_path.name}"
    logger.info("上传到 s3://%s/%s", S3_BUCKET, s3_key)
    s3.upload_file(
        Filename=str(local_path),
        Bucket=S3_BUCKET,
        Key=s3_key,
        # MinIO 单节点默认不加密；分布式模式会用 erasure coding
        ExtraArgs={"ContentType": "application/gzip"},
    )
    return s3_key


def cleanup_old_backups(s3) -> int:
    """删 RETENTION_DAYS 天前的备份 (S3 lifecycle 也可配但脚本兜底)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    cutoff_iso = cutoff.isoformat()
    deleted = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=BACKUP_PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                logger.info("删除过期: %s (mtime=%s)", obj["Key"], obj["LastModified"])
                s3.delete_object(Bucket=S3_BUCKET, Key=obj["Key"])
                deleted += 1
    return deleted


def list_recent_backups(s3, limit: int = 5) -> None:
    """列最近 N 个备份 (健康检查 / 总结)."""
    paginator = s3.get_paginator("list_objects_v2")
    items = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=BACKUP_PREFIX):
        for obj in page.get("Contents", []):
            items.append(obj)
    items.sort(key=lambda x: x["LastModified"], reverse=True)
    logger.info("最近 %d 个备份 (共 %d):", limit, len(items))
    for obj in items[:limit]:
        size_mb = obj.get("Size", 0) / 1024 / 1024
        logger.info(
            "  %s | %.1f MB | %s",
            obj["Key"], size_mb, obj["LastModified"].isoformat(),
        )


def main() -> int:
    logger.info("=" * 60)
    logger.info("NEXUS off-host 备份 (PostgreSQL → MinIO/S3)")
    logger.info("=" * 60)

    try:
        s3 = s3_client()
        ensure_bucket(s3)

        # 1. 备份
        local = pg_dump_compress()

        # 2. 上传
        s3_key = upload_backup(s3, local)

        # 3. 清理过期
        deleted = cleanup_old_backups(s3)

        # 4. 报告
        list_recent_backups(s3)

        logger.info("=" * 60)
        logger.info("备份成功: s3://%s/%s", S3_BUCKET, s3_key)
        logger.info("清理 %d 个过期备份 (保留 %d 天)", deleted, RETENTION_DAYS)
        logger.info("=" * 60)
        return 0
    except Exception as e:
        logger.exception("备份失败: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
