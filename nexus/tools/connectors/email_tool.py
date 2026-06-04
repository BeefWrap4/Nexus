"""Email tool — send emails via SMTP (simulated for testing)."""
from nexus.tools.registry import ToolRegistry, Tool, ToolResult, ToolType


def create_email_tool(registry: ToolRegistry) -> None:
    async def send_email(params: dict, context: dict) -> ToolResult:
        """Send an email (uses configured SMTP server)."""
        to = params["to"]
        subject = params["subject"]
        body = params["body"]
        # Production should use aiosmtplib or smtplib
        return ToolResult(
            success=True,
            data={
                "sent": True,
                "to": to,
                "subject": subject,
                "message": f"Email to {to} with subject '{subject}' would be sent",
            },
        )

    registry.register(Tool(
        name="send_email",
        description="Send email via SMTP",
        type=ToolType.PYTHON,
        schema={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        handler=send_email,
    ))
