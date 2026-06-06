"""企业级Agent基类.

基于WAT agent/base.py (1255行) 泛化:
- 保留协作类模式: LLMClient / TrustModel / DecisionParser
- 保留Fallback链: 主Provider → 备用Provider → 规则兜底
- 保留全局并发控制: Semaphore
- 新增: ToolUse / Memory / Delegation / Streaming
- CrewAI-style Role-Playing: role + goal + backstory
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Optional

from nexus.agent.decision_parser import AgentDecision, DecisionParser
from nexus.agent.llm_client import LLMClient
from nexus.agent.memory import AgentMemory
from nexus.agent.multimodal import MultiModalTask, build_multimodal_messages, is_vision_model
from nexus.agent.trust_model import TrustModel
from nexus.config import settings
from nexus.exceptions import LLMCallException, MaxIterationsReachedException
from nexus.observability.agent_metrics import record_agent_execution, AGENT_DECISION_LATENCY
from nexus.observability.llm_tracer import get_trace_context, set_trace_context
from nexus.prompts.resolver import PromptResolver
from nexus.security.pii_guard import PIIGuard
from uuid import UUID

logger = logging.getLogger(__name__)


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
    enable_semantic_cache: bool = False  # Phase 9: 语义缓存开关


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

    # 全局LLM调用并发控制（使用自适应控制器）
    _LLM_SEMAPHORE = asyncio.Semaphore(10)
    _CONCURRENCY_CONTROLLER = None

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """获取Semaphore，优先使用自适应控制器."""
        if cls._CONCURRENCY_CONTROLLER is not None:
            return cls._CONCURRENCY_CONTROLLER.semaphore
        return cls._LLM_SEMAPHORE

    def __init__(
        self,
        config: AgentConfig,
        llm_client: Optional[LLMClient] = None,
        trust_model: Optional[TrustModel] = None,
        decision_parser: Optional[DecisionParser] = None,
        memory: Optional[AgentMemory] = None,
        tool_registry=None,
        llm_service = None,  # 修复 (S4-1): 注入 LLMService 走 fallback 链
    ):
        self.config = config
        self.llm_client = llm_client or LLMClient()
        # 修复 (S4-1): 优先用 LLMService (含 retry + fallback chain)，
        # 不再用 raw LLMClient — 后者没有 fallback，模型挂掉就 hard fail
        if llm_service is not None:
            self.llm_service = llm_service
        else:
            from nexus.services.llm_service import LLMService
            # 复用同一 LLMClient 实例
            self.llm_service = LLMService(client=self.llm_client)
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

        # PII 检测与脱敏
        try:
            pii = PIIGuard()
            task_desc = task.description if hasattr(task, 'description') else str(task)
            if pii.has_pii(task_desc):
                findings = pii.detect(task_desc)
                logger.warning("PII detected in task input: %s", [f["type"] for f in findings])
                if hasattr(task, 'description'):
                    task.description = pii.sanitize(task_desc)
        except Exception:
            pass  # PII detection failure should not block agent execution

        # 设置 trace context（供 LLM 调用追踪）
        trace_token = set_trace_context(
            agent_id=self.config.name,
            run_id=ctx.get("run_id"),
            node_id=ctx.get("node_id"),
            tenant_id=ctx.get("tenant_id"),
            provider=self.config.provider,
        )

        start_time = perf_counter()
        try:
            result = await self._execute_loop(task, ctx, tool_calls_log, observations)
            
            # 记录Agent执行指标
            duration_seconds = perf_counter() - start_time
            record_agent_execution(
                agent_name=self.config.name,
                status=result.status,
                duration_seconds=duration_seconds,
            )
            
            return result
        except Exception as e:
            # 记录失败指标
            duration_seconds = perf_counter() - start_time
            status = "max_iterations_reached" if isinstance(e, MaxIterationsReachedException) else "failed"
            record_agent_execution(
                agent_name=self.config.name,
                status=status,
                duration_seconds=duration_seconds,
            )
            raise
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

        # 2a. 多模态消息预构建（仅首轮迭代使用）
        mm_messages = self._build_messages(task, system_prompt, memories)

        # 修复 (S5-1): 真 ReAct messages 列表
        # 之前用 _build_iteration_prompt 字符串拼接 observations 到 user_prompt。
        # 现在维护完整 messages list，tool 结果作为 role:tool 消息 append，
        # 这才是 OpenAI / Anthropic 期望的多轮 tool call 格式。
        messages: list[dict] = []

        # 3. ReAct模式循环
        for iteration in range(self.config.max_iterations):
            # 修复 (S5-1): 用 messages 列表而非字符串拼接
            if iteration == 0 and mm_messages is not None:
                # 多模态首轮：直接用预构建的消息
                current_messages = mm_messages
            else:
                # 文本首轮：建 user message（带 observations 累积）
                if iteration == 0:
                    # 第一个 user 消息：任务描述
                    current_messages = messages + [
                        {"role": "user", "content": task.description},
                    ]
                else:
                    # 后续轮：用户消息把上一步 observation 装进来
                    # 这样既保留 messages list 结构（model 能看到完整对话），
                    # 又解决了"之前 observations 是丢进 user_prompt 字符串里"的问题。
                    last_obs = observations[-1] if observations else ""
                    current_messages = messages + [
                        {"role": "user", "content": f"Previous step result: {last_obs}"},
                    ]

            # LLM调用（通过LiteLLM Proxy，携带 tools）
            # Phase 9: 语义缓存 session_id 使用 trace context 中的 run_id
            ctx = get_trace_context()
            session_id = str(ctx.get("run_id", self.config.name))

            try:
                async with self._get_semaphore():
                    # 修复 (S4-1): 用 LLMService.generate 走 fallback 链 + retry
                    # 修复 (S5-1): 传 messages 列表 (含 role:tool) 让 model 看完整多轮对话
                    response = await self.llm_service.generate(
                        system_prompt=system_prompt,
                        user_prompt="",  # 现在走 messages 路径
                        model=self.config.model,
                        provider=self.config.provider,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        tools=openai_tools if openai_tools else None,
                        messages=current_messages,
                        enable_semantic_cache=self.config.enable_semantic_cache,
                        session_id=session_id,
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
                    logger.debug("Response JSON parse failed, using raw text as content", exc_info=True)
                    raw_response = {"choices": [{"message": {"content": raw_response}}]}
            decision = self.decision_parser.parse(raw_response)

            # 修复 (S5-1): 把 assistant 的 tool_calls 写进 messages（让 model 在下一轮看得到）
            if decision.action == "tool_call" and decision.tool_name:
                # 从 raw_response 提取 tool_call_id（OpenAI 协议）
                tool_call_id = None
                if isinstance(raw_response, dict):
                    tool_calls = (
                        raw_response.get("choices", [{}])[0]
                        .get("message", {})
                        .get("tool_calls", [])
                    )
                    if tool_calls:
                        tool_call_id = tool_calls[0].get("id", f"call_{iteration}")

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_call_id or f"call_{iteration}",
                        "type": "function",
                        "function": {
                            "name": decision.tool_name,
                            "arguments": json.dumps(decision.tool_params or {}),
                        },
                    }],
                })

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
                # 修复 (S5-1): 取上一条 assistant.tool_calls 的 id，
                # 关联到对应的 role:tool 消息（OpenAI 协议要求）
                tool_call_id_for_response = f"call_{iteration}"
                if messages and messages[-1].get("role") == "assistant":
                    tcs = messages[-1].get("tool_calls") or []
                    if tcs and tcs[0].get("id"):
                        tool_call_id_for_response = tcs[0]["id"]

                tool_result_content = None
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
                        tool_result_content = (
                            str(result.data) if result.success else str(result.error)
                        )
                        observations.append({
                            "tool": decision.tool_name,
                            "params": decision.tool_params,
                            "result": result.data if result.success else result.error,
                            "success": result.success,
                        })
                    except Exception as exc:
                        # 工具执行失败，记录结构化错误
                        from nexus.exceptions import NexusException, NexusErrorCode

                        error_details = {
                            "tool_name": decision.tool_name,
                            "params": decision.tool_params,
                            "error_type": type(exc).__name__,
                        }

                        # 如果已经是NexusException，保留其错误码
                        if isinstance(exc, NexusException):
                            error_details["code"] = exc.error_code.value if hasattr(exc, 'error_code') else None

                        obs_text = f"Tool '{decision.tool_name}' failed: {str(exc)}"
                        tool_result_content = obs_text
                        observations.append({
                            "tool": decision.tool_name,
                            "params": decision.tool_params,
                            "error": str(exc),
                            "error_details": error_details,
                            "success": False,
                        })
                else:
                    obs_text = "[ToolRegistry not configured — tool execution skipped]"
                    tool_result_content = obs_text
                    observations.append({
                        "tool": decision.tool_name,
                        "params": decision.tool_params,
                        "result": obs_text,
                        "success": False,
                    })

                # 修复 (S5-1): 把工具结果作为 role:tool 消息 append 到 messages
                # 这样 model 在下一轮能看到完整的 tool result（不再用字符串拼接）
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id_for_response,
                    "content": tool_result_content or obs_text,
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

    def _build_messages(
        self,
        task: Task,
        system_content: str,
        memories: list[dict] | None = None,
    ) -> list[dict] | None:
        """构建消息列表（支持多模态）.

        Returns:
            消息列表（OpenAI格式），如果不是多模态任务则返回None（使用文本fallback）。
        """
        # 多模态支持
        if isinstance(task, MultiModalTask) and task.media:
            if is_vision_model(self.config.model):
                return build_multimodal_messages(
                    task, system_prompt=system_content, include_memory=memories
                )
        return None  # 使用现有文本流程
