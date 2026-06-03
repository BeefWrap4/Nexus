"""A/B 实验模型.

Phase 6.4: Prompt A/B 实验 — 流量分流与指标聚合。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from nexus.db.database import Base
from nexus.models.types import JSONVariant, UUIDVariant


class PromptExperiment(Base):
    """Prompt A/B 实验表."""

    __tablename__ = "prompt_experiments"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUIDVariant, nullable=False)
    name = Column(String(255), nullable=False)
    template_id = Column(
        UUIDVariant, ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(20), default="running")  # running / paused / completed
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    variants = relationship(
        "PromptExperimentVariant",
        back_populates="experiment",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<PromptExperiment(id={self.id}, name={self.name}, status={self.status})>"


class PromptExperimentVariant(Base):
    """实验变体表."""

    __tablename__ = "prompt_experiment_variants"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    experiment_id = Column(
        UUIDVariant, ForeignKey("prompt_experiments.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(100), nullable=False)  # control / variant_a / variant_b
    template_version = Column(Integer, nullable=False)
    traffic_percentage = Column(Integer, nullable=False)  # 0-100

    # 汇总指标（后台任务更新）
    total_calls = Column(Integer, default=0)
    avg_latency_ms = Column(Integer, default=0)
    avg_tokens = Column(Integer, default=0)

    # Relationships
    experiment = relationship("PromptExperiment", back_populates="variants")

    def __repr__(self):
        return (
            f"<PromptExperimentVariant(exp={self.experiment_id}, "
            f"name={self.name}, version={self.template_version})>"
        )
