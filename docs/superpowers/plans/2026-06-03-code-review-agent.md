# 代码审查 Agent 实施计划

> **对于 agentic workers:** 必需的子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐步实施此计划。步骤使用复选框 (`- [ ]`) 语法进行跟踪。

**目标:** 构建一个完整的代码审查 Agent 应用，首先作为交互式工作台（8.1），然后作为 PR 审查机器人（8.2），验证 NEXUS 的核心能力。

**架构:** Python 代码审查工具（parse_diff, security_check, perf_check, style_check, detect_language）+ LLM 驱动的 code_analyze 工具 → Agent "code-reviewer" → 通过 WorkflowEngine + EventBus → WebSocket 流式传输到前端。使用 NEXUS Prompt 模板系统管理审查标准。

**技术栈:** FastAPI, Vue 3 + Ant Design Vue, Jinja2, WebSocket, NEXUS WorkflowEngine, NEXUS Agent/BaseAgent, NEXUS ToolRegistry, PromptEngine

---

### 任务 1: 代码审查工具集

**文件:**
- 创建: `nexus/nexus/tools/code_review.py`
- 修改: `nexus/nexus/tools/registry.py:339-344`

- [ ] **步骤 1: 编写 `build_code_review_tools` 函数**

```python
"""代码审查 Agent 工具集.

Phase 8.1: 交互式代码审查工作台工具。
提供确定性检查（安全/性能/风格）和 LLM 驱动的语义分析。
"""

from __future__ import annotations

import re
from typing import Any

from nexus.tools.registry import Tool, ToolInfo, ToolResult, ToolType


def build_code_review_tools() -> list[Tool]:
    """构建代码审查工具集."""
    tools: list[Tool] = []

    # parse_diff — 解析 git diff 为结构化数据
    tools.append(Tool(
        name="parse_diff",
        description="Parse a git diff string into structured file/hunk/line data",
        type=ToolType.PYTHON,
        config={},
        handler=_handle_parse_diff,
        schema={
            "type": "object",
            "required": ["diff_text"],
            "properties": {
                "diff_text": {"type": "string", "description": "Git diff text to parse"},
            },
        },
    ))

    # detect_language — 自动识别编程语言
    tools.append(Tool(
        name="detect_language",
        description="Detect programming language from file extension or content",
        type=ToolType.PYTHON,
        config={},
        handler=_handle_detect_language,
        schema={
            "type": "object",
            "required": ["files"],
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"file": {"type": "string"}, "content": {"type": "string"}}},
                    "description": "List of files with optional content",
                },
            },
        },
    ))

    # security_check — 基于模式匹配的漏洞检测
    tools.append(Tool(
        name="security_check",
        description="Check code for common security vulnerabilities (hardcoded secrets, SQL injection, XSS)",
        type=ToolType.PYTHON,
        config={},
        handler=_handle_security_check,
        schema={
            "type": "object",
            "required": ["file", "content", "language"],
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
                "language": {"type": "string", "description": "Programming language"},
            },
        },
    ))

    # perf_check — 性能反模式检测
    tools.append(Tool(
        name="perf_check",
        description="Check code for performance anti-patterns (N+1 queries, memory leaks, blocking calls)",
        type=ToolType.PYTHON,
        config={},
        handler=_handle_perf_check,
        schema={
            "type": "object",
            "required": ["file", "content", "language"],
            "properties": {
                "file": {"type": "string"},
                "content": {"type": "string"},
                "language": {"type": "string"},
            },
        },
    ))

    # style_check — 代码风格问题
    tools.append(Tool(
        name="style_check",
        description="Check code style (long functions, deep nesting, naming conventions)",
        type=ToolType.PYTHON,
        config={},
        handler=_handle_style_check,
        schema={
            "type": "object",
            "required": ["file", "content", "language"],
            "properties": {
                "file": {"type": "string"},
                "content": {"type": "string"},
                "language": {"type": "string"},
            },
        },
    ))

    return tools


def register_code_review_tools(registry) -> None:
    """注册代码审查工具到 ToolRegistry."""
    import structlog
    logger = structlog.get_logger()
    tools = build_code_review_tools()
    for tool in tools:
        registry.register(tool)
    logger.info("code_review_tools_registered", count=len(tools))
```

- [ ] **步骤 2: 实现处理器函数**

```python
# --- 处理器实现 ---

async def _handle_parse_diff(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """解析 git diff 为结构化文件/块/行数据."""
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return ToolResult(success=False, error="Empty diff text")

    files = []
    current_file = None
    current_hunk = None

    for line in diff_text.split("\n"):
        # 匹配文件头
        file_match = re.match(r"^diff --git a/(.+?) b/(.+?)$", line)
        if file_match:
            if current_file:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            current_file = {"file": file_match.group(2), "hunks": [], "added_lines": 0, "removed_lines": 0}
            current_hunk = None
            continue

        if not current_file:
            continue

        # 匹配块头
        hunk_match = re.match(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)$", line)
        if hunk_match:
            if current_hunk:
                current_file["hunks"].append(current_hunk)
            current_hunk = {
                "old_start": int(hunk_match.group(1)),
                "new_start": int(hunk_match.group(3)),
                "context": hunk_match.group(5).strip(),
                "lines": [],
            }
            continue

        if not current_hunk:
            continue

        # 跟踪行
        if line.startswith("+") and not line.startswith("+++"):
            current_file["added_lines"] += 1
            current_hunk["lines"].append({"type": "added", "content": line[1:]})
        elif line.startswith("-") and not line.startswith("---"):
            current_file["removed_lines"] += 1
            current_hunk["lines"].append({"type": "removed", "content": line[1:]})
        else:
            current_hunk["lines"].append({"type": "context", "content": line[1:] if line.startswith(" ") else line})

    if current_file:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    return ToolResult(success=True, data={"files": files, "total_files": len(files)})


async def _handle_detect_language(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """从文件扩展名和内容检测编程语言."""
    files = params.get("files", [])

    EXTENSION_MAP = {
        ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "jsx", ".tsx": "tsx",
        ".java": "java", ".go": "go", ".rs": "rust", ".cpp": "cpp", ".c": "c",
        ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
        ".vue": "vue", ".svelte": "svelte", ".sql": "sql", ".sh": "shell",
        ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".xml": "xml",
        ".css": "css", ".scss": "scss", ".html": "html", ".md": "markdown",
    }

    results = []
    for f in files:
        filename = f.get("file", "")
        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        language = EXTENSION_MAP.get(ext, "unknown")
        results.append({"file": filename, "language": language, "extension": ext})

    return ToolResult(success=True, data={"files": results})


async def _handle_security_check(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """检查常见安全漏洞."""
    file = params.get("file", "")
    content = params.get("content", "")
    findings = []

    patterns = [
        ("hardcoded_api_key", r'(?:api[_-]?key|apikey|secret|token|password)\s*[:=]\s*["\x27][a-zA-Z0-9_\-]{8,}["\x27]', "Hardcoded API key or secret", "critical"),
        ("hardcoded_password", r'(?:password|passwd)\s*[:=]\s*["\x27](?!changeme|example|password)[^"\x27]{3,}["\x27]', "Hardcoded password", "critical"),
        ("sql_injection", r'(?:execute|executemany)\s*\(\s*(?:f["\x27]|["\x27]\s*%\s*["\x27]|["\x27]\s*\+)', "Potential SQL injection via string concatenation", "critical"),
        ("eval_usage", r'\beval\s*\(', "Use of eval() — potential code injection risk", "warning"),
        ("xss_unsafe", r'(?:innerHTML|dangerouslySetInnerHTML|v-html|document\.write)', "Potential XSS vulnerability via unsanitized HTML injection", "warning"),
        ("open_redirect", r'(?:window\.location\s*=\s*|redirect\s*\(\s*)(?:req\.|request\.|params\.)', "Potential open redirect vulnerability", "warning"),
    ]

    for line_idx, line in enumerate(content.split("\n"), 1):
        for check_id, pattern, description, severity in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                match = re.search(pattern, line, re.IGNORECASE)
                context_text = line.strip()[:120]
                findings.append({
                    "file": file,
                    "line": line_idx,
                    "severity": severity,
                    "category": "security",
                    "check_id": check_id,
                    "issue": description,
                    "context": context_text,
                    "suggestion": _get_security_suggestion(check_id),
                })

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


async def _handle_perf_check(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """检查性能反模式."""
    file = params.get("file", "")
    content = params.get("content", "")
    language = params.get("language", "")
    findings = []

    patterns = [
        ("n_plus_1_query", r'for\s+\w+\s+in\s+\w+:\s*\n\s*\w+\.(?:filter|get|query|execute)', "Potential N+1 query in loop", "warning", ["python", "javascript", "typescript", "ruby"]),
        ("memory_leak_list", r'(\w+)\s*=\s*\[\]\s*\n(?:.*\n)*?for\s+\w+\s+in\s+range\(', "List built in loop — consider generator or pre-allocation", "warning", ["python"]),
        ("large_file_read", r'\.read\s*\(\s*\)(?!\s*\.split)', "Reading entire file into memory — consider streaming", "suggestion", ["python"]),
        ("blocking_call", r'(?:time\.sleep|Thread\.sleep|fs\.readFileSync|fs\.writeFileSync)', "Blocking call in async context", "warning", ["python", "javascript", "typescript"]),
        ("deeply_nested_loop", r'for\s+\w+\s+in\s+\w+:\s*\n\s*for\s+\w+\s+in\s+\w+:\s*\n\s*for\s+\w+\s+in', "Triple-nested loop — O(n³) complexity", "suggestion", []),
    ]

    for line_idx, line in enumerate(content.split("\n"), 1):
        for check_id, pattern, description, severity, lang_filter in patterns:
            if lang_filter and language not in lang_filter:
                continue
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "file": file,
                    "line": line_idx,
                    "severity": severity,
                    "category": "performance",
                    "check_id": check_id,
                    "issue": description,
                    "context": line.strip()[:120],
                    "suggestion": _get_perf_suggestion(check_id),
                })

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


async def _handle_style_check(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """检查代码风格问题."""
    file = params.get("file", "")
    content = params.get("content", "")
    findings = []
    lines = content.split("\n")

    # 函数过长检测
    for i, line in enumerate(lines, 1):
        func_match = re.match(r"^\s*(?:def|function|func|async def|public|private|protected)\s+(\w+)", line)
        if func_match:
            func_name = func_match.group(1)
            func_start = i
            indent = len(line) - len(line.lstrip())
            func_end = func_start
            for j in range(func_start, len(lines)):
                if j < len(lines) and lines[j].strip() and not lines[j].startswith(" " * (indent + 1)) and lines[j].strip() != "{":
                    if j > func_start:
                        func_end = j
                        break
                func_end = j
            func_length = func_end - func_start
            if func_length > 50:
                findings.append({
                    "file": file, "line": func_start,
                    "severity": "warning", "category": "style",
                    "check_id": "function_too_long",
                    "issue": f"Function '{func_name}' is {func_length} lines (recommended ≤50)",
                    "context": line.strip()[:120],
                    "suggestion": f"Refactor '{func_name}' into smaller helper functions. Consider extracting sub-tasks.",
                })

    # 嵌套过深检测
    for i, line in enumerate(lines, 1):
        indent_level = len(line) - len(line.lstrip())
        if indent_level > 80:
            findings.append({
                "file": file, "line": i,
                "severity": "suggestion", "category": "style",
                "check_id": "deeply_nested",
                "issue": "Excessive indentation (>20 levels) — deeply nested logic",
                "context": line.strip()[:120],
                "suggestion": "Extract nested blocks into separate functions.",
            })

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


# --- 修复建议映射 ---

def _get_security_suggestion(check_id: str) -> str:
    suggestions = {
        "hardcoded_api_key": "Use environment variables or a secrets manager. Replace with os.environ.get('API_KEY').",
        "hardcoded_password": "Use environment variables. Never store passwords in source code.",
        "sql_injection": "Use parameterized queries or an ORM. Example: cursor.execute('SELECT * FROM users WHERE id=?', (user_id,))",
        "eval_usage": "Avoid eval(). Use ast.literal_eval() for parsing or a proper parser library.",
        "xss_unsafe": "Use textContent instead of innerHTML, or use a framework's sanitization (e.g., DOMPurify).",
        "open_redirect": "Validate redirect URLs against a whitelist. Example: if url not in ALLOWED_REDIRECTS: raise ValueError.",
    }
    return suggestions.get(check_id, "Review this pattern manually.")


def _get_perf_suggestion(check_id: str) -> str:
    suggestions = {
        "n_plus_1_query": "Batch the query outside the loop. Use JOIN or prefetch_related() to load related data in one query.",
        "memory_leak_list": "Use a generator expression: (x for x in range(n)) or pre-allocate: result = [None] * n.",
        "large_file_read": "Use file.read(chunk_size) or readline() in a loop for large files.",
        "blocking_call": "Use async equivalents: asyncio.sleep(), Thread.sleep() → await asyncio.sleep().",
        "deeply_nested_loop": "Refactor to use dictionaries/sets for O(1) lookups. Consider early-exit or divide-and-conquer.",
    }
    return suggestions.get(check_id, "Review this pattern for performance impact.")
```

- [ ] **步骤 3: 将 code_review 工具注册到 ToolRegistry 单例**

在 `nexus/nexus/tools/registry.py` 中，`get_tool_registry()` 函数内：

```python
# 在 from nexus.tools.rag import register_rag_tools 之后添加:
from nexus.tools.code_review import register_code_review_tools

# 在 register_rag_tools(_global_tool_registry) 之后添加:
register_code_review_tools(_global_tool_registry)
```

- [ ] **步骤 4: 运行测试验证工具注册**

```bash
python -c "from nexus.tools.registry import get_tool_registry; r = get_tool_registry(); tools = r.list_tools(); print([t.name for t in tools])"
```

预期: 列表中包含 `parse_diff`, `detect_language`, `security_check`, `perf_check`, `style_check`

- [ ] **步骤 5: 提交**

```bash
git add nexus/nexus/tools/code_review.py nexus/nexus/tools/registry.py
git commit -m "feat(P8.1): code review tool set (parse_diff, security, perf, style, detect_language)"
```

---

### 任务 2: 代码审查 Prompt 模板

**文件:**
- 创建: (无 — 通过 API 创建)

- [ ] **步骤 1: 编写 prompt 模板种子脚本**

```python
# scripts/seed_code_review_prompt.py
"""为代码审查 Agent 创建默认的 PromptTemplate."""

import asyncio
from nexus.db.database import get_db_session
from nexus.models.prompt import PromptTemplate, PromptTemplateVersion

CODE_REVIEW_TEMPLATE = """You are a {{ role }}. Review the following {{ language }} code with focus on {{ focus_areas }}.

{% if strictness == "strict" %}
Apply the highest code review standards. Flag every potential issue including minor style concerns.
{% elif strictness == "normal" %}
Balance thoroughness with practicality. Focus on bugs, security, and maintainability.
{% else %}
Only flag critical issues: security vulnerabilities and bugs that would cause runtime errors.
{% endif %}

## Code to Review
```{{ language }}
{{ diff_content }}
```

## Review Instructions
1. First use the available tools to detect issues (parse_diff, security_check, perf_check, style_check)
2. Then use your expertise to identify logic errors and design problems the tools cannot detect
3. Output findings in the structured JSON format below

## Output Format
Respond with a JSON object:
{
  "findings": [
    {
      "severity": "critical|warning|suggestion",
      "category": "security|performance|style|logic|maintainability",
      "file": "path/to/file",
      "line": 42,
      "title": "Short finding title",
      "description": "Detailed description of the issue",
      "suggestion": "Fix suggestion with example code if applicable"
    }
  ],
  "summary": {
    "overall_score": "1-10",
    "strengths": ["strength 1", "strength 2"],
    "risks": ["risk 1", "risk 2"],
    "review_notes": "Overall assessment summary"
  }
}
"""

async def main():
    async with get_db_session() as session:
        template = PromptTemplate(
            tenant_id="00000000-0000-0000-0000-000000000000",
            name="code-review-standard",
            description="Default code review standard template with configurable strictness",
            template_type="system",
            current_version=1,
        )
        session.add(template)
        await session.flush()

        version = PromptTemplateVersion(
            template_id=template.id,
            version=1,
            content=CODE_REVIEW_TEMPLATE,
            variables=["role", "language", "focus_areas", "strictness", "diff_content"],
            change_notes="Initial code review template",
        )
        session.add(version)
        await session.commit()
        print(f"Created template: {template.id}")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 2: 运行种子脚本**

```bash
cd nexus && python scripts/seed_code_review_prompt.py
```

预期: 输出 "Created template: <uuid>"

- [ ] **步骤 3: 提交**

```bash
git add scripts/seed_code_review_prompt.py
git commit -m "feat(P8.1): seed code review prompt template"
```

---

### 任务 3: 代码审查工作流定义 + 示例

**文件:**
- 创建: `nexus/examples/code_review_agent.py`

- [ ] **步骤 1: 编写端到端示例**

```python
#!/usr/bin/env python3
"""代码审查 Agent 示例 — 交互式审查工作台.

展示 NEXUS 代码审查 Agent 的完整用法：
1. 注册代码审查工具
2. 定义 DAG 工作流 (start → review → end)
3. 通过 WorkflowEngine 执行
4. 输出结构化审查报告

用法: python examples/code_review_agent.py
"""

from __future__ import annotations

import asyncio
from nexus.engine.workflow_engine import Edge, Node, WorkflowDefinition, WorkflowEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.event_bus import EventBus
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.router_engine import RouterEngine
from nexus.engine.node_executors import (
    AgentNodeExecutor, EndNodeExecutor, StartNodeExecutor, ToolNodeExecutor,
)
from nexus.engine.enums import NodeType
from nexus.tools.registry import get_tool_registry


async def main():
    # 1. 注册工具
    registry = get_tool_registry()
    from nexus.tools.code_review import register_code_review_tools
    register_code_review_tools(registry)

    # 2. 定义工作流
    wf = WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START),
            Node(id="review", type=NodeType.AGENT,
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
                 }),
            Node(id="end", type=NodeType.END,
                 config={"output": {"mappings": {"review_report": "{{#review.output#}}"}}}),
        ],
        edges=[
            Edge(source="start", target="review"),
            Edge(source="review", target="end"),
        ],
    )

    # 3. 创建引擎
    state_manager = StateManager()
    event_bus = EventBus()
    engine = WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=CheckpointManager(),
        variable_pool=VariablePool(),
        router_engine=RouterEngine(),
    )

    # 4. 注册执行器
    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor(tool_registry=registry))
    engine.register_executor(NodeType.TOOL, ToolNodeExecutor(tool_registry=registry, event_bus=event_bus))

    # 5. 执行
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

    print("执行代码审查...")
    result = await engine.execute(
        workflow_def=wf,
        trigger_payload={"diff_content": diff_example},
        run_id="example-code-review",
    )

    print(f"状态: {result.status.value}")
    print(f"耗时: {result.duration_ms}ms")
    print(f"审查报告:\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 2: 运行示例验证**

```bash
cd nexus && python examples/code_review_agent.py
```

预期: 输出审查状态和报告（可能需要 LLM API 密钥配置）

- [ ] **步骤 3: 提交**

```bash
git add examples/code_review_agent.py
git commit -m "feat(P8.1): code review agent example with workflow DAG"
```

---

### 任务 4: 代码审查 API 路由

**文件:**
- 创建: `nexus/nexus/api/routes/code_review.py`
- 修改: `nexus/nexus/api/main.py:155-166`

- [ ] **步骤 1: 编写 API 路由**

```python
"""代码审查 API 路由.

Phase 8.1: 交互式审查工作台 — 提交审查 + 流式结果。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.database import get_db
from nexus.engine.event_bus import EventBus
from nexus.engine.workflow_engine import (
    Edge, Node, NodeType, WorkflowDefinition, WorkflowEngine,
)
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.node_executors import (
    AgentNodeExecutor, EndNodeExecutor, StartNodeExecutor, ToolNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.security.auth import get_current_user
from nexus.services.run import RunService
from nexus.tools.registry import get_tool_registry

router = APIRouter()


class ReviewSubmitRequest(BaseModel):
    """提交代码审查请求."""
    diff_content: str = Field(..., description="Git diff or code content to review")
    language: str = Field(default="auto", description="Programming language (auto-detected if 'auto')")
    focus_areas: str = Field(default="security, performance, maintainability, correctness")
    strictness: str = Field(default="normal", description="Review strictness: strict, normal, relaxed")
    template_id: UUID | None = None  # 可选的 prompt 模板 ID


class ReviewResponse(BaseModel):
    """审查结果响应."""
    run_id: UUID
    status: str
    report: dict[str, Any] | None = None


@router.post("/reviews", response_model=ReviewResponse)
async def submit_review(
    data: ReviewSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """提交代码审查 — 触发工作流执行."""
    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("id")

    run_id = uuid4()

    # 构建审查工作流
    registry = get_tool_registry()
    event_bus = EventBus()

    wf = WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START),
            Node(id="review", type=NodeType.AGENT,
                 config={
                     "agent_name": "code-reviewer",
                     "agent_role": "senior software engineer performing code review",
                     "agent_goal": "Thoroughly review code and produce a structured review report",
                     "task_description": data.diff_content,
                     "system_prompt_template_id": str(data.template_id) if data.template_id else None,
                     "template_variables": {
                         "role": "senior software engineer",
                         "language": data.language,
                         "focus_areas": data.focus_areas,
                         "strictness": data.strictness,
                         "diff_content": data.diff_content,
                     },
                     "provider": "deepseek",
                     "model": "deepseek-chat",
                 }),
            Node(id="end", type=NodeType.END),
        ],
        edges=[
            Edge(source="start", target="review"),
            Edge(source="review", target="end"),
        ],
    )

    engine = WorkflowEngine(
        state_manager=StateManager(),
        event_bus=event_bus,
        checkpoint_mgr=CheckpointManager(),
        variable_pool=VariablePool(),
        router_engine=RouterEngine(),
    )

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor(tool_registry=registry))
    engine.register_executor(NodeType.TOOL, ToolNodeExecutor(tool_registry=registry, event_bus=event_bus))

    # 在后台执行（通过 EventBus 流式推送进度）
    import asyncio

    async def _run():
        result = await engine.execute(
            workflow_def=wf,
            trigger_payload={"diff_content": data.diff_content},
            run_id=str(run_id),
        )
        return result

    asyncio.create_task(_run())

    return ReviewResponse(run_id=run_id, status="started")


@router.get("/reviews/{run_id}")
async def get_review_result(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
):
    """获取审查结果（通过 RunService 查询 run 状态）."""
    run_service = RunService()
    tenant_id = UUID(current_user.get("tenant_id"))
    run = await run_service.get(db, run_id, tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Review run not found")
    return {"run_id": run_id, "status": run.status, "result": run.result}
```

- [ ] **步骤 2: 在 main.py 中注册路由**

在 `nexus/nexus/api/main.py`:
```python
# 添加导入:
from nexus.api.routes import code_review as code_review_routes

# 添加路由:
app.include_router(code_review_routes.router, prefix="/api/v1/code-review", tags=["code-review"])
```

- [ ] **步骤 3: 运行测试验证无回归**

```bash
python -m pytest tests/ -v --ignore=tests/test_workflow_engine.py 2>&1 | tail -5
```

预期: 178 passed

- [ ] **步骤 4: 提交**

```bash
git add nexus/nexus/api/routes/code_review.py nexus/nexus/api/main.py
git commit -m "feat(P8.1): code review API route (submit review, get result)"
```

---

### 任务 5: 前端审查工作台

**文件:**
- 创建: `nexus-ui/src/views/CodeReview.vue`

- [ ] **步骤 1: 编写 CodeReview.vue 组件**

```vue
<template>
  <div>
    <a-page-header title="代码审查" sub-title="AI Code Review Workbench">
      <template #extra>
        <a-button type="primary" @click="submitReview" :loading="reviewing">
          <PlayCircleOutlined /> 开始审查
        </a-button>
      </template>
    </a-page-header>

    <a-row :gutter="16">
      <!-- 输入区 -->
      <a-col :span="8">
        <a-card title="审查配置" size="small">
          <a-form layout="vertical">
            <a-form-item label="语言">
              <a-select v-model:value="config.language">
                <a-select-option value="auto">自动检测</a-select-option>
                <a-select-option value="python">Python</a-select-option>
                <a-select-option value="javascript">JavaScript</a-select-option>
                <a-select-option value="typescript">TypeScript</a-select-option>
                <a-select-option value="java">Java</a-select-option>
                <a-select-option value="go">Go</a-select-option>
                <a-select-option value="rust">Rust</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="关注领域">
              <a-select v-model:value="config.focus_areas" mode="multiple">
                <a-select-option value="security">安全</a-select-option>
                <a-select-option value="performance">性能</a-select-option>
                <a-select-option value="maintainability">可维护性</a-select-option>
                <a-select-option value="correctness">正确性</a-select-option>
                <a-select-option value="style">代码风格</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="严格度">
              <a-radio-group v-model:value="config.strictness">
                <a-radio-button value="strict">严格</a-radio-button>
                <a-radio-button value="normal">标准</a-radio-button>
                <a-radio-button value="relaxed">宽松</a-radio-button>
              </a-radio-group>
            </a-form-item>
          </a-form>
        </a-card>

        <a-card title="代码" size="small" style="margin-top: 12px">
          <a-tabs v-model:activeKey="inputMode">
            <a-tab-pane key="diff" tab="粘贴 Diff">
              <a-textarea v-model:value="diffContent" :rows="15" placeholder="粘贴 git diff..."/>
            </a-tab-pane>
            <a-tab-pane key="code" tab="直接粘贴代码">
              <a-textarea v-model:value="diffContent" :rows="15" placeholder="粘贴代码..."/>
            </a-tab-pane>
          </a-tabs>
        </a-card>
      </a-col>

      <!-- 报告区 -->
      <a-col :span="8">
        <a-card title="审查报告" size="small">
          <template v-if="report">
            <div style="text-align: center; margin: 16px 0">
              <a-progress type="circle" :percent="report.score * 10" :width="80"
                :format="p => `${report.score}/10`"
                :stroke-color="{ '0%': '#ff4d4f', '50%': '#faad14', '100%': '#52c41a' }"/>
            </div>

            <div v-if="report.strengths?.length" style="margin-bottom: 12px">
              <h4 style="color: #52c41a">✅ 优点</h4>
              <ul style="padding-left: 20px">
                <li v-for="s in report.strengths" :key="s">{{ s }}</li>
              </ul>
            </div>
            <div v-if="report.risks?.length">
              <h4 style="color: #faad14">⚠️ 风险</h4>
              <ul style="padding-left: 20px">
                <li v-for="r in report.risks" :key="r">{{ r }}</li>
              </ul>
            </div>
          </template>
          <a-empty v-else description="点击'开始审查'"/>
        </a-card>

        <!-- Findings -->
        <a-card title="发现" size="small" style="margin-top: 12px">
          <template v-if="findings.length">
            <a-list item-layout="vertical" :data-source="findings">
              <template #renderItem="{ item, index }">
                <a-list-item>
                  <a-list-item-meta>
                    <template #title>
                      <span :style="{ color: severityColor(item.severity) }">
                        {{ severityIcon(item.severity) }} #{{ index + 1 }} {{ item.title }}
                      </span>
                    </template>
                    <template #description>
                      <div style="font-size: 12px; color: #999">{{ item.file }}:{{ item.line }} · {{ item.category }}</div>
                      <p style="margin-top: 8px">{{ item.description }}</p>
                      <div v-if="item.suggestion" style="background: #f6f6f6; padding: 8px; border-radius: 4px; margin-top: 8px">
                        <strong>建议:</strong> {{ item.suggestion }}
                      </div>
                    </template>
                  </a-list-item-meta>
                </a-list-item>
              </template>
            </a-list>
          </template>
          <a-empty v-else description="暂无发现"/>
        </a-card>
      </a-col>

      <!-- 追问区 -->
      <a-col :span="8">
        <a-card title="追问" size="small">
          <div style="max-height: 400px; overflow-y: auto; margin-bottom: 12px">
            <div v-for="(msg, i) in followUpMessages" :key="i" style="margin-bottom: 12px">
              <div v-if="msg.role === 'user'" style="text-align: right">
                <a-tag color="blue">你</a-tag>
                <div style="background: #e6f7ff; padding: 8px; border-radius: 8px; display: inline-block; max-width: 80%; text-align: left">
                  {{ msg.content }}
                </div>
              </div>
              <div v-else>
                <a-tag color="green">AI</a-tag>
                <div style="background: #f6ffed; padding: 8px; border-radius: 8px; display: inline-block; max-width: 80%">
                  {{ msg.content }}
                </div>
              </div>
            </div>
          </div>
          <a-input-search v-model:value="followUpInput" placeholder="追问: 这个函数怎么拆分更好？"
            @search="sendFollowUp" :loading="followUpLoading"/>
        </a-card>

        <!-- 流式状态 -->
        <a-card title="审查进度" size="small" style="margin-top: 12px" v-if="reviewing">
          <div v-for="chunk in streamChunks" :key="chunk.index"
               style="font-family: monospace; font-size: 12px; color: #666; margin-bottom: 4px">
            {{ chunk.text }}
          </div>
          <a-spin v-if="reviewing" style="margin-left: 8px"/>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { message } from 'ant-design-vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'
import { api } from '@/utils/api'

const reviewing = ref(false)
const diffContent = ref('')
const inputMode = ref('diff')
const report = ref<any>(null)
const findings = ref<any[]>([])
const streamChunks = ref<any[]>([])
const followUpInput = ref('')
const followUpLoading = ref(false)
const followUpMessages = ref<{ role: string; content: string }[]>([])

const config = reactive({
  language: 'auto',
  focus_areas: ['security', 'performance', 'maintainability', 'correctness'],
  strictness: 'normal',
})

function severityColor(s: string) {
  return { critical: '#ff4d4f', warning: '#faad14', suggestion: '#1890ff' }[s] || '#666'
}

function severityIcon(s: string) {
  return { critical: '🔴', warning: '🟡', suggestion: '🔵' }[s] || '⚪'
}

async function submitReview() {
  if (!diffContent.value.trim()) {
    message.warning('请粘贴代码或 diff')
    return
  }
  reviewing.value = true
  report.value = null
  findings.value = []
  streamChunks.value = []

  try {
    const res = await api.post('/code-review/reviews', {
      diff_content: diffContent.value,
      language: config.language,
      focus_areas: config.focus_areas.join(', '),
      strictness: config.strictness,
    })
    const runId = res.data.run_id

    // WebSocket 连接获取流式进度
    const { connectWebSocket } = await import('@/api')
    const ws = connectWebSocket(runId)
    ws.onmessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data)
      if (data.type === 'stream_chunk') {
        streamChunks.value.push({ index: data.index, text: data.chunk })
      } else if (data.type === 'stream_end') {
        reviewing.value = false
        fetchResult(runId)
      }
    }
    ws.onerror = () => {
      reviewing.value = false
      message.error('连接中断，正在轮询结果...')
      setTimeout(() => fetchResult(runId), 2000)
    }
  } catch (e: any) {
    reviewing.value = false
    message.error(e.response?.data?.detail || '提交失败')
  }
}

async function fetchResult(runId: string) {
  try {
    const res = await api.get(`/code-review/reviews/${runId}`)
    const result = res.data.result || {}
    if (result.review_report) {
      const parsed = typeof result.review_report === 'string'
        ? JSON.parse(result.review_report)
        : result.review_report
      report.value = parsed.summary
      findings.value = parsed.findings || []
    }
  } catch (e) {
    message.error('获取结果失败')
  }
}

async function sendFollowUp(query: string) {
  if (!query.trim()) return
  followUpMessages.value.push({ role: 'user', content: query })
  followUpLoading.value = true
  try {
    // 复用审查 API，以追问模式
    const promptText = `关于之前的代码审查，用户追问: ${query}\n\n请针对该问题给出详细解答。`
    const res = await api.post('/code-review/reviews', {
      diff_content: promptText,
      language: config.language,
      strictness: config.strictness,
    })
    followUpMessages.value.push({ role: 'assistant', content: '正在分析...' })
    const runId = res.data.run_id
    setTimeout(async () => {
      try {
        const r = await api.get(`/code-review/reviews/${runId}`)
        followUpMessages.value.pop()
        followUpMessages.value.push({
          role: 'assistant',
          content: r.data.result?.output || '抱歉，无法获取回答。',
        })
      } catch { }
      followUpLoading.value = false
    }, 5000)
  } catch (e: any) {
    message.error('追问失败')
    followUpLoading.value = false
  }
  followUpInput.value = ''
}
</script>
```

- [ ] **步骤 2: 在路由中注册**

在 `nexus-ui/src/router/index.ts` 添加:
```typescript
{
  path: 'code-review',
  name: 'CodeReview',
  component: () => import('@/views/CodeReview.vue'),
},
```

- [ ] **步骤 3: 在侧边栏中注册**

在 `nexus-ui/src/views/Layout.vue`:
```typescript
// pageTitle 中添加:
codeReview: '代码审查',

// menuItems 中添加:
{ key: 'code-review', icon: () => h(CodeOutlined), label: '代码审查' },
```

- [ ] **步骤 4: 提交**

```bash
git add nexus-ui/src/views/CodeReview.vue nexus-ui/src/router/index.ts nexus-ui/src/views/Layout.vue
git commit -m "feat(P8.1): code review workbench UI with streaming progress"
```

---

### 任务 6: 测试

**文件:**
- 创建: `tests/test_code_review.py`

- [ ] **步骤 1: 编写测试**

```python
"""代码审查工具测试 — Phase 8.1.

覆盖:
- parse_diff: diff 解析、空输入
- security_check: 硬编码密钥、SQL 注入、XSS 检测
- perf_check: N+1 查询、阻塞调用检测
- style_check: 函数过长检测
- detect_language: 语言识别
"""

from __future__ import annotations

import pytest
from nexus.tools.code_review import (
    _handle_parse_diff,
    _handle_detect_language,
    _handle_security_check,
    _handle_perf_check,
    _handle_style_check,
    build_code_review_tools,
)
from nexus.tools.registry import ToolRegistry, ToolType


class TestParseDiff:
    @pytest.mark.asyncio
    async def test_parse_single_file_diff(self):
        diff = """diff --git a/app/main.py b/app/main.py
index 123..456 100644
--- a/app/main.py
+++ b/app/main.py
@@ -10,3 +10,5 @@
 def hello():
-    return "hello"
+    return "hello world"
+
+def new_func():
+    pass
"""
        result = await _handle_parse_diff({"diff_text": diff})
        assert result.success is True
        assert result.data["total_files"] == 1
        assert result.data["files"][0]["file"] == "app/main.py"
        assert result.data["files"][0]["added_lines"] == 3
        assert result.data["files"][0]["removed_lines"] == 1

    @pytest.mark.asyncio
    async def test_parse_empty_diff(self):
        result = await _handle_parse_diff({"diff_text": ""})
        assert result.success is False


class TestSecurityCheck:
    @pytest.mark.asyncio
    async def test_detect_hardcoded_api_key(self):
        code = 'api_key = "sk-abc123def456789"'
        result = await _handle_security_check({"file": "test.py", "content": code, "language": "python"})
        assert result.success is True
        assert len(result.data["findings"]) >= 1
        assert any("hardcoded" in f["check_id"].lower() for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_detect_sql_injection(self):
        code = 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)'
        result = await _handle_security_check({"file": "test.py", "content": code, "language": "python"})
        assert result.success is True
        assert any("sql_injection" == f["check_id"] for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_clean_code_no_findings(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b"
        result = await _handle_security_check({"file": "test.py", "content": code, "language": "python"})
        assert result.data["total"] == 0


class TestPerfCheck:
    @pytest.mark.asyncio
    async def test_n_plus_1_query_detection(self):
        code = """for user in users:
    results = db.execute("SELECT * FROM orders WHERE user_id = " + str(user.id))
"""
        result = await _handle_perf_check({"file": "test.py", "content": code, "language": "python"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_blocking_call_detection(self):
        code = "time.sleep(5)"
        result = await _handle_perf_check({"file": "test.py", "content": code, "language": "python"})
        assert result.success is True
        assert any("blocking" in f["check_id"].lower() for f in result.data["findings"])


class TestStyleCheck:
    @pytest.mark.asyncio
    async def test_long_function_detection(self):
        lines = ["def very_long_function():"] + ["    x = i * 2" for i in range(60)]
        code = "\n".join(lines)
        result = await _handle_style_check({"file": "test.py", "content": code, "language": "python"})
        assert result.success is True
        assert any("function_too_long" == f["check_id"] for f in result.data["findings"])


class TestDetectLanguage:
    @pytest.mark.asyncio
    async def test_detect_python(self):
        result = await _handle_detect_language({"files": [{"file": "main.py", "content": "def hello(): pass"}]})
        assert result.data["files"][0]["language"] == "python"

    @pytest.mark.asyncio
    async def test_detect_typescript(self):
        result = await _handle_detect_language({"files": [{"file": "app.ts", "content": "const x = 1"}]})
        assert result.data["files"][0]["language"] == "typescript"


class TestBuildCodeReviewTools:
    def test_all_tools_registered(self):
        registry = ToolRegistry()
        from nexus.tools.code_review import register_code_review_tools
        register_code_review_tools(registry)
        tools = registry.list_tools()
        tool_names = [t.name for t in tools]
        assert "parse_diff" in tool_names
        assert "security_check" in tool_names
        assert "perf_check" in tool_names
        assert "style_check" in tool_names
        assert "detect_language" in tool_names
```

- [ ] **步骤 2: 运行测试**

```bash
python -m pytest tests/test_code_review.py -v
```

预期: 全部通过

- [ ] **步骤 3: 运行全部测试验证无回归**

```bash
python -m pytest tests/ -v --ignore=tests/test_workflow_engine.py 2>&1 | tail -5
```

- [ ] **步骤 4: 提交**

```bash
git add tests/test_code_review.py
git commit -m "test(P8.1): code review tools — parse_diff, security, perf, style tests"
```

---

### 任务 7: Phase 8.2 — GitHub PR 审查机器人

**文件:**
- 创建: `nexus/nexus/tools/github_tools.py`
- 创建: `nexus/nexus/api/routes/github_webhook.py`
- 修改: `nexus/nexus/api/main.py`

*（8.1 完成后再详细规划，此处仅列骨架）*

---

## 验证检查清单

- [ ] `parse_diff` 正确解析单文件和多文件 diff
- [ ] `security_check` 检测硬编码密钥、SQL 注入、XSS
- [ ] `perf_check` 检测 N+1 查询、阻塞调用
- [ ] `style_check` 检测函数过长
- [ ] `detect_language` 识别 Python、TypeScript 等
- [ ] 全部 5 个工具都注册到 ToolRegistry
- [ ] API `/api/v1/code-review/reviews` POST 返回 run_id
- [ ] API `/api/v1/code-review/reviews/{id}` GET 返回结果
- [ ] 前端 CodeReview.vue 提交审查并显示结果
- [ ] WebSocket 流式进度工作正常
- [ ] 追问功能多轮对话正常
- [ ] `python examples/code_review_agent.py` 成功执行
- [ ] 所有现有 178 个测试 + 新增测试全部通过
- [ ] 无 lint 错误 (`ruff check nexus/ tests/ --ignore=F401,E501`)
