"""Usage metering and quota enforcement."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from nexus.billing.models import SubscriptionPlan, UsageRecord, BillingPeriod
from nexus.billing.plans import PLANS

logger = logging.getLogger(__name__)


class UsageMeter:
    """用量追踪器 — 内存实现（生产应持久化到DB）."""

    def __init__(self):
        self._records: list[UsageRecord] = []
        self._tenant_plans: dict[str, str] = {}  # tenant_id → plan_id

    def set_plan(self, tenant_id: str, plan_id: str) -> None:
        """设置租户计划."""
        if plan_id not in PLANS:
            raise ValueError(f"Unknown plan: {plan_id}")
        self._tenant_plans[tenant_id] = plan_id

    def get_plan(self, tenant_id: str) -> SubscriptionPlan:
        """获取租户当前计划（默认免费）."""
        plan_id = self._tenant_plans.get(tenant_id, "free")
        return PLANS[plan_id]

    def record_usage(self, tenant_id: str, metric: str, value: float = 1.0) -> UsageRecord:
        """记录用量."""
        record = UsageRecord(tenant_id=tenant_id, metric=metric, value=value)
        self._records.append(record)
        return record

    def get_usage(self, tenant_id: str, metric: str,
                  since: datetime | None = None) -> float:
        """获取指定指标的累计用量."""
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=30)
        total = sum(
            r.value for r in self._records
            if r.tenant_id == tenant_id and r.metric == metric and r.timestamp >= since
        )
        return total

    def check_quota(self, tenant_id: str, metric: str,
                    current_usage: float | None = None) -> tuple[bool, str]:
        """检查配额是否超限.

        Returns:
            (ok, message) — ok=False 表示超限
        """
        plan = self.get_plan(tenant_id)

        quota_map = {
            "llm_calls": plan.max_llm_calls_per_day,
            "workflows": plan.max_workflows,
            "tokens": plan.max_tokens_per_month,
            "crew_executions": plan.max_crew_executions,
        }

        limit = quota_map.get(metric)
        if limit is None:
            return True, f"No quota for metric: {metric}"

        usage = current_usage if current_usage is not None else self.get_usage(tenant_id, metric)

        if usage >= limit:
            msg = f"Quota exceeded: {metric} ({usage}/{limit}) — upgrade to {self._next_tier_plan(tenant_id)}"
            return False, msg

        return True, f"OK: {usage}/{limit}"

    def _next_tier_plan(self, tenant_id: str) -> str:
        """获取下一级计划名称."""
        plan = self.get_plan(tenant_id)
        if plan.plan_id == "free":
            return "Professional ($49/mo)"
        elif plan.plan_id == "pro":
            return "Enterprise ($299/mo)"
        return "Contact sales"

    def get_usage_report(self, tenant_id: str) -> dict[str, Any]:
        """生成用量报告."""
        plan = self.get_plan(tenant_id)
        return {
            "tenant_id": tenant_id,
            "plan": plan.name,
            "price": f"${plan.price_usd}/mo",
            "usage": {
                "llm_calls_today": self.get_usage(tenant_id, "llm_calls",
                    since=datetime.now(timezone.utc) - timedelta(days=1)),
                "workflows_this_month": self.get_usage(tenant_id, "workflows"),
                "tokens_this_month": int(self.get_usage(tenant_id, "tokens")),
                "crew_executions": self.get_usage(tenant_id, "crew_executions"),
            },
            "limits": {
                "max_llm_calls_per_day": plan.max_llm_calls_per_day,
                "max_workflows": plan.max_workflows,
                "max_tokens_per_month": plan.max_tokens_per_month,
                "max_crew_executions": plan.max_crew_executions,
            },
        }
