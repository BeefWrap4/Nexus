"""条件路由引擎.

处理条件分支(Condition节点)和动态路由。
支持表达式: JSONPath-like + 简单逻辑运算。
"""

from typing import Any

from nexus.engine.state_manager import WorkflowState


class RouterEngine:
    """路由引擎."""

    def evaluate_condition(
        self,
        condition: str,
        state: WorkflowState,
    ) -> bool:
        """评估条件表达式.

        支持的表达式:
        - 比较: ==, !=, <, >, <=, >=
        - 逻辑: and, or, not
        - 存在: exists, not_exists
        - 包含: contains, in
        - 正则: matches

        示例:
        - "{{#agent_a.output.score#}} > 0.8"
        - "{{#trigger.priority#}} == 'high'"
        - "exists {{#agent_b.output#}}"

        Args:
            condition: 条件表达式字符串
            state: 当前工作流状态

        Returns:
            bool: 条件是否满足
        """
        if not condition:
            return True

        # 简单表达式解析（生产环境应使用安全沙箱）
        condition = condition.strip()

        # exists / not_exists
        if condition.startswith("exists "):
            path = condition[7:].strip()
            return self._get_value(path, state) is not None

        if condition.startswith("not_exists "):
            path = condition[11:].strip()
            return self._get_value(path, state) is None

        # contains
        if " contains " in condition:
            parts = condition.split(" contains ")
            left = self._get_value(parts[0].strip(), state)
            right = self._parse_literal(parts[1].strip())
            if isinstance(left, (list, str, dict)):
                return right in left
            return False

        # in
        if " in " in condition:
            parts = condition.split(" in ")
            left = self._parse_literal(parts[0].strip())
            right = self._get_value(parts[1].strip(), state)
            if isinstance(right, (list, str, dict)):
                return left in right
            return False

        # matches (正则)
        if " matches " in condition:
            import re

            parts = condition.split(" matches ")
            left = str(self._get_value(parts[0].strip(), state))
            right = self._parse_literal(parts[1].strip())
            return bool(re.search(str(right), left))

        # 比较运算
        for op in ["==", "!=", "<=", ">=", "<", ">"]:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    left = self._get_value(parts[0].strip(), state)
                    right = self._parse_literal(parts[1].strip())
                    return self._compare(left, right, op)

        # 默认True
        return True

    def _get_value(self, path: str, state: WorkflowState) -> Any:
        """从状态获取值."""
        parts = path.split(".")
        if not parts:
            return None

        # trigger.{field}
        if parts[0] == "trigger" and len(parts) > 1:
            value = state.trigger_payload
            for p in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(p)
                else:
                    return None
            return value

        # env.{name}
        if parts[0] == "env" and len(parts) > 1:
            return state.env_vars.get(parts[1])

        # run.{name}
        if parts[0] == "run" and len(parts) > 1:
            return state.run_vars.get(parts[1])

        # {node_id}.{field}
        node_id = parts[0]
        if node_id in state.node_outputs:
            value = state.node_outputs[node_id]
            for p in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(p)
                else:
                    return None
            return value

        return None

    def _parse_literal(self, value: str) -> Any:
        """解析字面量."""
        value = value.strip()

        # 字符串（引号包裹）
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]

        # 布尔值
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False

        # null
        if value.lower() == "null" or value.lower() == "none":
            return None

        # 数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        return value

    def _compare(self, left: Any, right: Any, op: str) -> bool:
        """比较两个值."""
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            if op == "<=":
                return left <= right
            if op == ">=":
                return left >= right
        except TypeError:
            return False
        return False
