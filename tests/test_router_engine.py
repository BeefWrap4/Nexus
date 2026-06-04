"""路由引擎测试.

测试RouterEngine的条件评估、变量解析和比较逻辑。
覆盖率目标: 7% → 65%+
"""

import pytest
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import WorkflowState


@pytest.fixture
def router():
    """创建路由引擎实例."""
    return RouterEngine()


@pytest.fixture
def sample_state():
    """创建示例工作流状态."""
    state = WorkflowState(
        run_id="test-run-001",
        workflow_id="wf-001",
        version=1,
    )
    # 设置trigger payload
    state.trigger_payload = {
        "priority": "high",
        "category": "bug",
        "score": 0.85,
        "tags": ["urgent", "backend"],
    }
    # 设置环境变量
    state.env_vars = {
        "ENV": "production",
        "DEBUG": "false",
    }
    # 设置运行变量
    state.run_vars = {
        "retry_count": 3,
        "max_retries": 5,
    }
    # 设置节点输出
    state.node_outputs = {
        "agent_a": {
            "output": {
                "score": 0.92,
                "confidence": 0.88,
                "label": "positive",
            },
            "status": "completed",
        },
        "agent_b": {
            "output": None,
            "status": "pending",
        },
        "tool_call": {
            "result": {"items": [1, 2, 3]},
        },
    }
    return state


class TestEvaluateCondition:
    """测试条件评估功能."""

    def test_empty_condition_returns_true(self, router, sample_state):
        """空条件应返回True."""
        assert router.evaluate_condition("", sample_state) is True
        assert router.evaluate_condition("   ", sample_state) is True

    def test_exists_operator_existing_path(self, router, sample_state):
        """测试exists操作符 - 路径存在."""
        assert router.evaluate_condition("exists trigger.priority", sample_state) is True
        assert router.evaluate_condition("exists agent_a.output", sample_state) is True
        assert router.evaluate_condition("exists env.ENV", sample_state) is True

    def test_exists_operator_non_existing_path(self, router, sample_state):
        """测试exists操作符 - 路径不存在."""
        assert router.evaluate_condition("exists agent_c.output", sample_state) is False
        assert router.evaluate_condition("exists nonexistent.field", sample_state) is False

    def test_not_exists_operator(self, router, sample_state):
        """测试not_exists操作符."""
        assert router.evaluate_condition("not_exists agent_b.output", sample_state) is True
        assert router.evaluate_condition("not_exists trigger.priority", sample_state) is False

    def test_comparison_equal(self, router, sample_state):
        """测试相等比较."""
        assert router.evaluate_condition("trigger.priority == 'high'", sample_state) is True
        assert router.evaluate_condition("trigger.category == 'bug'", sample_state) is True
        assert router.evaluate_condition("agent_a.output.score == 0.92", sample_state) is True
        assert router.evaluate_condition("trigger.priority == 'low'", sample_state) is False

    def test_comparison_not_equal(self, router, sample_state):
        """测试不等比较."""
        assert router.evaluate_condition("trigger.priority != 'low'", sample_state) is True
        assert router.evaluate_condition("agent_a.output.label != 'negative'", sample_state) is True

    def test_comparison_greater_than(self, router, sample_state):
        """测试大于比较."""
        assert router.evaluate_condition("agent_a.output.score > 0.8", sample_state) is True
        assert router.evaluate_condition("trigger.score > 0.9", sample_state) is False

    def test_comparison_less_than(self, router, sample_state):
        """测试小于比较."""
        assert router.evaluate_condition("trigger.score < 0.9", sample_state) is True
        assert router.evaluate_condition("agent_a.output.score < 0.5", sample_state) is False

    def test_comparison_greater_equal(self, router, sample_state):
        """测试大于等于比较."""
        assert router.evaluate_condition("agent_a.output.score >= 0.92", sample_state) is True
        assert router.evaluate_condition("agent_a.output.score >= 0.93", sample_state) is False

    def test_comparison_less_equal(self, router, sample_state):
        """测试小于等于比较."""
        assert router.evaluate_condition("trigger.score <= 0.85", sample_state) is True
        assert router.evaluate_condition("trigger.score <= 0.84", sample_state) is False

    def test_contains_operator_list(self, router, sample_state):
        """测试contains操作符 - 列表."""
        assert router.evaluate_condition("trigger.tags contains 'urgent'", sample_state) is True
        assert router.evaluate_condition("trigger.tags contains 'frontend'", sample_state) is False

    def test_contains_operator_string(self, router, sample_state):
        """测试contains操作符 - 字符串."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"text": "hello world"}
        assert router.evaluate_condition("trigger.text contains 'world'", state) is True
        assert router.evaluate_condition("trigger.text contains 'xyz'", state) is False

    def test_in_operator(self, router, sample_state):
        """测试in操作符."""
        assert router.evaluate_condition("'urgent' in trigger.tags", sample_state) is True
        assert router.evaluate_condition("'frontend' in trigger.tags", sample_state) is False

    def test_matches_operator_regex(self, router, sample_state):
        """测试matches正则表达式操作符."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"email": "user@example.com"}
        assert router.evaluate_condition("trigger.email matches '.*@example\\.com'", state) is True
        assert router.evaluate_condition("trigger.email matches '.*@test\\.com'", state) is False

    def test_env_variable_access(self, router, sample_state):
        """测试环境变量访问."""
        assert router.evaluate_condition("env.ENV == 'production'", sample_state) is True
        assert router.evaluate_condition("env.DEBUG == 'false'", sample_state) is True
        assert router.evaluate_condition("env.NONEXISTENT == 'value'", sample_state) is False

    def test_run_variable_access(self, router, sample_state):
        """测试运行变量访问."""
        assert router.evaluate_condition("run.retry_count == 3", sample_state) is True
        assert router.evaluate_condition("run.max_retries == 5", sample_state) is True
        # Router engine不支持两个变量之间的直接比较，只支持变量与字面量比较
        assert router.evaluate_condition("run.retry_count < 10", sample_state) is True

    def test_node_output_nested_access(self, router, sample_state):
        """测试节点输出嵌套访问."""
        assert router.evaluate_condition("agent_a.output.score > 0.9", sample_state) is True
        assert router.evaluate_condition("agent_a.output.confidence > 0.8", sample_state) is True
        assert router.evaluate_condition("agent_a.status == 'completed'", sample_state) is True

    def test_type_mismatch_comparison(self, router, sample_state):
        """测试类型不匹配时的比较."""
        # 字符串与数字比较应返回False
        assert router.evaluate_condition("trigger.priority > 10", sample_state) is False

    def test_null_value_handling(self, router, sample_state):
        """测试null值处理."""
        assert router.evaluate_condition("agent_b.output == null", sample_state) is True
        assert router.evaluate_condition("agent_b.output == None", sample_state) is True


class TestGetValue:
    """测试_get_value方法."""

    def test_get_trigger_field(self, router, sample_state):
        """测试获取trigger字段."""
        value = router._get_value("trigger.priority", sample_state)
        assert value == "high"

    def test_get_env_variable(self, router, sample_state):
        """测试获取环境变量."""
        value = router._get_value("env.ENV", sample_state)
        assert value == "production"

    def test_get_run_variable(self, router, sample_state):
        """测试获取运行变量."""
        value = router._get_value("run.retry_count", sample_state)
        assert value == 3

    def test_get_node_output(self, router, sample_state):
        """测试获取节点输出."""
        value = router._get_value("agent_a.output.score", sample_state)
        assert value == 0.92

    def test_get_nonexistent_path(self, router, sample_state):
        """测试获取不存在的路径."""
        value = router._get_value("nonexistent.field", sample_state)
        assert value is None

    def test_get_empty_path(self, router, sample_state):
        """测试获取空路径."""
        value = router._get_value("", sample_state)
        assert value is None


class TestParseLiteral:
    """测试_parse_literal方法."""

    def test_parse_string_double_quotes(self, router):
        """测试解析双引号字符串."""
        assert router._parse_literal('"hello"') == "hello"
        assert router._parse_literal('"world 123"') == "world 123"

    def test_parse_string_single_quotes(self, router):
        """测试解析单引号字符串."""
        assert router._parse_literal("'hello'") == "hello"
        assert router._parse_literal("'test value'") == "test value"

    def test_parse_boolean_true(self, router):
        """测试解析布尔值true."""
        assert router._parse_literal("true") is True
        assert router._parse_literal("True") is True
        assert router._parse_literal("TRUE") is True

    def test_parse_boolean_false(self, router):
        """测试解析布尔值false."""
        assert router._parse_literal("false") is False
        assert router._parse_literal("False") is False
        assert router._parse_literal("FALSE") is False

    def test_parse_null(self, router):
        """测试解析null值."""
        assert router._parse_literal("null") is None
        assert router._parse_literal("None") is None
        assert router._parse_literal("NULL") is None

    def test_parse_integer(self, router):
        """测试解析整数."""
        assert router._parse_literal("42") == 42
        assert router._parse_literal("-10") == -10
        assert router._parse_literal("0") == 0

    def test_parse_float(self, router):
        """测试解析浮点数."""
        assert router._parse_literal("3.14") == 3.14
        assert router._parse_literal("-0.5") == -0.5
        assert router._parse_literal("1.0") == 1.0

    def test_parse_unquoted_string(self, router):
        """测试解析未加引号的字符串."""
        assert router._parse_literal("hello") == "hello"
        assert router._parse_literal("test_value") == "test_value"


class TestCompare:
    """测试_compare方法."""

    def test_compare_equal(self, router):
        """测试相等比较."""
        assert router._compare(1, 1, "==") is True
        assert router._compare("a", "a", "==") is True
        assert router._compare(1, 2, "==") is False

    def test_compare_not_equal(self, router):
        """测试不等比较."""
        assert router._compare(1, 2, "!=") is True
        assert router._compare("a", "b", "!=") is True
        assert router._compare(1, 1, "!=") is False

    def test_compare_less_than(self, router):
        """测试小于比较."""
        assert router._compare(1, 2, "<") is True
        assert router._compare(2, 1, "<") is False
        assert router._compare(1, 1, "<") is False

    def test_compare_greater_than(self, router):
        """测试大于比较."""
        assert router._compare(2, 1, ">") is True
        assert router._compare(1, 2, ">") is False
        assert router._compare(1, 1, ">") is False

    def test_compare_less_equal(self, router):
        """测试小于等于比较."""
        assert router._compare(1, 2, "<=") is True
        assert router._compare(1, 1, "<=") is True
        assert router._compare(2, 1, "<=") is False

    def test_compare_greater_equal(self, router):
        """测试大于等于比较."""
        assert router._compare(2, 1, ">=") is True
        assert router._compare(1, 1, ">=") is True
        assert router._compare(1, 2, ">=") is False

    def test_compare_type_error(self, router):
        """测试类型错误时的比较."""
        assert router._compare("string", 123, ">") is False
        assert router._compare(None, 123, "==") is False


class TestEdgeCases:
    """测试边界情况."""

    def test_whitespace_handling(self, router, sample_state):
        """测试空白字符处理."""
        assert router.evaluate_condition("  trigger.priority  ==  'high'  ", sample_state) is True

    def test_complex_nested_path(self, router, sample_state):
        """测试复杂嵌套路径."""
        assert router.evaluate_condition("agent_a.output.score > 0.5", sample_state) is True

    def test_missing_intermediate_node(self, router, sample_state):
        """测试中间节点缺失的情况."""
        assert router.evaluate_condition("nonexistent.output.score > 0", sample_state) is False

    def test_dict_contains(self, router, sample_state):
        """测试字典的contains操作."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"data": {"key": "value"}}
        # contains对dict检查key是否存在
        result = router.evaluate_condition("trigger.data contains 'key'", state)
        assert result is True

    def test_contains_non_container(self, router):
        """contains操作符左侧不是容器类型返回False (覆盖line 63)."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"number": 42}
        assert router.evaluate_condition("trigger.number contains 'anything'", state) is False

    def test_in_non_container(self, router):
        """in操作符右侧不是容器类型返回False (覆盖line 72)."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"number": 42}
        assert router.evaluate_condition("'anything' in trigger.number", state) is False

    def test_trigger_nested_non_dict(self, router):
        """trigger嵌套路径中遇到非dict值返回None (覆盖line 108)."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"nested": 42}  # nested is not a dict
        assert router._get_value("trigger.nested.key", state) is None

    def test_node_output_non_dict(self, router):
        """节点输出非dict值时返回None (覆盖line 127)."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.node_outputs = {"node1": 42}  # node1 output is not a dict
        assert router._get_value("node1.field", state) is None

    def test_compare_invalid_operator(self, router):
        """无效的比较操作符返回False (覆盖line 179)."""
        assert router._compare(1, 1, "invalid") is False
        assert router._compare(1, 1, "===") is False

    def test_none_condition(self, router, sample_state):
        """None条件返回True."""
        assert router.evaluate_condition(None, sample_state) is True

    def test_contains_string(self, router):
        """contains操作符检查字符串包含."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"text": "hello world"}
        assert router.evaluate_condition("trigger.text contains 'world'", state) is True

    def test_in_string(self, router):
        """in操作符检查字符串包含."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = {"text": "hello world"}
        assert router.evaluate_condition("'hello' in trigger.text", state) is True

    def test_default_true_unmatched(self, router, sample_state):
        """无法匹配任何操作符的条件默认为True."""
        assert router.evaluate_condition("somegarbage", sample_state) is True
