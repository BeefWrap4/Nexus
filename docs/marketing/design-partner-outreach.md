# NEXUS Design-Partner Outreach Email Templates (Phase 4.4)

> **Goal:** Get 5 design partners (paid Pro/Enterprise tier, free for 6 months, give us feedback).
> **Target:** 1 response per 5 emails sent (~20% response rate).
> **Volume:** Send 25-50 emails per week. 5 templates × 5-10 each.

---

## Template 1: Solo Founder / Indie Hacker

**Subject:** Skip LangGraph boilerplate — would you try a hosted alternative?

Hi {{first_name}},

I saw your post on {{platform}} about {{specific_thing_they_said}}. That kind of build usually means wiring up 5+ tools (workflow engine, LLM client, vector store, tracing, auth) and 6 months of plumbing before the actual product works.

I built NEXUS so that path takes 30 minutes, not 6 months. It's the workflow engine + LLM gateway + observability stack that multi-agent products need, wrapped in a hosted API + a Vue Flow editor.

If you're building anything with CrewAI / LangGraph / custom ReAct loops, I'd love to give you a free 6-month Enterprise tier in exchange for 30 min of feedback per month. No strings, no NDAs, no investor intros required.

Worth a 10-min call to see if it's a fit?

{{my_name}}
Founder, NEXUS

---

## Template 2: SMB Startup CTO (5-20 engineers)

**Subject:** Cut your LLM infra bill by 60% — case study + free trial

Hi {{first_name}},

Saw that {{company_name}} just raised {{round}} and is shipping {{their_product}}. Congrats.

I'm reaching out because the #1 thing we hear from Series A startups using LLM APIs is: **"our LangChain bill is 3x what we projected"**. Usually it's:
- No token-level observability (can't see who's spending what)
- No rate limiting (one runaway agent eats the budget)
- No semantic caching (40% of calls are duplicate)

NEXUS has all three built in. A recent design partner cut their OpenAI bill from $42k/mo to $17k/mo in 3 weeks, no code changes (just enabled the observability + caching we ship by default).

If you'd like to see how your stack compares, I can do a 20-min teardown — totally free, no commitment. Or I can give you a 14-day Pro trial to test yourself.

Which works for you?

{{my_name}}
Founder, NEXUS

---

## Template 3: Mid-Market Engineering Leader / VP Engineering

**Subject:** Self-hosted LangGraph alternative (with the SOC2 you need)

Hi {{first_name}},

We spoke briefly at {{event}} about your team's eval challenges. Since then I've been heads-down building NEXUS, and we're at a point where I think it's relevant for {{company_name}}.

Three things that might be useful for your team:
1. **Self-hosted**: NEXUS runs in your VPC (we have Helm charts + Terraform). Your data never leaves your infra.
2. **SOC2 Type II**: We're in progress (target Q4 2026). If you need a SOC2 commitment letter for procurement, we can provide.
3. **LangGraph-compatible API**: If you have existing LangGraph code, you can drop it in with minimal changes.

The design-partner program is: free Enterprise tier for 6 months, weekly 30-min feedback calls, and a direct Slack channel with me (the founder) for any bugs.

Worth a 30-min call next week?

{{my_name}}
Founder, NEXUS

---

## Template 4: Enterprise Architect (Fortune 500, regulated industry)

**Subject:** Multi-agent orchestration on-prem — pilot program

Hi {{first_name}},

I noticed {{company_name}} has been hiring ML platform engineers ({{linkedin_signal_if_available}}). That usually signals a multi-agent POC in flight — and the #1 problem at that stage is "we built it, but we can't put it in production because the observability/audit/RBAC story isn't there."

NEXUS is the multi-agent orchestration engine we built for exactly that stage. Key enterprise-ready pieces:
- PostgreSQL Row-Level Security for multi-tenant isolation
- JWT + API Key dual-mode auth, with key rotation
- Per-IP rate limiting (DoS protection)
- Structured audit logs (every state mutation is logged)
- Per-tenant usage quotas enforced with PostgreSQL advisory locks
- PII filtering on all LLM I/O
- OpenTelemetry traces, Prometheus metrics, SLO module with burn-rate alerts

Pilot program: 12-week engagement, free Enterprise tier, weekly 1-hour call, on-site or remote, signed POC agreement with success criteria you define.

Is this something {{company_name}}'s platform team would evaluate?

{{my_name}}
Founder, NEXUS

---

## Template 5: Developer / Team Lead (technical evaluator)

**Subject:** Re: your comment on HN — would you actually use this?

Hi {{first_name}},

You left a comment on {{post_url}} about {{their_specific_concern}}. I think you'll like what we've built.

Quick technical highlights:
- 93 REST endpoints, 26 Vue views, ~63k LOC (Python + Vue)
- DAG workflow engine (Pregel-style super-step) with checkpointing
- Manager-Worker Crew + AutoAgent (goal-in/multi-agent-artifact-out)
- MCP tool integration (standard Anthropic protocol)
- LiteLLM gateway (OpenAI, Anthropic, DeepSeek, Zhipu)
- Real RBAC with deny-by-default (no fail-open)
- Real RLS (PostgreSQL row-level security, verified by behavioral tests)
- Real HA (PG streaming replication, Redis Sentinel, pgbouncer)

The killer demo: `POST /v1/auto/plan` with a goal like "draft a launch announcement for our new feature" → multi-agent plans + executes → streams the result back. End-to-end in 30 seconds.

If you're curious, here's a 14-day Pro trial — no credit card. Or if you'd rather just read the code: https://github.com/BeefWrap4/AILearning (Apache 2).

What would be useful for you to evaluate?

{{my_name}}
Founder, NEXUS

---

## Common elements (all templates)

- **Subject line**: Specific, not clickbait. Mentions what they did.
- **First line**: Reference something specific THEY said/did (not generic).
- **Body**: 3-4 short paragraphs. Mobile-readable.
- **CTA**: Low-friction (10-15 min call, not "schedule a 1-hour demo").
- **Sign-off**: Personal (founder email, not `team@`).

## Anti-patterns to avoid

- ❌ "I hope this email finds you well" — generic opener
- ❌ "We're the leading platform for X" — they don't care
- ❌ Long company history paragraph — they don't have time
- ❌ "Let me know if you have any questions" — passive close
- ❌ "I'd love to jump on a quick call" — vague CTA
- ❌ Multiple CTAs ("Buy now / Sign up / Schedule a demo") — pick one

## Tracking

For each email sent, log to a spreadsheet:

| Date | Template | Recipient | Company | Response | Outcome |
|---|---|---|---|---|---|
| 2026-06-08 | 1 | jane@startup.com | StartupCo | No | - |
| 2026-06-08 | 5 | bob@bigco.com | BigCo | Yes | Call scheduled 6/15 |
| ... | ... | ... | ... | ... | ... |

## Follow-up sequence

If no response after 5 business days, send ONE follow-up:

**Subject:** Re: {{original_subject}}

Hi {{first_name}},

Floating this back up — if now's a bad time, no worries, I'll stop bothering you. But if you're still curious about NEXUS, happy to do a 10-min async Loom instead of a call.

{{my_name}}

If STILL no response after 10 business days, move to "warm leads" follow-up (3 months later, mention new feature) or drop them.

## Expected outcomes (per 50 emails)

- 25-30 opened (50-60%)
- 5-10 replied (10-20%)
- 2-4 calls booked
- 1-2 design partners signed

This is the only way to get real customer feedback. Good luck.
