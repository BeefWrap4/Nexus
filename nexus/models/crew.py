"""Crew 多 Agent 协作配置模型.

Phase 10: 多 Agent 协作增强
- Crew: Crew 团队配置
- CrewAgent: Crew-Agent 多对多关联
- CrewRun: Crew 执行记录
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from nexus.db.database import Base
from nexus.models.types import JSONVariant, UUIDVariant


class Crew(Base):
    """Crew 团队配置表."""

    __tablename__ = "crews"
    __table_args__ = (
        Index("ix_crews_tenant_mode", "tenant_id", "mode"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    mode = Column(String(50), default="hierarchical")  # hierarchical|sequential|parallel
    config = Column(JSONVariant, default=dict)  # {max_workers, shared_context_enabled, auto_delegate}

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="crews")
    crew_agents = relationship(
        "CrewAgent",
        back_populates="crew",
        cascade="all, delete-orphan",
    )
    runs = relationship(
        "CrewRun",
        back_populates="crew",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Crew(id={self.id}, name={self.name}, mode={self.mode})>"


class CrewAgent(Base):
    """Crew-Agent 关联表（多对多）.

    记录每个 Crew 包含哪些 Agent，以及 Agent 在 Crew 中的角色和顺序。
    """

    __tablename__ = "crew_agents"

    crew_id = Column(
        UUIDVariant,
        ForeignKey("crews.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id = Column(
        UUIDVariant,
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_in_crew = Column(String(50), default="worker")  # manager|worker
    order_index = Column(Integer, default=0)  # 用于 sequential 模式排序

    # Relationships
    crew = relationship("Crew", back_populates="crew_agents")
    agent = relationship("Agent", back_populates="crew_memberships")

    def __repr__(self):
        return (
            f"<CrewAgent(crew_id={self.crew_id}, agent_id={self.agent_id}, "
            f"role={self.role_in_crew}, order={self.order_index})>"
        )


class CrewRun(Base):
    """Crew 执行记录表."""

    __tablename__ = "crew_runs"
    __table_args__ = (
        Index("ix_crew_runs_crew_status", "crew_id", "status"),
        Index("ix_crew_runs_tenant_status", "tenant_id", "status"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUIDVariant, ForeignKey("crews.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id = Column(UUIDVariant, nullable=False)
    status = Column(String(50), default="pending")  # pending|running|completed|failed
    input_task = Column(Text)
    output = Column(Text)
    worker_results = Column(JSONVariant, default=list)  # [CrewWorkerResult dict, ...]
    duration_ms = Column(Integer, default=0)

    started_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    crew = relationship("Crew", back_populates="runs")

    def __repr__(self):
        return (
            f"<CrewRun(id={self.id}, crew_id={self.crew_id}, "
            f"status={self.status}, duration={self.duration_ms}ms)>"
        )
