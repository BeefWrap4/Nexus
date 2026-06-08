fix: Sprint 1 production-readiness P0 blockers

Critical security and engine fixes from multi-expert production-readiness review.

[EM-2] Bootstrap fix
- nexus-ui/Dockerfile: 1-char fix (localhost → 127.0.0.1) for wget healthcheck.
  Root cause of FailingStreak=84 (wget resolved localhost to IPv6 ::1, nginx
  listened on IPv4 only). After rebuild: FailingStreak=0, container healthy.
- scripts/deploy.sh: harden load_env() to skip <...> placeholders via python
  pre-parser. Previously the script aborted in strict mode when .env contained
  template placeholders like DEV_API_KEY=<LEAVE_BLANK_...> because bash parsed
  < as stdin redirection.
- .env: replaced 5 unfilled <...> placeholders (DEV_API_KEY, LITELLM_MASTER_KEY,
  OPENAI/ANTHROPIC/DASHSCOPE_API_KEY) with real values. Original backed up to
  .env.bak.<timestamp>. NOTE: DEEPSEEK_API_KEY and SILICONFLOW_API_KEY still
  contain leaked values that must be rotated in provider consoles (EM-1, manual).

[S1-1] WorkflowEngine.resume() actually re-executes
- nexus/engine/workflow_engine.py:
  - execute() now reuses existing state via get_state() before create_state().
    Resume case: state is pre-populated, fresh case: state is created.
  - resume() now loads checkpoint, injects human_input, sets state on
    StateManager, and calls execute() — fixing the bug where pause→resume
    would hang because resume() only set status without re-invoking execute().
  - New import: CheckpointNotFoundException for the no-checkpoint case.
- nexus/jobs/workflow.py: new resume_workflow_job that loads Workflow + Run
  from DB, builds engine, calls engine.resume(). This is what the ARQ worker
  picks up after API endpoint enqueues it.
- nexus/jobs/config.py: registered resume_workflow_job in WorkerSettings.
- nexus/api/routes/runs.py: POST /api/v1/runs/{run_id}/resume now enqueues
  the resume_workflow_job into ARQ (was previously a no-op status update).
  503 returned if ARQ pool is unavailable or enqueue fails.

[S1-4] JWT_SECRET_KEY production gate
- nexus/api/main.py: _validate_production_security() now also calls
  settings.validate_jwt_secret_key() — same fatal RuntimeError on dev default.
  Previously the dev JWT key could be shipped to production undetected.

[S1-7] JWT rate limiter uses Redis when available
- nexus/security/auth.py: JWT path of get_current_user now uses RateLimiter
  (Redis sliding window) when redis_client is in app.state, falls back to
  existing in-memory dict otherwise. The 200/60s limit is preserved; only
  the backing store improves (per-replica → cluster-wide).

[S1-8] RBAC resources
- nexus/security/rbac.py: added "dashboard" to KNOWN_RESOURCES. Other
  resources (prompts, evals, code-review, traces, mcp, auto) were already
  present from a previous session.

Verification
- pytest tests/test_workflow_engine.py: 32/32 passed.
- pytest tests/test_auth_edge_cases.py: 25/26 passed (1 pre-existing mock
  bug in test_dev_api_key_in_production_rejected, unrelated to this PR).
- Manual: _validate_production_security() correctly rejects
  JWT_SECRET_KEY="nexus-jwt-dev-secret-not-for-production" in production env
  with the new error message.
- Manual: deploy.sh --help runs cleanly (no bash syntax error from .env).
- Manual: nexus-ui container rebuilt, healthcheck passing (FailingStreak=0).
- Manual: docker compose restart api worker — new code live, /health 200.

Known follow-ups (not in this PR)
- EM-1: rotate DEEPSEEK and SILICONFLOW keys in provider consoles.
- S1-2: real Redis sentinel client (currently hardcoded redis-master).
- S1-3: PostgreSQL Row-Level Security (currently no policy DDL exists).
- S2-*: Prometheus exporter coverage, real worker metrics server.
- S3-*: 15 known-failing tests in test_workflow_engine_edge_cases.py.

Refs: docs/superpowers/plans/2026-06-05-production-readiness-plan-v2.md
