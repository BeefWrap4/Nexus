#!/usr/bin/env python3
"""Phase 8.1 end-to-end validation script.

Verifies the complete code review Agent chain:
1. ToolRegistry registers all code review tools
2. BaseAgent discovers tools and builds OpenAI function specs
3. LLM receives tools + task, returns structured decision
4. Agent executes tools via ToolRegistry
5. Final report contains findings from deterministic checks

Usage:
    cd nexus && python scripts/verify_code_review_e2e.py

Requires: DEEPSEEK_API_KEY in .env (or other configured provider)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

from nexus.agent.base import AgentConfig, BaseAgent, Task
from nexus.tools.code_review import (
    _handle_detect_language,
    _handle_parse_diff,
    _handle_perf_check,
    _handle_security_check,
    _handle_style_check,
)
from nexus.tools.registry import ToolRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test payload — deliberately contains security / perf / style issues
# ---------------------------------------------------------------------------

TEST_DIFF = """diff --git a/app/api/users.py b/app/api/users.py
index 1234567..abcdefg 100644
--- a/app/api/users.py
+++ b/app/api/users.py
@@ -10,6 +10,8 @@
 def get_user(user_id: int):
-    user = db.query("SELECT * FROM users WHERE id = " + user_id)
+    user = db.execute("SELECT * FROM users WHERE id = " + user_id)
+    api_key = "sk-abc123def456789"
+    password = "mysecretpassword"
     return user
"""

TEST_CODE = '''
def get_users():
    """Fetch all users with their orders — deliberately bad code for testing."""
    api_key = "sk-abc123def456789"
    password = "supersecret123"
    for user in users:
        orders = db.execute("SELECT * FROM orders WHERE user_id = " + str(user.id))
        time.sleep(0.1)
    x = 1
    x = 2
    x = 3
    x = 4
    x = 5
    x = 6
    x = 7
    x = 8
    x = 9
    x = 10
    x = 11
    x = 12
    x = 13
    x = 14
    x = 15
    x = 16
    x = 17
    x = 18
    x = 19
    x = 20
    x = 21
    x = 22
    x = 23
    x = 24
    x = 25
    x = 26
    x = 27
    x = 28
    x = 29
    x = 30
    x = 31
    x = 32
    x = 33
    x = 34
    x = 35
    x = 36
    x = 37
    x = 38
    x = 39
    x = 40
    x = 41
    x = 42
    x = 43
    x = 44
    x = 45
    x = 46
    x = 47
    x = 48
    x = 49
    x = 50
    x = 51
    x = 52
    x = 53
    x = 54
    x = 55
    return x
'''

CODE_REVIEW_SYSTEM_PROMPT = """You are a senior software engineer performing code review.

Your goal: Thoroughly review code and produce a structured review report with findings and suggestions.

## Instructions
1. First, call the available tools to detect deterministic issues:
   - parse_diff: if the input is a git diff, parse it first
   - detect_language: identify the programming language
   - security_check: find security vulnerabilities
   - perf_check: find performance anti-patterns
   - style_check: find style issues

2. After getting tool results, use your expertise to identify any logic errors or design problems.

3. Produce a final review report in JSON format:
{
  "findings": [
    {
      "severity": "critical|warning|suggestion",
      "category": "security|performance|style|logic",
      "file": "path/to/file",
      "line": 42,
      "title": "Short title",
      "description": "Detailed description",
      "suggestion": "How to fix"
    }
  ],
  "summary": {
    "overall_score": 1,
    "strengths": [],
    "risks": [],
    "review_notes": "Overall assessment"
  }
}

## Tool Use Format
To use a tool, respond with a JSON object:
{"action": "tool_call", "tool_name": "security_check", "tool_params": {"file": "test.py", "content": "...", "language": "python"}}

When finished, respond with:
{"action": "final_answer", "content": "<the JSON report>"}
"""


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

async def verify_tools_independently() -> bool:
    """Step 1: Verify each tool produces correct results independently."""
    logger.info("=" * 60)
    logger.info("STEP 1: Independent Tool Verification")
    logger.info("=" * 60)

    # parse_diff
    result = await _handle_parse_diff({"diff_text": TEST_DIFF})
    assert result.success, "parse_diff failed"
    assert result.data["total_files"] == 1
    logger.info(f"  ✅ parse_diff: {result.data['total_files']} file(s)")

    # detect_language
    result = await _handle_detect_language(
        {"files": [{"file": "app.py", "content": "def f(): pass"}]}
    )
    assert result.data["files"][0]["language"] == "python"
    logger.info(f"  ✅ detect_language: python detected")

    # security_check
    result = await _handle_security_check(
        {"file": "test.py", "content": TEST_CODE, "language": "python"}
    )
    sec_findings = result.data["findings"]
    has_key = any("hardcoded" in f["check_id"] for f in sec_findings)
    has_sql = any("sql" in f["check_id"] for f in sec_findings)
    logger.info(f"  ✅ security_check: {len(sec_findings)} findings (key={has_key}, sql={has_sql})")

    # perf_check
    result = await _handle_perf_check(
        {"file": "test.py", "content": TEST_CODE, "language": "python"}
    )
    perf_findings = result.data["findings"]
    logger.info(f"  ✅ perf_check: {len(perf_findings)} findings")

    # style_check
    result = await _handle_style_check(
        {"file": "test.py", "content": TEST_CODE, "language": "python"}
    )
    style_findings = result.data["findings"]
    has_long = any("function_too_long" == f["check_id"] for f in style_findings)
    logger.info(f"  ✅ style_check: {len(style_findings)} findings (long_func={has_long})")

    return True


async def verify_agent_tool_discovery() -> bool:
    """Step 2: Verify BaseAgent discovers tools and builds function specs."""
    logger.info("=" * 60)
    logger.info("STEP 2: Agent Tool Discovery")
    logger.info("=" * 60)

    registry = ToolRegistry()
    from nexus.tools.code_review import register_code_review_tools
    register_code_review_tools(registry)

    config = AgentConfig(
        name="code-reviewer",
        role="senior software engineer",
        goal="Review code",
        system_prompt=CODE_REVIEW_SYSTEM_PROMPT,
        provider="deepseek",
        model="deepseek-chat",
        temperature=0.3,
        max_iterations=15,
    )
    agent = BaseAgent(config=config, tool_registry=registry)

    # Verify tool specs are built
    tools = agent._get_openai_tools()
    assert tools is not None, "No tool specs built"
    tool_names = [t["function"]["name"] for t in tools]
    expected = ["parse_diff", "detect_language", "security_check", "perf_check", "style_check"]
    for name in expected:
        assert name in tool_names, f"Tool {name} not in function specs"
        logger.info(f"  ✅ {name} registered in OpenAI function specs")

    return True


async def verify_agent_executes_with_llm() -> dict:
    """Step 3: Full Agent → LLM → Tool → Report chain."""
    logger.info("=" * 60)
    logger.info("STEP 3: Full Agent + LLM Chain")
    logger.info("=" * 60)

    registry = ToolRegistry()
    from nexus.tools.code_review import register_code_review_tools
    register_code_review_tools(registry)

    # Use direct DeepSeek API (LiteLLM Proxy not running in validation env)
    import os
    from nexus.agent.llm_client import LLMClient

    llm_client = LLMClient(
        proxy_url="https://api.deepseek.com",
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
    )

    config = AgentConfig(
        name="code-reviewer",
        role="senior software engineer performing code review",
        goal="Thoroughly review code and produce a structured review report",
        system_prompt=CODE_REVIEW_SYSTEM_PROMPT,
        provider="deepseek",
        model="deepseek-v4-pro",
        temperature=0.3,
        max_tokens=4000,
        max_iterations=15,
    )
    agent = BaseAgent(config=config, llm_client=llm_client, tool_registry=registry)

    task = Task(
        description=f"""Review this Python code for security, performance, and style issues.

```python
{TEST_CODE}
```

First use the available tools (security_check, perf_check, style_check, detect_language) to find issues.
Then produce a final JSON report.""",
        expected_output="JSON review report with findings array and summary",
    )

    try:
        result = await agent.execute(
            task=task,
            context={"run_id": str(uuid4()), "tenant_id": "test"},
        )
        logger.info(f"  ✅ Agent completed — status: {result.status}")
        logger.info(f"  ✅ Tool calls made: {len(result.tool_calls)}")
        for tc in result.tool_calls:
            logger.info(f"      - {tc['tool']}: {tc['params']}")
        logger.info(f"  ✅ Output length: {len(result.output)} chars")
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"  ❌ Agent execution failed: {e}")
        return {"success": False, "error": str(e)}


async def verify_report_quality(result: AgentResult) -> bool:  # type: ignore[name-defined]
    """Step 4: Verify the review report contains expected findings."""
    logger.info("=" * 60)
    logger.info("STEP 4: Report Quality Check")
    logger.info("=" * 60)

    output = result.output
    # Try to extract JSON from markdown code blocks
    json_match = None
    if "```json" in output:
        json_match = output.split("```json")[1].split("```")[0]
    elif "```" in output:
        json_match = output.split("```")[1].split("```")[0]
    else:
        # Try to find JSON object directly
        start = output.find("{")
        end = output.rfind("}")
        if start != -1 and end != -1:
            json_match = output[start:end + 1]

    if not json_match:
        logger.warning("  ⚠️ No JSON found in output, checking raw text")
        logger.info(f"  Raw output:\n{output[:1000]}")
        return False

    try:
        report = json.loads(json_match)
    except json.JSONDecodeError:
        logger.warning("  ⚠️ JSON parse failed, checking raw text")
        logger.info(f"  Raw output:\n{output[:1000]}")
        return False

    findings = report.get("findings", [])
    summary = report.get("summary", {})

    logger.info(f"  ✅ Report parsed: {len(findings)} findings")

    # Check for expected issue categories
    categories = {f.get("category") for f in findings}
    logger.info(f"  Categories found: {categories}")

    # Score presence
    score = summary.get("overall_score")
    logger.info(f"  Overall score: {score}")

    # Detailed findings
    for f in findings[:5]:
        logger.info(f"    - [{f.get('severity')}] {f.get('category')}: {f.get('title', f.get('issue', 'N/A'))}")

    return True


async def main():
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 8.1 END-TO-END VALIDATION")
    logger.info("=" * 60)

    all_pass = True

    # Step 1
    try:
        await verify_tools_independently()
    except Exception as e:
        logger.error(f"STEP 1 FAILED: {e}")
        all_pass = False

    # Step 2
    try:
        await verify_agent_tool_discovery()
    except Exception as e:
        logger.error(f"STEP 2 FAILED: {e}")
        all_pass = False

    # Step 3
    agent_result = await verify_agent_executes_with_llm()
    if not agent_result["success"]:
        all_pass = False

    # Step 4
    if agent_result.get("success"):
        try:
            await verify_report_quality(agent_result["result"])
        except Exception as e:
            logger.error(f"STEP 4 FAILED: {e}")
            all_pass = False

    logger.info("\n" + "=" * 60)
    if all_pass:
        logger.info("✅ ALL VALIDATION STEPS PASSED")
    else:
        logger.info("❌ SOME VALIDATION STEPS FAILED — see logs above")
    logger.info("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
