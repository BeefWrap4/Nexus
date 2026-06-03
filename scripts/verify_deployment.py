#!/usr/bin/env python3
# =============================================================================
# NEXUS 部署后全量功能验证脚本
# 覆盖 Phase 1-10 全部核心功能
# 用法: python scripts/verify_deployment.py --url http://localhost:8000
# =============================================================================

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class CheckResult:
    """单个验证项的结果."""

    name: str
    phase: str
    passed: bool
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class VerifierState:
    """验证器状态，跨检查项共享资源."""

    base_url: str
    created_workflow_id: str | None = None
    created_agent_id: str | None = None
    created_crew_id: str | None = None
    created_prompt_id: str | None = None
    created_mcp_id: str | None = None


class DeploymentVerifier:
    """部署验证器 — 覆盖 Phase 1-10."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )
        self.state = VerifierState(base_url=base_url)
        self.results: list[CheckResult] = []

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------
    async def _get(self, path: str, expected_status: int = 200) -> tuple[bool, Any]:
        """发送 GET 请求并检查状态码."""
        try:
            resp = await self.client.get(path)
            if resp.status_code == expected_status:
                return True, resp.json() if resp.text else {}
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    async def _post(
        self, path: str, json_data: dict | None = None, expected_status: int = 200
    ) -> tuple[bool, Any]:
        """发送 POST 请求并检查状态码."""
        try:
            resp = await self.client.post(path, json=json_data)
            if resp.status_code == expected_status:
                return True, resp.json() if resp.text else {}
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    async def _delete(self, path: str, expected_status: int = 204) -> tuple[bool, Any]:
        """发送 DELETE 请求并检查状态码."""
        try:
            resp = await self.client.delete(path)
            if resp.status_code == expected_status:
                return True, {}
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, str(e)

    def _record(
        self, name: str, phase: str, passed: bool, message: str = "", elapsed: float = 0.0
    ) -> None:
        """记录验证结果."""
        self.results.append(
            CheckResult(
                name=name, phase=phase, passed=passed, message=message, duration_ms=elapsed * 1000
            )
        )
        status = "✅" if passed else "❌"
        msg = f" — {message}" if message else ""
        print(f"  {status} {name} ({elapsed*1000:.0f}ms){msg}")

    # ===================================================================
    # Phase 1: 基础架构
    # ===================================================================
    async def verify_health(self) -> None:
        """验证 /health 端点."""
        t0 = time.time()
        ok, data = await self._get("/health")
        self._record("Health Check", "P1", ok, str(data)[:100] if not ok else "", time.time() - t0)

    async def verify_api_docs(self) -> None:
        """验证 API 文档可访问."""
        t0 = time.time()
        ok1, _ = await self._get("/docs")
        ok2, _ = await self._get("/openapi.json")
        ok = ok1 and ok2
        self._record("API Docs", "P1", ok, "", time.time() - t0)

    async def verify_metrics(self) -> None:
        """验证 Prometheus /metrics 端点."""
        t0 = time.time()
        ok, data = await self._get("/metrics")
        has_metrics = ok and isinstance(data, str) and "python_" in data
        self._record("Prometheus Metrics", "P1", has_metrics, "", time.time() - t0)

    # ===================================================================
    # Phase 2: Workflow 引擎
    # ===================================================================
    async def verify_workflow_crud(self) -> None:
        """验证 Workflow CRUD."""
        t0 = time.time()

        # Create
        ok, data = await self._post(
            "/api/v1/workflows",
            {
                "name": "Verification Workflow",
                "description": "Created by deployment verification",
                "config": {"nodes": [], "edges": []},
                "tags": ["verify"],
            },
            expected_status=201,
        )
        if not ok:
            self._record("Workflow CRUD", "P2", False, str(data)[:200], time.time() - t0)
            return

        workflow_id = data.get("id")
        self.state.created_workflow_id = workflow_id

        # Read
        ok2, data2 = await self._get(f"/api/v1/workflows/{workflow_id}")
        read_ok = ok2 and data2.get("id") == workflow_id

        # List
        ok3, data3 = await self._get("/api/v1/workflows")
        list_ok = ok3 and isinstance(data3, list)

        # Update
        ok4, _ = await self.client.put(
            f"/api/v1/workflows/{workflow_id}",
            json={"name": "Verification Workflow Updated"},
        )
        update_ok = ok4.status_code == 200

        passed = read_ok and list_ok and update_ok
        self._record("Workflow CRUD", "P2", passed, "", time.time() - t0)

    async def verify_workflow_run(self) -> None:
        """验证 Workflow 执行触发."""
        if not self.state.created_workflow_id:
            self._record("Workflow Execution", "P2", False, "No workflow created", 0)
            return

        t0 = time.time()
        ok, data = await self._post(
            f"/api/v1/workflows/{self.state.created_workflow_id}/runs",
            {"trigger_payload": {"test": True}},
            expected_status=202,
        )
        passed = ok and data.get("run_id")
        self._record("Workflow Execution", "P2", passed, "", time.time() - t0)

    # ===================================================================
    # Phase 3: Agent 基础
    # ===================================================================
    async def verify_agent_crud(self) -> None:
        """验证 Agent CRUD."""
        t0 = time.time()

        ok, data = await self._post(
            "/api/v1/agents",
            {
                "name": "Verification Agent",
                "role": "verifier",
                "goal": "Verify deployment",
                "llm_config": {"model": "gpt-4o", "provider": "openai"},
                "system_prompt": "You are a verification agent.",
            },
            expected_status=201,
        )
        if not ok:
            self._record("Agent CRUD", "P3", False, str(data)[:200], time.time() - t0)
            return

        agent_id = data.get("id")
        self.state.created_agent_id = agent_id

        ok2, _ = await self._get(f"/api/v1/agents/{agent_id}")
        passed = ok2
        self._record("Agent CRUD", "P3", passed, "", time.time() - t0)

    # ===================================================================
    # Phase 4/10: Crew 多 Agent 协作
    # ===================================================================
    async def verify_crew_crud(self) -> None:
        """验证 Crew CRUD."""
        if not self.state.created_agent_id:
            self._record("Crew CRUD", "P10", False, "No agent created", 0)
            return

        t0 = time.time()

        ok, data = await self._post(
            "/api/v1/crews",
            {
                "name": "Verification Crew",
                "description": "Created by deployment verification",
                "mode": "hierarchical",
                "config": {"max_workers": 3, "shared_context_enabled": True, "auto_delegate": True},
                "agent_ids": [
                    {"agent_id": self.state.created_agent_id, "role_in_crew": "manager", "order_index": 0}
                ],
            },
            expected_status=201,
        )
        if not ok:
            self._record("Crew CRUD", "P10", False, str(data)[:200], time.time() - t0)
            return

        crew_id = data.get("id")
        self.state.created_crew_id = crew_id

        ok2, _ = await self._get(f"/api/v1/crews/{crew_id}")
        passed = ok2
        self._record("Crew CRUD", "P10", passed, "", time.time() - t0)

    async def verify_crew_execution(self) -> None:
        """验证 Crew 执行（Hierarchical 模式）."""
        if not self.state.created_crew_id:
            self._record("Crew Execution", "P10", False, "No crew created", 0)
            return

        t0 = time.time()
        ok, data = await self._post(
            f"/api/v1/crews/{self.state.created_crew_id}/run",
            {"task_description": "Verify the deployment is working correctly"},
            expected_status=200,
        )
        # Crew 执行可能因 LLM 配置而失败，但端点必须响应
        passed = ok and isinstance(data, dict)
        msg = data.get("status", "unknown") if isinstance(data, dict) else str(data)[:100]
        self._record("Crew Execution", "P10", passed, msg, time.time() - t0)

    # ===================================================================
    # Phase 5: MCP 工具
    # ===================================================================
    async def verify_mcp(self) -> None:
        """验证 MCP 连接列表可访问."""
        t0 = time.time()
        ok, data = await self._get("/api/v1/mcp/connections")
        passed = ok and isinstance(data, list)
        self._record("MCP Connections", "P5", passed, "", time.time() - t0)

    # ===================================================================
    # Phase 6: Prompt / Trace / Eval
    # ===================================================================
    async def verify_prompts(self) -> None:
        """验证 Prompt 管理."""
        t0 = time.time()

        ok, data = await self._post(
            "/api/v1/prompts",
            {
                "name": "verification-prompt",
                "content": "This is a verification prompt.",
                "variables": [],
                "tags": ["verify"],
            },
            expected_status=201,
        )
        if ok:
            self.state.created_prompt_id = data.get("id")

        ok2, _ = await self._get("/api/v1/prompts")
        passed = (ok or ok2)  # 创建或列表至少一个成功
        self._record("Prompt Management", "P6", passed, "", time.time() - t0)

    async def verify_traces(self) -> None:
        """验证 Trace 查询."""
        t0 = time.time()
        ok, data = await self._get("/api/v1/traces")
        passed = ok and isinstance(data, list)
        self._record("Trace Query", "P6", passed, "", time.time() - t0)

    async def verify_evals(self) -> None:
        """验证 Eval 端点可访问."""
        t0 = time.time()
        ok, data = await self._get("/api/v1/evals")
        passed = ok and isinstance(data, list)
        self._record("Eval Dashboard", "P6", passed, "", time.time() - t0)

    # ===================================================================
    # Phase 8: Code Review
    # ===================================================================
    async def verify_code_review(self) -> None:
        """验证 Code Review 端点."""
        t0 = time.time()
        ok, data = await self._post(
            "/api/v1/code-review",
            {
                "diff_text": "diff --git a/test.py b/test.py\n+print('hello')",
                "language": "python",
            },
            expected_status=200,
        )
        # 可能因 LLM 配置返回非 200，但端点必须存在
        passed = ok or (isinstance(data, dict) and "detail" in data)
        self._record("Code Review", "P8", ok, "", time.time() - t0)

    # ===================================================================
    # Phase 9: 语义缓存
    # ===================================================================
    async def verify_semantic_cache(self) -> None:
        """验证语义缓存指标存在."""
        t0 = time.time()
        ok, data = await self._get("/metrics")
        has_cache_metric = ok and isinstance(data, str) and "cache" in data.lower()
        self._record("Semantic Cache Metrics", "P9", has_cache_metric, "", time.time() - t0)

    # ===================================================================
    # 清理资源
    # ===================================================================
    async def cleanup(self) -> None:
        """清理验证过程中创建的资源."""
        print("\n🧹 Cleaning up...")
        if self.state.created_crew_id:
            await self._delete(f"/api/v1/crews/{self.state.created_crew_id}")
        if self.state.created_agent_id:
            await self._delete(f"/api/v1/agents/{self.state.created_agent_id}")
        if self.state.created_workflow_id:
            await self._delete(f"/api/v1/workflows/{self.state.created_workflow_id}")
        if self.state.created_prompt_id:
            await self._delete(f"/api/v1/prompts/{self.state.created_prompt_id}")
        print("  ✓ Cleanup done")

    # ===================================================================
    # 主验证流程
    # ===================================================================
    async def verify_all(self) -> bool:
        """运行全部验证."""
        print(f"\n🔍 Verifying deployment at {self.base_url}")
        print("=" * 50)

        checks = [
            self.verify_health,
            self.verify_api_docs,
            self.verify_metrics,
            self.verify_workflow_crud,
            self.verify_workflow_run,
            self.verify_agent_crud,
            self.verify_crew_crud,
            self.verify_crew_execution,
            self.verify_mcp,
            self.verify_prompts,
            self.verify_traces,
            self.verify_evals,
            self.verify_code_review,
            self.verify_semantic_cache,
        ]

        for check in checks:
            try:
                await check()
            except Exception as e:
                self._record(check.__name__, "ERR", False, str(e), 0)

        # 清理
        await self.cleanup()
        await self.client.aclose()

        # 汇总
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        failed = total - passed

        print("\n" + "=" * 50)
        print(f"📊 Results: {passed}/{total} passed, {failed} failed")

        if failed == 0:
            print("🎉 All checks passed!")
            return True
        else:
            print("\n❌ Failed checks:")
            for r in self.results:
                if not r.passed:
                    print(f"  • [{r.phase}] {r.name}: {r.message}")
            return False


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS Deployment Verification")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the NEXUS API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    verifier = DeploymentVerifier(base_url=args.url, timeout=args.timeout)
    success = asyncio.run(verifier.verify_all())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
