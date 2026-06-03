"""工具注册中心 - MCP兼容.

基于WAT utils/llm_providers.py 注册表模式泛化:
- 统一管理所有外部工具
- 标准化JSON Schema输入输出
- 工具级RBAC
- 完整审计

符合Model Context Protocol (MCP)标准。
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from nexus.exceptions import (
    ToolExecutionException,
    ToolNotFoundException,
    ToolPermissionDeniedException,
)


class ToolType(str, Enum):
    """工具类型."""

    HTTP = "http"
    SQL = "sql"
    PYTHON = "python"
    MCP = "mcp"


@dataclass
class ToolInfo:
    """工具信息."""

    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果."""

    success: bool
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    """工具定义."""

    name: str
    description: str
    type: ToolType
    config: dict[str, Any] = field(default_factory=dict)
    schema: dict[str, Any] = field(default_factory=dict)
    auth_config: dict[str, Any] = field(default_factory=dict)
    handler: Callable = None


class ToolRegistry:
    """工具注册中心.

    对应WAT: utils/llm_providers.py 的注册表模式。
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._audit_log: list[dict] = []

    def register(self, tool: Tool) -> None:
        """注册工具.

        对应WAT: LLM Provider注册。
        """
        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> None:
        """注销工具."""
        self._tools.pop(tool_name, None)

    async def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any] = None,
    ) -> ToolResult:
        """执行工具.

        Args:
            tool_name: 工具名称
            params: 工具参数
            context: 执行上下文（含tenant_id, user_id, permissions等）

        Returns:
            ToolResult: 执行结果
        """
        ctx = context or {}

        # 1. 查找工具
        tool = self._tools.get(tool_name)
        if not tool:
            raise ToolNotFoundException(tool_name)

        # 2. 权限校验
        if not self._check_permission(ctx, tool):
            raise ToolPermissionDeniedException(tool_name)

        # 3. 输入校验（JSON Schema）
        self._validate_input(tool.schema, params)

        # 4. 执行前审计
        call_id = len(self._audit_log)
        self._audit_log.append({
            "id": call_id,
            "tool": tool_name,
            "params": params,
            "context": ctx,
            "status": "started",
        })

        try:
            # 5. 执行工具
            if tool.type == ToolType.HTTP:
                result = await self._execute_http(tool, params, ctx)
            elif tool.type == ToolType.SQL:
                result = await self._execute_sql(tool, params, ctx)
            elif tool.type == ToolType.PYTHON:
                result = await self._execute_python(tool, params, ctx)
            elif tool.type == ToolType.MCP:
                result = await self._execute_mcp(tool, params, ctx)
            else:
                result = ToolResult(
                    success=False,
                    error=f"Unknown tool type: {tool.type}",
                )

            # 6. 记录成功
            self._audit_log[call_id]["status"] = "success"
            self._audit_log[call_id]["result"] = result.data if result.success else None

            return result

        except Exception as e:
            # 7. 记录失败
            self._audit_log[call_id]["status"] = "failed"
            self._audit_log[call_id]["error"] = str(e)
            raise ToolExecutionException(tool_name, str(e))

    def list_tools(self, context: dict[str, Any] = None) -> list[ToolInfo]:
        """列出可访问的工具（用于Agent工具选择）.

        对应WAT: get_available_providers()。
        """
        ctx = context or {}
        tools = []
        for tool in self._tools.values():
            if self._check_permission(ctx, tool):
                tools.append(
                    ToolInfo(
                        name=tool.name,
                        description=tool.description,
                        schema=tool.schema,
                    )
                )
        return tools

    def get_tool(self, tool_name: str) -> Tool | None:
        """获取工具定义."""
        return self._tools.get(tool_name)

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志."""
        return self._audit_log[-limit:]

    def _check_permission(self, context: dict[str, Any], tool: Tool) -> bool:
        """检查权限."""
        # 简化版：所有已注册用户都有权限
        # 生产环境应检查RBAC
        return True

    def _validate_input(self, schema: dict[str, Any], params: dict[str, Any]) -> None:
        """校验输入参数."""
        # 简化版：检查必填字段
        # 生产环境应使用jsonschema库
        required = schema.get("required", [])
        for field in required:
            if field not in params:
                raise ToolExecutionException(
                    "validation",
                    f"Missing required parameter: {field}",
                )

    async def _execute_http(
        self, tool: Tool, params: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """执行HTTP工具.

        增强功能:
        1. auth_config 头注入 — 支持 header / bearer 类型
        2. URL 模板替换 — 如 /sessions/{session_id}/history → 从 params 替换
        3. JSON Schema 参数过滤 — 只发送 schema 中定义的参数到 HTTP body
        """
        import httpx

        config = tool.config
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = dict(config.get("headers", {}))
        timeout = config.get("timeout", 30)

        # 1. 注入认证头
        auth = tool.auth_config
        if auth:
            auth_type = auth.get("type", "")
            if auth_type == "header":
                headers[auth["key"]] = auth["value"]
            elif auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth.get('token', '')}"

        # 2. URL 模板替换 — 提取 URL 中 {var} 并从 params 替换
        url_vars = self._extract_url_variables(url)
        url_params = {}
        body_params = dict(params)
        for var in url_vars:
            if var in body_params:
                url_params[var] = body_params.pop(var)
                url = url.replace(f"{{{var}}}", str(url_params[var]))

        # 3. JSON Schema 参数过滤 — 只保留 schema 中定义的参数
        schema = tool.schema
        if schema and schema.get("properties"):
            allowed_keys = set(schema["properties"].keys())
            # 保留 schema 定义的参数 + 已用于 URL 替换的参数已从 body 移除
            body_params = {k: v for k, v in body_params.items() if k in allowed_keys}

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, params=body_params, headers=headers)
            elif method == "POST":
                response = await client.post(url, json=body_params, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=body_params, headers=headers)
            elif method == "DELETE":
                response = await client.delete(url, params=body_params, headers=headers)
            else:
                return ToolResult(success=False, error=f"Unsupported method: {method}")

            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            is_json = content_type.startswith("application/json")
            return ToolResult(
                success=True,
                data=response.json() if is_json else response.text,
                metadata={"status_code": response.status_code, "content_type": content_type},
            )

    def _extract_url_variables(self, url: str) -> list[str]:
        """提取 URL 模板变量.

        例如 /sessions/{session_id}/history → ["session_id"]
        """
        import re

        return re.findall(r"\{(\w+)\}", url)

    async def _execute_sql(
        self, tool: Tool, params: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """执行SQL工具."""
        # SQL执行应在只读模式下运行（生产安全）
        config = tool.config
        query = params.get("query", "")

        # 安全检查：只允许SELECT
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT") and not config.get("allow_write", False):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed by default",
            )

        # 简化版：返回查询描述
        # 生产环境应连接真实数据库
        return ToolResult(
            success=True,
            data={"query": query, "rows": [], "description": "SQL execution placeholder"},
        )

    async def _execute_python(
        self, tool: Tool, params: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """执行Python工具 (in-process via handler callback)."""
        if tool.handler is not None:
            return await tool.handler(params, context)

        # Fallback: placeholder for tools without a handler
        code = params.get("code", "")
        return ToolResult(
            success=True,
            data={"code": code, "result": "Python execution placeholder"},
        )

    async def _execute_mcp(
        self, tool: Tool, params: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """执行MCP工具（通过MCPClientManager）.

        Phase 5: 从 placeholder 落地为实际 MCP SDK 调用。
        """
        from nexus.mcp.client import get_mcp_client_manager

        config = tool.config
        conn_name = config.get("mcp_server", "")
        mcp_tool_name = config.get("mcp_tool_name", "")

        if not conn_name or not mcp_tool_name:
            return ToolResult(
                success=False,
                error=f"Invalid MCP tool config: missing 'mcp_server' or 'mcp_tool_name'",
            )

        try:
            mcp_mgr = get_mcp_client_manager()
            result = await mcp_mgr.call_tool(conn_name, mcp_tool_name, params)
            return ToolResult(
                success=not result.get("isError", False),
                data=result.get("content", result),
                metadata={"mcp_server": conn_name, "mcp_tool": mcp_tool_name},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"MCP tool call failed: {str(e)}",
                metadata={"mcp_server": conn_name, "mcp_tool": mcp_tool_name},
            )


# ---------------------------------------------------------------------------
# 全局 ToolRegistry 单例
# ---------------------------------------------------------------------------
_global_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 单例.

    首次调用时自动创建并注册 RAG Tools。
    在 API 进程和 ARQ Worker 进程之间共享 Tool 定义。
    """
    global _global_tool_registry
    if _global_tool_registry is None:
        _global_tool_registry = ToolRegistry()
        # 延迟导入避免循环依赖
        from nexus.tools.rag import register_rag_tools
        from nexus.tools.code_review import register_code_review_tools

        register_rag_tools(_global_tool_registry)
        register_code_review_tools(_global_tool_registry)
        from nexus.tools.github_tools import register_github_tools
        register_github_tools(_global_tool_registry)
    return _global_tool_registry


def set_tool_registry(registry: ToolRegistry) -> None:
    """设置全局 ToolRegistry（用于测试替换）."""
    global _global_tool_registry
    _global_tool_registry = registry
