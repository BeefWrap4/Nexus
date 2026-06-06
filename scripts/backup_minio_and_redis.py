"""MinIO 工件 + Redis Sentinel 配置备份.

修复 (P1): 之前 backup_to_s3.py 只备份 PostgreSQL。
现在补两件事:
  1. MinIO 桶 (用户上传的 artifacts) → 同桶内复制到 backups/ 子前缀
  2. Redis Sentinel 拓扑 (SENTINEL MASTER + SLAVES + ACL) → 写 .conf

用法:
    python scripts/backup_minio_and_redis.py
    python scripts/backup_minio_and_redis.py --minio-only
    python scripts/backup_minio_and_redis.py --redis-only

环境变量:
    S3_ENDPOINT     (默认: http://nexus-minio:9000)
    S3_ACCESS_KEY   (默认: nexus)
    S3_SECRET_KEY   (默认: nexus-secret-key)
    S3_BUCKET       (默认: nexus-backups)
    REDIS_SENTINEL_HOSTS  (默认: nexus-redis-sentinel-1:26379,...)
    REDIS_SENTINEL_MASTER (默认: mymaster)
    REDIS_PASSWORD   (默认: 空)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 加载 .env (含 ${VAR} 解析) — 同 disaster_recovery_drill.py
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
        for _k, _v in _pairs.items():
            _m = re.fullmatch(r"\$\{([A-Z_][A-Z0-9_]*)\}", _v)
            if _m and _m.group(1) in _pairs:
                _v = _pairs[_m.group(1)]
            if _v.startswith("<") and _v.endswith(">"):
                continue
            os.environ.setdefault(_k, _v)
except Exception:
    pass

try:
    import boto3
    from botocore.client import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:
    logging.error("需要 boto3: pip install boto3")
    sys.exit(1)

try:
    import redis as redis_sync
    from redis.sentinel import Sentinel as SyncSentinel
except ImportError:
    logging.error("需要 redis: pip install redis")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://nexus-minio:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "nexus")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "nexus-secret-key")
S3_BUCKET = os.environ.get("S3_BUCKET", "nexus-backups")
REDIS_SENTINEL_HOSTS = os.environ.get(
    "REDIS_SENTINEL_HOSTS",
    "nexus-redis-sentinel-1:26379,nexus-redis-sentinel-2:26379,nexus-redis-sentinel-3:26379",
)
REDIS_SENTINEL_MASTER = os.environ.get("REDIS_SENTINEL_MASTER", "mymaster")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")


# ────────────────────────── MinIO 备份 ──────────────────────────

def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        region_name="us-east-1",
    )


def backup_minio_artifacts(s3) -> tuple[int, int]:
    """把所有非 backups/ 前缀的对象复制到 backups/minio/ 前缀下。

    Returns:
        (copied, skipped) — 复制成功的对象数 + 跳过的数 (已经在 backups/ 里)
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_prefix = f"backups/minio/{timestamp}/"
    copied = 0
    skipped = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET):
        for obj in page.get("Contents", []):
            src_key = obj["Key"]
            # 跳过已经在备份里的 (避免无限递归)
            if src_key.startswith("backups/"):
                skipped += 1
                continue
            dst_key = target_prefix + src_key
            try:
                copy_src = {"Bucket": S3_BUCKET, "Key": src_key}
                s3.copy_object(
                    Bucket=S3_BUCKET,
                    Key=dst_key,
                    CopySource=copy_src,
                    MetadataDirective="COPY",
                )
                copied += 1
                logger.info("复制: %s → %s (%d bytes)", src_key, dst_key, obj.get("Size", 0))
            except ClientError as e:
                logger.error("复制失败 %s: %s", src_key, e)

    logger.info("MinIO 备份完成: 复制 %d, 跳过 %d (在 backups/ 下)", copied, skipped)
    return copied, skipped


# ────────────────────────── Redis 配置备份 ──────────────────────────

def _parse_sentinel_hosts(s: str) -> list[tuple[str, int]]:
    out = []
    for entry in s.split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, _, port = entry.partition(":")
        out.append((host, int(port or 26379)))
    return out


def backup_redis_sentinel_config() -> Path:
    """抓取 Redis Sentinel 拓扑 + Master 关键配置 → 写 backups/redis/sentinel_<ts>.conf

    Returns:
        写入的 .conf 路径
    """
    sentinels = _parse_sentinel_hosts(REDIS_SENTINEL_HOSTS)
    sentinel_kwargs = {"password": REDIS_PASSWORD} if REDIS_PASSWORD else None
    sentinel = SyncSentinel(sentinels, socket_timeout=0.5, sentinel_kwargs=sentinel_kwargs)

    # 1. Master 拓扑
    master_info = None
    sentinel_hosts_status = []
    for host, port in sentinels:
        try:
            client = redis_sync.Redis(host=host, port=port, socket_timeout=0.5, decode_responses=True)
            sentinel_hosts_status.append((host, port, client.ping()))
        except Exception as e:
            sentinel_hosts_status.append((host, port, f"ERR: {e}"))

    try:
        master_info = sentinel.discover_master(REDIS_SENTINEL_MASTER)
    except Exception as e:
        logger.error("discover_master 失败: %s", e)

    # 2. Slave 列表
    try:
        client = redis_sync.Redis(
            host=sentinels[0][0], port=sentinels[0][1], socket_timeout=0.5, decode_responses=True
        )
        slaves_raw = client.execute_command("SENTINEL", "SLAVES", REDIS_SENTINEL_MASTER)
        slaves = [_parse_sentinel_record(s) for s in slaves_raw]
    except Exception as e:
        logger.warning("SENTINEL SLAVES 失败: %s", e)
        slaves = []

    # 3. Master 当前 config (持久化相关)
    master_config = {}
    if master_info:
        try:
            m = redis_sync.Redis(
                host=master_info[0], port=master_info[1],
                password=REDIS_PASSWORD or None, socket_timeout=0.5, decode_responses=True,
            )
            for k in ("appendonly", "save", "maxmemory-policy", "requirepass", "aclfile"):
                try:
                    master_config[k] = m.config_get(k)
                except Exception:
                    pass
            # ACL (用户列表, 含密码 hash)
            try:
                master_config["acl_list"] = m.acl_list()
            except Exception as e:
                master_config["acl_list_error"] = str(e)
        except Exception as e:
            logger.warning("连接 master 失败: %s", e)

    # 4. 写到 .conf
    # 修复 (P1): 写绝对路径 — 在容器内跑时, 相对路径会写到容器里看不到的 cwd
    out_dir = Path(os.environ.get("BACKUP_OUTPUT_DIR", str(Path.cwd()))) / "backups" / "redis"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"sentinel_{timestamp}.conf"
    lines = [
        f"# NEXUS Redis Sentinel 拓扑备份 @ {datetime.now(timezone.utc).isoformat()}",
        f"# master: {REDIS_SENTINEL_MASTER}",
        "",
        "[sentinel_hosts]",
    ]
    for host, port, status in sentinel_hosts_status:
        lines.append(f"  {host}:{port} = {status}")

    lines += [
        "",
        "[master]",
        f"  address = {master_info[0]}:{master_info[1]}" if master_info else "  address = UNKNOWN",
        "",
        "[slaves]",
    ]
    for s in slaves:
        lines.append(f"  - {s.get('name', '?')} @ {s.get('ip', '?')}:{s.get('port', '?')} (flags={s.get('flags', '?')})")

    lines += ["", "[master_config]"]
    for k, v in master_config.items():
        lines.append(f"  {k} = {v}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Redis Sentinel 配置备份: %s", out_path)
    return out_path


def _parse_sentinel_record(raw) -> dict:
    """SENTINEL SLAVES 返回的是 list of (key, value) pair, 转 dict."""
    d = {}
    for i in range(0, len(raw), 2):
        k = raw[i].decode() if isinstance(raw[i], bytes) else raw[i]
        v = raw[i + 1].decode() if isinstance(raw[i + 1], bytes) else raw[i + 1]
        d[k] = v
    return d


# ────────────────────────── main ──────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minio-only", action="store_true")
    ap.add_argument("--redis-only", action="store_true")
    args = ap.parse_args()

    do_minio = not args.redis_only
    do_redis = not args.minio_only

    logger.info("=" * 60)
    logger.info("NEXUS off-host 备份 (MinIO 工件 + Redis Sentinel 配置)")
    logger.info("=" * 60)

    try:
        if do_minio:
            s3 = s3_client()
            copied, skipped = backup_minio_artifacts(s3)
        if do_redis:
            backup_redis_sentinel_config()
        logger.info("=" * 60)
        logger.info("备份完成")
        return 0
    except Exception as e:
        logger.exception("备份失败: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
