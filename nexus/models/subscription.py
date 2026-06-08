"""Subscription model — links a tenant to a Stripe subscription."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from nexus.db.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_customer_id = Column(String(255), nullable=False, index=True)
    stripe_subscription_id = Column(String(255), nullable=True, index=True)
    plan = Column(String(50), nullable=False)  # free | pro | enterprise
    status = Column(String(50), nullable=False)  # active | trialing | past_due | canceled | unpaid
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(String(10), nullable=False, default="false")
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
