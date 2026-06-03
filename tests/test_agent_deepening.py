"""Agent 能力深化测试 — Phase 4.

覆盖：
- ReAct + Function Calling: Agent LLM 调用携带 tools schema
- Memory 持久化: InMemoryBackend + RedisBackend
- Crew 协作: Manager-Worker 任务分解与聚合
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.crew import Crew, CrewTask, CrewWorkerResult
from nexus.agent.memory import AgentMemory
from nexus.agent.memory_backend import (
    InMemoryBackend,
    MemoryEntry,
    RedisBackend,
    _keyword_relevance,
    create_memory_backend,
)
from nexus.tools.registry import Tool, ToolRegistry, ToolResult, ToolType


# -----------------------------------------------------------------------------
# Phase 4.1: ReAct + Function Calling
# -----------------------------------------------------------------------------

class TestReActFunctionCalling:
    """测试 Agent ReAct + Function Calling 增强."""

    def test_get_openai_tools_with_registry(self):
        """_get_openai_tools 应返回 OpenAI function spec 格式."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="rag_ask",
                description="RAG问答",
                type=ToolType.HTTP,
                config={},
                schema={
                    "type": "object",
                    "properties": {"prompt": {"type": "string"}},
                },
            )
        )

        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=registry)

        tools = agent._get_openai_tools()
        assert tools is not None
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "rag_ask"
        assert "parameters" in tools[0]["function"]

    def test_get_openai_tools_without_registry(self):
        """无 ToolRegistry 时应返回 None."""
        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=None)
        assert agent._get_openai_tools() is None

    def test_system_prompt_includes_tools(self):
        """System Prompt 应包含可用工具描述."""
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="rag_ask",
                description="语义缓存问答",
                type=ToolType.HTTP,
                config={},
            )
        )

        config = AgentConfig(name="test")
        agent = BaseAgent(config=config, tool_registry=registry)

        prompt = agent._build_system_prompt()
        assert "rag_ask" in prompt
        assert "语义缓存问答" in prompt
        assert "You have access to the following tools" in prompt

    @pytest.mark.asyncio
    async def test_agent_calls_tool_via_registry(self):
        """Agent 应通过 ToolRegistry 实际执行工具."""
        mock_registry = MagicMock()
        mock_registry.list_tools = MagicMock(
            return_value=[
                MagicMock(name="rag_ask", description="RAG", schema={})
            ]
        )
        mock_registry.get_tool = MagicMock(
            return_value=Tool(
                name="rag_ask", description="RAG", type=ToolType.HTTP, config={}
            )
        )
        mock_registry.execute = AsyncMock(
            return_value=ToolResult(success=True, data={"answer": "42"})
        )

        config = AgentConfig(name="test", max_iterations=3)
        agent = BaseAgent(config=config, tool_registry=mock_registry)

        # Mock LLM: 第一轮 tool_call, 第二轮 final_answer
        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            from nexus.agent.llm_client import LLMResponse

            mock_llm.side_effect = [
                LLMResponse(
                    content="",
                    raw={
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "function": {
                                                "name": "rag_ask",
                                                "arguments": json.dumps({"prompt": "test"}),
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                ),
                LLMResponse(
                    content="The answer is 42",
                    raw={"choices": [{"message": {"content": "The answer is 42"}}]},
                ),
            ]

            result = await agent.execute(
                Task(description="What is the answer?"),
                context={"run_id": "r1"},
            )

        assert result.output == "The answer is 42"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "rag_ask"

        # 验证 ToolRegistry 被调用
        mock_registry.execute.assert_called_once()
        call_args = mock_registry.execute.call_args
        assert call_args.kwargs["tool_name"] == "rag_ask"


# -----------------------------------------------------------------------------
# Phase 4.2: Agent Memory 持久化
# -----------------------------------------------------------------------------

class TestMemoryPersistence:
    """测试 Agent Memory 后端持久化."""

    @pytest.mark.asyncio
    async def test_in_memory_backend_save_and_retrieve(self):
        """InMemoryBackend 应支持保存和检索."""
        backend = InMemoryBackend()
        entry = MemoryEntry(
            entry_id="e1",
            content="Task: hello\nResult: world",
            task_description="hello",
            result="world",
            importance=0.8,
        )

        await backend.save("agent_1", entry)
        results = await backend.retrieve("agent_1", "hello", limit=5)

        assert len(results) == 1
        assert results[0].content == "Task: hello\nResult: world"

    @pytest.mark.asyncio
    async def test_in_memory_backend_isolation(self):
        """不同 agent_id 应隔离存储."""
        backend = InMemoryBackend()
        await backend.save("agent_a", MemoryEntry(entry_id="e1", content="A"))
        await backend.save("agent_b", MemoryEntry(entry_id="e2", content="B"))

        results_a = await backend.retrieve("agent_a", "test")
        assert len(results_a) == 1
        assert results_a[0].content == "A"

    @pytest.mark.asyncio
    async def test_agent_memory_with_backend(self):
        """AgentMemory 使用 backend 保存和检索."""
        backend = InMemoryBackend()
        memory = AgentMemory(agent_id="test_agent", backend=backend)

        await memory.save(
            task=Task(description="search for docs"),
            result="Found 5 documents",
        )

        results = await memory.retrieve("search docs", limit=5)
        assert len(results) == 1
        assert "Found 5 documents" in results[0]["result"]

    @pytest.mark.asyncio
    async def test_redis_backend_save_and_retrieve(self):
        """RedisBackend 应支持保存和检索（mock Redis）."""
        mock_redis = MagicMock()
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.hgetall = AsyncMock(
            return_value={"e1": json.dumps({"id": "e1", "content": "hello", "task_description": "", "result": "", "importance": 0.5, "created_at": "2024-01-01T00:00:00"})}
        )

        backend = RedisBackend(mock_redis)
        entry = MemoryEntry(entry_id="e1", content="hello")

        await backend.save("agent_1", entry)
        mock_redis.hset.assert_called_once()

        results = await backend.retrieve("agent_1", "hello")
        assert len(results) == 1
        assert results[0].content == "hello"

    def test_create_memory_backend_factory(self):
        """工厂函数应根据类型创建正确后端."""
        mem = create_memory_backend("memory")
        assert isinstance(mem, InMemoryBackend)

        mock_redis = MagicMock()
        redis_backend = create_memory_backend("redis", mock_redis)
        assert isinstance(redis_backend, RedisBackend)

    def test_keyword_relevance(self):
        """关键词相关性计算."""
        entry = MemoryEntry(
            entry_id="e1",
            content="semantic cache vector search",
            task_description="RAG",
            result="success",
        )
        score = _keyword_relevance(entry, {"semantic", "cache"})
        assert score > 0


# -----------------------------------------------------------------------------
# Phase 4.3: Crew 多 Agent 协作
# -----------------------------------------------------------------------------

class TestCrewCollaboration:
    """测试 Crew Manager-Worker 协作."""

    @pytest.mark.asyncio
    async def test_crew_execution(self):
        """Crew 应能分解任务并聚合结果."""

        # Mock Manager Agent
        mock_manager = MagicMock()
        mock_manager.config = AgentConfig(name="manager")
        mock_manager.llm_client = MagicMock()
        mock_manager.execute = AsyncMock(
            return_value=MagicMock(
                output="Final aggregated answer",
                reasoning="Aggregated",
                tool_calls=[],
                status="success",
            )
        )

        # Mock Worker Agent
        mock_worker = MagicMock()
        mock_worker.config = AgentConfig(name="researcher")
        mock_worker.execute = AsyncMock(
            return_value=MagicMock(
                output="Research result: 5 papers found",
                reasoning="Did research",
                tool_calls=[],
                status="success",
            )
        )

        crew = Crew(manager=mock_manager, workers=[mock_worker])

        # Mock _delegate 直接返回子任务（避免实际 LLM 调用）
        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Research topic", assigned_to="researcher")
            ]

            result = await crew.execute("Analyze this topic")

        assert result.output == "Final aggregated answer"
        assert len(result.worker_results) == 1
        assert result.worker_results[0].output == "Research result: 5 papers found"

    @pytest.mark.asyncio
    async def test_crew_worker_fallback(self):
        """指定 Worker 不存在时应 fallback 到第一个可用 Worker."""
        mock_manager = MagicMock()
        mock_manager.config = AgentConfig(name="manager")
        mock_manager.llm_client = MagicMock()
        mock_manager.execute = AsyncMock(
            return_value=MagicMock(
                output="Done",
                reasoning="",
                tool_calls=[],
                status="success",
            )
        )

        mock_worker = MagicMock()
        mock_worker.config = AgentConfig(name="default_worker")
        mock_worker.execute = AsyncMock(
            return_value=MagicMock(
                output="Handled",
                tool_calls=[],
                status="success",
            )
        )

        crew = Crew(manager=mock_manager, workers=[mock_worker])

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="nonexistent")
            ]

            result = await crew.execute("Test")

        # fallback 到第一个可用 worker，worker_name 反映实际执行的 worker
        assert result.worker_results[0].worker_name == "default_worker"
        assert result.worker_results[0].output == "Handled"

    @pytest.mark.asyncio
    async def test_crew_worker_failure_handling(self):
        """Worker 失败时应记录错误，不影响整体执行."""
        mock_manager = MagicMock()
        mock_manager.config = AgentConfig(name="manager")
        mock_manager.llm_client = MagicMock()
        mock_manager.execute = AsyncMock(
            return_value=MagicMock(output="Done", status="success")
        )

        mock_worker = MagicMock()
        mock_worker.config = AgentConfig(name="worker")
        mock_worker.execute = AsyncMock(side_effect=Exception("Worker crashed"))

        crew = Crew(manager=mock_manager, workers=[mock_worker])

        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                CrewTask(description="Task", assigned_to="worker")
            ]

            result = await crew.execute("Test")

        assert not result.worker_results[0].success
        assert "Worker crashed" in result.worker_results[0].error
