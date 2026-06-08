# NEXUS Getting-Started Video Script (Phase 4.6)

> **Title:** "Build a multi-agent workflow in 2 minutes"
> **Length:** 120 seconds (2:00)
> **Format:** Screen recording with voiceover + on-screen captions
> **Goal:** Viewer can replicate the demo after watching

---

## Storyboard

### 0:00 - 0:10 — Hook (problem statement)

**On screen:** Bold text "Multi-agent AI is too hard" + scrolling list of failed tools

**Voiceover:**
> "Building a multi-agent AI workflow shouldn't take 6 months of infrastructure work. But if you've used LangGraph, CrewAI, or rolled your own, you know it usually does."

---

### 0:10 - 0:20 — Setup (3 commands)

**On screen:** Terminal recording

**Voiceover:**
> "With NEXUS, you can have a production-grade multi-agent system running in three commands."

**Commands shown:**
```bash
docker compose up -d
# wait for healthy
curl http://localhost:8765/health
```

**On screen:** Green "ok" response

---

### 0:20 - 0:40 — Open the editor (20s)

**On screen:** Browser opens http://localhost/login → Login.vue → Dashboard

**Voiceover:**
> "Log in. The dashboard shows your workflows, runs, and usage. To build a new workflow, click the 'New Workflow' button."

**On screen:** Click "New Workflow" → WorkflowEditor.vue opens with a blank canvas

**Voiceover:**
> "This is the Vue Flow editor. Drag nodes from the left palette onto the canvas. Connect them. Configure each one. That's it — no YAML, no DSL, no custom framework to learn."

---

### 0:40 - 1:00 — Build a 2-agent crew (20s)

**On screen:** Drag 4 nodes: START → AGENT 1 (Researcher) → AGENT 2 (Writer) → END. Connect them.

**Voiceover:**
> "Let's build a 2-agent crew. Agent 1 is a Researcher — give it a role, a goal, and some tools. Agent 2 is a Writer — it takes Agent 1's output and writes a summary."

**On screen:** Configure Agent 1:
- Role: research
- Goal: Find the latest AI news
- Tools: web_search

Configure Agent 2:
- Role: write
- Goal: Write a 200-word summary
- Model: gpt-4o-mini

---

### 1:00 - 1:20 — Run it (20s)

**On screen:** Click "Run" → modal opens with progress

**Voiceover:**
> "Hit run. NEXUS streams the execution in real time. You can see which agent is working, what tools it's calling, and what tokens it's spending. When it's done, you get the result inline."

**On screen:** Run completes in 23 seconds. Output: "AI in 2026: [200-word summary]". Token usage: 1,243. Cost: $0.004.

---

### 1:20 - 1:40 — The killer feature (20s)

**On screen:** Close the modal. Open a new "AutoAgent" tab.

**Voiceover:**
> "And if you don't want to design the workflow yourself, just describe the goal. NEXUS's AutoAgent plans the multi-agent execution for you."

**On screen:** Type: "Write a launch announcement for our new feature 'Multi-Agent Builder'"

**Voiceover:**
> "It plans the workflow, picks the right agents, runs them, and gives you the result. End-to-end in 30 seconds."

**On screen:** Click submit → AutoAgent runs → produces "Introducing Multi-Agent Builder: [markdown draft]"

---

### 1:40 - 1:55 — What you got (15s)

**On screen:** Show the result inline. Highlight 3 things in the dashboard:
- Workflows: 1
- Runs today: 1
- Token usage: 2,847

**Voiceover:**
> "That's it. You have a working multi-agent system, with real observability, in 2 minutes. Try it yourself — free 14-day Pro trial, no credit card."

---

### 1:55 - 2:00 — CTA (5s)

**On screen:** URL: nexus.example.com + Discord invite

**Voiceover:**
> "nexus.example.com. Discord link in the description. See you there."

---

## Production notes

- **No music** (or very subtle background, optional)
- **Captions burned in** (most viewers watch muted)
- **Aspect ratio**: 16:9 (YouTube) and 9:16 (Shorts/TikTok cut)
- **Total budget**: 30 minutes of Loom + 1 hour of editing
- **Host**: founder (me) — authentic > polished for dev tools
- **CTA at end**: trial signup + Discord (not "subscribe", we're not a content channel)

## Repurposing plan

After the 2-min main video, cut into:

1. **30s teaser** for Twitter/LinkedIn: just the AutoAgent section (1:20 - 1:40)
2. **15s Shorts** for TikTok/Reels: the "drag a node, get an agent" clip
3. **GIF loop** for the docs site: the run-progress modal animation
4. **Screenshots** for the README hero image

Total repurposing time: 1-2 hours.

## Community setup (related)

- **Discord**: https://discord.gg/nexus (invite link in README + on this video)
- **GitHub Discussions**: enable on the repo (Settings → Features → Discussions)
- **#nexus-help** channel: free support, monitored 9-5 PT
- **#nexus-showcase**: users post their workflows, we feature the best weekly
- **Office hours**: every Thursday 4-5pm PT in Discord voice channel "Building-with-NEXUS"
