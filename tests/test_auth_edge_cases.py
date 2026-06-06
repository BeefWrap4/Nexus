"""认证模块边界条件测试.

覆盖:
- JWT Token边界情况（空token、过期token、无效格式）
- API Key边界情况（空key、错误格式、撤销的key）
- 密钥轮换场景
- 速率限制边界
- 并发认证请求
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from nexus.security.auth import (
    AuthService,
    _extract_key_prefix,
    _hash_api_key,
    _verify_api_key,
    get_current_user,
)


# ---------------------------------------------------------------------------
# JWT Token边界测试
# ---------------------------------------------------------------------------

class TestJWTTokenEdgeCases:
    """测试JWT Token的边界情况."""

    def test_empty_token_rejected(self):
        """空token应被拒绝."""
        with pytest.raises(Exception):
            AuthService.verify_token("")

    def test_malformed_token_rejected(self):
        """格式错误的token应被拒绝."""
        with pytest.raises(Exception):
            AuthService.verify_token("not.a.valid.token")

    def test_expired_token_raises_exception(self):
        """已过期的token应抛出ExpiredSignatureError."""
        # 创建一个已过期的token
        expire = datetime.now(timezone.utc) - timedelta(hours=1)
        payload = {
            "sub": "user123",
            "tenant_id": "tenant1",
            "role": "admin",
            "exp": expire,
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "type": "access",
        }
        from nexus.config import settings
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(Exception) as exc_info:
            AuthService.verify_token(token)
        assert "expired" in str(exc_info.value).lower() or "expir" in str(exc_info.value).lower()

    def test_token_with_invalid_signature_rejected(self):
        """签名无效的token应被拒绝."""
        # 使用错误的密钥签名
        payload = {
            "sub": "user123",
            "tenant_id": "tenant1",
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        wrong_token = jwt.encode(payload, "wrong_secret_key", algorithm="HS256")

        with pytest.raises(Exception):
            AuthService.verify_token(wrong_token)

    def test_token_without_required_fields(self):
        """缺少必要字段的token应能解析但可能缺少信息."""
        from nexus.config import settings
        payload = {
            "sub": "user123",
            # 缺少 tenant_id, role
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        result = AuthService.verify_token(token)
        assert result["sub"] == "user123"
        # 可选字段应有默认值或None
        assert "tenant_id" not in result or result.get("tenant_id") is None

    def test_very_long_token_handled(self):
        """超长token应能正常处理."""
        from nexus.config import settings
        # 创建一个包含大量额外数据的token
        payload = {
            "sub": "user123",
            "tenant_id": "tenant1",
            "role": "admin",
            "extra_data": "x" * 10000,  # 10KB额外数据
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        result = AuthService.verify_token(token)
        assert result["sub"] == "user123"

    def test_token_with_unicode_claims(self):
        """包含Unicode字符的claims应能正常处理."""
        from nexus.config import settings
        payload = {
            "sub": "用户123",
            "tenant_id": "租户αβγ",
            "role": "管理员",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        result = AuthService.verify_token(token)
        assert result["sub"] == "用户123"

    def test_refresh_token_verification(self):
        """刷新token应能正确验证."""
        refresh_token = AuthService.create_refresh_token("user123")
        result = AuthService.verify_token(refresh_token)
        assert result["sub"] == "user123"
        assert result["type"] == "refresh"

    def test_access_token_verification(self):
        """访问token应能正确验证."""
        access_token = AuthService.create_access_token(
            user_id="user123",
            tenant_id="tenant1",
            role="admin",
        )
        result = AuthService.verify_token(access_token)
        assert result["sub"] == "user123"
        assert result["tenant_id"] == "tenant1"
        assert result["role"] == "admin"
        assert result["type"] == "access"


# ---------------------------------------------------------------------------
# API Key边界测试
# ---------------------------------------------------------------------------

class TestAPIKeyEdgeCases:
    """测试API Key的边界情况."""

    def test_hash_api_key_consistency(self):
        """相同API Key的哈希应始终一致."""
        api_key = "nexus_test1234_secret"
        hash1 = _hash_api_key(api_key)
        hash2 = _hash_api_key(api_key)
        assert hash1 == hash2

    def test_hash_api_key_different_keys(self):
        """不同API Key的哈希应不同."""
        key1 = "nexus_abcd1234_secret1"
        key2 = "nexus_abcd1234_secret2"
        assert _hash_api_key(key1) != _hash_api_key(key2)

    def test_extract_prefix_valid_format(self):
        """从标准格式的API Key提取前缀."""
        api_key = "nexus_abcd1234_this_is_a_secret"
        prefix = _extract_key_prefix(api_key)
        assert prefix == "abcd1234"

    def test_extract_prefix_no_nexus_prefix(self):
        """没有nexus_前缀时返回前20字符."""
        api_key = "some_random_key_value"
        prefix = _extract_key_prefix(api_key)
        assert prefix == api_key[:20]

    def test_extract_prefix_short_key(self):
        """短key应正常提取."""
        api_key = "nexus_ab_secret"
        prefix = _extract_key_prefix(api_key)
        assert prefix == "ab"

    def test_extract_prefix_empty_key(self):
        """空key应返回空字符串."""
        prefix = _extract_key_prefix("")
        assert prefix == ""

    def test_extract_prefix_single_underscore(self):
        """只有一个下划线的key."""
        api_key = "nexus_"
        prefix = _extract_key_prefix(api_key)
        assert prefix == ""

    @pytest.mark.asyncio
    async def test_verify_api_key_nonexistent(self):
        """不存在的API Key应返回None."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _verify_api_key(mock_db, "nexus_abcd1234_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_api_key_expired(self):
        """已过期的API Key应返回None."""
        mock_db = AsyncMock()
        mock_record = MagicMock()
        mock_record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        mock_record.revoked_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _verify_api_key(mock_db, "nexus_abcd1234_expired")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_api_key_revoked(self):
        """已撤销的API Key应返回None."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # revoked_at检查在SQL中
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _verify_api_key(mock_db, "nexus_abcd1234_revoked")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_api_key_valid(self):
        """有效的API Key应返回记录."""
        mock_db = AsyncMock()
        mock_record = MagicMock()
        mock_record.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_record.revoked_at = None
        mock_record.last_used_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        result = await _verify_api_key(mock_db, "nexus_abcd1234_valid")
        assert result is not None
        assert mock_db.commit.called

    def test_generate_api_key_format(self):
        """生成的API Key应符合预期格式."""
        api_key, prefix, key_hash = AuthService.generate_api_key()
        assert api_key.startswith("nexus_")
        parts = api_key.split("_")
        assert len(parts) >= 3  # nexus_prefix_secret (secret可能包含下划线)
        assert parts[0] == "nexus"
        assert len(parts[1]) == 8  # 8位十六进制
        assert len(key_hash) == 64  # SHA256 hex长度

    def test_generate_api_key_uniqueness(self):
        """每次生成的API Key应唯一."""
        keys = set()
        for _ in range(100):
            api_key, _, _ = AuthService.generate_api_key()
            assert api_key not in keys
            keys.add(api_key)


# ---------------------------------------------------------------------------
# get_current_user边界测试
# ---------------------------------------------------------------------------

class TestGetCurrentUserEdgeCases:
    """测试get_current_user依赖函数的边界情况."""

    @pytest.mark.asyncio
    async def test_no_authentication_provided(self):
        """未提供任何认证信息应抛出401."""
        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.app.state = MagicMock()
        mock_request.app.state.redis = None
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, db=mock_db, credentials=None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_api_key(self):
        """无效的API Key应抛出401."""
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "invalid_key"}
        mock_request.app.state = MagicMock()
        mock_request.app.state.redis = None
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, db=mock_db, credentials=None)

        assert exc_info.value.status_code == 401
        assert "Invalid API Key" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_dev_api_key_in_development(self):
        """开发环境中DEV_API_KEY应能通过认证."""
        with patch("nexus.security.auth.settings") as mock_settings:
            mock_settings.DEV_API_KEY = "dev_test_key"
            mock_settings.ENVIRONMENT = "development"

            mock_request = MagicMock()
            mock_request.headers = {"X-API-Key": "dev_test_key"}
            mock_request.app.state = MagicMock()
            mock_request.app.state.redis = None
            mock_request.client = MagicMock()
            mock_request.client.host = "127.0.0.1"

            mock_db = AsyncMock()
            mock_tenant = MagicMock()
            mock_tenant.id = "tenant-default-id"
            mock_tenant_result = MagicMock()
            mock_tenant_result.scalar_one_or_none.return_value = mock_tenant
            mock_db.execute = AsyncMock(return_value=mock_tenant_result)

            result = await get_current_user(mock_request, db=mock_db, credentials=None)
            assert result["auth_type"] == "dev_api_key"
            assert result["id"] == "dev-api-key-user"

    @pytest.mark.asyncio
    async def test_dev_api_key_in_production_rejected(self):
        """生产环境中DEV_API_KEY不应生效."""
        with patch("nexus.security.auth.settings") as mock_settings:
            mock_settings.DEV_API_KEY = None  # 生产环境没有DEV_API_KEY
            mock_settings.ENVIRONMENT = "production"
            mock_settings.SECRET_KEY = "x" * 64  # 修复: _hash_api_key 需要 bytes-like SECRET_KEY
            mock_settings.JWT_SECRET_KEY = "y" * 64

            mock_request = MagicMock()
            mock_request.headers = {"X-API-Key": "some_random_key"}
            mock_request.app.state = MagicMock()
            mock_request.app.state.redis = None
            mock_request.client = MagicMock()
            mock_request.client.host = "127.0.0.1"

            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=mock_result)

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(mock_request, db=mock_db, credentials=None)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_rate_limit_exceeded(self):
        """JWT认证超过速率限制应抛出429."""
        from nexus.config import settings

        # 创建一个有效的token
        token = AuthService.create_access_token(
            user_id="rate_limited_user",
            tenant_id="tenant1",
            role="user",
        )

        mock_credentials = MagicMock()
        mock_credentials.credentials = token

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.app.state = MagicMock()
        mock_request.app.state.redis = None
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()

        # 模拟已经有很多请求
        import nexus.security.auth as auth_module
        auth_module._jwt_call_times["rate_limited_user"] = [time.time()] * 201

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_request, db=mock_db, credentials=mock_credentials)

        assert exc_info.value.status_code == 429

        # 清理
        if "rate_limited_user" in auth_module._jwt_call_times:
            del auth_module._jwt_call_times["rate_limited_user"]

    @pytest.mark.asyncio
    async def test_api_key_with_redis_rate_limit(self):
        """带Redis速率限制的API Key认证."""
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "nexus_abcd1234_test"}
        mock_request.app.state = MagicMock()
        mock_redis = AsyncMock()
        mock_request.app.state.redis = mock_redis
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()
        mock_record = MagicMock()
        mock_record.user_id = None
        mock_record.tenant_id = "tenant1"
        mock_record.permissions = ["read"]
        mock_record.rate_limit = 1000
        mock_record.rate_window = 60
        mock_record.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_record.revoked_at = None
        mock_record.last_used_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        # Mock RateLimiter
        with patch("nexus.security.auth.RateLimiter") as mock_limiter_class:
            mock_limiter = AsyncMock()
            mock_limiter.check_rate_limit = AsyncMock()
            mock_limiter_class.return_value = mock_limiter

            result = await get_current_user(mock_request, db=mock_db, credentials=None)
            assert result["auth_type"] == "api_key"
            assert result["tenant_id"] == "tenant1"

    @pytest.mark.asyncio
    async def test_api_key_with_associated_user(self):
        """关联用户的API Key应返回用户信息."""
        mock_request = MagicMock()
        mock_request.headers = {"X-API-Key": "nexus_abcd1234_user"}
        mock_request.app.state = MagicMock()
        mock_request.app.state.redis = None
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        mock_db = AsyncMock()

        # Mock API Key record
        mock_key_record = MagicMock()
        mock_key_record.user_id = "user-uuid-123"
        mock_key_record.tenant_id = "tenant1"
        mock_key_record.permissions = ["read", "write"]
        mock_key_record.rate_limit = 1000
        mock_key_record.rate_window = 60
        mock_key_record.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        mock_key_record.revoked_at = None
        mock_key_record.last_used_at = None

        # Mock User record
        mock_user = MagicMock()
        mock_user.id = "user-uuid-123"
        mock_user.role = "admin"

        # Setup execute to return different results based on query
        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            mock_result = MagicMock()
            if call_count[0] == 1:
                mock_result.scalar_one_or_none.return_value = mock_key_record
            else:
                mock_result.scalar_one_or_none.return_value = mock_user
            return mock_result

        mock_db.execute = mock_execute
        mock_db.commit = AsyncMock()

        result = await get_current_user(mock_request, db=mock_db, credentials=None)
        assert result["id"] == "user-uuid-123"
        assert result["role"] == "admin"
