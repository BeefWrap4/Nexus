"""pytest配置和共享fixtures.

提供:
- 异步事件循环支持
- PostgreSQL 测试数据库会话（Docker Compose）
- Mock引擎组件
- FastAPI TestClient
- JWT Token生成
"""

import asyncio
import os

# 必须在导入 nexus 模块之前设置，否则 nexus.db.database 会基于默认 SQLite 创建 engine
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///./.pytest_nexus.db",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DEV_API_KEY"] = "test-api-key"
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from nexus.api.main import app
from nexus.config import settings
from nexus.db.database import Base, get_db
from nexus.engine.checkpoint import CheckpointManager
from nexus.engine.enums import NodeStatus, NodeType, RunStatus
from nexus.engine.event_bus import EventBus
from nexus.engine.router_engine import RouterEngine
from nexus.engine.state_manager import StateManager, WorkflowState
from nexus.engine.variable_pool import VariablePool
from nexus.engine.workflow_engine import (
    Edge,
    Node,
    NodeExecutor,
    NodeResult,
    WorkflowDefinition,
    WorkflowEngine,
)
from nexus.security.auth import AuthService

# ---------------------------------------------------------------------------
# pytest配置
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """pytest全局配置."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )


# ---------------------------------------------------------------------------
# 异步事件循环
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """提供session级别的事件循环."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# 测试数据库（PostgreSQL — Docker Compose 内）
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供函数级别的 PostgreSQL 测试数据库会话.

    每次测试前重建所有表，测试后回滚，确保隔离。
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    # 清理并重建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # PostgreSQL 下禁用外键检查（兼容原先 SQLite 无 FK 约束的测试写法）
        from sqlalchemy import text

        if "postgresql" in TEST_DATABASE_URL:
            await session.execute(text("SET session_replication_role = 'replica'"))
            await session.commit()
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def override_get_db(db_session: AsyncSession):
    """覆盖FastAPI的get_db依赖，使用内存数据库."""
    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield db_session
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# FastAPI客户端
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def client(override_get_db) -> TestClient:
    """提供同步TestClient.

    注意: 由于SQLAlchemy async限制，同步客户端仅用于无需DB的路由测试。
    需要DB的路由请使用 async_client。
    """
    return TestClient(app)


@pytest_asyncio.fixture(scope="function")
async def async_client(override_get_db) -> AsyncGenerator[AsyncClient, None]:
    """提供异步HTTP客户端."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# 认证 Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_user() -> dict[str, Any]:
    """标准测试用户."""
    return {
        "id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": "admin",
        "auth_type": "jwt",
    }


@pytest.fixture(scope="function")
def test_token(test_user: dict[str, Any]) -> str:
    """生成测试JWT Token."""
    return AuthService.create_access_token(
        user_id=test_user["id"],
        tenant_id=test_user["tenant_id"],
        role=test_user["role"],
        expires_delta=timedelta(hours=1),
    )


@pytest.fixture(scope="function")
def auth_headers(test_token: str) -> dict[str, str]:
    """认证请求头."""
    return {"Authorization": f"Bearer {test_token}"}


# ---------------------------------------------------------------------------
# Mock引擎组件
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def mock_state_manager() -> MagicMock:
    """Mock StateManager.

    create_state 根据传入的 workflow_def 初始化所有节点为 PENDING，
    这样 _get_ready_nodes() 才能正确识别就绪节点。
    """
    mgr = MagicMock(spec=StateManager)

    def _create_state(workflow_def, trigger_payload, run_id):
        node_states = {node.id: NodeStatus.PENDING for node in workflow_def.nodes}
        return WorkflowState(
            run_id=run_id,
            workflow_id=getattr(workflow_def, "workflow_id", "test-wf-001"),
            version=getattr(workflow_def, "version", 1),
            status=RunStatus.RUNNING,
            node_states=node_states,
            trigger_payload=trigger_payload,
        )

    mgr.create_state = MagicMock(side_effect=_create_state)
    mgr.update_status = AsyncMock()
    mgr.update_node_state = AsyncMock()
    mgr.get_state = MagicMock(return_value=None)
    return mgr


@pytest.fixture(scope="function")
def mock_event_bus() -> MagicMock:
    """Mock EventBus."""
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture(scope="function")
def mock_checkpoint_mgr() -> MagicMock:
    """Mock CheckpointManager."""
    mgr = MagicMock(spec=CheckpointManager)
    mgr.save = AsyncMock()
    mgr.load = AsyncMock(return_value=None)
    return mgr


@pytest.fixture(scope="function")
def mock_variable_pool() -> MagicMock:
    """Mock VariablePool."""
    pool = MagicMock(spec=VariablePool)
    pool.resolve = MagicMock(return_value={})
    return pool


@pytest.fixture(scope="function")
def mock_router_engine() -> MagicMock:
    """Mock RouterEngine."""
    router = MagicMock(spec=RouterEngine)
    router.evaluate_condition = MagicMock(return_value=True)
    return router


# ---------------------------------------------------------------------------
# WorkflowEngine Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def workflow_engine(
    mock_state_manager,
    mock_event_bus,
    mock_checkpoint_mgr,
    mock_variable_pool,
    mock_router_engine,
) -> WorkflowEngine:
    """提供配置好的WorkflowEngine实例（使用Mock组件）."""
    engine = WorkflowEngine(
        state_manager=mock_state_manager,
        event_bus=mock_event_bus,
        checkpoint_mgr=mock_checkpoint_mgr,
        variable_pool=mock_variable_pool,
        router_engine=mock_router_engine,
    )
    return engine


# ---------------------------------------------------------------------------
# 测试用工作流定义
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def simple_workflow() -> WorkflowDefinition:
    """简单线性工作流: start -> agent_a -> end."""
    return WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START, config={}),
            Node(id="agent_a", type=NodeType.AGENT, config={"task": "test"}),
            Node(id="end", type=NodeType.END, config={}),
        ],
        edges=[
            Edge(source="start", target="agent_a"),
            Edge(source="agent_a", target="end"),
        ],
    )


@pytest.fixture(scope="function")
def branching_workflow() -> WorkflowDefinition:
    """分支工作流: start -> condition -> [branch_a | branch_b] -> end."""
    return WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START, config={}),
            Node(id="condition", type=NodeType.CONDITION, config={}),
            Node(id="branch_a", type=NodeType.AGENT, config={"task": "A"}),
            Node(id="branch_b", type=NodeType.AGENT, config={"task": "B"}),
            Node(id="end", type=NodeType.END, config={}),
        ],
        edges=[
            Edge(source="start", target="condition"),
            Edge(source="condition", target="branch_a", condition="a"),
            Edge(source="condition", target="branch_b", condition="b"),
            Edge(source="branch_a", target="end"),
            Edge(source="branch_b", target="end"),
        ],
    )


@pytest.fixture(scope="function")
def parallel_workflow() -> WorkflowDefinition:
    """并行工作流: start -> [agent_a, agent_b] -> end."""
    return WorkflowDefinition(
        nodes=[
            Node(id="start", type=NodeType.START, config={}),
            Node(id="agent_a", type=NodeType.AGENT, config={"task": "A"}),
            Node(id="agent_b", type=NodeType.AGENT, config={"task": "B"}),
            Node(id="end", type=NodeType.END, config={}),
        ],
        edges=[
            Edge(source="start", target="agent_a"),
            Edge(source="start", target="agent_b"),
            Edge(source="agent_a", target="end"),
            Edge(source="agent_b", target="end"),
        ],
    )


@pytest.fixture(scope="function")
def cyclic_workflow() -> WorkflowDefinition:
    """循环依赖工作流（用于测试验证）."""
    return WorkflowDefinition(
        nodes=[
            Node(id="a", type=NodeType.AGENT, config={}, depends_on=["c"]),
            Node(id="b", type=NodeType.AGENT, config={}, depends_on=["a"]),
            Node(id="c", type=NodeType.AGENT, config={}, depends_on=["b"]),
        ],
        edges=[
            Edge(source="a", target="b"),
            Edge(source="b", target="c"),
            Edge(source="c", target="a"),
        ],
    )


# ---------------------------------------------------------------------------
# LLM集成测试 Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def deepseek_api() -> dict[str, str]:
    """Lazy-load DeepSeek API key from .env.

    Returns a dict with ``api_key``, ``base_url``, and ``model`` for
    constructing an LLMClient pointed at the DeepSeek OpenAI-compatible
    endpoint.
    """
    import os

    from dotenv import load_dotenv

    # Locate the .env file relative to the project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path, override=False)

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        pytest.skip("DEEPSEEK_API_KEY not set in .env")

    return {
        "api_key": api_key,
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    }


# ---------------------------------------------------------------------------
# 通用Mock节点执行器
# ---------------------------------------------------------------------------


class MockNodeExecutor(NodeExecutor):
    """通用Mock节点执行器，用于测试."""

    def __init__(self, output: dict[str, Any] | None = None, fail: bool = False):
        self.output = output or {"mock": True}
        self.fail = fail

    async def execute(
        self,
        node: Node,
        inputs: dict[str, Any],
        state: WorkflowState,
        run_id: str,
    ) -> NodeResult:
        if self.fail:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error={"message": "Mock failure"},
            )
        return NodeResult(
            node_id=node.id,
            status=NodeStatus.SUCCEEDED,
            output=self.output,
        )


@pytest.fixture(scope="function")
def mock_executor_success() -> MockNodeExecutor:
    """返回成功的Mock执行器."""
    return MockNodeExecutor(output={"result": "ok"})


@pytest.fixture(scope="function")
def mock_executor_fail() -> MockNodeExecutor:
    """返回失败的Mock执行器."""
    return MockNodeExecutor(fail=True)
