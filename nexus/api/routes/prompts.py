"""Prompt 模板管理 API.

Phase 6.2-6.3: Prompt CRUD + 版本管理 + A/B 实验。
"""

from __future__ import annotations

import difflib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.security.auth import get_current_user
from nexus.services.prompt import (
    ExperimentService,
    PromptTemplateService,
    PromptVersionService,
)

router = APIRouter()

prompt_service = PromptTemplateService()
version_service = PromptVersionService()
experiment_service = ExperimentService()


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

    model_config = ConfigDict(from_attributes=True)


class PromptTemplateVersionOut(BaseModel):
    id: UUID
    template_id: UUID
    version: int
    content: str
    variables: list[str] | None = None
    change_notes: str | None = None
    created_at: Any

    model_config = ConfigDict(from_attributes=True)


class PromptDiffOut(BaseModel):
    version_a: int
    version_b: int
    diff: str


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    variants: list[dict[str, Any]] = Field(default_factory=list)


class ExperimentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    template_id: UUID
    status: str
    created_at: Any
    variants: list[dict[str, Any]] | None = None

    model_config = ConfigDict(from_attributes=True)


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
    tenant_id = current_user.get("tenant_id", "default")
    user_id = getattr(current_user, "id", None)

    return await prompt_service.create(
        db,
        name=data.name,
        description=data.description,
        template_type=data.template_type,
        content=data.content,
        variables=data.variables,
        change_notes=data.change_notes,
        tenant_id=tenant_id,
        user_id=user_id,
    )


@router.get("/prompts", response_model=list[PromptTemplateOut])
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出 PromptTemplates."""
    tenant_id = current_user.get("tenant_id", "default")
    return await prompt_service.list(db, tenant_id=tenant_id)


@router.get("/prompts/{prompt_id}", response_model=PromptTemplateOut)
async def get_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取 PromptTemplate（含当前版本内容）."""
    tenant_id = current_user.get("tenant_id", "default")
    template = await prompt_service.get(db, prompt_id, tenant_id)
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
    tenant_id = current_user.get("tenant_id", "default")
    template = await prompt_service.get(db, prompt_id, tenant_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    target_version = version or template.current_version
    version_record = await version_service.get_by_version(db, prompt_id, target_version)
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
    user_id = getattr(current_user, "id", None)

    template = await prompt_service.update(
        db,
        template_id=prompt_id,
        name=data.name,
        description=data.description,
        content=data.content,
        variables=data.variables,
        change_notes=data.change_notes,
        user_id=user_id,
    )
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return template


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """删除 PromptTemplate（级联删除所有版本）."""
    ok = await prompt_service.delete(db, prompt_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Prompt template not found")
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
    tenant_id = current_user.get("tenant_id", "default")
    return await version_service.list_by_template(db, prompt_id, tenant_id)


@router.get("/prompts/{prompt_id}/versions/{version_a}/diff/{version_b}", response_model=PromptDiffOut)
async def diff_versions(
    prompt_id: UUID,
    version_a: int,
    version_b: int,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """对比两个版本的差异（统一 diff 格式）."""
    tenant_id = current_user.get("tenant_id", "default")
    versions = {
        v.version: v
        for v in await version_service.list_by_template(db, prompt_id, tenant_id)
    }

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

@router.post("/prompts/{prompt_id}/experiments", response_model=ExperimentOut)
async def create_experiment(
    prompt_id: UUID,
    data: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """创建 Prompt A/B 实验."""
    tenant_id = current_user.get("tenant_id", "default")

    # 验证 template 存在（同时验证租户归属）
    template = await prompt_service.get(db, prompt_id, tenant_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")

    # 验证流量分配
    total_traffic = sum(v.get("traffic_percentage", 0) for v in data.variants)
    if total_traffic != 100:
        raise HTTPException(
            status_code=400,
            detail=f"Traffic percentages must sum to 100, got {total_traffic}",
        )

    return await experiment_service.create(
        db,
        name=data.name,
        template_id=prompt_id,
        variants=data.variants,
        tenant_id=tenant_id,
    )


@router.get("/prompts/{prompt_id}/experiments", response_model=list[ExperimentOut])
async def list_experiments(
    prompt_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """列出 PromptTemplate 的所有实验."""
    tenant_id = current_user.get("tenant_id", "default")
    return await experiment_service.list_by_template(db, prompt_id, tenant_id)


@router.post("/experiments/{exp_id}/pause")
async def pause_experiment(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """暂停实验."""
    tenant_id = current_user.get("tenant_id", "default")
    experiment = await experiment_service.update_status(db, exp_id, "paused", tenant_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {"id": exp_id, "status": "paused"}


@router.post("/experiments/{exp_id}/resume")
async def resume_experiment(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """恢复实验."""
    tenant_id = current_user.get("tenant_id", "default")
    experiment = await experiment_service.update_status(db, exp_id, "running", tenant_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {"id": exp_id, "status": "running"}


@router.get("/experiments/{exp_id}/results")
async def get_experiment_results(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取实验结果汇总."""
    tenant_id = current_user.get("tenant_id", "default")
    experiment = await experiment_service.get(db, exp_id, tenant_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # 计算汇总指标
    variant_results = []
    for variant in experiment.variants:
        variant_results.append({
            "name": variant.name,
            "version": variant.template_version,
            "traffic_percentage": variant.traffic_percentage,
            "total_calls": variant.total_calls,
            "avg_latency_ms": variant.avg_latency_ms,
            "avg_tokens": variant.avg_tokens,
        })

    return {
        "experiment_id": exp_id,
        "status": experiment.status,
        "variant_results": variant_results,
    }
