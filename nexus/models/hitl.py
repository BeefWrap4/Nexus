"""人工审批任务模型 - Human-in-the-Loop.

审批类型：
- approve: 通过/拒绝二选一
- select: 多选一
- input: 补充信息
- correct: 纠错修正
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class HITLTask(Base):
    """人工审批任务表."""

    __tablename__ = "hitl_tasks"
    __table_args__ = (
        Index("ix_hitl_tasks_tenant_status", "tenant_id", "status"),
        Index("ix_hitl_tasks_wf_run_status", "wf_run_id", "status"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    wf_run_id = Column(
        UUIDVariant, ForeignKey("wf_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id = Column(String(100), nullable=False)
    assignee_id = Column(
        UUIDVariant, ForeignKey("users.id"), nullable=True
    )
    task_type = Column(
        String(50), nullable=False
    )  # approve / select / input / correct
    title = Column(String(500), nullable=False)
    description = Column(Text)
    context = Column(JSONVariant)  # 审批上下文
    response = Column(JSONVariant)  # 审批响应
    status = Column(
        String(20), default="pending"
    )  # pending / approved / rejected / timeout
    deadline = Column(DateTime(timezone=True))
    responded_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant")
    wf_run = relationship("WorkflowRun", back_populates="hitl_tasks")
    assignee = relationship(
        "User", back_populates="hitl_tasks", foreign_keys=[assignee_id]
    )

    def __repr__(self):
        return (
            f"<HITLTask(id={self.id}, type={self.task_type}, status={self.status})>"
        )
