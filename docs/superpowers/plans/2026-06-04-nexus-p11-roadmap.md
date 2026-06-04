# NEXUS P11 阶段总体路线图

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 基于 NEXUS 现状分析，制定 P11 阶段（测试补强 → 功能深化 → 生态建设）的完整开发路线图，消除关键风险并推动项目向生产级成熟度演进。

**架构：** 采用三阶段冲刺模式（P11a → P11b → P11c），每阶段聚焦单一主题，产出可独立交付的增量。优先消除安全和可靠性风险，再逐步深化功能。

**技术栈：** Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL / Redis / Vue 3 / Docker / pytest

---

## 📊 现状基线

| 维度 | 当前值 | 目标值 |
|------|--------|--------|
| 测试覆盖率 | 46% | 70%+ (P11b结束) |
| 核心引擎测试 | 7-31% | 60%+ (P11a结束) |
| 0%覆盖率模块 | 5个 | 0个 (P11a结束) |
| 前端功能可用度 | 部分mock | 全部真实数据 (P11a结束) |
| AgentMemory | 关键词匹配 | 向量语义检索 (P11b结束) |
| RBAC权限 | 框架化 | 落地实施 (P11b结束) |

---

## 🗓️ 三阶段路线图

### P11a — 稳定性冲刺（2周）

**主题：消除安全风险 + 补齐测试短板 + 修复前端基础功能**

#### 目标产出
- [ ] 核心引擎测试覆盖率从 7-31% → 60%+
- [ ] 5个0%覆盖率模块补齐基础测试
- [ ] 修复21个失败测试
- [ ] CI/CD增加覆盖率门禁（≥60%）
- [ ] `.env` 加入 `.gitignore`，消除敏感信息泄露风险
- [ ] `Login.vue` 接入真实JWT认证
- [ ] `Workflows.vue` / `WorkflowRuns.vue` 接入真实API数据
- [ ] `Analytics.vue` 接入真实分析数据

#### 详细执行计划
📄 **独立计划文件：** `2026-06-04-p11a-test-security-sprint.md`

---

### P11b — 能力深化冲刺（1个月）

**主题：核心功能深化 + 架构增强 + 前端体验提升**

#### 2.1 AgentMemory 向量检索改造（Week 3-4）

**目标：** 将关键词匹配升级为真正的向量语义检索

**技术方案：**
- 集成 `pgvector` 扩展（PostgreSQL原生向量支持）
- 使用 `BAAI/bge-small-zh-v1.5` 作为Embedding模型
- 改造 `AgentMemory` 接口，保持向后兼容

**产出：**
- [ ] `pgvector` 扩展安装与迁移
- [ ] `VectorMemoryBackend` 实现（实现 `MemoryBackend` 接口）
- [ ] `AgentMemory` 支持配置切换 backend（`memory` / `redis` / `vector`）
- [ ] Embedding服务集成（本地模型或HTTP调用）
- [ ] 向量检索测试覆盖
- [ ] 性能基准测试（检索延迟 <50ms）

**文件范围：**
- 新建：`nexus/agent/vector_memory.py`
- 修改：`nexus/agent/memory.py`, `nexus/agent/memory_backend.py`
- 修改：`nexus/config.py`（新增 VECTOR_MEMORY_* 配置）
- 修改：`docker-compose.yml`（pgvector镜像）
- 测试：`tests/test_agent_memory.py`, `tests/test_vector_memory.py`

📄 **独立计划文件：** `2026-06-04-p11b-vector-memory.md`

---

#### 2.2 RBAC 权限落地（Week 3-4）

**目标：** 将 `_check_permission` 的硬编码 `return True` 替换为真实权限校验

**技术方案：**
- 完善 `PermissionEngine`（已存在 `nexus/engine/permission_engine.py`）
- 实现 `ToolRegistry._check_permission()` 真实逻辑
- API Key 的 `permissions` 字段解析与校验
- 权限资源定义（`workflow:*`, `agent:*`, `tool:*` 等）

**产出：**
- [ ] 权限资源枚举定义
- [ ] `PermissionEngine.check()` 实现
- [ ] `ToolRegistry` 集成权限校验
- [ ] API路由级权限装饰器（`@require_permission`）
- [ ] 权限测试覆盖

**文件范围：**
- 修改：`nexus/engine/permission_engine.py`
- 修改：`nexus/tools/registry.py`
- 修改：`nexus/security/rbac.py`
- 新建：`nexus/security/permissions.py`
- 测试：`tests/test_permissions.py`, `tests/test_tool_registry_auth.py`

📄 **独立计划文件：** `2026-06-04-p11b-rbac-implementation.md`

---

#### 2.3 HITL 状态恢复机制（Week 5）

**目标：** 解决 Worker 重启丢失 HITL 等待状态的问题

**技术方案：**
- HITL 任务启动时写入 DB `status = waiting`
- Worker 启动时扫描 DB 中 `waiting` 状态的 HITL 任务
- 重新订阅 EventBus 并恢复等待

**产出：**
- [ ] HITL 状态机扩展（`waiting` 状态）
- [ ] Worker 启动恢复逻辑
- [ ] 全局 HITL 超时监控
- [ ] 测试覆盖

📄 **独立计划文件：** `2026-06-04-p11b-hitl-recovery.md`

---

#### 2.4 前端组件化重构（Week 5-6）

**目标：** 完成剩余 19 个视图的通用组件迁移

**优先级视图：**
1. `Agents.vue` → DataTable + StatusBadge
2. `Crews.vue` → DataTable + StatusBadge
3. `WorkflowRuns.vue` → DataTable
4. `HITLTasks.vue` → DataTable + StatusBadge
5. `Tools.vue` → DataTable + FormBuilder

**产出：**
- [ ] 5个高频视图重构完成
- [ ] 新增 SearchFilter / EmptyState / LoadingSkeleton 组件
- [ ] 路由守卫实现
- [ ] Vue 错误边界组件
- [ ] 前端 Vitest 测试框架配置

**文件范围：**
- 修改：`nexus-ui/src/views/*.vue`
- 新建：`nexus-ui/src/components/common/SearchFilter.vue`
- 新建：`nexus-ui/src/components/common/EmptyState.vue`
- 新建：`nexus-ui/src/components/common/ErrorBoundary.vue`
- 修改：`nexus-ui/src/router/index.ts`
- 新建：`nexus-ui/src/stores/auth.ts`

📄 **独立计划文件：** `2026-06-04-p11b-frontend-refactor.md`

---

#### 2.5 OpenTelemetry 启用（Week 6）

**目标：** 将 `ENABLE_OPENTELEMETRY=false` 变为可用状态

**产出：**
- [ ] OpenTelemetry SDK 配置完善
- [ ] FastAPI 自动instrumentation
- [ ] 自定义 span 标注（WorkflowRun / Agent决策 / LLM调用）
- [ ] Jaeger 或 OTLP Collector 集成
- [ ] 文档更新

📄 **独立计划文件：** `2026-06-04-p11b-opentelemetry.md`

---

### P11c — 生态建设冲刺（2个月）

**主题：工具生态 + 行业模板 + 开发者体验**

#### 3.1 工具市场与预置连接器（Month 2）

**目标：** 构建预置工具库，降低用户上手门槛

**预置工具清单：**
- 飞书/Lark 连接器（消息发送/群聊/审批）
- 钉钉连接器
- 企业微信连接器
- Notion 连接器
- Jira 连接器
- 邮件发送工具
- 文件处理工具（PDF/Excel/Word）
- 搜索引擎工具（Bing/Google/SerpAPI）

**产出：**
- [ ] 工具分类体系
- [ ] 10+ 预置工具实现
- [ ] 工具配置UI（表单自动生成）
- [ ] 工具文档自动生成

📄 **独立计划文件：** `2026-06-04-p11c-tool-marketplace.md`

---

#### 3.2 垂直行业Agent模板（Month 2-3）

**目标：** 提供开箱即用的行业解决方案模板

**模板清单：**
- 代码审查专家（增强现有）
- 客服自动化Agent
- 数据分析报告Agent
- 合同审查Agent
- 会议纪要生成Agent
- 测试用例生成Agent

**产出：**
- [ ] 模板定义格式（JSON Schema）
- [ ] 模板市场UI
- [ ] 模板导入/导出功能
- [ ] 6个预置模板

📄 **独立计划文件：** `2026-06-04-p11c-agent-templates.md`

---

#### 3.3 SDK与CLI完善（Month 3）

**目标：** 提供完整的开发者工具链

**产出：**
- [ ] Python SDK (`nexus-sdk`) 封装
- [ ] CLI 工具增强（`nexus_cli.py` 扩展）
- [ ] API 客户端生成（OpenAPI → TypeScript/Python）
- [ ] 完整开发者文档

📄 **独立计划文件：** `2026-06-04-p11c-sdk-cli.md`

---

## 📋 依赖关系图

```
P11a (2周) ───────────────────────────────────────────────┐
├── 测试补强 ──→ 所有后续任务的基础                            │
├── 安全修复 ──→ 生产部署前置条件                              │
└── 前端mock修复 ──→ P11b前端重构基础                          │
                                                            ▼
P11b (1月) ─────────────────────────────────────────────────┤
├── 向量记忆 ──→ Agent能力质变                                │
├── RBAC落地 ──→ 企业级安全                                   │
├── HITL恢复 ──→ 可靠性增强                                   │
├── 前端重构 ──→ 用户体验                                     │
└── OpenTelemetry ──→ 可观测性完善                            │
                                                            ▼
P11c (2月) ─────────────────────────────────────────────────┘
├── 工具市场 ──→ 生态扩展
├── 行业模板 ──→ 商业价值
└── SDK/CLI ──→ 开发者体验
```

---

## 🎯 关键里程碑

| 里程碑 | 日期 | 验收标准 |
|--------|------|---------|
| P11a 完成 | +2周 | 覆盖率≥60%，0%模块清零，CI门禁启用，前端无mock |
| P11b 完成 | +6周 | 向量记忆可用，RBAC生效，HITL可靠，前端重构50%+
| P11c 完成 | +14周 | 10+预置工具，6+行业模板，SDK发布 |

---

## ⚠️ 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 测试Mock配置复杂 | P11a延期 | 投入专人1-2天集中解决Mock问题 |
| pgvector性能不达预期 | P11b延期 | 备选Milvus，保持接口兼容 |
| RBAC设计复杂度 | P11b延期 | 先实现粗粒度权限，再细化 |
| 前端重构范围过大 | P11b延期 | 聚焦5个高频视图，其余延后 |

---

**计划创建时间：** 2026-06-04  
**负责人：** AI Assistant  
**审核状态：** 待审核
