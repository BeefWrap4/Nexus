"""企业级Agent基类.

基于WAT agent/base.py (1255行) 泛化:
- 保留协作类模式: LLMClient / TrustModel / DecisionParser
- 保留Fallback链: 主Provider → 备用Provider → 规则兜底
- 保留全局并发控制: Semaphore
- 新增: ToolUse / Memory / Delegation / Streaming
- CrewAI-style Role-Playing: role + goal + backstory
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from nexus.agent.decision_parser import AgentDecision, DecisionParser
from nexus.agent.llm_client import LLMClient
from nexus.agent.memory import AgentMemory
from nexus.agent.trust_model import TrustModel
from nexus.config import settings
from nexus.exceptions import LLMCallException, MaxIterationsReachedException
from nexus.observability.llm_tracer import set_trace_context
from nexus.prompts.resolver import PromptResolver
from uuid import UUID


@dataclass
class AgentConfig:
    """Agent配置."""

    name: str
    role: str = ""  # 角色描述
    goal: str = ""  # 目标
    backstory: str = ""  # 背景/个性
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4000
    max_iterations: int = 10
    system_prompt: str = ""  # 直接填写或 template_id 二选一
    system_prompt_template_id: UUID | None = None  # 引用 PromptTemplate
    template_variables: dict[str, Any] = field(default_factory=dict)  # 模板变量
    tools: list[str] = field(default_factory=list)
    memory_enabled: bool = True


@dataclass
class Task:
    """Agent任务."""

    description: str
    expected_output: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent执行结果."""

    output: str
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "success"  # success / failed / max_iterations_reached


class BaseAgent:
    """企业级Agent基类.

    基于WAT BaseAgent泛化:
    - 移除狼人杀专属逻辑（信任模型保留为可选）
    - 增加ToolUse能力（通过 ToolRegistry 实际执行）
    - 增加Memory系统
    - 支持流式输出

    核心决策流程（对应WAT BaseAgent.decide()）:
    1. 检索记忆
    2. 构建System Prompt（含Role-Playing）
    3. 获取可用工具
    4. ReAct模式循环（Thought → Action → Observation）
    5. 返回结果
    """

    # 全局LLM调用并发控制（复用WAT设计）
    _LLM_SEMAPHORE = asyncio.Semaphore(10)

    def __init__(
        self,
        config: AgentConfig,
        llm_client: Optional[LLMClient] = None,
        trust_model: Optional[TrustModel] = None,
        decision_parser: Optional[DecisionParser] = None,
        memory: Optional[AgentMemory] = None,
        tool_registry=None,
    ):
        self.config = config
        self.llm_client = llm_client or LLMClient()
        self.trust_model = trust_model
        self.decision_parser = decision_parser or DecisionParser()
        self.memory = memory
        self.tool_registry = tool_registry

    async def execute(self, task: Task, context: dict[str, Any] = None) -> AgentResult:
        """执行Agent任务（ReAct + Function Calling 模式）.

        对应WAT BaseAgent.decide()。
        增强：
        1. LLM 调用携带可用工具的 function spec（OpenAI 格式）
        2. LLM 可自主返回 tool_calls 决策
        3. Tool 执行结果作为 observation 注入下一轮
        4. 支持流式输出到 EventBus（如果 event_bus 注入）
        """
        ctx = context or {}
        tool_calls_log = []
        observations = []

        # 设置 trace context（供 LLM 调用追踪）
        trace_token = set_trace_context(
            agent_id=self.config.name,
            run_id=ctx.get("run_id"),
            node_id=ctx.get("node_id"),
            tenant_id=ctx.get("tenant_id"),
            provider=self.config.provider,
        )

        try:
            return await self._execute_loop(task, ctx, tool_calls_log, observations)
        finally:
            from nexus.observability.llm_tracer import TRACE_CONTEXT
            TRACE_CONTEXT.reset(trace_token)

    async def _execute_loop(
        self,
        task: Task,
        ctx: dict[str, Any],
        tool_calls_log: list[dict],
        observations: list[dict],
    ) -> AgentResult:
        """Agent ReAct 执行循环（从 execute 抽离以支持 trace context 管理）."""
        # 0. 解析 PromptTemplate（如果配置了 template_id 或有 template_variables）
        self._resolved_system_prompt = ""
        if self.config.system_prompt_template_id:
            # 优先从数据库加载模板内容 + 渲染变量
            from nexus.db.database import AsyncSessionLocal
            from nexus.prompts.resolver import PromptResolver

            async with AsyncSessionLocal() as session:
                resolver = PromptResolver(db_session=session)
                resolved = await resolver.resolve(
                    template_id=self.config.system_prompt_template_id,
                    fallback_content=self.config.system_prompt,
                    variables=self.config.template_variables,
                )
                self._resolved_system_prompt = resolved.content
        elif self.config.template_variables:
            from nexus.prompts.engine import PromptEngine

            engine = PromptEngine()
            rendered = engine.render(
                self.config.system_prompt,
                self.config.template_variables,
            )
            self._resolved_system_prompt = rendered.content

        # 1. 检索相关记忆
        memories = []
        if self.memory and self.config.memory_enabled:
            memories = await self.memory.retrieve(task.description, limit=5)

        # 2. 构建System Prompt + 获取可用工具的 function spec
        system_prompt = self._build_system_prompt(memories)
        openai_tools = self._get_openai_tools()

        # 3. ReAct模式循环
        for iteration in range(self.config.max_iterations):
            # 构建当前轮次的Prompt
            prompt = self._build_iteration_prompt(
                task=task,
                iteration=iteration,
                observations=observations,
            )

            # LLM调用（通过LiteLLM Proxy，携带 tools）
            try:
                async with self._LLM_SEMAPHORE:
                    response = await self.llm_client.call(
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        model=self.config.model,
                        provider=self.config.provider,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        tools=openai_tools if openai_tools else None,
                    )
            except Exception as e:
                raise LLMCallException(str(e), self.config.provider)

            # 解析响应（支持 LLMResponse / dict / str fallback）
            raw_response = response.raw if hasattr(response, "raw") else response
            if isinstance(raw_response, str):
                try:
                    import json as _json
                    raw_response = _json.loads(raw_response)
                except Exception:
                    raw_response = {"choices": [{"message": {"content": raw_response}}]}
            decision = self.decision_parser.parse(raw_response)

            # 处理决策
            if decision.action == "final_answer":
                # 最终答案
                if self.memory and self.config.memory_enabled:
                    await self.memory.save(
                        task=task,
                        result=decision.content,
                        context=ctx,
                    )
                return AgentResult(
                    output=decision.content,
                    reasoning=decision.reasoning,
                    tool_calls=tool_calls_log,
                    confidence=decision.confidence or 0.8,
                )

            elif decision.action == "tool_call":
                # 通过 ToolRegistry 实际执行工具
                tool_calls_log.append({
                    "tool": decision.tool_name,
                    "params": decision.tool_params,
                })
                if self.tool_registry:
                    try:
                        result = await self.tool_registry.execute(
                            tool_name=decision.tool_name,
                            params=decision.tool_params or {},
                            context={
                                "run_id": ctx.get("run_id"),
                                "tenant_id": ctx.get("tenant_id"),
                                "user_id": ctx.get("user_id"),
                            },
                        )
                        obs_text = (
                            f"Tool '{decision.tool_name}' executed successfully. "
                            f"Result: {result.data if result.success else result.error}"
                        )
                        observations.append({
                            "tool": decision.tool_name,
                            "params": decision.tool_params,
                            "result": result.data if result.success else result.error,
                            "success": result.success,
                        })
                    except Exception as exc:
                        obs_text = f"Tool '{decision.tool_name}' failed: {str(exc)}"
                        observations.append({
                            "tool": decision.tool_name,
                            "params": decision.tool_params,
                            "error": str(exc),
                            "success": False,
                        })
                else:
                    obs_text = "[ToolRegistry not configured — tool execution skipped]"
                    observations.append({
                        "tool": decision.tool_name,
                        "params": decision.tool_params,
                        "result": obs_text,
                        "success": False,
                    })

            elif decision.action == "think":
                # 纯思考，继续循环
                observations.append({"thought": decision.content})

            else:
                # 未知动作，返回结果
                return AgentResult(
                    output=decision.content or str(decision),
                    reasoning=decision.reasoning,
                    tool_calls=tool_calls_log,
                )

        # 达到最大迭代次数
        raise MaxIterationsReachedException(self.config.name, self.config.max_iterations)

    def _get_openai_tools(self) -> list[dict] | None:
        """获取可用工具的 OpenAI function spec 格式列表.

        从 ToolRegistry 中提取工具定义，转换为 LLM function calling 格式。
        如果未配置 tool_registry 或无可用工具，返回 None。
        """
        if not self.tool_registry:
            return None

        tools = self.tool_registry.list_tools()
        if not tools:
            return None

        openai_tools = []
        for tool_info in tools:
            tool_def = self.tool_registry.get_tool(tool_info.name)
            if not tool_def:
                continue
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_info.name,
                    "description": tool_info.description,
                    "parameters": tool_info.schema or {"type": "object", "properties": {}},
                },
            })
        return openai_tools

    def _build_system_prompt(self, memories: list[dict] = None) -> str:
        """构建System Prompt.

        CrewAI-style Role-Playing:
        - role: 角色描述
        - goal: 目标
        - backstory: 背景/个性

        增强：支持 PromptTemplate 解析（template_id 优先于 system_prompt 文本）
        """
        parts = []

        # Role-Playing三元组
        if self.config.role:
            parts.append(f"You are {self.config.role}.")
        if self.config.goal:
            parts.append(f"Your goal is: {self.config.goal}")
        if self.config.backstory:
            parts.append(f"Backstory: {self.config.backstory}")

        # System Prompt：优先使用已解析的模板，其次直填文本
        system_prompt_text = getattr(self, "_resolved_system_prompt", None) or self.config.system_prompt
        if system_prompt_text:
            parts.append(system_prompt_text)

        # 可用工具描述（fallback text 格式，供不支持 function calling 的模型使用）
        if self.tool_registry:
            tools = self.tool_registry.list_tools()
            if tools:
                parts.append("\nYou have access to the following tools:")
                for tool_info in tools:
                    parts.append(
                        f"- {tool_info.name}: {tool_info.description}"
                    )
                parts.append(
                    "\nTo use a tool, respond with action 'tool_call' and specify the tool name and parameters."
                )

        # 记忆注入
        if memories:
            parts.append("\nRelevant memories from past tasks:")
            for mem in memories:
                parts.append(f"- {mem}")

        # 输出格式指令
        parts.append(
            "\nWhen you have a final answer, respond with action 'final_answer'.\n"
            "When you need to use a tool, respond with action 'tool_call'.\n"
            "When you need to think, respond with action 'think'."
        )

        return "\n\n".join(parts)

    def _build_iteration_prompt(
        self,
        task: Task,
        iteration: int,
        observations: list[dict],
    ) -> str:
        """构建迭代Prompt."""
        parts = [f"Task: {task.description}"]

        if task.expected_output:
            parts.append(f"Expected output: {task.expected_output}")

        if observations:
            parts.append("\nPrevious observations:")
            for i, obs in enumerate(observations, 1):
                parts.append(f"{i}. {obs}")

        parts.append(f"\nIteration: {iteration + 1}")
        parts.append("What is your next action?")

        return "\n\n".join(parts)
