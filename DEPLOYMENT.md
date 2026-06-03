# NEXUS 部署指南

> 遵循教案《项目部署》5 阶段框架。3 步上线。

## 架构

```
nginx (80)                       监控 (可选)
├── /api/* → api:8000             Prometheus:9090
├── /ws/*  → api:8000 (ws)       Grafana:3000
└── /*     → UI 静态文件

后端服务                          基础设施
├── api:8000  (FastAPI)          postgres:5432
├── worker    (ARQ)              redis:6379
├── litellm:4000 (LLM 网关)       minio:9000
└── [smart-cache:8777] (可选)     minio-console:9001
```

## 快速开始

### 1. 环境准备

```bash
# 安装 Docker & Docker Compose
# https://docs.docker.com/get-docker/

# 克隆仓库
git clone <repo-url> && cd nexus
```

### 2. 配置环境

```bash
# 开发环境 (SQLite + 本地端口)
cp .env.dev .env

# 生产环境 (PostgreSQL + 内网)
cp .env.prod .env
# 编辑 .env，设置生产密钥:
#   SECRET_KEY=<强随机字符串>
#   POSTGRES_PASSWORD=<数据库密码>
#   DEEPSEEK_API_KEY=<你的 API Key>
```

### 3. 启动

```bash
# 核心服务 (API + Worker + DB + Redis + LiteLLM + MinIO)
docker compose up -d

# 生产前端 (nginx 提供静态文件)
docker compose --profile prod-ui up -d

# 开发前端 (Vite 热重载, 端口 5173)
docker compose --profile dev-ui up -d

# RAG 集成 (Smart Cache)
docker compose --profile rag up -d smart-cache

# 监控 (Prometheus + Grafana)
docker compose --profile monitoring up -d

# 全部服务
docker compose --profile prod-ui --profile rag --profile monitoring up -d
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8000/health
# → {"status": "ok", "version": "0.2.0"}

# 前端 (生产 nginx 80 端口)
curl http://localhost/
# → 返回 index.html

# 监控
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000 (admin/admin)

# API 文档
# Swagger:    http://localhost:8000/docs
# ReDoc:      http://localhost:8000/redoc
```

## 服务列表

| 服务 | 端口 | 说明 |
|------|------|------|
| `api` | 8000 | FastAPI 后端 (ARQ Worker 通过内部网络连接) |
| `worker` | — | ARQ 后台任务执行 |
| `ui` (prod-ui) | 80 | nginx + Vue 3 静态文件 |
| `dev-ui` (dev-ui) | 5173 | Vite 开发服务器 (热重载) |
| `postgres` | 5432 | PostgreSQL 16 数据库 |
| `redis` | 6379 | Redis 7 缓存/队列/事件总线 |
| `litellm` | 4000 | LiteLLM Proxy LLM 网关 |
| `minio` | 9000/9001 | 对象存储 (API + Console) |
| `smart-cache` (rag) | 8777 | LLM Cache Engine (语义缓存/RAG) |
| `prometheus` (monitoring) | 9090 | 指标采集 |
| `grafana` (monitoring) | 3000 | 仪表盘可视化 |

## 常用操作

```bash
# 查看日志
docker compose logs -f api
docker compose logs -f worker

# 重启服务
docker compose restart api
docker compose restart worker

# 数据库迁移
docker compose exec api alembic upgrade head

# 清理重建
docker compose down -v
docker compose up -d --build

# 仅运行测试
pytest tests/ -v --ignore=tests/test_workflow_engine.py
```

## 环境变量

所有 NEXUS 配置项参见 `.env.dev` (开发) 和 `.env.prod` (生产)。

关键变量:
- `SECRET_KEY` — JWT 签名密钥 (生产必须修改)
- `DATABASE_URL` — 数据库连接串 (开发 SQLite, 生产 PostgreSQL)
- `REDIS_URL` — Redis 连接串
- `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` — LLM API 密钥 (至少配置一个)
- `SMART_CACHE_URL` — RAG 语义缓存地址 (可选)

## CI/CD

GitHub Actions 自动执行:
- **push/PR to main**: lint (ruff) → test (178 cases) → build API image → build UI image

## 下一步

- K8s Helm Chart — Kubernetes 集群部署
- Terraform — 基础设施即代码
- Vault 集成 — 敏感密钥管理
