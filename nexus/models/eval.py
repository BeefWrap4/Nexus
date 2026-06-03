"""Eval 运行记录模型.

Phase 6.5: 评估框架 — 批量回归测试与 LLM-as-Judge。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text

from nexus.db.database import Base
from nexus.models.types import JSONVariant, UUIDVariant


class EvalRun(Base):
    """评估运行记录表."""

    __tablename__ = "eval_runs"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUIDVariant, nullable=False)
    name = Column(String(255), nullable=False)
    eval_type = Column(String(50))  # llm_judge / exact_match / regex / custom
    status = Column(String(20), default="pending")  # pending / running / completed
    dataset = Column(JSONVariant)  # [{"input": ..., "expected": ...}]
    results = Column(JSONVariant)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<EvalRun(id={self.id}, name={self.name}, status={self.status})>"
