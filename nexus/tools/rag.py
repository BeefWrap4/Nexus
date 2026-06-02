"""RAG Tools 集成 — Smart Cache (LLM Cache Engine) 作为外部 HTTP Tool Provider.

将 Smart Cache 的能力封装为 NEXUS ToolRegistry 中的标准 HTTP Tools，
让 NEXUS Agent 能够无缝调用语义缓存、嵌入计算、意图路由和会话历史召回。

Smart Cache 是独立 FastAPI 微服务，通过 HTTP 接口与 NEXUS 通信：
- 零依赖冲突：Smart Cache 的 faiss/onnxruntime 依赖与 NEXUS 隔离
- 独立扩缩容：Smart Cache 可独立部署和扩容
- 配置化集成：仅需 URL + API Key，即可切换环境
"""

from __future__ import annotations

import structlog

from nexus.config import settings
from nexus.tools.registry import Tool, ToolType

logger = structlog.get_logger()


def build_rag_tools() -> list[Tool]:
    """构建 RAG Tool 定义列表.

    每个 Tool 对应 Smart Cache 的一个 API 端点。
    URL 基于 SMART_CACHE_URL 配置动态构建。

    Returns:
        4 个 RAG Tool 定义（rag_ask, rag_embeddings, rag_intent_match, rag_history_recall）
    """
    base_url = settings.SMART_CACHE_URL.rstrip("/")
    api_key = settings.SMART_CACHE_API_KEY

    auth_config = {}
    if api_key:
        auth_config = {"type": "header", "key": "X-API-Key", "value": api_key}

    common_headers = {"Content-Type": "application/json"}
    timeout = settings.SMART_CACHE_TIMEOUT

    return [
        Tool(
            name="rag_ask",
            description="使用 Smart Cache 进行带语义缓存的 LLM 问答。"
            "如果问题命中缓存，直接返回缓存结果；否则调用 LLM 生成回答并缓存。"
            "支持会话历史注入和多轮对话。",
            type=ToolType.HTTP,
            config={
                "url": f"{base_url}/v1/llm/ask",
                "method": "POST",
                "headers": common_headers,
                "timeout": timeout,
            },
            auth_config=auth_config,
            schema={
                "type": "object",
                "required": ["prompt", "session_id"],
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "用户问题或提示词",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话ID，用于缓存隔离和历史关联",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "系统提示词（覆盖默认）",
                    },
                    "temperature": {
                        "type": "number",
                        "default": 0.2,
                        "description": "生成温度，越低越确定",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "语义相似度阈值（覆盖全局配置）",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "额外元数据，将附加到缓存条目",
                    },
                    "use_history": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否注入会话历史",
                    },
                    "history_turns": {
                        "type": "integer",
                        "default": 5,
                        "description": "注入的历史轮数",
                    },
                },
            },
        ),
        Tool(
            name="rag_embeddings",
            description="获取文本的向量嵌入。"
            "支持缓存：相同文本重复请求时直接返回缓存的嵌入向量。",
            type=ToolType.HTTP,
            config={
                "url": f"{base_url}/v1/embeddings",
                "method": "POST",
                "headers": common_headers,
                "timeout": timeout,
            },
            auth_config=auth_config,
            schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要嵌入的文本",
                    },
                },
            },
        ),
        Tool(
            name="rag_intent_match",
            description="将用户查询匹配到预注册的意图。"
            "返回最佳匹配的意图名称和置信度分数，用于工作流分支决策。",
            type=ToolType.HTTP,
            config={
                "url": f"{base_url}/v1/intents/match",
                "method": "POST",
                "headers": common_headers,
                "timeout": timeout,
            },
            auth_config=auth_config,
            schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户查询文本",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "匹配阈值，低于此值返回 None",
                    },
                },
            },
        ),
        Tool(
            name="rag_history_recall",
            description="从会话历史中语义召回相关消息。"
            "基于向量相似度搜索，返回与当前查询最相关的历史消息。",
            type=ToolType.HTTP,
            config={
                "url": f"{base_url}/v1/sessions/{{session_id}}/history/relevant",
                "method": "POST",
                "headers": common_headers,
                "timeout": timeout,
            },
            auth_config=auth_config,
            schema={
                "type": "object",
                "required": ["session_id", "query"],
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话ID",
                    },
                    "query": {
                        "type": "string",
                        "description": "查询文本",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "description": "返回的 Top-K 条相关消息",
                    },
                },
            },
        ),
    ]


def register_rag_tools(registry) -> None:
    """注册所有 RAG Tools 到 ToolRegistry.

    Args:
        registry: ToolRegistry 实例

    如果 SMART_CACHE_URL 未配置（为空），则跳过注册并记录警告。
    """
    if not settings.SMART_CACHE_URL:
        logger.warning("rag_tools_skipped", reason="SMART_CACHE_URL not configured")
        return

    tools = build_rag_tools()
    for tool in tools:
        registry.register(tool)
        logger.info("rag_tool_registered", name=tool.name, url=tool.config.get("url"))

    logger.info(
        "rag_tools_registered",
        count=len(tools),
        base_url=settings.SMART_CACHE_URL,
    )
