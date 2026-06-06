"""File operations tool — read/write files (chrooted to workspace)."""
import os

import aiofiles
from nexus.exceptions import ToolExecutionException
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType

# 修复 (S4-2): 文件操作必须在 workspace root 内。
# 之前无 chroot → LLM 拼出 path='/etc/passwd' 就能读，
# 写出 path='/app/.env' 就能覆盖 SECRET_KEY。
# 通过 settings.TOOL_WORKSPACE_ROOT 配置（默认 /tmp/nexus_workspace）。
# 真实部署时建议挂一个独立 volume，不让工具写到主进程的工作目录。
_DEFAULT_WORKSPACE = "/tmp/nexus_workspace"
_WORKSPACE_ROOT = os.environ.get("NEXUS_TOOL_WORKSPACE_ROOT", _DEFAULT_WORKSPACE)
# 启动时自动建（幂等）
os.makedirs(_WORKSPACE_ROOT, exist_ok=True)


def _validate_path_within_workspace(path: str) -> str:
    """Resolve path 并强制在 workspace root 内.

    Returns:
        解析后的绝对路径。

    Raises:
        ToolExecutionException: path 解析失败或逃出 workspace。
    """
    # 1. realpath 解析 ../ 和 symlink
    try:
        real = os.path.realpath(path)
    except OSError as e:
        raise ToolExecutionException("file_tool", f"invalid path: {e}") from e

    # 2. 必须在 workspace root 内（防止 /etc/passwd、/app/.env 等）
    workspace_real = os.path.realpath(_WORKSPACE_ROOT)
    if not (real == workspace_real or real.startswith(workspace_real + os.sep)):
        raise ToolExecutionException(
            "file_tool",
            f"path escapes workspace: {path!r} (resolved: {real!r}, workspace: {workspace_real!r})",
        )

    return real


def create_file_tools(registry: ToolRegistry) -> None:
    async def read_file(params: dict, context: dict) -> ToolResult:
        """Read content from a file (must be within workspace root)."""
        path = params["path"]
        max_chars = int(params.get("max_chars", 10000))
        # 修复 (S4-2): chroot 校验
        real_path = _validate_path_within_workspace(path)

        # 上限 1MB，防止 LLM 拼 path 把整张硬盘读走
        max_chars = min(max_chars, 1_000_000)

        try:
            async with aiofiles.open(real_path, "r") as f:
                content = await f.read()
                return ToolResult(
                    success=True,
                    data={"content": content[:max_chars], "size": len(content), "path": real_path},
                )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"File not found: {real_path}",
            )

    async def write_file(params: dict, context: dict) -> ToolResult:
        """Write content to a file (must be within workspace root)."""
        path = params["path"]
        content = params["content"]
        # 修复 (S4-2): chroot 校验
        real_path = _validate_path_within_workspace(path)

        # 防止写出巨型文件
        max_write_bytes = 10_000_000  # 10MB
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = bytes(content)
        if len(content_bytes) > max_write_bytes:
            return ToolResult(
                success=False,
                error=f"content too large: {len(content_bytes)} bytes (max {max_write_bytes})",
            )

        # 自动创建父目录（但仅在 workspace 内）
        parent = os.path.dirname(real_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        async with aiofiles.open(real_path, "w") as f:
            await f.write(content)
        return ToolResult(
            success=True,
            data={"written": True, "path": real_path, "size": len(content_bytes)},
        )

    registry.register(Tool(
        name="read_file",
        description=f"Read file content (must be within workspace root {_WORKSPACE_ROOT})",
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
        description=f"Write content to file (must be within workspace root {_WORKSPACE_ROOT})",
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
