"""变量池 - 三层变量系统.

借鉴Dify设计:
- env_vars: 环境变量（工作流级）
- run_vars: 运行级变量（跨节点累积）
- node_outputs: 节点输出

变量引用语法: {{#node_id.field_name#}}
"""

import re
from typing import Any

from nexus.engine.state_manager import WorkflowState


VARIABLE_PATTERN = re.compile(r"\{\{#([^#]+)#\}\}")


class VariablePool:
    """变量池."""

    def resolve(self, template: Any, state: WorkflowState) -> Any:
        """解析模板中的变量引用.

        支持的数据类型:
        - str: 字符串中的变量替换
        - dict: 递归解析所有值
        - list: 递归解析所有元素
        - 其他: 原样返回

        Args:
            template: 待解析的模板数据
            state: 当前工作流状态

        Returns:
            解析后的数据
        """
        if isinstance(template, str):
            return self._resolve_string(template, state)
        elif isinstance(template, dict):
            return {
                k: self.resolve(v, state)
                for k, v in template.items()
            }
        elif isinstance(template, list):
            return [self.resolve(item, state) for item in template]
        return template

    def _resolve_string(self, template: str, state: WorkflowState) -> str:
        """解析字符串中的变量引用.

        支持的变量前缀:
        - env.{name}: 环境变量
        - run.{name}: 运行级变量
        - {node_id}.{field}: 节点输出
        - trigger.{field}: 触发数据
        """

        def replace_var(match: re.Match) -> str:
            var_path = match.group(1).strip()
            return self._get_value(var_path, state)

        return VARIABLE_PATTERN.sub(replace_var, template)

    def _get_value(self, var_path: str, state: WorkflowState) -> str:
        """根据变量路径获取值."""
        parts = var_path.split(".")

        if len(parts) < 1:
            return f"{{{{#{var_path}#}}}}"

        # env.{name}
        if parts[0] == "env" and len(parts) >= 2:
            return str(state.env_vars.get(parts[1], f"{{{{#{var_path}#}}}}"))

        # run.{name}
        if parts[0] == "run" and len(parts) >= 2:
            return str(state.run_vars.get(parts[1], f"{{{{#{var_path}#}}}}"))

        # trigger.{field}
        if parts[0] == "trigger" and len(parts) >= 2:
            return str(
                state.trigger_payload.get(parts[1], f"{{{{#{var_path}#}}}}")
            )

        # {node_id}.{field}
        node_id = parts[0]
        field_path = ".".join(parts[1:])

        if node_id not in state.node_outputs:
            return f"{{{{#{var_path}#}}}}"

        node_output = state.node_outputs[node_id]

        # 如果node_output是字典，按路径获取
        if isinstance(node_output, dict):
            value = node_output
            for field in field_path.split("."):
                if isinstance(value, dict) and field in value:
                    value = value[field]
                else:
                    return f"{{{{#{var_path}#}}}}"
            return str(value) if value is not None else ""

        # 如果node_output是标量，直接返回
        return str(node_output) if not field_path else f"{{{{#{var_path}#}}}}"

    def set_value(
        self,
        state: WorkflowState,
        scope: str,
        name: str,
        value: Any,
    ) -> None:
        """设置变量值.

        Args:
            state: 工作流状态
            scope: 变量作用域 (env / run)
            name: 变量名
            value: 变量值
        """
        if scope == "env":
            state.env_vars[name] = value
        elif scope == "run":
            state.run_vars[name] = value
