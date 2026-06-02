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
from typing import Any

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.engine.hitl_controller import HITLController, HITLResponse, HITLType
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.engine.enums import NodeStatus, RunStatus
from nexus.engine.workflow_engine import Node, NodeExecutor, NodeResult
from nexus.exceptions import AgentNotFoundException, ToolNotFoundException
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
    2. 构建Task对象
    3. 调用Agent.execute()并返回结果
    """

    def __init__(
        self,
        agent_factory: Any = None,  # Callable[[str], BaseAgent]
        default_agent: BaseAgent = None,
    ):
        self.agent_factory = agent_factory
        self.default_agent = default_agent
        self._agent_cache: dict[str, BaseAgent] = {}

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        """执行Agent节点."""
        config = node.config

        # 1. 获取Agent实例
        agent = await self._get_agent(config)
        if not agent:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"Agent not found for node: {node.id}"},
            )

        # 2. 构建Task
        task = Task(
            description=config.get("task", ""),
            expected_output=config.get("expected_output", ""),
            context=inputs,
        )

        # 3. 执行Agent
        try:
            result = await agent.execute(task, context={"run_id": run_id, "node_id": node.id})

            # 4. 将Agent输出写入run_vars（供下游节点引用）
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
    """

    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry

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

        # 构建执行上下文
        context = {
            "run_id": run_id,
            "node_id": node.id,
            "tenant_id": state.env_vars.get("tenant_id"),
            "user_id": state.env_vars.get("user_id"),
        }

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


class HITLNodeExecutor(NodeExecutor):
    """人工在环节点执行器.

    职责:
    1. 创建HITL审批任务
    2. 暂停工作流等待人工响应
    3. 收到响应后恢复并返回结果
    """

    def __init__(
        self,
        hitl_controller: HITLController,
        default_timeout: int = None,
    ):
        self.hitl_controller = hitl_controller
        self.default_timeout = default_timeout

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
