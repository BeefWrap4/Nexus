"""租户、用户和认证模型.

多租户设计：
- 每个表都包含 tenant_id 字段
- PostgreSQL Row-Level Security (RLS) 实现数据隔离
- 用户属于特定租户
- API Key用于程序化访问
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class Tenant(Base):
    """租户表 - SaaS多租户的核心."""

    __tablename__ = "tenants"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), default="free")  # free / pro / enterprise
    config = Column(JSONVariant, default=dict)
    status = Column(String(20), default="active")  # active / suspended / deleted
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    workflows = relationship(
        "Workflow", back_populates="tenant", cascade="all, delete-orphan"
    )
    agents = relationship(
        "Agent", back_populates="tenant", cascade="all, delete-orphan"
    )
    tools = relationship(
        "Tool", back_populates="tenant", cascade="all, delete-orphan"
    )
    crews = relationship(
        "Crew", back_populates="tenant", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name}, slug={self.slug})>"


class User(Base):
    """用户表."""

    __tablename__ = "users"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email = Column(String(255), nullable=False)
    name = Column(String(255))
    role = Column(String(50), default="member")  # admin / member / viewer
    avatar_url = Column(Text)
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Unique constraint: email per tenant
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_email"),)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    api_keys = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )
    hitl_tasks = relationship(
        "HITLTask", back_populates="assignee", foreign_keys="HITLTask.assignee_id"
    )

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class APIKey(Base):
    """API密钥表 - 用于程序化访问."""

    __tablename__ = "api_keys"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUIDVariant, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False)
    key_prefix = Column(String(20), nullable=False)
    permissions = Column(JSONVariant, default=list)  # ["workflows:read", "runs:write", ...]
    rate_limit = Column(Integer, default=1000)  # requests per minute
    rate_window = Column(Integer, default=60)  # rate limit window in seconds
    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    revoked_at = Column(DateTime(timezone=True))

    # Relationships
    tenant = relationship("Tenant")
    user = relationship("User", back_populates="api_keys")

    def __repr__(self):
        return f"<APIKey(id={self.id}, name={self.name}, prefix={self.key_prefix})>"
