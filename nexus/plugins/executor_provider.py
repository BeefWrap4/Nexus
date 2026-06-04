"""Executor provider interface for plugins."""
from abc import ABC, abstractmethod


class ExecutorProvider(ABC):
    """执行器提供者 — 插件可通过此接口注册自定义节点执行器."""

    @abstractmethod
    def get_executors(self) -> dict[str, "NodeExecutor"]:
        """返回节点类型 → 执行器的映射."""
