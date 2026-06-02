"""LLM集成测试.

针对DeepSeek API (OpenAI兼容接口) 验证:
- LLMClient连通性
- BaseAgent执行链路
- LLMResponse字段完整性

运行方式::

    pytest tests/test_llm_integration.py -v -m integration
"""

import pytest

from nexus.agent import BaseAgent, AgentConfig, Task
from nexus.agent.llm_client import LLMClient


# ---------------------------------------------------------------------------
# LLMClient 连通性
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectivity(deepseek_api: dict[str, str]) -> None:
    """验证DeepSeek API能正常连通.

    用简短的 ``say hello`` 调用DeepSeek API，确保不报错且有内容返回。
    """
    async with LLMClient(
        proxy_url=deepseek_api["base_url"],
        api_key=deepseek_api["api_key"],
    ) as client:
        response = await client.call(
            system_prompt="You are a helpful assistant.",
            user_prompt="say hello",
            model=deepseek_api["model"],
            provider="deepseek",
            max_tokens=200,
        )

    assert response is not None
    assert response.content, "response.content should be non-empty"
    assert len(response.content) > 0


# ---------------------------------------------------------------------------
# BaseAgent 执行链路
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_execute(deepseek_api: dict[str, str]) -> None:
    """验证BaseAgent通过DeepSeek执行简单任务.

    构造一个配置了DeepSeek的BaseAgent，执行一个简单问答任务，
    确认Agent能完成执行并返回AgentResult。
    """
    config = AgentConfig(
        name="TestAgent",
        role="a helpful testing assistant",
        goal="Answer simple questions accurately",
        model=deepseek_api["model"],
        provider="deepseek",
        max_tokens=400,
        max_iterations=5,
        temperature=0.3,
    )

    async with LLMClient(
        proxy_url=deepseek_api["base_url"],
        api_key=deepseek_api["api_key"],
    ) as llm_client:
        agent = BaseAgent(config=config, llm_client=llm_client)
        task = Task(
            description="What is 2 + 2? Give only the number.",
            expected_output="4",
        )
        result = await agent.execute(task)

    assert result is not None
    assert result.status == "success"
    assert result.output, "AgentResult.output should be non-empty"
    assert "4" in result.output


# ---------------------------------------------------------------------------
# LLMResponse 字段完整性
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_completion_stats(deepseek_api: dict[str, str]) -> None:
    """验证LLMResponse的content和total_tokens字段均非空.

    DeepSeek会返回usage统计，确保LLMResponse正确解析并暴露这些字段。
    """
    async with LLMClient(
        proxy_url=deepseek_api["base_url"],
        api_key=deepseek_api["api_key"],
    ) as client:
        response = await client.call(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the capital of France? Answer in one word.",
            model=deepseek_api["model"],
            provider="deepseek",
            max_tokens=100,
        )

    # content
    assert response.content, "response.content should be non-empty"
    assert "Paris" in response.content

    # token stats
    assert response.total_tokens > 0, (
        f"total_tokens should be > 0, got {response.total_tokens}"
    )
    assert response.prompt_tokens > 0, (
        f"prompt_tokens should be > 0, got {response.prompt_tokens}"
    )
    assert response.completion_tokens > 0, (
        f"completion_tokens should be > 0, got {response.completion_tokens}"
    )

    # model field present
    assert response.model, "response.model should be non-empty"
