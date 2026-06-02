# NEXUS - 企业级多Agent协作编排引擎

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3.4+-4FC08D.svg)](https://vuejs.org)

> NEXUS 是一个**通用多Agent协作编排平台**，支持开发者通过 API/SDK 构建复杂的多Agent工作流，同时支持业务人员通过可视化界面拖拽配置业务流程。

---

## 🎯 核心特性

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

## 🏗️ 系统架构

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Web控制台    │   │ 可视化编排器  │   │ 审批面板     │
│  (Vue3)      │   │ (Vue-Flow)   │   │ (Ant Design) │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       └──────────────────┼──────────────────┘
                          ▼
┌─────────────────────────────────────────────────────┐
│  API Gateway (FastAPI)                              │
│  REST API + WebSocket + MCP Gateway                 │
├─────────────────────────────────────────────────────┤
│  编排引擎核心 (WorkflowEngine)                       │
│  DAG执行 + 状态机 + HITL + 事件总线 + 检查点         │
├─────────────────────────────────────────────────────┤
│  Agent运行时 (BaseAgent)                            │
│  LLM调用 + 决策解析 + 信任模型 + 记忆系统             │
├─────────────────────────────────────────────────────┤
│  基础设施 (LiteLLM + PostgreSQL + Redis + S3)       │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

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

## 📁 项目结构

```
nexus/                          # 后端
├── nexus/
│   ├── api/                    # REST API + WebSocket
│   ├── engine/                 # 核心编排引擎
│   │   ├── workflow_engine.py  # DAG执行引擎
│   │   ├── state_manager.py    # 状态管理
│   │   ├── checkpoint.py       # 检查点/回滚
│   │   ├── hitl_controller.py  # 人工审批
│   │   └── node_executors.py   # 节点执行器
│   ├── agent/                  # Agent运行时
│   │   ├── base.py             # Agent基类
│   │   ├── llm_client.py       # LLM客户端
│   │   └── memory.py           # 记忆系统
│   ├── services/               # Service层 (CRUD)
│   ├── models/                 # 数据库ORM模型
│   ├── tools/                  # 工具注册中心 (MCP)
│   └── security/               # 认证/授权/PII
├── nexus_cli.py                # CLI工具
├── requirements.txt
└── docker-compose.yml

nexus-ui/                       # 前端
├── src/
│   ├── views/                  # 页面视图
│   │   ├── WorkflowEditor.vue  # 可视化编排器
│   │   ├── RunMonitor.vue      # 实时监控
│   │   └── HITLTasks.vue       # 审批任务
│   ├── api/                    # HTTP + WebSocket
│   └── stores/                 # Pinia状态管理
└── package.json
```

---

## 🔌 API概览

### REST API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/workflows` | GET/POST | 工作流列表/创建 |
| `/api/v1/workflows/{id}/runs` | POST | 触发执行 |
| `/api/v1/agents` | GET/POST | Agent管理 |
| `/api/v1/tools` | GET/POST | 工具注册 |
| `/api/v1/runs/{id}` | GET | 执行状态 |
| `/api/v1/hitl/tasks` | GET/POST | 审批任务 |

### WebSocket

```
ws://localhost:8000/ws/v1/runs/{run_id}
```

实时接收执行状态更新、HITL审批请求。

---

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定模块
pytest tests/test_workflow_engine.py -v
pytest tests/test_api.py -v
```

---

## 🏛️ 设计来源

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

## 📄 许可证

MIT License
