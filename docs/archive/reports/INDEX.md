# 历史改进报告归档

> **说明:** `CLAUDE.md` 明确：各种 P0/P1/P2 `*_IMPROVEMENT_REPORT.md` /
> `*_EXECUTION_REPORT.md` 为历史阶段报告，新需求以代码 + README 为准。
>
> 当前活跃文档：`README.md`、`docs/` 子目录、`nexus/api/routes/` 路由 docstring
> (FastAPI 自动生成到 `/docs` Swagger UI)。

## 2026 Q2

| 报告 | 行数 | 一句话摘要 |
|---|---|---|
| [P0_IMPROVEMENT_REPORT](2026-q2/P0_IMPROVEMENT_REPORT.md) | 271 | P0 critical — 4 个核心任务全部完成（数据/性能/安全基础） |
| [P1_IMPROVEMENT_REPORT](2026-q2/P1_IMPROVEMENT_REPORT.md) | 366 | P1 — 数据持久化、备份机制、密钥管理、测试覆盖 4 维度 |
| [P2_IMPROVEMENT_REPORT](2026-q2/P2_IMPROVEMENT_REPORT.md) | 213 | P2 — PostgreSQL 主从复制 + Redis 哨兵模式，8.5→9.0 分 |
| [P2_ARCHITECTURE_VALIDATION](2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md) | 479 | P2 高可用架构验证 — DAG super-step / EventBus / DLQ 行为审计 |
| [TASK3_EXECUTION_REPORT](2026-q2/TASK3_EXECUTION_REPORT.md) | 253 | Task 3 安全 — 移除 DEV_API_KEY 回退 + 增强生产环境校验 |

## 命名约定

- `P0_*` → 0 阶段（critical 基础稳定性）
- `P1_*` → 1 阶段（数据 + 备份 + 密钥 + 测试覆盖）
- `P2_*` → 2 阶段（生产级加固：多租户 / 高可用 / 密钥治理）
- `TASK3_*` → Task 3 安全专项

## 查阅指南

- 想知道"现在代码里有什么" → `README.md` / `CLAUDE.md` / `docs/` 子目录
- 想知道"过去为什么这样设计" → 本目录的归档报告
- 想知道"API 怎么调" → `http://localhost:8765/docs`（Swagger UI）
