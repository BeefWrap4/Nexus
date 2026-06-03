# NEXUS - 企业级多Agent协作编排引擎

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.4+-4FC08D.svg)](https://vuejs.org)
[![Tests](https://img.shields.io/badge/tests-245%20passed-brightgreen.svg)]()

> NEXUS 是一个**通用多Agent协作编排平台**，支持开发者通过 API/SDK 构建复杂的多Agent工作流，同时支持业务人员通过可视化界面拖拽配置业务流程。
> 
> 覆盖从单Agent执行到多Agent协作（Crew）、从工作流编排到LLM全链路观测的完整能力栈。

---

## 核心特性

| 特性 | 描述 |
|------|------|
| **DAG工作流引擎** | 基于有向图的工作流编排，支持串行/并行/条件分支/循环 |
| **多Agent协作 (Crew)** | Hierarchical / Sequential / Parallel 三种协作模式，Manager-Worker 任务分解与聚合 |
| **事件驱动架构** | Pub/Sub模式松耦合通信，Redis-backed持久化 |
| **状态持久化** | 每步Checkpoint，支持暂停/恢复/回滚/分叉 |
| **人机协作原生** | HITL作为一等公民，4种审批类型 |
| **MCP工具标准** | 兼容Model Context Protocol，统一工具治理 |
| **LLM网关** | LiteLLM Proxy统一管理多供应商，支持路由/回退/预算/审计 |
| **Prompt管理** | 版本化Prompt模板，动态变量解析，A/B实验支持 |
| **Trace追踪** | LLM调用全链路追踪，成本与延迟分析 |
| **Eval评估** | 自动化评测引擎，支持规则/模型/人工多维度评估 |
| **代码审查Agent** | 自动PR审查（安全、性能、风格），GitHub Webhook集成 |
| **语义缓存** | Smart Cache 集成，RAG增强的LLM响应缓存 |
| **多租户隔离** | PostgreSQL RLS + 端点级租户过滤，企业级SaaS架构 |
| **API Key 认证** | HMAC-SHA256 数据库验证，支持过期/撤销/速率限制 |
| **安全加固** | RBAC 权限引擎 + PII 检测预留 + 生产安全校验 |
| **可观测性** | Prometheus + Grafana 指标监控，OpenTelemetry链路追踪 |

---

## 开发进度

| Phase | 功能 | 状态 |
|-------|------|------|
| P1 | 基础架构（FastAPI + Vue3 + 多租户） | ✅ |
| P2 | DAG工作流引擎 | ✅ |
| P3 | Agent基础（ReAct + 工具调用） | ✅ |
| P4 | Agent深化（Memory + Crew协作） | ✅ |
| P5 | MCP工具集成 | ✅ |
| P6 | Prompt管理 / Trace追踪 / Eval评估 | ✅ |
| P7 | 生产部署（Docker + CI/CD + 监控） | ✅ |
| P8 | Code Review Agent | ✅ |
| P9 | 语义缓存（Smart Cache） | ✅ |
| P10 | 多Agent协作增强（Crew三种模式） | ✅ |
| P11 | 待规划 | 🔜 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端层 (Vue3)                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Dashboard│ │ 工作流编排 │ │ Crew管理 │ │ Prompts  │           │
│  │ 仪表盘   │ │ (Vue-Flow)│ │ 团队    │ │ 模板管理 │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Traces   │ │ Eval     │ │ Code     │ │ 审批面板 │           │
│  │ 追踪    │ │ 评估    │ │ Review  │ │ (HITL)  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST API / WebSocket
                           v
┌─────────────────────────────────────────────────────────────────┐
│  API Gateway (FastAPI)                                          │
│  REST API + WebSocket + MCP Gateway                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────────┐
│  编排引擎核心 (WorkflowEngine + Builder)                           │
│  DAG执行 + 状态机 + HITL + 事件总线 + 检查点 + 引擎工厂            │
├─────────────────────────────────────────────────────────────────┤
│  Agent运行时                                                     │
│  ├─ BaseAgent: ReAct循环 + LLM调用 + 决策解析 + 记忆系统          │
│  └─ Crew: Hierarchical / Sequential / Parallel 协作模式          │
├─────────────────────────────────────────────────────────────────┤
│  支撑服务                                                        │
│  ├─ Prompt引擎（模板解析 + 版本管理 + A/B实验）                   │
│  ├─ Trace追踪器（LLM调用全链路记录）                              │
│  ├─ Eval引擎（自动化评测 + 指标计算）                             │
│  └─ Code Review（安全/性能/风格检查）                             │
├─────────────────────────────────────────────────────────────────┤
│  基础设施                                                        │
│  ├─ LiteLLM Proxy（LLM统一网关，多供应商聚合）                    │
│  ├─ PostgreSQL（主数据库）                                       │
│  ├─ Redis（缓存 + 消息队列 + EventBus）                          │
│  ├─ MinIO（对象存储 / 产物管理）                                  │
│  └─ Smart Cache（语义缓存 / RAG）                                 │
├─────────────────────────────────────────────────────────────────┤
│  可观测性                                                        │
│  ├─ Prometheus（指标采集）                                       │
│  └─ Grafana（可视化仪表盘）                                       │
└─────────────────────────────────────────────────────────────────┘
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
# 编辑 .env 填入你的 API Key（至少配置一个 LLM 供应商）
```

**推荐配置（国内网络）**：
```bash
# DeepSeek（默认模型）
DEEPSEEK_API_KEY=sk-your-deepseek-key

# 其他可选
DASHSCOPE_API_KEY=sk-your-dashscope-key      # 阿里云百炼 / 通义千问
SILICONFLOW_API_KEY=sk-your-siliconflow-key  # 硅基流动
OPENAI_API_KEY=sk-your-openai-key            # OpenAI
ANTHROPIC_API_KEY=sk-your-anthropic-key      # Claude
```

### 3. Docker Compose 一键启动

```bash
# 启动全部核心服务（国内源自动加速）
docker compose up -d

# 启动前端开发模式
docker compose --profile dev-ui up -d

# 启动监控栈（Prometheus + Grafana）
docker compose --profile monitoring up -d
```

### 4. 验证部署

```bash
# 运行全量功能验证
python scripts/verify_deployment.py --url http://localhost:8765

# 运行测试套件（Docker 内）
docker compose exec api pytest tests/ -v
```

### 5. 访问服务

| 服务 | 地址 |
|------|------|
| 前端 UI | http://localhost:5173 |
| API 文档 (Swagger) | http://localhost:8765/docs |
| API 文档 (ReDoc) | http://localhost:8765/redoc |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |
| MinIO 控制台 | http://localhost:9001 |

---

## 增量部署

```bash
# 仅部署基础设施（postgres/redis/minio/litellm）
bash scripts/deploy.sh --layer infra

# 仅部署后端（api + worker）
bash scripts/deploy.sh --layer backend --build

# 仅部署前端
bash scripts/deploy.sh --layer frontend --build

# 全量部署 + 数据库迁移 + 验证
bash scripts/deploy.sh --full
```

详见 [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 项目结构

```
nexus/
├── nexus/                      # 后端核心
│   ├── api/                    # REST API + WebSocket
│   │   ├── routes/             # 路由端点
│   │   │   ├── workflows.py    # 工作流 CRUD
│   │   │   ├── agents.py       # Agent 管理
│   │   │   ├── crews.py        # Crew 多Agent协作
│   │   │   ├── prompts.py      # Prompt 模板管理
│   │   │   ├── traces.py       # LLM Trace 查询
│   │   │   ├── evals.py        # Eval 评估
│   │   │   ├── code_review.py  # 代码审查
│   │   │   └── mcp.py          # MCP 连接管理
│   ├── engine/                 # 核心编排引擎
│   │   ├── workflow_engine.py  # DAG执行引擎
│   │   ├── builder.py          # 引擎构建工厂（统一构建链路）
│   │   ├── state_manager.py    # 状态管理
│   │   ├── checkpoint.py       # 检查点/回滚
│   │   ├── event_bus.py        # 事件总线 (Pub/Sub)
│   │   ├── hitl_controller.py  # 人工审批
│   │   └── node_executors.py   # 节点执行器
│   ├── agent/                  # Agent运行时
│   │   ├── base.py             # BaseAgent（ReAct + ToolUse + Memory）
│   │   ├── crew.py             # Crew 协作编排器
│   │   ├── llm_client.py       # LLM客户端（LiteLLM代理）
│   │   ├── memory.py           # 记忆系统
│   │   └── decision_parser.py  # LLM响应解析
│   ├── services/               # Service层 (CRUD + 事务边界统一)
│   │   ├── base.py              # 通用CRUD基类
│   │   ├── run.py               # WorkflowRun + 触发执行
│   │   ├── node_run.py          # NodeRun 节点执行记录
│   │   └── ...                  # 各业务Service
│   ├── models/                 # SQLAlchemy ORM模型
│   ├── tools/                  # 工具注册中心 (MCP)
│   ├── security/               # 认证(JWT+API Key) / 授权(RBAC) / 租户隔离
│   ├── utils/                  # 通用工具 (安全后台任务/死信队列)
│   ├── prompts/                # Prompt模板引擎
│   ├── observability/          # Trace追踪 + 指标
│   ├── db/                     # 数据库迁移 (Alembic) + 种子数据
│   └── eval/                   # Eval评测引擎
├── tests/                      # 测试套件（245 tests）
│   ├── conftest.py             # pytest配置（PostgreSQL）
│   ├── test_workflow_engine.py # 引擎单元测试
│   ├── test_crew.py            # Crew协作测试
│   ├── test_agent_base.py      # Agent ReAct测试
│   ├── test_llm_client.py      # LLM调用测试
│   ├── test_services.py        # Service层测试
│   ├── test_api.py             # API集成测试
│   └── test_eval_engine.py     # Eval引擎测试
├── scripts/                    # 部署/迁移/验证脚本
│   ├── deploy.sh               # 增量部署脚本
│   ├── migrate.sh              # 数据库迁移脚本
│   └── verify_deployment.py    # 部署后功能验证
├── monitoring/                 # 监控配置
│   ├── prometheus.yml          # Prometheus配置
│   └── grafana/                # Grafana仪表盘
├── nexus-ui/                   # 前端（Vue3）
│   ├── src/
│   │   ├── views/              # 页面视图
│   │   ├── api/                # HTTP客户端
│   │   └── stores/             # Pinia状态管理
│   ├── Dockerfile              # 生产构建（nginx）
│   └── Dockerfile.dev          # 开发构建（Vite热更新）
├── Dockerfile                  # 后端多阶段构建
├── docker-compose.yml          # 全栈部署配置
├── litellm-config.yaml         # LiteLLM代理配置
├── nexus_cli.py                # CLI工具
├── requirements.txt
└── pytest.ini
```

---

## 架构说明

### 后台任务安全

所有 `asyncio.create_task` 调用使用 `utils/async_tasks.py` 中的 `safe_background_task()` 包装：

- 自动捕获并记录后台异常（不再静默丢弃）
- 工作流执行失败时自动更新 Run 状态为 `failed`
- 死信队列 (`dead_letter_jobs`) 记录失败任务，支持事后审计和重试

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

### Crew 多Agent协作

支持三种协作模式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **Hierarchical** | Manager 分解任务 → Workers 并行执行 → Manager 聚合结果 | 复杂任务需要分解 |
| **Sequential** | Workers 按顺序执行，前一输出作为后一上下文 | 流水线式处理 |
| **Parallel** | Workers 并行执行，结果写入共享上下文 | 独立子任务并行 |

所有模式下均支持：
- `shared_context`: Agent 间共享状态
- `EventBus` 实时事件广播
- 优雅降级（Worker 失败不影响整体）

### 三层变量系统

借鉴Dify的变量设计，支持：

- **env_vars**: 环境变量（租户级配置、密钥）
- **run_vars**: 运行级变量（节点间传递的中间结果）
- **node_outputs**: 节点输出（执行完成后聚合）

### 引擎构建 (Builder)

引擎创建统一使用 `engine/builder.py` 工厂模块，消除 API 路径和 ARQ Worker 路径之间的重复代码：

- `parse_workflow_definition()` — JSON config → DAG 解析
- `create_engine_components()` — 工厂创建 EventBus/StateManager/CheckpointMgr 等
- `register_base_executors()` — 注册执行器（支持基础/完整两种模式）
- `build_engine_and_executors()` — 一站式便捷入口

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

所有状态值使用 `RunStatus` / `NodeStatus` 枚举（统一管理，避免魔法字符串）。

### 多租户隔离

- 所有数据表包含 `tenant_id` 字段
- Service 层所有查询自动过滤租户
- API 端点级租户校验（12 个端点已加固）
- PostgreSQL Row-Level Security（可选启用）

### 认证与授权

- **JWT**: HS256 对称签名，access + refresh 双 Token
- **API Key**: `nexus_<prefix>_<secret>` 格式，HMAC-SHA256(SECRET_KEY) 数据库验证，支持过期/撤销/权限
- **RBAC**: 基于资源+操作的权限引擎，中间件自动拦截校验
- **开发回退**: `DEV_API_KEY` 环境变量在 development 环境直接通过（方便测试/文档）

---

## API文档

### REST API

#### 基础
| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/docs` | GET | Swagger UI |
| `/metrics` | GET | Prometheus 指标 |

#### 工作流
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/workflows` | GET/POST | 工作流列表/创建 |
| `/api/v1/workflows/{id}` | GET/PUT/DELETE | 工作流详情/更新/删除 |
| `/api/v1/workflows/{id}/runs` | POST | 触发执行 |
| `/api/v1/workflows/{id}/versions` | POST/GET | 版本管理 |
| `/api/v1/workflows/{id}/clone` | POST | 克隆工作流 |

#### Agent & Crew
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/agents` | GET/POST | Agent列表/创建 |
| `/api/v1/agents/{id}` | GET/PUT/DELETE | Agent详情/更新/删除 |
| `/api/v1/crews` | GET/POST | Crew团队列表/创建 |
| `/api/v1/crews/{id}` | GET/PUT/DELETE | Crew详情/更新/删除 |
| `/api/v1/crews/{id}/run` | POST | 触发Crew执行 |
| `/api/v1/crews/{id}/runs` | GET | Crew执行历史 |

#### Prompt / Trace / Eval
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/prompts/prompts` | GET/POST | Prompt模板列表/创建 |
| `/api/v1/traces/traces` | GET | LLM调用Trace查询 |
| `/api/v1/evals/evals` | GET/POST | Eval评估列表/执行 |

#### Code Review
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/code-review/reviews` | POST | 提交代码审查 |

#### MCP & 工具
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/mcp/connections` | GET/POST | MCP连接管理 |
| `/api/v1/tools` | GET/POST | 工具注册 |

#### 执行管理
| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/runs/{id}` | GET | 执行状态 |
| `/api/v1/runs/{id}/cancel` | POST | 取消执行 |
| `/api/v1/runs/{id}/pause` | POST | 暂停执行 |
| `/api/v1/runs/{id}/resume` | POST | 恢复执行 |
| `/api/v1/runs/{id}/retry` | POST | 重试执行 |
| `/api/v1/hitl/tasks` | GET/POST | 审批任务 |

### WebSocket

```
ws://localhost:8765/ws/v1/runs/{run_id}
```

实时接收执行状态更新、HITL审批请求。

---

## 环境变量

### 关键配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ENVIRONMENT` | `development` | 运行环境 |
| `SECRET_KEY` | `change-me-in-production` | JWT签名密钥 + API Key HMAC密钥 |
| `DEV_API_KEY` | — | 开发环境 API Key 回退（仅 development 生效） |
| `DATABASE_URL` | `postgresql+asyncpg://nexus:nexus@localhost:5432/nexus` | 数据库连接 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis连接 |

### LLM 配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DEFAULT_LLM_MODEL` | `deepseek-chat` | 默认LLM模型 |
| `DEFAULT_LLM_PROVIDER` | `deepseek` | 默认LLM提供商 |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LiteLLM代理地址 |
| `LITELLM_API_KEY` | `sk-litellm-master-key` | LiteLLM Master Key |
| `OPENAI_API_KEY` | - | OpenAI API Key |
| `ANTHROPIC_API_KEY` | - | Anthropic API Key |
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key |
| `DASHSCOPE_API_KEY` | - | 阿里云百炼 API Key |
| `SILICONFLOW_API_KEY` | - | 硅基流动 API Key |

### 其他

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `S3_ENDPOINT` | `http://localhost:9000` | MinIO端点 |
| `ENABLE_PROMETHEUS` | `true` | 启用Prometheus指标 |
| `ENABLE_OPENTELEMETRY` | `false` | 启用OpenTelemetry |
| `USE_CN_MIRROR` | `true` | Docker构建国内源加速 |

完整环境变量列表见 [`.env.example`](.env.example)

---

## 测试

```bash
# Docker 内运行全部测试（245 tests）
docker compose exec api pytest tests/ -v

# 运行特定模块
pytest tests/test_workflow_engine.py -v
pytest tests/test_crew.py -v
pytest tests/test_agent_base.py -v
pytest tests/test_llm_client.py -v

# 运行集成测试（需要外部LLM服务）
pytest -m integration

# 生成覆盖率报告
pytest --cov=nexus --cov-report=html
```

> **注意**: 测试使用 Docker Compose 内的 PostgreSQL (`nexus_test` 数据库)，无需安装 SQLite。

---

## 部署

### 本地开发

```bash
docker compose up -d                    # 核心服务
docker compose --profile dev-ui up -d   # 前端热更新
docker compose --profile monitoring up -d # 监控栈
```

### 生产部署

```bash
# 使用部署脚本（支持增量部署）
bash scripts/deploy.sh --full

# 或手动分层部署
bash scripts/deploy.sh --layer infra
bash scripts/deploy.sh --layer backend --build --migrate
bash scripts/deploy.sh --layer frontend --build
bash scripts/deploy.sh --verify
```

### CI/CD

GitHub Actions 工作流配置见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)，包含：
- Lint + Test
- Docker 镜像构建并推送至 GHCR
- SSH 远程部署

详细部署指南见 [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 设计来源

NEXUS 基于 [WAT (Werewolf-Agent-Team)](https://github.com/your-org/wat) 狼人杀多Agent博弈系统演化而来，借鉴了以下业界最佳实践：

| 来源项目 | 借鉴内容 |
|---------|---------|
| **LangGraph** | 图状态机 + Checkpoint持久化 |
| **Temporal** | 确定性Workflow + 事件溯源 |
| **Dify** | 可视化编排 + 变量池 |
| **CrewAI** | Role-Playing Agent + Manager-Worker协作 |
| **MCP** | 工具协议标准 |
| **LiteLLM** | LLM统一网关 |
| **OpenTelemetry** | 分布式链路追踪 |

---

## 许可证

MIT License
