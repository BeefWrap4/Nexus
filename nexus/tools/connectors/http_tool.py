"""HTTP request tool — make GET/POST/PUT/DELETE requests."""
import httpx
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


def create_http_tools(registry: ToolRegistry) -> None:
    async def http_request(params: dict, context: dict) -> ToolResult:
        """Make an HTTP request."""
        method = params.get("method", "GET")
        url = params["url"]
        headers = params.get("headers") or {}
        body = params.get("body") or {}
        timeout = params.get("timeout", 30)

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers)
            elif method.upper() == "POST":
                resp = await client.post(url, json=body, headers=headers)
            elif method.upper() == "PUT":
                resp = await client.put(url, json=body, headers=headers)
            elif method.upper() == "DELETE":
                resp = await client.delete(url, headers=headers)
            else:
                return ToolResult(success=False, error=f"Unsupported method: {method}")
            return ToolResult(
                success=True,
                data={"status": resp.status_code, "body": resp.text[:5000]},
            )

    registry.register(Tool(
        name="http_request",
        description="Make HTTP requests (GET/POST/PUT/DELETE)",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                "url": {"type": "string"},
                "headers": {"type": "object"},
                "body": {"type": "object"},
            },
            "required": ["method", "url"],
        },
        handler=http_request,
    ))
