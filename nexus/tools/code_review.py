"""Code review agent tool set — Phase 8.1 interactive review workbench tools.

Provides deterministic checks (security/perf/style) and language detection.
Design principle: Python tools do deterministic checks (auditable),
LLM tool does semantic analysis.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

from nexus.tools.registry import Tool, ToolResult, ToolType

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level constants (avoid re-creation per call)
# ---------------------------------------------------------------------------

_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".vue": "vue",
    ".svelte": "svelte",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".cs": "csharp",
    ".lua": "lua",
    ".pl": "perl",
    ".r": "r",
}

# Special filenames without extension → language
_SPECIAL_FILENAMES: dict[str, str] = {
    "makefile": "makefile",
    "dockerfile": "dockerfile",
    "cmakelists.txt": "cmake",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "cargo.toml": "rust",
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
}

# Security patterns — bounded whitespace {0,20} to avoid ReDoS
_SECURITY_PATTERNS: list[tuple[str, str, str, str]] = [
    (
        "hardcoded_api_key",
        r'(?:api[_-]?key|apikey|secret|token|password)\s{0,20}[:=]\s{0,20}["\x27][a-zA-Z0-9_\-]{8,}["\x27]',
        "Hardcoded API key or secret",
        "critical",
    ),
    (
        "hardcoded_password",
        r'(?:password|passwd)\s{0,20}[:=]\s{0,20}["\x27](?!changeme|example|password)[^"\x27]{3,}["\x27]',
        "Hardcoded password",
        "critical",
    ),
    (
        "sql_injection",
        r'(?:execute|executemany|cursor\.execute)\s*\([^)]*(?:\+|%|f["\x27]|f""")',
        "Potential SQL injection via string concatenation",
        "critical",
    ),
    ("eval_usage", r'\beval\s*\(', "Use of eval() — potential code injection risk", "warning"),
    (
        "xss_unsafe",
        r'(?:innerHTML|dangerouslySetInnerHTML|v-html|document\.write)\s*=',
        "Potential XSS via unsanitized HTML",
        "warning",
    ),
    (
        "open_redirect",
        r'(?:window\.location\s*=\s*|redirect\s*\(\s*)(?:req\.|request\.|params\.)',
        "Potential open redirect",
        "warning",
    ),
]

# Performance patterns — line-based (no \n inside patterns)
_PERF_PATTERNS: list[tuple[str, str, str, str, list[str]]] = [
    (
        "n_plus_1_query",
        r'\.(?:filter|get|query|execute|all)\s*\(',
        "Potential N+1 query — ORM call inside or near loop",
        "warning",
        ["python", "javascript", "typescript", "ruby"],
    ),
    (
        "list_append_in_loop",
        r'\.(?:append|extend|push)\s*\(',
        "List mutation in loop — consider pre-allocation or generator",
        "suggestion",
        ["python", "javascript", "typescript"],
    ),
    (
        "large_file_read",
        r'\.read\s*\(\s*\)(?!\s*\.split)',
        "Reading entire file into memory — consider streaming",
        "suggestion",
        ["python"],
    ),
    (
        "blocking_call",
        r'(?:time\.sleep\s*\(|Thread\.sleep|fs\.readFileSync|fs\.writeFileSync)',
        "Blocking call in async context",
        "warning",
        ["python", "javascript", "typescript"],
    ),
]

_SECURITY_SUGGESTIONS: dict[str, str] = {
    "hardcoded_api_key": "Use environment variables: os.environ.get('API_KEY'). Never hardcode secrets.",
    "hardcoded_password": "Use environment variables. Never store passwords in source code.",
    "sql_injection": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id=?', (user_id,)).",
    "eval_usage": "Avoid eval(). Use ast.literal_eval() for parsing or a proper parser library.",
    "xss_unsafe": "Use textContent instead of innerHTML, or sanitize with DOMPurify.",
    "open_redirect": "Validate redirect URLs against a whitelist.",
}

_PERF_SUGGESTIONS: dict[str, str] = {
    "n_plus_1_query": "Batch the query outside the loop. Use JOIN or prefetch_related().",
    "list_append_in_loop": "Use a generator expression or pre-allocate with known size.",
    "large_file_read": "Use read(chunk_size) or readline() in a loop for large files.",
    "blocking_call": "Use async equivalents: time.sleep() → await asyncio.sleep().",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_code_review_tools() -> list[Tool]:
    """Build the code review tool set."""
    return [
        Tool(
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
        ),
        Tool(
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
                        "items": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                        "description": "List of files with optional content",
                    },
                },
            },
        ),
        Tool(
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
        ),
        Tool(
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
        ),
        Tool(
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
        ),
    ]


def register_code_review_tools(registry: ToolRegistry) -> None:  # type: ignore[name-defined]
    """Register code review tools into the ToolRegistry."""
    tools = build_code_review_tools()
    for tool in tools:
        registry.register(tool)
    logger.info("code_review_tools_registered", count=len(tools))


# ---------------------------------------------------------------------------
# Handler Implementations
# ---------------------------------------------------------------------------

async def _handle_parse_diff(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Parse a git diff into structured file/hunk/line data."""
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return ToolResult(success=False, error="Empty diff text")

    files: list[dict[str, Any]] = []
    current_file: dict[str, Any] | None = None
    current_hunk: dict[str, Any] | None = None

    for line in diff_text.split("\n"):
        # File header: diff --git a/<path> b/<path>
        file_match = re.match(r"^diff --git a/(.+?) b/(.+?)$", line)
        if file_match:
            if current_file is not None:
                if current_hunk is not None:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            current_file = {
                "file": file_match.group(2),
                "hunks": [],
                "added_lines": 0,
                "removed_lines": 0,
            }
            current_hunk = None
            continue

        if current_file is None:
            continue

        # Binary file indicator
        if line.startswith("Binary files"):
            current_file["binary"] = True
            continue

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@ context
        hunk_match = re.match(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)$", line)
        if hunk_match:
            if current_hunk is not None:
                current_file["hunks"].append(current_hunk)
            current_hunk = {
                "old_start": int(hunk_match.group(1)),
                "old_count": int(hunk_match.group(2)) if hunk_match.group(2) else 1,
                "new_start": int(hunk_match.group(3)),
                "new_count": int(hunk_match.group(4)) if hunk_match.group(4) else 1,
                "context": hunk_match.group(5).strip(),
                "lines": [],
            }
            continue

        if current_hunk is None:
            continue

        # Track line changes
        if line.startswith("+") and not line.startswith("+++"):
            current_file["added_lines"] += 1
            current_hunk["lines"].append({"type": "added", "content": line[1:]})
        elif line.startswith("-") and not line.startswith("---"):
            current_file["removed_lines"] += 1
            current_hunk["lines"].append({"type": "removed", "content": line[1:]})
        elif line.startswith(" "):
            current_hunk["lines"].append({"type": "context", "content": line[1:]})
        # Skip "\ No newline at end of file" markers silently

    if current_file is not None:
        if current_hunk is not None:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    return ToolResult(success=True, data={"files": files, "total_files": len(files)})


async def _handle_detect_language(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Detect programming language from file extension or shebang."""
    files = params.get("files", [])

    results: list[dict[str, str]] = []
    for f in files:
        filename = f.get("file", "")
        content = f.get("content", "")
        language = _detect_language_single(filename, content)
        results.append({"file": filename, "language": language})

    return ToolResult(success=True, data={"files": results})


def _detect_language_single(filename: str, content: str) -> str:
    """Detect language for a single file."""
    # 1. Special filenames (Dockerfile, Makefile, etc.)
    basename_lower = Path(filename).name.lower()
    if basename_lower in _SPECIAL_FILENAMES:
        return _SPECIAL_FILENAMES[basename_lower]

    # 2. Extension mapping (handle compound extensions like .tar.gz)
    path = Path(filename)
    suffixes = path.suffixes
    if suffixes:
        # Try full compound extension first, then fall back to last suffix
        for ext in ["".join(suffixes), suffixes[-1]]:
            if ext in _EXTENSION_MAP:
                return _EXTENSION_MAP[ext]

    # 3. Shebang detection from content
    if content and content.startswith("#!/"):
        shebang = content.split("\n", 1)[0]
        if "python" in shebang:
            return "python"
        if "node" in shebang or "bash" in shebang or "sh" in shebang:
            return "shell"
        if "ruby" in shebang:
            return "ruby"
        if "perl" in shebang:
            return "perl"

    return "unknown"


async def _handle_security_check(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Check for common security vulnerabilities using pattern matching."""
    file = params.get("file", "")
    content = params.get("content", "")
    findings: list[dict[str, Any]] = []

    for line_idx, line in enumerate(content.split("\n"), 1):
        for check_id, pattern, description, severity in _SECURITY_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append(
                    {
                        "file": file,
                        "line": line_idx,
                        "severity": severity,
                        "category": "security",
                        "check_id": check_id,
                        "issue": description,
                        "context": line.strip()[:120],
                        "suggestion": _SECURITY_SUGGESTIONS.get(
                            check_id, "Review this pattern manually."
                        ),
                    }
                )

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


async def _handle_perf_check(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Check for performance anti-patterns."""
    file = params.get("file", "")
    content = params.get("content", "")
    language = params.get("language", "")
    findings: list[dict[str, Any]] = []
    lines = content.split("\n")

    # Multi-line context: track if we're inside a loop
    in_loop = False
    loop_indent = 0

    for line_idx, line in enumerate(lines, 1):
        current_indent = len(line) - len(line.lstrip())

        # Detect loop entry (Python-style for/while)
        if re.match(r"^\s*(?:for|while)\s+", line):
            in_loop = True
            loop_indent = current_indent
            continue

        # Detect loop exit (dedent below loop level)
        if in_loop and line.strip() and current_indent <= loop_indent:
            in_loop = False

        # Check perf patterns
        for check_id, pattern, description, severity, lang_filter in _PERF_PATTERNS:
            if lang_filter and language not in lang_filter:
                continue
            if re.search(pattern, line, re.IGNORECASE):
                # For n_plus_1_query, only flag if inside or near a loop
                if check_id == "n_plus_1_query" and not in_loop:
                    # Check if any of the previous 3 lines start a loop
                    near_loop = any(
                        re.match(r"^\s*(?:for|while)\s+", lines[max(0, line_idx - 1 - i)])
                        for i in range(3)
                    )
                    if not near_loop:
                        continue

                findings.append(
                    {
                        "file": file,
                        "line": line_idx,
                        "severity": severity,
                        "category": "performance",
                        "check_id": check_id,
                        "issue": description,
                        "context": line.strip()[:120],
                        "suggestion": _PERF_SUGGESTIONS.get(
                            check_id, "Review for performance impact."
                        ),
                    }
                )

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})


async def _handle_style_check(
    params: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> ToolResult:
    """Check for code style issues."""
    file = params.get("file", "")
    content = params.get("content", "")
    language = params.get("language", "")
    findings: list[dict[str, Any]] = []
    lines = content.split("\n")

    # --- Long function detection ---
    # Track brace depth for C-style languages; indent level for Python
    func_start_line: int | None = None
    func_name: str = ""
    brace_depth = 0
    inside_func = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect function start
        func_match = re.match(
            r"^\s*(?:def|function|func|async\s+def|public|private|protected|static)?\s*(\w+)\s*\(",
            line,
        )
        if func_match and not inside_func:
            # Heuristic: skip if this looks like a function call, not definition
            # (calls usually don't have type hints / access modifiers)
            if re.match(r"^\s*(?:def|function|func|async\s+def|public|private|protected)", line):
                func_name = func_match.group(1)
                func_start_line = i
                inside_func = True
                brace_depth = 0
                continue

        if not inside_func or func_start_line is None:
            continue

        # Track brace depth for C-style languages
        if language in {"javascript", "typescript", "java", "c", "cpp", "csharp", "go"}:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0 and i > func_start_line:
                func_length = i - func_start_line + 1
                if func_length > 50:
                    findings.append(
                        {
                            "file": file,
                            "line": func_start_line,
                            "severity": "warning",
                            "category": "style",
                            "check_id": "function_too_long",
                            "issue": f"Function '{func_name}' is {func_length} lines (recommended ≤50)",
                            "context": lines[func_start_line - 1].strip()[:120],
                            "suggestion": f"Refactor '{func_name}' into smaller helper functions.",
                        }
                    )
                inside_func = False
                func_start_line = None
        else:
            # Python / indent-based: use indentation heuristics
            # End when we hit a line at or below the function's indentation
            # that's not blank and not a comment/decorator/continuation
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.startswith("@")
                and not line.endswith("\\")
            ):
                indent = len(line) - len(line.lstrip())
                func_indent = len(lines[func_start_line - 1]) - len(
                    lines[func_start_line - 1].lstrip()
                )
                if indent <= func_indent and i > func_start_line + 1:
                    func_length = i - func_start_line
                    if func_length > 50:
                        findings.append(
                            {
                                "file": file,
                                "line": func_start_line,
                                "severity": "warning",
                                "category": "style",
                                "check_id": "function_too_long",
                                "issue": f"Function '{func_name}' is {func_length} lines (recommended ≤50)",
                                "context": lines[func_start_line - 1].strip()[:120],
                                "suggestion": f"Refactor '{func_name}' into smaller helper functions.",
                            }
                        )
                    inside_func = False
                    func_start_line = None

    # Catch function that runs to end of file
    if inside_func and func_start_line is not None:
        func_length = len(lines) - func_start_line + 1
        if func_length > 50:
            findings.append(
                {
                    "file": file,
                    "line": func_start_line,
                    "severity": "warning",
                    "category": "style",
                    "check_id": "function_too_long",
                    "issue": f"Function '{func_name}' is {func_length} lines (recommended ≤50)",
                    "context": lines[func_start_line - 1].strip()[:120],
                    "suggestion": f"Refactor '{func_name}' into smaller helper functions.",
                }
            )

    # --- Deep nesting detection ---
    max_indent = 0
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent > max_indent:
            max_indent = indent
        # Flag lines with >16 levels of nesting (4-space indent → 64 chars)
        if indent > 64:
            findings.append(
                {
                    "file": file,
                    "line": i,
                    "severity": "suggestion",
                    "category": "style",
                    "check_id": "deeply_nested",
                    "issue": f"Excessive indentation ({indent // 4} levels at {indent} chars)",
                    "context": line.strip()[:120],
                    "suggestion": "Extract nested blocks into separate functions.",
                }
            )

    return ToolResult(success=True, data={"findings": findings, "total": len(findings)})
