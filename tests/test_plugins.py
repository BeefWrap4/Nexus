import pytest
from nexus.plugins.base import NexusPlugin, PluginManager
from nexus.plugins.hooks import Hook, HookType
from nexus.plugins.tool_provider import ToolProvider
from nexus.plugins.examples.hello_plugin import HelloPlugin, GreetingTool


class TestPluginManager:
    def test_singleton(self):
        m1 = PluginManager()
        m2 = PluginManager()
        assert m1 is m2

    def test_load_plugin(self):
        mgr = PluginManager()
        plugin = HelloPlugin()
        mgr.load_plugin(plugin)
        assert "hello-plugin" in [p["name"] for p in mgr.list_plugins()]

    def test_duplicate_load_skipped(self):
        mgr = PluginManager()
        mgr.load_plugin(HelloPlugin())
        mgr.load_plugin(HelloPlugin())  # should not crash
        assert len(mgr.list_plugins()) == 1

    def test_unload_plugin(self):
        mgr = PluginManager()
        mgr.load_plugin(HelloPlugin())
        mgr.unload_plugin("hello-plugin")
        assert mgr.list_plugins() == []


class TestGreetingTool:
    @pytest.mark.asyncio
    async def test_greet_en(self):
        tool = GreetingTool()
        handler = tool.get_tools()[0]["handler"]
        result = await handler(name="World")
        assert result["greeting"] == "Hello, World!"

    @pytest.mark.asyncio
    async def test_greet_zh(self):
        tool = GreetingTool()
        handler = tool.get_tools()[0]["handler"]
        result = await handler(name="世界", language="zh")
        assert "你好" in result["greeting"]


class TestHooks:
    @pytest.mark.asyncio
    async def test_register_and_trigger_hook(self):
        mgr = PluginManager()
        called = []

        async def my_hook(**kwargs):
            called.append(kwargs.get("msg"))
            return "ok"

        mgr.register_hook(HookType.WORKFLOW_PRE_EXECUTE, my_hook)
        results = await mgr.trigger_hook(HookType.WORKFLOW_PRE_EXECUTE, msg="hello")
        assert called == ["hello"]
        assert results == ["ok"]

    @pytest.mark.asyncio
    async def test_hook_exception_handled(self):
        mgr = PluginManager()

        async def bad_hook(**kwargs):
            raise ValueError("boom")

        mgr.register_hook(HookType.LLM_PRE_CALL, bad_hook)
        results = await mgr.trigger_hook(HookType.LLM_PRE_CALL)  # should not crash
        assert results == []
