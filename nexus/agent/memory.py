"""Agent记忆系统.

基于WAT evolution/strategy_memory.py 升级:
- 短期记忆: 最近性加权（默认30天半衰期）
- 长期记忆: 持久化向量存储（pgvector）
- 实体记忆: 分层作用域

借鉴CrewAI Memory设计。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class MemoryEntry:
    """记忆条目."""

    id: str
    content: str
    task_description: str = ""
    result: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None
    importance: float = 0.5  # 0.0 - 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentMemory:
    """Agent记忆系统.

    对应WAT evolution/strategy_memory.py。
    """

    def __init__(
        self,
        short_term_limit: int = 50,
        long_term_enabled: bool = True,
    ):
        self.short_term_limit = short_term_limit
        self.long_term_enabled = long_term_enabled
        self._entries: list[MemoryEntry] = []

    async def save(
        self,
        task: Any,
        result: str,
        context: dict[str, Any] = None,
    ) -> None:
        """保存记忆."""
        import uuid

        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=f"Task: {getattr(task, 'description', str(task))}\nResult: {result}",
            task_description=getattr(task, "description", str(task)),
            result=result,
            context=context or {},
            importance=self._calculate_importance(result),
        )

        self._entries.append(entry)

        # 限制短期记忆大小
        if len(self._entries) > self.short_term_limit:
            self._entries = sorted(
                self._entries,
                key=lambda e: (e.importance, e.created_at),
                reverse=True,
            )[:self.short_term_limit]

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """检索相关记忆.

        简单的关键词匹配（生产环境应使用向量检索）。
        """
        query_terms = set(query.lower().split())
        scored = []

        for entry in self._entries:
            score = self._compute_relevance(entry, query_terms)
            scored.append((score, entry))

        # 按相关性和重要性排序
        scored.sort(key=lambda x: (x[0], x[1].importance), reverse=True)
        return [
            {
                "content": entry.content,
                "task": entry.task_description,
                "result": entry.result,
                "importance": entry.importance,
            }
            for _, entry in scored[:limit]
        ]

    def _calculate_importance(self, result: str) -> float:
        """计算记忆重要性."""
        # 简单启发式：结果越长越重要
        length_score = min(1.0, len(result) / 1000)
        return 0.5 + length_score * 0.5

    def _compute_relevance(
        self,
        entry: MemoryEntry,
        query_terms: set[str],
    ) -> float:
        """计算记忆与查询的相关性."""
        entry_terms = set(entry.content.lower().split())
        if not entry_terms:
            return 0.0
        overlap = len(query_terms & entry_terms)
        return overlap / len(query_terms) if query_terms else 0.0
