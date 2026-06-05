# NEXUS 生产就绪改进计划

> **来源：** 安全专家 (2.8/5) + 运维专家 (3.1/5) + 产品/用户 (3.8/5) 三视角联合审查
> **目标：** 从内部 Beta 达到对外上线标准
> **创建日期：** 2026-06-05

---

## 总体路线

```
Phase A: 安全阻断修复 (3天)  →  内部 Beta 可用
Phase B: 运维加固 (5天)        →  有条件上线
Phase C: 产品完善 (1周)         →  正式上线
```

---

## Phase A: 安全阻断修复（3 天）

### A1. AutoAgent API 添加认证 🔴 CRITICAL

**现状：** `routes/auto.py` 的 `/plan` 和 `/execute` 端点无 `Depends(get_current_user)`，任何人可无认证消耗 LLM 配额。

**修改：** `nexus/api/routes/auto.py`

```python
# 在函数签名中添加依赖注入
from nexus.security.auth import get_current_user

@router.post("/plan", response_model=PlanResponse)
async def auto_plan(
    request: Request,
    body: PlanRequest,
    current_user: dict = Depends(get_current_user),  # 新增
):
    # 使用 current_user["tenant_id"] 确保租户隔离
    ...
```

**同时修复：** `auto_execute` 创建工作流时必须设置 `tenant_id` 和 `created_by`：

```python
workflow = Workflow(
    ...
    tenant_id=current_user["tenant_id"],  # 新增
    created_by=current_user.get("user_id"),   # 新增
)
```

**测试：**
- 无 API Key 的请求应返回 401
- 有 API Key 的请求正常返回结果
- 创建的 Workflow 包含正确的 `tenant_id`

---

### A2. 轮换泄露的 API Key 🔴 CRITICAL

**现状：** `.env` 文件中包含真实 DeepSeek 和硅基流动 Key（已推送至 GitHub 公开仓库，必须立即轮换）。

**步骤：**
1. 登录 [DeepSeek Platform](https://platform.deepseek.com) → API Keys → 删除 `sk-3f2230835...` → 生成新 Key
2. 登录 [SiliconFlow](https://siliconflow.cn) → API Keys → 删除 `sk-ylicfemqg...` → 生成新 Key
3. 更新 `.env` 文件中的值
4. 确认 `.env` 被 `.gitignore` 忽略：`git check-ignore -v .env`
5. 确认 `.env.example` 中无真实值

---

### A3. JWT 路径添加速率限制 🔴 CRITICAL

**现状：** RateLimiter 仅集成在 API Key 认证路径中，JWT Bearer Token 路径无限制。

**修改：** `nexus/security/auth.py`

```python
# 在 get_current_user() 的 JWT 分支中添加
async def get_current_user(...):
    ...
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        # 新增：JWT 速率限制
        rate_limiter = RateLimiter(redis_client)
        user_id = payload.get("sub", "unknown")
        if not await rate_limiter.check(f"jwt:{user_id}", limit=200, window=60):
            raise RateLimitException()
        ...
```

---

### A4. RBAC 中间件扩展资源类型 🔴 CRITICAL

**现状：** `RBACMiddleware.KNOWN_RESOURCES` 仅含 7 种资源，遗漏 `prompts`, `evals`, `code-review`, `traces`, `mcp`, `auto`。

**修改：** `nexus/security/rbac.py`

```python
KNOWN_RESOURCES = {
    "workflows", "agents", "tools", "crews", "runs", "hitl", "tenants",
    "prompts", "evals", "code-review", "traces", "mcp", "auto",  # 新增
}
```

---

### A5. Worker 真实健康检查 🔴 CRITICAL

**现状：** `docker-compose.yml` 中 Worker 健康检查为 `exit 0`（永久成功）。

**修改：** `docker-compose.yml`

```yaml
worker:
  healthcheck:
    test: ["CMD-SHELL", "python -c 'import redis; r=redis.from_url(\"redis://redis:6379/0\"); r.ping()'"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 10s
```

**同时添加健康检查端点** `nexus/jobs/config.py`：

```python
# WorkerSettings 中添加 health endpoint
async def health_check():
    """检查 ARQ 连接和 Redis 状态."""
    try:
        from nexus.db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
```

---

### A6. 容器资源限制 🔴 CRITICAL

**现状：** 除 Redis 外，所有容器无 `mem_limit`/`cpus`。

**修改：** `docker-compose.yml`，为每个服务添加：

```yaml
api:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 1G
      reservations:
        cpus: '0.5'
        memory: 256M

worker:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 512M

postgres:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 512M

redis:
  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 384M
```

---

### A7. 前端 CORS 修复 🔴 CRITICAL

**现状：** 前端所有 API 调用被 CORS 拦截。

**根因分析：** 检查 `nexus/api/main.py` 中 CORS 中间件是否在 RBAC 中间件之前注册。确认 `ENVIRONMENT=development` 时 `allow_origins=["*"]`。

**修改：** 确保 CORS 中间件最先注册，且前端 dev server 的 proxy 配置正确：

```python
# main.py 中 CORS 必须在 RBACMiddleware 之前
app.add_middleware(CORSMiddleware, ...)  # 先 CORS
app.add_middleware(RBACMiddleware)        # 再 RBAC
```

---

## Phase B: 运维加固（5 天）

### B1. 自动数据库备份 ⚠️ HIGH

**新增：** `scripts/backup_db.sh`

```bash
#!/bin/bash
BACKUP_DIR="/backups/postgres"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose exec -T postgres pg_dump -U nexus nexus > "$BACKUP_DIR/nexus_$TIMESTAMP.sql"
find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION_DAYS -delete
```

**docker-compose.yml 新增备份服务：**

```yaml
db-backup:
  image: postgres:16-alpine
  volumes:
    - ./scripts/backup_db.sh:/backup.sh:ro
    - backup-data:/backups
  entrypoint: /bin/sh -c "while true; do /backup.sh; sleep 86400; done"
  profiles: [production]
```

---

### B2. 集中式日志 ⚠️ HIGH

**新增：** `docker-compose.yml` 添加 Loki + Promtail

```yaml
loki:
  image: grafana/loki:latest
  ports: ["3100:3100"]
  profiles: [monitoring]

promtail:
  image: grafana/promtail:latest
  volumes:
    - ./monitoring/promtail.yml:/etc/promtail/config.yml:ro
    - /var/lib/docker/containers:/var/lib/docker/containers:ro
  profiles: [monitoring]
```

**修改：** `nexus/config.py` 中 structlog 配置为 JSON 格式输出（生产环境）。

---

### B3. CI 安全扫描 ⚠️ HIGH

**修改：** `.github/workflows/ci.yml`

```yaml
- name: Security scan (SAST)
  run: pip install bandit && bandit -r nexus/ -f json -o bandit-report.json

- name: Dependency vulnerability scan
  run: pip install safety && safety check -r requirements.txt

- name: Docker image scan
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: nexus-api:latest
    format: table
    exit-code: 1
    severity: CRITICAL,HIGH
```

---

### B4. Worker 多实例 ⚠️ HIGH

**修改：** `docker-compose.yml`

```yaml
worker:
  deploy:
    replicas: 2  # 从 1 → 2
```

---

### B5. Node Exporter ⚠️ MEDIUM

**修改：** `docker-compose.yml`

```yaml
node-exporter:
  image: prom/node-exporter:latest
  ports: ["9100:9100"]
  volumes: [/proc:/host/proc:ro, /sys:/host/sys:ro, /:/rootfs:ro]
  command: ['--path.procfs=/host/proc', '--path.sysfs=/host/sys', '--path.rootfs=/rootfs']
  profiles: [monitoring]
```

---

### B6. 数据库连接池安全配置 ⚠️ MEDIUM

**修改：** `nexus/db/database.py`

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,  # 新增：1小时回收连接
)
```

---

## Phase C: 产品完善（1 周）

### C1. PIIGuard 集成 ⚠️ MEDIUM

**修改：** `nexus/agent/base.py` — 在 Agent 执行前检测输入：

```python
from nexus.security.pii_guard import PIIGuard

async def execute(self, task: Task) -> AgentResult:
    pii = PIIGuard()
    if pii.has_pii(task.description):
        task.description = pii.sanitize(task.description)
        logger.warning("PII detected and sanitized in task input")
    ...
```

---

### C2. 国际化完善 ⚠️ MEDIUM

**修改：** 所有前端页面中的硬编码中文替换为 `t('key')` 调用。
- `WorkflowEditor.vue` — "开始", "结束", "Agent" 等节点标签
- `Layout.vue` — 菜单项标签
- 错误消息 — 从硬编码中文改为 i18n key

---

### C3. 前端错误优雅降级 ⚠️ MEDIUM

**修改：** `nexus-ui/src/api/index.ts` 的响应拦截器

```typescript
// 当 CORS/网络错误时，不弹错误 toast
if (error.code === 'ERR_NETWORK' || error.message === 'Network Error') {
  // 静默降级，使用 mock 数据
  if (import.meta.env.DEV) {
    console.warn('API unavailable, using mock data')
    return Promise.resolve({ data: getMockData(config.url) })
  }
}
```

---

### C4. 覆盖率门禁提升 ⚠️ MEDIUM

**修改：** `.github/workflows/ci.yml`

```yaml
# 从 60% 逐步提升到 80%
- run: pytest tests/ --cov=nexus --cov-fail-under=75
```

---

### C5. E2E 集成测试加入 CI ⚠️ MEDIUM

**修改：** `.github/workflows/ci.yml`

```yaml
- name: E2E Integration tests
  run: |
    docker compose up -d postgres redis
    sleep 5
    pytest tests/test_e2e_integration.py -v -k "not Docker" --tb=short
```

---

## 📊 工作量估算

| Phase | 内容 | 工作量 | 事后状态 |
|-------|------|--------|---------|
| **A** | 安全阻断修复 (7项) | 3 天 | 🔒 内部 Beta 可用 |
| **B** | 运维加固 (6项) | 5 天 | ⚙️ 有条件上线 |
| **C** | 产品完善 (5项) | 1 周 | 🚀 正式上线 |
| **总计** | 18 项改进 | **~3 周** | 🟢 生产就绪 |

---

## 🎯 上线标准检查清单

- [ ] 所有 API 端点有认证（无公开端点消耗 LLM）
- [ ] API Key 已轮换，`.env` 不在仓库中
- [ ] JWT 和 API Key 路径均有速率限制
- [ ] RBAC 覆盖所有资源类型
- [ ] Worker 健康检查真实可用
- [ ] 容器有 CPU/内存限制
- [ ] 前端无 CORS 错误
- [ ] 自动数据库备份运行中
- [ ] CI/CD 含安全扫描
- [ ] Worker ≥2 实例
- [ ] 日志集中收集（Loki）
- [ ] PII 检测集成
- [ ] 国际化完成
- [ ] 覆盖率 ≥75%

---

**计划创建时间：** 2026-06-05
**预计完成：** 2026-06-26 (3 周)
