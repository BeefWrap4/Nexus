"""检查点管理器测试.

测试CheckpointManager的保存、加载、分叉和删除功能。
覆盖率目标: 16% → 60%+
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.engine.checkpoint import Checkpoint, CheckpointManager
from nexus.engine.state_manager import WorkflowState
from nexus.exceptions import CheckpointNotFoundException


@pytest.fixture
def checkpoint_manager():
    """创建检查点管理器实例."""
    return CheckpointManager()


@pytest.fixture
def sample_state():
    """创建示例工作流状态."""
    return WorkflowState(
        run_id="test-run-001",
        workflow_id="wf-001",
        version=1,
    )


@pytest.fixture
def populated_state():
    """创建填充数据的工作流状态."""
    state = WorkflowState(
        run_id="test-run-002",
        workflow_id="wf-002",
        version=1,
    )
    state.trigger_payload = {"input": "test data"}
    state.node_outputs = {
        "node_a": {"result": "value_a"},
        "node_b": {"result": "value_b"},
    }
    state.env_vars = {"ENV": "test"}
    state.run_vars = {"counter": 5}
    return state


class TestCheckpointSave:
    """测试检查点保存功能."""

    @pytest.mark.asyncio
    async def test_save_checkpoint_basic(self, checkpoint_manager, sample_state):
        """测试基本保存检查点."""
        checkpoint = await checkpoint_manager.save(
            run_id="test-run-001",
            state=sample_state,
        )
        
        assert checkpoint is not None
        assert checkpoint.run_id == "test-run-001"
        assert checkpoint.state == sample_state
        assert checkpoint.id.startswith("test-run-001_")

    @pytest.mark.asyncio
    async def test_save_checkpoint_with_node_id(self, checkpoint_manager, sample_state):
        """测试保存带节点ID的检查点."""
        checkpoint = await checkpoint_manager.save(
            run_id="test-run-001",
            state=sample_state,
            node_id="node_a",
        )
        
        assert checkpoint.node_id == "node_a"

    @pytest.mark.asyncio
    async def test_save_multiple_checkpoints(self, checkpoint_manager, sample_state):
        """测试保存多个检查点."""
        cp1 = await checkpoint_manager.save("run-1", sample_state, "node_a")
        cp2 = await checkpoint_manager.save("run-1", sample_state, "node_b")
        cp3 = await checkpoint_manager.save("run-1", sample_state, "node_c")
        
        checkpoints = checkpoint_manager._checkpoints["run-1"]
        assert len(checkpoints) == 3
        assert checkpoints[0].node_id == "node_a"
        assert checkpoints[1].node_id == "node_b"
        assert checkpoints[2].node_id == "node_c"

    @pytest.mark.asyncio
    async def test_save_different_runs(self, checkpoint_manager, sample_state):
        """测试为不同运行保存检查点."""
        await checkpoint_manager.save("run-1", sample_state)
        await checkpoint_manager.save("run-2", sample_state)
        
        assert "run-1" in checkpoint_manager._checkpoints
        assert "run-2" in checkpoint_manager._checkpoints
        assert len(checkpoint_manager._checkpoints["run-1"]) == 1
        assert len(checkpoint_manager._checkpoints["run-2"]) == 1

    @pytest.mark.asyncio
    async def test_save_large_state_threshold(self, checkpoint_manager):
        """测试大状态阈值判断."""
        # 创建一个大数据量的状态
        state = WorkflowState(run_id="large-run", workflow_id="wf", version=1)
        state.node_outputs = {"data": "x" * 200000}  # 超过100KB
        
        checkpoint = await checkpoint_manager.save("large-run", state)
        
        # 没有S3客户端时，state_s3_key应为None
        assert checkpoint.state_s3_key is None


class TestCheckpointLoad:
    """测试检查点加载功能."""

    @pytest.mark.asyncio
    async def test_load_latest_checkpoint(self, checkpoint_manager, sample_state):
        """测试加载最新检查点."""
        await checkpoint_manager.save("run-1", sample_state, "node_a")
        await checkpoint_manager.save("run-1", sample_state, "node_b")
        
        loaded_state = await checkpoint_manager.load("run-1")
        
        assert loaded_state is not None
        # 注意: loaded_state的run_id应该是sample_state的run_id，而非load的参数
        # 这是因为WorkflowState在创建时设置了run_id

    @pytest.mark.asyncio
    async def test_load_specific_checkpoint(self, checkpoint_manager, sample_state):
        """测试加载特定检查点."""
        cp1 = await checkpoint_manager.save("run-1", sample_state, "node_a")
        cp2 = await checkpoint_manager.save("run-1", sample_state, "node_b")
        
        loaded_state = await checkpoint_manager.load("run-1", cp1.id)
        
        assert loaded_state is not None

    @pytest.mark.asyncio
    async def test_load_nonexistent_run(self, checkpoint_manager):
        """测试加载不存在的运行."""
        with pytest.raises(CheckpointNotFoundException):
            await checkpoint_manager.load("nonexistent-run")

    @pytest.mark.asyncio
    async def test_load_from_memory_cache(self, checkpoint_manager, sample_state):
        """测试从内存缓存加载."""
        await checkpoint_manager.save("run-1", sample_state)
        
        # 应该从内存缓存加载
        loaded_state = await checkpoint_manager.load("run-1")
        assert loaded_state is not None


class TestListCheckpoints:
    """测试列出检查点功能."""

    @pytest.mark.asyncio
    async def test_list_checkpoints_empty(self, checkpoint_manager):
        """测试列出空检查点列表."""
        checkpoints = await checkpoint_manager.list_checkpoints("nonexistent")
        assert checkpoints == []

    @pytest.mark.asyncio
    async def test_list_checkpoints_from_cache(self, checkpoint_manager, sample_state):
        """测试从缓存列出检查点."""
        await checkpoint_manager.save("run-1", sample_state, "node_a")
        await checkpoint_manager.save("run-1", sample_state, "node_b")
        
        checkpoints = await checkpoint_manager.list_checkpoints("run-1")
        assert len(checkpoints) == 2

    @pytest.mark.asyncio
    async def test_list_checkpoints_order(self, checkpoint_manager, sample_state):
        """测试检查点列表顺序."""
        await checkpoint_manager.save("run-1", sample_state, "node_a")
        await checkpoint_manager.save("run-1", sample_state, "node_b")
        await checkpoint_manager.save("run-1", sample_state, "node_c")
        
        checkpoints = await checkpoint_manager.list_checkpoints("run-1")
        assert len(checkpoints) == 3
        assert checkpoints[0].node_id == "node_a"
        assert checkpoints[1].node_id == "node_b"
        assert checkpoints[2].node_id == "node_c"


class TestFork:
    """测试分叉功能."""

    @pytest.mark.asyncio
    async def test_fork_checkpoint(self, checkpoint_manager, populated_state):
        """测试从检查点分叉."""
        cp = await checkpoint_manager.save("original-run", populated_state, "node_b")
        
        forked_state = await checkpoint_manager.fork(
            run_id="original-run",
            checkpoint_id=cp.id,
            new_run_id="forked-run",
        )
        
        assert forked_state.run_id == "forked-run"
        # 分叉后状态应重置为pending
        assert forked_state.started_at is None
        assert forked_state.completed_at is None

    @pytest.mark.asyncio
    async def test_fork_preserves_data(self, checkpoint_manager, populated_state):
        """测试分叉保留数据."""
        cp = await checkpoint_manager.save("original-run", populated_state)
        
        forked_state = await checkpoint_manager.fork(
            run_id="original-run",
            checkpoint_id=cp.id,
            new_run_id="forked-run",
        )
        
        # 验证数据被保留
        assert forked_state.trigger_payload == populated_state.trigger_payload
        assert forked_state.node_outputs == populated_state.node_outputs
        assert forked_state.env_vars == populated_state.env_vars


class TestDeleteCheckpoints:
    """测试删除检查点功能."""

    @pytest.mark.asyncio
    async def test_delete_checkpoints(self, checkpoint_manager, sample_state):
        """测试删除检查点."""
        await checkpoint_manager.save("run-1", sample_state)
        await checkpoint_manager.save("run-1", sample_state)
        
        assert "run-1" in checkpoint_manager._checkpoints
        
        await checkpoint_manager.delete_checkpoints("run-1")
        
        assert "run-1" not in checkpoint_manager._checkpoints

    @pytest.mark.asyncio
    async def test_delete_nonexistent_checkpoints(self, checkpoint_manager):
        """测试删除不存在的检查点（不应报错）."""
        await checkpoint_manager.delete_checkpoints("nonexistent")
        # 不应该抛出异常


class TestCheckpointClass:
    """测试Checkpoint类."""

    def test_checkpoint_creation(self, sample_state):
        """测试检查点创建."""
        cp = Checkpoint(
            run_id="test-run",
            state=sample_state,
            node_id="node_a",
        )
        
        assert cp.run_id == "test-run"
        assert cp.node_id == "node_a"
        assert cp.state == sample_state
        assert cp.id.startswith("test-run_")
        assert cp.created_at is not None

    def test_checkpoint_with_s3_key(self, sample_state):
        """测试带S3 key的检查点."""
        cp = Checkpoint(
            run_id="test-run",
            state=sample_state,
            state_s3_key="s3://bucket/checkpoint.json",
        )
        
        assert cp.state_s3_key == "s3://bucket/checkpoint.json"


class TestDatabaseIntegration:
    """测试数据库集成（Mock）."""

    @pytest.mark.asyncio
    async def test_save_with_db_error(self, checkpoint_manager, sample_state):
        """测试数据库保存失败时的容错."""
        with patch('nexus.db.database.get_db_session') as mock_get_db:
            mock_get_db.side_effect = Exception("DB connection failed")
            
            # 不应抛出异常，只是记录错误日志
            checkpoint = await checkpoint_manager.save("run-1", sample_state)
            
            # 内存缓存仍应可用
            assert checkpoint is not None
            assert "run-1" in checkpoint_manager._checkpoints

    @pytest.mark.asyncio
    async def test_load_with_db_error(self, checkpoint_manager):
        """测试数据库加载失败时的容错."""
        with patch('nexus.db.database.get_db_session') as mock_get_db:
            mock_get_db.side_effect = Exception("DB connection failed")
            
            # 应从内存缓存加载（如果存在）
            # 如果不存在且DB失败，应抛出异常
            with pytest.raises(CheckpointNotFoundException):
                await checkpoint_manager.load("nonexistent")


class TestEdgeCases:
    """测试边界情况."""

    @pytest.mark.asyncio
    async def test_save_state_with_none_values(self, checkpoint_manager):
        """测试保存包含None值的状态."""
        state = WorkflowState(run_id="test", workflow_id="wf", version=1)
        state.trigger_payload = None
        state.node_outputs = {"node": None}

        checkpoint = await checkpoint_manager.save("test", state)
        assert checkpoint is not None

    @pytest.mark.asyncio
    async def test_load_after_multiple_saves(self, checkpoint_manager, sample_state):
        """测试多次保存后加载最新状态."""
        state1 = WorkflowState(run_id="run-1", workflow_id="wf", version=1)
        state1.trigger_payload = {"version": 1}

        state2 = WorkflowState(run_id="run-1", workflow_id="wf", version=1)
        state2.trigger_payload = {"version": 2}

        await checkpoint_manager.save("run-1", state1)
        await checkpoint_manager.save("run-1", state2)

        loaded = await checkpoint_manager.load("run-1")
        assert loaded.trigger_payload == {"version": 2}


class TestLargeStateS3:
    """测试大状态S3存储路径 (覆盖 lines 78-81)."""

    @pytest.mark.asyncio
    async def test_save_large_state_with_s3_client(self):
        """大状态 (>100KB) + S3客户端时存储到S3."""
        mock_s3 = AsyncMock()
        mgr = CheckpointManager(s3_client=mock_s3)

        # 构造序列化后超过100KB的状态
        state = WorkflowState(run_id="large-run", workflow_id="wf", version=1)
        # node_outputs 放入大量数据使序列化 > 100KB
        large_data = "x" * (CheckpointManager.LARGE_STATE_THRESHOLD + 1000)
        state.node_outputs = {"large_field": large_data}

        checkpoint = await mgr.save(run_id="large-run", state=state, node_id="node_s3")

        assert checkpoint.state_s3_key is not None
        assert checkpoint.state_s3_key.startswith("checkpoints/large-run/")
        # 大状态应缓存到内存
        assert "large-run" in mgr._checkpoints

    @pytest.mark.asyncio
    async def test_save_large_state_without_s3_falls_back(self):
        """大状态但无S3客户端时仍走内存（state_s3_key=None）."""
        mgr = CheckpointManager(s3_client=None)

        state = WorkflowState(run_id="large-run-nos3", workflow_id="wf", version=1)
        large_data = "x" * (CheckpointManager.LARGE_STATE_THRESHOLD + 1000)
        state.node_outputs = {"large_field": large_data}

        checkpoint = await mgr.save(run_id="large-run-nos3", state=state)
        # 无S3客户端时 state_s3_key 仍为 None
        assert checkpoint.state_s3_key is None
        assert "large-run-nos3" in mgr._checkpoints


class TestDBFallbackLoad:
    """测试DB回退加载路径 (覆盖 lines 151, 166-171)."""

    @pytest.mark.asyncio
    async def test_load_from_db_with_checkpoint_id(self):
        """通过指定checkpoint_id从DB加载."""
        from nexus.models.workflow import CheckpointRecord

        mgr = CheckpointManager()
        state = WorkflowState(run_id="db-run", workflow_id="wf-db", version=1)
        state.run_vars = {"from": "db"}
        record_data = state.to_dict()

        mock_record = MagicMock(spec=CheckpointRecord)
        mock_record.id = "cp_db_specific"
        mock_record.run_id = "db-run"
        mock_record.state_data = record_data
        mock_record.state_s3_key = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            loaded = await mgr.load(run_id="db-run", checkpoint_id="cp_db_specific")
            assert loaded.run_id == "db-run"
            assert loaded.workflow_id == "wf-db"

    @pytest.mark.asyncio
    async def test_load_from_db_latest(self):
        """从DB加载最新检查点（无checkpoint_id）."""
        from nexus.models.workflow import CheckpointRecord

        mgr = CheckpointManager()
        state = WorkflowState(run_id="db-run-latest", workflow_id="wf-latest", version=1)
        record_data = state.to_dict()

        mock_record = MagicMock(spec=CheckpointRecord)
        mock_record.id = "cp_db_latest"
        mock_record.run_id = "db-run-latest"
        mock_record.state_data = record_data
        mock_record.state_s3_key = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            loaded = await mgr.load(run_id="db-run-latest")
            assert loaded.run_id == "db-run-latest"
            assert loaded.workflow_id == "wf-latest"

    @pytest.mark.asyncio
    async def test_load_from_db_with_s3(self):
        """从DB加载时走S3路径."""
        from nexus.models.workflow import CheckpointRecord

        mock_s3 = AsyncMock()
        mgr = CheckpointManager(s3_client=mock_s3)

        state = WorkflowState(run_id="s3-run", workflow_id="wf-s3", version=1)
        state_data_json = json.dumps(state.to_dict())
        mock_s3.get_object = AsyncMock(return_value=state_data_json)

        mock_record = MagicMock(spec=CheckpointRecord)
        mock_record.id = "cp_s3"
        mock_record.run_id = "s3-run"
        mock_record.state_data = None
        mock_record.state_s3_key = "checkpoints/s3-run/key.json"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            loaded = await mgr.load(run_id="s3-run")
            assert loaded.run_id == "s3-run"
            assert loaded.workflow_id == "wf-s3"

    @pytest.mark.asyncio
    async def test_load_from_db_record_not_found(self):
        """DB中找不到记录时回退抛出异常."""
        mgr = CheckpointManager()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            with pytest.raises(CheckpointNotFoundException):
                await mgr.load(run_id="not-in-db")


class TestDBListCheckpoints:
    """测试DB回退列出检查点 (覆盖 lines 200-216)."""

    @pytest.mark.asyncio
    async def test_list_from_db_with_records(self):
        """从DB列出多个检查点记录."""
        from nexus.models.workflow import CheckpointRecord

        mgr = CheckpointManager()
        state = WorkflowState(run_id="list-run", workflow_id="wf-list", version=1)
        record_data = state.to_dict()

        mock_record1 = MagicMock(spec=CheckpointRecord)
        mock_record1.id = "cp_1"
        mock_record1.run_id = "list-run"
        mock_record1.node_id = "node_a"
        mock_record1.state_data = record_data
        mock_record1.state_s3_key = None
        mock_record1.created_at = None

        mock_record2 = MagicMock(spec=CheckpointRecord)
        mock_record2.id = "cp_2"
        mock_record2.run_id = "list-run"
        mock_record2.node_id = "node_b"
        mock_record2.state_data = None
        mock_record2.state_s3_key = "s3://bucket/key.json"
        mock_record2.created_at = None

        mock_session = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_record1, mock_record2]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            cps = await mgr.list_checkpoints("list-run")
            assert len(cps) == 2
            assert cps[0].id == "cp_1"
            assert cps[0].node_id == "node_a"
            assert cps[1].id == "cp_2"
            assert cps[1].node_id == "node_b"
            assert cps[1].state_s3_key == "s3://bucket/key.json"
            # 验证DB结果缓存到内存
            assert "list-run" in mgr._checkpoints

    @pytest.mark.asyncio
    async def test_list_from_db_error_returns_empty(self):
        """DB故障时list_checkpoints静默返回空列表."""
        mgr = CheckpointManager()

        with patch("nexus.db.database.get_db_session", side_effect=Exception("DB down")):
            cps = await mgr.list_checkpoints("error-run")
            assert cps == []

    @pytest.mark.asyncio
    async def test_list_from_db_record_without_state_data(self):
        """DB记录无state_data无s3_key时仍创建checkpoint."""
        from nexus.models.workflow import CheckpointRecord

        mgr = CheckpointManager()

        mock_record = MagicMock(spec=CheckpointRecord)
        mock_record.id = "cp_no_data"
        mock_record.run_id = "no-data-run"
        mock_record.node_id = "node_x"
        mock_record.state_data = None
        mock_record.state_s3_key = None
        mock_record.created_at = None

        mock_session = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_record]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            cps = await mgr.list_checkpoints("no-data-run")
            assert len(cps) == 1
            assert cps[0].id == "cp_no_data"


class TestDBDeleteCheckpoints:
    """测试DB删除检查点 (覆盖 lines 254-255)."""

    @pytest.mark.asyncio
    async def test_delete_from_memory_and_db(self, checkpoint_manager, sample_state):
        """删除同时清理内存和DB."""
        from nexus.models.workflow import CheckpointRecord
        from sqlalchemy import delete

        await checkpoint_manager.save("run-del", sample_state)

        mock_session = AsyncMock()

        with patch("nexus.db.database.get_db_session") as mock_db:
            mock_db.return_value.__aenter__.return_value = mock_session
            await checkpoint_manager.delete_checkpoints("run-del")

            # 验证内存已删除
            assert "run-del" not in checkpoint_manager._checkpoints
            # 验证DB execute 被调用
            assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_delete_db_error_swallowed(self, checkpoint_manager, sample_state):
        """DB删除失败时静默处理."""
        await checkpoint_manager.save("run-del-err", sample_state)

        with patch("nexus.db.database.get_db_session", side_effect=Exception("DB down")):
            await checkpoint_manager.delete_checkpoints("run-del-err")

        # 内存仍应删除
        assert "run-del-err" not in checkpoint_manager._checkpoints


class TestS3LoadCheckpointState:
    """测试 _load_checkpoint_state 的S3路径 (覆盖 line 263)."""

    @pytest.mark.asyncio
    async def test_load_checkpoint_state_with_s3(self):
        """通过S3加载检查点状态."""
        state = WorkflowState(run_id="s3-cp-run", workflow_id="wf-s3-cp", version=2)
        state_data_json = json.dumps(state.to_dict())

        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value=state_data_json)
        mgr = CheckpointManager(s3_client=mock_s3)

        cp = Checkpoint(
            run_id="s3-cp-run",
            state=state,
            node_id="node_s3",
            state_s3_key="s3://bucket/cp.json",
        )

        loaded = await mgr._load_checkpoint_state(cp)
        assert loaded.run_id == "s3-cp-run"
        assert loaded.workflow_id == "wf-s3-cp"
        assert loaded.version == 2

    @pytest.mark.asyncio
    async def test_load_checkpoint_state_no_s3_client(self):
        """无S3客户端时直接返回checkpoint.state."""
        mgr = CheckpointManager(s3_client=None)
        state = WorkflowState(run_id="mem-cp", workflow_id="wf-mem", version=1)

        cp = Checkpoint(
            run_id="mem-cp",
            state=state,
            node_id="node_mem",
            state_s3_key="s3://bucket/ignored.json",
        )

        loaded = await mgr._load_checkpoint_state(cp)
        assert loaded is state  # 完全相同对象

    @pytest.mark.asyncio
    async def test_load_checkpoint_state_no_s3_key(self):
        """无s3_key时直接返回checkpoint.state."""
        mock_s3 = AsyncMock()
        mgr = CheckpointManager(s3_client=mock_s3)
        state = WorkflowState(run_id="no-key", workflow_id="wf-nokey", version=1)

        cp = Checkpoint(
            run_id="no-key",
            state=state,
            node_id="node_nokey",
            state_s3_key=None,
        )

        loaded = await mgr._load_checkpoint_state(cp)
        assert loaded is state
