"""向量记忆后端测试.

覆盖:
- EmbeddingService: mock 嵌入生成、确定性、归一化、维度
- VectorMemoryBackend: save/retrieve/clear、语义检索排序、工厂创建
"""

import pytest
from nexus.agent.memory_backend import MemoryEntry, create_memory_backend


class TestEmbeddingService:
    """EmbeddingService 单元测试."""

    def test_mock_embed_returns_correct_dimension(self):
        """mock 嵌入应返回指定维度的向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=384)
        vec = svc._mock_embed("hello")
        assert len(vec) == 384

    def test_mock_embed_returns_normalized_vector(self):
        """mock 嵌入应返回 L2 归一化的向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=512)
        vec = svc._mock_embed("test normalization")
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 0.001

    def test_mock_embed_is_deterministic(self):
        """相同输入应产生相同向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=384)
        v1 = svc._mock_embed("hello world")
        v2 = svc._mock_embed("hello world")
        assert v1 == v2

    def test_mock_embed_different_texts_produce_different_vectors(self):
        """不同输入应产生不同向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=384)
        v1 = svc._mock_embed("hello")
        v2 = svc._mock_embed("completely different string here")
        assert v1 != v2

    def test_mock_embed_different_dim_produces_different_length(self):
        """不同 dim 产生不同长度向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc128 = EmbeddingService(backend="mock", dim=128)
        svc768 = EmbeddingService(backend="mock", dim=768)
        assert len(svc128._mock_embed("hello")) == 128
        assert len(svc768._mock_embed("hello")) == 768

    @pytest.mark.asyncio
    async def test_embed_delegates_to_mock(self):
        """embed() 应正确委托到 _mock_embed()."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=128)
        vec = await svc.embed("async test")
        assert len(vec) == 128

    @pytest.mark.asyncio
    async def test_embed_batch_returns_all_vectors(self):
        """embed_batch() 应返回所有文本的向量."""
        from nexus.agent.vector_memory import EmbeddingService

        svc = EmbeddingService(backend="mock", dim=128)
        texts = ["a", "b", "c"]
        vecs = await svc.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == 128 for v in vecs)

    def test_unknown_backend_raises(self):
        """不支持的 backend 应抛出 ValueError."""
        from nexus.agent.vector_memory import EmbeddingService

        import asyncio

        svc = EmbeddingService(backend="unsupported", dim=128)
        with pytest.raises(ValueError, match="Unknown embedding backend"):
            asyncio.run(svc.embed("test"))


class TestVectorMemoryBackend:
    """VectorMemoryBackend 集成测试."""

    @pytest.fixture
    def backend(self):
        """创建测试用 VectorMemoryBackend."""
        return create_memory_backend("vector")

    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, backend):
        """保存后应能检索到条目."""
        entry = MemoryEntry(
            entry_id="e1",
            content="machine learning algorithms",
            task_description="learn ML",
            result="success",
        )
        await backend.save("agent1", entry)
        results = await backend.retrieve("agent1", "AI and machine learning", limit=5)
        assert len(results) >= 1
        assert results[0].content == "machine learning algorithms"

    @pytest.mark.asyncio
    async def test_save_sets_embedding(self, backend):
        """保存时应自动计算并设置 embedding."""
        entry = MemoryEntry(entry_id="e1", content="test content")
        await backend.save("agent1", entry)
        assert entry.embedding is not None
        assert len(entry.embedding) == 384

    @pytest.mark.asyncio
    async def test_retrieve_empty_agent_returns_empty(self, backend):
        """未保存任何记忆的 agent 应返回空列表."""
        results = await backend.retrieve("nonexistent", "query")
        assert results == []

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, backend):
        """clear 后检索应返回空列表."""
        entry = MemoryEntry(entry_id="e1", content="test")
        await backend.save("agent1", entry)
        await backend.clear("agent1")
        results = await backend.retrieve("agent1", "test")
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_respects_limit(self, backend):
        """检索应遵守 limit 参数."""
        for i in range(10):
            entry = MemoryEntry(entry_id=f"e{i}", content=f"entry number {i}")
            await backend.save("agent1", entry)
        results = await backend.retrieve("agent1", "entry", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_semantic_retrieval_ranks_relevant_higher(self, backend):
        """语义相关的内容应排在语义不相关的内容之前."""
        await backend.save(
            "agent1",
            MemoryEntry(entry_id="e1", content="Python programming language and coding"),
        )
        await backend.save(
            "agent1",
            MemoryEntry(entry_id="e2", content="Cooking recipes for dinner tonight"),
        )
        await backend.save(
            "agent1",
            MemoryEntry(entry_id="e3", content="Software development best practices"),
        )
        results = await backend.retrieve("agent1", "coding and software development", limit=3)

        # "Python programming" 或 "Software development" 应排在 "Cooking" 前面
        # 因为 mock embedding 基于文本 hash，语义相似文本有相近的 hash 分布
        top_contents = [r.content for r in results]
        assert "Cooking" not in top_contents[0]

    @pytest.mark.asyncio
    async def test_multiple_agents_isolation(self, backend):
        """不同 agent 的记忆应隔离."""
        await backend.save("agentA", MemoryEntry(entry_id="a1", content="data for A"))
        await backend.save("agentB", MemoryEntry(entry_id="b1", content="data for B"))
        results_a = await backend.retrieve("agentA", "data", limit=5)
        results_b = await backend.retrieve("agentB", "data", limit=5)
        assert len(results_a) == 1
        assert len(results_b) == 1
        assert results_a[0].content == "data for A"
        assert results_b[0].content == "data for B"

    @pytest.mark.asyncio
    async def test_importance_affects_ranking(self, backend):
        """importance 较高的记忆应在相同相似度下排在前面."""
        await backend.save(
            "agent1",
            MemoryEntry(
                entry_id="low",
                content="general information about the topic",
                importance=0.1,
            ),
        )
        await backend.save(
            "agent1",
            MemoryEntry(
                entry_id="high",
                content="general information about the topic",
                importance=0.9,
            ),
        )
        results = await backend.retrieve("agent1", "information topic", limit=2)
        # 高 importance 应排前面（content 相同则 similarity 相同）
        assert results[0].id == "high"

    @pytest.mark.asyncio
    async def test_cosine_similarity_identical_vectors(self):
        """相同向量的 cosine similarity 应为 1.0."""
        from nexus.agent.vector_memory import VectorMemoryBackend

        vec = [0.5, 0.5, 0.5, 0.5]
        sim = VectorMemoryBackend._cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_cosine_similarity_orthogonal_vectors(self):
        """正交向量的 cosine similarity 应为 0.0."""
        from nexus.agent.vector_memory import VectorMemoryBackend

        a = [1.0, 0.0]
        b = [0.0, 1.0]
        sim = VectorMemoryBackend._cosine_similarity(a, b)
        assert abs(sim - 0.0) < 1e-9

    @pytest.mark.asyncio
    async def test_cosine_similarity_zero_vector(self):
        """零向量的 cosine similarity 应为 0.0（不 crash）."""
        from nexus.agent.vector_memory import VectorMemoryBackend

        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        sim = VectorMemoryBackend._cosine_similarity(a, b)
        assert sim == 0.0


class TestCreateMemoryBackendVector:
    """工厂函数 vector 类型测试."""

    def test_create_vector_backend(self):
        """create_memory_backend("vector") 应返回 VectorMemoryBackend."""
        from nexus.agent.vector_memory import VectorMemoryBackend

        backend = create_memory_backend("vector")
        assert isinstance(backend, VectorMemoryBackend)

    def test_create_unknown_backend_raises(self):
        """不支持的 backend_type 应抛出 ValueError."""
        with pytest.raises(ValueError, match="Unsupported memory backend"):
            create_memory_backend("cassandra")
