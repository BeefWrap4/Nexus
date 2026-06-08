#!/bin/sh
# Redis Sentinel Entrypoint with DNS wait + IP + password substitution
# 修复 (S1-2): 也替换 sentinel auth-pass 密码，从 REDIS_PASSWORD env 读
set -e

echo "Waiting for Redis master to be resolvable..."
MAX_RETRIES=30
RETRY_COUNT=0
MASTER_IP=""

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    MASTER_IP=$(getent hosts nexus-redis-master | awk '{print $1}')
    if [ -n "$MASTER_IP" ]; then
        echo "Redis master resolved to IP: $MASTER_IP"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Attempt $RETRY_COUNT/$MAX_RETRIES: Cannot resolve nexus-redis-master, retrying in 2s..."
    sleep 2
done

if [ -z "$MASTER_IP" ]; then
    echo "ERROR: Failed to resolve nexus-redis-master after $MAX_RETRIES attempts"
    exit 1
fi

# 修复 (S1-2): 哨兵配置文件需要 2 处替换：
# 1. nexus-redis-master → master IP（让 sentinel 能连到 master）
# 2. __REDIS_PASSWORD__ → 实际密码（避免硬编码泄漏的旧密码）
echo "Updating sentinel configuration (IP + auth-pass substitution)..."
if [ -z "${REDIS_PASSWORD:-}" ]; then
    echo "WARNING: REDIS_PASSWORD env not set, sentinel auth-pass will be empty"
    AUTH_PASS_VALUE=""
else
    AUTH_PASS_VALUE="$REDIS_PASSWORD"
fi

sed -e "s/nexus-redis-master/$MASTER_IP/g" \
    /usr/local/etc/redis/sentinel.conf > /tmp/sentinel-updated.conf

# 修复 (Phase 4.7): Redis 7.4.8 不接受空 auth-pass 指令
# 当 REDIS_PASSWORD 未设时, 直接删整行 sentinel auth-pass
if [ -z "${REDIS_PASSWORD:-}" ]; then
    echo "WARNING: REDIS_PASSWORD not set, removing sentinel auth-pass line"
    sed -i '/^sentinel auth-pass/d' /tmp/sentinel-updated.conf
else
    sed -i "s/__REDIS_PASSWORD__/$REDIS_PASSWORD/g" /tmp/sentinel-updated.conf
fi

echo "Starting Redis Sentinel..."
exec redis-sentinel /tmp/sentinel-updated.conf
