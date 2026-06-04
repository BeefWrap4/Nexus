"""向量语义检索记忆后端.

基于 WAT evolution 的 Memory 系统升级：
- EmbeddingService: 文本转向量服务（支持 mock / sentence_transformers / HTTP 后端）
- VectorMemoryBackend: 使用 cosine similarity 进行语义检索的记忆后端

设计模式：Strategy Pattern (EmbeddingService) + Template Method (VectorMemoryBackend)
继承自 MemoryBackend 抽象接口，保持向后兼容。
"""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING

import structlog

from nexus.agent.memory_backend import MemoryBackend, MemoryEntry

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger()


class EmbeddingService:
    """文本转向量服务.

    支持多种后端：
    - "mock" — 测试用，基于文本 hash 产生确定性归一化向量
    - "sentence_transformers" — 本地模型（默认：BAAI/bge-small-zh-v1.5）
    - "http" — HTTP API（如 Smart Cache / Ollama / 兼容 OpenAI embeddings 接口）
    """

    def __init__(
        self,
        backend: str = "mock",
        model_name: str = "BAAI/bge-small-zh-v1.5",
        http_url: str | None = None,
        http_api_key: str | None = None,
        dim: int = 384,
    ):
        self.backend = backend
        self.model_name = model_name
        self.http_url = http_url
        self.http_api_key = http_api_key
        self.dim = dim
        self._model = None

    async def embed(self, text: str) -> list[float]:
        """将文本转换为向量."""
        if self.backend == "mock":
            return self._mock_embed(text)
        elif self.backend == "sentence_transformers":
            return await self._st_embed(text)
        elif self.backend == "http":
            return await self._http_embed(text)
        else:
            raise ValueError(f"Unknown embedding backend: {self.backend}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量转向量."""
        return [await self.embed(t) for t in texts]

    def _mock_embed(self, text: str) -> list[float]:
        """Mock: 基于文本 hash 产生确定性归一化向量.

        使用 SHA-256 哈希作为随机种子，生成在 [-1, 1] 范围内
        均匀分布的向量，然后做 L2 归一化。相同输入始终产生相同向量。
        """
        h = hashlib.sha256(text.encode("utf-8"))
        seed = int(h.hexdigest()[:16], 16)
        rng = random.Random(seed)
        vec = [rng.uniform(-1, 1) for _ in range(self.dim)]
        # L2 归一化
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    async def _st_embed(self, text: str) -> list[float]:
        """使用 sentence-transformers 本地模型编码.

        Lazy-load 模型，首次调用时初始化。
        """
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                logger.info(
                    "embedding_model_loaded",
                    model=self.model_name,
                    backend="sentence_transformers",
                )
            except ImportError:
                raise ImportError(
                    "sentence-transformers is not installed. "
                    "Install with: pip install sentence-transformers"
                )
            except Exception as e:
                logger.error("embedding_model_load_failed", error=str(e))
                raise

        import asyncio

        embedding = await asyncio.to_thread(self._model.encode, text, normalize_embeddings=True)
        return embedding.tolist()

    async def _http_embed(self, text: str) -> list[float]:
        """通过 HTTP API 获取向量（兼容 OpenAI embeddings 格式）.

        支持的 API 格式：
        - OpenAI /v1/embeddings
        - Ollama /api/embeddings
        - Smart Cache 自定义接口
        """
        import json

        import aiohttp

        if not self.http_url:
            raise ValueError("http_url is required for HTTP embedding backend")

        headers = {"Content-Type": "application/json"}
        if self.http_api_key:
            headers["Authorization"] = f"Bearer {self.http_api_key}"

        # 尝试 OpenAI 兼容格式
        payload = {
            "input": text,
            "model": self.model_name,
        }

        try:
            async with aiohttp.ClientSession() as session:
                # 自动处理 URL 末尾斜杠
                url = self.http_url.rstrip("/")
                async with session.post(
                    f"{url}/v1/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["data"][0]["embedding"]
                    elif resp.status == 404:
                        # 尝试 Ollama 格式
                        pass
                    else:
                        body = await resp.text()
                        logger.warning(
                            "http_embed_failed",
                            status=resp.status,
                            body=body[:500],
                        )

                # 回退：尝试 Ollama 格式
                ollama_payload = {
                    "model": self.model_name,
                    "prompt": text,
                }
                async with session.post(
                    f"{url}/api/embeddings",
                    headers=headers,
                    json=ollama_payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["embedding"]
                    else:
                        body = await resp.text()
                        raise RuntimeError(
                            f"HTTP embedding failed: status={resp.status}, body={body[:500]}"
                        )
        except aiohttp.ClientError as e:
            logger.error("http_embed_connection_error", error=str(e))
            raise


class VectorMemoryBackend(MemoryBackend):
    """向量语义检索后端.

    使用 cosine similarity 进行记忆检索，配合 EmbeddingService
    将文本转为向量。

    特性：
    - 内存存储 + 可选 Redis 持久化
    - Cosine similarity 语义匹配
    - 结果按相似度 × 重要性加权排序
    - 确定性 mock embedding（测试友好）
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        redis_client=None,
    ):
        self._store: dict[str, list[MemoryEntry]] = {}  # agent_id -> entries
        self.embeddings: dict[str, list[list[float]]] = {}  # agent_id -> vectors
        self.embed = embedding_service
        self.redis = redis_client

    async def save(self, agent_id: str, entry: MemoryEntry) -> None:
        """保存记忆条目并计算 embedding."""
        # 计算 embedding（如果尚未设置）
        if entry.embedding is None:
            entry.embedding = await self.embed.embed(entry.content)

        if agent_id not in self._store:
            self._store[agent_id] = []
            self.embeddings[agent_id] = []

        self._store[agent_id].append(entry)
        self.embeddings[agent_id].append(entry.embedding)

        # 可选 Redis 持久化
        if self.redis is not None:
            import json

            key = f"nexus:vecmem:{agent_id}"
            await self.redis.hset(key, entry.id, json.dumps(entry.to_dict()))
            await self.redis.expire(key, 86400 * 30)

        logger.debug(
            "vector_memory_saved",
            agent_id=agent_id,
            entry_id=entry.id,
            dim=len(entry.embedding),
        )

    async def retrieve(
        self, agent_id: str, query: str, limit: int = 5
    ) -> list[MemoryEntry]:
        """检索相关记忆条目（语义匹配）.

        使用 cosine similarity 计算 query 与每条记忆的相似度，
        先归一化到 [0, 1] 区间再按 (norm_sim × importance 加权)
        排序返回 top-N。
        """
        entries = self._store.get(agent_id, [])
        embeddings = self.embeddings.get(agent_id, [])

        if not entries or not embeddings:
            return []

        # 计算 query 的 embedding
        query_vec = await self.embed.embed(query)

        # 计算每条记忆的 cosine similarity
        scores: list[tuple[float, int]] = []
        for i, emb in enumerate(embeddings):
            sim = self._cosine_similarity(query_vec, emb)
            # 归一化到 [0, 1]，避免负相似度时 importance 加权反转排序
            norm_sim = (sim + 1.0) / 2.0
            weight = 0.5 + 0.5 * entries[i].importance
            scores.append((norm_sim * weight, i))

        # 按加权分数降序排序
        scores.sort(key=lambda x: x[0], reverse=True)
        return [entries[i] for _, i in scores[:limit]]

    async def clear(self, agent_id: str) -> None:
        """清除指定 Agent 的所有记忆."""
        self._store.pop(agent_id, None)
        self.embeddings.pop(agent_id, None)

        if self.redis is not None:
            key = f"nexus:vecmem:{agent_id}"
            await self.redis.delete(key)
            logger.info("vector_memory_cleared", agent_id=agent_id)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的 cosine similarity."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = (sum(x * x for x in a)) ** 0.5
        norm_b = (sum(x * x for x in b)) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
