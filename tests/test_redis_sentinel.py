"""S1-2: Redis Sentinel 真实客户端测试.

测试 _resolve_master_via_sentinel 的逻辑路径：
- 单节点模式：直接用 REDIS_URL
- 哨兵模式：通过 Sentinel.discover_master 实时发现
- 哨兵发现失败：fallback 到默认 ('redis-master', 6379)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nexus.jobs.pool import _resolve_master_via_sentinel


# ---------------------------------------------------------------------------
# 单节点模式
# ---------------------------------------------------------------------------


class TestSingleNodeMode:
    """单节点模式（USE_REDIS_SENTINEL=false）."""

    @pytest.mark.asyncio
    async def test_single_node_default_url(self):
        """默认 REDIS_URL=redis://localhost:6379/0 → (localhost, 6379)."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = False
        mock_settings.REDIS_SENTINEL_HOSTS = ""
        mock_settings.REDIS_URL = "redis://localhost:6379/0"

        with patch("nexus.jobs.pool.settings", mock_settings):
            host, port = await _resolve_master_via_sentinel()
        assert host == "localhost"
        assert port == 6379

    @pytest.mark.asyncio
    async def test_single_node_with_password_in_url(self):
        """URL 里有密码 → host/port 解析对，密码从 settings 读."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = False
        mock_settings.REDIS_SENTINEL_HOSTS = ""
        mock_settings.REDIS_URL = "redis://:secret@redis.internal:6380/2"

        with patch("nexus.jobs.pool.settings", mock_settings):
            host, port = await _resolve_master_via_sentinel()
        assert host == "redis.internal"
        assert port == 6380


# ---------------------------------------------------------------------------
# 哨兵模式
# ---------------------------------------------------------------------------


class TestSentinelMode:
    """哨兵模式（USE_REDIS_SENTINEL=true）— 真实 Sentinel 客户端."""

    @pytest.mark.asyncio
    async def test_sentinel_discovers_master_successfully(self):
        """Sentinel.discover_master() 返回 ('10.0.0.5', 6379) → 直接用."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = True
        mock_settings.REDIS_SENTINEL_HOSTS = "sentinel-1:26379,sentinel-2:26380,sentinel-3:26381"
        mock_settings.REDIS_SENTINEL_MASTER = "mymaster"
        mock_settings.REDIS_PASSWORD = "secret"

        # 模拟 Sentinel.discover_master 返回 master (host, port)
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.discover_master = AsyncMock(
            return_value=("10.0.0.5", 6379)
        )

        with patch("nexus.jobs.pool.settings", mock_settings), \
             patch("nexus.jobs.pool.Sentinel", return_value=mock_sentinel_instance):
            host, port = await _resolve_master_via_sentinel()

        # 验证：返回的 master 来自 Sentinel，不是硬编码
        assert host == "10.0.0.5"
        assert port == 6379
        # 验证：discover_master 真的被调了
        mock_sentinel_instance.discover_master.assert_awaited_once_with("mymaster")

    @pytest.mark.asyncio
    async def test_sentinel_discovery_failure_falls_back_to_redis_master(self):
        """Sentinel 不可用时 fallback 到 ('redis-master', 6379) — 不应抛."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = True
        mock_settings.REDIS_SENTINEL_HOSTS = "sentinel-1:26379"
        mock_settings.REDIS_SENTINEL_MASTER = "mymaster"
        mock_settings.REDIS_PASSWORD = "secret"

        # 模拟 discover_master 抛连接超时
        mock_sentinel_instance = MagicMock()
        mock_sentinel_instance.discover_master = AsyncMock(
            side_effect=ConnectionError("all sentinels unreachable")
        )

        with patch("nexus.jobs.pool.settings", mock_settings), \
             patch("nexus.jobs.pool.Sentinel", return_value=mock_sentinel_instance):
            host, port = await _resolve_master_via_sentinel()

        # fallback 行为：返默认 master 名
        assert host == "redis-master"
        assert port == 6379

    @pytest.mark.asyncio
    async def test_sentinel_handles_multiple_hosts(self):
        """多个 sentinel host 逗号分隔 → 全部传给 Sentinel()."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = True
        mock_settings.REDIS_SENTINEL_HOSTS = "s1:26379,s2:26379,s3:26379"
        mock_settings.REDIS_SENTINEL_MASTER = "mymaster"
        mock_settings.REDIS_PASSWORD = "secret"

        sentinel_constructor_calls = []

        def sentinel_constructor(sentinels, **kwargs):
            sentinel_constructor_calls.append(sentinels)
            mock_instance = MagicMock()
            mock_instance.discover_master = AsyncMock(return_value=("1.2.3.4", 6379))
            return mock_instance

        with patch("nexus.jobs.pool.settings", mock_settings), \
             patch("nexus.jobs.pool.Sentinel", side_effect=sentinel_constructor):
            await _resolve_master_via_sentinel()

        # 验证：3 个 sentinel host 全部传给了 Sentinel 构造函数
        assert len(sentinel_constructor_calls) == 1
        sentinels_arg = sentinel_constructor_calls[0]
        assert sentinels_arg == [
            ("s1", 26379),
            ("s2", 26379),
            ("s3", 26379),
        ]

    @pytest.mark.asyncio
    async def test_sentinel_handles_default_port_in_host(self):
        """sentinel-1 没写 port → 默认 26379."""
        mock_settings = MagicMock()
        mock_settings.use_redis_sentinel = True
        mock_settings.REDIS_SENTINEL_HOSTS = "sentinel-1,sentinel-2:26380"
        mock_settings.REDIS_SENTINEL_MASTER = "mymaster"
        mock_settings.REDIS_PASSWORD = "secret"

        sentinel_constructor_calls = []

        def sentinel_constructor(sentinels, **kwargs):
            sentinel_constructor_calls.append(sentinels)
            mock_instance = MagicMock()
            mock_instance.discover_master = AsyncMock(return_value=("1.2.3.4", 6379))
            return mock_instance

        with patch("nexus.jobs.pool.settings", mock_settings), \
             patch("nexus.jobs.pool.Sentinel", side_effect=sentinel_constructor):
            await _resolve_master_via_sentinel()

        sentinels_arg = sentinel_constructor_calls[0]
        assert sentinels_arg == [
            ("sentinel-1", 26379),  # 默认 port
            ("sentinel-2", 26380),
        ]
