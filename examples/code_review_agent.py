#!/usr/bin/env python3
"""Code Review Agent example — interactive review workbench.

Demonstrates complete NEXUS code review Agent usage:
1. Register code review tools
2. Define DAG workflow (start → review → end)
3. Execute via WorkflowEngine
4. Output structured review report

Usage: python examples/code_review_agent.py
"""

from __future__ import annotations

import asyncio

from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeType
from nexus.engine.event_bus import EventBus
from nexus.engine.node_executors import (
    AgentNodeExecutor,
    EndNodeExecutor,
    StartNodeExecutor,
    ToolNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import Edge, Node, WorkflowDefinition, WorkflowEngine
from nexus.tools.registry import get_tool_registry


async def main():
    # 1. Register tools
    registry = get_tool_registry()

    # 2. Define workflow
    wf = WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START),
            Node(
                id="review",
                type=NodeType.AGENT,
                config={
                    "agent_name": "code-reviewer",
                    "agent_role": "senior software engineer performing code review",
                    "agent_goal": "Thoroughly review code and produce a structured review report with findings and suggestions",
                    "task_description": (
                        "Review the following code changes. Use parse_diff to structure the diff, "
                        "detect_language to identify the language, security_check, perf_check, and "
                        "style_check to find deterministic issues, and your own expertise for logic/design review.\n"
                        "Produce a complete review report in the specified JSON format."
                    ),
                    "template_variables": {
                        "role": "senior software engineer",
                        "language": "python",
                        "focus_areas": "security, performance, maintainability, correctness",
                        "strictness": "normal",
                    },
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                },
            ),
            Node(
                id="end",
                type=NodeType.END,
                config={"output": {"mappings": {"review_report": "{{#review.output#}}"}}},
            ),
        ],
        edges=[
            Edge(source="start", target="review"),
            Edge(source="review", target="end"),
        ],
    )

    # 3. Create engine
    state_manager = StateManager()
    event_bus = EventBus()
    engine = WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=CheckpointManager(),
        variable_pool=VariablePool(),
        router_engine=RouterEngine(),
    )

    # 4. Register executors
    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor(tool_registry=registry))
    engine.register_executor(
        NodeType.TOOL, ToolNodeExecutor(tool_registry=registry, event_bus=event_bus)
    )

    # 5. Execute with example diff containing security issues
    diff_example = """diff --git a/app/api/users.py b/app/api/users.py
index 1234567..abcdefg 100644
--- a/app/api/users.py
+++ b/app/api/users.py
@@ -10,6 +10,8 @@
 def get_user(user_id: int):
-    user = db.query("SELECT * FROM users WHERE id = " + user_id)
+    user = db.query("SELECT * FROM users WHERE id = " + user_id)
+    api_key = "sk-abc123def456789"
+    password = "mysecretpassword"
     return user
"""

    print("Executing code review...")
    result = await engine.execute(
        workflow_def=wf,
        trigger_payload={"diff_content": diff_example},
        run_id="example-code-review",
    )

    print(f"Status: {result.status.value}")
    print(f"Duration: {result.duration_ms}ms")
    print(f"Report:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
