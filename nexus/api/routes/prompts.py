"""Prompt 模板管理 API.

Phase 6.2-6.3: Prompt CRUD + 版本管理 + A/B 实验。
"""

from __future__ import annotations

import difflib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.models.prompt import PromptTemplate, PromptTemplateVersion
from nexus.security.auth import get_current_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class PromptTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    template_type: str = "system"
    content: str = Field(..., min_length=1)
    variables: list[str] = Field(default_factory=list)
    change_notes: str = "Initial version"


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    variables: list[str] | None = None
    change_notes: str = "Updated"


class PromptTemplateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None = None
    template_type: str
    current_version: int
    created_at: Any

    model_config = {"from_attributes": True}


class PromptTemplateVersionOut(BaseModel):
    id: UUID
    template_id: UUID
    version: int
    content: str
    variables: list[str] | None = None
    change_notes: str | None = None
    created_at: Any

    model_config = {"from_attributes": True}


class PromptDiffOut(BaseModel):
    version_a: int
    version_b: int
    diff: str


# ---------------------------------------------------------------------------
# CRUD Endpoints
# ---------------------------------------------------------------------------

@router.post("/prompts", response_model=PromptTemplateOut)
async def create_prompt(
    data: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """创建 PromptTemplate（自动生成 v1）."""
    tenant_id = getattr(current_user, "tenant_id", None)
    user_id = getattr(current_user, "id", None)

    template = PromptTemplate(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        template_type=data.template_type,
        current_version=1,
        created_by=user_id,
    )
    db.add(template)
    await db.flush()  # 获取 template.id

    version = PromptTemplateVersion(
        template_id=template.id,
        version=1,
        content=data.content,
        variables=data.variables,
        change_notes=data.change_notes,
        created_by=user_id,
    )
    db.add(version)
    await db.commit()  # TODO: extract to PromptService
    await db.refresh(template)
    return template


@router.get("/prompts", response_model=list[PromptTemplateOut])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出 PromptTemplates."""
    tenant_id = getattr(current_user, "tenant_id", None)
    stmt = select(PromptTemplate).order_by(desc(PromptTemplate.updated_at))
    if tenant_id:
        stmt = stmt.where(PromptTemplate.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/prompts/{prompt_id}", response_model=PromptTemplateOut)
async def get_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取 PromptTemplate（含当前版本内容）."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == str(prompt_id))
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return template


@router.get("/prompts/{prompt_id}/content")
async def get_prompt_content(
    prompt_id: UUID,
    version: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取 Prompt 内容（默认当前版本，可指定历史版本）."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == str(prompt_id))
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    target_version = version or template.current_version
    version_result = await db.execute(
        select(PromptTemplateVersion)
        .where(PromptTemplateVersion.template_id == str(prompt_id))
        .where(PromptTemplateVersion.version == target_version)
    )
    version_record = version_result.scalar_one_or_none()
    if not version_record:
        raise HTTPException(status_code=404, detail=f"Version {target_version} not found")

    return {
        "template_id": prompt_id,
        "version": target_version,
        "content": version_record.content,
        "variables": version_record.variables,
    }


@router.put("/prompts/{prompt_id}", response_model=PromptTemplateOut)
async def update_prompt(
    prompt_id: UUID,
    data: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """更新 Prompt — 自动创建新版本."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == str(prompt_id))
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    user_id = getattr(current_user, "id", None)

    # 更新模板元数据
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description

    # 如果 content 有变更，创建新版本
    if data.content is not None:
        new_version = template.current_version + 1
        version = PromptTemplateVersion(
            template_id=template.id,
            version=new_version,
            content=data.content,
            variables=data.variables if data.variables is not None else [],
            change_notes=data.change_notes,
            created_by=user_id,
        )
        db.add(version)
        template.current_version = new_version

    await db.commit()  # TODO: extract to PromptService
    await db.refresh(template)
    return template


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """删除 PromptTemplate（级联删除所有版本）."""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == str(prompt_id))
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    await db.delete(template)
    await db.commit()  # TODO: extract to PromptService

    return {"id": prompt_id, "deleted": True}


# ---------------------------------------------------------------------------
# 版本管理
# ---------------------------------------------------------------------------

@router.get("/prompts/{prompt_id}/versions", response_model=list[PromptTemplateVersionOut])
async def list_versions(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出所有版本历史."""
    result = await db.execute(
        select(PromptTemplateVersion)
        .where(PromptTemplateVersion.template_id == str(prompt_id))
        .order_by(desc(PromptTemplateVersion.version))
    )
    return list(result.scalars().all())


@router.get("/prompts/{prompt_id}/versions/{version_a}/diff/{version_b}", response_model=PromptDiffOut)
async def diff_versions(
    prompt_id: UUID,
    version_a: int,
    version_b: int,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """对比两个版本的差异（统一 diff 格式）."""
    stmt = (
        select(PromptTemplateVersion)
        .where(PromptTemplateVersion.template_id == str(prompt_id))
        .where(PromptTemplateVersion.version.in_([version_a, version_b]))
    )
    result = await db.execute(stmt)
    versions = {v.version: v for v in result.scalars().all()}

    if version_a not in versions or version_b not in versions:
        raise HTTPException(status_code=404, detail="One or both versions not found")

    diff = difflib.unified_diff(
        versions[version_a].content.splitlines(keepends=True),
        versions[version_b].content.splitlines(keepends=True),
        fromfile=f"v{version_a}",
        tofile=f"v{version_b}",
    )

    return PromptDiffOut(
        version_a=version_a,
        version_b=version_b,
        diff="".join(diff),
    )


# ---------------------------------------------------------------------------
# A/B 实验管理
# ---------------------------------------------------------------------------

class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    variants: list[dict] = Field(..., description="[{name, version, traffic_percentage}]")


class ExperimentOut(BaseModel):
    id: UUID
    name: str
    template_id: UUID
    status: str
    variants: list[dict] | None = None
    created_at: Any | None = None


@router.post("/prompts/{prompt_id}/experiments", response_model=ExperimentOut)
async def create_experiment(
    prompt_id: UUID,
    data: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """为 PromptTemplate 创建 A/B 实验."""
    tenant_id = getattr(current_user, "tenant_id", None)
    user_id = getattr(current_user, "id", None)

    # 验证 template 存在
    template_result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == str(prompt_id))
    )
    template = template_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    from nexus.models.experiment import PromptExperiment, PromptExperimentVariant

    experiment = PromptExperiment(
        tenant_id=tenant_id,
        name=data.name,
        template_id=template.id,
        status="running",
    )
    db.add(experiment)
    await db.flush()

    # 创建变体
    total_traffic = 0
    for v in data.variants:
        total_traffic += v.get("traffic_percentage", 0)
        variant = PromptExperimentVariant(
            experiment_id=experiment.id,
            name=v["name"],
            template_version=v["version"],
            traffic_percentage=v["traffic_percentage"],
        )
        db.add(variant)

    if total_traffic != 100:
        raise HTTPException(status_code=400, detail=f"Traffic percentages must sum to 100, got {total_traffic}")

    await db.commit()  # TODO: extract to ExperimentService
    await db.refresh(experiment)

    # 加载 variants
    var_result = await db.execute(
        select(PromptExperimentVariant)
        .where(PromptExperimentVariant.experiment_id == str(experiment.id))
    )
    experiment.variants = list(var_result.scalars().all())
    return experiment


@router.get("/prompts/{prompt_id}/experiments", response_model=list[ExperimentOut])
async def list_experiments(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出 PromptTemplate 的所有实验."""
    from nexus.models.experiment import PromptExperiment

    result = await db.execute(
        select(PromptExperiment)
        .where(PromptExperiment.template_id == str(prompt_id))
        .order_by(desc(PromptExperiment.created_at))
    )
    return list(result.scalars().all())


@router.post("/experiments/{exp_id}/pause")
async def pause_experiment(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """暂停实验."""
    from nexus.models.experiment import PromptExperiment

    result = await db.execute(
        select(PromptExperiment).where(PromptExperiment.id == str(exp_id))
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    experiment.status = "paused"

    return {"id": exp_id, "status": "paused"}


@router.get("/experiments/{exp_id}/results")
async def get_experiment_results(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取实验结果（各变体指标）."""
    from nexus.models.experiment import PromptExperiment, PromptExperimentVariant

    exp_result = await db.execute(
        select(PromptExperiment).where(PromptExperiment.id == str(exp_id))
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    var_result = await db.execute(
        select(PromptExperimentVariant)
        .where(PromptExperimentVariant.experiment_id == str(exp_id))
    )
    variants = var_result.scalars().all()

    return {
        "experiment_id": exp_id,
        "name": experiment.name,
        "status": experiment.status,
        "variants": [
            {
                "name": v.name,
                "version": v.template_version,
                "traffic_percentage": v.traffic_percentage,
                "total_calls": v.total_calls,
                "avg_latency_ms": v.avg_latency_ms,
                "avg_tokens": v.avg_tokens,
            }
            for v in variants
        ],
    }
