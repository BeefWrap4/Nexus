"""BaseAgent 纯逻辑层测试 — mock LLMClient 避免实际 LLM 调用.

覆盖:
- AgentConfig / Task / AgentResult 数据类
- BaseAgent 构造、semaphore
- _get_openai_tools() 边界情况
- _build_system_prompt() 完整逻辑
- _build_iteration_prompt() 全部分支
- execute() + _execute_loop() 核心流程:
    final_answer / tool_call / think / unknown / max_iterations / error
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nexus.agent.base import AgentConfig, AgentResult, BaseAgent, Task
from nexus.agent.decision_parser import AgentDecision
from nexus.agent.llm_client import LLMResponse
from nexus.exceptions import LLMCallException, MaxIterationsReachedException
from nexus.tools.registry import Tool, ToolInfo, ToolRegistry, ToolResult, ToolType


# ============================================================================
# 数据类测试
# ============================================================================

class TestAgentConfig:
    """AgentConfig 数据类测试."""

    def test_default_config(self):
        """默认值应正确."""
        config = AgentConfig(name="test_agent")
        assert config.name == "test_agent"
        assert config.role == ""
        assert config.goal == ""
        assert config.backstory == ""
        assert config.provider == "openai"
        assert config.model == "gpt-4o"
        assert config.temperature == 0.7
        assert config.max_tokens == 4000
        assert config.max_iterations == 10
        assert config.system_prompt == ""
        assert config.system_prompt_template_id is None
        assert config.template_variables == {}
        assert config.tools == []
        assert config.memory_enabled is True
        assert config.enable_semantic_cache is False

    def test_full_config(self):
        """全字段配置应保留所有值."""
        config = AgentConfig(
            name="expert",
            role="senior developer",
            goal="write clean code",
            backstory="10 years of Python experience",
            provider="deepseek",
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=8000,
            max_iterations=5,
            system_prompt="You are a senior dev.",
            tools=["code_review", "search"],
            memory_enabled=False,
            enable_semantic_cache=True,
        )
        assert config.name == "expert"
        assert config.role == "senior developer"
        assert config.goal == "write clean code"
        assert config.backstory == "10 years of Python experience"
        assert config.provider == "deepseek"
        assert config.model == "deepseek-chat"
        assert config.temperature == 0.3
        assert config.max_tokens == 8000
        assert config.max_iterations == 5
        assert config.system_prompt == "You are a senior dev."
        assert config.tools == ["code_review", "search"]
        assert config.memory_enabled is False
        assert config.enable_semantic_cache is True

    def test_template_variables_default(self):
        """template_variables 默认应为空字典（field default_factory）."""
        config = AgentConfig(name="test")
        assert config.template_variables == {}
        # 确保不同实例不共享同一字典对象
        assert config.template_variables is not AgentConfig(name="other").template_variables


class TestTask:
    """Task 数据类测试."""

    def test_task_basic(self):
        """基本任务创建."""
        task = Task(description="Review code")
        assert task.description == "Review code"
        assert task.expected_output == ""
        assert task.context == {}

    def test_task_full(self):
        """完整任务字段."""
        task = Task(
            description="Find bugs",
            expected_output="List of bugs found",
            context={"repo": "nexus", "language": "python"},
        )
        assert task.description == "Find bugs"
        assert task.expected_output == "List of bugs found"
        assert task.context == {"repo": "nexus", "language": "python"}


class TestAgentResult:
    """AgentResult 数据类测试."""

    def test_result_defaults(self):
        """默认 status 和 confidence."""
        result = AgentResult(output="done")
        assert result.output == "done"
        assert result.reasoning == ""
        assert result.tool_calls == []
        assert result.confidence == 0.0
        assert result.status == "success"

    def test_result_failed(self):
        """失败状态."""
        result = AgentResult(output="", status="failed", confidence=0.0)
        assert result.status == "failed"

    def test_result_with_tool_calls(self):
        """包含工具调用日志."""
        result = AgentResult(
            output="Completed",
            reasoning="Step by step",
            tool_calls=[{"tool": "search", "params": {"q": "test"}}],
            confidence=0.9,
            status="success",
        )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "search"
        assert result.reasoning == "Step by step"
        assert result.confidence == 0.9


# ============================================================================
# BaseAgent 构造测试
# ============================================================================

class TestBaseAgentConstruction:
    """BaseAgent 构造函数测试."""

    def test_minimal_creation(self):
        """最小化创建 — 使用所有默认依赖."""
        config = AgentConfig(name="agent")
        agent = BaseAgent(config)
        assert agent.config is config
        assert agent.config.name == "agent"
        assert agent.llm_client is not None
        assert agent.decision_parser is not None
        assert agent.trust_model is None
        assert agent.memory is None
        assert agent.tool_registry is None

    def test_full_dependencies(self):
        """注入所有依赖."""
        config = AgentConfig(name="full_agent", role="coder", goal="code")
        mock_llm = MagicMock()
        mock_trust = MagicMock()
        mock_parser = MagicMock()
        mock_memory = MagicMock()
        mock_registry = MagicMock()

        agent = BaseAgent(
            config=config,
            llm_client=mock_llm,
            trust_model=mock_trust,
            decision_parser=mock_parser,
            memory=mock_memory,
            tool_registry=mock_registry,
        )
        assert agent.llm_client is mock_llm
        assert agent.trust_model is mock_trust
        assert agent.decision_parser is mock_parser
        assert agent.memory is mock_memory
        assert agent.tool_registry is mock_registry

    def test_config_assignment(self):
        """config 引用保持."""
        config = AgentConfig(name="agent", role="tester", goal="test", max_iterations=7)
        agent = BaseAgent(config)
        assert agent.config.role == "tester"
        assert agent.config.goal == "test"
        assert agent.config.max_iterations == 7


# ============================================================================
# Semaphore 测试
# ============================================================================

class TestGetSemaphore:
    """_get_semaphore() 类方法测试."""

    def test_default_semaphore(self):
        """默认返回 _LLM_SEMAPHORE."""
        sem = BaseAgent._get_semaphore()
        assert sem is BaseAgent._LLM_SEMAPHORE
        assert sem._value == 10  # 默认并发数

    def test_with_concurrency_controller(self):
        """配置 _CONCURRENCY_CONTROLLER 后应优先返回其 semaphore."""
        mock_controller = MagicMock()
        mock_controller.semaphore = MagicMock()
        original = BaseAgent._CONCURRENCY_CONTROLLER
        try:
            BaseAgent._CONCURRENCY_CONTROLLER = mock_controller
            sem = BaseAgent._get_semaphore()
            assert sem is mock_controller.semaphore
        finally:
            BaseAgent._CONCURRENCY_CONTROLLER = original


# ============================================================================
# _get_openai_tools() 测试
# ============================================================================

class TestGetOpenaiTools:
    """_get_openai_tools() 边界场景测试."""

    def test_empty_registry_returns_none(self):
        """空 ToolRegistry（无工具注册）返回 None."""
        registry = ToolRegistry()
        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=registry)
        assert agent._get_openai_tools() is None

    def test_tool_with_no_schema(self):
        """工具无 schema 时应使用默认空 properties."""
        registry = ToolRegistry()
        registry.register(Tool(name="no_schema", description="A tool", type=ToolType.HTTP, config={}))
        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=registry)
        tools = agent._get_openai_tools()
        assert tools is not None
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "no_schema"
        assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_multiple_tools(self):
        """多个工具应全部返回."""
        registry = ToolRegistry()
        registry.register(Tool(name="search", description="Search", type=ToolType.HTTP, config={}))
        registry.register(Tool(name="read", description="Read file", type=ToolType.HTTP, config={}))
        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=registry)
        tools = agent._get_openai_tools()
        assert tools is not None
        assert len(tools) == 2
        names = [t["function"]["name"] for t in tools]
        assert "search" in names
        assert "read" in names

    def test_get_tool_returns_none_skipped(self):
        """get_tool 返回 None 时该工具应被跳过."""
        registry = ToolRegistry()
        # 注册一个工具，但 list_tools 会返回它，
        # get_tool 返回 None — 这可以通过 mock 实现
        mock_registry = MagicMock()
        mock_registry.list_tools = MagicMock(return_value=[
            ToolInfo(name="ghost", description="Ghost tool"),
        ])
        mock_registry.get_tool = MagicMock(return_value=None)
        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=mock_registry)
        tools = agent._get_openai_tools()
        assert tools == []  # 列表存在但为空


# ============================================================================
# _build_system_prompt() 测试
# ============================================================================

class TestBuildSystemPrompt:
    """_build_system_prompt() 完整测试."""

    def test_empty_config(self):
        """空 role/goal/backstory 时只有输出格式指令."""
        config = AgentConfig(name="minimal")
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "final_answer" in prompt
        assert "tool_call" in prompt
        assert "think" in prompt
        # 不应有 role/goal/backstory 相关文本
        assert "You are" not in prompt
        assert "Your goal" not in prompt
        assert "Backstory" not in prompt

    def test_role_only(self):
        """仅 role 存在."""
        config = AgentConfig(name="agent", role="code reviewer")
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "You are code reviewer." in prompt

    def test_goal_only(self):
        """仅 goal 存在."""
        config = AgentConfig(name="agent", goal="review PRs")
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "Your goal is: review PRs" in prompt

    def test_backstory_only(self):
        """仅 backstory 存在."""
        config = AgentConfig(name="agent", backstory="senior eng")
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "Backstory: senior eng" in prompt

    def test_role_goal_backstory(self):
        """三元组完整."""
        config = AgentConfig(
            name="agent",
            role="Python expert",
            goal="produce clean code",
            backstory="15 years experience",
        )
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "You are Python expert." in prompt
        assert "Your goal is: produce clean code" in prompt
        assert "Backstory: 15 years experience" in prompt

    def test_system_prompt_text(self):
        """直填 system_prompt 文本."""
        config = AgentConfig(name="agent", system_prompt="Be helpful and concise.")
        agent = BaseAgent(config)
        prompt = agent._build_system_prompt()
        assert "Be helpful and concise." in prompt

    def test_resolved_system_prompt_override(self):
        """_resolved_system_prompt 优先于 config.system_prompt."""
        config = AgentConfig(name="agent", system_prompt="default prompt")
        agent = BaseAgent(config)
        agent._resolved_system_prompt = "resolved from template"
        prompt = agent._build_system_prompt()
        assert "resolved from template" in prompt
        assert "default prompt" not in prompt

    def test_resolved_empty_falls_back_to_config(self):
        """_resolved_system_prompt 为空字符串时应回退到 config.system_prompt."""
        config = AgentConfig(name="agent", system_prompt="fallback prompt")
        agent = BaseAgent(config)
        agent._resolved_system_prompt = ""
        prompt = agent._build_system_prompt()
        assert "fallback prompt" in prompt

    def test_with_tool_registry(self):
        """prompt 应包含工具列表."""
        registry = ToolRegistry()
        registry.register(
            Tool(name="search_code", description="Search codebase", type=ToolType.HTTP, config={})
        )
        config = AgentConfig(name="agent")
        agent = BaseAgent(config=config, tool_registry=registry)
        prompt = agent._build_system_prompt()
        assert "You have access to the following tools" in prompt
        assert "search_code" in prompt
        assert "Search codebase" in prompt

    def test_with_memories(self):
        """prompt 应包含记忆文本."""
        config = AgentConfig(name="agent")
        agent = BaseAgent(config)
        memories = [
            {"task": "Fix bug #123", "result": "Resolved", "importance": 0.8},
            {"task": "Review PR #456", "result": "Approved", "importance": 0.5},
        ]
        prompt = agent._build_system_prompt(memories=memories)
        assert "Relevant memories from past tasks:" in prompt
        # 确认记忆内容出现在 prompt 中（repr 形式）
        assert "Fix bug #123" in prompt
        assert "Review PR #456" in prompt

    def test_complete_prompt(self):
        """完整 prompt — 三元组 + system + 工具 + 记忆."""
        registry = ToolRegistry()
        registry.register(Tool(name="rag", description="RAG query", type=ToolType.HTTP, config={}))
        config = AgentConfig(
            name="full_agent",
            role="researcher",
            goal="find information",
            backstory="AI researcher",
            system_prompt="Always cite sources.",
        )
        agent = BaseAgent(config=config, tool_registry=registry)
        memories = [{"task": "prev", "result": "ok"}]
        prompt = agent._build_system_prompt(memories=memories)
        assert "You are researcher." in prompt
        assert "Your goal is: find information" in prompt
        assert "Backstory: AI researcher" in prompt
        assert "Always cite sources." in prompt
        assert "You have access to the following tools" in prompt
        assert "Relevant memories from past tasks:" in prompt
        # 顺序正确：尾部是输出格式指令
        assert prompt.rstrip().endswith("respond with action 'think'.")


# ============================================================================
# _build_iteration_prompt() 测试
# ============================================================================

class TestBuildIterationPrompt:
    """_build_iteration_prompt() 测试."""

    def test_basic_task(self):
        """基本 task + iteration."""
        config = AgentConfig(name="agent")
        agent = BaseAgent(config)
        task = Task(description="Write a function")
        prompt = agent._build_iteration_prompt(task, iteration=0, observations=[])
        assert "Task: Write a function" in prompt
        assert "Iteration: 1" in prompt
        assert "What is your next action?" in prompt

    def test_with_expected_output(self):
        """task 含 expected_output."""
        config = AgentConfig(name="agent")
        agent = BaseAgent(config)
        task = Task(description="Analyze data", expected_output="JSON report")
        prompt = agent._build_iteration_prompt(task, iteration=2, observations=[])
        assert "Task: Analyze data" in prompt
        assert "Expected output: JSON report" in prompt
        assert "Iteration: 3" in prompt

    def test_with_observations(self):
        """含历史 observation."""
        config = AgentConfig(name="agent")
        agent = BaseAgent(config)
        task = Task(description="Research topic")
        observations = [
            {"tool": "search", "params": {"q": "AI"}, "result": "42 results"},
            {"thought": "I need to narrow down"},
        ]
        prompt = agent._build_iteration_prompt(task, iteration=1, observations=observations)
        assert "Previous observations:" in prompt
        assert "AI" in prompt  # params in observation
        assert "narrow down" in prompt  # thought content
        assert "Iteration: 2" in prompt


# ============================================================================
# execute() + _execute_loop() 集成测试
# ============================================================================

class TestBaseAgentExecute:
    """async execute() 核心流程测试."""

    @pytest.fixture
    def agent_no_tools(self):
        """无工具注册的基本 Agent."""
        config = AgentConfig(name="test_agent", role="assistant", goal="help", max_iterations=3)
        return BaseAgent(config=config)

    @pytest.fixture
    def agent_with_tools(self):
        """带工具注册的 Agent."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="search",
                description="Search the web",
                type=ToolType.HTTP,
                config={},
                schema={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            )
        )
        config = AgentConfig(name="tool_agent", role="researcher", goal="find info", max_iterations=3)
        return BaseAgent(config=config, tool_registry=registry)

    # ------------------------------------------------------------------
    # execute() 自身逻辑测试（mock _execute_loop）
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_execute_wraps_loop_success(self, agent_no_tools):
        """execute() 正常返回时应记录 success 指标."""
        mock_result = AgentResult(output="done", status="success")
        with patch.object(agent_no_tools, "_execute_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = mock_result
            with patch("nexus.agent.base.record_agent_execution") as mock_record:
                result = await agent_no_tools.execute(Task(description="Test"))
                assert result is mock_result
                mock_record.assert_called_once()
                assert mock_record.call_args.kwargs["status"] == "success"
                assert mock_record.call_args.kwargs["agent_name"] == "test_agent"

    @pytest.mark.asyncio
    async def test_execute_records_max_iterations(self, agent_no_tools):
        """execute() 捕获 MaxIterationsReachedException 时应记录对应状态."""
        with patch.object(agent_no_tools, "_execute_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.side_effect = MaxIterationsReachedException("test", 3)
            with patch("nexus.agent.base.record_agent_execution") as mock_record:
                with pytest.raises(MaxIterationsReachedException):
                    await agent_no_tools.execute(Task(description="Test"))
                mock_record.assert_called_once()
                assert mock_record.call_args.kwargs["status"] == "max_iterations_reached"

    @pytest.mark.asyncio
    async def test_execute_records_failed(self, agent_no_tools):
        """execute() 捕获普通异常时应记录 failed."""
        with patch.object(agent_no_tools, "_execute_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.side_effect = RuntimeError("unexpected")
            with patch("nexus.agent.base.record_agent_execution") as mock_record:
                with pytest.raises(RuntimeError):
                    await agent_no_tools.execute(Task(description="Test"))
                mock_record.assert_called_once()
                assert mock_record.call_args.kwargs["status"] == "failed"

    # ------------------------------------------------------------------
    # _execute_loop() — final_answer
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_simple_final_answer(self, agent_no_tools):
        """Mock LLM 返回 final_answer — 验证 AgentResult."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="Task completed successfully!",
                raw={"choices": [{"message": {"content": "Task completed successfully!"}}]},
            )
            result = await agent_no_tools.execute(Task(description="Do X"))
            assert result.output == "Task completed successfully!"
            assert result.status == "success"

    @pytest.mark.asyncio
    async def test_final_answer_with_confidence(self, agent_no_tools):
        """LLM 返回带 confidence 的 final_answer."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="",
                raw={
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "action": "final_answer",
                                "content": "Answer is 42",
                                "reasoning": "computed",
                                "confidence": 0.95,
                            })
                        }
                    }]
                },
            )
            result = await agent_no_tools.execute(Task(description="What is the answer?"))
            assert result.output == "Answer is 42"
            assert result.reasoning == "computed"
            assert result.confidence == 0.95

    # ------------------------------------------------------------------
    # _execute_loop() — tool_call
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_call_then_final_answer(self, agent_with_tools):
        """第一轮 tool_call → 第二轮 final_answer."""
        with patch.object(agent_with_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = [
                LLMResponse(
                    content="",
                    raw={
                        "choices": [{
                            "message": {
                                "tool_calls": [{
                                    "function": {
                                        "name": "search",
                                        "arguments": json.dumps({"q": "NEXUS"}),
                                    }
                                }]
                            }
                        }]
                    },
                ),
                LLMResponse(
                    content="Found 10 results about NEXUS",
                    raw={"choices": [{"message": {"content": "Found 10 results about NEXUS"}}]},
                ),
            ]
            result = await agent_with_tools.execute(Task(description="Search for NEXUS"))
            assert "10 results" in result.output
            assert len(result.tool_calls) == 1
            assert result.tool_calls[0]["tool"] == "search"
            assert result.tool_calls[0]["params"] == {"q": "NEXUS"}

    @pytest.mark.asyncio
    async def test_tool_call_with_failure(self, agent_with_tools):
        """工具执行失败（异常）时继续循环."""
        with patch.object(agent_with_tools.tool_registry, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = ValueError("search index corrupted")
            with patch.object(agent_with_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
                mock_call.side_effect = [
                    LLMResponse(
                        content="",
                        raw={
                            "choices": [{
                                "message": {
                                    "tool_calls": [{
                                        "function": {
                                            "name": "search",
                                            "arguments": json.dumps({"q": "test"}),
                                        }
                                    }]
                                }
                            }]
                        },
                    ),
                    LLMResponse(
                        content="Search failed, I'll try another approach... Result: fallback",
                        raw={"choices": [{"message": {"content": "Search failed, I'll try another approach... Result: fallback"}}]},
                    ),
                ]
                result = await agent_with_tools.execute(Task(description="Search for test"))
                assert "fallback" in result.output

    @pytest.mark.asyncio
    async def test_tool_returns_error_without_raising(self, agent_with_tools):
        """工具执行返回 success=False 但不抛异常，应记录 error 文本并继续."""
        with patch.object(agent_with_tools.tool_registry, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = ToolResult(success=False, error="API rate limit exceeded")
            with patch.object(agent_with_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
                mock_call.side_effect = [
                    LLMResponse(
                        content="",
                        raw={
                            "choices": [{
                                "message": {
                                    "tool_calls": [{
                                        "function": {
                                            "name": "search",
                                            "arguments": json.dumps({"q": "ratelimit-test"}),
                                        }
                                    }]
                                }
                            }]
                        },
                    ),
                    LLMResponse(
                        content="Rate limit hit, will retry later.",
                        raw={"choices": [{"message": {"content": "Rate limit hit, will retry later."}}]},
                    ),
                ]
                result = await agent_with_tools.execute(Task(description="Search rate limited"))
                assert "Rate limit hit" in result.output
                assert len(result.tool_calls) == 1

    # ------------------------------------------------------------------
    # _execute_loop() — think
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_think_then_final_answer(self, agent_no_tools):
        """think action 后继续循环 → 最终 final_answer."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = [
                LLMResponse(
                    content="",
                    raw={"choices": [{"message": {"content": json.dumps(
                        {"action": "think", "content": "I need to analyze this first"}
                    )}}]},
                ),
                LLMResponse(
                    content="After analysis, here is the answer",
                    raw={"choices": [{"message": {"content": "After analysis, here is the answer"}}]},
                ),
            ]
            result = await agent_no_tools.execute(Task(description="Complex problem"))
            assert "After analysis" in result.output
            assert result.status == "success"

    # ------------------------------------------------------------------
    # _execute_loop() — max_iterations
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, agent_no_tools):
        """LLM 持续返回 tool_call 导致超限."""
        agent_no_tools.config.max_iterations = 2
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="",
                raw={
                    "choices": [{
                        "message": {
                            "tool_calls": [{
                                "function": {
                                    "name": "loop_tool",
                                    "arguments": json.dumps({}),
                                }
                            }]
                        }
                    }]
                },
            )
            with pytest.raises(MaxIterationsReachedException) as exc_info:
                await agent_no_tools.execute(Task(description="Loop forever"))
            assert "test_agent" in str(exc_info.value)
            assert "2" in str(exc_info.value)

    # ------------------------------------------------------------------
    # _execute_loop() — unknown action
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_unknown_action_returns_result(self, agent_no_tools):
        """未知 action 时应立即返回 AgentResult."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            # 使用 JSON 格式返回一个未知 action
            mock_call.return_value = LLMResponse(
                content="",
                raw={
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "action": "unknown_action_xyz",
                                "content": "Something happened",
                                "reasoning": "not sure",
                            })
                        }
                    }]
                },
            )
            result = await agent_no_tools.execute(Task(description="Test unknown"))
            assert result.status == "success"  # default
            assert "Something happened" in result.output

    # ------------------------------------------------------------------
    # _execute_loop() — LLM call exception
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_llm_call_exception(self, agent_no_tools):
        """LLM 调用异常时包装为 LLMCallException."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("network error")
            with pytest.raises(LLMCallException) as exc_info:
                await agent_no_tools.execute(Task(description="Test"))
            assert "network error" in str(exc_info.value)

    # ------------------------------------------------------------------
    # _execute_loop() — string raw fallback
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raw_string_response(self, agent_no_tools):
        """raw 为普通字符串时 fallback 到 content."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="plain text response",
                raw="plain text response",  # raw 是字符串，不是 dict
            )
            result = await agent_no_tools.execute(Task(description="Test"))
            assert "plain text response" in result.output

    # ------------------------------------------------------------------
    # _execute_loop() — tool_registry not configured
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_call_without_registry(self, agent_no_tools):
        """没有 tool_registry 时 tool_call 应记录并继续."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = [
                LLMResponse(
                    content="",
                    raw={
                        "choices": [{
                            "message": {
                                "tool_calls": [{
                                    "function": {
                                        "name": "search",
                                        "arguments": json.dumps({"q": "test"}),
                                    }
                                }]
                            }
                        }]
                    },
                ),
                LLMResponse(
                    content="No tools available but here's my best answer",
                    raw={"choices": [{"message": {"content": "No tools available but here's my best answer"}}]},
                ),
            ]
            result = await agent_no_tools.execute(Task(description="Search for test"))
            # agent_no_tools 没有 tool_registry，tool_call 应被跳过
            assert result.tool_calls[0]["tool"] == "search"  # 记录在 log 中
            assert "best answer" in result.output

    # ------------------------------------------------------------------
    # _execute_loop() — JSON string raw (not dict)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_raw_json_string(self, agent_no_tools):
        """raw 是 JSON 字符串时应正确解析."""
        with patch.object(agent_no_tools.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="",
                raw=json.dumps({
                    "choices": [{"message": {"content": "Parsed from JSON string"}}]
                }),
            )
            result = await agent_no_tools.execute(Task(description="Test"))
            assert "Parsed from JSON string" in result.output


# ============================================================================
# _execute_loop() — 模板变量
# ============================================================================

class TestExecuteLoopTemplates:
    """模板变量 / PromptTemplate 相关测试."""

    @pytest.mark.asyncio
    async def test_template_variables_path(self):
        """config.template_variables 设置时应调用 PromptEngine.render."""
        config = AgentConfig(
            name="template_agent",
            role="helper",
            system_prompt="Hello {{name}}",
            template_variables={"name": "World"},
            max_iterations=2,
        )
        agent = BaseAgent(config=config)

        # Mock PromptEngine.render — PromptEngine 在 _execute_loop 内
        # 通过 `from nexus.prompts.engine import PromptEngine` 延迟导入
        mock_engine = MagicMock()
        mock_rendered = MagicMock()
        mock_rendered.content = "Hello World"
        mock_engine.render = MagicMock(return_value=mock_rendered)

        with patch("nexus.prompts.engine.PromptEngine", return_value=mock_engine):
            with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = LLMResponse(
                    content="Response: Hello World!",
                    raw={"choices": [{"message": {"content": "Response: Hello World!"}}]},
                )
                result = await agent.execute(Task(description="Greet"))
                assert "Hello World!" in result.output
                mock_engine.render.assert_called_once_with(
                    "Hello {{name}}",
                    {"name": "World"},
                )

    @pytest.mark.asyncio
    async def test_template_id_db_path(self):
        """config.system_prompt_template_id 设置时应从数据库加载并渲染模板."""
        from uuid import uuid4

        template_id = uuid4()
        config = AgentConfig(
            name="template_db_agent",
            role="helper",
            system_prompt="fallback-text",
            system_prompt_template_id=template_id,
            template_variables={"var1": "value1"},
            max_iterations=2,
        )
        agent = BaseAgent(config=config)

        # Mock DB session 和 PromptResolver
        mock_session = MagicMock()
        mock_resolver = MagicMock()
        mock_resolved = MagicMock()
        mock_resolved.content = "Resolved from database"
        mock_resolver.resolve = AsyncMock(return_value=mock_resolved)

        with patch("nexus.db.database.AsyncSessionLocal") as mock_db:
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("nexus.prompts.resolver.PromptResolver", return_value=mock_resolver):
                with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_call:
                    mock_call.return_value = LLMResponse(
                        content="Response with DB template!",
                        raw={"choices": [{"message": {"content": "Response with DB template!"}}]},
                    )
                    result = await agent.execute(Task(description="Task with template"))
                    assert "Response with DB template!" in result.output
                    mock_resolver.resolve.assert_called_once()
                    call_kwargs = mock_resolver.resolve.call_args.kwargs
                    assert call_kwargs["template_id"] == template_id
                    assert call_kwargs["fallback_content"] == "fallback-text"
                    assert call_kwargs["variables"] == {"var1": "value1"}


# ============================================================================
# _execute_loop() — 记忆
# ============================================================================

class TestExecuteLoopMemory:
    """记忆集成测试."""

    @pytest.mark.asyncio
    async def test_memory_retrieve_and_save(self):
        """启用记忆时应在执行前后调用 memory 的 retrieve 和 save."""
        from nexus.agent.memory import AgentMemory
        from nexus.agent.memory_backend import InMemoryBackend

        config = AgentConfig(name="mem_agent", role="helper", memory_enabled=True, max_iterations=2)
        backend = InMemoryBackend()
        memory = AgentMemory(agent_id="mem_agent", backend=backend)

        # 预设记忆
        await memory.save(task=Task(description="Old task"), result="Old result")
        agent = BaseAgent(config=config, memory=memory)

        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="Working on it — answer found",
                raw={"choices": [{"message": {"content": "Working on it — answer found"}}]},
            )
            result = await agent.execute(Task(description="New task"))
            assert result.output == "Working on it — answer found"

            # 验证记忆被保存
            results = await backend.retrieve("mem_agent", "New task", limit=5)
            assert len(results) >= 1  # 新任务的结果被保存

    @pytest.mark.asyncio
    async def test_memory_disabled(self):
        """memory_enabled=False 时不调用记忆."""
        from nexus.agent.memory import AgentMemory
        from nexus.agent.memory_backend import InMemoryBackend

        config = AgentConfig(name="no_mem", role="helper", memory_enabled=False, max_iterations=2)
        backend = InMemoryBackend()
        memory = AgentMemory(agent_id="no_mem", backend=backend)
        agent = BaseAgent(config=config, memory=memory)

        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResponse(
                content="Quick answer, no memory",
                raw={"choices": [{"message": {"content": "Quick answer, no memory"}}]},
            )
            result = await agent.execute(Task(description="Ephemeral"))
            assert result.output == "Quick answer, no memory"
            # 记忆不应被保存
            results = await backend.retrieve("no_mem", "Ephemeral", limit=5)
            assert len(results) == 0


# ============================================================================
# 决策解析边界测试
# ============================================================================

class TestDecisionParsingInLoop:
    """_execute_loop 中的决策解析边界场景."""

    @pytest.mark.asyncio
    async def test_decision_tool_call_with_json_content(self):
        """当 raw content 是 JSON action (非 tool_calls) 时."""
        config = AgentConfig(name="agent", role="helper", max_iterations=2)
        registry = ToolRegistry()
        registry.register(Tool(name="exec", description="Execute", type=ToolType.HTTP, config={}))
        agent = BaseAgent(config=config, tool_registry=registry)

        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_call:
            # 使用 JSON 格式指定 tool_call (非 OpenAI tool_calls)
            mock_call.side_effect = [
                LLMResponse(
                    content="",
                    raw={
                        "choices": [{
                            "message": {
                                "content": json.dumps({
                                    "action": "tool_call",
                                    "tool_name": "exec",
                                    "tool_params": {"cmd": "ls"},
                                })
                            }
                        }]
                    },
                ),
                LLMResponse(
                    content="Executed successfully",
                    raw={"choices": [{"message": {"content": "Executed successfully"}}]},
                ),
            ]
            result = await agent.execute(Task(description="Run command"))
            assert result.output == "Executed successfully"
            assert result.tool_calls[0]["tool"] == "exec"
