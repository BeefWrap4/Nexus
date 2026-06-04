"""CLI命令测试."""
import pytest
from typer.testing import CliRunner

runner = CliRunner()


class TestTemplateCLI:
    def test_template_list(self):
        from nexus_cli import app
        result = runner.invoke(app, ["template", "list"])
        assert result.exit_code == 0
        assert "code-reviewer" in result.stdout or "data-analyst" in result.stdout

    def test_template_show_valid(self):
        from nexus_cli import app
        result = runner.invoke(app, ["template", "show", "code-reviewer-v2"])
        assert result.exit_code == 0
        assert "code-reviewer-v2" in result.stdout

    def test_template_show_invalid(self):
        from nexus_cli import app
        result = runner.invoke(app, ["template", "show", "nonexistent"])
        assert result.exit_code != 0


class TestToolCLI:
    def test_tool_list(self):
        from nexus_cli import app
        result = runner.invoke(app, ["tool", "list"])
        assert result.exit_code == 0

    def test_tool_test_valid(self):
        from nexus_cli import app
        result = runner.invoke(app, ["tool", "test", "json"])
        assert result.exit_code == 0

    def test_tool_test_invalid(self):
        from nexus_cli import app
        result = runner.invoke(app, ["tool", "test", "invalid-tool"])
        assert result.exit_code != 0
