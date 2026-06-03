"""LLM 调用追踪记录模型.

Phase 6.1: LLM Trace 系统 — 持久化每次 LLM 调用的完整上下文。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from nexus.db.database import Base
from nexus.models.types import JSONVariant, UUIDVariant


class LLMCallTrace(Base):
    """LLM 调用追踪记录表.

    记录每次 LLM 调用的：
    - 输入：system_prompt, user_prompt
    - 输出：response_content, response_reasoning, tool_calls
    - 用量：prompt_tokens, completion_tokens, total_tokens
    - 性能：latency_ms, retry_count, fallback_model
    - 上下文：run_id, node_id, agent_id, experiment_id
    """

    __tablename__ = "llm_call_traces"

    id = Column(UUIDVariant, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUIDVariant, nullable=False)
    run_id = Column(
        UUIDVariant, ForeignKey("wf_runs.id", ondelete="SET NULL"), nullable=True
    )
    node_id = Column(String(100), nullable=True)
    agent_id = Column(String(100), nullable=True)
    experiment_id = Column(UUIDVariant, nullable=True)

    # 调用详情
    model = Column(String(100), nullable=False)
    provider = Column(String(50))
    system_prompt = Column(Text)
    user_prompt = Column(Text)
    response_content = Column(Text)
    response_reasoning = Column(Text)
    tool_calls = Column(JSONVariant, default=list)

    # 用量与耗时
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    fallback_model = Column(String(100))
    cache_hit = Column(Boolean, default=False)

    # 原始响应（可选，用于调试）
    raw_response = Column(JSONVariant)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return (
            f"<LLMCallTrace(id={self.id}, model={self.model}, "
            f"latency={self.latency_ms}ms, tokens={self.total_tokens})>"
        )
