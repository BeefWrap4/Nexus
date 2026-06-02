# NEXUS - 企业级多Agent协作编排引擎

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.4+-4FC08D.svg)](https://vuejs.org)

> NEXUS 是一个**通用多Agent协作编排平台**，支持开发者通过 API/SDK 构建复杂的多Agent工作流，同时支持业务人员通过可视化界面拖拽配置业务流程。

---

## 核心特性

| 特性 | 描述 |
|------|------|
| **DAG工作流引擎** | 基于有向图的工作流编排，支持串行/并行/条件分支/循环 |
| **事件驱动架构** | Pub/Sub模式松耦合通信，Redis-backed持久化 |
| **状态持久化** | 每步Checkpoint，支持暂停/恢复/回滚/分叉 |
| **人机协作原生** | HITL作为一等公民，4种审批类型 |
| **MCP工具标准** | 兼容Model Context Protocol，统一工具治理 |
| **LLM网关** | LiteLLM Proxy统一管理，路由/回退/预算/审计 |
| **多租户隔离** | PostgreSQL RLS，企业级SaaS架构 |

---

## 系统架构

```
+--------------+   +--------------+   +--------------+
|  Web控制台    |   | 可视化编排器  |   | 审批面板     |
|  (Vue3)      |   | (Vue-Flow)   |   | (Ant Design) |
+------+-------+   +------+-------+   +------+-------+
       +------------------+------------------+
                          |
                          v
+-----------------------------------------------------+
|  API Gateway (FastAPI)                              |
|  REST API + WebSocket + MCP Gateway                 |
+-----------------------------------------------------+
|  编排引擎核心 (WorkflowEngine)                       |
|  DAG执行 + 状态机 + HITL + 事件总线 + 检查点         |
+-----------------------------------------------------+
|  Agent运行时 (BaseAgent)                            |
|  LLM调用 + 决策解析 + 信任模型 + 记忆系统             |
+-----------------------------------------------------+
|  基础设施 (LiteLLM + PostgreSQL + Redis + S3)       |
+-----------------------------------------------------+
```

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd nexus
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的API密钥
```

### 3. 启动基础设施（Docker）

```bash
docker-compose up -d postgres redis litellm minio
```

### 4. 初始化数据库

```bash
pip install -r requirements.txt
python nexus_cli.py db init
python nexus_cli.py db migrate
python nexus_cli.py db seed
```

### 5. 启动后端

```bash
python nexus_cli.py run
# 或
uvicorn nexus.api.main:app --reload
```

API文档: http://localhost:8000/docs

### 6. 启动前端

```bash
cd nexus-ui
npm install
npm run dev
```

前端地址: http://localhost:5173

---

## 项目结构

```
nexus/                          # 后端
|-- nexus/
|   |-- api/                    # REST API + WebSocket
|   |-- engine/                 # 核心编排引擎
|   |   |-- workflow_engine.py  # DAG执行引擎
|   |   |-- state_manager.py    # 状态管理
|   |   |-- checkpoint.py       # 检查点/回滚
|   |   |-- hitl_controller.py  # 人工审批
|   |   |-- node_executors.py   # 节点执行器
|   |-- agent/                  # Agent运行时
|   |   |-- base.py             # Agent基类
|   |   |-- llm_client.py       # LLM客户端
|   |   |-- memory.py           # 记忆系统
|   |-- services/               # Service层 (CRUD)
|   |-- models/                 # 数据库ORM模型
|   |-- tools/                  # 工具注册中心 (MCP)
|   |-- security/               # 认证/授权/PII
|-- tests/                      # 测试套件
|   |-- conftest.py             # pytest配置和fixtures
|   |-- test_workflow_engine.py # 引擎单元测试
|   |-- test_services.py        # Service层测试
|   |-- test_api.py             # API集成测试
|-- nexus_cli.py                # CLI工具
|-- requirements.txt
|-- pytest.ini                  # pytest配置
|-- docker-compose.yml

nexus-ui/                       # 前端
|-- src/
|   |-- views/                  # 页面视图
|   |   |-- WorkflowEditor.vue  # 可视化编排器
|   |   |-- RunMonitor.vue      # 实时监控
|   |   |-- HITLTasks.vue       # 审批任务
|   |-- api/                    # HTTP + WebSocket
|   |-- stores/                 # Pinia状态管理
|-- package.json
```

---

## 架构说明

### 编排引擎 (WorkflowEngine)

NEXUS的核心是**DAG工作流执行引擎**，设计灵感来源于：

- **LangGraph**: 图状态机 + 增量状态更新
- **Temporal**: 确定性Workflow + 非确定性Activity分离
- **Dify**: 队列驱动并行执行 + 变量池系统

引擎采用**Pregel-inspired Super-Step**执行模型：

1. **验证**: 检查工作流定义合法性（循环依赖、边界节点）
2. **注入**: 自动添加start/end边界节点（如未显式定义）
3. **调度**: 每轮获取所有依赖已满足的节点，并行执行
4. **合并**: 收集各节点结果，增量更新全局状态
5. **持久化**: 每步Checkpoint到PostgreSQL
6. **广播**: 通过EventBus发布状态更新（WebSocket推送）

### 三层变量系统

借鉴Dify的变量设计，支持：

- **env_vars**: 环境变量（租户级配置、密钥）
- **run_vars**: 运行级变量（节点间传递的中间结果）
- **node_outputs**: 节点输出（执行完成后聚合）

### 状态生命周期

```
PENDING -> RUNNING -> [COMPLETED | FAILED | CANCELLED]
              |
              v
           PAUSED (HITL等待人工响应)
              |
              v
           RUNNING (恢复)
```

### 多租户隔离

- 所有数据表包含 `tenant_id` 字段
- Service层所有查询自动过滤租户
- PostgreSQL Row-Level Security（可选启用）

---

## API文档

### REST API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/v1/workflows` | GET/POST | 工作流列表/创建 |
| `/api/v1/workflows/{id}` | GET/PUT/DELETE | 工作流详情/更新/删除 |
| `/api/v1/workflows/{id}/runs` | POST | 触发执行 |
| `/api/v1/workflows/{id}/runs` | GET | 列出执行记录 |
| `/api/v1/workflows/{id}/versions` | POST/GET | 版本管理 |
| `/api/v1/workflows/{id}/clone` | POST | 克隆工作流 |
| `/api/v1/agents` | GET/POST | Agent列表/创建 |
| `/api/v1/agents/{id}` | GET/PUT/DELETE | Agent详情/更新/删除 |
| `/api/v1/tools` | GET/POST | 工具注册 |
| `/api/v1/runs/{id}` | GET | 执行状态 |
| `/api/v1/runs/{id}/cancel` | POST | 取消执行 |
| `/api/v1/runs/{id}/pause` | POST | 暂停执行 |
| `/api/v1/runs/{id}/resume` | POST | 恢复执行 |
| `/api/v1/runs/{id}/retry` | POST | 重试执行 |
| `/api/v1/runs/{id}/logs` | GET | 执行日志 |
| `/api/v1/runs/{id}/artifacts` | GET | 输出产物 |
| `/api/v1/hitl/tasks` | GET/POST | 审批任务 |

### WebSocket

```
ws://localhost:8000/ws/v1/runs/{run_id}
```

实时接收执行状态更新、HITL审批请求。

### 交互式API文档

启动服务后访问：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `APP_NAME` | `NEXUS` | 应用名称 |
| `APP_VERSION` | `0.1.0` | 应用版本 |
| `ENVIRONMENT` | `development` | 运行环境 (development/staging/production) |
| `DEBUG` | `False` | 调试模式 |
| `SECRET_KEY` | `change-me-in-production` | JWT签名密钥 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Access Token有效期（分钟） |
| `DATABASE_URL` | `postgresql+asyncpg://nexus:nexus@localhost:5432/nexus` | 数据库连接URL |
| `DATABASE_POOL_SIZE` | `10` | 连接池大小 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis连接URL |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LiteLLM代理地址 |
| `LITELLM_API_KEY` | `None` | LiteLLM API密钥 |
| `DEFAULT_LLM_MODEL` | `gpt-4o` | 默认LLM模型 |
| `DEFAULT_LLM_PROVIDER` | `openai` | 默认LLM提供商 |
| `DEFAULT_LLM_TIMEOUT` | `120.0` | LLM调用超时（秒） |
| `DEFAULT_LLM_MAX_TOKENS` | `4000` | 默认最大Token数 |
| `DEFAULT_LLM_TEMPERATURE` | `0.7` | 默认Temperature |
| `LLM_MAX_RETRIES` | `3` | LLM调用最大重试次数 |
| `LLM_MAX_CONCURRENT_CALLS` | `10` | LLM最大并发数 |
| `S3_ENDPOINT` | `http://localhost:9000` | S3/MinIO端点 |
| `S3_ACCESS_KEY` | `nexus` | S3访问密钥 |
| `S3_SECRET_KEY` | `nexus-secret-key` | S3秘密密钥 |
| `S3_BUCKET` | `nexus-artifacts` | S3存储桶 |
| `MAX_WORKFLOW_STEPS` | `500` | 工作流最大执行步数 |
| `WORKFLOW_TIMEOUT_SECONDS` | `3600` | 工作流超时（秒） |
| `DEFAULT_HITL_TIMEOUT_SECONDS` | `86400` | HITL审批超时（秒） |
| `AUDIT_LOG_RETENTION_DAYS` | `90` | 审计日志保留天数 |
| `ENABLE_PROMETHEUS` | `True` | 启用Prometheus指标 |
| `ENABLE_OPENTELEMETRY` | `False` | 启用OpenTelemetry链路追踪 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

---

## 测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio httpx aiosqlite

# 运行所有测试
pytest

# 运行特定模块
pytest tests/test_workflow_engine.py -v
pytest tests/test_services.py -v
pytest tests/test_api.py -v

# 运行慢测试
pytest -m slow

# 运行集成测试（需要外部服务）
pytest -m integration

# 生成覆盖率报告
pytest --cov=nexus --cov-report=html
```

---

## 设计来源

NEXUS 基于 [WAT (Werewolf-Agent-Team)](https://github.com/your-org/wat) 狼人杀多Agent博弈系统演化而来，借鉴了以下业界最佳实践：

| 来源项目 | 借鉴内容 |
|---------|---------|
| **LangGraph** | 图状态机 + Checkpoint持久化 |
| **Temporal** | 确定性Workflow + 事件溯源 |
| **Dify** | 可视化编排 + 变量池 |
| **CrewAI** | Role-Playing Agent设计 |
| **MCP** | 工具协议标准 |
| **LiteLLM** | LLM统一网关 |

---

## 许可证

MIT License
