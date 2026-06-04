# P11b — 能力深化冲刺：向量记忆 + RBAC + HITL恢复 + 前端重构 + OpenTelemetry

> **面向 AI 代理的工作者：** 使用 superpowers:subagent-driven-development 逐任务实现。

**目标：** 在一个月内深化 NEXUS 核心能力，将 Agent 记忆升级为向量语义检索、RBAC 权限从框架落地为可执行、HITL 支持 Worker 崩溃恢复、前端完成高频视图重构、OpenTelemetry 真正启用。

**前提：** P11a 已完成（测试覆盖率 ≥60%，安全修复到位）

---

## 工作包总览

| 工作包 | 时间 | 目标 |
|--------|------|------|
| B1 AgentMemory 向量检索 | Week 1-2 | 关键词匹配 → pgvector 语义检索 |
| B2 RBAC 权限落地 | Week 1-2 | `_check_permission` 从 `return True` → 真实 RBAC |
| B3 HITL 状态恢复 | Week 3 | Worker 重启后恢复 HITL 等待状态 |
| B4 前端组件化重构 | Week 3-4 | 5个高频视图迁移到通用组件 |
| B5 OpenTelemetry 启用 | Week 4 | `ENABLE_OPENTELEMETRY=false` → 可用 |

---

## B1: AgentMemory 向量检索改造

**文件范围：**
- 新建: `nexus/agent/vector_memory.py` (VectorMemoryBackend)
- 修改: `nexus/agent/memory.py`, `nexus/agent/memory_backend.py`
- 修改: `nexus/config.py` (新增 VECTOR_MEMORY_* 配置)
- 修改: `docker-compose.yml` (pgvector 镜像)
- 测试: `tests/test_vector_memory.py`

**验收标准：**
- [x] pgvector 扩展集成
- [x] VectorMemoryBackend 实现 MemoryBackend 接口
- [x] AgentMemory 支持 `backend="vector"` 配置
- [x] Embedding 服务集成
- [x] 测试覆盖 80%+
- [x] 检索延迟 < 50ms

---

## B2: RBAC 权限落地

**文件范围：**
- 修改: `nexus/engine/permission_engine.py`
- 修改: `nexus/tools/registry.py` (`_check_permission`)
- 修改: `nexus/security/rbac.py`
- 新建: `nexus/security/permissions.py` (权限定义)
- 测试: `tests/test_permissions.py`

**验收标准：**
- [ ] 权限资源枚举定义
- [ ] PermissionEngine.check() 真实实现
- [ ] ToolRegistry 集成权限校验
- [ ] API 路由级权限检查
- [ ] 权限测试覆盖

---

## B3: HITL 状态恢复机制

**文件范围：**
- 修改: `nexus/engine/hitl_controller.py`
- 修改: `nexus/jobs/config.py` (Worker 启动钩子)
- 修改: `nexus/models/hitl.py` (状态机扩展)
- 测试: `tests/test_hitl_recovery.py`

**验收标准：**
- [ ] HITL waiting 状态
- [ ] Worker 启动扫描恢复
- [ ] 全局 HITL 超时监控
- [ ] EventBus 重新订阅
- [ ] 测试覆盖

---

## B4: 前端组件化重构

**文件范围：**
- 修改: `nexus-ui/src/views/Agents.vue`, `Crews.vue`, `Tools.vue`, `HITLTasks.vue`, `Settings.vue`
- 新建: `nexus-ui/src/components/common/SearchFilter.vue`, `EmptyState.vue`, `ErrorBoundary.vue`
- 测试: `nexus-ui/vitest.config.ts`

**验收标准：**
- [ ] 5 个视图完成 DataTable/StatusBadge 迁移
- [ ] 3 个通用组件可复用
- [ ] ErrorBoundary 包裹根组件
- [ ] 前端测试配置就绪

---

## B5: OpenTelemetry 启用

**文件范围：**
- 修改: `nexus/observability/` (OpenTelemetry 配置)
- 修改: `nexus/api/main.py` (instrumentation)
- 修改: `docker-compose.yml` (Jaeger/OTLP)
- 修改: `nexus/config.py`

**验收标准：**
- [ ] OTLP Exporter 配置
- [ ] FastAPI 自动 instrumentation
- [ ] 自定义 Span (WorkflowRun/Agent决策/LLM调用)
- [ ] 测试验证 Trace 生成

---

**计划创建时间:** 2026-06-04
**预计工期:** 4 周
