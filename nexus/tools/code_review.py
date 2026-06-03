"""Code review agent tool set — Phase 8.1 interactive review workbench tools.
Provides deterministic checks (security/perf/style) and language detection.
"""

from __future__ import annotations

import re
from typing import Any

from nexus.tools.registry import Tool, ToolResult, ToolType


def build_code_review_tools() -> list[Tool]:
    """Build the code review tool set."""
    tools: list[Tool] = []

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
                "file": {"type": "string"},
                "content": {"type": "string"},
                "language": {"type": "string"},
            },
        },
    ))

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
    """Register code review tools into the ToolRegistry."""
    import structlog

    logger = structlog.get_logger()
    tools = build_code_review_tools()
    for tool in tools:
        registry.register(tool)
    logger.info("code_review_tools_registered", count=len(tools))


# --- Handler Implementations ---

async def _handle_parse_diff(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """Parse a git diff into structured file/hunk/line data."""
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return ToolResult(success=False, error="Empty diff text")

    files = []
    current_file = None
    current_hunk = None

    for line in diff_text.split("\n"):
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
    """Detect programming language from file extension."""
    files = params.get("files", [])

    EXTENSION_MAP = {
        ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "jsx", ".tsx": "tsx",
        ".java": "java", ".go": "go", ".rs": "rust", ".cpp": "cpp", ".c": "c",
        ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
        ".vue": "vue", ".svelte": "svelte", ".sql": "sql", ".sh": "shell",
        ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".xml": "xml",
        ".css": "css", ".scss": "scss", ".html": "html", ".md": "markdown",
        ".cs": "csharp", ".lua": "lua",
    }

    results = []
    for f in files:
        filename = f.get("file", "")
        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        language = EXTENSION_MAP.get(ext, "unknown")
        results.append({"file": filename, "language": language, "extension": ext})

    return ToolResult(success=True, data={"files": results})


async def _handle_security_check(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """Check for common security vulnerabilities using pattern matching."""
    file = params.get("file", "")
    content = params.get("content", "")
    findings = []

    patterns = [
        ("hardcoded_api_key", r'(?:api[_-]?key|apikey|secret|token|password)\s*[:=]\s*["\x27][a-zA-Z0-9_\-]{8,}["\x27]', "Hardcoded API key or secret", "critical"),
        ("hardcoded_password", r'(?:password|passwd)\s*[:=]\s*["\x27](?!changeme|example|password)[^"\x27]{3,}["\x27]', "Hardcoded password", "critical"),
        ("sql_injection", r'(?:execute|executemany)\s*\(\s*(?:f["\x27]|["\x27]\s*%\s*["\x27]|["\x27]\s*\+)', "Potential SQL injection via string concatenation", "critical"),
        ("eval_usage", r'\beval\s*\(', "Use of eval() — potential code injection risk", "warning"),
        ("xss_unsafe", r'(?:innerHTML|dangerouslySetInnerHTML|v-html|document\.write)', "Potential XSS via unsanitized HTML", "warning"),
        ("open_redirect", r'(?:window\.location\s*=\s*|redirect\s*\(\s*)(?:req\.|request\.|params\.)', "Potential open redirect", "warning"),
    ]

    for line_idx, line in enumerate(content.split("\n"), 1):
        for check_id, pattern, description, severity in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    "file": file,
                    "line": line_idx,
                    "severity": severity,
                    "category": "security",
                    "check_id": check_id,
                    "issue": description,
                    "context": line.strip()[:120],
                    "suggestion": _get_security_suggestion(check_id),
                })

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


async def _handle_perf_check(params: dict[str, Any], context: dict[str, Any] = None) -> ToolResult:
    """Check for performance anti-patterns."""
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
    """Check for code style issues."""
    file = params.get("file", "")
    content = params.get("content", "")
    findings = []
    lines = content.split("\n")

    # Long function detection
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
                    "suggestion": f"Refactor '{func_name}' into smaller helper functions.",
                })

    # Deep nesting detection
    for i, line in enumerate(lines, 1):
        indent_level = len(line) - len(line.lstrip())
        if indent_level > 80:
            findings.append({
                "file": file, "line": i,
                "severity": "suggestion", "category": "style",
                "check_id": "deeply_nested",
                "issue": "Excessive indentation (>20 levels)",
                "context": line.strip()[:120],
                "suggestion": "Extract nested blocks into separate functions.",
            })

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


# --- Suggestion helpers ---

def _get_security_suggestion(check_id: str) -> str:
    suggestions = {
        "hardcoded_api_key": "Use environment variables: os.environ.get('API_KEY'). Never hardcode secrets.",
        "hardcoded_password": "Use environment variables. Never store passwords in source code.",
        "sql_injection": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id=?', (user_id,)).",
        "eval_usage": "Avoid eval(). Use ast.literal_eval() for parsing or a proper parser library.",
        "xss_unsafe": "Use textContent instead of innerHTML, or sanitize with DOMPurify.",
        "open_redirect": "Validate redirect URLs against a whitelist.",
    }
    return suggestions.get(check_id, "Review this pattern manually.")


def _get_perf_suggestion(check_id: str) -> str:
    suggestions = {
        "n_plus_1_query": "Batch the query outside the loop. Use JOIN or prefetch_related().",
        "memory_leak_list": "Use a generator expression or pre-allocate with known size.",
        "large_file_read": "Use read(chunk_size) or readline() in a loop for large files.",
        "blocking_call": "Use async equivalents: time.sleep() → await asyncio.sleep().",
        "deeply_nested_loop": "Refactor to use dictionaries/sets for O(1) lookups.",
    }
    return suggestions.get(check_id, "Review for performance impact.")
