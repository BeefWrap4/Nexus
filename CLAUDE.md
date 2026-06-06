# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

NEXUS 是一个**企业级多Agent协作编排引擎**：DAG 工作流执行引擎 + ReAct/Crew 多 Agent 协作 + MCP 工具标准 + LiteLLM LLM 网关 + 多租户 SaaS。

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) / ARQ (Redis 异步任务)
- **前端**：Vue 3 / Vite / Pinia / Ant Design Vue / Vue Flow / TypeScript
- **数据**：PostgreSQL (主从) + Redis (含 Sentinel 模式) + MinIO + LiteLLM Proxy + Smart Cache (语义缓存)
- **可观测性**：Prometheus + Grafana + OpenTelemetry
- **设计来源**：LangGraph (图状态机) / Temporal (确定性 Workflow) / Dify (变量池) / CrewAI (Manager-Worker)

## 常用命令

> 项目根目录即为仓库根目录。所有命令在 `D:/AI_learning/nexus/` 下执行（Windows 平台使用 bash 语法）。

### 启动开发环境

```bash
# 一键启动核心服务（PostgreSQL/Redis/MinIO/LiteLLM + API + Worker）
docker compose up -d

# 启动前端开发模式（Vite 热更新，端口 5173）
docker compose --profile dev-ui up -d

# 启动监控栈（Prometheus + Grafana）
docker compose --profile monitoring up -d

# 启动前端 UI（容器外，本地 npm）
cd nexus-ui && npm install && npm run dev
```

服务端口：API `:8765` (Swagger `/docs`) / 前端 `:5173` / Prometheus `:9090` / Grafana `:3000` / MinIO `:9001` / LiteLLM `:4000` / Smart Cache `:8777`。

### 部署

```bash
# 增量部署（自动检测变更层：infra / backend / frontend / all）
bash scripts/deploy.sh                       # 自动检测
bash scripts/deploy.sh --layer backend --build --migrate
bash scripts/deploy.sh --full                # 全量：build + migrate + verify
bash scripts/deploy.sh --full --no-cn-mirror  # 海外部署

# 海外构建：USE_CN_MIRROR=false docker compose build
```

### 数据库

```bash
# 迁移（项目内）
bash scripts/migrate.sh

# 手动执行 Alembic
alembic upgrade head
alembic revision --autogenerate -m "msg"

# 初始化种子数据
python scripts/init_db.py
python scripts/seed_data.py
```

### ARQ Worker（独立进程）

```bash
# Worker 入口：nexus.jobs.config.WorkerSettings
arq nexus.jobs.config.WorkerSettings
# 或
python -m arq nexus.jobs.config.WorkerSettings
```

### 测试

```bash
# 全量（pytest.ini 默认排除 slow / integration）
pytest tests/ -v

# 单个文件
pytest tests/test_workflow_engine.py -v

# 单个测试（class::method 或 path）
pytest tests/test_workflow_engine.py::TestWorkflowDefinition::test_simple_linear_workflow_valid -v

# 集成测试（需要外部 LLM 服务，例 DeepSeek）
pytest -m integration -v
# 在 Docker 容器中：docker compose exec api pytest tests/ -v

# 覆盖率
pytest --cov=nexus --cov-report=html
pytest --cov=nexus --cov-report=term-missing --cov-fail-under=75   # CI 阈值
```

测试夹具集中在 `tests/conftest.py`：`db_session`、`async_client`、`workflow_engine`（用 Mock 组件构造）、`test_token`/`auth_headers`、`simple_workflow`/`branching_workflow`/`parallel_workflow` 等工作流定义。`MockNodeExecutor` 是注入 `WorkflowEngine` 的标准方式。

### Lint / 格式化 / 类型检查

```bash
# 后端（dev 依赖：black, ruff, mypy）
ruff check nexus/ tests/
black --check nexus/ tests/
mypy nexus/

# 前端
cd nexus-ui
npm run lint          # eslint
npm run type-check    # vue-tsc --noEmit
npm run build         # vue-tsc + vite build（自定义脚本）

# 安全扫描（CI 中执行）
bandit -r nexus/ -ll -f txt
python scripts/validate_security.py
safety check -r requirements.txt
```

### CLI 工具

```bash
python nexus_cli.py --help
```

## 架构（高层）

```
Client (Vue3 / API)
    │  HTTP / WebSocket
    ▼
┌────────────────────────────────────────────────────────┐
│  nexus/api/             FastAPI 路由 + 异常 + WS 桥接  │
│   routes/   workflows, agents, crews, runs, hitl,     │
│             prompts, traces, evals, mcp, auth, ...     │
│   main.py   CORS / RBAC / Prometheus 中间件 + lifespan │
│   websocket.py  ← EventBus 推送                        │
├────────────────────────────────────────────────────────┤
│  nexus/services/        业务逻辑（CRUD + 事务边界）     │
│   base.py   BaseService[Model]  create/get/list/update │
│             /delete — 所有方法强制 tenant_id 过滤     │
│   run.py / node_run.py / prompt.py / crew.py / ...     │
├────────────────────────────────────────────────────────┤
│  nexus/engine/          DAG 工作流引擎（Pregel super-step）
│   workflow_engine.py   WorkflowEngine.execute()        │
│   builder.py           **工厂** — parse / build /     │
│             create_engine_components / register_executors│
│             /build_engine_and_executors。API 与 Worker│
│             两条路径都走这里，避免重复                 │
│   state_manager.py / checkpoint.py / event_bus.py /   │
│   hitl_controller.py / variable_pool.py / router_engine│
│   executors/  start / end / agent / crew / tool /      │
│               condition / hitl / llm                   │
├────────────────────────────────────────────────────────┤
│  nexus/agent/           Agent 运行时（ReAct + Crew）    │
│   base.py     BaseAgent.execute()  ReAct 循环          │
│               (系统Prompt → LLM → 解析 → 工具执行 → 观察)│
│   crew.py     Manager-Worker (Hierarchical/Sequential/ │
│               Parallel) + shared_context                │
│   llm_client.py  LLMClient → LiteLLM Proxy / 直连      │
│   memory.py / vector_memory.py / multimodal.py         │
├────────────────────────────────────────────────────────┤
│  nexus/security/        认证 / 授权 / 限流 / PII         │
│   auth.py   JWT (HS256) + API Key (HMAC-SHA256, 格式    │
│             nexus_<prefix>_<secret>); get_current_user │
│             同时支持 Bearer Token 和 X-API-Key          │
│   rbac.py   RBACMiddleware 检查 {role}:{resource}:{action}
│   rate_limiter.py  Redis 滑动窗口                       │
├────────────────────────────────────────────────────────┤
│  nexus/jobs/            ARQ 异步任务                    │
│   config.py     WorkerSettings（Redis/并发/超时）      │
│   workflow.py   execute_workflow_job（enqueue 入口）    │
│   dlq.py        死信队列（任务重试上限后落库）          │
│   scheduler.py  定时工作流（cron job）                  │
├────────────────────────────────────────────────────────┤
│  nexus/db/   SQLAlchemy 2.0 async + Alembic             │
│  nexus/observability/  Prometheus 指标 + OTel trace    │
│  nexus/tools/registry.py  ToolRegistry（MCP 工具统一注册）│
│  nexus/prompts/  PromptTemplate + 变量解析 + A/B 实验   │
│  nexus/eval/     评估 runner + evaluator                │
│  nexus/plugins/  PluginManager / Hooks / ToolProvider   │
│  nexus/billing/  Free/Pro/Enterprise 计费 + 配额         │
│  nexus/cache/    Smart Cache (RAG) + Redis 客户端       │
│  nexus/mcp/      MCP Client/Server（标准协议）          │
└────────────────────────────────────────────────────────┘
```

### 关键流程

1. **DAG 调度（Pregel-inspired super-step）**：
   验证定义 → 注入 start/end 边界节点 → 反复：取就绪节点 → 并行 `asyncio.gather` → 合并结果 → Checkpoint → EventBus 广播 → 终止判定。终止条件：所有节点 done / 无就绪且全部 blocked / 超过 `MAX_WORKFLOW_STEPS` / `WORKFLOW_TIMEOUT_SECONDS`。

2. **状态生命周期**：
   `PENDING → RUNNING → [COMPLETED | FAILED | CANCELLED]`，HITL 触发 `PAUSED`，`resume()` 回到 `RUNNING`。状态值统一在 `nexus/engine/enums.py`（`RunStatus`、`NodeStatus`、`HITLStatus` 等），禁止魔法字符串。

3. **多租户**：
   - 所有表带 `tenant_id`，`BaseService` 全部方法按 `tenant_id` 过滤。
   - RBAC 中间件按路径解析 `resource_type`、按 HTTP 方法解析 `action`（GET→read, POST→write, PUT/PATCH→update, DELETE→delete），公开路径：`/`、`/health`、`/docs`、`/openapi.json`、`/metrics`、`/api/v1/auth/*`。
   - DB 可选 PostgreSQL Row-Level Security（生产级加固）。

4. **三层层级变量**（借鉴 Dify）：
   `env_vars`（租户级配置）→ `run_vars`（运行级）→ `node_outputs`（执行后聚合）。`VariablePool.resolve()` 解析节点输入。

5. **认证授权双模**：
   - JWT：HS256，access (1h) + refresh (7d)，支持密钥轮换（`JWT_PREVIOUS_SECRET_KEYS` 历史密钥仍可验签）。
   - API Key：`nexus_<prefix>_<secret>`，DB 存 HMAC-SHA256(SECRET_KEY, key)；验证流程：提取 prefix → 索引定位 → HMAC 比对 → 过期/撤销检查 → 速率限制（Redis 滑动窗口）。
   - `DEV_API_KEY`：**仅 development 环境**直接通过（生产启动校验会拒绝）。

6. **后台任务**：所有 `asyncio.create_task` 必须用 `nexus/utils/async_tasks.py` 的 `safe_background_task()` 包装 — 捕获异常、更新 Run 状态、写入死信队列（`dead_letter_jobs` 表），**绝不允许静默丢弃**。

7. **LLM 网关**：`LLMClient` 默认走 `LITELLM_PROXY_URL`，但当 `PROVIDER_CONFIGS` 中对应 provider 的 API Key 存在时直连。`PROVIDER_CONFIGS` 支持 deepseek / openai / siliconflow / dashscope / zhipu。支持 Fallback 链（`LLM_FALLBACK_CHAIN`）。

8. **跨进程事件传播**：Worker publish → Redis Pub/Sub → API EventBus listener（后台 task）→ WebSocket manager → 浏览器。`nexus/api/websocket.py::subscribe_websocket_to_eventbus` 完成最后一段桥接。

### 错误码体系

`NexusException` (基类) + 子类层级（`WorkflowException` / `AgentException` / `ToolException` / `HITLException` / `SecurityException` / `TenantException`）。响应统一格式：
```json
{ "success": false, "error": { "code": 1101, "name": "WORKFLOW_NOT_FOUND", "message": "...", "details": {} } }
```
错误码分段：1xxx 认证 / 11xx 工作流 / 12xx Agent / 13xx DB / 14xx 校验 / 15xx 内部 / 16xx HITL / 17xx 工具 / 18xx 租户权限。详细映射见 `README.md` 与 `nexus/exceptions/error_codes.py`。

### 状态值枚举

`nexus/engine/enums.py`：`NodeType`（START/AGENT/CREW/TOOL/HITL/CONDITION/PARALLEL/LOOP/DELAY/END）、`NodeStatus`（PENDING/RUNNING/SUCCEEDED/FAILED/SKIPPED）、`RunStatus`（PENDING/RUNNING/PAUSED/COMPLETED/FAILED/CANCELLED）、`HITLStatus`、`CrewRunStatus`、`EvalRunStatus`、`DLQJobStatus`。Crew 模式在 `nexus/agent/crew.py::CrewMode`：HIERARCHICAL / SEQUENTIAL / PARALLEL。

## 配置

`nexus/config.py::Settings` 通过 pydantic-settings 从 `.env` 读取。生产环境启动时执行 `_validate_production_security()`（`nexus/api/main.py`）：禁止默认 `SECRET_KEY`、禁止 SQLite、禁止 `DEV_API_KEY`、CORS 禁止通配符、强制 `DEBUG=false`。

`.env.example` 是模板（占位符 `<REPLACE_...>`），**必须** `cp .env.example .env` 并替换；不要提交真实凭证。验证：`python scripts/validate_security.py`。

## 关键约定

- **异步优先**：pytest 用 `asyncio_mode=auto`，所有 I/O `async/await`，DB 用 `AsyncSession`。
- **路径导入**：所有跨包 import 走 `nexus.xxx` 形式，不用相对路径。
- **新增 Service**：继承 `BaseService[Model]`，强制 `tenant_id` 参数（CRUD 基类已封装）。
- **新增 API 端点**：放 `nexus/api/routes/<resource>.py`，在 `nexus/api/main.py` 注册（已含 CORS/RBAC/Prometheus 中间件）。
- **新增工作流节点类型**：在 `nexus/engine/enums.py::NodeType` 增枚举 + `nexus/engine/executors/` 新建 executor + `register_base_executors()` 或 `register_extra=True` 路径注册。
- **新增 LLM Provider**：在 `nexus/config.py::Settings.PROVIDER_CONFIGS` 加 `(base_url, env_key)`，并实现 `LLMClient` 的对应解析（如需）。
- **所有 `asyncio.create_task`**：用 `safe_background_task()` 包装；工作流执行用 `safe_workflow_execution()`（自动更新 Run 状态）。
- **DB 会话**：路由用 `Depends(get_db)`；Worker 用 `async with get_db_session() as session:`。
- **CI**：`.github/workflows/ci.yml` 跑 `pytest --cov-fail-under=75`、`bandit`、`safety`、前端 `lint` + `type-check` + `build`、Docker smoke build。

## 关键文件速查

| 文件 | 作用 |
|------|------|
| `nexus/api/main.py` | FastAPI app + lifespan + 全局异常处理 + 路由注册 |
| `nexus/api/websocket.py` | WS 连接管理 + EventBus 桥接 |
| `nexus/engine/workflow_engine.py` | DAG 调度核心（super-step 循环） |
| `nexus/engine/builder.py` | **引擎工厂**（API/Worker 共用，消除重复） |
| `nexus/engine/enums.py` | 状态/类型枚举 |
| `nexus/agent/base.py` | BaseAgent ReAct 循环 + 工具调用 + 记忆 |
| `nexus/agent/crew.py` | Manager-Worker 三种模式 |
| `nexus/agent/llm_client.py` | LLM 客户端（LiteLLM/直连/Fallback） |
| `nexus/services/base.py` | 通用 CRUD 基类（tenant 强制） |
| `nexus/services/run.py` | WorkflowRun 触发与状态机 |
| `nexus/security/auth.py` | JWT + API Key + `get_current_user` |
| `nexus/security/rbac.py` | RBAC 中间件 |
| `nexus/jobs/workflow.py` | ARQ 工作流执行入口 |
| `nexus/jobs/config.py` | WorkerSettings（Redis/并发/cron） |
| `nexus/db/database.py` | async engine + sessionmaker + get_db |
| `nexus/exceptions.py` | NexusException 层级 + 错误码 |
| `nexus/config.py` | Settings（pydantic-settings） |
| `nexus/utils/async_tasks.py` | safe_background_task / safe_workflow_execution |
| `nexus/tools/registry.py` | ToolRegistry（MCP 工具统一入口） |
| `tests/conftest.py` | 测试 fixtures（DB / 客户端 / Mock 引擎） |
| `docker-compose.yml` | 全栈编排（PG/Redis/MinIO/LiteLLM/监控） |
| `scripts/deploy.sh` | 增量部署（变更检测 + 分层） |
| `docs/ERROR_CODE_QUICK_REFERENCE.md` | 错误码速查 |
| `monitoring/MONITORING_GUIDE.md` | Prometheus/Grafana 配置说明 |
| `DEPLOYMENT.md` | 部署详细指南 |

## 不在仓库的内容

- 真实 `.env`（gitignore）；用 `.env.example` 作模板。
- Docker 卷数据、SQLite 临时库（`.pytest_nexus.db*`、`.benchmarks/`、`.pytest_cache/`、`.ruff_cache/`、`htmlcov/`）。
- `nexus-ui/node_modules/` 和 `nexus-ui/dist/`。
- 各种 P0/P1/P2 *IMPROVEMENT_REPORT.md / *EXECUTION_REPORT.md — 历史阶段报告，新需求以代码 + README 为准。
