"""Invoice model — Stripe invoice mirror (for the billing dashboard)."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from nexus.db.database import Base


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    stripe_invoice_id = Column(String(255), nullable=True, index=True)
    amount_due_cents = Column(Integer, nullable=False)
    amount_paid_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(10), nullable=False, default="usd")
    status = Column(String(50), nullable=False)  # draft | open | paid | uncollectible | void
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
