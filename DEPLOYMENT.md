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

## 国内源加速配置（中国大陆部署）

在中国大陆部署时，Docker Hub / PyPI / npm 官方源访问缓慢。NEXUS 已内置国内源加速支持。

### 1. Docker Hub 镜像加速器（宿主机配置）

```bash
# 复制示例配置到 Docker daemon 配置目录
sudo cp .docker/daemon.json.example /etc/docker/daemon.json
sudo systemctl restart docker
```

配置的镜像源包括：上海交大、DaoCloud、网易云、DockerProxy、中科大。

### 2. 构建时国内源（自动启用，默认开启）

| 包管理器 | 国内源 | 配置位置 |
|---------|-------|---------|
| pip (后端) | 阿里云 PyPI | `Dockerfile` builder stage |
| apt (后端) | 阿里云 Debian | `Dockerfile` production stage |
| npm (前端) | 淘宝 npm 镜像 | `nexus-ui/Dockerfile` |
| apk (前端) | 阿里云 Alpine | `nexus-ui/Dockerfile` nginx stage |

**禁用国内源**（海外部署时）：
```bash
# 单次构建禁用
USE_CN_MIRROR=false docker compose build

# 或在 .env 中永久禁用
USE_CN_MIRROR=false
```

### 3. 验证加速效果

```bash
# 构建后端镜像，观察下载速度
docker compose build api

# 构建前端镜像
docker compose build ui
```

---

## 快速开始

### 1. 环境准备

```bash
# 安装 Docker & Docker Compose
# https://docs.docker.com/get-docker/

# 克隆仓库
git clone <repo-url> && cd nexus

# （中国大陆用户）配置 Docker Hub 镜像加速器
sudo cp .docker/daemon.json.example /etc/docker/daemon.json
sudo systemctl restart docker
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

---

## 增量部署

使用 `scripts/deploy.sh` 实现分层增量部署，自动检测变更并只重建受影响的服务。

### 部署分层

```
Layer 1: infra     — PostgreSQL, Redis, MinIO, LiteLLM (变更频率低)
Layer 2: backend   — API, Worker (变更频率中)
Layer 3: frontend  — Vue UI (变更频率高)
```

### 常用部署命令

```bash
# 全量部署（含构建 + 迁移 + 验证）
bash scripts/deploy.sh --full

# 仅部署后端（代码更新后）
bash scripts/deploy.sh --layer backend --build --migrate

# 仅部署前端（UI 更新后）
bash scripts/deploy.sh --layer frontend

# 自动检测变更并部署（默认行为）
bash scripts/deploy.sh

# 禁用国内源（海外服务器）
bash scripts/deploy.sh --full --no-cn-mirror

# 查看帮助
bash scripts/deploy.sh --help
```

### 滚动更新策略

`deploy.sh` 采用**先 Worker 后 API** 的滚动更新策略：
1. 先更新 `worker` 容器（避免中断正在执行的异步任务）
2. 等待 Worker 就绪
3. 再更新 `api` 容器
4. 等待 API 健康检查通过
5. 最后更新 `ui` 容器

---

## 数据库迁移

使用 `scripts/migrate.sh` 安全执行数据库迁移，支持自动备份和回滚。

### 标准迁移流程

```bash
# 备份当前数据库并执行迁移到最新版本
bash scripts/migrate.sh

# 自动生成迁移脚本（模型变更后）
bash scripts/migrate.sh --generate --message "add crew tables"

# 仅查看当前状态
bash scripts/migrate.sh --status

# 查看帮助
bash scripts/migrate.sh --help
```

### 回滚操作

```bash
# 使用最近一次备份回滚数据库
bash scripts/migrate.sh --rollback

# 回滚前会自动创建紧急备份，以防回滚失败
```

### 手动迁移

```bash
# 在运行中的 API 容器内执行
docker compose exec api alembic upgrade head

# 或通过 CLI
cd nexus && python nexus_cli.py db migrate
```

---

## 部署后全量验证

使用 `scripts/verify_deployment.py` 验证所有 Phase 1-10 功能是否正常工作。

### 运行验证

```bash
# 针对本地部署验证
python scripts/verify_deployment.py --url http://localhost:8000

# 针对生产环境验证
python scripts/verify_deployment.py --url https://nexus.example.com
```

### 验证覆盖范围

| Phase | 验证项 |
|-------|--------|
| P1 | Health Check, API Docs, Prometheus Metrics |
| P2 | Workflow CRUD, Workflow Execution |
| P3 | Agent CRUD |
| P5 | MCP Connections |
| P6 | Prompt Management, Trace Query, Eval Dashboard |
| P8 | Code Review |
| P9 | Semantic Cache Metrics |
| P10 | Crew CRUD, Crew Execution |

### 与 deploy.sh 集成

```bash
# 部署时自动运行验证
bash scripts/deploy.sh --full
# 或
bash scripts/deploy.sh --layer all --verify
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
# ─── 查看日志 ───
docker compose logs -f api
docker compose logs -f worker

# ─── 重启服务 ───
docker compose restart api
docker compose restart worker

# ─── 增量部署（推荐） ───
bash scripts/deploy.sh --layer backend --build --migrate

# ─── 数据库迁移 ───
bash scripts/migrate.sh              # 备份 + 迁移
bash scripts/migrate.sh --status     # 查看状态
bash scripts/migrate.sh --rollback   # 回滚

# ─── 部署后验证 ───
python scripts/verify_deployment.py --url http://localhost:8000

# ─── 清理重建 ───
docker compose down -v
docker compose up -d --build

# ─── 仅运行测试 ───
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

GitHub Actions 自动执行: **lint → test → build → push → deploy**

| Stage | 说明 |
|-------|------|
| `lint` | ruff 代码检查 |
| `test` | pytest (200+ 测试用例) |
| `build-api` | 构建并推送 API 镜像到 GHCR |
| `build-ui` | 构建并推送 UI 镜像到 GHCR |
| `deploy` | SSH 触发远程服务器增量部署（需配置 secrets） |

### 所需 Secrets

| Secret | 说明 |
|--------|------|
| `DEPLOY_HOST` | 部署目标服务器 IP/域名 |
| `DEPLOY_USER` | SSH 用户名 |
| `DEPLOY_KEY` | SSH 私钥 |

镜像推送使用 `GITHUB_TOKEN`（自动提供），无需额外配置。

### 镜像标签

- `ghcr.io/<owner>/nexus/api:latest` — 最新版本
- `ghcr.io/<owner>/nexus/api:<sha>` — 按 commit SHA 版本化
- `ghcr.io/<owner>/nexus/ui:latest` — 前端最新版本
- `ghcr.io/<owner>/nexus/ui:<sha>` — 前端按 commit 版本化

---

## 部署检查清单

```
□ 1. 环境准备
  □ 配置 Docker Hub 镜像加速器（中国大陆）
  □ 确认 .env 配置正确（生产密钥已设置）
  □ 确认目标服务器资源充足

□ 2. 代码验证
  □ git pull 最新代码
  □ pytest tests/ -v 全部通过
  □ git diff 确认变更范围

□ 3. 数据库迁移
  □ bash scripts/migrate.sh（自动备份 + 迁移）
  □ 或 docker compose exec api alembic upgrade head
  □ 验证新表已创建

□ 4. 增量部署
  □ bash scripts/deploy.sh --layer infra（如需要）
  □ bash scripts/deploy.sh --layer backend --build --migrate
  □ bash scripts/deploy.sh --layer frontend

□ 5. 功能验证
  □ python scripts/verify_deployment.py --url http://localhost:8000
  □ 全部 14 项验证通过

□ 6. 监控确认
  □ Prometheus /metrics 正常
  □ Grafana 仪表盘数据正常
  □ 无异常日志
```

---

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 构建缓慢 | 未配置国内源 | 确认 `USE_CN_MIRROR=true`（默认开启） |
| 数据库迁移失败 | 表已存在或结构不兼容 | `bash scripts/migrate.sh --rollback` |
| API 启动失败 | 依赖服务未就绪 | `docker compose up -d postgres redis minio` |
| Worker 不消费任务 | Redis 连接问题 | 检查 `REDIS_URL` 配置 |
| 前端 502 | API 未启动 | `docker compose logs api` 查看错误 |

---

## 下一步

- K8s Helm Chart — Kubernetes 集群部署
- Terraform — 基础设施即代码
- Vault 集成 — 敏感密钥管理
