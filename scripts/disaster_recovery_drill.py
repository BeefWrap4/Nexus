"""灾备演练脚本：从 S3 备份恢复 PostgreSQL.

修复 (S5 收尾)：之前没有任何脚本能验证"备份能恢复"。
现在跑此脚本会：
1. 从 S3 (MinIO) 下载最新备份
2. 启动干净的 postgres 容器
3. 把 .sql.gz 灌进去
4. 跑 SELECT count(*) 验证表存在
5. 报告 RTO (恢复时间) 和 RPO (数据丢失窗口)

用法:
    python scripts/disaster_recovery_drill.py

环境变量:
    S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, BACKUP_PREFIX
    同 backup_to_s3.py
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 修复 (DR 收尾 2): 自动从仓库根目录 .env 加载 S3 凭据 — DR 演练时
# 不再强制要求手动 export 环境变量。两遍扫描：第一遍收所有 KEY=VAL，
# 第二遍解析 ${VAR} 引用 (因为 S3_ACCESS_KEY=${MINIO_ROOT_USER} 这种)。
# 占位符 <...> 跳过。
try:
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        _pairs: dict[str, str] = {}
        for _line in _env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            _pairs[_k.strip()] = _v.strip()
        # 解析 ${VAR} 引用 (只支持简单形如 ${VAR}, 不支持嵌套)
        import re as _re
        for _k, _v in list(_pairs.items()):
            _m = _re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)\}", _v)
            if _m and _m.group(1) in _pairs:
                _v = _pairs[_m.group(1)]
            if _v.startswith("<") and _v.endswith(">"):
                continue
            os.environ.setdefault(_k, _v)
except Exception:  # noqa: BLE001 — 任何 IO 错误都不致命
    pass

import boto3
from botocore.client import Config as BotoConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.environ.get("S3_BUCKET", "nexus-backups")
BACKUP_PREFIX = os.environ.get("BACKUP_PREFIX", "postgres/")
RESTORE_CONTAINER = os.environ.get("DR_RESTORE_CONTAINER", "nexus-dr-restore")
DR_PORT = os.environ.get("DR_PORT", "5444")
DR_USER = os.environ.get("DR_USER", "nexus")
DR_PASSWORD = os.environ.get("DR_PASSWORD", "dr_pwd")


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def download_latest_backup(s3) -> str:
    """下载 S3 桶里最新 .sql.gz 备份到本地."""
    paginator = s3.get_paginator("list_objects_v2")
    items = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=BACKUP_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".sql.gz"):
                items.append(obj)
    if not items:
        raise FileNotFoundError(f"S3 桶 {S3_BUCKET}/{BACKUP_PREFIX} 没找到 .sql.gz 备份")

    items.sort(key=lambda x: x["LastModified"], reverse=True)
    latest = items[0]
    local = f"/tmp/nexus_dr_{latest['Key'].split('/')[-1]}"
    logger.info("下载最新备份: s3://%s/%s -> %s", S3_BUCKET, latest["Key"], local)
    s3.download_file(Bucket=S3_BUCKET, Key=latest["Key"], Filename=local)
    logger.info("下载完成: %.2f MB", os.path.getsize(local) / 1024 / 1024)
    return local


def ensure_restore_container() -> None:
    """启动干净 postgres 容器（如不存在）."""
    # 检查是否已在
    try:
        subprocess.run(
            ["docker", "inspect", RESTORE_CONTAINER],
            capture_output=True, check=True,
        )
        logger.info("恢复容器已存在: %s", RESTORE_CONTAINER)
        return
    except subprocess.CalledProcessError:
        pass

    # 启动新容器
    logger.info("启动干净 postgres: %s", RESTORE_CONTAINER)
    subprocess.run([
        "docker", "run", "-d",
        "--name", RESTORE_CONTAINER,
        "-e", f"POSTGRES_USER={DR_USER}",
        "-e", f"POSTGRES_PASSWORD={DR_PASSWORD}",
        "-e", "POSTGRES_DB=nexus",
        "-p", f"{DR_PORT}:5432",
        "postgres:16-alpine",
    ], check=True, capture_output=True)

    # 等健康
    for _ in range(30):
        time.sleep(1)
        try:
            subprocess.run(
                ["docker", "exec", RESTORE_CONTAINER, "pg_isready", "-U", DR_USER],
                capture_output=True, check=True,
            )
            logger.info("postgres 健康: %s", RESTORE_CONTAINER)
            return
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("postgres 启动超时")


def restore_backup(backup_path: str) -> None:
    """用 Python gzip + docker exec psql 灌备份到恢复容器 (跨平台)."""
    import gzip
    logger.info("恢复中: %s -> %s", backup_path, RESTORE_CONTAINER)
    # 1. 读 .sql.gz 文件 (用 Python gzip 避免依赖 gunzip)
    with gzip.open(backup_path, "rt", encoding="utf-8") as f:
        sql_text = f.read()
    logger.info("读备份: %d 字符", len(sql_text))
    # 2. 用 docker exec 把 SQL 灌进 psql
    #    关键：psql -f - 从 stdin 读（避免命令行长度限制）
    proc = subprocess.run(
        ["docker", "exec", "-i", RESTORE_CONTAINER,
         "psql", "-U", DR_USER, "-d", "nexus", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=sql_text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        logger.error("psql stderr: %s", proc.stderr[:500] if proc.stderr else "(none)")
        logger.error("psql stdout: %s", proc.stdout[-500:] if proc.stdout else "(none)")
        raise RuntimeError(f"恢复失败 (rc={proc.returncode})")
    logger.info("恢复完成 (psql 输出最后一行: %s)",
                (proc.stdout.strip().splitlines() or [""])[-1])


def verify_restore() -> dict:
    """验证恢复：跑 SELECT count(*) 几个核心表."""
    tables = ["tenants", "users", "workflows", "wf_runs", "agents"]
    counts = {}
    for t in tables:
        out = subprocess.run(
            ["docker", "exec", RESTORE_CONTAINER,
             "psql", "-U", DR_USER, "-d", "nexus", "-tAc",
             f"SELECT count(*) FROM {t}"],
            capture_output=True, text=True, check=True,
        )
        counts[t] = int(out.stdout.strip() or "0")
    return counts


def cleanup() -> None:
    """删恢复容器（演练结束清理）."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", RESTORE_CONTAINER],
            capture_output=True, check=True,
        )
        logger.info("清理恢复容器: %s", RESTORE_CONTAINER)
    except subprocess.CalledProcessError:
        pass


def main() -> int:
    logger.info("=" * 70)
    logger.info("NEXUS 灾备演练 (DR Drill) — 从 S3 备份恢复 PostgreSQL")
    logger.info("=" * 70)

    t_start = time.time()
    try:
        s3 = s3_client()
        backup_path = download_latest_backup(s3)

        ensure_restore_container()
        restore_backup(backup_path)
        counts = verify_restore()
        t_elapsed = time.time() - t_start

        # 计算 RPO：从最近一次备份到现在的时间
        # 这里粗略算 (RPO 是从 data last written 到 backup taken 的时间，
        # 也就是 backup schedule 的周期 — 默认 24h 的话 RPO = 24h)
        rpo_seconds = 86400  # 假设每天备份

        logger.info("=" * 70)
        logger.info("灾备演练结果")
        logger.info("=" * 70)
        logger.info("RTO (恢复时间): %.1f 秒", t_elapsed)
        logger.info("RPO (数据丢失窗口): ≤ %d 秒 (%d 小时, 假设日备份)", rpo_seconds, rpo_seconds // 3600)
        logger.info("")
        logger.info("恢复后表行数:")
        for t, n in counts.items():
            marker = "✓" if n > 0 else "○"
            logger.info("  %s %-20s %d 行", marker, t, n)
        logger.info("=" * 70)
        logger.info("✓ 灾备演练成功")
        return 0
    except Exception as e:
        logger.exception("灾备演练失败: %s", e)
        return 1
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
