"""Dashboard统计API路由."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db, get_tenant_db
from nexus.models import WorkflowRun, Workflow, Agent, HITLTask
from nexus.security.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_tenant_db),
    current_user: dict = Depends(get_current_user),
):
    """获取Dashboard统计信息.
    
    返回工作流、Agent、执行记录等统计数据。
    """
    tenant_id = UUID(current_user.get("tenant_id", "default"))
    
    # 1. 工作流总数
    wf_stmt = select(func.count()).select_from(Workflow).where(Workflow.tenant_id == tenant_id)
    wf_result = await db.execute(wf_stmt)
    workflows_count = wf_result.scalar() or 0
    
    # 2. Agent总数
    agent_stmt = select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id)
    agent_result = await db.execute(agent_stmt)
    agents_count = agent_result.scalar() or 0
    
    # 3. 今日执行次数
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_exec_stmt = (
        select(func.count())
        .select_from(WorkflowRun)
        .where(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.started_at >= today_start
        )
    )
    today_exec_result = await db.execute(today_exec_stmt)
    today_executions = today_exec_result.scalar() or 0
    
    # 4. 待审批任务数
    pending_stmt = (
        select(func.count())
        .select_from(HITLTask)
        .where(
            HITLTask.tenant_id == tenant_id,
            HITLTask.status == "pending"
        )
    )
    pending_result = await db.execute(pending_stmt)
    pending_approvals = pending_result.scalar() or 0
    
    # 5. 执行状态分布
    status_stmt = (
        select(WorkflowRun.status, func.count())
        .where(WorkflowRun.tenant_id == tenant_id)
        .group_by(WorkflowRun.status)
    )
    status_result = await db.execute(status_stmt)
    execution_status = {
        "success": 0,
        "running": 0,
        "failed": 0,
        "cancelled": 0,
    }
    for status, count in status_result.all():
        if status in execution_status:
            execution_status[status] = count
    
    # 6. 缓存统计 (TODO: 实际应该从缓存服务获取)
    cache_stats = {
        "hit_rate": 0.0,
        "hits": 0,
        "tokens_saved": 0,
    }
    
    # 7. LLM调用次数 (TODO: 实际应该从traces获取)
    llm_calls = 0
    
    return {
        "workflows_count": workflows_count,
        "today_executions": today_executions,
        "agents_count": agents_count,
        "pending_approvals": pending_approvals,
        "cache_stats": cache_stats,
        "llm_calls": llm_calls,
        "execution_status": execution_status,
    }
