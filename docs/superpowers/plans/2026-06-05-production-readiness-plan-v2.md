# NEXUS 生产就绪优化计划 v2

> **来源：** 6 专家独立审查（后端架构 / DevOps / 安全 / QA / 数据库 / AI/ML） + 我本人独立验证 4 项关键发现 + 旧版计划 `2026-06-05-production-readiness-plan.md`（v1，**部分保留**）
> **目标：** 让 NEXUS 从 "内部 Beta PoC" 提升到 "能接外部付费流量"
> **创建：** 2026-06-05  •  **supersedes：** v1（保留作历史，新决策以本版为准）
> **预计周期：** 6-8 周（5 个 Sprint，每个 1-2 周）
> **预算建议：** 1 名高级后端 + 1 名 DevOps 兼安全 + 0.5 名 QA

---

## ⚠️ 立即执行项（24 小时内，必须先于一切）

### EM-1. 轮换 2 个已泄露的 LLM API Key  🔴 P0-CRITICAL

**现状（实锤）：** `.env` 包含真实生产密钥，**已经推送至公开仓库**：

```
DEEPSEEK_API_KEY=<REDACTED-DEEPSEEK-KEY>   ← 泄露
SILICONFLOW_API_KEY=<REDACTED-SILICONFLOW-KEY>  ← 泄露
```

**步骤：**

```bash
# 1. 立刻在供应商控制台删除旧 key（id 完整字符串不在这记录）
# DeepSeek:   https://platform.deepseek.com → API Keys → 删除旧 key → 生成新 key
# SiliconFlow: https://siliconflow.cn → API Keys → 删除旧 key → 生成新 key

# 2. 更新 .env（绝对不要 commit .env）
# 编辑 D:/AI_learning/nexus/.env 替换这两行

# 3. 立即验证 .env 在 .gitignore 中
git check-ignore -v .env
# 期望输出: .gitignore:...:.env  .env

# 4. 用 git-filter-repo 清理 git 历史（如果 .env 曾被 commit）
# 如果 git log 中能找到这些 key 的历史版本，必须清理：
git filter-repo --invert-paths --path .env
# 然后 force-push 并通知所有协作者重新 clone

# 5. 通知 DeepSeek/SiliconFlow 风控
# 如果这些 key 已被滥用，要求供应商查账单
```

**验证：**
```bash
# 旧 key 必须已撤销（用你自己的旧 key 字符串替换 <OLD_KEY>，不要在此处写真实 key）
curl -X POST https://api.deepseek.com/v1/chat/completions -H "Authorization: Bearer <OLD_KEY>"  # 应 401
# 新 key 工作正常
curl -X POST https://api.deepseek.com/v1/chat/completions -H "Authorization: Bearer $NEW_KEY"  # 200
```

**为什么排第一：** 一旦公开仓库被爬虫索引（GitHub 自动 + git history 永久可见），任何持有这两个 key 的人都能调用 LLM 到破产。**你的账单已经在计时。**

---

### EM-2. 替换 5 个未填占位符，否则 deploy.sh 立刻崩  🔴 P0-CRITICAL

**现状：** `.env` 有 5 处 `<...>` 字面值（不是真值，是模板里没替换），bash 严格模式解析时把 `<` 当成 stdin 重定向，整个 deploy.sh 在第一步就 abort。

```
DEV_API_KEY=<LEAVE_BLANK_FOR_PRODUCTION_OR_SET_FOR_DEV_TESTING>   ← bash 解析失败
LITELLM_MASTER_KEY=<REPLACE_WITH_STRONG_RANDOM_STRING>             ← bash 解析失败
OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>                              ← bash 解析失败
ANTHROPIC_API_KEY=<YOUR_ANTHROPIC_API_KEY>                        ← bash 解析失败
DASHSCOPE_API_KEY=<YOUR_DASHSCOPE_API_KEY>                        ← bash 解析失败
```

**修复（一次性的 `.env` 卫生 + 长期防御）：**

```bash
# 1. 立刻修 .env：把每个 <...> 替换为真实值或留空
# DEV_API_KEY=        (开发环境可设成 "dev-key-$(openssl rand -hex 8)")
# LITELLM_MASTER_KEY=$(openssl rand -hex 32)
# OPENAI/ANTHROPIC/DASHSCOPE_API_KEY  按需填或留空

# 2. 给 deploy.sh 加一道防御：source 之前用 python 解析
# 修改 scripts/deploy.sh 第 147-166 行 load_env()：
load_env() {
    if [ -f "${PROJECT_ROOT}/.env" ]; then
        # 先用 python 把 .env 解析成 KEY=VAL 形式，避开 bash 解析 < > 问题
        python3 -c "
import re, shlex
with open('${PROJECT_ROOT}/.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        # 跳过 <...> 占位符
        if re.match(r'^<[A-Z_]+>$', v.strip()):
            continue
        # 安全打印供 eval
        print(f'export {k.strip()}={shlex.quote(v.strip())}')
        " > /tmp/nexus_env.sh
        set -a
        # shellcheck source=/dev/null
        source /tmp/nexus_env.sh
        set +a
        echo -e "${GREEN}✓ .env loaded (placeholders skipped)${NC}"
    else
        echo -e "${YELLOW}⚠ .env file not found${NC}"
    fi
    # ... 后续不变
}
```

**验证：**
```bash
bash scripts/deploy.sh --layer backend   # 必须能正常跑过 detect_changes
grep -E "syntax error" /tmp/deploy.log    # 必须 0 命中
```

---

## 总体路线（5 个 Sprint）

```
Sprint 1 (1-2 周):  P0 阻塞 + 安全卫生
   ├── 立即执行项 EM-1, EM-2 (24 小时内)
   ├── 7 个 P0 阻塞修复（核心引擎、Redis HA、PostgreSQL RLS、JWT 校验）
   └── v1 计划保留的 4 个安全修复（A1, A3, A4, A5）

Sprint 2 (2 周):     可观测性 + 部署卫生
   ├── Prometheus 补全 exporter + 真实告警
   ├── Worker replicas 修复 + 独立 metrics 端口
   ├── UI healthcheck 修复
   ├── 备份脚本 + JWT 轮转脚本
   └── v1 计划保留的 B1-B6 运维加固

Sprint 3 (2 周):     测试质量
   ├── 修复 15 个红测试（或删除）
   ├── CI 去掉 `|| echo skipped` + 去掉 mock theatre
   ├── E2E 在 CI 真跑
   ├── 测试覆盖率 75% → 真行为覆盖率
   └── v1 计划 C4-C5

Sprint 4 (2 周):     架构纪律
   ├── BaseAgent 走 LLMService
   ├── Tool 沙箱（SSRF / chroot / timeout）
   ├── 成本控制 pre-call
   ├── PostgreSQL RLS 真启用
   ├── 软删除 + audit columns
   └── SQLAlchemy 2.0 DeclarativeBase 迁移

Sprint 5 (1-2 周):   加固 + 验收
   ├── 真实 ReAct 改造（tool messages）
   ├── 流式 + WebSocket 通路
   ├── Load test + chaos
   ├── 第三方安全审计
   ├── 灾备演练
   └── 上线 gate 全部勾完
```

---

## Sprint 1: P0 阻塞 + 安全卫生（1-2 周）

> **目标：** 修掉所有"现在就跑不起来或跑起来会出事"的问题。完成后可内部 Beta 测试。

### S1-1. `WorkflowEngine.resume()` 真正恢复执行  🔴 P0（核心引擎）
**文件：** `nexus/engine/workflow_engine.py:180-184`
**问题：** `resume()` 只改 status=RUNNING，从不调 `execute()`。**任何 HITL 工作流在 API 层会卡死。**
```python
# 当前（错）
async def resume(self, run_id: str, human_input: dict) -> None:
    state = await self.checkpoint_mgr.load(run_id)
    state.human_input = human_input
    await self.state_manager.update_status(run_id, RunStatus.RUNNING)
```
**改为：**
```python
async def resume(self, run_id: str, human_input: dict) -> None:
    """恢复执行：必须重新调用 execute() 才会真的继续。"""
    # 1. 把 human_input 注入到最近的 HITL 节点输出
    state = await self.checkpoint_mgr.load(run_id)
    state.human_input = human_input
    state.status = RunStatus.RUNNING

    # 2. 把 HITL 节点标 SUCCEEDED，让 super-step 看到依赖已满足
    for node_id, ns in state.node_states.items():
        if ns == NodeStatus.PAUSED:  # 假设有这个状态
            state.node_states[node_id] = NodeStatus.SUCCEEDED
    await self.checkpoint_mgr.save(run_id, state)

    # 3. 重新触发执行
    workflow_def = await self._load_workflow_def(run_id)
    # 在 Worker 进程里直接 await；API 进程里用 safe_background_task
    await self.execute(workflow_def, state.trigger_payload, run_id)
```
**测试（Sprint 1 必做）：**
```python
async def test_hitl_resume_continues_execution(workflow_engine, paused_state):
    """模拟 HITL 暂停后 resume，必须真的执行后续节点。"""
    # ... 触发一个含 HITL 节点的工作流到 PAUSED
    # 调 resume()
    # 断言后续节点被执行
```
**验收：** 新增 `tests/test_hitl_resume_e2e.py` 真实走通 pause → resume → 后续节点执行。

---

### S1-2. Redis 真正的高可用（替换硬编码）  🔴 P0
**文件：** 3 处
- `nexus/jobs/config.py:78-83`
- `nexus/jobs/pool.py:33-37`
- `nexus/jobs/config.py:131-150` (worker health_check)

**问题：** 应用代码硬编码 `host='redis-master'`，根本没用哨兵发现主节点。`configs/redis-sentinel.conf:21` 又把哨兵认证密码硬编码成明文。

**修复 1（哨兵发现主节点）：**
```python
# nexus/jobs/config.py
from redis.asyncio.sentinel import Sentinel

def _get_sentinel_client():
    """真·哨兵客户端：发现主节点、自动重连、监听 +sdown/-sdown。"""
    if not (settings.REDIS_SENTINEL_HOSTS and settings.use_redis_sentinel):
        # 单节点模式（向后兼容）
        return Redis.from_url(settings.REDIS_URL or "redis://localhost:6379/0")
    sentinels = [
        (h.split(":")[0], int(h.split(":")[1]))
        for h in settings.REDIS_SENTINEL_HOSTS.split(",")
    ]
    sentinel = Sentinel(
        sentinels,
        password=settings.REDIS_PASSWORD,
        sentinel_kwargs={"password": settings.REDIS_PASSWORD},
    )
    return sentinel.master_for(
        settings.REDIS_SENTINEL_MASTER,
        password=settings.REDIS_PASSWORD,
        socket_timeout=2,
    )
```
**修复 2（哨兵密码从 env 替换，不再硬编码）：**
```bash
# 修改 configs/redis-sentinel-entrypoint.sh，添加：
sed -i "s/__REDIS_PASSWORD__/${REDIS_PASSWORD:-}/g" /tmp/sentinel.conf
# 修改 configs/redis-sentinel.conf 模板：
sentinel auth-pass mymaster __REDIS_PASSWORD__
```
**修复 3（Worker healthcheck 也要用哨兵）：** 把 `r = Redis(host='redis-master', port=6379, ...)` 换成上面 `_get_sentinel_client()`。

**验收：**
```bash
# 强制 redis-master 宕机
docker stop nexus-redis-master
# 5 秒内 sentinel 应把 redis-replica-1 提升为新 master
docker logs nexus-redis-sentinel-1 | grep "switch-master"
# 期间 API 不应报错
curl -sf http://localhost:8765/health  # 持续 200
# 把旧 master 重新拉起
docker start nexus-redis-master
```

---

### S1-3. PostgreSQL RLS 真启用（不是写 README）  🔴 P0
**文件：** 新增 `nexus/db/migrations/versions/add_rls_policies.py`

**问题：** README 第 30 行写"PostgreSQL RLS + 端点级租户过滤"，但全仓库 grep 不到 `ENABLE ROW LEVEL SECURITY` / `CREATE POLICY`。**应用层 WHERE 漏一个 = 跨租户数据泄露。**

**修复（新增迁移）：**
```python
"""Enable Row-Level Security on all multi-tenant tables."""
from alembic import op

MULTI_TENANT_TABLES = [
    "workflows", "wf_runs", "node_runs", "wf_versions",
    "agents", "tools", "crews", "crew_runs",
    "hitl_tasks", "artifacts", "api_keys", "users",
    "audit_logs", "llm_call_traces", "prompt_templates",
    "prompt_experiments", "eval_runs",
]

def upgrade():
    # 1. 给每张表开 RLS
    for table in MULTI_TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # 2. 创建策略：仅当 GUC app.tenant_id 等于行 tenant_id 时可见
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id::text = current_setting('app.tenant_id', TRUE))
        """)

def downgrade():
    for table in MULTI_TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
```
**应用层 hook（每次请求设置 GUC）：**
```python
# nexus/db/database.py 新增
from sqlalchemy import event

@event.listens_for(AsyncSession, "after_begin")
def set_tenant_guc(session, transaction, connection):
    """事务开始时把 tenant_id 注入 PG 会话，GUC 驱动 RLS。"""
    tenant_id = getattr(session.info, "tenant_id", None)
    if tenant_id:
        connection.exec_driver_sql(
            f"SET app.tenant_id = '{tenant_id}'"
        )

# 在 get_current_user 之后，所有 Depends(get_db) 之前：
# router 加 dependency，在 db session 注入 tenant_id
async def db_with_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    db.info["tenant_id"] = request.state.user["tenant_id"]
    yield db
```
**验收：**
```python
async def test_rls_blocks_cross_tenant_query(db_session):
    """A 租户不能 SELECT B 租户的数据，即使应用层忘加 WHERE。"""
    # 插入两个租户的数据
    # 切换 app.tenant_id 到 A
    # 直接 SELECT * FROM workflows（无 WHERE），结果应只含 A 租户
```

---

### S1-4. JWT_SECRET_KEY 强制生产校验  🔴 P0
**文件：** `nexus/api/main.py:29-96`（`_validate_production_security` 函数）

**问题：** 函数存在但**从不调** `Settings.validate_jwt_secret_key()`。默认值 `nexus-jwt-dev-secret-not-for-production` 公开在 git，可直接上生产签发 admin token。

**修复（5 行）：**
```python
# nexus/api/main.py _validate_production_security() 内，第 56 行 SECRET_KEY 校验后追加：

    # JWT 密钥校验（与 SECRET_KEY 同等强度）
    try:
        settings.validate_jwt_secret_key()
    except ValueError as e:
        raise RuntimeError(
            f"SECURITY ERROR: {str(e)} "
            f"Set a strong JWT_SECRET_KEY (≥32 chars) via environment variable."
        ) from e
```

**验收：**
```bash
JWT_SECRET_KEY="nexus-jwt-dev-secret-not-for-production" ENVIRONMENT=production \
    python -c "from nexus.api.main import app"  # 必须 RuntimeError 退出
JWT_SECRET_KEY="$(openssl rand -hex 32)" ENVIRONMENT=production \
    python -c "from nexus.api.main import app; print('OK')"  # OK
```

---

### S1-5. nexus-ui 健康检查 wget 改 IPv4  🟡 P0（5 分钟修复）
**文件：** `nexus-ui/Dockerfile`（HEALTHCHECK 行）

**问题：** `wget -qO- http://localhost:80/` 解析到 IPv6 `::1` 失败（nginx 监听 IPv4），FailingStreak=84 次未被发现。

**修复：**
```dockerfile
HEALTHCHECK CMD wget -qO- http://127.0.0.1:80/ || exit 1
#                                ^^^^^^^^ 改这里
```
**外加：** `monitoring/prometheus.yml` 添加 nexus-ui 的 scrape target + 告警 `NexusUIFailingStreak`。

---

### S1-6. AutoAgent API 缺认证（保留 v1 计划 A1）  🔴 P0
**文件：** `nexus/api/routes/auto.py`
**修复：** 在 `/plan` 和 `/execute` 加 `Depends(get_current_user)` + 用 `current_user["tenant_id"]` 创建 Workflow。详见 v1 计划 A1。

---

### S1-7. JWT 路径加速率限制（保留 v1 计划 A3）  🔴 P0
**文件：** `nexus/security/auth.py:330-352`
**修复：** 调 `rate_limiter.check(f"jwt:{user_id}", limit=200, window=60)`。v1 计划 A3 已给代码。

---

### S1-8. RBAC 扩展资源类型（保留 v1 计划 A4）  🟡 P0
**文件：** `nexus/security/rbac.py:69` 的 `KNOWN_RESOURCES` 集合添加 `prompts, evals, code-review, traces, mcp, auto, dashboard`。

---

### S1-9. Worker 真实健康检查（保留 v1 计划 A5）  🟡 P0
**文件：** `nexus/jobs/config.py` + `docker-compose.yml`
**修复：** `health_check()` 加 DB SELECT 1 探测；compose healthcheck 改成 Redis ping。

---

### S1-10. 容器资源限制（保留 v1 计划 A6）  🟡 P0
**文件：** `docker-compose.yml`（每个服务加 `deploy.resources.limits`）

---

### Sprint 1 验收清单
- [ ] EM-1 真实 LLM key 已轮换 + 旧 key 在供应商端撤销
- [ ] EM-2 `bash scripts/deploy.sh` 不再因 .env 占位符崩溃
- [ ] HITL 工作流 E2E 测试（pause→human input→resume→继续执行）通过
- [ ] Redis 主节点宕机后 10 秒内 API 仍可服务
- [ ] PostgreSQL RLS 迁移执行成功；跨租户查询测试通过
- [ ] `JWT_SECRET_KEY` 默认值在 production 启动时拒绝
- [ ] nexus-ui FailingStreak=0
- [ ] `POST /api/v1/auto/execute` 无 token 返回 401
- [ ] JWT 用户在 60s 内超过 200 次请求被限流
- [ ] 所有容器有 CPU/内存限制

---

## Sprint 2: 可观测性 + 部署卫生（2 周）

### S2-1. Prometheus 补全 exporter  🟡 P1
**文件：** `monitoring/prometheus.yml`, `docker-compose.yml`

**问题：** 4 个 exporter 缺失（postgres_exporter, redis_exporter, minio, node_exporter, litellm, smart-cache, nexus-ui），**至少 3 个告警规则（DatabaseConnectionPoolExhausted / HighDiskUsage / QueueBacklog）永远不会触发。**

**修复：** compose 加 4 个 exporter 服务 + prometheus.yml 加 4 个 scrape target。

### S2-2. Worker replicas 修复 + 独立 metrics 端口  🟡 P1
**文件：** `nexus/jobs/config.py:78-83, 123`, `docker-compose.yml:541`, `monitoring/prometheus.yml:28`

**问题 1：** `replicas: 2` 但 `health_check_port=8080` 是 in-container，第二个 worker 启动会 port 冲突。
**问题 2：** ARQ 的 health_check_port 服务的是 plain `OK` 文本，不是 Prometheus 格式。**prometheus.yml 里的 worker:8080/metrics 是死的。**

**修复：**
```python
# nexus/jobs/config.py
# 删掉 health_check_port
# 在 on_startup 钩子里启动 prometheus_client HTTP server
from prometheus_client import start_http_server
start_http_server(9090)  # 每个 worker 进程独立端口 9090
```
```yaml
# docker-compose.yml worker 改成普通 service（不用 deploy.replicas）
worker:
  ports: ["9090:9090"]  # 注意：2 个 worker 都映射到宿主同一端口会冲突
# 改用：
worker-1: { ports: ["9091:9090"] }
worker-2: { ports: ["9092:9090"] }
```
```yaml
# monitoring/prometheus.yml
- job_name: 'nexus-worker'
  static_configs:
    - targets: ['worker-1:9090', 'worker-2:9090']
```

### S2-3. nexus-ui 改回正常健康检查（同时 S1-5）  🟢

### S2-4. 备份脚本 + 默认 port 修正  🟡 P1
**文件：** `scripts/backup_postgres.sh:37`

**问题：** 默认 `DB_PORT=5432` 但 compose 用 5433，**每次手敲 DB_PORT=5433 才能跑**。

**修复：**
```bash
# 改成 docker exec 默认
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"  # 与 .env 里的 POSTGRES_PORT 对齐
PG_DUMP_CMD="docker exec nexus-postgres-primary pg_dump -U ${POSTGRES_USER:-nexus} -d ${POSTGRES_DB:-nexus}"
# 加 --verify 模式调用 gzip -t 校验
```

### S2-5. JWT 轮转脚本 + 自动重启容器  🟡 P1
**文件：** `scripts/rotate_jwt_keys.py:182`

**问题：** 改 .env 但不重启 api/worker，新 key 永远在磁盘，进程里还是旧 key。

**修复：**
```python
# 追加：
subprocess.run(["docker", "compose", "restart", "api", "worker"], check=True)
logger.info("API and worker containers restarted with new JWT key")
```

### S2-6. Worker 资源限制 + 告警真实可用  🟢（保留 v1 计划 B5-B6）

### Sprint 2 验收清单
- [ ] Prometheus 看到 9 个以上的 scrape target（api, 2xworker, postgres, redis, minio, node, litellm, smart-cache, ui）
- [ ] `DatabaseConnectionPoolExhausted` 告警能在真用满连接池时触发
- [ ] 2 个 worker 都能启动且 metrics 可拉取
- [ ] 备份脚本 `bash scripts/backup_postgres.sh --verify` 一键成功
- [ ] 轮转 JWT 后新 token 立即生效

---

## Sprint 3: 测试质量（2 周）

### S3-1. 修复或删除 15 个红测试  🔴 P1
**文件：** `tests/test_workflow_engine_edge_cases.py`
**问题：** P1 报告自己承认 15 个 fail，被 demote 到 P2。**CI 跑的 75% 覆盖率里包含这些红测试，gate 形同虚设。**

**修复：**
```bash
# 选 1：花时间修（预计 3-5 天）
# 选 2：删除（P1 报告说"fixture 使用不当"是测试本身的问题）
# 推荐选 2，把 fixture 改对后重写 5-10 个真正有意义的边界测试
```

### S3-2. 删除 CI 的 `|| echo "skipped"`  🔴 P1
**文件：** `.github/workflows/ci.yml:45`
```yaml
# 当前（错）
- run: pytest tests/test_e2e_integration.py -v --tb=short -k "not test_0" || echo "E2E tests skipped (no Docker in CI)"
# 改为：把 E2E step 直接删掉，迁移到独立的 nightly workflow
```

### S3-3. 拆掉 engine 测试的 mock theatre  🟡 P1
**文件：** `tests/conftest.py:189-271`（mock_state_manager 等 5 个 fixtures）

**问题：** 5 个 `MagicMock(spec=...)` 替换引擎的协作者，**测的不是系统，是 mock 被调用了**。

**修复：**
```python
# conftest.py 改用真实的 in-memory 实现：
@pytest.fixture
def workflow_engine(db_session, event_bus_redis_free):
    """用真实 in-memory state/checkpoint + 临时 Redis 替代 mock。"""
    state_mgr = StateManager()  # 用真实实现，不用 mock
    cp_mgr = CheckpointManager(db=db_session)  # 真 DB
    return WorkflowEngine(
        state_manager=state_mgr,
        event_bus=event_bus_redis_free,
        checkpoint_mgr=cp_mgr,
        variable_pool=VariablePool(),
        router_engine=RouterEngine(),
    )
```
**预计影响：** 16/32 个 engine 测试可能要重写，但行为覆盖率会真正上升。

### S3-4. E2E 在 CI 真跑（不靠 mock）  🟡 P1
**修复：**
```yaml
# .github/workflows/ci.yml 新增 job
e2e:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:16
      env:
        POSTGRES_PASSWORD: test
    redis:
      image: redis:7
  steps:
    - uses: actions/checkout@v4
    - run: pip install -r requirements-dev.txt
    - run: pytest tests/test_e2e_integration.py -v --tb=short
```

### S3-5. 删除 test_api.py 11 处静默 skip  🟡 P1
**文件：** `tests/test_api.py`（line 181, 207, 234, 263, 291, 316, 342, 367, 445, 472, 562）
**修复：** 把 `pytest.skip("Create failed, skipping X test")` 改成 `pytest.fail("Create endpoint regressed: ...")`

### Sprint 3 验收清单
- [ ] `pytest tests/ -v --tb=short` **0 失败、0 skip**
- [ ] 删掉或修复 15 个红测试
- [ ] CI 跑 E2E 失败时 PR 真的被挡
- [ ] 覆盖率仍是 75%，但**有 ≥40% 来自真实集成路径**（不是 mock）

---

## Sprint 4: 架构纪律（2 周）

### S4-1. BaseAgent 走 LLMService（让 fallback 真的生效）  🟡 P1
**文件：** `nexus/agent/base.py:240-264`
**修复：**
```python
# base.py 改：
from nexus.services.llm_service import LLMService
# 初始化时
self.llm_service = llm_service or LLMService()
# execute_loop 里
async with self._get_semaphore():
    response = await self.llm_service.generate(
        messages=messages,
        system_prompt=system_prompt,
        model=self.config.model,
        provider=self.config.provider,
        # ... 其他参数
    )
```
**验收：** kill `litellm` 容器后调 agent，**自动 fallback 到下一个 provider**（在 settings.LLM_FALLBACK_CHAIN 里配置）。

### S4-2. Tool 层沙箱（SSRF + chroot + timeout）  🔴 P1
**文件：** `nexus/tools/connectors/http_tool.py`, `file_tool.py`, `registry.py:194-215`

**问题：** HTTP tool 接任何 url（SSRF 到 169.254.169.254 拿 AWS metadata）；file tool 写任意路径（chroot 缺失）；tool 没有统一 timeout。

**修复（SSRF）：**
```python
# nexus/tools/connectors/http_tool.py
import ipaddress
from urllib.parse import urlparse

BLOCKED_CIDRS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # metadata!
    ipaddress.ip_network("::1/128"),
]

async def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolExecutionException("http_tool", "only http(s) allowed")
    # 解析 host，检查不在内网
    import socket
    infos = await asyncio.get_event_loop().getaddrinfo(parsed.hostname, None)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in cidr for cidr in BLOCKED_CIDRS):
            raise ToolExecutionException("http_tool", f"blocked private IP: {ip}")
```
**修复（chroot）：**
```python
WORKSPACE_ROOT = "/app/data/agent_workspace"  # 配置项

async def _validate_path(path: str) -> str:
    abs_path = os.path.realpath(path)
    if not abs_path.startswith(os.path.realpath(WORKSPACE_ROOT)):
        raise ToolPermissionDeniedException("file_tool", f"path escapes workspace: {path}")
    return abs_path
```
**修复（统一 timeout）：**
```python
# registry.py
DEFAULT_TOOL_TIMEOUT = 30  # 可被 tool.config 覆盖

# 在 execute() 里包一层
async def execute(self, tool_name, params, context, timeout=None):
    timeout = timeout or self.get_tool(tool_name).config.get("timeout", DEFAULT_TOOL_TIMEOUT)
    return await asyncio.wait_for(
        self._do_execute(tool_name, params, context),
        timeout=timeout,
    )
```

### S4-3. 成本控制 pre-call 拦截  🟡 P1
**文件：** `nexus/billing/meter.py`, `nexus/services/llm_service.py`

**问题：** UsageMeter 在内存里，无 DbUsageMeter 实例化。**没有任何 pre-call 拦截。**

**修复：**
```python
# nexus/services/llm_service.py generate() 开头加：
async def generate(self, ...):
    tenant_id = context.get("tenant_id")
    if tenant_id:
        # 用 DbUsageMeter 而非内存版
        usage = await DbUsageMeter.get_current_month(tenant_id)
        plan = await BillingPlan.get_for_tenant(tenant_id)
        if usage.total_tokens >= plan.max_tokens_per_month:
            raise QuotaExceededException(
                f"Tenant {tenant_id} exceeded {plan.max_tokens_per_month} tokens this month"
            )
    return await self._do_generate(...)
```

### S4-4. SQLAlchemy 2.0 风格迁移  🟢 P2
**文件：** `nexus/db/database.py:22`
```python
# 当前：legacy
from sqlalchemy.orm import declarative_base
Base = declarative_base()
# 改为 2.0 风格
from sqlalchemy.orm import DeclarativeBase
class Base(DeclarativeBase):
    pass
```

### S4-5. 软删除 + audit columns  🟢 P2
- 所有业务表加 `deleted_at: Mapped[datetime | None]`
- 删除改 UPDATE deleted_at，**CASCADE 改成 NULL**
- 加 `updated_by`, `ip_address`, `user_agent` 列

### S4-6. 修 4 处 fire-and-forget asyncio.create_task  🟢 P2
**文件：** `nexus/api/main.py:222, 243`, `nexus/engine/event_bus.py:94`, `nexus/observability/llm_tracer.py:192`

**修复：** 全部换成 `safe_background_task()`。

### S4-7. 数据库缺少的 FK  🟢 P2
**文件：** `nexus/db/migrations/versions/initial_migration.py:299, 316, 330, 391` 给 `crew_runs.tenant_id` / `eval_runs.tenant_id` / `llm_call_traces.tenant_id` / `prompt_experiments.tenant_id` 加 `ForeignKey('tenants.id')`。

### Sprint 4 验收清单
- [ ] Kill LiteLLM 后 agent 自动 fallback（log 显式说明）
- [ ] agent 试图访问 `http://169.254.169.254/` 被工具层拒绝
- [ ] agent 试图写 `/etc/passwd` 被 chroot 拒绝
- [ ] 单租户超过月配额，LLM 调用直接 429 / 报错
- [ ] 测试中 `Base = declarative_base()` 不再出现

---

## Sprint 5: 加固 + 验收（1-2 周）

### S5-1. 真实 ReAct 改造（tool messages）  🟢 P2
**文件：** `nexus/agent/base.py:226-364`

**问题：** 当前 ReAct 是字符串拼接，不是 messages=[{role:tool, ...}]。**multi-turn tool call 会断上下文。**

**修复：** 维护真正的 `messages` 列表，tool 执行后追加 `{role: "tool", tool_call_id: ..., content: ...}` 而不是拼到 user_prompt。

### S5-2. 流式 LLM → WebSocket 通路  🟢 P2
**文件：** `nexus/api/websocket.py:90-119`, `nexus/agent/base.py:240-264`

**修复：** 把 `LLMClient.stream_call()` 的 chunks 灌进 EventBus → WebSocket，前端就能看到打字机效果。

### S5-3. pgbouncer / 连接池治理  🟢 P2
- 加 pgbouncer 容器，复用连接
- 调小 pool_size=5, max_overflow=10（per replica）
- Postgres `max_connections=300`

### S5-4. off-host 备份  🟢 P2
**修复：** 备份用 rclone 推到 S3/MinIO + 加密 + 30 天保留。

### S5-5. Load test + chaos engineering  🟡 P1
- k6 跑 100 RPS × 10 分钟，看 P95 < 300ms
- kill -9 随机容器，验证自动恢复
- Redis 哨兵 failover 实测

### S5-6. 第三方安全审计  🟡 P1
- 找外部安全公司做一次渗透测试
- bandit/safety 全绿

### S5-7. 灾备演练  🟢 P2
- 整个 Postgres 容器删除，从 backup 恢复
- 演练 RTO < 1h, RPO < 15min

### Sprint 5 验收清单
- [ ] k6 load test: 100 RPS 下 P95 < 300ms, 0 错误
- [ ] 第三方安全审计 ≤ 0 critical, ≤ 3 high
- [ ] 灾备演练恢复时间 < 1 小时
- [ ] 文档（README, CLAUDE.md, 错误码表）数字与实际 CI 输出对齐

---

## 总体时间线

```
Sprint 1 (1-2 周):  P0 阻塞 + 安全卫生           [~10 工作日]
   ↑ 包含 EM-1/EM-2（24 小时内）
Sprint 2 (2 周):     可观测性 + 部署卫生          [~10 工作日]
Sprint 3 (2 周):     测试质量                    [~10 工作日]
Sprint 4 (2 周):     架构纪律                    [~10 工作日]
Sprint 5 (1-2 周):   加固 + 验收                  [~5-10 工作日]
─────────────────────────────────────────────
总计: 6-8 周 ≈ 45-60 工作日（1 senior + 1 devops + 0.5 QA）
```

---

## 关键成功指标（上线 gate）

### 必须 100% 通过

| 指标 | 当前 | 目标 |
|------|------|------|
| `pytest tests/` 失败数 | 15+ | **0** |
| `pytest tests/ --cov-fail-under` | 75%（mock 撑的） | 75%（**真行为**） |
| 默认 `bash scripts/deploy.sh` | bash syntax error 崩 | 正常完成 |
| `.env` 包含真实泄漏 LLM key | 2 个 | **0** |
| 跨租户数据查询测试 | N/A（无 RLS） | 100% 拒绝 |
| `JWT_SECRET_KEY` 默认值启动 prod | 接受 | 拒绝 |
| `redis-master` 宕机 → API 可用 | 不可用 | 10 秒内恢复 |
| nexus-ui FailingStreak | 84 | 0 |
| `bandit -r nexus/ -ll` | 0 high | 0 high |
| `safety check -r requirements.txt` | `\|\| true` 吞掉 | 0 critical |
| POST /api/v1/auto/* 无 token | admin 访问 | 401 |
| Redis 真实哨兵发现主节点 | 假的（直连） | 真的 |
| HITL pause→resume→继续执行 | 卡死 | 真执行 |

### 推荐但非阻塞

- 覆盖率从 mock 75% 升到 真实 80%+
- P95 < 300ms @ 100 RPS
- 文档（README badge、CLAUDE.md 数字）与 CI 输出一致
- 100% Docker compose 服务有 healthcheck
- 所有 Prometheus 告警规则有对应 exporter

---

## 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| DeepSeek/SiliconFlow key 在公开仓库被滥用 | **高**（已经被推） | 严重 | **EM-1 立刻轮换** |
| 修 HITL resume 暴露更多引擎 bug | 中 | 中 | 把 HITL 测试做厚，覆盖率 ≥ 90% |
| Redis HA 改造引入新 bug | 中 | 高 | 写专门的 failover 集成测试 |
| 修测试 mock theatre 时大面积 fail | 中 | 中 | 一个模块一个模块迁移，不一次性全拆 |
| RLS 引入性能问题 | 中 | 中 | 基准测试对比；必要时关闭 RLS、保留应用层过滤 |
| 第三方安全审计发现更多 critical | 中 | 高 | 准备延后 2-3 周处理 |

---

## 与 v1 计划的关系

| v1 项 | 本计划位置 | 状态 |
|-------|-----------|------|
| A1: AutoAgent 缺认证 | S1-6 | ✅ 保留 |
| A2: 轮换泄露 API Key | **EM-1（提升至 24 小时内）** | ✅ 保留 + 升级 |
| A3: JWT 速率限制 | S1-7 | ✅ 保留 |
| A4: RBAC 资源类型 | S1-8 | ✅ 保留 |
| A5: Worker 真实健康检查 | S1-9 | ✅ 保留 |
| A6: 容器资源限制 | S1-10 | ✅ 保留 |
| A7: CORS 修复 | 删 | ❌ 验证后 CORS 在 dev `["*"]` 是预期行为，非 bug |
| B1-B6: 运维加固 | S2-1, S2-2, S2-4-S2-6 | ✅ 保留（拆分更细） |
| C1: PII 集成 | S5-1 之后 | 推迟到 Sprint 5（PIIGuard 自身有 bug，先别用） |
| C2: 国际化 | 不在本计划 | 推迟到 Sprint 5+（产品需求） |
| C3: 前端错误降级 | 删 | 已是 existing feature（`nexus-ui/src/api/index.ts`） |
| C4: 覆盖率门禁 | Sprint 3 验收的一部分 | ✅ 吸收 |
| C5: E2E CI | S3-4 | ✅ 吸收 |

**本计划比 v1 多了：**
- Redis 真 HA 修复（v1 完全漏掉）
- PostgreSQL RLS 真启用（v1 完全漏掉）
- WorkflowEngine.resume() 修复（v1 完全漏掉，**最高优先级**）
- 7 个未填占位符导致 deploy 崩溃（v1 完全漏掉）
- 真实 ReAct、流式通路、pII guard 推迟（v1 误以为可立即做）
- 测试质量整体改造（v1 只有覆盖率数字，没有真伪）

---

## 上线前最后 1 周的硬性 checklist

- [ ] **EM-1 完成**：旧 key 撤销，新 key 验证可用
- [ ] 所有 5 个 Sprint 验收清单 100% 通过
- [ ] 第三方安全审计报告 ≤ 0 critical
- [ ] Load test 通过：100 RPS × 10 min, P95 < 300ms
- [ ] Chaos test 通过：kill -9 任一容器，30 秒内自动恢复
- [ ] 灾备演练通过：删 Postgres，从 backup 恢复 < 1 小时
- [ ] 文档同步：README.md 的 "245 tests passed" 改成实际 CI 输出的数字；CLAUDE.md 同步；错误码表同步
- [ ] 第一次正式发布：tag `v1.0.0-rc.1`，灰度 5% 流量 24 小时
- [ ] 24 小时灰度内 0 事故 → 100% 流量 → 公开宣布

---

**计划创建时间：** 2026-06-05
**预计完成：** 2026-08 中下旬（约 6-8 周）
**supersedes：** `2026-06-05-production-readiness-plan.md`（v1，保留作历史）
