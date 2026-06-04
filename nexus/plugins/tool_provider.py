"""Tool provider interface for plugins."""
from abc import ABC, abstractmethod
from typing import Any


class ToolProvider(ABC):
    """工具提供者 — 插件通过此接口注册工具."""

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """返回工具定义列表.

        每个工具定义:
        {
            "name": str,
            "description": str,
            "handler": callable,
            "schema": dict,  # JSON Schema
            "tool_type": str,  # PYTHON/HTTP/SQL/MCP
        }
        """
