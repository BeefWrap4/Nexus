"""工作流模型 - 对应WAT的GameConfig泛化.

核心概念：
- Workflow: 工作流定义（静态配置）
- WorkflowVersion: 版本历史（不可变快照）
- WorkflowRun: 执行实例（动态状态）
- NodeRun: 节点执行记录
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class Workflow(Base):
    """工作流定义表."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_tenant_status", "tenant_id", "status"),
        Index("ix_workflows_tenant_name", "tenant_id", "name"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by = Column(
        UUIDVariant, ForeignKey("users.id"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(20), default="draft")  # draft / active / archived
    config = Column(JSONVariant, nullable=False)  # DAG定义: nodes + edges
    variables = Column(JSONVariant, default=dict)  # 环境变量定义
    tags = Column(JSONVariant, default=list)
    current_version = Column(Integer, default=1)
    run_count = Column(Integer, default=0)
    schedule_cron = Column(String(100), nullable=True)  # Cron 表达式，如 "0 9 * * *"
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="workflows")
    versions = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version.desc()",
    )
    runs = relationship(
        "WorkflowRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowRun.created_at.desc()",
    )

    def __repr__(self):
        return f"<Workflow(id={self.id}, name={self.name}, status={self.status})>"


class WorkflowVersion(Base):
    """工作流版本历史表 - 不可变快照."""

    __tablename__ = "wf_versions"
    __table_args__ = (
        Index("ix_wf_versions_workflow_version", "workflow_id", "version", unique=True),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        UUIDVariant,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    config = Column(JSONVariant, nullable=False)  # 完整工作流配置快照
    change_notes = Column(Text)
    created_by = Column(UUIDVariant, ForeignKey("users.id"), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    workflow = relationship("Workflow", back_populates="versions")

    def __repr__(self):
        return f"<WorkflowVersion(workflow={self.workflow_id}, v={self.version})>"


class WorkflowRun(Base):
    """工作流执行实例表 - 对应WAT的GameState持久化."""

    __tablename__ = "wf_runs"
    __table_args__ = (
        Index("ix_wf_runs_tenant_status", "tenant_id", "status"),
        Index("ix_wf_runs_workflow_created", "workflow_id", "created_at"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id = Column(
        UUIDVariant, ForeignKey("workflows.id"), nullable=True
    )
    version = Column(Integer, nullable=False)
    status = Column(
        String(30), default="pending"
    )  # pending / running / paused / completed / failed / cancelled
    trigger_type = Column(String(50))  # api / webhook / schedule / manual
    trigger_payload = Column(JSONVariant)
    state = Column(JSONVariant)  # 当前执行状态（Checkpoint）
    result = Column(JSONVariant)  # 执行结果
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant")
    workflow = relationship("Workflow", back_populates="runs")
    node_runs = relationship(
        "NodeRun",
        back_populates="wf_run",
        cascade="all, delete-orphan",
        order_by="NodeRun.created_at",
    )
    hitl_tasks = relationship(
        "HITLTask", back_populates="wf_run", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<WorkflowRun(id={self.id}, status={self.status})>"


class NodeRun(Base):
    """节点执行记录表 - 对应WAT的GameEvent持久化."""

    __tablename__ = "node_runs"
    __table_args__ = (
        Index("ix_node_runs_wf_run_node", "wf_run_id", "node_id"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    wf_run_id = Column(
        UUIDVariant, ForeignKey("wf_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id = Column(String(100), nullable=False)
    node_type = Column(
        String(50), nullable=False
    )  # agent / tool / hitl / condition / start / end / parallel / loop / delay
    status = Column(
        String(30), default="pending"
    )  # pending / running / succeeded / failed / skipped
    input_data = Column("input", JSONVariant)
    output_data = Column("output", JSONVariant)
    error = Column(JSONVariant)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    wf_run = relationship("WorkflowRun", back_populates="node_runs")

    def __repr__(self):
        return f"<NodeRun(run={self.wf_run_id}, node={self.node_id}, type={self.node_type})>"


class CheckpointRecord(Base):
    """检查点记录表 - 用于状态恢复和分叉."""

    __tablename__ = "checkpoints"

    id = Column(String(100), primary_key=True)
    run_id = Column(
        UUIDVariant, ForeignKey("wf_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id = Column(String(100))
    state_data = Column(JSONVariant)  # WorkflowState JSON（小状态）
    state_s3_key = Column(Text)  # S3 路径（大状态）
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<CheckpointRecord(id={self.id}, run={self.run_id}, node={self.node_id})>"


class DeadLetterJob(Base):
    """死信队列记录表 - 用于失败任务的人工排查和重试."""

    __tablename__ = "dead_letter_jobs"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    run_id = Column(UUIDVariant, nullable=False)
    workflow_id = Column(UUIDVariant)
    tenant_id = Column(UUIDVariant, nullable=False)
    error_type = Column(String(100))
    error_message = Column(Text)
    traceback = Column(Text)
    payload = Column(JSONVariant)  # 原始任务参数
    retry_count = Column(Integer, default=0)
    status = Column(String(20), default="failed")  # failed / retried / discarded
    failed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    retried_at = Column(DateTime(timezone=True))

    def __repr__(self):
        return f"<DeadLetterJob(id={self.id}, run={self.run_id}, status={self.status})>"
