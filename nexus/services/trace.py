"""LLM Trace 服务层.

Phase 6.1: Trace Viewer — 提供 LLM 调用追踪的查询与统计。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.llm_trace import LLMCallTrace
from nexus.services.base import BaseService


class TraceService(BaseService[LLMCallTrace]):
    """LLM Trace Service.

    提供 Trace 的列表查询、详情获取、聚合统计。
    所有数据库操作通过传入的 session 执行，由调用方控制事务边界。
    """

    def __init__(self):
        super().__init__(LLMCallTrace)

    async def list_traces(
        self,
        session: AsyncSession,
        tenant_id: UUID | None,
        run_id: UUID | None = None,
        agent_id: str | None = None,
        model: str | None = None,
        experiment_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[LLMCallTrace], int]:
        """列出 LLM 调用追踪记录.

        Args:
            session: 数据库会话
            tenant_id: 租户ID（None 时不过滤）
            run_id: 按运行实例过滤
            agent_id: 按 Agent 过滤
            model: 按模型过滤
            experiment_id: 按实验ID过滤
            skip: 偏移量
            limit: 每页数量

        Returns:
            (记录列表, 总数量)
        """
        stmt = select(LLMCallTrace).order_by(desc(LLMCallTrace.created_at))

        if tenant_id:
            stmt = stmt.where(LLMCallTrace.tenant_id == str(tenant_id))
        if run_id:
            stmt = stmt.where(LLMCallTrace.run_id == str(run_id))
        if agent_id:
            stmt = stmt.where(LLMCallTrace.agent_id == agent_id)
        if model:
            stmt = stmt.where(LLMCallTrace.model == model)
        if experiment_id:
            stmt = stmt.where(LLMCallTrace.experiment_id == str(experiment_id))

        # 计数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        # 分页
        stmt = stmt.limit(limit).offset(skip)
        result = await session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_trace(
        self,
        session: AsyncSession,
        trace_id: UUID,
        tenant_id: UUID | None = None,
    ) -> LLMCallTrace | None:
        """根据 ID 获取 Trace 详情（含完整 prompt/response）.

        Args:
            session: 数据库会话
            trace_id: Trace ID
            tenant_id: 租户ID（用于隔离校验）

        Returns:
            Trace 实例，不存在则返回 None
        """
        stmt = select(LLMCallTrace).where(LLMCallTrace.id == str(trace_id))
        if tenant_id is not None:
            stmt = stmt.where(LLMCallTrace.tenant_id == str(tenant_id))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_summary(
        self,
        session: AsyncSession,
        tenant_id: UUID | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """按 model 聚合的统计：调用次数、平均耗时、平均 token.

        Args:
            session: 数据库会话
            tenant_id: 租户ID（None 时不过滤）
            start_date: 开始时间
            end_date: 结束时间

        Returns:
            聚合统计列表
        """
        stmt = (
            select(
                LLMCallTrace.model,
                func.count().label("total_calls"),
                func.avg(cast(LLMCallTrace.latency_ms, Float)).label("avg_latency_ms"),
                func.avg(cast(LLMCallTrace.prompt_tokens, Float)).label("avg_prompt_tokens"),
                func.avg(cast(LLMCallTrace.completion_tokens, Float)).label(
                    "avg_completion_tokens"
                ),
                func.sum(LLMCallTrace.total_tokens).label("total_tokens"),
            )
            .group_by(LLMCallTrace.model)
            .order_by(desc("total_calls"))
        )

        if tenant_id:
            stmt = stmt.where(LLMCallTrace.tenant_id == str(tenant_id))
        if start_date:
            stmt = stmt.where(LLMCallTrace.created_at >= start_date)
        if end_date:
            stmt = stmt.where(LLMCallTrace.created_at <= end_date)

        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "model": row.model,
                "total_calls": row.total_calls,
                "avg_latency_ms": round(row.avg_latency_ms or 0, 2),
                "avg_prompt_tokens": round(row.avg_prompt_tokens or 0, 2),
                "avg_completion_tokens": round(row.avg_completion_tokens or 0, 2),
                "total_tokens": row.total_tokens or 0,
            }
            for row in rows
        ]
