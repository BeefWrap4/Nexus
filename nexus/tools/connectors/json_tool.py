"""JSON tool — parse, query, and transform JSON data."""
import json
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


def create_json_tools(registry: ToolRegistry) -> None:
    async def json_query(params: dict, context: dict) -> ToolResult:
        """Query JSON data using dot-notation path."""
        data = params["data"]
        path = params.get("path", "")
        try:
            obj = json.loads(data) if isinstance(data, str) else data
            if not path:
                return ToolResult(success=True, data={"result": obj})
            parts = path.split(".")
            current = obj
            for p in parts:
                if isinstance(current, dict):
                    current = current.get(p)
                elif isinstance(current, list) and p.isdigit():
                    current = current[int(p)]
                else:
                    return ToolResult(
                        success=False,
                        error=f"Cannot access '{p}' in {type(current).__name__}",
                    )
            return ToolResult(success=True, data={"result": current})
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

    async def json_format(params: dict, context: dict) -> ToolResult:
        """Pretty-print JSON data."""
        data = params["data"]
        indent = params.get("indent", 2)
        try:
            obj = json.loads(data) if isinstance(data, str) else data
            return ToolResult(
                success=True,
                data={"formatted": json.dumps(obj, indent=indent, ensure_ascii=False)},
            )
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

    registry.register(Tool(
        name="json_query",
        description="Query JSON with dot-notation path",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "data": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["data"],
        },
        handler=json_query,
    ))

    registry.register(Tool(
        name="json_format",
        description="Pretty-print JSON data",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "data": {"type": "string"},
                "indent": {"type": "integer"},
            },
            "required": ["data"],
        },
        handler=json_format,
    ))
