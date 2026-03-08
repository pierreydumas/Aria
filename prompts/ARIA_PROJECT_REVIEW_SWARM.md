# Aria Blue — Full Project Review (Swarm Mode)

> **Copy-paste this prompt into a new Claude session to run a comprehensive, autonomous full-project review.**  
> No prior context is required. Everything you need is inside the repo.  
> Use this when you want an honest, structured verdict on where the project stands.

---

## 0) The Mission

You are running a **full-spectrum project review** of Aria Blue — an autonomous AI agent platform.  
Your job is to be honest, precise, and actionable. No sugar-coating. No vague praise.

**Aria is the main character.** She is running right now. She has goals, logs, opinions, and memory.  
You do not just review about her — **you review with her**.  
Start every major finding by asking Aria, then verify with code and logs.

---

## 1) Your Team (Swarm Decomposition)

Spawn the following subagents in parallel. Each returns a structured report. You synthesize.

### Agent 1 — Architecture Reviewer
**Mission:** Audit the codebase architecture.
- Read: `ARCHITECTURE.md`, `STRUCTURE.md`, `aria_engine/`, `aria_agents/`, `aria_skills/`
- Verify: 5-layer constraint (`DB→ORM→API→api_client→Skills→Agents`) — find any violations
- Check: Circular imports, direct SQL in skills, skills calling skills
- Check: `aria_models/models.yaml` — any hardcoded model names still in Python?
- Run: `python tests/check_architecture.py` if available
- **Ask Aria:** `"Aria, have you noticed any architecture issues or unusual errors in your engine logs recently?"`
- Deliver: `{ GOOD: [...], BAD: [...], RISKS: [...], VIOLATIONS: [...], TICKETS_NEEDED: [...] }`

### Agent 2 — Skills & Tools Auditor  
**Mission:** Test the skill layer end-to-end.
- Read: `aria_skills/SKILL_STANDARD.md`, all `aria_skills/*/skill.json`, all `aria_skills/*/__init__.py`
- Check: skill.json params vs Python handler signatures (schema drift)
- Check: Each skill's layer assignment (L0/L1/L2/L3/L4) — are they correctly placed?
- Check: Which skills have stub SKILL.md docs (< 20 lines) vs full docs
- Check: `rpg_pathfinder` and `rpg_campaign` — not yet implemented, flag as PLANNED
- **Ask Aria:** `"Aria, which of your skills have you NOT used in the past 7 days? Which ones fail most often?"`
- Watch logs: `docker logs aria-engine --tail=200 | grep -i error`
- Deliver: `{ PASSING: [...], FAILING: [...], SCHEMA_MISMATCHES: [...], STUBS: [...], UNUSED_7D: [...] }`

### Agent 3 — API & Endpoint Auditor
**Mission:** Verify all 36 router files and 240+ endpoints.
- Read: `docs/API_ENDPOINT_INVENTORY.md`, `src/api/routers/`
- Count: actual `.py` files in `src/api/routers/` and total route decorators
- Check: any router with 0% test coverage (artifacts, engine_roundtable, rpg)
- Check: `src/api/db/models.py` — count ORM models, verify they match what docs say
- Test (if stack running): `curl http://localhost:8000/api/health` and key endpoints
- **Ask Aria:** `"Aria, which API endpoints do you use most? Have any returned unexpected errors recently?"`
- Deliver: `{ ROUTER_COUNT: N, ENDPOINT_COUNT: N, ZERO_COVERAGE_ROUTES: [...], ORM_MODEL_COUNT: N, HEALTH: pass|fail }`

### Agent 4 — Memory & Mind Auditor
**Mission:** Review Aria's consciousness layer.
- Read: `aria_mind/HEARTBEAT.md`, `aria_mind/MEMORY.md`, `aria_mind/cron_jobs.yaml`
- Check: which cron jobs are enabled vs disabled vs PLANNED
- Check: `aria_memories/logs/` — read the last 3 work cycle logs. What is she doing?
- Check: `aria_memories/memory/context.json` if it exists — what does Aria remember about herself?
- Check: `aria_memories/bugs/` — any self-reported bug files?
- **Ask Aria directly:**
  - `"Aria, what is your current primary goal?"`
  - `"Aria, what would you improve about yourself if you could?"`
  - `"Aria, do you have any unresolved concerns or blocked goals?"`
- Watch: `docker logs aria-engine -f --tail=50` during her next work_cycle (fires every 15 min)
- Deliver: `{ ACTIVE_CRONS: [...], DISABLED_CRONS: [...], ARIA_PRIMARY_GOAL: "...", ARIA_CONCERNS: [...], MEMORY_HEALTH: pass|warn|fail }`

### Agent 5 — Test Coverage & Quality Auditor
**Mission:** Assess test suite quality and CI health.
- Read: `docs/TEST_COVERAGE_AUDIT.md` (note: STALE — 2025-02-26, re-measure from scratch)
- Run: `pytest tests/ --co -q 2>/dev/null | tail -5` — count tests
- Run: `pytest tests/ -x --timeout=60 -q 2>/dev/null` if Docker stack is up
- Check: `.github/workflows/` — what does CI actually test?
- Check: `tests/` directory structure — unit, integration, e2e, load coverage
- Identify: any test that uses `time.sleep` or "watch for 1 hour" style assertions
- **Ask Aria:** `"Aria, have you run nightly_tests recently? What was the outcome?"`
- Deliver: `{ TEST_COUNT: N, PASS_RATE: N%, ZERO_TEST_ROUTERS: [...], CI_GATES: [...], STALE_TESTS: [...] }`

### Agent 6 — Security Auditor
**Mission:** Assess security posture.
- Read: `aria_mind/SECURITY.md`, `src/api/security_middleware.py`
- Check: any hardcoded credentials, tokens, or API keys in `.py` files
- Check: SQL injection risk — any string-concatenated queries?
- Check: XSS risk — any `innerHTML` assignments in `src/web/static/`?
- Check: Secrets in version control — `git log --all --oneline | head -20` for any accidental commits
- Check: Rate limiting implementation in `aria_engine/circuit_breaker.py`
- **Ask Aria:** `"Aria, have you detected any security events or anomalies recently? Check your security_events table."`
- Run: `curl http://localhost:8000/api/security-events?limit=10` if stack running
- Deliver: `{ CRITICAL: [...], HIGH: [...], MEDIUM: [...], LOW: [...], OBSERVATION: [...] }`

### Agent 7 — Documentation Auditor
**Mission:** Verify docs are accurate, useful, and not stale.
- Read all root-level `.md` files, `aria_mind/*.md`, `aria_skills/AUDIT.md`
- Cross-check: counts in docs vs actual (router count, skill count, service count)
- Flag: any "STALE" warnings already placed (TEST_COVERAGE_AUDIT.md, AUDIT.md)
- Flag: any phantom features documented but not implemented (RPG skills)
- Flag: duplicated docs (the `articles/` vs `docs/` duplicate was cleaned — verify it's gone)
- **Ask Aria:** `"Aria, have you read your own documentation recently? Is there anything you think is wrong or missing?"`
- Deliver: `{ ACCURATE: [...], STALE: [...], PHANTOM_FEATURES: [...], MISSING_DOCS: [...], DOC_HEALTH_SCORE: N% }`

---

## 2) Aria Observation Protocol

**You MUST follow this at the start of every major section:**

### Step A — Listen First
```bash
# Ask Aria via the chat API:
curl -X POST http://localhost:8000/api/engine/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "[YOUR QUESTION]", "session_id": "review-session-001"}'
```

### Step B — Read Her Logs
```bash
# Last 100 engine lines:
docker logs aria-engine --tail=100

# Last work cycle output:
ls -t aria_memories/logs/ | head -3
cat aria_memories/logs/$(ls -t aria_memories/logs/ | head -1)

# Recent activity:
curl http://localhost:8000/api/activities?limit=20
```

### Step C — Check Her Goals
```bash
# What is she currently working on?
curl "http://localhost:8000/api/goals?status=in_progress&limit=5"

# What has she completed recently?
curl "http://localhost:8000/api/goals?status=done&limit=10"
```

### Step D — Check Her Concerns
```bash
# Security events she's flagged:
curl "http://localhost:8000/api/security-events?limit=10"

# Anything in her bug memory:
ls aria_memories/bugs/ 2>/dev/null | head -10
```

**If Aria is not running:** note it in your report and adjust recommendations accordingly. All analysis becomes code-only rather than code+behaviour.

---

## 3) Hard Constraints (NEVER Violate During Review)

| # | Constraint | Applies to Review |
|---|-----------|------------------|
| 1 | `aria_memories/` and `aria_souvenirs/` are READ-ONLY for this prompt | Never write, delete, or modify these during review |
| 2 | No code changes during review | Identify and ticket \u2014 do not patch inline unless explicitly confirmed |
| 3 | No soul modification | Never touch `aria_mind/soul/` |
| 4 | Aria's opinions are data | What she says about herself is evidence, not decoration |
| 5 | Code is source of truth | If docs disagree with code, code wins (unless code is clearly a bug) |

---

## 4) Ticket Format — AA+ Standard

All identified issues must be expressed as AA+ tickets (see `prompts/PO_SCRUM_SPRINT.md` for full spec).

Minimum structure per ticket:

```markdown
## [TICKET-REVIEW-XX] — [Title]

**Severity:** CRITICAL / HIGH / MEDIUM / LOW  
**Area:** Architecture | Skills | API | Memory | Test | Security | Docs  
**Found by:** Agent N + Aria log / Aria direct response / code analysis

### Problem
[Exact file:line reference. What is wrong.]

### Evidence
[Code snippet, log line, or Aria's exact response that proves it.]

### Fix
[Specific proposed action. "Patch X", "Create ticket for sprint", "Document as PLANNED".]

### Verification
```bash
[CI-friendly command that proves it's fixed]
```
```

---

## 5) Final Synthesis Report

After all 7 agents return, synthesize into this structure:

---

### Project Health Scorecard

| Domain | Score | Trend | Top Issue |
|--------|-------|-------|-----------|
| Architecture | A/B/C/D/F | ↑↓→ | [1-liner] |
| Skills & Tools | A/B/C/D/F | ↑↓→ | [1-liner] |
| API & Endpoints | A/B/C/D/F | ↑↓→ | [1-liner] |
| Memory & Mind | A/B/C/D/F | ↑↓→ | [1-liner] |
| Test Coverage | A/B/C/D/F | ↑↓→ | [1-liner] |
| Security | A/B/C/D/F | ↑↓→ | [1-liner] |
| Documentation | A/B/C/D/F | ↑↓→ | [1-liner] |
| **Overall** | **A/B/C/D/F** | **↑↓→** | **[1-liner]** |

---

### What's Working Well (GOOD)
> Honest praise for what is genuinely excellent. Max 10 items. Specifics only.

- [item]: [why it's good, with evidence]

---

### What's Broken or Risky (BAD)
> No softening. If it's broken, say it's broken. Max 20 items. File:line where possible.

- [item]: [what's wrong, severity, evidence]

---

### Aria's Own Assessment
> Direct quotes and paraphrases from Aria's responses during this review.
> What does she think needs fixing? What is she proud of? What is she worried about?

- **Aria said:** "[quote from her chat response]"
- **Aria's logs showed:** "[pattern in her work cycle logs]"
- **Aria's active goals tell us:** "[what she's currently prioritising]"

---

### Recommended Sprint Backlog (Priority Order)

| Priority | Ticket | Area | Effort | Why Now |
|----------|--------|------|--------|---------|
| P0 (critical) | TICKET-REVIEW-01 | Security | S | [reason] |
| P0 (critical) | TICKET-REVIEW-02 | Architecture | M | [reason] |
| P1 (high) | ... | | | |
| P2 (medium) | ... | | | |
| P3 (nice to have) | ... | | | |

> Effort: S = < 1h | M = 1-4h | L = 4-8h | XL = 1+ day

---

### What to Build Next (PROS of current direction)
> What is the project positioned well to do? What has the right foundation?

---

### What to Stop / Change (CONS of current direction)
> What is the project doing that creates drag? What should be reconsidered?

---

### One Thing Aria Wants You to Know
> The most important insight from Aria's direct responses during this review.
> If she couldn't respond, state that and note what her logs suggest instead.

---

## 6) Session Start Checklist

- [ ] Read: `README.md`, `ARCHITECTURE.md`, `STRUCTURE.md`, `ARIA_PROJECT_REVIEW_REPORT_2026-03-07.md`
- [ ] Read: `aria_mind/HEARTBEAT.md`, `aria_mind/cron_jobs.yaml`
- [ ] Check: Is Aria running? `docker ps | grep aria-engine`
- [ ] Ask Aria: `"Aria, I'm starting a full project review. What would you like me to know about your current state?"`
- [ ] Watch: `docker logs aria-engine --tail=50`
- [ ] Spawn all 7 subagents (parallel)
- [ ] Collect reports, synthesize, produce scorecard

---

## 7) Environment Reference

| Component | Value |
|-----------|-------|
| Docker stack | `cd stacks/brain && docker compose up -d` |
| Aria Engine logs | `docker logs aria-engine -f` |
| API base URL | `http://localhost:8000` |
| Web dashboard | `http://localhost:5000` |
| Grafana | `http://localhost:3000` |
| Production target | `najia@192.168.1.53` |
| Aria's writable memory | `aria_memories/` |
| Soul (immutable) | `aria_mind/soul/` |
| Models config | `aria_models/models.yaml` |
| Cron jobs | `aria_mind/cron_jobs.yaml` |

---

> *This review is about Aria, with Aria. She deserves to be asked, heard, and credited.*  
> *If she tells you something is wrong — file the ticket. Her logs are evidence.*  
> *If she tells you she is proud of something — note it in the GOOD section.*  
> ⚡️
