# NEXUS 30-Day Onboarding Playbook (Phase 4.3)

> **Audience:** New customers who just signed up.
> **Goal:** From signup → first production workflow in 30 days, with weekly checkpoints.
> **Owner:** Customer Success team + the customer's named technical contact.

---

## Week 1: Foundations (Day 1-7)

### Day 1: Sign up + first 5 minutes

- [ ] **Account creation**: Sign up at https://nexus.example.com/signup
- [ ] **Email verification**: Click the link in the verification email
- [ ] **Pick a plan**: Choose Free (14-day Pro trial) or Pro ($49/mo)
- [ ] **Add payment method**: Even for the trial, add a card (Stripe test mode: `4242 4242 4242 4242`)
- [ ] **Invite team members**: At least 1 admin + 2 regular members
- [ ] **Confirm** you've seen the dashboard and `/api/v1/billing/usage` page

**Success criteria**: You can log in, see your dashboard, and the billing page shows your plan.

### Day 2-3: API key + first workflow

- [ ] **Generate API key**: Settings → API Keys → "Generate new key"
- [ ] **Store the key securely** (1Password / Vault, NEVER in git)
- [ ] **Make your first API call** (curl + your key):
  ```bash
  curl https://api.nexus.example.com/v1/auth/me -H "X-API-Key: nx_..."
  ```
- [ ] **Create your first workflow** via the UI (WorkflowEditor.vue)
  - Add 3 nodes: START → LLM (gpt-4o-mini) → END
  - Connect them
  - Save and run

**Success criteria**: Workflow runs end-to-end and emits a result.

### Day 4-5: Connect your real LLM provider

- [ ] **OpenAI**: Add `OPENAI_API_KEY` in Settings → LLM Providers
- [ ] **Anthropic** (optional): Add `ANTHROPIC_API_KEY` for Claude access
- [ ] **Set fallback chain**: Settings → LLM → Default fallback: gpt-4o-mini → gpt-3.5-turbo
- [ ] **Test**: Re-run your workflow, verify it uses the right model (check `/v1/llm/traces`)

**Success criteria**: Workflow uses your real API key (not the dev fallback).

### Day 6-7: First multi-agent workflow

- [ ] **Create a 2-agent Crew** (Crews → New Crew)
  - Agent 1: "Researcher" (role: research, tools: web_search)
  - Agent 2: "Writer" (role: write, depends on Agent 1's output)
  - Mode: SEQUENTIAL
- [ ] **Run the crew** with a real task (e.g., "Write a 200-word summary of X")
- [ ] **Review the output** and rate the Crew (thumbs up/down)

**Success criteria**: A 2-agent crew runs and produces output you can use.

---

## Week 2: First production-ish workload (Day 8-14)

### Day 8-10: Connect a real data source

- [ ] **Pick a data source**: One of:
  - Webhook (Stripe events, GitHub events, etc.)
  - Database (Postgres connection string)
  - S3 bucket (read CSVs, JSON, etc.)
  - HTTP API (your existing internal service)
- [ ] **Configure in NEXUS**: Tools → Add Tool → Pick the source
- [ ] **Build a workflow**: Fetch data → LLM process → Store result
- [ ] **Run 10 times** to check stability

**Success criteria**: Workflow reliably processes real data from your source.

### Day 11-12: Add observability

- [ ] **Check `/v1/llm/traces`**: Latency, token usage, model, error rate
- [ ] **Set up Slack webhook** for failure alerts (Tools → Slack)
- [ ] **Configure budget alerts**: Settings → Billing → Set "warn at 80%, hard at 100%"

**Success criteria**: You get a Slack notification when something breaks.

### Day 13-14: First HITL (Human-in-the-Loop) workflow

- [ ] **Add a HITL node** to your workflow (decision point)
- [ ] **Configure the approval UI** (HITL Tasks view)
- [ ] **Run the workflow** end-to-end (your task, LLM does work, you approve)
- [ ] **Measure**: How long does the human review take? Is the LLM output high enough quality?

**Success criteria**: A workflow where a human approves an LLM-generated artifact.

---

## Week 3: Production hardening (Day 15-21)

### Day 15-16: Auth + RBAC

- [ ] **Create roles** for your team (admin, member, viewer)
- [ ] **Set per-resource permissions** (who can run which workflows)
- [ ] **Test** with a non-admin account: can they run but not delete?

**Success criteria**: RBAC enforced, non-admin can't see admin-only workflows.

### Day 17-18: Monitoring + alerts

- [ ] **Connect Prometheus** (we expose `/metrics` in OpenMetrics format)
- [ ] **Set up Grafana dashboard** (JSON in `docs/grafana/`)
- [ ] **Configure SLO alerts** (99% availability, 1s p99 latency)
- [ ] **On-call rotation** (if your team is >5 people)

**Success criteria**: You have a dashboard showing 4 golden signals + alerts.

### Day 19-21: Backup + DR drill

- [ ] **Confirm automated backups** are running (Settings → Backups)
- [ ] **Test restore**: Pick a recent backup, restore to a sandbox tenant
- [ ] **Document your RTO/RPO** expectations

**Success criteria**: You can restore a workflow run from yesterday in <30 minutes.

---

## Week 4: Scale + ship (Day 22-30)

### Day 22-24: Load test

- [ ] **Locust** (we have a `benchmarks/` directory)
- [ ] **Run 100 concurrent users** for 10 minutes
- [ ] **Identify the bottleneck** (DB? LLM upstream? API rate limits?)
- [ ] **Plan for scale**: Upgrade plan / add caching / batch jobs

**Success criteria**: System handles 100 concurrent users with <1s p99 latency.

### Day 25-27: First customer-facing use

- [ ] **Embed NEXUS in your product** (API integration OR webhook OR scheduled workflow)
- [ ] **Add the workflow to your CI/CD** (run nightly via ARQ cron)
- [ ] **Monitor the first 7 days** of production usage

**Success criteria**: Real end-users are using the workflow you built.

### Day 28-30: Optimize + expand

- [ ] **Review token spend** (Settings → Billing → Usage dashboard)
- [ ] **Tune prompts** to reduce tokens/call (30-50% reduction is common)
- [ ] **Add 1-2 more workflows** (now you know the patterns)
- [ ] **Write your team's runbook** (or use ours as a template)

**Success criteria**: 3+ production workflows, <$200/mo token spend, on-call calm.

---

## 30-day scorecard (success metrics)

| Metric | Target | Actual |
|---|---|---|
| Workflows in production | 3+ | ___ |
| Daily API calls | 1000+ | ___ |
| Uptime | 99%+ | ___ |
| p99 latency | <1s | ___ |
| Monthly token spend | <$200 (Pro) | ___ |
| Team members using NEXUS | 3+ | ___ |
| Workflows with HITL | 1+ | ___ |
| Workflows that ran >100 times | 1+ | ___ |

---

## Common pitfalls (we've seen)

1. **Hardcoding the API key in code**: Use env vars / secrets manager
2. **Not setting up a fallback LLM**: One provider outage kills your workflow
3. **Skipping HITL for "obviously safe" tasks**: LLMs are confidently wrong ~5% of the time
4. **Not reading token usage**: First invoice is sometimes 5x expected
5. **Skipping backups**: You WILL need them. Day 1.
6. **Not inviting your team**: Solo admin means single point of failure

---

## When to call us (CS team)

| Issue | Action |
|---|---|
| Stuck > 1 hour on one step | Open a chat — we're online M-F 9-5 PT |
| Outage or data loss | Email `urgent@nexus.example.com` (24/7) |
| Feature request | Post in Discord or open a GitHub issue |
| Security disclosure | Email `security@nexus.example.com` (PGP key on our site) |
| Billing dispute | Email `billing@nexus.example.com` (reply within 1 business day) |

---

## What's next (after 30 days)

- **Day 31-60**: Build 2-3 more workflows, get team fully onboarded
- **Day 61-90**: Add MCP tool integrations, explore the Agent / AutoAgent features
- **Day 90+**: Consider Enterprise plan if you need SSO, audit logs, custom SLA

Welcome to NEXUS! 🚀
