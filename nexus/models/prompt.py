"""Prompt 模板模型.

Phase 6.2: Prompt Engineering Platform — 模板定义与版本管理。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from nexus.db.database import Base
from nexus.models.types import JSONVariant, UUIDVariant


class PromptTemplate(Base):
    """Prompt 模板定义表."""

    __tablename__ = "prompt_templates"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    template_type = Column(String(50), default="system")  # system / user / composite
    current_version = Column(Integer, default=1)
    created_by = Column(UUIDVariant, ForeignKey("users.id"))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    versions = relationship(
        "PromptTemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PromptTemplateVersion.version.desc()",
    )

    def __repr__(self):
        return f"<PromptTemplate(id={self.id}, name={self.name}, v={self.current_version})>"


class PromptTemplateVersion(Base):
    """Prompt 模板版本历史表 — 不可变快照."""

    __tablename__ = "prompt_template_versions"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    template_id = Column(
        UUIDVariant,
        ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)  # Jinja2 模板内容
    variables = Column(JSONVariant, default=list)  # ["name", "language"]
    change_notes = Column(Text)
    created_by = Column(UUIDVariant, ForeignKey("users.id"))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    template = relationship("PromptTemplate", back_populates="versions")

    def __repr__(self):
        return f"<PromptTemplateVersion(template={self.template_id}, v={self.version})>"
