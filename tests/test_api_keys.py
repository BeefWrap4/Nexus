"""API Key 真写库端到端测试 (49d460a1).

验证:
  - POST /api/v1/api-keys 真写 api_keys 表
  - 创建时返回明文 key (prefix 匹配)
  - GET /api/v1/api-keys 列当前 tenant, 排除已撤销
  - DELETE /api/v1/api-keys/{id} 软删
  - 撤销后 X-API-Key 再调, _verify_api_key 拒绝

注: 用 httpx 打 live API (localhost:8765), 而不是 in-memory async_client
(后者用的是 sqlite 测试库, 没有 admin@nexus.local 用户, 而且 rate limiter
在 in-memory 模式下会撞连接)。
"""
import os
import uuid

import httpx
import pytest


# 注: 这些测试需要 live API (在 8765), 跑 docker stack 后能 pass。
# 标记为 integration 避免 CI 默认排除。
pytestmark = pytest.mark.integration


LIVE_API = os.environ.get("NEXUS_TEST_API_URL", "http://localhost:8765")


def _login() -> str:
    """登录拿 JWT (sync, 因为 in-process ASGI 不通)."""
    resp = httpx.post(
        f"{LIVE_API}/api/v1/auth/login",
        json={"email": "admin@nexus.local", "password": "admin123"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def test_list_api_keys():
    """列 API keys — 至少能返回 200 + list (可能空, 可能有历史 dev key)."""
    token = _login()
    resp = httpx.get(
        f"{LIVE_API}/api/v1/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_list_use_revoke_key():
    """完整生命周期: 创建 → 列 → 用 key 调 API → 撤销 → 列 → 撤销后用."""
    token = _login()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. 创建
    create_resp = httpx.post(
        f"{LIVE_API}/api/v1/api-keys",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": f"E2E Test Key {uuid.uuid4().hex[:8]}", "rate_limit": 100, "expires_days": 7},
        timeout=10,
    )
    assert create_resp.status_code == 200, create_resp.text
    created = create_resp.json()
    assert "key" in created and created["key"].startswith("nexus_")
    assert "key_prefix" in created and len(created["key_prefix"]) > 0
    assert created["rate_limit"] == 100
    key_id = created["id"]
    raw_key = created["key"]

    try:
        # 2. 列
        list_resp = httpx.get(f"{LIVE_API}/api/v1/api-keys", headers=headers, timeout=10)
        assert list_resp.status_code == 200
        listed_ids = [k["id"] for k in list_resp.json()]
        assert key_id in listed_ids
        # 创建响应里的 key 字段在 list 时应该为 None (只在创建时返回)
        listed_row = next(k for k in list_resp.json() if k["id"] == key_id)
        assert listed_row["key"] is None

        # 3. 用新 key 调 API
        use_resp = httpx.get(
            f"{LIVE_API}/api/v1/agents/",
            headers={"X-API-Key": raw_key},
            timeout=10,
        )
        assert use_resp.status_code == 200, use_resp.text

        # 4. 撤销
        del_resp = httpx.delete(
            f"{LIVE_API}/api/v1/api-keys/{key_id}", headers=headers, timeout=10
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

        # 5. 撤销后, list 应该过滤掉
        list2 = httpx.get(f"{LIVE_API}/api/v1/api-keys", headers=headers, timeout=10)
        assert key_id not in [k["id"] for k in list2.json()]

        # 6. 撤销后用 key 调 → 401
        use2 = httpx.get(
            f"{LIVE_API}/api/v1/agents/",
            headers={"X-API-Key": raw_key},
            timeout=10,
        )
        assert use2.status_code == 401
        assert "Invalid" in use2.json().get("detail", "")
    finally:
        # 清理: 即便中间 assert 失败也确保 key 被撤销 (避免 dev DB 留垃圾)
        if created.get("revoked_at") is None:
            try:
                httpx.delete(
                    f"{LIVE_API}/api/v1/api-keys/{key_id}",
                    headers=headers,
                    timeout=5,
                )
            except Exception:
                pass


def test_create_key_minimal_payload():
    """空 payload 应该 OK (所有字段有默认)."""
    token = _login()
    resp = httpx.post(
        f"{LIVE_API}/api/v1/api-keys",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "unnamed"  # 默认名
    # 清理
    httpx.delete(
        f"{LIVE_API}/api/v1/api-keys/{body['id']}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )


def test_delete_nonexistent_key():
    """删不存在的 key 应该 404."""
    token = _login()
    resp = httpx.delete(
        f"{LIVE_API}/api/v1/api-keys/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert resp.status_code == 404


def test_unauth_list_rejected():
    """没 token 调 /api-keys 应该 401."""
    resp = httpx.get(f"{LIVE_API}/api/v1/api-keys", timeout=10)
    assert resp.status_code == 401

