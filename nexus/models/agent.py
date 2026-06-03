"""Agent配置模型 - 基于WAT BaseAgent泛化.

CrewAI-style Role-Playing设计:
- role: 角色描述（如"数据分析师"）
- goal: 目标（如"从销售数据中提取关键洞察"）
- backstory: 背景/个性（塑造Agent行为风格）
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class Agent(Base):
    """Agent配置表."""

    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_tenant_name", "tenant_id", "name"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    role = Column(String(255))  # 角色描述
    goal = Column(Text)  # 目标
    backstory = Column(Text)  # 背景/个性
    llm_settings = Column(JSONVariant, nullable=False)  # {provider, model, temperature, max_tokens}
    system_prompt = Column(Text)
    system_prompt_template_id = Column(
        UUIDVariant, ForeignKey("prompt_templates.id"), nullable=True
    )
    tools = Column(JSONVariant, default=list)  # 可用工具列表
    memory_config = Column(JSONVariant, default=dict)  # 记忆配置
    max_iterations = Column(Integer, default=10)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="agents")
    crew_memberships = relationship(
        "CrewAgent",
        back_populates="agent",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, role={self.role})>"
