"""检查点管理器.

基于WAT CheckpointManager 升级:
- **PostgreSQL 持久化**（支持跨进程恢复）
- 支持S3大对象存储
- 支持分叉(fork) - 用于A/B测试
- 保留策略自动清理

借鉴LangGraph PostgresSaver + Temporal Event Sourcing。
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from nexus.engine.state_manager import WorkflowState
from nexus.exceptions import CheckpointNotFoundException

logger = logging.getLogger(__name__)

# S3 bucket used for large checkpoint state. Override via BACKUP_S3_BUCKET env.
DEFAULT_CHECKPOINT_S3_BUCKET = "nexus-checkpoints"


def _checkpoint_bucket() -> str:
    """Resolve the S3 bucket name for checkpoint blobs."""
    return os.environ.get("BACKUP_S3_BUCKET", DEFAULT_CHECKPOINT_S3_BUCKET)


class Checkpoint:
    """检查点（内存表示）."""

    def __init__(
        self,
        run_id: str,
        state: WorkflowState,
        node_id: Optional[str] = None,
        state_s3_key: Optional[str] = None,
    ):
        self.id = f"{run_id}_{datetime.now(timezone.utc).isoformat()}"
        self.run_id = run_id
        self.node_id = node_id
        self.state = state
        self.state_s3_key = state_s3_key
        self.created_at = datetime.now(timezone.utc)


class CheckpointManager:
    """检查点管理器 - DB-backed + S3 大对象.

    关键设计:
    - 小状态 (<100KB): 直接存入 PostgreSQL JSON 字段
    - 大状态 (>=100KB): 存入 S3，DB 只存 key
    - 支持跨进程恢复（Worker A 保存，Worker B 加载）
    """

    # 大状态阈值 (100KB)
    LARGE_STATE_THRESHOLD = 100 * 1024

    def __init__(self, s3_client=None):
        self.s3 = s3_client
        self._checkpoints: dict[str, list[Checkpoint]] = {}  # 内存缓存

    async def save(
        self,
        run_id: str,
        state: WorkflowState,
        node_id: Optional[str] = None,
    ) -> Checkpoint:
        """保存检查点.

        Args:
            run_id: 运行实例ID
            state: 当前工作流状态
            node_id: 当前节点ID（可选）

        Returns:
            Checkpoint: 检查点对象
        """
        state_s3_key = None
        state_data = json.dumps(state.to_dict())

        # 大状态存储到S3
        if len(state_data) > self.LARGE_STATE_THRESHOLD and self.s3:
            key = f"checkpoints/{run_id}/{datetime.now(timezone.utc).isoformat()}.json"
            try:
                # boto3-style call: put_object(Bucket=..., Key=..., Body=...)
                await self.s3.put_object(
                    Bucket=_checkpoint_bucket(),
                    Key=key,
                    Body=state_data.encode("utf-8"),
                )
                state_s3_key = key
                state_data = None  # 不存本地，只存 S3 key
            except Exception as e:
                logger.error(
                    "checkpoint_s3_upload_failed key=%s err=%s", key, e
                )
                # Fallback: keep state in DB if S3 upload fails
                state_s3_key = None

        checkpoint = Checkpoint(
            run_id=run_id,
            state=state,
            node_id=node_id,
            state_s3_key=state_s3_key,
        )

        # 缓存到内存
        if run_id not in self._checkpoints:
            self._checkpoints[run_id] = []
        self._checkpoints[run_id].append(checkpoint)

        # 持久化到 DB
        try:
            from nexus.db.database import get_db_session
            from nexus.models.workflow import CheckpointRecord

            async with get_db_session() as session:
                record = CheckpointRecord(
                    id=checkpoint.id,
                    run_id=run_id,
                    node_id=node_id,
                    state_data=json.loads(state_data) if state_data else None,
                    state_s3_key=state_s3_key,
                    created_at=checkpoint.created_at,
                )
                session.add(record)
        except Exception:
            # DB 写入失败不阻塞检查点保存（内存缓存仍可用）
            logger.error("Failed to persist checkpoint to DB (run_id=%s)", run_id, exc_info=True)

        return checkpoint

    async def load(
        self,
        run_id: str,
        checkpoint_id: Optional[str] = None,
    ) -> WorkflowState:
        """加载检查点.

        Args:
            run_id: 运行实例ID
            checkpoint_id: 特定检查点ID（None则加载最新）

        Returns:
            WorkflowState: 检查点状态

        Raises:
            CheckpointNotFoundException: 检查点不存在
        """
        # 优先从内存加载
        checkpoints = self._checkpoints.get(run_id, [])
        if checkpoints:
            if checkpoint_id:
                for cp in checkpoints:
                    if cp.id == checkpoint_id:
                        return await self._load_checkpoint_state(cp)
            else:
                return await self._load_checkpoint_state(checkpoints[-1])

        # 从 DB 加载
        try:
            from nexus.db.database import get_db_session
            from nexus.models.workflow import CheckpointRecord
            from sqlalchemy import select

            async with get_db_session() as session:
                if checkpoint_id:
                    stmt = select(CheckpointRecord).where(
                        CheckpointRecord.id == checkpoint_id,
                        CheckpointRecord.run_id == run_id,
                    )
                else:
                    stmt = (
                        select(CheckpointRecord)
                        .where(CheckpointRecord.run_id == run_id)
                        .order_by(CheckpointRecord.created_at.desc())
                        .limit(1)
                    )
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()

                if record:
                    if record.state_s3_key and self.s3:
                        # 从 S3 加载（boto3-style: get_object returns {"Body": BytesReadable}）
                        try:
                            response = await self.s3.get_object(
                                Bucket=_checkpoint_bucket(),
                                Key=record.state_s3_key,
                            )
                            body = response["Body"].read()
                            if isinstance(body, bytes):
                                body = body.decode("utf-8")
                            return WorkflowState.from_dict(json.loads(body))
                        except Exception as e:
                            logger.error(
                                "checkpoint_s3_load_failed key=%s err=%s",
                                record.state_s3_key,
                                e,
                            )
                            raise
                    elif record.state_data:
                        return WorkflowState.from_dict(record.state_data)
        except Exception:
            logger.error("Failed to load checkpoint from DB/S3 (run_id=%s)", run_id, exc_info=True)

        raise CheckpointNotFoundException(run_id)

    async def list_checkpoints(self, run_id: str) -> list[Checkpoint]:
        """列出所有检查点."""
        # 优先返回内存缓存
        if run_id in self._checkpoints:
            return self._checkpoints[run_id]

        # 从 DB 加载
        try:
            from nexus.db.database import get_db_session
            from nexus.models.workflow import CheckpointRecord
            from sqlalchemy import select

            async with get_db_session() as session:
                stmt = (
                    select(CheckpointRecord)
                    .where(CheckpointRecord.run_id == run_id)
                    .order_by(CheckpointRecord.created_at)
                )
                result = await session.execute(stmt)
                records = result.scalars().all()

                checkpoints = []
                for record in records:
                    state = None
                    if record.state_data:
                        state = WorkflowState.from_dict(record.state_data)
                    cp = Checkpoint(
                        run_id=run_id,
                        state=state or WorkflowState(run_id=run_id, workflow_id="", version=1),
                        node_id=record.node_id,
                        state_s3_key=record.state_s3_key,
                    )
                    cp.id = record.id
                    checkpoints.append(cp)

                self._checkpoints[run_id] = checkpoints
                return checkpoints
        except Exception:
            logger.error("Failed to list checkpoints from DB (run_id=%s)", run_id, exc_info=True)
            return []

    async def fork(
        self,
        run_id: str,
        checkpoint_id: str,
        new_run_id: str,
    ) -> WorkflowState:
        """分叉执行 - 从检查点创建新分支（用于A/B测试）.

        Args:
            run_id: 源运行实例ID
            checkpoint_id: 检查点ID
            new_run_id: 新运行实例ID

        Returns:
            WorkflowState: 分叉后的新状态
        """
        state = await self.load(run_id, checkpoint_id)
        state.run_id = new_run_id
        state.status = state.status.__class__.PENDING  # 重置为pending
        state.started_at = None
        state.completed_at = None
        return state

    async def delete_checkpoints(self, run_id: str) -> None:
        """删除运行实例的所有检查点."""
        self._checkpoints.pop(run_id, None)

        # 从 DB 删除
        try:
            from nexus.db.database import get_db_session
            from nexus.models.workflow import CheckpointRecord
            from sqlalchemy import delete

            async with get_db_session() as session:
                stmt = delete(CheckpointRecord).where(CheckpointRecord.run_id == run_id)
                await session.execute(stmt)
        except Exception:
            logger.error("Failed to delete checkpoints from DB (run_id=%s)", run_id, exc_info=True)

    async def _load_checkpoint_state(self, checkpoint: Checkpoint) -> WorkflowState:
        """从检查点加载状态."""
        if checkpoint.state_s3_key and self.s3:
            # 从S3加载（boto3-style: get_object returns {"Body": BytesReadable}）
            try:
                response = await self.s3.get_object(
                    Bucket=_checkpoint_bucket(),
                    Key=checkpoint.state_s3_key,
                )
                body = response["Body"].read()
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                return WorkflowState.from_dict(json.loads(body))
            except Exception as e:
                logger.error(
                    "checkpoint_s3_load_failed key=%s err=%s",
                    checkpoint.state_s3_key,
                    e,
                )
                raise

        return checkpoint.state
