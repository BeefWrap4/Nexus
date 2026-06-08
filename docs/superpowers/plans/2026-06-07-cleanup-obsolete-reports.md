# Archive Obsolete Stage Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move 5 untracked historical improvement reports from the repo root into `docs/archive/reports/2026-q2/` with a discoverable INDEX.md.

**Architecture:** Pure file-system operation (mv + write new file). No code changes. No test changes. Single commit captures the entire move.

**Tech Stack:** Git, bash, Markdown

---

## File Structure

**Files moved (5):**
- `P0_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P0_IMPROVEMENT_REPORT.md`
- `P1_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P1_IMPROVEMENT_REPORT.md`
- `P2_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P2_IMPROVEMENT_REPORT.md`
- `P2_ARCHITECTURE_VALIDATION_REPORT.md` → `docs/archive/reports/2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md`
- `TASK3_EXECUTION_REPORT.md` → `docs/archive/reports/2026-q2/TASK3_EXECUTION_REPORT.md`

**Files created (1):**
- `docs/archive/reports/INDEX.md` — discoverability index for the archive

**Files modified:** None.

---

## Task 1: Move 5 files into archive directory

**Files:**
- Move: `P0_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P0_IMPROVEMENT_REPORT.md`
- Move: `P1_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P1_IMPROVEMENT_REPORT.md`
- Move: `P2_IMPROVEMENT_REPORT.md` → `docs/archive/reports/2026-q2/P2_IMPROVEMENT_REPORT.md`
- Move: `P2_ARCHITECTURE_VALIDATION_REPORT.md` → `docs/archive/reports/2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md`
- Move: `TASK3_EXECUTION_REPORT.md` → `docs/archive/reports/2026-q2/TASK3_EXECUTION_REPORT.md`

- [ ] **Step 1: Verify all 5 source files exist in repo root**

Run from repo root `D:/AI_learning/nexus/`:
```bash
ls -1 P0_IMPROVEMENT_REPORT.md P1_IMPROVEMENT_REPORT.md P2_IMPROVEMENT_REPORT.md P2_ARCHITECTURE_VALIDATION_REPORT.md TASK3_EXECUTION_REPORT.md
```

Expected: 5 lines, one per filename.

- [ ] **Step 2: Create archive subdirectory**

```bash
mkdir -p docs/archive/reports/2026-q2
```

Expected: no output, exit 0.

- [ ] **Step 3: Move the 5 files**

```bash
git mv P0_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/P0_IMPROVEMENT_REPORT.md
git mv P1_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/P1_IMPROVEMENT_REPORT.md
git mv P2_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/P2_IMPROVEMENT_REPORT.md
git mv P2_ARCHITECTURE_VALIDATION_REPORT.md docs/archive/reports/2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md
git mv TASK3_EXECUTION_REPORT.md           docs/archive/reports/2026-q2/TASK3_EXECUTION_REPORT.md
```

Expected: 5 lines, each `Renaming: ...`. Exit 0.

> **Why `git mv` even though the files are untracked?**
> Per `git status` the files are `??` (untracked). `git mv` works on untracked
> files too in recent Git versions, but the safer Windows-friendly fallback
> is plain `mv`. If `git mv` errors with "not under version control", fall
> back to:
> ```bash
> mv P0_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/
> mv P1_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/
> mv P2_IMPROVEMENT_REPORT.md            docs/archive/reports/2026-q2/
> mv P2_ARCHITECTURE_VALIDATION_REPORT.md docs/archive/reports/2026-q2/
> mv TASK3_EXECUTION_REPORT.md           docs/archive/reports/2026-q2/
> ```

- [ ] **Step 4: Verify move succeeded**

```bash
ls -1 docs/archive/reports/2026-q2/
```

Expected: 5 filenames (the same 5).

```bash
ls P*_IMPROVEMENT_REPORT.md P2_ARCHITECTURE_VALIDATION_REPORT.md TASK3_EXECUTION_REPORT.md 2>&1
```

Expected: `ls: cannot access ...: No such file or directory` — repo root is clean.

- [ ] **Step 5: Commit the move (do NOT amend — keep move separate from INDEX creation)**

```bash
git add -A docs/archive/reports/2026-q2/
git status --short
```

Expected: 5 `A` lines, one per moved file. (Plain `mv` will show as `??` initially; that's fine for the commit — `git add` stages the new path.)

```bash
git commit -m "chore(repo): archive 5 obsolete stage reports to docs/archive/reports/2026-q2/

Moves (all untracked previously):
- P0_IMPROVEMENT_REPORT.md (271 lines)
- P1_IMPROVEMENT_REPORT.md (366 lines)
- P2_IMPROVEMENT_REPORT.md (213 lines)
- P2_ARCHITECTURE_VALIDATION_REPORT.md (479 lines)
- TASK3_EXECUTION_REPORT.md (253 lines)

Per CLAUDE.md: these are historical stage reports, no longer maintained
as canonical docs. INDEX.md (next commit) provides discoverability."
```

Expected: `[main <hash>] chore(repo): archive ...` with 5 files changed.

---

## Task 2: Create INDEX.md

**Files:**
- Create: `docs/archive/reports/INDEX.md`

- [ ] **Step 1: Extract first-paragraph summary from each report for INDEX.md table**

For each of the 5 files in `docs/archive/reports/2026-q2/`, read the first
heading + first paragraph (~3-5 lines after `#` or first `##`). Use those
to fill the "一句话摘要" column. (We extract these manually rather than
running a script — 5 files, eyeballing is faster.)

The required output is 5 one-line summaries. Use these if you cannot read
the source:

| File | One-line summary (fallback) |
|---|---|
| P0_IMPROVEMENT_REPORT.md | P0 阶段 — 基础安全 / 性能 / 文档修复 (JWT / Rate Limit / Prometheus) |
| P1_IMPROVEMENT_REPORT.md | P1 阶段 — 监控告警 + 备份 DR + MinIO 集成 |
| P2_IMPROVEMENT_REPORT.md | P2 阶段 — RLS 多租户 / Redis Sentinel / JWT 密钥轮换 |
| P2_ARCHITECTURE_VALIDATION_REPORT.md | P2 阶段架构验证 — DAG super-step / EventBus / DLQ 行为审计 |
| TASK3_EXECUTION_REPORT.md | Task 3 安全 — pre-commit 密钥扫描 + `.env` 轮换 + 历史清理 |

- [ ] **Step 2: Write INDEX.md**

Create `docs/archive/reports/INDEX.md` with this exact content
(replace fallback summaries with real first-paragraph extracts from Step 1
if you read them):

```markdown
# 历史改进报告归档

> **说明:** `CLAUDE.md` 明确：各种 P0/P1/P2 `*_IMPROVEMENT_REPORT.md` /
> `*_EXECUTION_REPORT.md` 为历史阶段报告，新需求以代码 + README 为准。
>
> 当前活跃文档：`README.md`、`docs/` 子目录、`nexus/api/routes/` 路由 docstring
> (FastAPI 自动生成到 `/docs` Swagger UI)。

## 2026 Q2

| 报告 | 行数 | 一句话摘要 |
|---|---|---|
| [P0_IMPROVEMENT_REPORT](2026-q2/P0_IMPROVEMENT_REPORT.md) | 271 | P0 阶段 — 基础安全 / 性能 / 文档修复 (JWT / Rate Limit / Prometheus) |
| [P1_IMPROVEMENT_REPORT](2026-q2/P1_IMPROVEMENT_REPORT.md) | 366 | P1 阶段 — 监控告警 + 备份 DR + MinIO 集成 |
| [P2_IMPROVEMENT_REPORT](2026-q2/P2_IMPROVEMENT_REPORT.md) | 213 | P2 阶段 — RLS 多租户 / Redis Sentinel / JWT 密钥轮换 |
| [P2_ARCHITECTURE_VALIDATION](2026-q2/P2_ARCHITECTURE_VALIDATION_REPORT.md) | 479 | P2 阶段架构验证 — DAG super-step / EventBus / DLQ 行为审计 |
| [TASK3_EXECUTION_REPORT](2026-q2/TASK3_EXECUTION_REPORT.md) | 253 | Task 3 安全 — pre-commit 密钥扫描 + `.env` 轮换 + 历史清理 |

## 命名约定

- `P0_*` → 0 阶段 (基础稳定性)
- `P1_*` → 1 阶段 (可观测性 + 灾备)
- `P2_*` → 2 阶段 (生产级加固：多租户 / 高可用 / 密钥治理)
- `TASK3_*` → Task 3 安全专项

## 查阅指南

- 想知道"现在代码里有什么" → `README.md` / `CLAUDE.md` / `docs/` 子目录
- 想知道"过去为什么这样设计" → 本目录的归档报告
- 想知道"API 怎么调" → `http://localhost:8765/docs` (Swagger UI)
```

- [ ] **Step 3: Verify INDEX.md exists and looks right**

```bash
ls -1 docs/archive/reports/INDEX.md
wc -l docs/archive/reports/INDEX.md
head -5 docs/archive/reports/INDEX.md
```

Expected: 3 commands all succeed. `wc -l` reports ~30 lines. First 5 lines
start with `# 历史改进报告归档`.

- [ ] **Step 4: Commit INDEX.md**

```bash
git add docs/archive/reports/INDEX.md
git status --short
```

Expected: single `A  docs/archive/reports/INDEX.md` line.

```bash
git commit -m "docs(archive): add INDEX.md for historical stage reports

Lists 5 archived reports under docs/archive/reports/2026-q2/ with
one-line summaries and line counts. Points readers to README.md /
CLAUDE.md / Swagger UI for current canonical docs."
```

Expected: `[main <hash>] docs(archive): add INDEX.md ...` with 1 file changed.

---

## Task 3: Final verification

- [ ] **Step 1: Confirm repo root is clean of the 5 reports**

```bash
ls P*_IMPROVEMENT_REPORT.md P2_ARCHITECTURE_VALIDATION_REPORT.md TASK3_EXECUTION_REPORT.md 2>&1
```

Expected: `ls: cannot access ...: No such file or directory` — all 5 are gone from the root.

- [ ] **Step 2: Confirm archive directory has all 5 + INDEX.md**

```bash
ls -1 docs/archive/reports/ docs/archive/reports/2026-q2/
```

Expected:
- `docs/archive/reports/` shows `INDEX.md` and `2026-q2/`
- `docs/archive/reports/2026-q2/` shows the 5 report files

- [ ] **Step 3: Confirm git log shows 2 new commits**

```bash
git log --oneline -5
```

Expected: top 2 commits are the ones from Task 1 and Task 2 above.

- [ ] **Step 4: Confirm no untracked `*_IMPROVEMENT_REPORT.md` / `*_EXECUTION_REPORT.md` remain**

```bash
git status --short | grep -E "IMPROVEMENT_REPORT|EXECUTION_REPORT" || echo "CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 5: Push to origin**

```bash
git push
```

Expected: `2 commits pushed`. (If `git push` fails with `Recv failure`
or similar transient network error, retry once.)

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - 5 files moved? → Task 1 Steps 3-4
  - INDEX.md created? → Task 2 Step 2
  - Single commit per phase? → Task 1 Step 5, Task 2 Step 4
  - Success criteria (root clean, archive populated, INDEX has 5 entries)? → Task 3 Steps 1-2

- [x] **Placeholder scan:** No "TBD" / "TODO" in steps. INDEX.md content is fully specified (with fallback summaries).

- [x] **Type / name consistency:** File names match spec exactly. No function/type names (no code changed).

- [x] **Bite-sized steps:** Each step is a single action (2-5 minutes). File ops, git ops, or read/write.

- [x] **Test coverage:** N/A — pure file operation. Spec says "no tests needed".

- [x] **Frequent commits:** 2 commits (move batch, then INDEX) plus optional push. Matches "frequent commits" principle.
