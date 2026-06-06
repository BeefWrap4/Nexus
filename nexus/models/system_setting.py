"""System Setting 模型 — KV 形式的租户级设置.

修复 (P1 收尾): 之前的 /api/v1/settings/{general,llm,security} 是 stub,
只 log 不入库。需要一个 KV 表存租户级配置, 让前端保存的设置真的持久化。

设计:
  - 主键 (tenant_id, key) — 每个租户可以有同名 key
  - value JSONB — 任意结构 (前端发 Record<string, any>)
  - category VARCHAR — 'general' / 'llm' / 'security' / 未来扩展
  - updated_at + updated_by (user_id) — 审计
  - 索引 (tenant_id, category) — 按 category 列快

注: tenants.id / users.id 在 DB 是 varchar(36) 不是 UUID, 所以
tenant_id / updated_by 用 String(36) 跟其它表一致 (api_keys / wf_runs)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from nexus.db.database import Base


class SystemSetting(Base):
    """系统设置 KV 表 — 租户级."""

    __tablename__ = "system_settings"

    tenant_id = Column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True, nullable=False,
    )
    key = Column(String(255), primary_key=True, nullable=False)
    value = Column(JSONB, nullable=False)
    category = Column(String(50), nullable=False, default="general")
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationship
    tenant = relationship("Tenant")

    __table_args__ = (
        Index("ix_system_settings_tenant_category", "tenant_id", "category"),
    )

    def __repr__(self):
        return f"<SystemSetting(tenant={self.tenant_id}, key={self.key}, cat={self.category})>"
