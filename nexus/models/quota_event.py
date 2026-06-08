"""Quota event model — records each quota consumption for billing + analytics."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Index
from nexus.db.database import Base


class QuotaEvent(Base):
    __tablename__ = "quota_events"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    metric = Column(String(50), nullable=False)  # tokens | api_calls | storage_bytes
    quantity = Column(Integer, nullable=False)
    resource_id = Column(String(36), nullable=True)  # workflow_id, run_id, etc.
    source = Column(String(50), nullable=False)  # llm | tool | storage
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_quota_tenant_metric_created", "tenant_id", "metric", "created_at"),
    )
