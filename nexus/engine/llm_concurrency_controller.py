"""LLM并发控制器 - 基于负载动态调整并发数.

根据系统负载、队列长度和延迟指标，动态调整LLM调用的并发限制，
以优化吞吐量同时避免过载。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from nexus.config.slo import SLO

logger = logging.getLogger(__name__)


@dataclass
class LoadMetrics:
    """系统负载指标."""

    active_requests: int = 0
    """当前活跃的LLM请求数"""

    queued_requests: int = 0
    """排队等待的请求数"""

    avg_latency_ms: float = 0.0
    """平均延迟（毫秒）"""

    p95_latency_ms: float = 0.0
    """P95延迟（毫秒）"""

    error_rate: float = 0.0
    """错误率（0-1）"""

    cpu_usage: float = 0.0
    """CPU使用率（0-100）"""

    memory_usage: float = 0.0
    """内存使用率（0-100）"""


class AdaptiveConcurrencyController:
    """自适应并发控制器.

    基于负载指标动态调整Semaphore的大小，实现：
    1. 低负载时提高并发数以增加吞吐量
    2. 高负载时降低并发数以避免过载
    3. 错误率高时快速降级
    """

    def __init__(
        self,
        min_concurrency: int = 5,
        max_concurrency: int = SLO.MAX_CONCURRENT_LLM_CALLS,
        initial_concurrency: int = 10,
        adjustment_interval: float = 5.0,
    ):
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.current_concurrency = initial_concurrency
        self.adjustment_interval = adjustment_interval

        # Semaphore用于控制并发
        self._semaphore = asyncio.Semaphore(initial_concurrency)

        # 负载指标历史
        self._metrics_history: list[LoadMetrics] = []
        self._last_adjustment_time = time.time()

        # 调整锁，防止并发调整
        self._adjustment_lock = asyncio.Lock()

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """获取当前的Semaphore."""
        return self._semaphore

    async def update_metrics(self, metrics: LoadMetrics):
        """更新负载指标并可能触发并发调整.

        Args:
            metrics: 当前负载指标
        """
        self._metrics_history.append(metrics)

        # 保留最近60秒的指标
        cutoff_time = time.time() - 60
        self._metrics_history = [
            m for m in self._metrics_history
            if hasattr(m, '_timestamp') and m._timestamp > cutoff_time  # type: ignore
        ]

        # 检查是否需要调整
        current_time = time.time()
        if current_time - self._last_adjustment_time >= self.adjustment_interval:
            await self._maybe_adjust_concurrency(metrics)
            self._last_adjustment_time = current_time

    async def _maybe_adjust_concurrency(self, metrics: LoadMetrics):
        """根据当前负载决定是否调整并发数.

        调整策略：
        1. 如果错误率 > 10%，立即降低并发到最小值
        2. 如果P95延迟 > SLO阈值 * 2，降低并发
        3. 如果CPU/内存使用率 > 80%，降低并发
        4. 如果各项指标良好且队列长度 > 0，提高并发
        """
        async with self._adjustment_lock:
            old_concurrency = self.current_concurrency
            new_concurrency = old_concurrency

            # 规则1：错误率过高，紧急降级
            if metrics.error_rate > 0.10:
                new_concurrency = self.min_concurrency
                logger.warning(
                    f"错误率过高 ({metrics.error_rate * 100:.1f}%)，"
                    f"降低并发到 {new_concurrency}"
                )

            # 规则2：延迟超标
            elif metrics.p95_latency_ms > SLO.LLM_CALL_P95_LATENCY_MS * 2:
                # 延迟严重超标，大幅降低
                reduction_factor = 0.5
                new_concurrency = max(
                    self.min_concurrency,
                    int(old_concurrency * reduction_factor),
                )
                logger.info(
                    f"P95延迟超标 ({metrics.p95_latency_ms:.0f}ms > "
                    f"{SLO.LLM_CALL_P95_LATENCY_MS * 2:.0f}ms)，"
                    f"降低并发: {old_concurrency} -> {new_concurrency}"
                )

            # 规则3：资源使用率过高
            elif (
                metrics.cpu_usage > SLO.CPU_USAGE_THRESHOLD
                or metrics.memory_usage > SLO.MEMORY_USAGE_THRESHOLD
            ):
                reduction_factor = 0.7
                new_concurrency = max(
                    self.min_concurrency,
                    int(old_concurrency * reduction_factor),
                )
                logger.info(
                    f"资源使用率过高 (CPU: {metrics.cpu_usage:.1f}%, "
                    f"Memory: {metrics.memory_usage:.1f}%)，"
                    f"降低并发: {old_concurrency} -> {new_concurrency}"
                )

            # 规则4：负载较低且有排队请求，提高并发
            elif (
                metrics.p95_latency_ms < SLO.LLM_CALL_P95_LATENCY_MS * 0.5
                and metrics.error_rate < 0.02
                and metrics.queued_requests > 0
                and metrics.cpu_usage < SLO.CPU_USAGE_THRESHOLD * 0.7
            ):
                increase_step = min(5, self.max_concurrency - old_concurrency)
                new_concurrency = old_concurrency + increase_step
                logger.info(
                    f"负载较低且有排队请求，提高并发: "
                    f"{old_concurrency} -> {new_concurrency}"
                )

            # 应用调整
            if new_concurrency != old_concurrency:
                await self._adjust_semaphore(new_concurrency)

    async def _adjust_semaphore(self, new_concurrency: int):
        """调整Semaphore大小.

        注意：asyncio.Semaphore不支持动态调整大小，
        所以需要创建新的Semaphore并迁移状态。
        """
        # 获取当前可用的permits数量
        # 由于无法直接获取，我们简单地创建新的Semaphore
        old_semaphore = self._semaphore
        self._semaphore = asyncio.Semaphore(new_concurrency)
        self.current_concurrency = new_concurrency

        logger.debug(f"Semaphore已调整: {new_concurrency}")

    def get_stats(self) -> dict:
        """获取控制器统计信息."""
        return {
            "current_concurrency": self.current_concurrency,
            "min_concurrency": self.min_concurrency,
            "max_concurrency": self.max_concurrency,
            "metrics_history_count": len(self._metrics_history),
        }


# 全局并发控制器实例
_global_controller: Optional[AdaptiveConcurrencyController] = None


def get_concurrency_controller() -> AdaptiveConcurrencyController:
    """获取全局并发控制器."""
    global _global_controller
    if _global_controller is None:
        _global_controller = AdaptiveConcurrencyController()
    return _global_controller


def reset_concurrency_controller():
    """重置全局并发控制器（用于测试）."""
    global _global_controller
    _global_controller = None
