"""审计日志和产物模型.

审计日志：完整操作追踪，满足合规要求（SOC2 / GDPR）
产物：工作流执行产生的输出文件
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class AuditLog(Base):
    """审计日志表."""

    __tablename__ = "audit_logs"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUIDVariant, ForeignKey("users.id"), nullable=True)
    resource_type = Column(
        String(50), nullable=False
    )  # workflow / agent / tool / run / hitl_task
    resource_id = Column(UUIDVariant, nullable=True)  # Was False; nullable for non-UUID paths (P2 fix)
    action = Column(
        String(50), nullable=False
    )  # create / update / delete / execute / approve
    payload = Column(JSONVariant)  # 变更内容
    ip_address = Column(String(45), nullable=True)  # IPv4/v6地址
    user_agent = Column(Text)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant")
    user = relationship("User")

    def __repr__(self):
        return (
            f"<AuditLog(resource={self.resource_type}, action={self.action}, "
            f"user={self.user_id})>"
        )


class Artifact(Base):
    """输出产物表."""

    __tablename__ = "artifacts"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    wf_run_id = Column(
        UUIDVariant, ForeignKey("wf_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(
        String(50), nullable=False
    )  # text / json / markdown / file / table
    content = Column(Text)  # 文本内容（小对象）
    file_path = Column(Text)  # S3/MinIO路径（大对象）
    mime_type = Column(String(100))
    size_bytes = Column(BigInteger)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant")
    wf_run = relationship("WorkflowRun")

    def __repr__(self):
        return f"<Artifact(id={self.id}, name={self.name}, type={self.type})>"
