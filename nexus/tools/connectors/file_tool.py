"""File operations tool — read/write files."""
import aiofiles
import os
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


def create_file_tools(registry: ToolRegistry) -> None:
    async def read_file(params: dict, context: dict) -> ToolResult:
        """Read content from a file."""
        path = params["path"]
        max_chars = params.get("max_chars", 10000)
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
                return ToolResult(
                    success=True,
                    data={"content": content[:max_chars], "size": len(content)},
                )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"File not found: {path}",
            )

    async def write_file(params: dict, context: dict) -> ToolResult:
        """Write content to a file."""
        path = params["path"]
        content = params["content"]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        async with aiofiles.open(path, "w") as f:
            await f.write(content)
        return ToolResult(
            success=True,
            data={"written": True, "path": path, "size": len(content)},
        )

    registry.register(Tool(
        name="read_file",
        description="Read file content",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
        handler=read_file,
    ))

    registry.register(Tool(
        name="write_file",
        description="Write content to file",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    ))
