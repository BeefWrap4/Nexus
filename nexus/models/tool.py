"""工具注册模型 - MCP (Model Context Protocol) 兼容.

支持4种工具类型：
- http: HTTP API调用
- sql: SQL查询
- python: Python函数执行
- mcp: MCP Server集成
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from nexus.models.types import UUIDVariant
from nexus.models.types import JSONVariant
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class Tool(Base):
    """工具注册表."""

    __tablename__ = "tools"
    __table_args__ = (
        Index("ix_tools_tenant_status_type", "tenant_id", "status", "type"),
    )

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUIDVariant, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    description = Column(Text)
    type = Column(
        String(50), nullable=False
    )  # http / sql / python / mcp
    config = Column(JSONVariant, nullable=False)  # 工具配置
    schema = Column(JSONVariant)  # JSON Schema输入输出定义
    auth_config = Column(JSONVariant)  # 认证配置
    status = Column(String(20), default="active")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant = relationship("Tenant", back_populates="tools")

    def __repr__(self):
        return f"<Tool(id={self.id}, name={self.name}, type={self.type})>"
