"""节点执行器集合.

为WorkflowEngine提供各类节点的具体执行逻辑:
- AgentNodeExecutor: 调用Agent执行
- ToolNodeExecutor: 调用ToolRegistry
- HITLNodeExecutor: 调用HITLController
- ConditionNodeExecutor: 调用RouterEngine
- StartNodeExecutor / EndNodeExecutor: 边界节点处理

设计来源:
- WAT PhaseController: 阶段执行编排
- LangGraph: 节点函数即执行器
- Dify: 节点类型标准化
"""

import asyncio
import os
from typing import Any

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.crew import Crew, CrewConfig, CrewMode
from nexus.agent.llm_client import LLMClient
from nexus.config import settings
from nexus.engine.hitl_controller import HITLController, HITLResponse, HITLType
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.engine.enums import NodeStatus, RunStatus
from nexus.engine.workflow_engine import Node, NodeExecutor, NodeResult
from nexus.exceptions import AgentNotFoundException, ToolNotFoundException
from nexus.observability.llm_tracer import set_trace_context
from nexus.tools.registry import ToolRegistry


class StartNodeExecutor(NodeExecutor):
    """开始节点执行器.

    职责:
    1. 将trigger_payload注入到工作流变量池
    2. 设置初始运行变量
    3. 标记工作流正式开始
    """

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行开始节点."""
        # 将trigger_payload中的数据提升到run_vars
        payload_mapping = node.config.get("output_mapping", {})
        if payload_mapping:
            for var_name, payload_key in payload_mapping.items():
                state.run_vars[var_name] = state.trigger_payload.get(payload_key)
        else:
            # 默认: 将整个payload作为run.trigger
            state.run_vars["trigger"] = state.trigger_payload

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={"trigger_payload": state.trigger_payload},
        )


class EndNodeExecutor(NodeExecutor):
    """结束节点执行器.

    职责:
    1. 聚合最终输出
    2. 将指定节点输出映射到工作流output
    3. 标记工作流完成
    """

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行结束节点."""
        output_config = node.config.get("output", {})

        # 支持两种输出模式:
        # 1. 直接指定输出表达式
        # 2. 从上游节点聚合
        final_output = {}

        if "expression" in output_config:
            # 表达式模式: 如 "{{#last_agent.output#}}"
            variable_pool = VariablePool()
            resolved = variable_pool.resolve(output_config["expression"], state)
            final_output["result"] = resolved
        elif "mappings" in output_config:
            # 映射模式: { "summary": "{{#agent_a.output.summary#}}" }
            variable_pool = VariablePool()
            for key, expr in output_config["mappings"].items():
                final_output[key] = variable_pool.resolve(expr, state)
        else:
            # 默认: 聚合所有上游节点的输出
            final_output = dict(state.node_outputs)

        # 设置工作流最终输出
        state.output = final_output
        state.status = RunStatus.COMPLETED

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output=final_output,
        )


class AgentNodeExecutor(NodeExecutor):
    """Agent节点执行器.

    职责:
    1. 根据配置查找或创建Agent实例
    2. 注入 ToolRegistry 和持久化 Memory
    3. 构建Task对象
    4. 调用Agent.execute()并返回结果
    """

    def __init__(
        self,
        agent_factory: Any = None,
        default_agent: BaseAgent = None,
        tool_registry: Any = None,
        memory_backend: Any = None,
    ):
        self.agent_factory = agent_factory
        self.default_agent = default_agent
        self.tool_registry = tool_registry
        self.memory_backend = memory_backend
        self._agent_cache: dict[str, BaseAgent] = {}

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行Agent节点.

        从 node.config 读取配置参数，创建 Agent 实例并执行任务。
        Phase 4 增强：注入 ToolRegistry 和 Redis-backed Memory。
        """
        config = node.config

        # 1. 从 node.config 读取 Agent 配置
        agent_name = config.get("agent_name", f"agent_{node.id}")
        agent_role = config.get("agent_role", "")
        agent_goal = config.get("agent_goal", "")
        task_description = config.get("task_description", config.get("task", ""))
        tools_list = config.get("tools", [])  # 显式配置的工具白名单

        # 2. 从 node.config 读取模型配置
        model = config.get("model", settings.DEFAULT_LLM_MODEL)
        provider = config.get("provider", settings.DEFAULT_LLM_PROVIDER)

        # 3. 创建 LLMClient 实例
        provider_base_urls = {
            "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
            "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
            "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
            "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
            "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
        }

        if provider in provider_base_urls:
            direct_url, env_key = provider_base_urls[provider]
            api_key = os.environ.get(env_key)
            if api_key:
                base_url = direct_url
            else:
                base_url = settings.LITELLM_PROXY_URL
                api_key = settings.LITELLM_API_KEY
        else:
            base_url = settings.LITELLM_PROXY_URL
            api_key = settings.LITELLM_API_KEY

        llm_client = LLMClient(proxy_url=base_url, api_key=api_key)

        # 4. 创建持久化 AgentMemory（如果 backend 可用）
        memory = None
        if self.memory_backend and settings.AGENT_MEMORY_ENABLED:
            from nexus.agent.memory import AgentMemory

            memory = AgentMemory(
                agent_id=f"{run_id}:{node.id}",
                backend=self.memory_backend,
            )

        # 5. 创建 AgentConfig + BaseAgent 实例（注入完整依赖）
        # Phase 8: 支持从 node.config 传递 prompt template 和参数
        template_id = config.get("system_prompt_template_id")
        if template_id:
            from uuid import UUID
            if isinstance(template_id, str):
                template_id = UUID(template_id)

        agent_config = AgentConfig(
            name=agent_name,
            role=agent_role,
            goal=agent_goal,
            system_prompt=config.get("system_prompt", ""),
            system_prompt_template_id=template_id,
            template_variables=config.get("template_variables", {}),
            provider=provider,
            model=model,
            temperature=config.get("temperature", settings.DEFAULT_LLM_TEMPERATURE),
            max_tokens=config.get("max_tokens", settings.DEFAULT_LLM_MAX_TOKENS),
            max_iterations=config.get("max_iterations", settings.DEFAULT_MAX_ITERATIONS),
            tools=tools_list,
            memory_enabled=settings.AGENT_MEMORY_ENABLED,
            enable_semantic_cache=config.get("enable_semantic_cache", False),
        )
        agent = BaseAgent(
            config=agent_config,
            llm_client=llm_client,
            memory=memory,
            tool_registry=self.tool_registry,
        )

        # 6. 创建 Task
        task = Task(description=task_description)

        # 7. 执行 Agent（设置 trace context 供 LLM 调用追踪）
        trace_token = set_trace_context(
            run_id=run_id,
            node_id=node.id,
            tenant_id=state.env_vars.get("tenant_id"),
        )
        try:
            result = await agent.execute(
                task,
                context={
                    "run_id": run_id,
                    "node_id": node.id,
                    "tenant_id": state.env_vars.get("tenant_id"),
                    "user_id": state.env_vars.get("user_id"),
                },
            )

            # 8. 将Agent输出写入run_vars（供下游节点引用）
            output_key = config.get("output_key", node.id)
            state.run_vars[output_key] = result.output

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "output": result.output,
                    "reasoning": result.reasoning,
                    "tool_calls": result.tool_calls,
                    "confidence": result.confidence,
                },
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )
        finally:
            from nexus.observability.llm_tracer import TRACE_CONTEXT
            TRACE_CONTEXT.reset(trace_token)

    async def _get_agent(self, config: dict[str, Any]) -> BaseAgent | None:
        """获取Agent实例."""
        agent_id = config.get("agent_id")

        # 从缓存获取
        if agent_id and agent_id in self._agent_cache:
            return self._agent_cache[agent_id]

        # 使用工厂创建
        if agent_id and self.agent_factory:
            agent = self.agent_factory(agent_id)
            if agent:
                self._agent_cache[agent_id] = agent
            return agent

        # 使用内联配置创建
        if "agent_config" in config:
            agent_config = AgentConfig(**config["agent_config"])
            agent = BaseAgent(config=agent_config)
            if agent_id:
                self._agent_cache[agent_id] = agent
            return agent

        # 使用默认Agent
        return self.default_agent


class ToolNodeExecutor(NodeExecutor):
    """工具节点执行器.

    职责:
    1. 从ToolRegistry查找工具
    2. 解析并校验输入参数
    3. 执行工具并返回结果
    4. 支持流式输出（SSE → EventBus → WebSocket）
    """

    def __init__(self, tool_registry: ToolRegistry, event_bus=None):
        self.tool_registry = tool_registry
        self.event_bus = event_bus

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行工具节点."""
        config = node.config
        tool_name = config.get("tool_name")

        if not tool_name:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "Tool name not specified in node config"},
            )

        # 查找工具定义
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"Tool '{tool_name}' not found"},
            )

        # 构建执行上下文
        context = {
            "run_id": run_id,
            "node_id": node.id,
            "tenant_id": state.env_vars.get("tenant_id"),
            "user_id": state.env_vars.get("user_id"),
        }

        # 流式执行（SSE → EventBus → WebSocket）
        if tool.config.get("stream"):
            return await self._execute_stream(node, tool, inputs, context, run_id)

        # 普通执行
        try:
            result = await self.tool_registry.execute(
                tool_name=tool_name,
                params=inputs,
                context=context,
            )

            if result.success:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output={
                        "data": result.data,
                        "metadata": result.metadata,
                    },
                )
            else:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    error={"message": result.error},
                )

        except ToolNotFoundException:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"Tool '{tool_name}' not found"},
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )

    async def _execute_stream(
        self,
        node: Node,
        tool,
        inputs: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
    ) -> NodeResult:
        """执行流式工具（SSE）.

        逐 chunk 消费 SSE 响应，通过 EventBus 发布到 WebSocket 客户端。
        最终返回聚合的完整结果。
        """
        import httpx

        config = tool.config
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = dict(config.get("headers", {}))
        timeout = config.get("timeout", 30)

        # 注入认证头
        auth = tool.auth_config
        if auth:
            auth_type = auth.get("type", "")
            if auth_type == "header":
                headers[auth["key"]] = auth["value"]
            elif auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth.get('token', '')}"

        # URL 模板替换 + 参数过滤（复用 registry 逻辑）
        import re
        url_vars = re.findall(r"\{(\w+)\}", url)
        body_params = dict(inputs)
        for var in url_vars:
            if var in body_params:
                url = url.replace(f"{{{var}}}", str(body_params.pop(var)))

        schema = tool.schema
        if schema and schema.get("properties"):
            allowed_keys = set(schema["properties"].keys())
            body_params = {k: v for k, v in body_params.items() if k in allowed_keys}

        collected_chunks = []

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_kwargs = {"headers": headers}
                if method == "POST":
                    request_kwargs["json"] = body_params
                elif method == "GET":
                    request_kwargs["params"] = body_params

                async with client.stream(method, url, **request_kwargs) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk = line[6:].strip()
                            if chunk == "[DONE]":
                                break
                            collected_chunks.append(chunk)

                            # 通过 EventBus 推送 chunk（实时传输到前端）
                            if self.event_bus:
                                await self.event_bus.publish({
                                    "type": "stream_chunk",
                                    "run_id": run_id,
                                    "node_id": node.id,
                                    "tool_name": tool.name,
                                    "chunk": chunk,
                                    "index": len(collected_chunks) - 1,
                                })

            full_text = "".join(collected_chunks)

            # 发送流结束标记
            if self.event_bus:
                await self.event_bus.publish({
                    "type": "stream_end",
                    "run_id": run_id,
                    "node_id": node.id,
                    "tool_name": tool.name,
                    "total_chunks": len(collected_chunks),
                })

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "data": {"response": full_text, "streamed": True},
                    "metadata": {"chunks": len(collected_chunks), "tool": tool.name},
                },
            )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )


class HITLNodeExecutor(NodeExecutor):
    """人工在环节点执行器.

    职责:
    1. 创建HITL审批任务
    2. 暂停工作流等待人工响应
    3. 收到响应后恢复并返回结果
    """

    def __init__(
        self,
        hitl_controller: HITLController = None,
        default_timeout: int = None,
    ):
        self.hitl_controller = hitl_controller
        self.default_timeout = default_timeout or 30  # 默认30秒超时

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行HITL节点."""
        config = node.config

        # 1. 创建审批任务
        task = await self.hitl_controller.create_task(
            run_id=run_id,
            node_id=node.id,
            task_type=HITLType(config.get("hitl_type", "approve")),
            title=config.get("title", "Approval Required"),
            description=config.get("description", ""),
            context={
                "inputs": inputs,
                "node_outputs": state.node_outputs,
                **config.get("extra_context", {}),
            },
            assignee_id=config.get("assignee_id"),
        )

        # 2. 暂停工作流状态
        state.status = RunStatus.PAUSED

        # 3. 等待响应（阻塞直到人工介入）
        try:
            timeout = config.get("timeout_seconds", self.default_timeout)
            default_on_timeout = None

            # 如果配置了超时自动处理策略
            if config.get("auto_on_timeout"):
                default_on_timeout = await self.hitl_controller.get_default_timeout_response(
                    task.task_type
                )

            response = await self.hitl_controller.wait_for_response(
                task_id=task.id,
                timeout=timeout,
                default_on_timeout=default_on_timeout,
            )

            # 4. 恢复工作流状态
            state.status = RunStatus.RUNNING
            state.human_input = {
                "task_id": task.id,
                "approved": response.approved,
                "selection": response.selection,
                "input_data": response.input_data,
                "correction": response.correction,
                "notes": response.notes,
            }

            # 5. 如果被拒绝，节点标记为失败（由工作流决定后续处理）
            if not response.approved:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    output={
                        "approved": False,
                        "notes": response.notes,
                    },
                    error={"message": f"HITL rejected: {response.notes}"},
                )

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "approved": True,
                    "selection": response.selection,
                    "input_data": response.input_data,
                    "correction": response.correction,
                    "notes": response.notes,
                },
            )

        except Exception as e:
            state.status = RunStatus.RUNNING
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )


class ConditionNodeExecutor(NodeExecutor):
    """条件节点执行器.

    职责:
    1. 调用RouterEngine评估条件表达式
    2. 根据结果决定下游分支
    3. 标记未命中分支的节点为SKIPPED
    """

    def __init__(
        self,
        router_engine: RouterEngine,
        workflow_def: Any = None,
    ):
        self.router_engine = router_engine
        self.workflow_def = workflow_def

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行条件节点."""
        config = node.config
        conditions = config.get("conditions", [])

        if not conditions:
            # 无条件，默认通过
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={"matched_branch": None, "result": True},
            )

        # 评估每个条件分支
        matched_branch = None
        for branch in conditions:
            condition_expr = branch.get("expression", "")
            branch_id = branch.get("branch_id", "")

            result = self.router_engine.evaluate_condition(condition_expr, state)
            if result:
                matched_branch = branch_id
                break

        # 如果没有匹配任何分支，使用默认分支
        if matched_branch is None:
            matched_branch = config.get("default_branch")

        # 标记未命中分支的下游节点为SKIPPED
        if self.workflow_def and matched_branch is not None:
            await self._skip_unmatched_branches(node, matched_branch, state)

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output={
                "matched_branch": matched_branch,
                "result": matched_branch is not None,
            },
        )

    async def _skip_unmatched_branches(
        self,
        node: Node,
        matched_branch: str,
        state: WorkflowState,
    ) -> None:
        """标记未命中分支的下游节点为SKIPPED."""
        if not self.workflow_def:
            return

        # 获取所有下游节点
        downstream = self.workflow_def.get_downstream(node.id)

        # 获取匹配分支的下游节点
        matched_downstream = set()
        for edge in self.workflow_def.edges:
            if edge.source == node.id:
                # 边的condition对应branch_id
                if edge.condition == matched_branch:
                    matched_downstream.add(edge.target)

        # 标记未匹配的下游节点为SKIPPED
        for target_id in downstream:
            if target_id not in matched_downstream:
                state.node_states[target_id] = NodeStatus.SKIPPED


class CrewNodeExecutor(NodeExecutor):
    """Crew 节点执行器.

    Phase 10: 将 Crew 多 Agent 协作作为 Workflow DAG 节点执行。

    职责:
    1. 从 node.config 读取 crew_id，从数据库加载 Crew 配置
    2. 加载关联的 Agent 列表，为每个 Agent 创建 BaseAgent 实例
    3. 确定 Manager（role_in_crew == 'manager' 的 Agent）
    4. 实例化 Crew 并执行协作任务
    5. 将 CrewResult 写入 state.run_vars
    """

    def __init__(
        self,
        tool_registry: Any = None,
        event_bus: Any = None,
    ):
        self.tool_registry = tool_registry
        self.event_bus = event_bus

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行 Crew 节点."""
        config = node.config

        # 1. 读取配置
        crew_id = config.get("crew_id")
        task_description = config.get("task_description", config.get("task", ""))

        if not crew_id:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "crew_id not specified in node config"},
            )

        if not task_description:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "task_description not specified in node config"},
            )

        try:
            # 2. 从数据库加载 Crew 配置和关联 Agent
            from nexus.db.database import AsyncSessionLocal
            from nexus.models.crew import Crew as CrewModel
            from nexus.models.agent import Agent as AgentModel
            from nexus.models.crew import CrewAgent as CrewAgentModel
            from uuid import UUID

            if isinstance(crew_id, str):
                crew_id = UUID(crew_id)

            async with AsyncSessionLocal() as session:
                # 加载 Crew
                crew_record = await session.get(CrewModel, crew_id)
                if not crew_record:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' not found"},
                    )

                # 加载关联的 CrewAgent + Agent
                from sqlalchemy import select
                stmt = (
                    select(CrewAgentModel, AgentModel)
                    .join(AgentModel, CrewAgentModel.agent_id == AgentModel.id)
                    .where(CrewAgentModel.crew_id == crew_id)
                    .order_by(CrewAgentModel.order_index)
                )
                result = await session.execute(stmt)
                rows = result.all()

                if not rows:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' has no agents"},
                    )

                # 3. 为每个 Agent 创建 BaseAgent 实例
                workers = []
                manager = None

                for ca, agent_model in rows:
                    agent_config = AgentConfig(
                        name=agent_model.name,
                        role=agent_model.role or "",
                        goal=agent_model.goal or "",
                        backstory=agent_model.backstory or "",
                        system_prompt=agent_model.system_prompt or "",
                        provider=agent_model.model_config.get("provider", settings.DEFAULT_LLM_PROVIDER),
                        model=agent_model.model_config.get("model", settings.DEFAULT_LLM_MODEL),
                        temperature=agent_model.model_config.get("temperature", settings.DEFAULT_LLM_TEMPERATURE),
                        max_tokens=agent_model.model_config.get("max_tokens", settings.DEFAULT_LLM_MAX_TOKENS),
                        max_iterations=agent_model.max_iterations or settings.DEFAULT_MAX_ITERATIONS,
                        tools=agent_model.tools or [],
                    )

                    # 创建 LLMClient（复用 AgentNodeExecutor 的 provider 映射逻辑）
                    llm_client = self._create_llm_client(agent_model.model_config)

                    base_agent = BaseAgent(
                        config=agent_config,
                        llm_client=llm_client,
                        tool_registry=self.tool_registry,
                    )

                    if ca.role_in_crew == "manager":
                        manager = base_agent
                    else:
                        workers.append(base_agent)

                # 如果没有指定 Manager，使用第一个 Worker 作为 Manager
                if not manager and workers:
                    manager = workers.pop(0)

                if not manager:
                    return NodeResult(
                        node_id=node.id,
                        status=NodeStatus.FAILED,
                        error={"message": f"Crew '{crew_id}' has no valid agents"},
                    )

                # 4. 构建 CrewConfig
                crew_config = CrewConfig(
                    mode=CrewMode(crew_record.mode or "hierarchical"),
                    max_workers=crew_record.config.get("max_workers", 5),
                    shared_context_enabled=crew_record.config.get("shared_context_enabled", True),
                    auto_delegate=crew_record.config.get("auto_delegate", True),
                )

                # 5. 实例化 Crew 并执行
                crew = Crew(
                    manager=manager,
                    workers=workers,
                    config=crew_config,
                    event_bus=self.event_bus,
                    crew_id=str(crew_id),
                )

                crew_result = await crew.execute(
                    task_description=task_description,
                    context={
                        "run_id": run_id,
                        "node_id": node.id,
                        "tenant_id": state.env_vars.get("tenant_id"),
                        "user_id": state.env_vars.get("user_id"),
                    },
                )

                # 6. 将结果写入 state.run_vars
                output_key = config.get("output_key", node.id)
                state.run_vars[output_key] = crew_result.output

                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output={
                        "output": crew_result.output,
                        "manager_reasoning": crew_result.manager_reasoning,
                        "worker_results": [
                            {
                                "worker_name": w.worker_name,
                                "output": w.output,
                                "success": w.success,
                                "error": w.error,
                            }
                            for w in crew_result.worker_results
                        ],
                        "tool_calls": crew_result.tool_calls,
                    },
                )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )

    def _create_llm_client(self, model_config: dict[str, Any]) -> LLMClient:
        """根据 Agent model_config 创建 LLMClient."""
        provider = model_config.get("provider", settings.DEFAULT_LLM_PROVIDER)

        provider_base_urls = {
            "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
            "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
            "siliconflow": ("https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
            "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
            "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
        }

        if provider in provider_base_urls:
            direct_url, env_key = provider_base_urls[provider]
            api_key = os.environ.get(env_key)
            if api_key:
                base_url = direct_url
            else:
                base_url = settings.LITELLM_PROXY_URL
                api_key = settings.LITELLM_API_KEY
        else:
            base_url = settings.LITELLM_PROXY_URL
            api_key = settings.LITELLM_API_KEY

        return LLMClient(proxy_url=base_url, api_key=api_key)
