"""Jinja2 Prompt 渲染引擎.

Phase 6.2: Prompt 模板系统核心 — 安全渲染 + 变量提取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2 import BaseLoader, Environment, UndefinedError, meta
from jinja2.sandbox import SandboxedEnvironment


@dataclass
class RenderedPrompt:
    """渲染后的 Prompt 结果."""

    content: str
    variables_used: list[str]
    missing_variables: list[str]


class PromptEngine:
    """Jinja2 Prompt 渲染引擎.

    使用 SandboxedEnvironment 防止 SSTI（模板注入）攻击。
    禁用所有危险的全局函数和过滤器。
    """

    def __init__(self):
        # 沙箱环境：禁用 __import__、file 操作等危险能力
        self.env = SandboxedEnvironment(
            loader=BaseLoader(),
            autoescape=False,  # Prompt 不是 HTML，不需要转义
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_content: str, variables: dict[str, Any] | None = None) -> RenderedPrompt:
        """渲染模板.

        Args:
            template_content: Jinja2 模板字符串
            variables: 变量字典

        Returns:
            RenderedPrompt: 包含渲染结果、使用的变量、缺失的变量

        Raises:
            ValueError: 模板语法错误或渲染失败
        """
        variables = variables or {}

        try:
            tmpl = self.env.from_string(template_content)
        except Exception as e:
            raise ValueError(f"Template syntax error: {e}")

        # 提取模板中声明的变量
        declared_vars = self.extract_variables(template_content)

        # 检查缺失的变量
        missing = [v for v in declared_vars if v not in variables]

        try:
            content = tmpl.render(**variables)
        except UndefinedError as e:
            # 变量缺失时，Jinja2 默认抛出 UndefinedError
            # 但我们已经提前检测了 missing，这里主要是处理复杂表达式
            raise ValueError(f"Template rendering failed: {e}")
        except Exception as e:
            raise ValueError(f"Template rendering failed: {e}")

        # 记录实际使用的变量（有值的）
        used = [v for v in declared_vars if v in variables]

        return RenderedPrompt(
            content=content,
            variables_used=used,
            missing_variables=missing,
        )

    def extract_variables(self, template_content: str) -> list[str]:
        """提取模板中使用的变量名.

        Args:
            template_content: Jinja2 模板字符串

        Returns:
            变量名列表（去重、排序）
        """
        try:
            ast = self.env.parse(template_content)
        except Exception:
            return []

        undeclared = meta.find_undeclared_variables(ast)
        return sorted(undeclared)

    def validate(self, template_content: str) -> tuple[bool, str]:
        """验证模板语法是否合法.

        Returns:
            (is_valid, error_message)
        """
        try:
            self.env.parse(template_content)
            return True, ""
        except Exception as e:
            return False, str(e)
