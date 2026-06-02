"""RAG 助手工作流示例 — NEXUS + Smart Cache 端到端集成.

本示例演示如何构建一个智能客服助手，利用 Smart Cache 的语义缓存和
意图路由能力实现高效、精准的知识问答。

工作流结构:
    start ──► intent_match（意图识别）──► [分支]
                                            ├──► knowledge_agent（知识问答）──► end
                                            └──► chat_agent（闲聊）──► end

节点说明:
1. intent_match: rag_intent_match Tool
   - 将用户查询匹配到预注册意图（"knowledge", "greeting", "farewell"）
   - 输出: {"intent": "knowledge", "confidence": 0.95}

2. knowledge_agent: Agent 节点
   - 使用 rag_ask Tool 调用 Smart Cache 获取带缓存的回答
   - 支持多轮对话和历史注入

3. chat_agent: Agent 节点
   - 普通对话，不经过 RAG 缓存

前置条件:
    - Smart Cache (llm-cache-engine) 已启动，端口 8777
    - NEXUS API 已启动
    - 已在 Smart Cache 中注册意图（见下方 setup_intents）

使用方法:
    # 1. 注册意图（只需执行一次）
    python examples/rag_assistant.py --setup

    # 2. 创建并执行工作流
    python examples/rag_assistant.py --run

    # 3. 查看完整的 API 调用示例
    python examples/rag_assistant.py --show
"""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx

# Smart Cache 默认地址（Docker 部署）
SMART_CACHE_URL = "http://localhost:8777"
NEXUS_URL = "http://localhost:8000"


INTENTS = [
    {
        "name": "knowledge",
        "description": "用户询问产品、技术、业务相关知识",
        "examples": [
            "什么是语义缓存？",
            "你们的产品支持哪些模型？",
            "如何配置工作流？",
            "API 文档在哪里？",
        ],
    },
    {
        "name": "greeting",
        "description": "用户打招呼",
        "examples": [
            "你好",
            "Hello",
            "Hi there",
            "在吗",
        ],
    },
    {
        "name": "farewell",
        "description": "用户告别",
        "examples": [
            "再见",
            "Bye",
            "谢谢，我先走了",
        ],
    },
    {
        "name": "complaint",
        "description": "用户投诉或反馈问题",
        "examples": [
            "这个功能不好用",
            "服务又挂了",
            "为什么总是报错",
        ],
    },
]


async def setup_intents() -> None:
    """在 Smart Cache 中注册意图（只需执行一次）."""
    print("Registering intents to Smart Cache...")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SMART_CACHE_URL}/v1/intents",
            json={"intents": INTENTS},
        )
        response.raise_for_status()
        result = response.json()
        print(f"Registered {result.get('count', len(INTENTS))} intents")
        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")


WORKFLOW_CONFIG = {
    "name": "RAG 智能客服助手",
    "description": "基于 Smart Cache 语义缓存的智能客服，支持意图路由和知识问答",
    "config": {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "config": {},
            },
            {
                "id": "intent_match",
                "type": "tool",
                "config": {
                    "tool_name": "rag_intent_match",
                    "inputs": {
                        "query": "{{#trigger.query#}}",
                    },
                },
            },
            {
                "id": "knowledge_agent",
                "type": "agent",
                "config": {
                    "name": "知识助手",
                    "role": "专业客服",
                    "goal": "基于知识库回答用户问题",
                    "system_prompt": "你是一个专业的客服助手。使用 rag_ask 工具查询知识库来回答问题。如果用户的问题是问候或告别，简单回应即可。",
                    "tools": ["rag_ask", "rag_history_recall"],
                    "max_iterations": 3,
                },
            },
            {
                "id": "chat_agent",
                "type": "agent",
                "config": {
                    "name": "闲聊助手",
                    "role": "友好助手",
                    "goal": "进行自然友好的对话",
                    "system_prompt": "你是一个友好的聊天助手。进行自然、简短的对话。",
                    "tools": [],
                    "max_iterations": 2,
                },
            },
            {
                "id": "end",
                "type": "end",
                "config": {},
            },
        ],
        "edges": [
            {"source": "start", "target": "intent_match"},
            {"source": "intent_match", "target": "knowledge_agent", "condition": "intent == 'knowledge'"},
            {"source": "intent_match", "target": "knowledge_agent", "condition": "intent == 'complaint'"},
            {"source": "intent_match", "target": "chat_agent"},
            {"source": "knowledge_agent", "target": "end"},
            {"source": "chat_agent", "target": "end"},
        ],
    },
}


async def create_workflow(token: str = "") -> str:
    """创建工作流并返回 workflow_id."""
    print(f"\nCreating workflow via {NEXUS_URL}/api/v1/workflows")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NEXUS_URL}/api/v1/workflows",
            json=WORKFLOW_CONFIG,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        if response.status_code != 201:
            print(f"Error creating workflow: {response.status_code}")
            print(response.text)
            return ""

        result = response.json()
        workflow_id = result.get("id", "")
        print(f"Created workflow: {workflow_id}")
        return workflow_id


async def trigger_run(workflow_id: str, query: str, session_id: str, token: str = "") -> dict:
    """触发工作流执行."""
    print(f"\nTriggering run for workflow {workflow_id}")
    print(f"Query: {query}")
    print(f"Session: {session_id}")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NEXUS_URL}/api/v1/workflows/{workflow_id}/runs",
            json={
                "trigger_payload": {
                    "query": query,
                    "session_id": session_id,
                },
            },
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        response.raise_for_status()
        result = response.json()
        print(f"Run triggered: {result.get('run_id')}")
        return result


async def get_run_status(run_id: str, token: str = "") -> dict:
    """查询执行状态."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{NEXUS_URL}/api/v1/runs/{run_id}",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        response.raise_for_status()
        return response.json()


async def run_example() -> None:
    """运行完整示例."""
    print("=" * 60)
    print("RAG Assistant Example — NEXUS + Smart Cache")
    print("=" * 60)

    # 1. 创建/获取工作流
    workflow_id = await create_workflow()
    if not workflow_id:
        print("Failed to create workflow. Exiting.")
        return

    # 2. 测试用例
    test_queries = [
        ("什么是语义缓存？", "test-session-001"),
        ("你好，请问在吗？", "test-session-002"),
        ("如何配置工作流节点？", "test-session-001"),  # 同一 session，测试历史
    ]

    for query, session_id in test_queries:
        print(f"\n{'─' * 50}")
        result = await trigger_run(workflow_id, query, session_id)
        run_id = result.get("run_id", "")

        # 等待完成（简单轮询）
        for _ in range(30):
            await asyncio.sleep(1)
            status = await get_run_status(run_id)
            if status.get("status") in ("completed", "failed", "cancelled"):
                print(f"Run completed: {status}")
                break
            print(f"  Status: {status.get('status')} ...")

    print(f"\n{'=' * 60}")
    print("Example completed.")
    print(f"{'=' * 60}")


def show_api_calls() -> None:
    """打印完整的 API 调用示例（curl）."""
    print("API 调用示例:")
    print("=" * 60)

    # 注册意图
    print("\n1. 注册意图（Smart Cache）:")
    print(f"""
curl -X POST {SMART_CACHE_URL}/v1/intents \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps({"intents": INTENTS}, ensure_ascii=False, indent=2)}'
""")

    # 创建工作流
    print("\n2. 创建工作流（NEXUS）:")
    print(f"""
curl -X POST {NEXUS_URL}/api/v1/workflows \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(WORKFLOW_CONFIG, ensure_ascii=False, indent=2)}'
""")

    # 触发执行
    print("\n3. 触发执行（NEXUS）:")
    print(f"""
curl -X POST {NEXUS_URL}/api/v1/workflows/{{workflow_id}}/runs \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps({
      "trigger_payload": {"query": "什么是语义缓存？", "session_id": "test-001"}
  }, ensure_ascii=False, indent=2)}'
""")

    # 查询运行状态
    print("\n4. 查询运行状态:")
    print(f"curl {NEXUS_URL}/api/v1/runs/{{run_id}}")

    # 列出工具
    print("\n5. 列出 RAG Tools:")
    print(f"curl {NEXUS_URL}/api/v1/tools")


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Assistant Example")
    parser.add_argument("--setup", action="store_true", help="注册意图到 Smart Cache")
    parser.add_argument("--run", action="store_true", help="创建并执行工作流")
    parser.add_argument("--show", action="store_true", help="显示 API 调用示例")
    args = parser.parse_args()

    if args.setup:
        await setup_intents()
    elif args.run:
        await run_example()
    elif args.show:
        show_api_calls()
    else:
        print("Usage:")
        print("  python examples/rag_assistant.py --setup   # 注册意图")
        print("  python examples/rag_assistant.py --run     # 运行示例")
        print("  python examples/rag_assistant.py --show    # 显示 API 示例")


if __name__ == "__main__":
    asyncio.run(main())
