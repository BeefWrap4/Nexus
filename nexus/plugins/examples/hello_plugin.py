"""Example plugin: adds a greeting tool."""
from nexus.plugins.base import NexusPlugin, PluginManager
from nexus.plugins.tool_provider import ToolProvider


class GreetingTool(ToolProvider):
    def get_tools(self):
        async def greet(name: str, language: str = "en") -> dict:
            greetings = {"en": "Hello", "zh": "你好", "ja": "こんにちは"}
            greeting = greetings.get(language, "Hello")
            return {"greeting": f"{greeting}, {name}!"}

        return [{
            "name": "greet",
            "description": "Generate a greeting in the specified language",
            "handler": greet,
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Person's name"},
                    "language": {"type": "string", "enum": ["en", "zh", "ja"]},
                },
                "required": ["name"],
            },
            "tool_type": "PYTHON",
        }]


class HelloPlugin(NexusPlugin):
    name = "hello-plugin"
    version = "1.0.0"
    description = "Adds multilingual greeting tool"
    author = "NEXUS Team"

    def setup(self, manager: PluginManager):
        manager.register_tool(GreetingTool())
