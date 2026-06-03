"""Prompt 模板 Service 层.

Phase 6: Prompt 管理 / 版本管理 / A/B 实验
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.experiment import PromptExperiment, PromptExperimentVariant
from nexus.models.prompt import PromptTemplate, PromptTemplateVersion


class PromptTemplateService:
    """PromptTemplate Service."""

    async def create(
        self,
        session: AsyncSession,
        name: str,
        description: str,
        template_type: str,
        content: str,
        variables: list[str],
        change_notes: str,
        tenant_id: UUID | None,
        user_id: UUID | None = None,
    ) -> PromptTemplate:
        """创建 PromptTemplate（自动生成 v1 版本）."""
        template = PromptTemplate(
            tenant_id=tenant_id,
            name=name,
            description=description,
            template_type=template_type,
            current_version=1,
            created_by=user_id,
        )
        session.add(template)
        await session.flush()

        version = PromptTemplateVersion(
            template_id=template.id,
            version=1,
            content=content,
            variables=variables,
            change_notes=change_notes,
            created_by=user_id,
        )
        session.add(version)
        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        await session.refresh(template)
        return template

    async def get(
        self,
        session: AsyncSession,
        template_id: UUID,
        tenant_id: UUID | None = None,
    ) -> PromptTemplate | None:
        """根据 ID 获取 PromptTemplate（可选租户过滤）."""
        stmt = select(PromptTemplate).where(PromptTemplate.id == str(template_id))
        if tenant_id is not None:
            stmt = stmt.where(PromptTemplate.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        session: AsyncSession,
        tenant_id: UUID | None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[PromptTemplate]:
        """列出 PromptTemplates."""
        stmt = select(PromptTemplate).order_by(desc(PromptTemplate.updated_at))
        if tenant_id:
            stmt = stmt.where(PromptTemplate.tenant_id == tenant_id)
        stmt = stmt.offset(skip).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        session: AsyncSession,
        template_id: UUID,
        name: str | None,
        description: str | None,
        content: str | None,
        variables: list[str] | None,
        change_notes: str,
        user_id: UUID | None = None,
    ) -> PromptTemplate | None:
        """更新 PromptTemplate — 自动创建新版本（如果 content 变更）."""
        result = await session.execute(
            select(PromptTemplate).where(PromptTemplate.id == str(template_id))
        )
        template = result.scalar_one_or_none()
        if not template:
            return None

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description

        if content is not None:
            new_version = template.current_version + 1
            version = PromptTemplateVersion(
                template_id=template.id,
                version=new_version,
                content=content,
                variables=variables if variables is not None else [],
                change_notes=change_notes,
                created_by=user_id,
            )
            session.add(version)
            template.current_version = new_version

        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        await session.refresh(template)
        return template

    async def delete(
        self,
        session: AsyncSession,
        template_id: UUID,
    ) -> bool:
        """删除 PromptTemplate（级联删除所有版本）."""
        result = await session.execute(
            select(PromptTemplate).where(PromptTemplate.id == str(template_id))
        )
        template = result.scalar_one_or_none()
        if not template:
            return False

        await session.delete(template)
        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        return True


class PromptVersionService:
    """PromptTemplateVersion Service."""

    async def list_by_template(
        self,
        session: AsyncSession,
        template_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[PromptTemplateVersion]:
        """列出 PromptTemplate 的所有版本（可选租户过滤）."""
        stmt = (
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == str(template_id))
        )
        if tenant_id is not None:
            stmt = stmt.join(
                PromptTemplate,
                PromptTemplateVersion.template_id == PromptTemplate.id,
            ).where(PromptTemplate.tenant_id == tenant_id)
        stmt = stmt.order_by(desc(PromptTemplateVersion.version))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_version(
        self,
        session: AsyncSession,
        template_id: UUID,
        version: int,
    ) -> PromptTemplateVersion | None:
        """根据版本号获取 PromptTemplateVersion."""
        result = await session.execute(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == str(template_id))
            .where(PromptTemplateVersion.version == version)
        )
        return result.scalar_one_or_none()


class ExperimentService:
    """PromptExperiment Service."""

    async def create(
        self,
        session: AsyncSession,
        name: str,
        template_id: UUID,
        variants: list[dict[str, Any]],
        tenant_id: UUID | None,
    ) -> PromptExperiment:
        """创建 PromptExperiment（含变体）."""
        experiment = PromptExperiment(
            tenant_id=tenant_id,
            name=name,
            template_id=template_id,
            status="running",
        )
        session.add(experiment)
        await session.flush()

        for v in variants:
            variant = PromptExperimentVariant(
                experiment_id=experiment.id,
                name=v["name"],
                template_version=v["version"],
                traffic_percentage=v.get("traffic_percentage", 0),
            )
            session.add(variant)

        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        await session.refresh(experiment)

        # 加载 variants
        var_result = await session.execute(
            select(PromptExperimentVariant)
            .where(PromptExperimentVariant.experiment_id == str(experiment.id))
        )
        experiment.variants = list(var_result.scalars().all())
        return experiment

    async def list_by_template(
        self,
        session: AsyncSession,
        template_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[PromptExperiment]:
        """列出 PromptTemplate 的所有实验（可选租户过滤）."""
        stmt = (
            select(PromptExperiment)
            .where(PromptExperiment.template_id == str(template_id))
        )
        if tenant_id is not None:
            stmt = stmt.where(PromptExperiment.tenant_id == tenant_id)
        stmt = stmt.order_by(desc(PromptExperiment.created_at))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get(
        self,
        session: AsyncSession,
        experiment_id: UUID,
        tenant_id: UUID | None = None,
    ) -> PromptExperiment | None:
        """根据 ID 获取实验（可选租户过滤）."""
        stmt = select(PromptExperiment).where(
            PromptExperiment.id == str(experiment_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(PromptExperiment.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        session: AsyncSession,
        experiment_id: UUID,
        status: str,
        tenant_id: UUID | None = None,
    ) -> PromptExperiment | None:
        """更新实验状态（可选租户过滤）."""
        stmt = select(PromptExperiment).where(
            PromptExperiment.id == str(experiment_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(PromptExperiment.tenant_id == tenant_id)
        result = await session.execute(stmt)
        experiment = result.scalar_one_or_none()
        if not experiment:
            return None

        experiment.status = status
        await session.flush()
        # NOTE: 不在这里 commit，事务边界由调用方控制
        await session.refresh(experiment)
        return experiment
