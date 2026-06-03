"""Code Review 服务层.

Phase 8: 代码审查 Agent — 封装 workflow 构建、持久化和入队执行。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.jobs.pool import get_arq_pool
from nexus.services.run import RunService


class CodeReviewService:
    """代码审查服务.

    负责：
    1. 创建持久化的 WorkflowRun 记录
    2. 将审查 workflow 入队到 ARQ Worker 执行
    3. ARQ 不可用时降级到本地异步执行
    """

    def __init__(self):
        self.run_service = RunService()

    async def submit_review(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        diff_content: str,
        language: str = "auto",
        focus_areas: str = "security, performance, maintainability, correctness",
        strictness: str = "normal",
        template_id: UUID | None = None,
    ) -> dict[str, Any]:
        """提交代码审查请求.

        Args:
            session: 数据库会话
            tenant_id: 租户ID
            diff_content: 代码 diff 内容
            language: 编程语言
            focus_areas: 关注领域
            strictness: 严格程度
            template_id: 可选的 PromptTemplate ID

        Returns:
            {"run_id": str, "status": str}
        """
        workflow_config = self._build_simple_review_workflow(
            diff_content=diff_content,
            language=language,
            focus_areas=focus_areas,
            strictness=strictness,
            template_id=str(template_id) if template_id else None,
        )
        trigger_payload = {"diff_content": diff_content}

        return await self._create_and_enqueue(
            session, tenant_id, workflow_config, trigger_payload
        )

    async def submit_pr_review(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        owner: str,
        repo: str,
        pull_number: int,
        pr_data: dict[str, Any],
    ) -> dict[str, Any]:
        """提交 PR 代码审查请求.

        Args:
            session: 数据库会话
            tenant_id: 租户ID
            owner: GitHub 仓库所有者
            repo: 仓库名
            pull_number: PR 编号
            pr_data: PR 完整 payload

        Returns:
            {"run_id": str, "status": str}
        """
        workflow_config = self._build_pr_review_workflow(
            owner=owner, repo=repo, pull_number=pull_number
        )
        trigger_payload = {"pr": pr_data}

        return await self._create_and_enqueue(
            session, tenant_id, workflow_config, trigger_payload
        )

    async def get_review_result(
        self,
        session: AsyncSession,
        run_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """获取审查结果.

        Args:
            session: 数据库会话
            run_id: 运行实例ID
            tenant_id: 租户ID

        Returns:
            审查结果，不存在则返回 None
        """
        run = await self.run_service.get(session, run_id, tenant_id)
        if not run:
            return None
        return {
            "run_id": str(run_id),
            "status": run.status,
            "result": run.result,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _create_and_enqueue(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        workflow_config: dict[str, Any],
        trigger_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """创建 WorkflowRun 并入队执行（或本地降级）."""
        run = await self.run_service.create(
            session,
            data={
                "workflow_id": None,  # 内联 workflow，无预定义 workflow_id
                "trigger_type": "code_review",
                "trigger_payload": trigger_payload,
            },
            tenant_id=tenant_id,
        )
        run_id = str(run.id)

        arq_pool = get_arq_pool()
        if arq_pool:
            await arq_pool.enqueue_job(
                "execute_workflow_job",
                run_id=run_id,
                workflow_config=workflow_config,
                trigger_payload=trigger_payload,
                tenant_id=str(tenant_id),
            )
        else:
            # 降级：本地异步执行（ARQ 未初始化时）
            from nexus.utils.async_tasks import safe_workflow_execution

            safe_workflow_execution(
                self._execute_local(run_id, workflow_config, trigger_payload, tenant_id),
                run_id=run_id,
                tenant_id=str(tenant_id),
            )

        return {"run_id": run_id, "status": "started"}

    async def _execute_local(
        self,
        run_id: str,
        workflow_config: dict[str, Any],
        trigger_payload: dict[str, Any],
        tenant_id: UUID,
    ) -> None:
        """本地降级执行（ARQ 不可用时）.

        异常由调用方的 safe_workflow_execution 捕获和处理。
        """
        from nexus.jobs.workflow import execute_workflow_job

        ctx: dict[str, Any] = {"redis": None, "worker_id": "local"}
        await execute_workflow_job(
            ctx,
            run_id=run_id,
            workflow_config=workflow_config,
            trigger_payload=trigger_payload,
            tenant_id=str(tenant_id),
        )

    @staticmethod
    def _build_simple_review_workflow(
        diff_content: str,
        language: str = "auto",
        focus_areas: str = "security, performance, maintainability, correctness",
        strictness: str = "normal",
        template_id: str | None = None,
    ) -> dict[str, Any]:
        """构建简单代码审查 workflow（3 节点：start → review → end）."""
        return {
            "nodes": [
                {"id": "start", "type": "start", "config": {}, "depends_on": []},
                {
                    "id": "review",
                    "type": "agent",
                    "config": {
                        "agent_name": "code-reviewer",
                        "agent_role": "senior software engineer performing code review",
                        "agent_goal": "Thoroughly review code and produce a structured review report",
                        "task_description": diff_content,
                        "system_prompt_template_id": template_id,
                        "template_variables": {
                            "role": "senior software engineer",
                            "language": language,
                            "focus_areas": focus_areas,
                            "strictness": strictness,
                            "diff_content": diff_content,
                        },
                        "provider": settings.DEFAULT_LLM_PROVIDER,
                        "model": settings.DEFAULT_LLM_MODEL,
                    },
                    "depends_on": [],
                },
                {"id": "end", "type": "end", "config": {}, "depends_on": []},
            ],
            "edges": [
                {"source": "start", "target": "review", "condition": None},
                {"source": "review", "target": "end", "condition": None},
            ],
        }

    @staticmethod
    def _build_pr_review_workflow(
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        """构建 PR 审查 workflow（5 节点：start → fetch_diff → review → post_review → end）."""
        return {
            "nodes": [
                {"id": "start", "type": "start", "config": {}, "depends_on": []},
                {
                    "id": "fetch_diff",
                    "type": "tool",
                    "config": {
                        "tool_name": "github_get_pr_diff",
                        "tool_params": {
                            "owner": owner,
                            "repo": repo,
                            "pull_number": pull_number,
                        },
                    },
                    "depends_on": [],
                },
                {
                    "id": "review",
                    "type": "agent",
                    "config": {
                        "agent_name": "pr-code-reviewer",
                        "agent_role": "senior software engineer performing PR code review",
                        "agent_goal": "Review PR diff and produce a structured review report",
                        "task_description": (
                            "Review the PR diff. First call parse_diff to structure it, "
                            "then detect_language, security_check, perf_check, and style_check "
                            "to find deterministic issues. Finally use your expertise for logic/design review.\n"
                            "Output a concise review report with findings and suggestions."
                        ),
                        "template_variables": {
                            "role": "senior software engineer",
                            "language": "auto",
                            "focus_areas": "security, performance, maintainability, correctness",
                            "strictness": "normal",
                            "diff_content": "{{#fetch_diff.output.diff#}}",
                        },
                        "provider": settings.DEFAULT_LLM_PROVIDER,
                        "model": settings.DEFAULT_LLM_MODEL,
                        "temperature": 0.3,
                        "max_iterations": 15,
                    },
                    "depends_on": [],
                },
                {
                    "id": "post_review",
                    "type": "tool",
                    "config": {
                        "tool_name": "github_post_review_comment",
                        "tool_params": {
                            "owner": owner,
                            "repo": repo,
                            "pull_number": pull_number,
                            "body": "{{#review.output#}}",
                        },
                    },
                    "depends_on": [],
                },
                {"id": "end", "type": "end", "config": {}, "depends_on": []},
            ],
            "edges": [
                {"source": "start", "target": "fetch_diff", "condition": None},
                {"source": "fetch_diff", "target": "review", "condition": None},
                {"source": "review", "target": "post_review", "condition": None},
                {"source": "post_review", "target": "end", "condition": None},
            ],
        }
