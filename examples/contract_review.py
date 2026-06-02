#!/usr/bin/env python3
"""NEXUS 端到端验证脚本：合同审查工作流（Contract Review Workflow）

运行指令：从 D:/AI_learning/nexus 目录执行
    cd D:/AI_learning/nexus
    python examples/contract_review.py

前提条件：
    1. 已安装依赖: pip install -r requirements.txt
    2. （默认跳过 LLM）LiteLLM Proxy 运行在 http://localhost:4000 并提供 deepseek-chat 模型
    3. .env 文件中有必要的 API Key 配置（LITELLM_API_KEY 等）

若 LLM 不可用（Proxy 未启动），脚本会 catch 异常并打印说明，不会崩溃。
"""

import asyncio
import os
import sys

# ---- 确保 NEXUS 模块可导入 ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 加载环境变量 ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 未安装也不影响运行


async def main():
    from nexus.engine.workflow_engine import (
        Edge,
        Node,
        NodeExecutor,
        WorkflowDefinition,
        WorkflowEngine,
    )
    from nexus.engine.state_manager import StateManager
    from nexus.engine.event_bus import EventBus
    from nexus.engine.checkpoint import CheckpointManager
    from nexus.engine.variable_pool import VariablePool
    from nexus.engine.router_engine import RouterEngine
    from nexus.engine.node_executors import (
        AgentNodeExecutor,
        EndNodeExecutor,
        HITLNodeExecutor,
        StartNodeExecutor,
    )
    from nexus.engine.hitl_controller import HITLController
    from nexus.engine.enums import NodeType

    print("=" * 60)
    print("[NEXUS] 合同审查工作流 (Contract Review)")
    print("[NEXUS] 端到端验证脚本")
    print("=" * 60)

    # ================================================================
    # 1. 定义工作流：5 个节点串联
    # ================================================================
    nodes = [
        Node(
            id="start",
            type=NodeType.START,
        ),
        Node(
            id="extract_clauses",
            type=NodeType.AGENT,
            config={
                "agent_name": "条款提取员",
                "agent_role": "法律文件分析师",
                "task_description": (
                    "你是一位资深法律文件分析师。请仔细阅读以下合同文本，"
                    "并从中提取出所有关键条款，包括但不限于：\n"
                    "1. 合同主体信息（甲方、乙方）\n"
                    "2. 合同标的与数量\n"
                    "3. 价款/报酬条款\n"
                    "4. 履行期限与方式\n"
                    "5. 违约责任条款\n"
                    "6. 争议解决条款\n"
                    "7. 保密条款\n"
                    "8. 合同解除/终止条款\n\n"
                    "合同文本如下：\n"
                    "---\n"
                    "供应合同：甲方科技有限公司（买方）与乙方制造有限公司（卖方）就采购智能设备签订本合同。"
                    "产品单价100元，首批订购10000台，总价款100万元。交货期为合同生效后30个自然日内。"
                    "逾期交货每日按未交货物金额的0.5%支付违约金。质量不符合标准的，买方有权要求全额退款并索赔"
                    "直接损失的200%。知识产权及相关源代码归买方独占所有。争议由卖方所在地法院管辖。\n"
                    "---\n\n"
                    "请以结构化 JSON 格式输出提取到的条款列表，"
                    "每项条款包含 title (条款标题)、content (条款原文摘要)、"
                    "and risk_indicators (潜在风险关键词列表)。"
                ),
            },
        ),
        Node(
            id="risk_assessment",
            type=NodeType.AGENT,
            depends_on=["extract_clauses"],
            config={
                "agent_name": "风险评估师",
                "agent_role": "合同风险分析专家",
                "task_description": (
                    "你是一位合同风险分析专家。基于上游提取的条款列表，"
                    "请对每一则条款进行风险评估，确定其风险等级\n"
                    "（高/中/低），并说明理由。\n\n"
                    "评估维度包括：\n"
                    "1. 法律合规性风险\n"
                    "2. 商业条款不公风险\n"
                    "3. 履约可行性风险\n"
                    "4. 潜在争议风险\n\n"
                    "最终输出一份风险分析报告，包含 overall_risk_level"
                    "（综合风险等级：high/medium/low）、risk_items （每项风险评估详情）"
                    "和 recommendations （改进建议列表）。"
                ),
            },
        ),
        Node(
            id="human_review",
            type=NodeType.HITL,
            depends_on=["risk_assessment"],
            config={
                "hitl_type": "approve",
                "title": "合同审查结果确认",
                "description": (
                    "请审核 AI 生成的合同风险分析报告。"
                    "确认无误后点击通过，或点击拒绝要求重新审查。"
                ),
                # 如果 3 分钟内无人响应，自动通过（仅用于演示）
                "timeout_seconds": 180,
                "auto_on_timeout": True,
            },
        ),
        Node(
            id="end",
            type=NodeType.END,
            config={
                "output": {
                    "mappings": {
                        "extracted_clauses": "{{#extract_clauses.output#}}",
                        "risk_report": "{{#risk_assessment.output#}}",
                        "human_review": "{{#human_review.output#}}",
                    }
                }
            },
        ),
    ]

    edges = [
        Edge(source="start", target="extract_clauses"),
        Edge(source="extract_clauses", target="risk_assessment"),
        Edge(source="risk_assessment", target="human_review"),
        Edge(source="human_review", target="end"),
    ]

    workflow_def = WorkflowDefinition(nodes=nodes, edges=edges)

    print("\n[工作流] 节点定义：")
    for node in workflow_def.nodes:
        dep_str = f" (depends_on: {node.depends_on})" if node.depends_on else ""
        print(f"  - [{node.type.value}] {node.id}{dep_str}")
    print("\n[工作流] 边定义：")
    for edge in workflow_def.edges:
        cond_str = f" [condition: {edge.condition}]" if edge.condition else ""
        print(f"  - {edge.source} -> {edge.target}{cond_str}")

    # ================================================================
    # 2. 创建引擎组件
    # ================================================================
    print("\n[引擎] 初始化组件...")

    state_manager = StateManager()
    event_bus = EventBus()
    checkpoint_mgr = CheckpointManager()
    variable_pool = VariablePool()
    router_engine = RouterEngine()

    hitl_controller = HITLController(event_bus=event_bus)

    engine = WorkflowEngine(
        state_manager=state_manager,
        event_bus=event_bus,
        checkpoint_mgr=checkpoint_mgr,
        variable_pool=variable_pool,
        router_engine=router_engine,
    )

    # ================================================================
    # 3. 注册执行器
    # ================================================================
    print("[引擎] 注册执行器...")

    engine.register_executor(NodeType.START, StartNodeExecutor())
    engine.register_executor(NodeType.END, EndNodeExecutor())
    engine.register_executor(NodeType.AGENT, AgentNodeExecutor())
    engine.register_executor(NodeType.HITL, HITLNodeExecutor(
        hitl_controller=hitl_controller,
        default_timeout=180,
    ))

    print("  - StartNodeExecutor: OK")
    print("  - EndNodeExecutor: OK")
    print("  - AgentNodeExecutor: OK")
    print("  - HITLNodeExecutor: OK")

    # ================================================================
    # 4. 执行工作流
    # ================================================================
    trigger_payload = {
        "合同文本": (
            "供应合同\n\n"
            "甲方（供应商）：上海科技贸易有限公司\n"
            "乙方（采购方）：广州创新实业有限公司\n\n"
            "第一条 标的物：乙方从甲方采购一批电子元件，"
            "型号为 XC-2000，数量 50,000 件，"
            "单价人民币 28.50 元/件。\n\n"
            "第二条 质量标准：符合国家 GB/T 标准，"
            "甲方须提供合格证明。\n\n"
            "第三条 交货期限：甲方应在合同签订后 45 "
            "个工作日内分两批交货，每批各 25,000 件。\n\n"
            "第四条 价款支付：签约后 3 日内乙方支付 30%"
            "预付款；第一批货物签收后支付 40%；"
            "全部货物验收合格后支付剩余 30%。\n\n"
            "第五条 违约责任：任一方逾期履行超过 15 天，"
            "须按逾期金额每日万分之五支付违约金。"
            "乙方逾期付款超过 30 天，甲方有权解除合同。\n\n"
            "第六条 争议解决：本合同项下争议由甲方所在地"
            "人民法院管辖。\n\n"
            "第七条 保密条款：双方均不得向第三方透露合同内"
            "容，违者赔偿守约方全部损失。\n\n"
            "甲方签章：_________  乙方签章：_________\n"
            "签订日期：2026 年 __ 月 __ 日"
        ),
    }
    run_id = "contract-review-001"

    print(f"\n[执行] run_id: {run_id}")
    print(f"[执行] trigger_payload 已就绪（合同长度: {len(trigger_payload['合同文本'])} 字符）")
    print("[执行] 开始执行工作流 ...\n")

    result = None
    try:
        result = await engine.execute(
            workflow_def=workflow_def,
            trigger_payload=trigger_payload,
            run_id=run_id,
        )

        # ---- 打印执行结果 ----
        print("\n" + "=" * 60)
        print("[结果] 工作流执行完毕")
        print(f"  run_id:      {result.run_id}")
        print(f"  status:      {result.status.value}")
        print(f"  duration_ms: {result.duration_ms} ms")

        state = state_manager.get_state(run_id)
        if state:
            print(f"\n[状态] 各节点执行情况：")
            for node_id, node_status in state.node_states.items():
                output_preview = ""
                if node_id in state.node_outputs:
                    output = state.node_outputs[node_id]
                    if isinstance(output, dict):
                        keys = list(output.keys())
                        output_preview = f" -> keys: {keys[:5]}"
                    else:
                        output_preview = f" -> {str(output)[:80]}"
                print(f"  [{node_status.value:10s}] {node_id}{output_preview}")

            print(f"\n[输出] 最终工作流输出 keys: {list(result.output.keys())}")

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"[异常] 工作流执行时发生错误: {type(e).__name__}")
        print(f"  {e}")

        # 判断是否因 LLM 不可用导致
        error_str = str(e)
        if any(keyword in error_str.lower() for keyword in (
            "connection", "connect", "refused", "timeout", "http",
            "litellm", "proxy", "llm", "deepseek",
        )):
            print("\n" + "-" * 40)
            print("[提示] 该错误很可能是由于 LLM 服务不可用导致的。")
            print("请确认以下条件已满足：")
            print("  1. LiteLLM Proxy 已启动: docker-compose up litellm")
            print("    或手动启动: litellm --port 4000")
            print("  2. .env 文件中正确配置了 LITELLM_API_KEY")
            print("  3. 配置的模型（deepseek-chat）在 LiteLLM Proxy 中可用")
            print("-" * 40)
        else:
            print("\n[提示] 未知异常。请检查上方调用栈。")

        return  # 提前退出

    # 最终校验
    if result.status.value == "completed":
        print(f"\n[OK]  合同审查工作流端到端验证通过！")
    elif result.status.value == "failed":
        print(f"\n[WARN] 工作流标记为 FAILED（可能有节点执行出错）")
    else:
        print(f"\n[INFO] 工作流状态: {result.status.value}")


if __name__ == "__main__":
    asyncio.run(main())
