"""Webhook tool — call external webhooks."""
import httpx
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


def create_webhook_tool(registry: ToolRegistry) -> None:
    async def call_webhook(params: dict, context: dict) -> ToolResult:
        """Call a webhook URL with JSON payload."""
        url = params["url"]
        payload = params.get("payload") or {}
        secret = params.get("secret")

        headers = {}
        if secret:
            import hmac
            import hashlib

            headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
                secret.encode(), str(payload).encode(), hashlib.sha256
            ).hexdigest()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            return ToolResult(
                success=True,
                data={"status": resp.status_code, "ok": resp.is_success},
            )

    registry.register(Tool(
        name="call_webhook",
        description="Call an external webhook URL",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "payload": {"type": "object"},
                "secret": {"type": "string"},
            },
            "required": ["url"],
        },
        handler=call_webhook,
    ))
