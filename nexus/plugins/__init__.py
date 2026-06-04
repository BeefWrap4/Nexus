"""NEXUS Plugin SDK — Extend the platform with custom tools, executors, and hooks."""
from nexus.plugins.base import NexusPlugin, PluginManager
from nexus.plugins.hooks import Hook, HookType
from nexus.plugins.tool_provider import ToolProvider
from nexus.plugins.executor_provider import ExecutorProvider

__all__ = ["NexusPlugin", "PluginManager", "Hook", "HookType", "ToolProvider", "ExecutorProvider"]
