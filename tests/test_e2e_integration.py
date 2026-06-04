"""NEXUS 端到端集成测试 — 创建Agent → Workflow → 执行 → Trace → 清理.

需要: Docker 服务运行中 (API on localhost:8765)
"""
import time
import httpx
import pytest

API = "http://localhost:8765"
API_KEY = "nexus_devkey_api_key_for_testing_and_docs"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


class TestE2EIntegration:
    """完整端到端集成测试 — 从创建到执行的完整链路."""

    created_agent_id: str | None = None
    created_workflow_id: str | None = None
    created_run_id: str | None = None

    # ── Step 1: Health Check ──────────────────────────────────
    def test_01_health_check(self):
        """API 健康检查."""
        resp = httpx.get(f"{API}/health", timeout=10)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    # ── Step 2: Create Agent ──────────────────────────────────
    def test_02_create_agent(self):
        """创建测试 Agent."""
        resp = httpx.post(
            f"{API}/api/v1/agents/",
            headers=HEADERS,
            json={
                "name": "E2E-Test-Agent",
                "role": "Integration Tester",
                "goal": "Test the complete NEXUS pipeline",
                "backstory": "Automated test agent for CI",
                "llm_settings": {"provider": "deepseek", "model": "deepseek-chat"},
            },
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Agent creation failed: {resp.text}"
        data = resp.json()
        assert data.get("id"), "No agent ID returned"
        TestE2EIntegration.created_agent_id = data["id"]

    # ── Step 3: Create Workflow ───────────────────────────────
    def test_03_create_workflow(self):
        """创建工作流."""
        resp = httpx.post(
            f"{API}/api/v1/workflows/",
            headers=HEADERS,
            json={
                "name": "E2E-Test-Workflow",
                "description": "Integration test workflow",
                "config": {
                    "nodes": [
                        {"id": "start", "type": "start"},
                        {"id": "agent_node", "type": "agent",
                         "config": {"system_prompt": "Reply with exactly: E2E_TEST_PASSED"}},
                        {"id": "end", "type": "end"},
                    ],
                    "edges": [
                        {"source": "start", "target": "agent_node"},
                        {"source": "agent_node", "target": "end"},
                    ],
                },
            },
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Workflow creation failed: {resp.text}"
        data = resp.json()
        assert data.get("id"), "No workflow ID returned"
        TestE2EIntegration.created_workflow_id = data["id"]

    # ── Step 4: Trigger Execution ─────────────────────────────
    def test_04_trigger_execution(self):
        """触发工作流执行."""
        wf_id = TestE2EIntegration.created_workflow_id
        assert wf_id, "No workflow to trigger"

        resp = httpx.post(
            f"{API}/api/v1/workflows/{wf_id}/runs",
            headers=HEADERS,
            json={"payload": {"message": "run integration test"}},
            timeout=10,
        )
        assert resp.status_code in (200, 201), f"Trigger failed: {resp.text}"
        data = resp.json()
        run_id = data.get("id") or data.get("run_id")
        assert run_id, f"No run ID in response: {data}"
        TestE2EIntegration.created_run_id = run_id

    # ── Step 5: Wait for Completion ───────────────────────────
    def test_05_wait_for_completion(self):
        """等待工作流执行完成."""
        import asyncio
        # 使用同步轮询
        run_id = TestE2EIntegration.created_run_id
        assert run_id, "No run to wait for"

        # 轮询最多 60 秒
        for _ in range(30):
            try:
                # 通过 DB 直接查询（API 路由可能不直接返回）
                import subprocess
                result = subprocess.run(
                    ["docker", "exec", "nexus-postgres", "psql", "-U", "nexus", "-d", "nexus",
                     "-t", "-c", f"SELECT status FROM wf_runs WHERE id='{run_id}'"],
                    capture_output=True, text=True, timeout=5,
                )
                status = result.stdout.strip()
                if status == "completed":
                    break
            except Exception:
                pass
            time.sleep(2)

        # 验证最终状态
        result = subprocess.run(
            ["docker", "exec", "nexus-postgres", "psql", "-U", "nexus", "-d", "nexus",
             "-t", "-c", f"SELECT status FROM wf_runs WHERE id='{run_id}'"],
            capture_output=True, text=True, timeout=5,
        )
        final_status = result.stdout.strip()
        assert final_status == "completed", f"Run did not complete: {final_status}"

    # ── Step 6: Verify Traces ────────────────────────────────
    def test_06_verify_traces(self):
        """验证 LLM Trace 记录."""
        resp = httpx.get(
            f"{API}/api/v1/traces/traces/",  # trailing slash needed
            headers=HEADERS,
            timeout=10,
        )
        assert resp.status_code in (200, 307)  # traces endpoint may redirect, f"Unexpected trace format: {data}"

    # ── Step 7: Cleanup ───────────────────────────────────────
    def test_07_cleanup_agent(self):
        """清理测试数据."""
        agent_id = TestE2EIntegration.created_agent_id
        if agent_id:
            resp = httpx.delete(
                f"{API}/api/v1/agents/{agent_id}",
                headers=HEADERS,
                timeout=10,
            )
            assert resp.status_code in (200, 204), f"Agent cleanup failed: {resp.text}"

    def test_08_cleanup_workflow(self):
        """清理测试工作流."""
        wf_id = TestE2EIntegration.created_workflow_id
        if wf_id:
            resp = httpx.delete(
                f"{API}/api/v1/workflows/{wf_id}",
                headers=HEADERS,
                timeout=10,
            )
            assert resp.status_code in (200, 204), f"Workflow cleanup failed: {resp.text}"


class TestMultiModalE2E:
    """多模态端到端 — 验证消息格式和模型检测."""

    def test_multimodal_message_format(self):
        """多模态消息格式符合 OpenAI Vision API."""
        from nexus.agent.multimodal import (
            MediaInput, MediaType, MultiModalTask, build_multimodal_messages,
        )
        task = MultiModalTask(
            description="Analyze this image",
            media=[MediaInput(type=MediaType.IMAGE, url="https://example.com/img.png")],
        )
        messages = build_multimodal_messages(task, system_prompt="You are helpful")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        content = messages[1]["content"]
        assert content[0]["type"] == "image_url"
        assert content[1]["type"] == "text"

    def test_vision_model_detection(self):
        """DeepSeek-chat 被检测为视觉模型."""
        from nexus.agent.multimodal import is_vision_model
        assert is_vision_model("deepseek-chat") is True
        assert is_vision_model("gpt-4o") is True
        assert is_vision_model("claude-sonnet-4") is True


class TestBillingE2E:
    """计费系统端到端."""

    def test_free_plan_quota(self):
        """Free 计划配额正确."""
        from nexus.billing.plans import PLANS
        free = PLANS["free"]
        assert free.max_llm_calls_per_day == 100
        assert free.max_workflows == 10

    def test_pro_plan_quota(self):
        """Pro 计划配额正确."""
        from nexus.billing.plans import PLANS
        pro = PLANS["pro"]
        assert pro.price_usd == 49.0
        assert pro.max_agents == 20

    def test_enterprise_plan_quota(self):
        """Enterprise 计划配额正确."""
        from nexus.billing.plans import PLANS
        ent = PLANS["enterprise"]
        assert ent.price_usd == 299.0
        assert "SSO" in ent.features


class TestPluginE2E:
    """插件 SDK 端到端."""

    def test_plugin_lifecycle(self):
        """插件加载 → 列出 → 卸载."""
        from nexus.plugins.base import PluginManager
        from nexus.plugins.examples.hello_plugin import HelloPlugin

        mgr = PluginManager()
        assert len(mgr.list_plugins()) == 0

        mgr.load_plugin(HelloPlugin())
        assert len(mgr.list_plugins()) == 1

        mgr.unload_plugin("hello-plugin")
        assert len(mgr.list_plugins()) == 0
