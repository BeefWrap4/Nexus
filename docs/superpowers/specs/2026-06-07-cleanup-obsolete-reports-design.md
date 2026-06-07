# Cleanup Obsolete Improvement Reports

**Date:** 2026-06-07
**Author:** Claude (brainstorm session)
**Status:** Approved
**Scope:** Repository hygiene — move 5 untracked stage reports out of the repo root into an archive directory.

## Context

The NEXUS repo root contains 5 Markdown reports documenting historical
improvement phases (P0 / P1 / P2 / Architecture validation / Task 3):

| File | Lines |
|---|---|
| `P0_IMPROVEMENT_REPORT.md` | 271 |
| `P1_IMPROVEMENT_REPORT.md` | 366 |
| `P2_IMPROVEMENT_REPORT.md` | 213 |
| `P2_ARCHITECTURE_VALIDATION_REPORT.md` | 479 |
| `TASK3_EXECUTION_REPORT.md` | 253 |
| **Total** | **1582** |

`CLAUDE.md` explicitly states:

> 各种 P0/P1/P2 *IMPROVEMENT_REPORT.md / *EXECUTION_REPORT.md — 历史阶段报告，
> 新需求以代码 + README 为准。

These files are untracked in git (`git status` shows them as `??`); they have
never been committed. They clutter the repo root and create the false
impression of a current API surface for new contributors.

## Decision

Adopt **Option C** (move + index): preserve the historical content in a
dedicated archive, and provide a discoverable index that summarises each
report.

### Target Layout

```
nexus/
├── docs/
│   └── archive/
│       └── reports/
│           ├── INDEX.md                              (new)
│           └── 2026-q2/
│               ├── P0_IMPROVEMENT_REPORT.md          (moved)
│               ├── P1_IMPROVEMENT_REPORT.md          (moved)
│               ├── P2_IMPROVEMENT_REPORT.md          (moved)
│               ├── P2_ARCHITECTURE_VALIDATION_REPORT.md   (moved)
│               └── TASK3_EXECUTION_REPORT.md         (moved)
├── P0_IMPROVEMENT_REPORT.md           ← delete
├── P1_IMPROVEMENT_REPORT.md           ← delete
├── P2_IMPROVEMENT_REPORT.md           ← delete
├── P2_ARCHITECTURE_VALIDATION_REPORT.md   ← delete
└── TASK3_EXECUTION_REPORT.md          ← delete
```

### INDEX.md Skeleton

```markdown
# 历史改进报告归档

> CLAUDE.md 说明: "P0/P1/P2 *_IMPROVEMENT_REPORT.md / *_EXECUTION_REPORT.md —
> 历史阶段报告，新需求以代码 + README 为准。"

## 2026 Q2

| 报告 | 行数 | 一句话摘要 |
|---|---|---|
| [P0_IMPROVEMENT_REPORT](2026-q2/P0_IMPROVEMENT_REPORT.md) | 271 | P0 阶段安全 / 性能 / 文档基础修复 |
| [P1_IMPROVEMENT_REPORT](2026-q2/P1_IMPROVEMENT_REPORT.md) | 366 | P1 阶段功能完成 + 监控告警 |
| [P2_IMPROVEMENT_REPORT](2026-q2/P2_IMPROVEMENT_REPORT.md) | 213 | P2 阶段 RLS / Redis Sentinel / JWT 轮换 |
| [P2_ARCHITECTURE_VALIDATION](2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md) | 479 | P2 阶段架构验证 (DAG / EventBus / DLQ) |
| [TASK3_EXECUTION_REPORT](2026-q2/TASK3_EXECUTION_REPORT.md) | 253 | Task 3 安全相关任务执行 |
```

(One-line summaries to be filled in by reading the first paragraph of each
report at implementation time — placeholder values shown for shape.)

## Alternatives Considered

| Option | Verdict | Why |
|---|---|---|
| A. Hard delete | Rejected | Loses historical context; outside readers can't find reasoning for past architectural decisions. |
| B. Move without INDEX | Considered | Acceptable, but reduces discoverability. The reports are too obscure to find via casual browsing. |
| **C. Move + INDEX.md** | **Chosen** | Best discoverability-to-noise ratio. INDEX is 1 file, ~20 lines. |

## Risks

- **Negligible** — all 5 files are untracked; move + delete is fully reversible
  via `git fsck --lost-found` only if we had committed them, which we never
  did. The archive lives entirely in the working tree.
- No runtime impact — these are documentation only.
- No test impact — no test references these paths.

## Success Criteria

1. Repo root has zero `*_IMPROVEMENT_REPORT.md` / `*_EXECUTION_REPORT.md` files
2. `docs/archive/reports/2026-q2/` contains all 5 files unchanged
3. `docs/archive/reports/INDEX.md` exists with 5 entries
4. Single commit: `chore(repo): archive 5 obsolete stage reports to docs/archive/`
5. `git status` after the move: no `?? P*_IMPROVEMENT_REPORT.md`,
   no `?? TASK3_EXECUTION_REPORT.md`

## Out of Scope

- Deleting `../.env.bak.1780671766` (security cleanup — separate task)
- Migrating other untracked files in `..` (parent directory, not our concern)
- Backfilling summaries into INDEX beyond 1 line per report
- Restructuring `docs/` beyond adding `archive/`
