"""Tool workflow node executor."""

from __future__ import annotations

import re
from typing import Any

from nexus.engine.enums import NodeStatus
from nexus.engine.state_manager import WorkflowState
from nexus.engine.workflow_types import Node, NodeExecutor, NodeResult
from nexus.exceptions import ToolNotFoundException
from nexus.tools.registry import ToolRegistry


class ToolNodeExecutor(NodeExecutor):
    """Resolve a registered tool, execute it, and return a node result."""

    def __init__(self, tool_registry: ToolRegistry, event_bus=None):
        self.tool_registry = tool_registry
        self.event_bus = event_bus

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        config = node.config
        tool_name = config.get("tool_name")

        if not tool_name:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "Tool name not specified in node config"},
            )

        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"Tool '{tool_name}' not found"},
            )

        context = {
            "run_id": run_id,
            "node_id": node.id,
            "tenant_id": state.env_vars.get("tenant_id"),
            "user_id": state.env_vars.get("user_id"),
        }

        if tool.config.get("stream"):
            return await self._execute_stream(node, tool, inputs, context, run_id)

        try:
            result = await self.tool_registry.execute(
                tool_name=tool_name,
                params=inputs,
                context=context,
            )

            if result.success:
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output={
                        "data": result.data,
                        "metadata": result.metadata,
                    },
                )

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": result.error},
            )

        except ToolNotFoundException:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": f"Tool '{tool_name}' not found"},
            )
        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )

    async def _execute_stream(
        self,
        node: Node,
        tool,
        inputs: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
    ) -> NodeResult:
        """Consume an SSE-style tool response and publish stream events."""
        import httpx

        config = tool.config
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = dict(config.get("headers", {}))
        timeout = config.get("timeout", 30)

        auth = tool.auth_config
        if auth:
            auth_type = auth.get("type", "")
            if auth_type == "header":
                headers[auth["key"]] = auth["value"]
            elif auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth.get('token', '')}"

        url_vars = re.findall(r"\{(\w+)\}", url)
        body_params = dict(inputs)
        for var in url_vars:
            if var in body_params:
                url = url.replace(f"{{{var}}}", str(body_params.pop(var)))

        schema = tool.schema
        if schema and schema.get("properties"):
            allowed_keys = set(schema["properties"].keys())
            body_params = {k: v for k, v in body_params.items() if k in allowed_keys}

        collected_chunks = []

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request_kwargs = {"headers": headers}
                if method == "POST":
                    request_kwargs["json"] = body_params
                elif method == "GET":
                    request_kwargs["params"] = body_params

                async with client.stream(method, url, **request_kwargs) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk = line[6:].strip()
                            if chunk == "[DONE]":
                                break
                            collected_chunks.append(chunk)

                            if self.event_bus:
                                await self.event_bus.publish({
                                    "type": "stream_chunk",
                                    "run_id": run_id,
                                    "node_id": node.id,
                                    "tool_name": tool.name,
                                    "chunk": chunk,
                                    "index": len(collected_chunks) - 1,
                                })

            full_text = "".join(collected_chunks)

            if self.event_bus:
                await self.event_bus.publish({
                    "type": "stream_end",
                    "run_id": run_id,
                    "node_id": node.id,
                    "tool_name": tool.name,
                    "total_chunks": len(collected_chunks),
                })

            return NodeResult(
                node_id=node.id,
                status=NodeStatus.SUCCEEDED,
                output={
                    "data": {"response": full_text, "streamed": True},
                    "metadata": {"chunks": len(collected_chunks), "tool": tool.name},
                },
            )

        except Exception as e:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"type": type(e).__name__, "message": str(e)},
            )
