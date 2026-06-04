"""NEXUS Service Level Objectives (SLO) 配置.

定义系统的性能目标和可用性要求，用于监控和告警。
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ServiceLevelObjective:
    """服务等级目标配置."""

    # =========================================================================
    # API 延迟指标 (毫秒)
    # =========================================================================
    API_P50_LATENCY_MS: int = 100
    """API P50延迟目标：50%的请求应在100ms内完成"""

    API_P95_LATENCY_MS: int = 300
    """API P95延迟目标：95%的请求应在300ms内完成"""

    API_P99_LATENCY_MS: int = 500
    """API P99延迟目标：99%的请求应在500ms内完成"""

    # =========================================================================
    # 工作流执行延迟指标 (毫秒)
    # =========================================================================
    WORKFLOW_SIMPLE_P95_MS: int = 5000
    """简单工作流(3节点)P95延迟目标：5秒"""

    WORKFLOW_MEDIUM_P95_MS: int = 15000
    """中等工作流(10节点)P95延迟目标：15秒"""

    WORKFLOW_COMPLEX_P95_MS: int = 30000
    """复杂工作流(20节点+并行)P95延迟目标：30秒"""

    # =========================================================================
    # Agent决策延迟指标 (毫秒)
    # =========================================================================
    AGENT_DECISION_P50_MS: int = 2000
    """Agent决策P50延迟目标：2秒"""

    AGENT_DECISION_P95_MS: int = 5000
    """Agent决策P95延迟目标：5秒"""

    # =========================================================================
    # LLM调用指标
    # =========================================================================
    LLM_CALL_P50_LATENCY_MS: int = 1000
    """LLM调用P50延迟目标：1秒"""

    LLM_CALL_P95_LATENCY_MS: int = 3000
    """LLM调用P95延迟目标：3秒"""

    LLM_CALL_P99_LATENCY_MS: int = 5000
    """LLM调用P99延迟目标：5秒"""

    # =========================================================================
    # 数据库查询指标 (毫秒)
    # =========================================================================
    DB_QUERY_P50_MS: int = 10
    """数据库查询P50延迟目标：10ms"""

    DB_QUERY_P95_MS: int = 50
    """数据库查询P95延迟目标：50ms"""

    DB_QUERY_P99_MS: int = 100
    """数据库查询P99延迟目标：100ms"""

    # =========================================================================
    # 缓存命中率指标
    # =========================================================================
    CACHE_HIT_RATE_TARGET: float = 0.8
    """缓存命中率目标：80%"""

    # =========================================================================
    # 可用性指标
    # =========================================================================
    AVAILABILITY_TARGET: float = 99.9
    """可用性目标：99.9% (每月停机时间不超过43分钟)"""

    # =========================================================================
    # 错误率指标
    # =========================================================================
    ERROR_RATE_THRESHOLD: float = 0.01
    """错误率阈值：1%"""

    LLM_ERROR_RATE_THRESHOLD: float = 0.05
    """LLM调用错误率阈值：5%"""

    # =========================================================================
    # 吞吐量指标 (请求/秒)
    # =========================================================================
    API_THROUGHPUT_RPS: int = 100
    """API吞吐量目标：100请求/秒"""

    WORKFLOW_EXECUTION_THROUGHPUT: int = 10
    """工作流执行吞吐量目标：10工作流/秒"""

    # =========================================================================
    # 并发限制
    # =========================================================================
    MAX_CONCURRENT_WORKFLOWS: int = 50
    """最大并发工作流数"""

    MAX_CONCURRENT_LLM_CALLS: int = 20
    """最大并发LLM调用数"""

    MAX_CONCURRENT_AGENT_TASKS: int = 30
    """最大并发Agent任务数"""

    # =========================================================================
    # 资源使用指标
    # =========================================================================
    CPU_USAGE_THRESHOLD: float = 80.0
    """CPU使用率告警阈值：80%"""

    MEMORY_USAGE_THRESHOLD: float = 85.0
    """内存使用率告警阈值：85%"""

    DATABASE_CONNECTION_POOL_USAGE: float = 80.0
    """数据库连接池使用率告警阈值：80%"""

    def to_dict(self) -> Dict[str, any]:
        """将SLO配置转换为字典格式."""
        return {
            "api_latency": {
                "p50_ms": self.API_P50_LATENCY_MS,
                "p95_ms": self.API_P95_LATENCY_MS,
                "p99_ms": self.API_P99_LATENCY_MS,
            },
            "workflow_latency": {
                "simple_p95_ms": self.WORKFLOW_SIMPLE_P95_MS,
                "medium_p95_ms": self.WORKFLOW_MEDIUM_P95_MS,
                "complex_p95_ms": self.WORKFLOW_COMPLEX_P95_MS,
            },
            "agent_decision_latency": {
                "p50_ms": self.AGENT_DECISION_P50_MS,
                "p95_ms": self.AGENT_DECISION_P95_MS,
            },
            "llm_call_latency": {
                "p50_ms": self.LLM_CALL_P50_LATENCY_MS,
                "p95_ms": self.LLM_CALL_P95_LATENCY_MS,
                "p99_ms": self.LLM_CALL_P99_LATENCY_MS,
            },
            "db_query_latency": {
                "p50_ms": self.DB_QUERY_P50_MS,
                "p95_ms": self.DB_QUERY_P95_MS,
                "p99_ms": self.DB_QUERY_P99_MS,
            },
            "cache_hit_rate": self.CACHE_HIT_RATE_TARGET,
            "availability": self.AVAILABILITY_TARGET,
            "error_rates": {
                "general": self.ERROR_RATE_THRESHOLD,
                "llm": self.LLM_ERROR_RATE_THRESHOLD,
            },
            "throughput": {
                "api_rps": self.API_THROUGHPUT_RPS,
                "workflow_per_second": self.WORKFLOW_EXECUTION_THROUGHPUT,
            },
            "concurrency_limits": {
                "max_concurrent_workflows": self.MAX_CONCURRENT_WORKFLOWS,
                "max_concurrent_llm_calls": self.MAX_CONCURRENT_LLM_CALLS,
                "max_concurrent_agent_tasks": self.MAX_CONCURRENT_AGENT_TASKS,
            },
            "resource_thresholds": {
                "cpu_usage_percent": self.CPU_USAGE_THRESHOLD,
                "memory_usage_percent": self.MEMORY_USAGE_THRESHOLD,
                "db_pool_usage_percent": self.DATABASE_CONNECTION_POOL_USAGE,
            },
        }


# 全局SLO实例
SLO = ServiceLevelObjective()


def check_slo_violation(metric_name: str, actual_value: float) -> tuple[bool, str]:
    """检查是否违反SLO.

    Args:
        metric_name: 指标名称
        actual_value: 实际值

    Returns:
        (是否违反SLO, 描述信息)
    """
    slo_map = {
        "api_p50_latency": (SLO.API_P50_LATENCY_MS, "API P50延迟"),
        "api_p95_latency": (SLO.API_P95_LATENCY_MS, "API P95延迟"),
        "api_p99_latency": (SLO.API_P99_LATENCY_MS, "API P99延迟"),
        "workflow_simple_p95": (SLO.WORKFLOW_SIMPLE_P95_MS, "简单工作流P95延迟"),
        "workflow_medium_p95": (SLO.WORKFLOW_MEDIUM_P95_MS, "中等工作流P95延迟"),
        "workflow_complex_p95": (SLO.WORKFLOW_COMPLEX_P95_MS, "复杂工作流P95延迟"),
        "agent_decision_p50": (SLO.AGENT_DECISION_P50_MS, "Agent决策P50延迟"),
        "agent_decision_p95": (SLO.AGENT_DECISION_P95_MS, "Agent决策P95延迟"),
        "llm_call_p50_latency": (SLO.LLM_CALL_P50_LATENCY_MS, "LLM调用P50延迟"),
        "llm_call_p95_latency": (SLO.LLM_CALL_P95_LATENCY_MS, "LLM调用P95延迟"),
        "llm_call_p99_latency": (SLO.LLM_CALL_P99_LATENCY_MS, "LLM调用P99延迟"),
        "db_query_p50": (SLO.DB_QUERY_P50_MS, "数据库查询P50延迟"),
        "db_query_p95": (SLO.DB_QUERY_P95_MS, "数据库查询P95延迟"),
        "db_query_p99": (SLO.DB_QUERY_P99_MS, "数据库查询P99延迟"),
    }

    if metric_name not in slo_map:
        return False, f"未知指标: {metric_name}"

    threshold, description = slo_map[metric_name]
    violated = actual_value > threshold

    if violated:
        return True, f"{description}超标: {actual_value:.2f}ms > {threshold}ms"
    return False, f"{description}正常: {actual_value:.2f}ms <= {threshold}ms"


__all__ = ["SLO", "ServiceLevelObjective", "check_slo_violation"]
