"""Eval 评估 Service 层.

Phase 6.5: 评估框架 — 批量回归测试与 LLM-as-Judge。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.engine.enums import EvalRunStatus
from nexus.models.eval import EvalRun


class EvalService:
    """EvalRun Service."""

    async def create(
        self,
        session: AsyncSession,
        name: str,
        eval_type: str,
        dataset: list[dict[str, Any]],
        tenant_id: UUID | None,
    ) -> EvalRun:
        """创建评估运行记录."""
        eval_run = EvalRun(
            tenant_id=tenant_id,
            name=name,
            eval_type=eval_type,
            dataset=dataset,
            status=EvalRunStatus.PENDING.value,
        )
        session.add(eval_run)
        await session.flush()
        await session.refresh(eval_run)
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return eval_run

    async def get(
        self,
        session: AsyncSession,
        eval_id: UUID,
        tenant_id: UUID | None = None,
    ) -> EvalRun | None:
        """根据 ID 获取评估运行（可选租户过滤）."""
        stmt = select(EvalRun).where(EvalRun.id == str(eval_id))
        if tenant_id is not None:
            stmt = stmt.where(EvalRun.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID | None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[EvalRun]:
        """列出评估运行记录."""
        stmt = select(EvalRun).order_by(desc(EvalRun.created_at))
        if tenant_id:
            stmt = stmt.where(EvalRun.tenant_id == tenant_id)
        stmt = stmt.offset(skip).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete(
        self,
        session: AsyncSession,
        eval_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """删除评估运行记录（可选租户过滤）."""
        stmt = select(EvalRun).where(EvalRun.id == str(eval_id))
        if tenant_id is not None:
            stmt = stmt.where(EvalRun.tenant_id == tenant_id)
        result = await session.execute(stmt)
        eval_run = result.scalar_one_or_none()
        if not eval_run:
            return False

        await session.delete(eval_run)
        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return True
