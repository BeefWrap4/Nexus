"""AutoAgent API — 目标到可执行工作流."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from nexus.security.auth import get_current_user

router = APIRouter(tags=["auto"])


class PlanRequest(BaseModel):
    goal: str = Field(..., description="高层目标描述")
    model: str = Field(default="deepseek-chat")
    provider: str = Field(default="deepseek")


class SubtaskResponse(BaseModel):
    id: str
    name: str
    description: str
    depends_on: list[str] = []
    tool_needs: list[str] = []
    agent_role: str = ""


class PlanResponse(BaseModel):
    goal: str
    subtasks: list[SubtaskResponse]
    workflow_config: dict
    agent_configs: list[dict]
    reasoning: str


@router.post("/plan", response_model=PlanResponse)
async def auto_plan(
    request: Request,
    body: PlanRequest,
    current_user: dict = Depends(get_current_user),
):
    """将高层目标自动分解为可执行工作流 DAG.

    输入: "分析销售数据，找出趋势，生成报告"
    输出: 包含节点和边的完整 WorkflowDefinition + Agent 配置
    """
    from nexus.agent.auto_agent import AutoAgent
    from nexus.agent.llm_client import LLMClient
    from nexus.config import settings

    # 创建 LLM 客户端（用于复杂分解）
    llm_client = LLMClient(
        proxy_url=settings.LITELLM_PROXY_URL,
        api_key=settings.LITELLM_API_KEY,
    )

    agent = AutoAgent(llm_client=llm_client)
    result = await agent.plan_async(body.goal)

    return {
        "goal": result.goal,
        "subtasks": [
            {
                "id": t.id, "name": t.name, "description": t.description,
                "depends_on": t.depends_on, "tool_needs": t.tool_needs,
                "agent_role": t.agent_role,
            }
            for t in result.plan.subtasks
        ],
        "workflow_config": result.blueprint.workflow_config,
        "agent_configs": result.blueprint.agent_configs,
        "reasoning": result.plan.reasoning,
    }


@router.post("/execute")
async def auto_execute(
    request: Request,
    body: PlanRequest,
    current_user: dict = Depends(get_current_user),
):
    """从目标到执行的完整自动化流水线.

    1. 分解目标 → WorkflowDefinition
    2. 创建工作流
    3. 触发执行
    4. 返回 run_id
    """
    from nexus.agent.auto_agent import AutoAgent
    from nexus.agent.llm_client import LLMClient
    from nexus.config import settings
    from nexus.db.database import AsyncSessionLocal
    from nexus.models.workflow import Workflow

    llm_client = LLMClient(
        proxy_url=settings.LITELLM_PROXY_URL,
        api_key=settings.LITELLM_API_KEY,
    )

    # Step 1: Plan
    agent = AutoAgent(llm_client=llm_client)
    result = await agent.plan_async(body.goal)

    if not result.success:
        return {"success": False, "error": result.error}

    # Step 2: Create workflow in DB
    import uuid
    async with AsyncSessionLocal() as session:
        workflow = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=current_user.get("tenant_id", "default"),
            name=f"Auto: {body.goal[:60]}",
            description=body.goal,
            config=result.blueprint.workflow_config,
        )
        session.add(workflow)
        await session.commit()

        # Step 3: Trigger execution (via ARQ)
        from nexus.jobs.workflow import execute_workflow_job
        run_id = str(uuid.uuid4())
        await execute_workflow_job(
            run_id=run_id,
            workflow_id=workflow.id,
            trigger_payload={"goal": body.goal},
        )

        return {
            "success": True,
            "workflow_id": workflow.id,
            "run_id": run_id,
            "plan": {
                "subtasks_count": len(result.plan.subtasks),
                "nodes_count": len(result.blueprint.workflow_config["nodes"]),
                "reasoning": result.plan.reasoning,
            },
        }
