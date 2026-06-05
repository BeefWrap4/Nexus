#!/usr/bin/env python3
"""监控配置验证脚本.

用于验证所有Prometheus指标是否正确注册和采集。
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_workflow_metrics():
    """测试工作流指标模块."""
    print("🔍 Testing workflow metrics...")
    
    from nexus.observability.workflow_metrics import (
        WORKFLOW_DURATION,
        WORKFLOW_RUNS_TOTAL,
        WORKFLOW_RUNNING,
        NODE_DURATION,
        record_workflow_execution,
        record_node_execution,
    )
    
    # 测试记录工作流执行
    record_workflow_execution(
        tenant_id="test-tenant",
        workflow_name="test-workflow",
        status="succeeded",
        duration_seconds=1.5,
    )
    
    # 测试记录节点执行
    record_node_execution(
        node_type="agent",
        status="succeeded",
        duration_seconds=0.5,
    )
    
    print("✅ Workflow metrics module loaded successfully")
    return True


def test_agent_metrics():
    """测试Agent指标模块."""
    print("🔍 Testing agent metrics...")
    
    from nexus.observability.agent_metrics import (
        AGENT_DECISION_LATENCY,
        LLM_CALLS_TOTAL,
        LLM_COST_USD,
        LLM_TOKENS_TOTAL,
        record_agent_execution,
        record_llm_call,
    )
    
    # 测试记录Agent执行
    record_agent_execution(
        agent_name="test-agent",
        status="success",
        duration_seconds=2.0,
    )
    
    # 测试记录LLM调用
    record_llm_call(
        provider="openai",
        model="gpt-4o",
        status="success",
        prompt_tokens=100,
        completion_tokens=200,
        cost_usd=0.01,
        latency_seconds=1.0,
    )
    
    print("✅ Agent metrics module loaded successfully")
    return True


def test_queue_metrics():
    """测试队列指标模块."""
    print("🔍 Testing queue metrics...")
    
    from nexus.observability.queue_metrics import (
        QUEUE_LENGTH,
        ACTIVE_WORKERS,
        TASK_PROCESSING_TIME,
        update_queue_length,
        update_active_workers,
        record_task_execution,
    )
    
    # 测试更新队列长度
    update_queue_length(length=50)
    
    # 测试更新活跃Worker数
    update_active_workers(count=3)
    
    # 测试记录任务执行
    record_task_execution(
        job_type="workflow",
        status="success",
        duration_seconds=3.0,
    )
    
    print("✅ Queue metrics module loaded successfully")
    return True


def test_prometheus_export():
    """测试Prometheus指标导出."""
    print("🔍 Testing Prometheus metrics export...")
    
    from prometheus_client import generate_latest
    
    # 生成指标数据
    metrics_data = generate_latest()
    
    # 检查是否包含NEXUS自定义指标
    metrics_text = metrics_data.decode('utf-8')
    
    required_metrics = [
        'nexus_workflow_duration_seconds',
        'nexus_workflow_runs_total',
        'nexus_workflow_running',
        'nexus_node_duration_seconds',
        'nexus_agent_decision_latency_seconds',
        'nexus_llm_calls_total',
        'nexus_llm_cost_usd',
        'nexus_llm_tokens_total',
        'nexus_arq_queue_length',
        'nexus_task_processing_time_seconds',
    ]
    
    missing_metrics = []
    for metric in required_metrics:
        if metric not in metrics_text:
            missing_metrics.append(metric)
    
    if missing_metrics:
        print(f"❌ Missing metrics: {missing_metrics}")
        return False
    
    print(f"✅ All {len(required_metrics)} required metrics found")
    return True


def main():
    """运行所有测试."""
    print("=" * 60)
    print("NEXUS Monitoring Configuration Validation")
    print("=" * 60)
    print()
    
    tests = [
        test_workflow_metrics,
        test_agent_metrics,
        test_queue_metrics,
        test_prometheus_export,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
            print()
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
            print()
    
    # 总结
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    
    if all(results):
        print(f"✅ All tests passed ({passed}/{total})")
        print("=" * 60)
        return 0
    else:
        print(f"❌ Some tests failed ({passed}/{total} passed)")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
