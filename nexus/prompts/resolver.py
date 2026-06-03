"""Prompt 解析器.

Phase 6.2: 从模板 ID / 实验配置解析最终 prompt。
集成 A/B 实验分流逻辑。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nexus.prompts.engine import PromptEngine, RenderedPrompt


@dataclass
class ResolvedPrompt:
    """解析后的最终 Prompt."""

    content: str
    template_id: UUID | None = None
    version: int | None = None
    experiment_id: UUID | None = None
    variant_name: str | None = None
    variables_used: list[str] = None
    missing_variables: list[str] = None

    def __post_init__(self):
        if self.variables_used is None:
            self.variables_used = []
        if self.missing_variables is None:
            self.missing_variables = []


class PromptResolver:
    """Prompt 解析器 — 从模板 ID / 实验配置解析最终 prompt.

    核心逻辑：
    1. 如果 template_id 为空，返回 fallback_content
    2. 查询 PromptTemplate 当前版本
    3. 如果该 template 有活跃的 A/B 实验，根据流量选择版本
    4. Jinja2 渲染变量
    5. 返回 ResolvedPrompt
    """

    def __init__(self, db_session=None):
        self.engine = PromptEngine()
        self._db = db_session

    async def resolve(
        self,
        template_id: UUID | None,
        fallback_content: str,
        variables: dict[str, Any] | None = None,
        user_id: str | None = None,
        db_session=None,
    ) -> ResolvedPrompt:
        """解析最终 prompt 内容.

        Args:
            template_id: PromptTemplate ID
            fallback_content: 如果没有模板，返回此内容
            variables: Jinja2 渲染变量
            user_id: 用于 A/B 实验的确定性分流
            db_session: 数据库会话（可选，优先于构造函数传入的）

        Returns:
            ResolvedPrompt
        """
        session = db_session or self._db

        if not template_id or not session:
            return ResolvedPrompt(content=fallback_content)

        # 查询 PromptTemplate
        from sqlalchemy import select
        from nexus.models.prompt import PromptTemplate

        result = await session.execute(
            select(PromptTemplate).where(PromptTemplate.id == str(template_id))
        )
        template = result.scalar_one_or_none()
        if not template:
            return ResolvedPrompt(content=fallback_content)

        # 检查是否有活跃的 A/B 实验
        experiment, variant = await self._select_experiment_variant(
            session, template_id, user_id
        )

        version = template.current_version
        experiment_id = None
        variant_name = None

        if experiment and variant:
            version = variant.template_version
            experiment_id = experiment.id
            variant_name = variant.name

        # 查询指定版本的模板内容
        from nexus.models.prompt import PromptTemplateVersion

        version_result = await session.execute(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == str(template_id))
            .where(PromptTemplateVersion.version == version)
        )
        version_record = version_result.scalar_one_or_none()

        if not version_record:
            # 回退到 fallback
            return ResolvedPrompt(
                content=fallback_content,
                template_id=template_id,
                version=version,
            )

        # Jinja2 渲染
        rendered = self.engine.render(version_record.content, variables or {})

        return ResolvedPrompt(
            content=rendered.content,
            template_id=template_id,
            version=version,
            experiment_id=experiment_id,
            variant_name=variant_name,
            variables_used=rendered.variables_used,
            missing_variables=rendered.missing_variables,
        )

    async def _select_experiment_variant(
        self,
        session,
        template_id: UUID,
        user_id: str | None,
    ) -> tuple[Any, Any]:
        """选择实验变体.

        如果有 running 的实验：
        - 如果有 user_id，使用确定性哈希分流（保证同一用户始终进入同一组）
        - 否则使用随机分流

        Returns:
            (experiment, variant) 或 (None, None)
        """
        from sqlalchemy import select
        from nexus.models.experiment import PromptExperiment, PromptExperimentVariant

        exp_result = await session.execute(
            select(PromptExperiment)
            .where(PromptExperiment.template_id == str(template_id))
            .where(PromptExperiment.status == "running")
        )
        experiment = exp_result.scalar_one_or_none()
        if not experiment:
            return None, None

        # 获取所有变体
        var_result = await session.execute(
            select(PromptExperimentVariant)
            .where(PromptExperimentVariant.experiment_id == str(experiment.id))
        )
        variants = list(var_result.scalars().all())
        if not variants:
            return None, None

        # 分流
        if user_id:
            # 确定性哈希：user_id 的 hash % 100
            import hashlib

            hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
            bucket = hash_val % 100
        else:
            bucket = random.randint(0, 99)

        cumulative = 0
        for variant in variants:
            cumulative += variant.traffic_percentage
            if bucket < cumulative:
                return experiment, variant

        # fallback 到最后一个
        return experiment, variants[-1]
