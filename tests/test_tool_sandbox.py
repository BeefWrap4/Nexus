"""S4-2: Tool 沙箱 (SSRF + chroot) 测试."""

import os
import sys

import pytest

from nexus.exceptions import ToolExecutionException
from nexus.tools.connectors.file_tool import _validate_path_within_workspace
from nexus.tools.connectors.http_tool import _validate_url_safety


# ---------------------------------------------------------------------------
# SSRF 防护
# ---------------------------------------------------------------------------


class TestSSRFProtection:
    """S4-2: 阻止 SSRF 到内网 / metadata endpoint。"""

    @pytest.mark.asyncio
    async def test_localhost_blocked(self):
        """http://localhost 应被拒（127.0.0.0/8）。"""
        with pytest.raises(ToolExecutionException) as exc:
            await _validate_url_safety("http://localhost:8080/admin")
        assert "blocked" in str(exc.value).lower() or "private" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_127_loopback_blocked(self):
        """http://127.0.0.1 应被拒。"""
        with pytest.raises(ToolExecutionException):
            await _validate_url_safety("http://127.0.0.1:5432/")

    @pytest.mark.asyncio
    async def test_aws_metadata_blocked(self):
        """http://169.254.169.254/latest/meta-data 应被拒 (云 metadata endpoint)。"""
        with pytest.raises(ToolExecutionException) as exc:
            await _validate_url_safety("http://169.254.169.254/latest/meta-data/")
        assert "169.254" in str(exc.value) or "metadata" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_rfc1918_private_blocked(self):
        """10.0.0.0/8、172.16.0.0/12、192.168.0.0/16 都应被拒。"""
        for private_ip in ("http://10.0.0.1/", "http://172.16.5.5/", "http://192.168.1.1/"):
            with pytest.raises(ToolExecutionException):
                await _validate_url_safety(private_ip)

    @pytest.mark.asyncio
    async def test_file_scheme_blocked(self):
        """file:// 协议应被拒。"""
        with pytest.raises(ToolExecutionException) as exc:
            await _validate_url_safety("file:///etc/passwd")
        assert "scheme" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_no_hostname_blocked(self):
        """无 hostname 的 URL 应被拒。"""
        with pytest.raises(ToolExecutionException):
            await _validate_url_safety("http:///path")

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("CI_NO_NET") == "1" or sys.platform == "win32",
        reason="需要真实 DNS 解析",
    )
    async def test_public_url_allowed(self):
        """公开 URL 应通过（例如 example.com）。"""
        # 不真发请求，只走 URL 校验
        # 如果 DNS 失败会抛 ToolExecutionException(..., "DNS resolution failed")
        # 我们用真实存在的公共 host
        try:
            await _validate_url_safety("https://www.example.com/")
        except ToolExecutionException as e:
            if "DNS resolution failed" in str(e):
                pytest.skip("网络不可用")
            else:
                raise


# ---------------------------------------------------------------------------
# 文件 chroot
# ---------------------------------------------------------------------------


class TestFileChroot:
    """S4-2: 文件操作必须在 workspace root 内。"""

    def test_path_in_workspace_allowed(self, tmp_path):
        """workspace 内的文件应允许。"""
        from nexus.tools.connectors import file_tool
        # 直接修改模块级 _WORKSPACE_ROOT（因为 import 时已固定，monkeypatch.setenv 没用）
        original = file_tool._WORKSPACE_ROOT
        file_tool._WORKSPACE_ROOT = str(tmp_path)
        try:
            real = _validate_path_within_workspace(str(tmp_path / "foo.txt"))
            assert real.startswith(str(tmp_path))
        finally:
            file_tool._WORKSPACE_ROOT = original

    def test_etc_passwd_blocked(self):
        """/etc/passwd 必须被拒。"""
        with pytest.raises(ToolExecutionException) as exc:
            _validate_path_within_workspace("/etc/passwd")
        assert "workspace" in str(exc.value).lower() or "escapes" in str(exc.value).lower()

    def test_app_env_blocked(self):
        """/app/.env 必须被拒（之前可被 LLM 改 SECRET_KEY）。"""
        with pytest.raises(ToolExecutionException):
            _validate_path_within_workspace("/app/.env")

    def test_relative_traversal_blocked(self, tmp_path):
        """../ 绕过 workspace 应被拒。"""
        from nexus.tools.connectors import file_tool
        original = file_tool._WORKSPACE_ROOT
        file_tool._WORKSPACE_ROOT = str(tmp_path)
        try:
            with pytest.raises(ToolExecutionException):
                _validate_path_within_workspace(str(tmp_path / "../outside.txt"))
        finally:
            file_tool._WORKSPACE_ROOT = original


# ---------------------------------------------------------------------------
# 工具端到端（实际 execute）
# ---------------------------------------------------------------------------


class TestFileToolExecution:
    """read_file / write_file 真的走 chroot。"""

    @pytest.mark.asyncio
    async def test_read_file_blocks_etc_passwd(self):
        """read_file 拒绝 /etc/passwd (registry.execute 抛 ToolExecutionException)。"""
        from nexus.tools.connectors.file_tool import create_file_tools
        from nexus.tools.registry import ToolRegistry

        registry = ToolRegistry()
        create_file_tools(registry)

        # 修复：file_tool 抛 ToolExecutionException，registry.execute 会再包一层
        with pytest.raises(ToolExecutionException) as exc:
            await registry.execute(
                "read_file",
                {"path": "/etc/passwd"},
                context={"user_id": "u1", "tenant_id": "t1"},
            )
        # 嵌套异常信息中能找到 "workspace" 或 "escapes"
        msg = str(exc.value).lower()
        assert "workspace" in msg or "escapes" in msg

    @pytest.mark.asyncio
    async def test_write_file_blocks_etc_passwd(self):
        """write_file 拒绝写到 /etc/。"""
        from nexus.tools.connectors.file_tool import create_file_tools
        from nexus.tools.registry import ToolRegistry

        registry = ToolRegistry()
        create_file_tools(registry)

        with pytest.raises(ToolExecutionException) as exc:
            await registry.execute(
                "write_file",
                {"path": "/etc/evil.conf", "content": "pwned"},
                context={"user_id": "u1", "tenant_id": "t1"},
            )
        msg = str(exc.value).lower()
        assert "workspace" in msg or "escapes" in msg

    @pytest.mark.asyncio
    async def test_write_and_read_in_workspace(self, tmp_path, monkeypatch):
        """workspace 内能正常写读。"""
        from nexus.tools.connectors import file_tool
        # 直接重置模块级 _WORKSPACE_ROOT（不能用 monkeypatch.setattr 因为它是 module-level 字符串）
        file_tool._WORKSPACE_ROOT = str(tmp_path)

        from nexus.tools.connectors.file_tool import create_file_tools
        from nexus.tools.registry import ToolRegistry

        registry = ToolRegistry()
        create_file_tools(registry)

        # 写
        result_w = await registry.execute(
            "write_file",
            {"path": str(tmp_path / "test.txt"), "content": "hello"},
            context={"user_id": "u1", "tenant_id": "t1"},
        )
        assert result_w.success, f"write failed: {result_w.error}"

        # 读
        result_r = await registry.execute(
            "read_file",
            {"path": str(tmp_path / "test.txt")},
            context={"user_id": "u1", "tenant_id": "t1"},
        )
        assert result_r.success
        assert result_r.data["content"] == "hello"
