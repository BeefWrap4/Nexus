"""Billing ORM models."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey

from nexus.db.database import Base
from nexus.models.types import UUIDVariant


class BillingSubscription(Base):
    """租户订阅记录."""
    __tablename__ = "billing_subscriptions"

    id = Column(UUIDVariant, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(UUIDVariant, ForeignKey("tenants.id"), nullable=False, index=True)
    plan_id = Column(String, nullable=False, default="free")
    status = Column(String, default="active")  # active/cancelled/expired
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)


class BillingUsageRecord(Base):
    """用量记录表."""
    __tablename__ = "billing_usage_records"

    id = Column(UUIDVariant, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(UUIDVariant, ForeignKey("tenants.id"), nullable=False, index=True)
    metric = Column(String, nullable=False)  # "llm_calls", "workflows", "tokens"
    value = Column(Float, default=1.0)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
