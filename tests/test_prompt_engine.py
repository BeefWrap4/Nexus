"""Prompt Engine 测试 — Phase 6.2.

覆盖：
- PromptEngine.render: Jinja2 变量替换、条件分支
- PromptEngine.extract_variables: 变量名提取
- PromptEngine.validate: 语法校验
- SandboxedEnvironment: SSTI 防护
- BaseAgent._build_system_prompt: 模板解析集成
"""

import pytest

from unittest.mock import AsyncMock, patch

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.agent.llm_client import LLMResponse
from nexus.prompts.engine import PromptEngine, RenderedPrompt


class TestPromptEngineRender:
    """Test PromptEngine.render()."""

    def test_simple_variable_replacement(self):
        """简单变量替换."""
        engine = PromptEngine()
        result = engine.render("Hello {{ name }}!", {"name": "World"})
        assert result.content == "Hello World!"
        assert "name" in result.variables_used
        assert result.missing_variables == []

    def test_multiple_variables(self):
        """多个变量替换."""
        engine = PromptEngine()
        result = engine.render(
            "{{ greeting }} {{ name }}, you are {{ age }} years old.",
            {"greeting": "Hi", "name": "Alice", "age": "30"},
        )
        assert result.content == "Hi Alice, you are 30 years old."
        assert sorted(result.variables_used) == ["age", "greeting", "name"]

    def test_missing_variables(self):
        """缺失变量检测."""
        engine = PromptEngine()
        result = engine.render("Hello {{ name }}!", {})
        assert result.content == "Hello !"
        assert result.variables_used == []
        assert result.missing_variables == ["name"]

    def test_conditional_branch(self):
        """Jinja2 条件分支."""
        engine = PromptEngine()
        template = "{% if formal %}Dear {{ title }} {{ name }}{% else %}Hey {{ name }}{% endif %}"
        result = engine.render(template, {"formal": True, "title": "Dr.", "name": "Smith"})
        assert result.content == "Dear Dr. Smith"

    def test_loop(self):
        """Jinja2 循环."""
        engine = PromptEngine()
        template = "Items: {% for item in items %}{{ item }}{% if not loop.last %}, {% endif %}{% endfor %}"
        result = engine.render(template, {"items": ["a", "b", "c"]})
        assert result.content == "Items: a, b, c"

    def test_empty_variables(self):
        """空变量字典."""
        engine = PromptEngine()
        result = engine.render("Hello world!", {})
        assert result.content == "Hello world!"
        assert result.missing_variables == []


class TestPromptEngineExtractVariables:
    """Test PromptEngine.extract_variables()."""

    def test_extract_simple_variables(self):
        """提取简单变量."""
        engine = PromptEngine()
        vars_found = engine.extract_variables("Hello {{ name }}, your age is {{ age }}")
        assert vars_found == ["age", "name"]

    def test_extract_with_conditions(self):
        """条件语句中的变量提取."""
        engine = PromptEngine()
        vars_found = engine.extract_variables("{% if active %}{{ name }}{% endif %}")
        assert "active" in vars_found
        assert "name" in vars_found

    def test_extract_with_loops(self):
        """循环中的变量提取."""
        engine = PromptEngine()
        vars_found = engine.extract_variables("{% for item in items %}{{ item }}{% endfor %}")
        assert "items" in vars_found

    def test_extract_no_variables(self):
        """无变量模板."""
        engine = PromptEngine()
        vars_found = engine.extract_variables("Hello world!")
        assert vars_found == []

    def test_extract_invalid_template(self):
        """无效模板返回空列表."""
        engine = PromptEngine()
        vars_found = engine.extract_variables("{% unclosed")
        assert vars_found == []


class TestPromptEngineValidate:
    """Test PromptEngine.validate()."""

    def test_valid_template(self):
        """有效模板."""
        engine = PromptEngine()
        is_valid, error = engine.validate("Hello {{ name }}!")
        assert is_valid is True
        assert error == ""

    def test_invalid_syntax(self):
        """无效语法."""
        engine = PromptEngine()
        is_valid, error = engine.validate("{% if %}")
        assert is_valid is False
        assert len(error) > 0  # Any error message is fine


class TestSSTIProtection:
    """Test SandboxedEnvironment prevents SSTI."""

    def test_no_os_module_access(self):
        """无法访问 os 模块."""
        engine = PromptEngine()
        # 尝试 SSTI payload
        with pytest.raises(ValueError):
            engine.render("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})

    def test_no_file_access(self):
        """无法访问文件系统."""
        engine = PromptEngine()
        with pytest.raises(ValueError):
            engine.render("{{ open('/etc/passwd').read() }}", {})


class TestBaseAgentPromptTemplate:
    """Test BaseAgent integrates with template rendering."""

    @pytest.mark.asyncio
    async def test_agent_uses_template_variables(self):
        """AgentConfig.template_variables 应被渲染到 system_prompt."""
        config = AgentConfig(
            name="test",
            system_prompt="You are a {{ role }} assistant.",
            template_variables={"role": "coding"},
        )
        agent = BaseAgent(config=config)

        # _build_system_prompt 应在 execute 循环中被调用
        with patch.object(agent.llm_client, "call", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = LLMResponse(
                content="done",
                raw={"choices": [{"message": {"content": "done"}}]},
            )
            with patch.object(agent.decision_parser, "parse") as mock_parse:
                from nexus.agent.decision_parser import AgentDecision
                mock_parse.return_value = AgentDecision(
                    action="final_answer", content="done"
                )
                await agent.execute(Task(description="test"))

        # 验证 LLM 调用时 system_prompt 包含渲染后的内容
        call_args = mock_llm.call_args
        system_prompt = call_args.kwargs.get("system_prompt", "")
        assert "coding assistant" in system_prompt
