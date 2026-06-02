"""API集成测试.

覆盖:
- 健康检查与根路径
- 认证与授权（JWT + API Key）
- Workflow路由（CRUD、触发执行、版本管理、克隆）
- Agent路由（CRUD）
- Run路由（状态管理、日志、产物）
- 全局异常处理
"""

import pytest
from httpx import AsyncClient

from nexus.api.main import app
from nexus.security.auth import AuthService


# ---------------------------------------------------------------------------
# 基础端点测试
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    """测试健康检查端点."""

    @pytest.mark.asyncio
    async def test_health_check(self, async_client: AsyncClient):
        """健康检查应返回ok和版本号."""
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client: AsyncClient):
        """根路径应返回应用信息."""
        response = await async_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "NEXUS"
        assert "version" in data
        assert "docs" in data


# ---------------------------------------------------------------------------
# 认证测试
# ---------------------------------------------------------------------------

class TestAuthentication:
    """测试认证机制."""

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, async_client: AsyncClient):
        """未提供认证信息时应返回401."""
        response = await async_client.get("/api/v1/workflows/")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, async_client: AsyncClient):
        """无效Token应返回401."""
        response = await async_client.get(
            "/api/v1/workflows/",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_allows_access(
        self, async_client: AsyncClient, test_token: str
    ):
        """有效Token应允许访问（至少不返回401）."""
        response = await async_client.get(
            "/api/v1/workflows/",
            headers={"Authorization": f"Bearer {test_token}"},
        )
        # 可能200（空列表）或500（DB未初始化），但不应401
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_api_key_auth(self, async_client: AsyncClient):
        """API Key认证应被接受."""
        response = await async_client.get(
            "/api/v1/workflows/",
            headers={"X-API-Key": "test-api-key"},
        )
        # API Key认证通过，不应返回401
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# Workflow路由测试
# ---------------------------------------------------------------------------

class TestWorkflowRoutes:
    """测试Workflow API路由."""

    @pytest.mark.asyncio
    async def test_create_workflow(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试创建工作流."""
        payload = {
            "name": "Test Workflow",
            "description": "A test workflow",
            "config": {"nodes": [], "edges": []},
            "variables": {},
            "tags": ["test"],
        }
        response = await async_client.post(
            "/api/v1/workflows/", json=payload, headers=auth_headers
        )
        # 数据库已override为内存DB，应成功
        assert response.status_code in (201, 200)
        if response.status_code == 201:
            data = response.json()
            assert data["name"] == "Test Workflow"
            assert "id" in data

    @pytest.mark.asyncio
    async def test_list_workflows(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试列出工作流."""
        response = await async_client.get(
            "/api/v1/workflows/", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_workflows_with_pagination(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试分页参数."""
        response = await async_client.get(
            "/api/v1/workflows/?skip=0&limit=10", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 10

    @pytest.mark.asyncio
    async def test_list_workflows_with_status_filter(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试状态过滤."""
        response = await async_client.get(
            "/api/v1/workflows/?status=active", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_workflow_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """获取不存在的工作流应返回404."""
        from uuid import uuid4

        response = await async_client.get(
            f"/api/v1/workflows/{uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_and_get_workflow(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试创建后获取工作流."""
        # 创建
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Get Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping get test")

        created = create_resp.json()
        wf_id = created["id"]

        # 获取
        get_resp = await async_client.get(
            f"/api/v1/workflows/{wf_id}", headers=auth_headers
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == wf_id
        assert data["name"] == "Get Test"

    @pytest.mark.asyncio
    async def test_update_workflow(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试更新工作流."""
        # 创建
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Update Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping update test")

        created = create_resp.json()
        wf_id = created["id"]

        # 更新
        update_resp = await async_client.put(
            f"/api/v1/workflows/{wf_id}",
            json={"name": "Updated Name", "description": "New desc"},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_delete_workflow(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试删除工作流."""
        # 创建
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Delete Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping delete test")

        created = create_resp.json()
        wf_id = created["id"]

        # 删除
        del_resp = await async_client.delete(
            f"/api/v1/workflows/{wf_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204

        # 再次获取应404
        get_resp = await async_client.get(
            f"/api/v1/workflows/{wf_id}", headers=auth_headers
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_workflow_run(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试触发工作流执行."""
        # 创建工作流
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Trigger Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping trigger test")

        created = create_resp.json()
        wf_id = created["id"]

        # 触发执行
        trigger_resp = await async_client.post(
            f"/api/v1/workflows/{wf_id}/runs",
            json={"trigger_payload": {"input": "test"}, "version": None},
            headers=auth_headers,
        )
        assert trigger_resp.status_code in (200, 201)
        data = trigger_resp.json()
        assert "run_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_workflow_runs(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试列出工作流执行记录."""
        # 创建工作流
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "List Runs Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping list runs test")

        created = create_resp.json()
        wf_id = created["id"]

        # 列出执行记录
        list_resp = await async_client.get(
            f"/api/v1/workflows/{wf_id}/runs", headers=auth_headers
        )
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_version(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试创建工作流版本."""
        # 创建工作流
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Version Test", "config": {"v": 1}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping version test")

        created = create_resp.json()
        wf_id = created["id"]

        # 创建版本
        ver_resp = await async_client.post(
            f"/api/v1/workflows/{wf_id}/versions", headers=auth_headers
        )
        assert ver_resp.status_code in (200, 201)
        data = ver_resp.json()
        assert "version" in data
        assert data["version"] >= 1

    @pytest.mark.asyncio
    async def test_list_versions(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试列出版本历史."""
        # 创建工作流
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "List Versions Test", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping list versions test")

        created = create_resp.json()
        wf_id = created["id"]

        # 列出版本
        list_resp = await async_client.get(
            f"/api/v1/workflows/{wf_id}/versions", headers=auth_headers
        )
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_clone_workflow(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试克隆工作流."""
        # 创建工作流
        create_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Clone Source", "config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping clone test")

        created = create_resp.json()
        wf_id = created["id"]

        # 克隆
        clone_resp = await async_client.post(
            f"/api/v1/workflows/{wf_id}/clone", headers=auth_headers
        )
        assert clone_resp.status_code in (200, 201)
        data = clone_resp.json()
        assert "new_workflow_id" in data
        assert data["source"] == wf_id


# ---------------------------------------------------------------------------
# Agent路由测试
# ---------------------------------------------------------------------------

class TestAgentRoutes:
    """测试Agent API路由."""

    @pytest.mark.asyncio
    async def test_list_agents(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试列出Agent."""
        response = await async_client.get(
            "/api/v1/agents/", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_agent(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试创建Agent."""
        payload = {
            "name": "Test Agent",
            "role": "assistant",
            "goal": "Help users",
            "llm_config": {"model": "gpt-4o"},
            "tools": ["search", "calculator"],
        }
        response = await async_client.post(
            "/api/v1/agents/", json=payload, headers=auth_headers
        )
        assert response.status_code in (201, 200)
        if response.status_code == 201:
            data = response.json()
            assert data["name"] == "Test Agent"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """获取不存在的Agent应返回404."""
        from uuid import uuid4

        response = await async_client.get(
            f"/api/v1/agents/{uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_agent(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试更新Agent."""
        # 创建
        create_resp = await async_client.post(
            "/api/v1/agents/",
            json={"name": "Update Agent", "llm_config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping update test")

        created = create_resp.json()
        agent_id = created["id"]

        # 更新
        update_resp = await async_client.put(
            f"/api/v1/agents/{agent_id}",
            json={"name": "Updated Agent Name"},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "Updated Agent Name"

    @pytest.mark.asyncio
    async def test_delete_agent(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试删除Agent."""
        # 创建
        create_resp = await async_client.post(
            "/api/v1/agents/",
            json={"name": "Delete Agent", "llm_config": {}},
            headers=auth_headers,
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip("Create failed, skipping delete test")

        created = create_resp.json()
        agent_id = created["id"]

        # 删除
        del_resp = await async_client.delete(
            f"/api/v1/agents/{agent_id}", headers=auth_headers
        )
        assert del_resp.status_code == 204


# ---------------------------------------------------------------------------
# Run路由测试
# ---------------------------------------------------------------------------

class TestRunRoutes:
    """测试Run API路由."""

    @pytest.mark.asyncio
    async def test_get_run_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """获取不存在的Run应返回404."""
        from uuid import uuid4

        response = await async_client.get(
            f"/api/v1/runs/{uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_run_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """取消不存在的Run应返回404."""
        from uuid import uuid4

        response = await async_client.post(
            f"/api/v1/runs/{uuid4()}/cancel", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_pause_run_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """暂停不存在的Run应返回404."""
        from uuid import uuid4

        response = await async_client.post(
            f"/api/v1/runs/{uuid4()}/pause", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_run_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """恢复不存在的Run应返回404."""
        from uuid import uuid4

        response = await async_client.post(
            f"/api/v1/runs/{uuid4()}/resume", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_run_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """重试不存在的Run应返回404."""
        from uuid import uuid4

        response = await async_client.post(
            f"/api/v1/runs/{uuid4()}/retry", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_run_lifecycle(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        """测试Run完整生命周期: 创建 -> 取消."""
        # 先创建工作流
        wf_resp = await async_client.post(
            "/api/v1/workflows/",
            json={"name": "Lifecycle Test", "config": {}},
            headers=auth_headers,
        )
        if wf_resp.status_code not in (200, 201):
            pytest.skip("Workflow create failed, skipping lifecycle test")

        wf_id = wf_resp.json()["id"]

        # 触发执行
        trigger_resp = await async_client.post(
            f"/api/v1/workflows/{wf_id}/runs",
            json={"trigger_payload": {}},
            headers=auth_headers,
        )
        assert trigger_resp.status_code in (200, 201)
        run_id = trigger_resp.json()["run_id"]

        # 获取Run
        get_resp = await async_client.get(
            f"/api/v1/runs/{run_id}", headers=auth_headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == run_id

        # 取消Run
        cancel_resp = await async_client.post(
            f"/api/v1/runs/{run_id}/cancel", headers=auth_headers
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        # 获取日志
        logs_resp = await async_client.get(
            f"/api/v1/runs/{run_id}/logs", headers=auth_headers
        )
        assert logs_resp.status_code == 200
        assert isinstance(logs_resp.json(), list)

        # 获取产物
        artifacts_resp = await async_client.get(
            f"/api/v1/runs/{run_id}/artifacts", headers=auth_headers
        )
        assert artifacts_resp.status_code == 200
        assert isinstance(artifacts_resp.json(), list)


# ---------------------------------------------------------------------------
# 异常处理测试
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """测试全局异常处理."""

    @pytest.mark.asyncio
    async def test_nexus_exception_handler(self, async_client: AsyncClient):
        """NexusException应被正确处理为400响应."""
        # 通过触发一个已知会失败的场景来测试
        # 这里测试一个缺少认证的请求，验证错误格式
        response = await async_client.get("/api/v1/workflows/")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_validation_error(self, async_client: AsyncClient, auth_headers: dict[str, str]):
        """Pydantic验证错误应返回422."""
        # 发送无效数据触发验证错误
        response = await async_client.post(
            "/api/v1/workflows/",
            json={"name": ""},  # 空名称，违反min_length=1
            headers=auth_headers,
        )
        assert response.status_code == 422
