"""Agent 记忆后端 — 支持内存和 Redis 持久化.

设计模式：Strategy Pattern
- MemoryBackend: 抽象接口
- InMemoryBackend: 默认内存存储（向后兼容）
- RedisBackend: Redis 持久化（生产推荐）

存储格式（Redis）:
    Hash key: nexus:memory:{agent_id}
    Field: {entry_id}
    Value: JSON serialized MemoryEntry
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()


class MemoryEntry:
    """记忆条目（可 JSON 序列化）."""

    def __init__(
        self,
        entry_id: str,
        content: str,
        task_description: str = "",
        result: str = "",
        context: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        importance: float = 0.5,
        created_at: datetime | None = None,
    ):
        self.id = entry_id
        self.content = content
        self.task_description = task_description
        self.result = result
        self.context = context or {}
        self.embedding = embedding
        self.importance = importance
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典."""
        return {
            "id": self.id,
            "content": self.content,
            "task_description": self.task_description,
            "result": self.result,
            "context": self.context,
            "embedding": self.embedding,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        """从字典反序列化."""
        created_at = None
        if "created_at" in data and data["created_at"]:
            try:
                created_at = datetime.fromisoformat(data["created_at"])
            except ValueError:
                pass
        return cls(
            entry_id=data.get("id", ""),
            content=data.get("content", ""),
            task_description=data.get("task_description", ""),
            result=data.get("result", ""),
            context=data.get("context", {}),
            embedding=data.get("embedding"),
            importance=data.get("importance", 0.5),
            created_at=created_at,
        )


class MemoryBackend(ABC):
    """记忆后端抽象接口."""

    @abstractmethod
    async def save(self, agent_id: str, entry: MemoryEntry) -> None:
        """保存记忆条目."""

    @abstractmethod
    async def retrieve(
        self, agent_id: str, query: str, limit: int = 5
    ) -> list[MemoryEntry]:
        """检索相关记忆条目."""

    @abstractmethod
    async def clear(self, agent_id: str) -> None:
        """清除指定 Agent 的所有记忆."""


class InMemoryBackend(MemoryBackend):
    """内存后端 — 默认实现，向后兼容.

    使用类级字典存储，同一进程内所有 Agent 实例共享。
    """

    _store: dict[str, list[MemoryEntry]] = {}

    async def save(self, agent_id: str, entry: MemoryEntry) -> None:
        if agent_id not in self._store:
            self._store[agent_id] = []
        self._store[agent_id].append(entry)

    async def retrieve(
        self, agent_id: str, query: str, limit: int = 5
    ) -> list[MemoryEntry]:
        entries = self._store.get(agent_id, [])
        # 简单关键词匹配排序
        query_terms = set(query.lower().split())
        scored = []
        for entry in entries:
            score = _keyword_relevance(entry, query_terms)
            scored.append((score, entry))
        scored.sort(key=lambda x: (x[0], x[1].importance), reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def clear(self, agent_id: str) -> None:
        self._store.pop(agent_id, None)


class RedisBackend(MemoryBackend):
    """Redis 持久化后端 — 生产推荐.

    使用 Redis Hash 存储，每个 Agent 一个 Hash：
        key: nexus:memory:{agent_id}
        field: {entry_id}
        value: JSON serialized MemoryEntry

    优点：
    - 跨进程共享（API 进程写入，Worker 进程读取）
    - Worker 重启不丢失
    - 支持 TTL 自动过期
    """

    def __init__(self, redis_client, ttl_seconds: int = 86400 * 30):
        self.redis = redis_client
        self.ttl = ttl_seconds
        self._key_prefix = "nexus:memory"

    def _hash_key(self, agent_id: str) -> str:
        return f"{self._key_prefix}:{agent_id}"

    async def save(self, agent_id: str, entry: MemoryEntry) -> None:
        key = self._hash_key(agent_id)
        await self.redis.hset(key, entry.id, json.dumps(entry.to_dict()))
        # 设置 TTL（如果首次创建）
        await self.redis.expire(key, self.ttl)
        logger.debug("memory_saved", agent_id=agent_id, entry_id=entry.id)

    async def retrieve(
        self, agent_id: str, query: str, limit: int = 5
    ) -> list[MemoryEntry]:
        key = self._hash_key(agent_id)
        raw_entries = await self.redis.hgetall(key)
        if not raw_entries:
            return []

        entries = []
        for entry_json in raw_entries.values():
            try:
                data = json.loads(entry_json)
                entries.append(MemoryEntry.from_dict(data))
            except (json.JSONDecodeError, TypeError):
                continue

        # 简单关键词匹配排序（未来可升级为向量检索）
        query_terms = set(query.lower().split())
        scored = []
        for entry in entries:
            score = _keyword_relevance(entry, query_terms)
            scored.append((score, entry))
        scored.sort(key=lambda x: (x[0], x[1].importance), reverse=True)
        return [entry for _, entry in scored[:limit]]

    async def clear(self, agent_id: str) -> None:
        key = self._hash_key(agent_id)
        await self.redis.delete(key)
        logger.info("memory_cleared", agent_id=agent_id)


def _keyword_relevance(entry: MemoryEntry, query_terms: set[str]) -> float:
    """计算关键词相关性分数."""
    entry_text = f"{entry.content} {entry.task_description} {entry.result}".lower()
    entry_terms = set(entry_text.split())
    if not entry_terms or not query_terms:
        return 0.0
    overlap = len(query_terms & entry_terms)
    return overlap / len(query_terms)


def create_memory_backend(backend_type: str, redis_client=None) -> MemoryBackend:
    """工厂函数：根据配置创建记忆后端.

    Args:
        backend_type: "memory" 或 "redis"
        redis_client: Redis 客户端（backend_type="redis" 时必需）

    Returns:
        MemoryBackend 实例

    Raises:
        ValueError: 不支持的 backend_type
    """
    if backend_type == "memory":
        return InMemoryBackend()
    elif backend_type == "redis":
        if redis_client is None:
            raise ValueError("redis_client is required for redis backend")
        return RedisBackend(redis_client)
    else:
        raise ValueError(f"Unsupported memory backend: {backend_type}")
