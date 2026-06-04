"""Billing data models."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


class BillingPeriod(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass
class SubscriptionPlan:
    """订阅计划."""
    plan_id: str
    name: str
    price_usd: float
    period: BillingPeriod = BillingPeriod.MONTHLY

    # Quotas (None = unlimited)
    max_workflows: int = 100
    max_agents: int = 10
    max_llm_calls_per_day: int = 1000
    max_tokens_per_month: int = 1_000_000
    max_crew_executions: int = 50
    max_storage_gb: int = 1

    features: list[str] = field(default_factory=list)


@dataclass
class UsageRecord:
    """用量记录."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    metric: str = ""  # "llm_calls", "workflows", "tokens", "storage", etc.
    value: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tenant_id": self.tenant_id,
            "metric": self.metric, "value": self.value,
            "timestamp": self.timestamp.isoformat(),
        }
