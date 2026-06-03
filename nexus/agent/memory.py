"""Agent记忆系统.

基于WAT evolution/strategy_memory.py 升级:
- 短期记忆: 最近性加权（默认30天半衰期）
- 长期记忆: 持久化向量存储（pgvector）
- 实体记忆: 分层作用域

借鉴CrewAI Memory设计。

增强（Phase 4）:
- 支持 pluggable backend（内存 / Redis）
- 跨进程/跨会话持久化
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from nexus.agent.memory_backend import (
    InMemoryBackend,
    MemoryBackend,
    MemoryEntry,
)


class AgentMemory:
    """Agent记忆系统.

    对应WAT evolution/strategy_memory.py。

    Phase 4 增强：支持 pluggable backend，默认 InMemoryBackend
    保持向后兼容（无 backend 参数时自动使用 InMemoryBackend）。
    """

    def __init__(
        self,
        agent_id: str = "",
        backend: MemoryBackend | None = None,
        short_term_limit: int = 50,
        long_term_enabled: bool = True,
    ):
        self.agent_id = agent_id or f"agent_{id(self)}"
        self.backend = backend or InMemoryBackend()
        self.short_term_limit = short_term_limit
        self.long_term_enabled = long_term_enabled

    async def save(
        self,
        task: Any,
        result: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """保存记忆（通过 backend 持久化）."""
        entry = MemoryEntry(
            entry_id=str(uuid.uuid4()),
            content=f"Task: {getattr(task, 'description', str(task))}\nResult: {result}",
            task_description=getattr(task, "description", str(task)),
            result=result,
            context=context or {},
            importance=self._calculate_importance(result),
        )
        await self.backend.save(self.agent_id, entry)

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """检索相关记忆（通过 backend 查询）."""
        entries = await self.backend.retrieve(self.agent_id, query, limit=limit)
        return [
            {
                "content": entry.content,
                "task": entry.task_description,
                "result": entry.result,
                "importance": entry.importance,
            }
            for entry in entries
        ]

    def _calculate_importance(self, result: str) -> float:
        """计算记忆重要性."""
        length_score = min(1.0, len(result) / 1000)
        return 0.5 + length_score * 0.5
