"""Plugin base class and registry."""
import logging
from typing import Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class NexusPlugin(ABC):
    """第三方插件基类.

    Example:
        class MyPlugin(NexusPlugin):
            name = "my-plugin"
            version = "1.0.0"

            def setup(self, manager: "PluginManager"):
                manager.register_tool(self.tool_provider)
    """
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    @abstractmethod
    def setup(self, manager: "PluginManager") -> None:
        """插件初始化 — 注册工具、执行器、钩子."""

    def teardown(self) -> None:
        """插件卸载."""
        pass


class PluginManager:
    """插件管理器 — 单例，管理所有已加载插件."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._plugins = {}
            cls._instance._hook_handlers = {}
            cls._instance._tool_providers = []
            cls._instance._executor_providers = []
        return cls._instance

    def load_plugin(self, plugin: NexusPlugin) -> None:
        """加载插件."""
        if plugin.name in self._plugins:
            logger.warning(f"Plugin '{plugin.name}' already loaded, skipping")
            return
        plugin.setup(self)
        self._plugins[plugin.name] = plugin
        logger.info(f"Plugin loaded: {plugin.name} v{plugin.version}")

    def unload_plugin(self, name: str) -> None:
        """卸载插件."""
        if name in self._plugins:
            self._plugins[name].teardown()
            del self._plugins[name]

    def list_plugins(self) -> list[dict[str, str]]:
        """列出所有已加载插件."""
        return [{"name": p.name, "version": p.version, "description": p.description}
                for p in self._plugins.values()]

    def register_tool(self, provider: "ToolProvider") -> None:
        """注册工具提供者."""
        self._tool_providers.append(provider)

    def register_executor(self, provider: "ExecutorProvider") -> None:
        """注册执行器提供者."""
        self._executor_providers.append(provider)

    def register_hook(self, hook_type: str, handler: callable) -> None:
        """注册生命周期钩子."""
        if hook_type not in self._hook_handlers:
            self._hook_handlers[hook_type] = []
        self._hook_handlers[hook_type].append(handler)

    async def trigger_hook(self, hook_type: str, **kwargs) -> list[Any]:
        """触发钩子."""
        handlers = self._hook_handlers.get(hook_type, [])
        results = []
        for handler in handlers:
            try:
                result = await handler(**kwargs) if hasattr(handler, '__call__') else handler(**kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Hook {hook_type} failed: {e}")
        return results
