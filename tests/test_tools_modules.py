"""工具模块测试.

测试RAG、GitHub等工具模块的基础功能。
覆盖率目标: 0% → 50%+
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.tools.rag import build_rag_tools
from nexus.tools.github_tools import (
    build_github_tools,
    _handle_get_pr_diff,
    _handle_post_review_comment,
    _handle_list_pr_files,
)
from nexus.tools.registry import Tool, ToolType


class TestRAGTools:
    """测试RAG工具模块."""

    def test_build_rag_tools_returns_list(self):
        """测试build_rag_tools返回工具列表."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    assert isinstance(tools, list)
                    assert len(tools) > 0

    def test_rag_ask_stream_tool_structure(self):
        """测试rag_ask_stream工具结构."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    # 查找rag_ask_stream工具
                    rag_ask_stream = next(
                        (t for t in tools if t.name == "rag_ask_stream"),
                        None
                    )
                    
                    assert rag_ask_stream is not None
                    assert rag_ask_stream.type == ToolType.HTTP
                    assert "stream" in rag_ask_stream.config
                    assert rag_ask_stream.config["stream"] is True
                    assert rag_ask_stream.auth_config is not None

    def test_rag_ask_tool_structure(self):
        """测试rag_ask工具结构."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    rag_ask = next(
                        (t for t in tools if t.name == "rag_ask"),
                        None
                    )
                    
                    assert rag_ask is not None
                    assert rag_ask.type == ToolType.HTTP
                    assert "/v1/llm/ask" in rag_ask.config["url"]

    def test_rag_embeddings_tool_structure(self):
        """测试rag_embeddings工具结构."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    embeddings = next(
                        (t for t in tools if t.name == "rag_embeddings"),
                        None
                    )
                    
                    assert embeddings is not None
                    assert embeddings.type == ToolType.HTTP
                    assert "/v1/embeddings" in embeddings.config["url"]

    def test_rag_intent_match_tool_structure(self):
        """测试rag_intent_match工具结构."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    intent_match = next(
                        (t for t in tools if t.name == "rag_intent_match"),
                        None
                    )
                    
                    assert intent_match is not None
                    assert intent_match.type == ToolType.HTTP

    def test_rag_history_recall_tool_structure(self):
        """测试rag_history_recall工具结构."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'test-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    history_recall = next(
                        (t for t in tools if t.name == "rag_history_recall"),
                        None
                    )
                    
                    assert history_recall is not None
                    assert history_recall.type == ToolType.HTTP

    def test_rag_tools_auth_config_with_api_key(self):
        """测试带API key的RAG工具认证配置."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'secret-key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    for tool in tools:
                        assert tool.auth_config is not None
                        assert tool.auth_config["type"] == "header"
                        assert tool.auth_config["key"] == "X-API-Key"
                        assert tool.auth_config["value"] == "secret-key"

    def test_rag_tools_auth_config_without_api_key(self):
        """测试不带API key的RAG工具认证配置."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', ''):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    for tool in tools:
                        assert tool.auth_config == {}

    def test_rag_tools_url_construction(self):
        """测试RAG工具URL构建."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://custom-cache:8080'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', ''):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 60):
                    tools = build_rag_tools()
                    
                    for tool in tools:
                        assert tool.config["url"].startswith("http://custom-cache:8080")

    def test_rag_tools_schema_properties(self):
        """测试RAG工具的schema属性."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', ''):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    rag_ask = next((t for t in tools if t.name == "rag_ask"), None)
                    assert rag_ask is not None
                    assert rag_ask.schema is not None
                    assert "properties" in rag_ask.schema
                    assert "required" in rag_ask.schema


class TestGitHubTools:
    """测试GitHub工具模块."""

    def test_build_github_tools_returns_list(self):
        """测试build_github_tools返回工具列表."""
        tools = build_github_tools()
        
        assert isinstance(tools, list)
        assert len(tools) == 3

    def test_github_get_pr_diff_tool(self):
        """测试github_get_pr_diff工具."""
        tools = build_github_tools()
        
        get_diff = next((t for t in tools if t.name == "github_get_pr_diff"), None)
        
        assert get_diff is not None
        assert get_diff.type == ToolType.PYTHON
        assert get_diff.handler is not None
        assert "owner" in get_diff.schema["required"]
        assert "repo" in get_diff.schema["required"]
        assert "pull_number" in get_diff.schema["required"]

    def test_github_post_review_comment_tool(self):
        """测试github_post_review_comment工具."""
        tools = build_github_tools()
        
        post_comment = next(
            (t for t in tools if t.name == "github_post_review_comment"),
            None
        )
        
        assert post_comment is not None
        assert post_comment.type == ToolType.PYTHON
        assert post_comment.handler is not None
        assert "body" in post_comment.schema["required"]

    def test_github_list_pr_files_tool(self):
        """测试github_list_pr_files工具."""
        tools = build_github_tools()
        
        list_files = next((t for t in tools if t.name == "github_list_pr_files"), None)
        
        assert list_files is not None
        assert list_files.type == ToolType.PYTHON
        assert list_files.handler is not None

    @pytest.mark.asyncio
    async def test_handle_get_pr_diff_no_token(self):
        """测试获取PR diff时缺少token的情况."""
        result = await _handle_get_pr_diff(
            params={"owner": "test", "repo": "repo", "pull_number": 1}
        )
        
        # 如果没有设置GITHUB_TOKEN，应该返回失败
        assert result.success is False
        assert "token" in result.error.lower() or "GITHUB_TOKEN" in result.error

    @pytest.mark.asyncio
    async def test_handle_get_pr_diff_missing_params(self):
        """测试获取PR diff时缺少参数的情况."""
        result = await _handle_get_pr_diff(params={})
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handle_post_review_comment_no_token(self):
        """测试发布评论时缺少token的情况."""
        result = await _handle_post_review_comment(
            params={
                "owner": "test",
                "repo": "repo",
                "pull_number": 1,
                "body": "Test comment",
            }
        )
        
        assert result.success is False
        assert "token" in result.error.lower() or "GITHUB_TOKEN" in result.error

    @pytest.mark.asyncio
    async def test_handle_post_review_comment_missing_required_params(self):
        """测试发布评论时缺少必需参数."""
        result = await _handle_post_review_comment(params={})
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handle_list_pr_files_no_token(self):
        """测试列出PR文件时缺少token的情况."""
        result = await _handle_list_pr_files(
            params={"owner": "test", "repo": "repo", "pull_number": 1}
        )
        
        assert result.success is False
        assert "token" in result.error.lower() or "GITHUB_TOKEN" in result.error

    @pytest.mark.asyncio
    async def test_handle_list_pr_files_missing_params(self):
        """测试列出PR文件时缺少参数."""
        result = await _handle_list_pr_files(params={})
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_handle_get_pr_diff_with_mock_http(self):
        """测试使用Mock HTTP客户端获取PR diff."""
        mock_response_data = "diff --git a/file.py b/file.py\n+new line"
        
        with patch('nexus.tools.github_tools._get_github_token', return_value='test-token'):
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = AsyncMock()
                mock_response.text = mock_response_data
                mock_response.raise_for_status = MagicMock()
                mock_client.get.return_value = mock_response
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                result = await _handle_get_pr_diff(
                    params={"owner": "test", "repo": "repo", "pull_number": 123}
                )
                
                assert result.success is True
                assert result.data is not None

    @pytest.mark.asyncio
    async def test_handle_post_review_comment_with_mock_http(self):
        """测试使用Mock HTTP客户端发布评论."""
        with patch('nexus.tools.github_tools._get_github_token', return_value='test-token'):
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.json.return_value = {"id": 12345}
                mock_response.raise_for_status = MagicMock()
                # 关键修复：post必须是AsyncMock
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                result = await _handle_post_review_comment(
                    params={
                        "owner": "test",
                        "repo": "repo",
                        "pull_number": 123,
                        "body": "Great PR!",
                    }
                )
                
                assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_list_pr_files_with_mock_http(self):
        """测试使用Mock HTTP客户端列出PR文件."""
        mock_files = [
            {"filename": "file1.py", "status": "modified"},
            {"filename": "file2.py", "status": "added"},
        ]
        
        with patch('nexus.tools.github_tools._get_github_token', return_value='test-token'):
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.json.return_value = mock_files
                mock_response.raise_for_status = MagicMock()
                # 关键修复：get必须是AsyncMock
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                result = await _handle_list_pr_files(
                    params={"owner": "test", "repo": "repo", "pull_number": 123}
                )
                
                assert result.success is True
                assert result.data is not None
                assert len(result.data) == 2

    def test_github_tools_handler_assignment(self):
        """测试GitHub工具的handler分配."""
        tools = build_github_tools()
        
        for tool in tools:
            assert tool.handler is not None
            assert callable(tool.handler)

    def test_github_tools_schema_validation(self):
        """测试GitHub工具的schema验证."""
        tools = build_github_tools()
        
        for tool in tools:
            assert tool.schema is not None
            assert "type" in tool.schema
            assert "properties" in tool.schema
            assert "required" in tool.schema


class TestToolIntegration:
    """测试工具集成场景."""

    def test_all_rag_tools_have_required_fields(self):
        """测试所有RAG工具都有必需字段."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', 'key'):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    
                    for tool in tools:
                        assert hasattr(tool, 'name')
                        assert hasattr(tool, 'description')
                        assert hasattr(tool, 'type')
                        assert hasattr(tool, 'config')
                        assert tool.name
                        assert tool.description

    def test_all_github_tools_have_required_fields(self):
        """测试所有GitHub工具都有必需字段."""
        tools = build_github_tools()
        
        for tool in tools:
            assert hasattr(tool, 'name')
            assert hasattr(tool, 'description')
            assert hasattr(tool, 'type')
            assert hasattr(tool, 'config')
            assert tool.name
            assert tool.description

    def test_tool_name_uniqueness_rag(self):
        """测试RAG工具名称唯一性."""
        with patch('nexus.config.settings.SMART_CACHE_URL', 'http://cache-service'):
            with patch('nexus.config.settings.SMART_CACHE_API_KEY', ''):
                with patch('nexus.config.settings.SMART_CACHE_TIMEOUT', 30):
                    tools = build_rag_tools()
                    names = [t.name for t in tools]
                    assert len(names) == len(set(names))

    def test_tool_name_uniqueness_github(self):
        """测试GitHub工具名称唯一性."""
        tools = build_github_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names))
