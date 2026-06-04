"""执行器测试.

测试Agent、Tool和Code执行器的核心功能。
覆盖率目标: 16-34% → 60%+
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.config import settings
from nexus.engine.executors.agent import AgentNodeExecutor
from nexus.engine.executors.tool import ToolNodeExecutor
from nexus.engine.workflow_types import Node, NodeResult
from nexus.engine.state_manager import WorkflowState
from nexus.engine.enums import NodeStatus
from nexus.tools.registry import ToolRegistry


@pytest.fixture
def sample_node():
    """创建示例节点."""
    return Node(
        id="test-node",
        type="agent",
        config={
            "agent_name": "test_agent",
            "agent_role": "assistant",
            "agent_goal": "help user",
            "task_description": "Answer the question",
            "model": "gpt-4o",
            "provider": "openai",
        },
    )


@pytest.fixture
def sample_state():
    """创建示例工作流状态."""
    state = WorkflowState(
        run_id="test-run-001",
        workflow_id="wf-001",
        version=1,
    )
    state.env_vars = {
        "tenant_id": "tenant-123",
        "user_id": "user-456",
    }
    return state


class TestAgentNodeExecutor:
    """测试Agent节点执行器."""

    @pytest.mark.asyncio
    async def test_execute_basic(self, sample_node, sample_state):
        """测试基本Agent执行."""
        # Mock BaseAgent
        mock_agent_result = MagicMock()
        mock_agent_result.output = "Test output"
        mock_agent_result.reasoning = "Test reasoning"
        mock_agent_result.tool_calls = []
        mock_agent_result.confidence = 0.9

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = mock_agent_result

        executor = AgentNodeExecutor()

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                result = await executor.execute(
                    node=sample_node,
                    inputs={},
                    state=sample_state,
                    run_id="test-run-001",
                )

        assert isinstance(result, NodeResult)
        assert result.node_id == "test-node"
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["output"] == "Test output"
        assert result.output["reasoning"] == "Test reasoning"
        assert result.output["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_execute_with_custom_config(self, sample_state):
        """测试自定义配置的Agent执行."""
        node = Node(
            id="custom-agent",
            type="agent",
            config={
                "agent_name": "custom_agent",
                "agent_role": "expert",
                "agent_goal": "solve problems",
                "task_description": "Analyze data",
                "model": "claude-sonnet",
                "provider": "anthropic",
                "temperature": 0.8,
                "max_tokens": 2000,
                "output_key": "analysis_result",
            },
        )

        mock_agent_result = MagicMock()
        mock_agent_result.output = {"analysis": "complete"}
        mock_agent_result.reasoning = ""
        mock_agent_result.tool_calls = []
        mock_agent_result.confidence = 0.85

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = mock_agent_result

        executor = AgentNodeExecutor()

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                result = await executor.execute(
                    node=node,
                    inputs={},
                    state=sample_state,
                    run_id="test-run-001",
                )

        assert result.status == NodeStatus.SUCCEEDED
        # 验证输出被保存到run_vars
        assert "analysis_result" in sample_state.run_vars

    @pytest.mark.asyncio
    async def test_execute_with_tools(self, sample_state):
        """测试带工具的Agent执行."""
        node = Node(
            id="agent-with-tools",
            type="agent",
            config={
                "agent_name": "tool_agent",
                "task_description": "Use tools to answer",
                "tools": ["search", "calculator"],
            },
        )

        mock_agent_result = MagicMock()
        mock_agent_result.output = "Answer using tools"
        mock_agent_result.reasoning = "Used search tool"
        mock_agent_result.tool_calls = [
            {"name": "search", "arguments": {"query": "test"}}
        ]
        mock_agent_result.confidence = 0.95

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = mock_agent_result

        executor = AgentNodeExecutor()

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                result = await executor.execute(
                    node=node,
                    inputs={},
                    state=sample_state,
                    run_id="test-run-001",
                )

        assert result.status == NodeStatus.SUCCEEDED
        assert len(result.output["tool_calls"]) == 1

    @pytest.mark.asyncio
    async def test_execute_with_memory(self, sample_state):
        """测试带记忆的Agent执行."""
        node = Node(
            id="agent-with-memory",
            type="agent",
            config={
                "agent_name": "memory_agent",
                "task_description": "Remember context",
            },
        )

        mock_agent_result = MagicMock()
        mock_agent_result.output = "Contextual answer"
        mock_agent_result.reasoning = ""
        mock_agent_result.tool_calls = []
        mock_agent_result.confidence = 0.9

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = mock_agent_result

        mock_memory_backend = MagicMock()

        executor = AgentNodeExecutor(memory_backend=mock_memory_backend)

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                with patch('nexus.config.settings.AGENT_MEMORY_ENABLED', True):
                    result = await executor.execute(
                        node=node,
                        inputs={},
                        state=sample_state,
                        run_id="test-run-001",
                    )

        assert result.status == NodeStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_execute_exception_handling(self, sample_node, sample_state):
        """测试异常处理."""
        mock_agent = AsyncMock()
        mock_agent.execute.side_effect = Exception("Agent execution failed")

        executor = AgentNodeExecutor()

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                result = await executor.execute(
                    node=sample_node,
                    inputs={},
                    state=sample_state,
                    run_id="test-run-001",
                )

        assert result.status == NodeStatus.FAILED
        assert "error" in result.__dict__ or hasattr(result, 'error')

    @pytest.mark.asyncio
    async def test_execute_with_template_id(self, sample_state):
        """测试带模板ID的Agent执行."""
        from uuid import uuid4
        
        template_id = str(uuid4())
        node = Node(
            id="template-agent",
            type="agent",
            config={
                "agent_name": "template_agent",
                "task_description": "Use template",
                "system_prompt_template_id": template_id,
                "template_variables": {"var1": "value1"},
            },
        )

        mock_agent_result = MagicMock()
        mock_agent_result.output = "Template-based output"
        mock_agent_result.reasoning = ""
        mock_agent_result.tool_calls = []
        mock_agent_result.confidence = 0.88

        mock_agent = AsyncMock()
        mock_agent.execute.return_value = mock_agent_result

        executor = AgentNodeExecutor()

        with patch('nexus.engine.executors.agent.BaseAgent', return_value=mock_agent):
            with patch('nexus.engine.executors.agent.create_llm_client'):
                result = await executor.execute(
                    node=node,
                    inputs={},
                    state=sample_state,
                    run_id="test-run-001",
                )

        assert result.status == NodeStatus.SUCCEEDED


class TestToolNodeExecutor:
    """测试Tool节点执行器."""

    @pytest.fixture
    def tool_registry(self):
        """创建工具注册表."""
        return ToolRegistry()

    @pytest.fixture
    def sample_tool_node(self):
        """创建示例工具节点."""
        return Node(
            id="test-tool-node",
            type="tool",
            config={
                "tool_name": "test_tool",
            },
        )

    @pytest.mark.asyncio
    async def test_execute_basic(self, sample_tool_node, sample_state, tool_registry):
        """测试基本工具执行."""
        # Mock tool
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.config = {}
        mock_tool.auth_config = None
        mock_tool.schema = None

        tool_registry.register(mock_tool)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"result": "success"}
        mock_result.metadata = {"execution_time": 0.1}

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        with patch.object(tool_registry, 'execute', return_value=mock_result):
            result = await executor.execute(
                node=sample_tool_node,
                inputs={"param1": "value1"},
                state=sample_state,
                run_id="test-run-001",
            )

        assert isinstance(result, NodeResult)
        assert result.node_id == "test-tool-node"
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["data"]["result"] == "success"

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, sample_tool_node, sample_state, tool_registry):
        """测试工具不存在的情况."""
        executor = ToolNodeExecutor(tool_registry=tool_registry)

        result = await executor.execute(
            node=sample_tool_node,
            inputs={},
            state=sample_state,
            run_id="test-run-001",
        )

        assert result.status == NodeStatus.FAILED
        assert "not found" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_missing_tool_name(self, sample_state, tool_registry):
        """测试缺少工具名称的情况."""
        node = Node(
            id="no-tool-name",
            type="tool",
            config={},
        )

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        result = await executor.execute(
            node=node,
            inputs={},
            state=sample_state,
            run_id="test-run-001",
        )

        assert result.status == NodeStatus.FAILED
        assert "not specified" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_tool_failure(self, sample_tool_node, sample_state, tool_registry):
        """测试工具执行失败的情况."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.config = {}
        tool_registry.register(mock_tool)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Tool execution error"

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        with patch.object(tool_registry, 'execute', return_value=mock_result):
            result = await executor.execute(
                node=sample_tool_node,
                inputs={},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.FAILED
        assert result.error["message"] == "Tool execution error"

    @pytest.mark.asyncio
    async def test_execute_with_exception(self, sample_tool_node, sample_state, tool_registry):
        """测试工具执行抛出异常的情况."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.config = {}
        tool_registry.register(mock_tool)

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        with patch.object(tool_registry, 'execute', side_effect=Exception("Unexpected error")):
            result = await executor.execute(
                node=sample_tool_node,
                inputs={},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_stream_mode(self, sample_state, tool_registry):
        """测试流式工具执行."""
        node = Node(
            id="stream-tool",
            type="tool",
            config={
                "tool_name": "stream_tool",
                "url": "http://test-api/stream",
                "method": "GET",
            },
        )

        mock_tool = MagicMock()
        mock_tool.name = "stream_tool"
        mock_tool.config = {
            "stream": True,
            "url": "http://test-api/stream",
            "method": "GET",
        }
        mock_tool.auth_config = None
        mock_tool.schema = None
        tool_registry.register(mock_tool)

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        # Mock HTTP stream response
        import httpx
        
        async def mock_iter_lines():
            yield "data: chunk1"
            yield "data: chunk2"
            yield "data: [DONE]"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_iter_lines

        class MockStreamContext:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                pass

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # 关键修复：stream方法直接返回上下文管理器，不需要await
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await executor.execute(
                node=node,
                inputs={"param": "value"},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["data"]["streamed"] is True
        assert result.output["metadata"]["chunks"] == 2

    @pytest.mark.asyncio
    async def test_execute_stream_with_auth(self, sample_state, tool_registry):
        """测试带认证的流式工具执行."""
        node = Node(
            id="auth-stream-tool",
            type="tool",
            config={
                "tool_name": "auth_stream_tool",
            },
        )

        mock_tool = MagicMock()
        mock_tool.name = "auth_stream_tool"
        mock_tool.config = {
            "stream": True,
            "url": "http://test-api/stream",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
        }
        mock_tool.auth_config = {
            "type": "bearer",
            "token": "test-token-123",
        }
        mock_tool.schema = None
        tool_registry.register(mock_tool)

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        async def mock_iter_lines():
            yield "data: response"
            yield "data: [DONE]"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_iter_lines

        class MockStreamContext:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                pass

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # 关键修复：stream方法直接返回上下文管理器
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await executor.execute(
                node=node,
                inputs={"query": "test"},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_execute_stream_with_url_params(self, sample_state, tool_registry):
        """测试带URL参数的流式工具执行."""
        node = Node(
            id="url-param-tool",
            type="tool",
            config={
                "tool_name": "url_param_tool",
            },
        )

        mock_tool = MagicMock()
        mock_tool.name = "url_param_tool"
        mock_tool.config = {
            "stream": True,
            "url": "http://test-api/{resource}/data",
            "method": "GET",
        }
        mock_tool.auth_config = None
        mock_tool.schema = None
        tool_registry.register(mock_tool)

        executor = ToolNodeExecutor(tool_registry=tool_registry)

        async def mock_iter_lines():
            yield "data: result"
            yield "data: [DONE]"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_iter_lines

        class MockStreamContext:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                pass

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # 关键修复：stream方法直接返回上下文管理器
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await executor.execute(
                node=node,
                inputs={"resource": "users", "filter": "active"},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_execute_stream_with_event_bus(self, sample_state, tool_registry):
        """测试带事件总线的流式工具执行."""
        node = Node(
            id="event-bus-tool",
            type="tool",
            config={
                "tool_name": "event_bus_tool",
            },
        )

        mock_tool = MagicMock()
        mock_tool.name = "event_bus_tool"
        mock_tool.config = {
            "stream": True,
            "url": "http://test-api/stream",
            "method": "GET",
        }
        mock_tool.auth_config = None
        mock_tool.schema = None
        tool_registry.register(mock_tool)

        mock_event_bus = AsyncMock()

        executor = ToolNodeExecutor(tool_registry=tool_registry, event_bus=mock_event_bus)

        async def mock_iter_lines():
            yield "data: chunk1"
            yield "data: chunk2"
            yield "data: [DONE]"

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_iter_lines

        class MockStreamContext:
            async def __aenter__(self):
                return mock_response
            async def __aexit__(self, *args):
                pass

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # 关键修复：stream方法直接返回上下文管理器
            mock_client.stream = MagicMock(return_value=MockStreamContext())
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await executor.execute(
                node=node,
                inputs={},
                state=sample_state,
                run_id="test-run-001",
            )

        assert result.status == NodeStatus.SUCCEEDED
        # 验证事件总线被调用
        assert mock_event_bus.publish.call_count >= 2  # 至少chunk和end事件


# =============================================================================
# Boundary Executor Tests (StartNodeExecutor + EndNodeExecutor)
# =============================================================================


class TestStartNodeExecutor:
    """StartNodeExecutor 测试——将 trigger_payload 注入 run_vars."""

    @pytest.fixture
    def executor(self):
        from nexus.engine.executors.boundary import StartNodeExecutor
        return StartNodeExecutor()

    @pytest.fixture
    def state(self):
        return WorkflowState(
            run_id="run_1",
            workflow_id="wf_1",
            version=1,
            trigger_payload={"name": "test", "priority": "high"},
        )

    @pytest.mark.asyncio
    async def test_default_maps_entire_trigger_to_run_vars(self, executor, state):
        """无 output_mapping 时，整个 trigger_payload 写入 run_vars["trigger"]."""
        node = Node(id="start", type="start", config={})
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.run_vars["trigger"] == {"name": "test", "priority": "high"}
        assert result.output["trigger_payload"] == {"name": "test", "priority": "high"}

    @pytest.mark.asyncio
    async def test_output_mapping_maps_specific_fields(self, executor, state):
        """output_mapping 按字段映射 trigger_payload 到 run_vars."""
        node = Node(id="start", type="start", config={
            "output_mapping": {"task_name": "name", "urgency": "priority"},
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.run_vars["task_name"] == "test"
        assert state.run_vars["urgency"] == "high"

    @pytest.mark.asyncio
    async def test_output_mapping_partial_payload(self, executor, state):
        """output_mapping 中引用不存在的 key 时对应值为 None."""
        node = Node(id="start", type="start", config={
            "output_mapping": {"task_name": "name", "missing_key": "no_such_field"},
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.run_vars["task_name"] == "test"
        assert state.run_vars["missing_key"] is None

    @pytest.mark.asyncio
    async def test_result_includes_trigger_payload(self, executor, state):
        """无论有无 mapping，NodeResult.output 始终包含 trigger_payload."""
        node = Node(id="start", type="start", config={
            "output_mapping": {"x": "name"},
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["trigger_payload"] == state.trigger_payload


class TestEndNodeExecutor:
    """EndNodeExecutor 测试——聚合工作流输出并将状态标记为 COMPLETED."""

    @pytest.fixture
    def state(self):
        s = WorkflowState(run_id="run_1", workflow_id="wf_1", version=1)
        s.node_outputs = {"agent_a": {"result": "done"}, "agent_b": {"score": 95}}
        s.run_vars["myvar"] = "hello_world"
        return s

    @pytest.mark.asyncio
    async def test_default_collects_all_node_outputs(self, state):
        """无 output 配置时，直接拷贝 node_outputs 作为最终输出."""
        from nexus.engine.executors.boundary import EndNodeExecutor
        executor = EndNodeExecutor()
        node = Node(id="end", type="end", config={})
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.output == {"agent_a": {"result": "done"}, "agent_b": {"score": 95}}
        assert state.status == "completed"  # RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_expression_mode_resolves_single_result(self, state):
        """expression 模式：VariablePool 解析表达式后写入 state.output["result"]."""
        from nexus.engine.executors.boundary import EndNodeExecutor
        executor = EndNodeExecutor()
        node = Node(id="end", type="end", config={
            "output": {"expression": "{{#run.myvar#}}"},
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.output["result"] == "hello_world"
        assert state.status == "completed"

    @pytest.mark.asyncio
    async def test_mappings_mode_resolves_each_key(self, state):
        """mappings 模式：逐个解析变量表达式生成输出 dict."""
        from nexus.engine.executors.boundary import EndNodeExecutor
        executor = EndNodeExecutor()
        node = Node(id="end", type="end", config={
            "output": {"mappings": {
                "final_result": "{{#agent_a.result#}}",
                "final_score": "{{#agent_b.score#}}",
            }},
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert state.output["final_result"] == "done"
        assert state.output["final_score"] == "95"  # VariablePool returns str
        assert state.status == "completed"

    @pytest.mark.asyncio
    async def test_sets_status_to_completed(self, state):
        """EndNodeExecutor 将 RunStatus 设置为 COMPLETED."""
        from nexus.engine.executors.boundary import EndNodeExecutor
        executor = EndNodeExecutor()
        node = Node(id="end", type="end", config={})
        await executor.execute(node, {}, state, "run_1")
        assert state.status == "completed"


# =============================================================================
# Condition Executor Tests (ConditionNodeExecutor)
# =============================================================================


class TestConditionNodeExecutor:
    """ConditionNodeExecutor 测试——条件分支评估与未匹配分支跳过."""

    @pytest.fixture
    def router(self):
        from nexus.engine.router_engine import RouterEngine
        return RouterEngine()

    @pytest.fixture
    def state(self):
        s = WorkflowState(run_id="run_1", workflow_id="wf_1", version=1)
        s.run_vars["score"] = 85
        s.run_vars["category"] = "premium"
        return s

    @pytest.mark.asyncio
    async def test_no_conditions_returns_none_branch(self, router, state):
        """空条件列表返回 matched_branch=None, result=True."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router)
        node = Node(id="cond", type="condition", config={"conditions": []})
        result = await executor.execute(node, {}, state, "run_1")
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["matched_branch"] is None
        assert result.output["result"] is True

    @pytest.mark.asyncio
    async def test_condition_matches_first_branch(self, router, state):
        """第一条条件匹配时立即返回该 branch_id，不再评估后续."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router)
        node = Node(id="cond", type="condition", config={
            "conditions": [
                {"expression": "run.score > 70", "branch_id": "high_score"},
                {"expression": "run.score <= 70", "branch_id": "low_score"},
            ],
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] == "high_score"

    @pytest.mark.asyncio
    async def test_condition_no_match_falls_to_default(self, router, state):
        """所有条件都不匹配时使用 default_branch."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router)
        node = Node(id="cond", type="condition", config={
            "conditions": [{"expression": "run.score > 100", "branch_id": "impossible"}],
            "default_branch": "fallback_branch",
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] == "fallback_branch"
        assert result.output["result"] is True

    @pytest.mark.asyncio
    async def test_condition_no_match_no_default(self, router, state):
        """无匹配且无 default_branch 时 matched_branch 为 None."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router)
        node = Node(id="cond", type="condition", config={
            "conditions": [{"expression": "run.score > 200", "branch_id": "impossible"}],
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] is None
        assert result.output["result"] is False

    @pytest.mark.asyncio
    async def test_skip_unmatched_branches(self, router, state):
        """有 workflow_def 时，未匹配分支标记为 SKIPPED."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        from nexus.engine.workflow_types import Edge, WorkflowDefinition

        wf_def = WorkflowDefinition(
            nodes=[
                Node(id="cond", type="condition", config={}),
                Node(id="branch_a", type="agent", config={}),
                Node(id="branch_b", type="agent", config={}),
                Node(id="end", type="end", config={}),
            ],
            edges=[
                Edge(source="cond", target="branch_a", condition="high"),
                Edge(source="cond", target="branch_b", condition="low"),
                Edge(source="branch_a", target="end"),
                Edge(source="branch_b", target="end"),
            ],
        )

        executor = ConditionNodeExecutor(router, workflow_def=wf_def)
        node = wf_def.nodes[0]  # the condition node
        node.config = {
            "conditions": [
                {"expression": "run.score > 70", "branch_id": "high"},
                {"expression": "run.score <= 70", "branch_id": "low"},
            ],
        }

        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] == "high"
        # branch_a matched, branch_b should be skipped
        assert state.node_states["branch_b"] == NodeStatus.SKIPPED
        # branch_a should NOT be skipped (matched)
        assert "branch_a" not in state.node_states or state.node_states.get("branch_a") != NodeStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skip_unmatched_no_workflow_def(self, router, state):
        """无 workflow_def 时，不执行跳过逻辑（不抛出异常）."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router, workflow_def=None)
        node = Node(id="cond", type="condition", config={
            "conditions": [{"expression": "run.score > 70", "branch_id": "high"}],
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] == "high"

    @pytest.mark.asyncio
    async def test_skip_unmatched_none_matched(self, router, state):
        """matched_branch 为 None 时不执行跳过逻辑."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        from nexus.engine.workflow_types import Edge, WorkflowDefinition

        wf_def = WorkflowDefinition(
            nodes=[
                Node(id="cond", type="condition", config={}),
                Node(id="branch_a", type="agent", config={}),
            ],
            edges=[Edge(source="cond", target="branch_a", condition="high")],
        )

        executor = ConditionNodeExecutor(router, workflow_def=wf_def)
        node = Node(id="cond", type="condition", config={
            "conditions": [{"expression": "run.score > 200", "branch_id": "high"}],
        })
        result = await executor.execute(node, {}, state, "run_1")
        assert result.output["matched_branch"] is None
        # branch_a should NOT be skipped (matched_branch is None, skip is not called)
        assert state.node_states.get("branch_a") != NodeStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skip_unmatched_direct_call_guards_none_workflow_def(self, router, state):
        """直接调用 _skip_unmatched_branches 时 workflow_def=None 安全返回."""
        from nexus.engine.executors.condition import ConditionNodeExecutor
        executor = ConditionNodeExecutor(router, workflow_def=None)
        node = Node(id="cond", type="condition", config={})
        # 直接调用内部方法，覆盖 defensive guard (line 73)
        await executor._skip_unmatched_branches(node, "high", state)
        # 无异常抛出即为通过


# =============================================================================
# LLM Client Helper Tests (create_llm_client)
# =============================================================================


class TestCreateLLMClient:
    """create_llm_client 测试——Provider 直连 vs LiteLLM Proxy 回退."""

    def test_creates_client_with_direct_provider_credential(self):
        """当环境变量中提供了对应 Provider 的 API Key 时，使用直连 URL."""
        from nexus.engine.executors.llm import create_llm_client

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-test-deepseek-123"}):
            client = create_llm_client({"provider": "deepseek"})
            assert client is not None
            assert client.proxy_url == "https://api.deepseek.com/v1"
            assert client.api_key == "sk-test-deepseek-123"

    def test_creates_client_with_litellm_fallback_unknown_provider(self):
        """未知 Provider 直接走 LiteLLM Proxy fallback 分支."""
        from nexus.engine.executors.llm import create_llm_client

        # 未知 provider 不在 PROVIDER_CONFIGS 中, 直接使用 LiteLLM 配置
        client = create_llm_client({"provider": "unknown_provider"})
        assert client is not None
        # LITELLM_PROXY_URL 的默认值是 http://localhost:4000
        assert "localhost:4000" in client.proxy_url or "litellm" in client.proxy_url

    def test_creates_client_with_litellm_fallback_no_api_key(self):
        """已知 Provider 但环境变量中无 API Key 时，回退到 LiteLLM Proxy."""
        from nexus.engine.executors.llm import create_llm_client

        # openai 在 PROVIDER_CONFIGS 中，但清除 OPENAI_API_KEY 环境变量
        with patch.dict("os.environ", {}, clear=True):
            client = create_llm_client({"provider": "openai"})
            assert client is not None
            # 没有 API key 时使用 LiteLLM Proxy
            assert client.api_key is None or client.api_key == settings.LITELLM_API_KEY

    def test_default_provider_when_empty_dict(self):
        """未指定 provider 时使用 settings.DEFAULT_LLM_PROVIDER (deepseek)."""
        from nexus.engine.executors.llm import create_llm_client

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-default"}):
            client = create_llm_client({})
            assert client is not None
            # deepseek 有 API key 时使用直连
            assert client.proxy_url == "https://api.deepseek.com/v1"
            assert client.api_key == "sk-default"

    def test_llm_settings_is_none(self):
        """传入 None 作为 llm_settings 时正常回退到默认值."""
        from nexus.engine.executors.llm import create_llm_client

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-none-test"}):
            client = create_llm_client(None)
            assert client is not None
            # deepseek 默认 provider，有 API key 时直连
            assert client.proxy_url == "https://api.deepseek.com/v1"
            assert client.api_key == "sk-none-test"
