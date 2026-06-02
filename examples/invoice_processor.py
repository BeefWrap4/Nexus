#!/usr/bin/env python3
"""NEXUS E2E: 发票智能处理流程.

3节点Agent链：提取发票信息 → 合规性校验 → 汇总输出
全程使用 DeepSeek LLM，无需任何前端交互。

运行: python examples/invoice_processor.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.event_bus import EventBus
from nexus.engine.node_executors import (
    AgentNodeExecutor,
    EndNodeExecutor,
    StartNodeExecutor,
)
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeType,
    RunStatus,
    WorkflowDefinition,
    WorkflowEngine,
)


async def main():
    print("=" * 60)
    print("NEXUS E2E: 发票智能处理流程")
    print("=" * 60)

    # 发票数据（模拟OCR或上传的发票文本）
    invoice_text = (
        "========================================\n"
        "          增值税专用发票\n"
        "========================================\n"
        "发票号码: INV-2026-0042\n"
        "开票日期: 2026年06月02日\n"
        "销售方: A智能科技有限公司\n"
        "购买方: B精密制造有限公司\n"
        "----------------------------------------\n"
        "商品名称: 智能传感器模块 (SN-100)\n"
        "规格型号: SN-100 V3.2\n"
        "数量: 500 个\n"
        "单价: 200.00 元 (不含税)\n"
        "金额: 100,000.00 元\n"
        "税率: 13%\n"
        "税额: 13,000.00 元\n"
        "价税合计: 113,000.00 元\n"
        "----------------------------------------\n"
        "付款期限: 发票日后30个自然日内\n"
        "备注: 验收合格后付款\n"
        "========================================\n"
    )

    # 定义3节点Agent链：提取 → 校验 → 汇总
    wf = WorkflowDefinition(
        nodes=[
            Node(id="s", type=NodeType.START),
            Node(
                id="extract_info",
                type=NodeType.AGENT,
                config={
                    "agent_name": "发票信息提取员",
                    "agent_role": "财务数据提取专家，擅长从非结构化文本中提取结构化数据",
                    "task_description": (
                        "你是一位财务数据提取专家。请从以下发票文本中提取关键信息，"
                        "以JSON格式输出。\n\n"
                        "发票文本：\n"
                        f"```\n{invoice_text}```\n\n"
                        "提取字段：\n"
                        "- invoice_number: 发票号码\n"
                        "- date: 开票日期\n"
                        "- seller: 销售方全称\n"
                        "- buyer: 购买方全称\n"
                        "- product_name: 商品名称\n"
                        "- quantity: 数量（数字）\n"
                        "- unit_price: 单价（不含税，数字）\n"
                        "- amount: 金额（不含税）\n"
                        "- tax_rate: 税率（百分比数字）\n"
                        "- tax_amount: 税额\n"
                        "- total: 价税合计\n"
                        "- payment_terms: 付款期限\n"
                        "- notes: 备注\n\n"
                        "请用中文输出，JSON格式严格包含以上所有字段。"
                    ),
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                },
            ),
            Node(
                id="validate_compliance",
                type=NodeType.AGENT,
                depends_on=["extract_info"],
                config={
                    "agent_name": "发票合规校验员",
                    "agent_role": "财务合规审计师，擅长发现发票数据异常",
                    "task_description": (
                        "你是一位财务合规审计师。请检查已提取的发票数据进行合规性校验。\n\n"
                        "已提取的发票数据：\n"
                        "{{#extract_info.output#}}\n\n"
                        "校验项目：\n"
                        "1. 税额计算: 金额 × 税率 应等于 税额（允许±1元舍入误差）\n"
                        "2. 价税合计: 金额 + 税额 应等于 total\n"
                        "3. 单价合理性: 检查数量×单价≈金额\n"
                        "4. 付款条款: 是否存在不合理条款（如验收后付款、超长账期等）\n\n"
                        "输出JSON格式：\n"
                        "{\n"
                        '  "is_valid": true/false,\n'
                        '  "checks": [\n'
                        '    {"item": "税额计算", "passed": bool, "detail": "..."},\n'
                        '    {"item": "价税合计", "passed": bool, "detail": "..."},\n'
                        '    {"item": "单价合理性", "passed": bool, "detail": "..."},\n'
                        '    {"item": "付款条款", "passed": bool, "detail": "..."}\n'
                        "  ],\n"
                        '  "issues": ["异常项1", ...],\n'
                        '  "risk_level": "low/medium/high",\n'
                        '  "recommendation": "处理建议"\n'
                        "}"
                    ),
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                },
            ),
            Node(id="e", type=NodeType.END),
        ],
        edges=[
            Edge(source="s", target="extract_info"),
            Edge(source="extract_info", target="validate_compliance"),
            Edge(source="validate_compliance", target="e"),
        ],
    )

    # 创建引擎 + 注册执行器
    sm = StateManager()
    eb = EventBus()
    cp = CheckpointManager()
    vp = VariablePool()
    re_ = RouterEngine()
    engine = WorkflowEngine(sm, eb, cp, vp, re_)

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor())

    # 执行
    print("\n开始执行 3 节点 Agent 链...\n")
    result = await engine.execute(wf, {}, "invoice-demo-001")
    state = sm.get_state("invoice-demo-001")

    # 输出结果
    print(f"\n{'=' * 60}")
    print(f"执行结果: {result.status.value.upper()} (耗时 {result.duration_ms}ms)")
    print(f"{'=' * 60}")

    for nid in ["extract_info", "validate_compliance"]:
        out = state.node_outputs.get(nid, {})
        ns = state.node_states.get(nid, "?")
        icon = "✅" if ns.value == "succeeded" else "❌"
        text = str(out.get("output", ""))[:500]
        print(f"\n{icon} [{nid}] ({ns.value}):")
        print(f"   {text}")

    # 总结
    all_success = all(
        s.value == "succeeded" for s in state.node_states.values()
    )
    print(f"\n{'=' * 60}")
    print(f"{'✅ 全部通过!' if all_success else '❌ 存在失败节点'}")
    print(f"{'=' * 60}")

    return result


if __name__ == "__main__":
    asyncio.run(main())
