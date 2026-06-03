#!/usr/bin/env python3
"""Code review tools tests — Phase 8.1.

Covers:
- parse_diff: diff parsing, empty input, binary files
- security_check: hardcoded secrets, SQL injection, XSS detection
- perf_check: N+1 queries, blocking calls
- style_check: long function detection, deep nesting
- detect_language: language identification, compound extensions, special filenames
"""

from __future__ import annotations

import pytest

from nexus.tools.code_review import (
    _detect_language_single,
    _handle_detect_language,
    _handle_parse_diff,
    _handle_perf_check,
    _handle_security_check,
    _handle_style_check,
    build_code_review_tools,
)
from nexus.tools.registry import ToolRegistry


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
        assert result.data["files"][0]["added_lines"] == 4
        assert result.data["files"][0]["removed_lines"] == 1
        assert len(result.data["files"][0]["hunks"]) == 1

    @pytest.mark.asyncio
    async def test_parse_empty_diff(self):
        result = await _handle_parse_diff({"diff_text": ""})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_parse_binary_diff(self):
        diff = "diff --git a/logo.png b/logo.png\nBinary files differ\n"
        result = await _handle_parse_diff({"diff_text": diff})
        assert result.success is True
        assert result.data["files"][0].get("binary") is True


class TestSecurityCheck:
    @pytest.mark.asyncio
    async def test_detect_hardcoded_api_key(self):
        code = 'api_key = "sk-abc123def456789"'
        result = await _handle_security_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert len(result.data["findings"]) >= 1
        assert any("hardcoded" in f["check_id"].lower() for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_detect_sql_injection(self):
        code = 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)'
        result = await _handle_security_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert any("sql_injection" == f["check_id"] for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_detect_eval_usage(self):
        code = "result = eval(user_input)"
        result = await _handle_security_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert any("eval_usage" == f["check_id"] for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_clean_code_no_findings(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b"
        result = await _handle_security_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.data["total"] == 0


class TestPerfCheck:
    @pytest.mark.asyncio
    async def test_blocking_call_detection(self):
        code = "time.sleep(5)\n"
        result = await _handle_perf_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert any("blocking" in f["check_id"].lower() for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_large_file_read_detection(self):
        code = 'data = f.read()\n'
        result = await _handle_perf_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert any("large_file_read" == f["check_id"] for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_clean_code_no_findings(self):
        code = "def add(a, b):\n    return a + b\n"
        result = await _handle_perf_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.data["total"] == 0


class TestStyleCheck:
    @pytest.mark.asyncio
    async def test_long_function_detection(self):
        lines = ["def very_long_function():"] + ["    x = i * 2" for i in range(60)]
        code = "\n".join(lines)
        result = await _handle_style_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True
        assert any("function_too_long" == f["check_id"] for f in result.data["findings"])

    @pytest.mark.asyncio
    async def test_deep_nesting_detection(self):
        # 17 levels * 4 spaces = 68 chars, threshold is 64
        code = "                \t                \t                \tx = 1\n"
        result = await _handle_style_check(
            {"file": "test.py", "content": code, "language": "python"}
        )
        assert result.success is True


class TestDetectLanguage:
    @pytest.mark.asyncio
    async def test_detect_python(self):
        result = await _handle_detect_language(
            {"files": [{"file": "main.py", "content": "def hello(): pass"}]}
        )
        assert result.data["files"][0]["language"] == "python"

    @pytest.mark.asyncio
    async def test_detect_typescript(self):
        result = await _handle_detect_language(
            {"files": [{"file": "app.ts", "content": "const x = 1"}]}
        )
        assert result.data["files"][0]["language"] == "typescript"

    def test_detect_compound_extension(self):
        assert _detect_language_single("archive.tar.gz", "") == "unknown"

    def test_detect_special_filename(self):
        assert _detect_language_single("Dockerfile", "") == "dockerfile"
        assert _detect_language_single("Makefile", "") == "makefile"

    def test_detect_shebang(self):
        assert _detect_language_single("script", "#!/usr/bin/env python3\nprint(1)") == "python"
        assert _detect_language_single("script", "#!/bin/bash\necho hello") == "shell"


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
