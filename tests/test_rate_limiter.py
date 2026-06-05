"""速率限制器单元测试.

测试场景:
1. 正常请求（未超限）
2. 达到限制后拒绝（429错误）
3. 窗口过期后重置
4. 并发请求处理
5. 速率限制信息查询
6. 速率限制重置
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from nexus.security.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """创建Mock Redis客户端."""
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=MagicMock())
    return redis


@pytest.fixture
def rate_limiter(mock_redis):
    """创建RateLimiter实例."""
    return RateLimiter(mock_redis)


# ---------------------------------------------------------------------------
# 测试1: 正常请求（未超限）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_request_within_limit(rate_limiter, mock_redis):
    """测试正常请求，未超出速率限制."""
    api_key = "test_api_key_001"
    limit = 100
    window = 60

    # Mock pipeline执行结果
    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[None, 5])  # zrem返回None, zcard返回5
    mock_redis.pipeline.return_value = pipe_mock

    # Mock zadd和expire
    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    result = await rate_limiter.check_rate_limit(api_key, limit, window)

    assert result["allowed"] is True
    assert result["remaining"] == 94  # 100 - 5 - 1
    assert "reset_at" in result
    assert result["reset_at"] > time.time()

    # 验证pipeline被调用
    assert pipe_mock.execute.called
    assert mock_redis.zadd.called
    assert mock_redis.expire.called


# ---------------------------------------------------------------------------
# 测试2: 达到限制后拒绝（429错误）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_exceeded(rate_limiter, mock_redis):
    """测试超出速率限制时抛出429错误."""
    api_key = "test_api_key_002"
    limit = 10
    window = 60

    # Mock pipeline：当前已有10个请求（达到限制）
    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[None, 10])
    mock_redis.pipeline.return_value = pipe_mock

    # Mock zrange返回最早的记录
    now = time.time()
    mock_redis.zrange = AsyncMock(return_value=[(f"{now - 30}", now - 30)])

    with pytest.raises(HTTPException) as exc_info:
        await rate_limiter.check_rate_limit(api_key, limit, window)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Rate limit exceeded"

    # 验证响应头
    headers = exc_info.value.headers
    assert headers["X-RateLimit-Limit"] == "10"
    assert headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in headers
    assert "Retry-After" in headers


@pytest.mark.asyncio
async def test_rate_limit_headers(rate_limiter, mock_redis):
    """测试429响应的速率限制头信息."""
    api_key = "test_api_key_003"
    limit = 5
    window = 60

    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[None, 5])
    mock_redis.pipeline.return_value = pipe_mock

    now = time.time()
    mock_redis.zrange = AsyncMock(return_value=[(f"{now - 20}", now - 20)])

    with pytest.raises(HTTPException) as exc_info:
        await rate_limiter.check_rate_limit(api_key, limit, window)

    headers = exc_info.value.headers
    assert int(headers["X-RateLimit-Limit"]) == limit
    assert int(headers["X-RateLimit-Remaining"]) == 0
    assert int(headers["X-RateLimit-Reset"]) > 0
    assert int(headers["Retry-After"]) > 0


# ---------------------------------------------------------------------------
# 测试3: 窗口过期后重置
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_window_reset_after_expiry(rate_limiter, mock_redis):
    """测试时间窗口过期后计数重置."""
    api_key = "test_api_key_004"
    limit = 5
    window = 60

    # 第一次请求：窗口内已有5个请求（达到限制）
    pipe_mock1 = MagicMock()
    pipe_mock1.execute = AsyncMock(return_value=[None, 5])
    mock_redis.pipeline.return_value = pipe_mock1

    now = time.time()
    mock_redis.zrange = AsyncMock(return_value=[(f"{now - 70}", now - 70)])

    # 应该抛出429
    with pytest.raises(HTTPException) as exc_info:
        await rate_limiter.check_rate_limit(api_key, limit, window)
    assert exc_info.value.status_code == 429

    # 模拟时间过去，窗口外的记录被清理
    pipe_mock2 = MagicMock()
    pipe_mock2.execute = AsyncMock(return_value=[None, 0])  # 清理后计数为0
    mock_redis.pipeline.return_value = pipe_mock2

    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    # 第二次请求：应该成功
    result = await rate_limiter.check_rate_limit(api_key, limit, window)
    assert result["allowed"] is True
    assert result["remaining"] == 4  # 5 - 0 - 1


# ---------------------------------------------------------------------------
# 测试4: 并发请求处理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_requests(rate_limiter, mock_redis):
    """测试并发请求时的速率限制."""
    api_key = "test_api_key_005"
    limit = 10
    window = 60

    call_count = 0

    async def mock_execute():
        nonlocal call_count
        call_count += 1
        # 模拟递增的请求数
        return [None, min(call_count - 1, limit)]

    pipe_mock = MagicMock()
    pipe_mock.execute = mock_execute
    mock_redis.pipeline.return_value = pipe_mock

    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=[(f"{time.time()}", time.time())])

    # 发起多个并发请求
    tasks = []
    for _ in range(15):
        tasks.append(rate_limiter.check_rate_limit(api_key, limit, window))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 统计成功和失败的请求
    success_count = sum(1 for r in results if isinstance(r, dict) and r["allowed"])
    error_count = sum(1 for r in results if isinstance(r, HTTPException))

    # 应该有最多limit个成功请求，其余被拒绝
    assert success_count <= limit
    assert error_count >= 5  # 至少5个被拒绝


# ---------------------------------------------------------------------------
# 测试5: 速率限制信息查询
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_rate_limit_info(rate_limiter, mock_redis):
    """测试获取速率限制信息（不增加计数）."""
    api_key = "test_api_key_006"
    limit = 100
    window = 60

    mock_redis.zremrangebyscore = AsyncMock()
    mock_redis.zcard = AsyncMock(return_value=25)
    now = time.time()
    mock_redis.zrange = AsyncMock(return_value=[(f"{now - 10}", now - 10)])

    info = await rate_limiter.get_rate_limit_info(api_key, limit, window)

    assert info["current_count"] == 25
    assert info["remaining"] == 75  # 100 - 25
    assert info["limit"] == limit
    assert info["window"] == window
    assert "reset_at" in info

    # 验证没有调用zadd（不增加计数）
    assert not hasattr(mock_redis, 'zadd') or not mock_redis.zadd.called


# ---------------------------------------------------------------------------
# 测试6: 速率限制重置
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_rate_limit(rate_limiter, mock_redis):
    """测试重置速率限制计数."""
    api_key = "test_api_key_007"

    mock_redis.delete = AsyncMock(return_value=1)

    result = await rate_limiter.reset_rate_limit(api_key)

    assert result is True
    mock_redis.delete.assert_called_once_with(f"rate_limit:{api_key}")


@pytest.mark.asyncio
async def test_reset_nonexistent_key(rate_limiter, mock_redis):
    """测试重置不存在的速率限制键."""
    api_key = "test_api_key_008"

    mock_redis.delete = AsyncMock(return_value=0)

    result = await rate_limiter.reset_rate_limit(api_key)

    assert result is False


# ---------------------------------------------------------------------------
# 测试7: 边界情况
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_limit(rate_limiter, mock_redis):
    """测试限制为0的情况."""
    api_key = "test_api_key_009"
    limit = 0
    window = 60

    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[None, 0])
    mock_redis.pipeline.return_value = pipe_mock

    now = time.time()
    mock_redis.zrange = AsyncMock(return_value=[(f"{now}", now)])

    with pytest.raises(HTTPException) as exc_info:
        await rate_limiter.check_rate_limit(api_key, limit, window)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_large_window(rate_limiter, mock_redis):
    """测试大时间窗口（如1小时）."""
    api_key = "test_api_key_010"
    limit = 1000
    window = 3600  # 1小时

    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(return_value=[None, 100])
    mock_redis.pipeline.return_value = pipe_mock

    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    result = await rate_limiter.check_rate_limit(api_key, limit, window)

    assert result["allowed"] is True
    assert result["remaining"] == 899  # 1000 - 100 - 1

    # 验证过期时间设置正确（window + 10）
    mock_redis.expire.assert_called_once()
    call_args = mock_redis.expire.call_args
    assert call_args[0][1] == window + 10


@pytest.mark.asyncio
async def test_different_api_keys_independent(rate_limiter, mock_redis):
    """测试不同API Key的速率限制相互独立."""
    limit = 5
    window = 60

    # API Key 1: 已有4个请求
    pipe_mock1 = MagicMock()
    pipe_mock1.execute = AsyncMock(return_value=[None, 4])
    mock_redis.pipeline.return_value = pipe_mock1
    mock_redis.zadd = AsyncMock()
    mock_redis.expire = AsyncMock()

    result1 = await rate_limiter.check_rate_limit("api_key_1", limit, window)
    assert result1["remaining"] == 0  # 5 - 4 - 1

    # API Key 2: 只有1个请求
    pipe_mock2 = MagicMock()
    pipe_mock2.execute = AsyncMock(return_value=[None, 1])
    mock_redis.pipeline.return_value = pipe_mock2

    result2 = await rate_limiter.check_rate_limit("api_key_2", limit, window)
    assert result2["remaining"] == 3  # 5 - 1 - 1


# ---------------------------------------------------------------------------
# 测试8: Redis异常处理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_connection_error(rate_limiter, mock_redis):
    """测试Redis连接错误时的行为."""
    api_key = "test_api_key_011"
    limit = 100
    window = 60

    pipe_mock = MagicMock()
    pipe_mock.execute = AsyncMock(side_effect=ConnectionError("Redis connection failed"))
    mock_redis.pipeline.return_value = pipe_mock

    with pytest.raises(ConnectionError):
        await rate_limiter.check_rate_limit(api_key, limit, window)


# ---------------------------------------------------------------------------
# 集成测试提示
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_with_real_redis():
    """集成测试：使用真实Redis（需要Redis服务运行）.

    运行此测试前请确保:
    1. Redis服务正在运行 (redis-server)
    2. 环境变量REDIS_URL配置正确

    运行命令:
        pytest tests/test_rate_limiter.py::test_integration_with_real_redis -v -m integration
    """
    try:
        from redis.asyncio import Redis

        redis = Redis.from_url("redis://localhost:6379/15", decode_responses=True)

        # 测试基本功能
        limiter = RateLimiter(redis)
        test_key = f"integration_test_{time.time()}"

        # 清理测试数据
        await limiter.reset_rate_limit(test_key)

        # 测试正常请求
        result = await limiter.check_rate_limit(test_key, limit=10, window=60)
        assert result["allowed"] is True
        assert result["remaining"] == 9

        # 测试获取信息
        info = await limiter.get_rate_limit_info(test_key, limit=10, window=60)
        assert info["current_count"] == 1
        assert info["remaining"] == 9

        # 清理
        await limiter.reset_rate_limit(test_key)
        await redis.close()

    except ConnectionError:
        pytest.skip("Redis service not available")
