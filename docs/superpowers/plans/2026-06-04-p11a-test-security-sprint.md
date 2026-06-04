# P11a — 稳定性冲刺：测试补强 + 安全修复 + 前端基础修复

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在2周内消除NEXUS最关键的安全风险和测试短板，使核心模块达到可生产部署的最低标准。

**架构：** 采用"风险优先"排序：安全修复（1天）→ 核心引擎测试（3天）→ Agent测试（2天）→ 0%模块测试（2天）→ 前端mock修复（2天）→ CI门禁（1天）。

**技术栈：** Python 3.11 / pytest / FastAPI / SQLAlchemy / Vue 3 / Docker

---

## 📁 文件结构总览

| 文件 | 职责 | 操作 |
|------|------|------|
| `.gitignore` | Git忽略规则 | 追加 `.env` |
| `nexus/engine/router_engine.py` | 工作流条件路由决策 | 已有代码，需补测试 |
| `nexus/engine/checkpoint.py` | 断点保存/恢复 | 已有代码，需补测试 |
| `nexus/engine/executors/*.py` | 节点执行器集合 | 已有代码，需补测试 |
| `nexus/agent/base.py` | Agent ReAct基类 | 已有代码，需补测试 |
| `nexus/agent/crew.py` | Crew多Agent编排 | 已有代码，需补测试 |
| `nexus/agent/llm_client.py` | LLM统一客户端 | 已有代码，需补测试 |
| `nexus/tools/code_review.py` | 代码审查工具 | 已有代码，需补测试 |
| `nexus/tools/github_tools.py` | GitHub API工具 | 已有代码，需补测试 |
| `nexus/tools/rag.py` | RAG工具集 | 已有代码，需补测试 |
| `nexus/utils/async_tasks.py` | 安全后台任务包装 | 已有代码，需补测试 |
| `nexus/mcp/server.py` | MCP Server实现 | 已有代码，需补测试 |
| `nexus-ui/src/views/Login.vue` | 登录页面 | 接入真实API |
| `nexus-ui/src/views/Workflows.vue` | 工作流列表 | 接入真实API |
| `nexus-ui/src/views/WorkflowRuns.vue` | 执行记录 | 接入真实API |
| `nexus-ui/src/views/Analytics.vue` | 分析面板 | 接入真实API |
| `nexus-ui/src/router/index.ts` | 路由配置 | 添加守卫 |
| `nexus-ui/src/api/index.ts` | API封装 | 已有，需扩展 |
| `.github/workflows/ci.yml` | CI配置 | 添加覆盖率门禁 |

---

## 工作包 1：安全修复（Day 1）

### 任务 1.1：`.env` 加入 `.gitignore`

**文件：**
- 修改：`.gitignore`

- [ ] **步骤 1：检查当前 `.gitignore` 内容**

```bash
cat .gitignore
```

- [ ] **步骤 2：追加 `.env` 到忽略列表**

```bash
echo "" >> .gitignore
echo "# Environment variables (contain secrets)" >> .gitignore
echo ".env" >> .gitignore
echo ".env.dev" >> .gitignore
echo ".env.prod" >> .gitignore
```

- [ ] **步骤 3：验证 `.env` 未被追踪**

```bash
git check-ignore -v .env
# 预期输出：.gitignore:4:.env	.env
```

- [ ] **步骤 4：确保 `.env.example` 仍被追踪**

```bash
git ls-files | grep "\.env"
# 预期输出：.env.example
```

- [ ] **步骤 5：Commit**

```bash
git add .gitignore
git commit -m "security: add .env files to .gitignore to prevent secret leakage"
```

---

### 任务 1.2：生产环境启动安全校验增强

**文件：**
- 修改：`nexus/api/main.py:28-63`

- [ ] **步骤 1：编写测试验证弱 SECRET_KEY 被拦截**

新建 `tests/test_production_security.py`：

```python
import pytest
from nexus.config import settings
from nexus.api.main import _validate_production_security


class TestProductionSecurity:
    """验证生产环境启动安全校验."""

    def test_weak_secret_key_rejected(self, monkeypatch):
        """弱 SECRET_KEY 应该触发 RuntimeError."""
        monkeypatch.setattr(settings, "SECRET_KEY", "short")
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(settings, "DEV_API_KEY", None)

        with pytest.raises(RuntimeError, match="SECRET_KEY is too weak"):
            _validate_production_security()

    def test_default_secret_key_rejected(self, monkeypatch):
        """默认 SECRET_KEY 应该触发 RuntimeError."""
        monkeypatch.setattr(settings, "SECRET_KEY", "nexus-dev-secret-not-for-production")
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(settings, "DEV_API_KEY", None)

        with pytest.raises(RuntimeError, match="SECRET_KEY is too weak"):
            _validate_production_security()

    def test_sqlite_in_production_rejected(self, monkeypatch):
        """生产环境使用 SQLite 应该触发 RuntimeError."""
        monkeypatch.setattr(settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///test.db")
        monkeypatch.setattr(settings, "DEV_API_KEY", None)

        with pytest.raises(RuntimeError, match="SQLite is not allowed"):
            _validate_production_security()

    def test_dev_api_key_in_production_rejected(self, monkeypatch):
        """生产环境设置 DEV_API_KEY 应该触发 RuntimeError."""
        monkeypatch.setattr(settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(settings, "DEV_API_KEY", "dev-key-123")

        with pytest.raises(RuntimeError, match="DEV_API_KEY must not be set"):
            _validate_production_security()

    def test_valid_production_config_passes(self, monkeypatch):
        """有效的生产环境配置应该通过校验."""
        monkeypatch.setattr(settings, "SECRET_KEY", "a" * 32)
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://test")
        monkeypatch.setattr(settings, "DEV_API_KEY", None)

        # 不应该抛出异常
        _validate_production_security()
```

- [ ] **步骤 2：运行测试验证通过**

```bash
cd D:/AI_learning/nexus
pytest tests/test_production_security.py -v
# 预期：5 passed
```

- [ ] **步骤 3：Commit**

```bash
git add tests/test_production_security.py
git commit -m "test(security): add production security validation tests"
```

---

## 工作包 2：核心引擎测试补强（Day 2-4）

### 任务 2.1：`router_engine.py` 测试（覆盖率 7% → 60%+）

**文件：**
- 修改/已有：`nexus/engine/router_engine.py`
- 新建：`tests/test_router_engine.py`

- [ ] **步骤 1：阅读 router_engine.py 确定测试范围**

```bash
cd D:/AI_learning/nexus
wc -l nexus/engine/router_engine.py
# 记录总行数，分析 public 方法
```

阅读文件，识别以下需要测试的方法：
- `RouterEngine.__init__()`
- `RouterEngine.evaluate_condition()`
- `RouterEngine._compare()`
- `RouterEngine._extract_value()`
- `RouterEngine.route()`

- [ ] **步骤 2：编写 RouterEngine 基础测试**

```python
import pytest
from nexus.engine.router_engine import RouterEngine
from nexus.engine.workflow_types import WorkflowDefinition, Node, Edge


class TestRouterEngine:
    """RouterEngine 条件路由决策测试."""

    @pytest.fixture
    def router(self):
        return RouterEngine()

    @pytest.fixture
    def sample_workflow(self):
        """创建一个简单工作流定义用于测试."""
        return WorkflowDefinition(
            nodes=[
                Node(id="start", type="start"),
                Node(id="condition", type="condition"),
                Node(id="branch_a", type="agent"),
                Node(id="branch_b", type="agent"),
                Node(id="end", type="end"),
            ],
            edges=[
                Edge(source="start", target="condition"),
                Edge(source="condition", target="branch_a", condition="x > 5"),
                Edge(source="condition", target="branch_b", condition="x <= 5"),
                Edge(source="branch_a", target="end"),
                Edge(source="branch_b", target="end"),
            ],
        )

    def test_evaluate_numeric_comparison_gt(self, router):
        """测试数值大于比较."""
        result = router.evaluate_condition("x > 5", {"x": 10})
        assert result is True

    def test_evaluate_numeric_comparison_gt_false(self, router):
        """测试数值大于比较（不满足）."""
        result = router.evaluate_condition("x > 5", {"x": 3})
        assert result is False

    def test_evaluate_numeric_comparison_eq(self, router):
        """测试数值等于比较."""
        result = router.evaluate_condition("x == 5", {"x": 5})
        assert result is True

    def test_evaluate_string_comparison(self, router):
        """测试字符串比较."""
        result = router.evaluate_condition('status == "active"', {"status": "active"})
        assert result is True

    def test_evaluate_missing_variable(self, router):
        """测试缺少变量时返回 False."""
        result = router.evaluate_condition("x > 5", {"y": 10})
        assert result is False

    def test_evaluate_invalid_condition(self, router):
        """测试无效条件表达式."""
        result = router.evaluate_condition("invalid @#$", {"x": 10})
        assert result is False

    def test_route_selects_correct_branch(self, router, sample_workflow):
        """测试路由选择正确的分支."""
        # 根据 condition 节点和上下文选择下一节点
        next_node = router.route(
            current_node_id="condition",
            workflow_def=sample_workflow,
            context={"x": 10},
        )
        assert next_node == "branch_a"

    def test_route_fallback_when_no_match(self, router, sample_workflow):
        """测试无匹配条件时的回退行为."""
        next_node = router.route(
            current_node_id="condition",
            workflow_def=sample_workflow,
            context={"x": 5},  # x > 5 为 False, x <= 5 为 True
        )
        assert next_node == "branch_b"

    def test_route_with_empty_workflow(self, router):
        """测试空工作流定义."""
        empty_workflow = WorkflowDefinition(nodes=[], edges=[])
        next_node = router.route(
            current_node_id="start",
            workflow_def=empty_workflow,
            context={},
        )
        assert next_node is None

    def test_compare_equal(self, router):
        """测试 _compare 等于比较."""
        assert router._compare(5, "==", 5) is True
        assert router._compare(5, "==", 3) is False

    def test_compare_not_equal(self, router):
        """测试 _compare 不等于比较."""
        assert router._compare(5, "!=", 3) is True
        assert router._compare(5, "!=", 5) is False

    def test_compare_greater_than(self, router):
        """测试 _compare 大于比较."""
        assert router._compare(10, ">", 5) is True
        assert router._compare(3, ">", 5) is False

    def test_compare_less_than_equal(self, router):
        """测试 _compare 小于等于比较."""
        assert router._compare(5, "<=", 5) is True
        assert router._compare(3, "<=", 5) is True
        assert router._compare(10, "<=", 5) is False

    def test_compare_contains(self, router):
        """测试 _compare 包含比较."""
        assert router._compare("hello world", "contains", "world") is True
        assert router._compare("hello", "contains", "xyz") is False

    def test_compare_invalid_operator(self, router):
        """测试 _compare 无效操作符."""
        assert router._compare(5, "invalid", 3) is False

    def test_extract_value_nested(self, router):
        """测试嵌套变量提取."""
        context = {"user": {"name": "Alice", "age": 30}}
        assert router._extract_value("user.name", context) == "Alice"
        assert router._extract_value("user.age", context) == 30

    def test_extract_value_top_level(self, router):
        """测试顶层变量提取."""
        assert router._extract_value("status", {"status": "active"}) == "active"

    def test_extract_value_missing(self, router):
        """测试缺失变量返回 None."""
        assert router._extract_value("missing", {"x": 1}) is None
```

- [ ] **步骤 3：运行测试**

```bash
pytest tests/test_router_engine.py -v
# 预期：根据实际实现调整，先确认测试结构正确
```

- [ ] **步骤 4：根据实际实现调整测试并修复失败项**

查看 `nexus/engine/router_engine.py` 的实际API签名，调整测试中的方法名和参数。

- [ ] **步骤 5：运行覆盖率检查**

```bash
pytest tests/test_router_engine.py --cov=nexus.engine.router_engine --cov-report=term-missing -v
# 预期：覆盖率 > 60%
```

- [ ] **步骤 6：Commit**

```bash
git add tests/test_router_engine.py
git commit -m "test(router): add comprehensive RouterEngine tests (7% → 60%+)"
```

---

### 任务 2.2：`checkpoint.py` 测试（覆盖率 16% → 60%+）

**文件：**
- 修改/已有：`nexus/engine/checkpoint.py`
- 新建：`tests/test_checkpoint.py`

- [ ] **步骤 1：阅读 checkpoint.py 确定测试范围**

```bash
wc -l nexus/engine/checkpoint.py
# 记录 public 方法
```

- [ ] **步骤 2：编写 CheckpointManager 测试**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.engine.checkpoint import CheckpointManager


class TestCheckpointManager:
    """CheckpointManager 断点保存/恢复测试."""

    @pytest.fixture
    def mock_db(self):
        """模拟数据库会话."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_s3(self):
        """模拟 S3 客户端."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def checkpoint_mgr(self, mock_db, mock_s3):
        return CheckpointManager(db_session=mock_db, s3_client=mock_s3)

    @pytest.mark.asyncio
    async def test_save_small_state_to_db(self, checkpoint_mgr, mock_db):
        """测试小状态直接保存到数据库."""
        state = {"step": 1, "data": "small"}
        run_id = "run_123"

        await checkpoint_mgr.save(run_id=run_id, state=state)

        # 验证数据库写入被调用
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_large_state_to_s3(self, checkpoint_mgr, mock_db, mock_s3):
        """测试大状态保存到 S3."""
        # 创建超过阈值的大状态
        state = {"data": "x" * 100000}
        run_id = "run_123"

        await checkpoint_mgr.save(run_id=run_id, state=state)

        # 验证 S3 上传被调用
        mock_s3.put_object.assert_called_once()
        # 验证数据库中保存了 S3 key
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_from_db(self, checkpoint_mgr, mock_db):
        """测试从数据库加载状态."""
        from nexus.models.workflow import CheckpointRecord

        expected_state = {"step": 5, "result": "done"}
        mock_record = MagicMock()
        mock_record.state_data = expected_state
        mock_record.state_s3_key = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute.return_value = mock_result

        state = await checkpoint_mgr.load(run_id="run_123")

        assert state == expected_state

    @pytest.mark.asyncio
    async def test_load_from_s3(self, checkpoint_mgr, mock_db, mock_s3):
        """测试从 S3 加载状态."""
        import json

        expected_state = {"step": 5, "data": "large"}
        mock_record = MagicMock()
        mock_record.state_data = None
        mock_record.state_s3_key = "checkpoints/run_123/latest.json"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute.return_value = mock_result

        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(expected_state).encode())
        }

        state = await checkpoint_mgr.load(run_id="run_123")

        assert state == expected_state
        mock_s3.get_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_not_found(self, checkpoint_mgr, mock_db):
        """测试状态不存在时返回 None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        state = await checkpoint_mgr.load(run_id="nonexistent")

        assert state is None

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, checkpoint_mgr, mock_db):
        """测试删除断点."""
        mock_record = MagicMock()
        mock_record.state_s3_key = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db.execute.return_value = mock_result

        await checkpoint_mgr.delete(run_id="run_123")

        mock_db.delete.assert_called_once_with(mock_record)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, checkpoint_mgr, mock_db):
        """测试列出断点."""
        mock_record1 = MagicMock()
        mock_record1.run_id = "run_1"
        mock_record1.created_at = "2024-01-01"

        mock_record2 = MagicMock()
        mock_record2.run_id = "run_2"
        mock_record2.created_at = "2024-01-02"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record1, mock_record2]
        mock_db.execute.return_value = mock_result

        checkpoints = await checkpoint_mgr.list_checkpoints()

        assert len(checkpoints) == 2
```

- [ ] **步骤 3：运行测试并修复**

```bash
pytest tests/test_checkpoint.py -v
# 根据实际API签名调整
```

- [ ] **步骤 4：运行覆盖率检查**

```bash
pytest tests/test_checkpoint.py --cov=nexus.engine.checkpoint --cov-report=term-missing -v
# 预期：覆盖率 > 60%
```

- [ ] **步骤 5：Commit**

```bash
git add tests/test_checkpoint.py
git commit -m "test(checkpoint): add CheckpointManager tests (16% → 60%+)"
```

---

### 任务 2.3：执行器测试（executors/* 覆盖率 16-34% → 60%+）

**文件：**
- 修改/已有：`nexus/engine/executors/*.py`
- 新建：`tests/test_executors.py`

- [ ] **步骤 1：识别所有执行器类型**

```bash
ls nexus/engine/executors/
# 列出所有执行器文件
```

- [ ] **步骤 2：编写通用执行器测试框架**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from nexus.engine.executors.boundary import StartNodeExecutor, EndNodeExecutor
from nexus.engine.executors.condition import ConditionNodeExecutor
from nexus.engine.executors.llm import LLMNodeExecutor


class TestStartNodeExecutor:
    """Start 节点执行器测试."""

    @pytest.fixture
    def executor(self):
        return StartNodeExecutor()

    @pytest.mark.asyncio
    async def test_start_node_returns_trigger_payload(self, executor):
        """Start 节点应返回 trigger_payload."""
        node = MagicMock()
        node.id = "start"
        inputs = {}
        state = MagicMock()
        state.trigger_payload = {"message": "hello"}

        result = await executor.execute(node, inputs, state, "run_1")

        assert result == {"message": "hello"}


class TestEndNodeExecutor:
    """End 节点执行器测试."""

    @pytest.fixture
    def executor(self):
        return EndNodeExecutor()

    @pytest.mark.asyncio
    async def test_end_node_returns_final_output(self, executor):
        """End 节点应返回最终输出."""
        node = MagicMock()
        node.id = "end"
        inputs = {"prev_result": "final"}
        state = MagicMock()

        result = await executor.execute(node, inputs, state, "run_1")

        assert result == {"prev_result": "final"}


class TestConditionNodeExecutor:
    """Condition 节点执行器测试."""

    @pytest.fixture
    def executor(self):
        return ConditionNodeExecutor()

    @pytest.mark.asyncio
    async def test_condition_evaluates_true(self, executor):
        """条件为真时返回 True."""
        node = MagicMock()
        node.id = "condition"
        node.config = {"expression": "x > 5"}
        inputs = {"x": 10}
        state = MagicMock()
        state.variables = {"x": 10}

        result = await executor.execute(node, inputs, state, "run_1")

        assert result is True

    @pytest.mark.asyncio
    async def test_condition_evaluates_false(self, executor):
        """条件为假时返回 False."""
        node = MagicMock()
        node.id = "condition"
        node.config = {"expression": "x > 5"}
        inputs = {"x": 3}
        state = MagicMock()
        state.variables = {"x": 3}

        result = await executor.execute(node, inputs, state, "run_1")

        assert result is False


class TestLLMNodeExecutor:
    """LLM 节点执行器测试."""

    @pytest.fixture
    def executor(self):
        return LLMNodeExecutor()

    @pytest.mark.asyncio
    async def test_llm_node_calls_client(self, executor):
        """LLM 节点应调用 LLM 客户端."""
        node = MagicMock()
        node.id = "llm"
        node.config = {
            "model": "gpt-4o",
            "system_prompt": "You are a helpful assistant.",
            "user_prompt": "Say hello",
        }
        inputs = {}
        state = MagicMock()
        state.variables = {}

        # Mock LLM client
        with patch("nexus.engine.executors.llm.get_llm_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.call.return_value = "Hello!"
            mock_get_client.return_value = mock_client

            result = await executor.execute(node, inputs, state, "run_1")

            mock_client.call.assert_called_once()
            assert result == "Hello!"
```

- [ ] **步骤 3-5：运行、修复、覆盖率检查、Commit**

---

## 工作包 3：Agent模块测试补强（Day 5-6）

### 任务 3.1：`agent/base.py` 测试（覆盖率 31% → 50%+）

**文件：**
- 修改/已有：`nexus/agent/base.py`
- 新建：`tests/test_agent_base.py`

- [ ] **步骤 1：编写 BaseAgent 核心行为测试**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.agent.base import BaseAgent


class TestBaseAgent:
    """BaseAgent ReAct + ToolUse + Memory 测试."""

    @pytest.fixture
    def agent(self):
        return BaseAgent(
            name="test_agent",
            role="tester",
            goal="test things",
            backstory="I test things.",
        )

    def test_agent_initialization(self, agent):
        """测试 Agent 初始化."""
        assert agent.name == "test_agent"
        assert agent.role == "tester"
        assert agent.goal == "test things"
        assert agent.backstory == "I test things."

    @pytest.mark.asyncio
    async def test_agent_execute_with_no_tools(self, agent):
        """测试无工具时的 Agent 执行."""
        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "Task completed"}

            result = await agent.execute("Do something simple")

            assert result == "Task completed"
            mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_uses_tool_when_requested(self, agent):
        """测试 Agent 在 LLM 请求时调用工具."""
        tool_mock = MagicMock()
        tool_mock.name = "calculator"
        tool_mock.execute = AsyncMock(return_value="42")
        agent.tools = [tool_mock]

        # 第一轮：LLM 决定使用工具
        # 第二轮：LLM 根据工具结果给出最终回答
        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [
                {
                    "tool_calls": [
                        {"name": "calculator", "arguments": {"expr": "20+22"}}
                    ]
                },
                {"content": "The answer is 42"},
            ]

            result = await agent.execute("Calculate 20+22")

            tool_mock.execute.assert_called_once_with(expr="20+22")
            assert result == "The answer is 42"

    @pytest.mark.asyncio
    async def test_agent_max_iterations_reached(self, agent):
        """测试达到最大迭代次数时停止."""
        agent.max_iterations = 2

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            # LLM 每次都请求工具，触发无限循环
            mock_llm.return_value = {
                "tool_calls": [
                    {"name": "dummy", "arguments": {}}
                ]
            }

            with pytest.raises(Exception, match="max iterations"):
                await agent.execute("Infinite loop task")

    @pytest.mark.asyncio
    async def test_agent_memory_integration(self, agent):
        """测试 Agent 记忆功能."""
        memory_mock = MagicMock()
        memory_mock.add = MagicMock()
        memory_mock.get_relevant = MagicMock(return_value=["previous context"])
        agent.memory = memory_mock

        with patch.object(agent, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "Done"}

            await agent.execute("Remember this")

            # 验证记忆被添加
            memory_mock.add.assert_called()
            # 验证记忆被检索
            memory_mock.get_relevant.assert_called()
```

- [ ] **步骤 2-4：运行、修复、覆盖率检查、Commit**

---

### 任务 3.2：`agent/crew.py` 测试（覆盖率 24% → 50%+）

**文件：**
- 修改/已有：`nexus/agent/crew.py`
- 新建：`tests/test_crew_extended.py`

- [ ] **步骤 1：编写 Crew 三种模式测试**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.agent.crew import Crew


class TestCrewSequential:
    """Crew Sequential 模式测试."""

    @pytest.fixture
    def crew(self):
        return Crew(name="test_crew", mode="sequential")

    @pytest.mark.asyncio
    async def test_sequential_execution_order(self, crew):
        """测试 Sequential 模式按顺序执行 Agent."""
        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.execute = AsyncMock(return_value="result1")

        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.execute = AsyncMock(return_value="result2")

        crew.agents = [agent1, agent2]

        result = await crew.execute("Process data")

        # 验证顺序执行
        agent1.execute.assert_called_once()
        agent2.execute.assert_called_once()
        # agent2 应该收到 agent1 的输出作为上下文
        call_args = agent2.execute.call_args
        assert "result1" in str(call_args)


class TestCrewParallel:
    """Crew Parallel 模式测试."""

    @pytest.fixture
    def crew(self):
        return Crew(name="test_crew", mode="parallel")

    @pytest.mark.asyncio
    async def test_parallel_execution(self, crew):
        """测试 Parallel 模式并行执行 Agent."""
        agent1 = MagicMock()
        agent1.name = "agent1"
        agent1.execute = AsyncMock(return_value="result1")

        agent2 = MagicMock()
        agent2.name = "agent2"
        agent2.execute = AsyncMock(return_value="result2")

        crew.agents = [agent1, agent2]

        result = await crew.execute("Process data")

        # 两个 Agent 都被调用
        agent1.execute.assert_called_once()
        agent2.execute.assert_called_once()
        # 结果应该包含两个 Agent 的输出
        assert "result1" in str(result)
        assert "result2" in str(result)


class TestCrewHierarchical:
    """Crew Hierarchical 模式测试."""

    @pytest.fixture
    def crew(self):
        return Crew(name="test_crew", mode="hierarchical")

    @pytest.mark.asyncio
    async def test_hierarchical_delegation(self, crew):
        """测试 Hierarchical 模式任务分解."""
        manager = MagicMock()
        manager.name = "manager"
        manager.role = "manager"

        worker1 = MagicMock()
        worker1.name = "worker1"
        worker1.execute = AsyncMock(return_value="worker1_result")

        worker2 = MagicMock()
        worker2.name = "worker2"
        worker2.execute = AsyncMock(return_value="worker2_result")

        crew.agents = [manager, worker1, worker2]
        crew.manager = manager

        # Mock manager 的分解和聚合
        with patch.object(crew, "_delegate", new_callable=AsyncMock) as mock_delegate:
            mock_delegate.return_value = [
                {"agent": "worker1", "task": "subtask1"},
                {"agent": "worker2", "task": "subtask2"},
            ]

            with patch.object(crew, "_aggregate", new_callable=AsyncMock) as mock_aggregate:
                mock_aggregate.return_value = "final_result"

                result = await crew.execute("Complex task")

                mock_delegate.assert_called_once()
                mock_aggregate.assert_called_once()
                assert result == "final_result"
```

- [ ] **步骤 2-4：运行、修复、覆盖率检查、Commit**

---

## 工作包 4：0%覆盖率模块测试（Day 7-8）

### 任务 4.1：`tools/code_review.py` 测试

**文件：**
- 新建：`tests/test_code_review_tools.py`

- [ ] **步骤 1：编写代码审查工具测试**

```python
import pytest
from nexus.tools.code_review import (
    parse_diff,
    detect_language,
    security_check,
    perf_check,
    style_check,
)


class TestParseDiff:
    """Diff 解析测试."""

    def test_parse_simple_diff(self):
        """测试简单 diff 解析."""
        diff_text = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 def hello():
-    print("old")
+    print("new")
"""
        result = parse_diff(diff_text)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_parse_empty_diff(self):
        """测试空 diff."""
        result = parse_diff("")
        assert result == []


class TestDetectLanguage:
    """语言检测测试."""

    def test_detect_python(self):
        """检测 Python 文件."""
        assert detect_language("test.py") == "python"

    def test_detect_javascript(self):
        """检测 JavaScript 文件."""
        assert detect_language("test.js") == "javascript"

    def test_detect_unknown(self):
        """检测未知文件类型."""
        assert detect_language("test.unknown") == "unknown"


class TestSecurityCheck:
    """安全检查测试."""

    def test_detect_hardcoded_secret(self):
        """检测硬编码密钥."""
        code = 'API_KEY = "sk-1234567890abcdef"'
        findings = security_check(code, "python")
        assert len(findings) > 0
        assert any("secret" in f.lower() or "key" in f.lower() for f in findings)

    def test_detect_sql_injection(self):
        """检测 SQL 注入风险."""
        code = 'query = f"SELECT * FROM users WHERE id = {user_id}"'
        findings = security_check(code, "python")
        assert any("sql" in f.lower() for f in findings)

    def test_detect_eval_usage(self):
        """检测 eval 使用."""
        code = "result = eval(user_input)"
        findings = security_check(code, "python")
        assert any("eval" in f.lower() for f in findings)

    def test_safe_code_no_findings(self):
        """安全代码应无发现."""
        code = 'def hello():\n    print("hello")'
        findings = security_check(code, "python")
        assert findings == []


class TestPerfCheck:
    """性能检查测试."""

    def test_detect_n_plus_one(self):
        """检测 N+1 查询模式."""
        code = """
for user in users:
    orders = db.query(Order).filter(Order.user_id == user.id).all()
"""
        findings = perf_check(code, "python")
        assert any("n+1" in f.lower() for f in findings)

    def test_detect_list_append_in_loop(self):
        """检测循环内列表追加."""
        code = """
result = []
for i in range(1000):
    result.append(i * 2)
"""
        findings = perf_check(code, "python")
        # 根据实际情况调整断言
        assert isinstance(findings, list)


class TestStyleCheck:
    """风格检查测试."""

    def test_detect_long_function(self):
        """检测过长函数."""
        code = "\n".join([f"    line_{i} = {i}" for i in range(60)])
        code = f"def long_func():\n{code}"
        findings = style_check(code, "python")
        assert any("length" in f.lower() or "long" in f.lower() for f in findings)

    def test_detect_deep_nesting(self):
        """检测过深嵌套."""
        code = """
def nested():
    if a:
        if b:
            if c:
                if d:
                    if e:
                        if f:
                            pass
"""
        findings = style_check(code, "python")
        assert any("nest" in f.lower() for f in findings)
```

- [ ] **步骤 2-4：运行、修复、Commit**

---

### 任务 4.2：`tools/github_tools.py` 测试

**文件：**
- 新建：`tests/test_github_tools.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.tools.github_tools import get_pr_diff, post_review_comment, list_pr_files


class TestGetPRDiff:
    """获取 PR Diff 测试."""

    @pytest.mark.asyncio
    async def test_get_pr_diff_success(self):
        """测试成功获取 PR diff."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "diff --git a/file.py b/file.py"
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            result = await get_pr_diff("owner", "repo", 1)
            assert "diff" in result

    @pytest.mark.asyncio
    async def test_get_pr_diff_not_found(self):
        """测试 PR 不存在."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            with pytest.raises(Exception, match="not found"):
                await get_pr_diff("owner", "repo", 999)
```

- [ ] **步骤 2-4：运行、修复、Commit**

---

### 任务 4.3：`utils/async_tasks.py` 测试

**文件：**
- 新建：`tests/test_async_tasks.py`

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.utils.async_tasks import safe_background_task


class TestSafeBackgroundTask:
    """安全后台任务包装测试."""

    @pytest.mark.asyncio
    async def test_task_success_no_exception(self):
        """成功任务不应抛出异常."""
        async def good_task():
            return "success"

        task = safe_background_task(good_task())
        result = await task
        assert result == "success"

    @pytest.mark.asyncio
    async def test_task_failure_caught_and_logged(self):
        """失败任务应被捕获并记录."""
        async def bad_task():
            raise ValueError("something wrong")

        with patch("nexus.utils.async_tasks.logger") as mock_logger:
            task = safe_background_task(bad_task())
            # 等待任务完成
            try:
                await task
            except Exception:
                pass

            # 验证异常被记录
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_task_updates_run_status_on_failure(self):
        """工作流执行失败时应更新 Run 状态."""
        async def failing_task():
            raise RuntimeError("workflow failed")

        with patch("nexus.utils.async_tasks.update_run_status") as mock_update:
            task = safe_background_task(failing_task())
            try:
                await task
            except Exception:
                pass

            mock_update.assert_called_with(status="failed")
```

- [ ] **步骤 2-4：运行、修复、Commit**

---

### 任务 4.4：`mcp/server.py` 测试

**文件：**
- 新建：`tests/test_mcp_server.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nexus.mcp.server import NexusMCPServer


class TestNexusMCPServer:
    """MCP Server 测试."""

    @pytest.fixture
    def mock_tool_registry(self):
        registry = MagicMock()
        registry.list_tools.return_value = [
            {"name": "tool1", "description": "Test tool"}
        ]
        return registry

    def test_server_initialization(self, mock_tool_registry):
        """测试 MCP Server 初始化."""
        server = NexusMCPServer(mock_tool_registry, name="test")
        assert server.name == "test"
        assert server.tool_registry == mock_tool_registry

    @pytest.mark.asyncio
    async def test_server_exposes_tools(self, mock_tool_registry):
        """测试 Server 暴露工具列表."""
        server = NexusMCPServer(mock_tool_registry, name="test")

        tools = await server.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "tool1"

    @pytest.mark.asyncio
    async def test_server_calls_tool(self, mock_tool_registry):
        """测试通过 Server 调用工具."""
        server = NexusMCPServer(mock_tool_registry, name="test")

        mock_tool_registry.execute_tool = AsyncMock(return_value="tool_result")

        result = await server.call_tool("tool1", {"arg": "value"})
        assert result == "tool_result"
        mock_tool_registry.execute_tool.assert_called_with("tool1", {"arg": "value"})
```

- [ ] **步骤 2-4：运行、修复、Commit**

---

## 工作包 5：前端 Mock 修复（Day 9-10）

### 任务 5.1：`Login.vue` 接入真实 JWT 认证

**文件：**
- 修改：`nexus-ui/src/views/Login.vue`
- 修改：`nexus-ui/src/api/index.ts`（添加 authApi）
- 新建/修改：`nexus-ui/src/stores/auth.ts`

- [ ] **步骤 1：创建 Pinia Auth Store**

新建/修改 `nexus-ui/src/stores/auth.ts`：

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('nexus_token'))
  const user = ref<{ email: string; name: string } | null>(null)
  const isAuthenticated = computed(() => !!token.value)

  async function login(email: string, password: string) {
    const response = await authApi.login({ email, password })
    token.value = response.data.token
    localStorage.setItem('nexus_token', response.data.token)
    user.value = response.data.user
    return response.data
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('nexus_token')
  }

  async function fetchUser() {
    if (!token.value) return
    try {
      const response = await authApi.me()
      user.value = response.data
    } catch {
      logout()
    }
  }

  return { token, user, isAuthenticated, login, logout, fetchUser }
})
```

- [ ] **步骤 2：扩展 authApi**

在 `nexus-ui/src/api/index.ts` 中添加：

```typescript
export const authApi = {
  login: (data: { email: string; password: string }) =>
    api.post('/auth/login', data),
  me: () =>
    api.get('/auth/me'),
  logout: () =>
    api.post('/auth/logout'),
}
```

- [ ] **步骤 3：修改 Login.vue 使用真实 API**

修改 `nexus-ui/src/views/Login.vue`：

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { message } from 'ant-design-vue'

const router = useRouter()
const authStore = useAuthStore()
const email = ref('')
const password = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!email.value || !password.value) {
    message.error('请输入邮箱和密码')
    return
  }

  loading.value = true
  try {
    await authStore.login(email.value, password.value)
    message.success('登录成功')
    router.push('/dashboard')
  } catch (error: any) {
    message.error(error.response?.data?.error?.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>
```

- [ ] **步骤 4：Commit**

```bash
git add nexus-ui/src/stores/auth.ts nexus-ui/src/api/index.ts nexus-ui/src/views/Login.vue
git commit -m "feat(auth): implement real JWT login with Pinia store"
```

---

### 任务 5.2：`Workflows.vue` 接入真实 API

**文件：**
- 修改：`nexus-ui/src/views/Workflows.vue`

- [ ] **步骤 1：替换 mock 数据为 API 调用**

修改 `Workflows.vue` 的 script 部分：

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { workflowApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { message } from 'ant-design-vue'

const router = useRouter()
const authStore = useAuthStore()
const workflows = ref([])
const loading = ref(false)

async function fetchWorkflows() {
  loading.value = true
  try {
    const response = await workflowApi.list()
    workflows.value = response.data.items || []
  } catch (error: any) {
    message.error(error.response?.data?.error?.message || '获取工作流失败')
  } finally {
    loading.value = false
  }
}

async function handleDelete(id: string) {
  try {
    await workflowApi.delete(id)
    message.success('删除成功')
    await fetchWorkflows()
  } catch (error: any) {
    message.error(error.response?.data?.error?.message || '删除失败')
  }
}

async function handleRun(id: string) {
  try {
    await workflowApi.trigger(id)
    message.success('执行已触发')
  } catch (error: any) {
    message.error(error.response?.data?.error?.message || '触发失败')
  }
}

onMounted(() => {
  fetchWorkflows()
})
</script>
```

- [ ] **步骤 2：Commit**

```bash
git add nexus-ui/src/views/Workflows.vue
git commit -m "feat(ui): connect Workflows.vue to real API, replace mock data"
```

---

### 任务 5.3：添加路由守卫

**文件：**
- 修改：`nexus-ui/src/router/index.ts`

- [ ] **步骤 1：实现路由守卫**

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // ... existing routes
  ],
})

// 路由守卫：未登录用户重定向到登录页
router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  const publicRoutes = ['/login', '/register']

  if (!authStore.isAuthenticated && !publicRoutes.includes(to.path)) {
    next('/login')
  } else if (authStore.isAuthenticated && to.path === '/login') {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
```

- [ ] **步骤 2：Commit**

```bash
git add nexus-ui/src/router/index.ts
git commit -m "feat(ui): add route guard for authentication protection"
```

---

## 工作包 6：CI/CD 覆盖率门禁（Day 11-12）

### 任务 6.1：CI 配置覆盖率门禁

**文件：**
- 修改：`.github/workflows/ci.yml`

- [ ] **步骤 1：修改 CI 配置添加覆盖率检查**

```yaml
name: CI

on:
  push:
    branches: [main, codex/**]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Run tests with coverage
        run: |
          pytest tests/ -v --cov=nexus --cov-report=term-missing --cov-fail-under=60

      - name: Generate coverage report
        if: always()
        run: |
          pytest tests/ --cov=nexus --cov-report=xml

      - name: Upload coverage to Codecov
        if: always()
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          fail_ci_if_error: false

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: nexus-ui/package-lock.json

      - name: Install dependencies
        working-directory: nexus-ui
        run: npm ci

      - name: Run lint
        working-directory: nexus-ui
        run: npm run lint

      - name: Run type check
        working-directory: nexus-ui
        run: npm run type-check

      - name: Build
        working-directory: nexus-ui
        run: npm run build

  docker:
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build backend Docker image
        run: docker build --target development -t nexus-api:test .

      - name: Build frontend Docker image
        run: docker build -t nexus-ui:test ./nexus-ui
```

- [ ] **步骤 2：Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add coverage gate (60%) and frontend lint/type-check to CI"
```

---

### 任务 6.2：运行全量测试验证覆盖率

- [ ] **步骤 1：运行全量测试**

```bash
cd D:/AI_learning/nexus
pytest tests/ -v --cov=nexus --cov-report=term-missing
```

- [ ] **步骤 2：检查覆盖率是否达到 60%**

查看输出中的总覆盖率，确认 ≥60%。

- [ ] **步骤 3：如未达标，识别缺口模块并补充**

```bash
pytest tests/ --cov=nexus --cov-report=html
# 打开 htmlcov/index.html 查看未覆盖代码
```

- [ ] **步骤 4：Commit 最终状态**

```bash
git add .
git commit -m "test: complete P11a coverage improvement (46% → 60%+), all critical modules tested"
```

---

## 📊 验收标准

| 验收项 | 目标 | 验证方式 |
|--------|------|---------|
| `.env` 在 gitignore 中 | ✅ | `git check-ignore -v .env` |
| 核心引擎覆盖率 | ≥60% | `pytest --cov=nexus.engine` |
| Agent模块覆盖率 | ≥50% | `pytest --cov=nexus.agent` |
| 0%模块清零 | 0个 | `pytest --cov=nexus.tools` etc. |
| CI覆盖率门禁 | ≥60% | `.github/workflows/ci.yml` |
| Login.vue 真实认证 | ✅ | 手动测试登录流程 |
| Workflows.vue 真实数据 | ✅ | 页面展示真实工作流列表 |
| 路由守卫 | ✅ | 未登录访问 `/dashboard` 被重定向 |

---

**计划创建时间：** 2026-06-04  
**预计工期：** 10个工作日（2周）  
**负责人：** AI Assistant  
**审核状态：** 待审核
