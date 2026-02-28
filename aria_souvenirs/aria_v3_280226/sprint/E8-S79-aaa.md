# E8-S79 — ORCHESTRATION.md: Roundtable / Swarm Trigger Conditions
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P1 | **Points:** 2 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None (documentation only)  
**Familiar Value:** Roundtable/swarm are Aria's collective intelligence. Without trigger conditions she defaults to single-agent even when complex tasks demand multiple perspectives — reducing the quality of every major decision she supports.

---

## Problem

`aria_mind/ORCHESTRATION.md` is 272 lines. The roundtable and swarm tools are
defined at lines **256–272** (the final 17 lines of the file) in a minimal block:

```
### Roundtable
Multi-agent discussion orchestrator. Creates a temporary session, sends the topic
to all enabled agents in parallel, collects their responses, then synthesizes a
unified answer.
- Endpoint: POST /api/engine/roundtable
...
### Swarm
Decision-making orchestrator for binary/multi-choice questions...
```

**Zero trigger conditions. Zero API signatures. Zero usage examples.**

Consequences:
1. Sub-agents (`devops`, `analyst`, `creator`) do NOT load ORCHESTRATION.md
   (verified from `AGENTS.md` named agents table — they load only `IDENTITY, TOOLS,
   SECURITY/MEMORY/SOUL/SKILLS`). They never discover that roundtable/swarm exist.
2. Aria defaults to single-agent delegation even when topic complexity clearly
   warrants multi-perspective analysis.
3. `six_hour_review` (`HEARTBEAT.md` line 92: "Delegate to analyst") delegates to
   a single agent instead of triggering a roundtable — losing creator and devops perspectives.
4. The actual `POST /api/engine/roundtable` payload format (verified against
   `aria_engine/roundtable.py` line 136 `discuss()` signature):
   ```
   {"topic": str, "agent_ids": list[str], "rounds": int, "timeout": int}
   ```
   is NOT documented anywhere in any mind file.

---

## Root Cause

ORCHESTRATION.md was written before roundtable/swarm were implemented. The
implementation (`aria_engine/roundtable.py`, `aria_engine/swarm.py`) was added
in a later sprint but ORCHESTRATION.md was not updated with:
- When to use each mode
- How to call each endpoint (tool syntax)
- What topic categories trigger roundtable vs swarm vs single-agent

---

## Fix

### ORCHESTRATION.md — expand Roundtable & Swarm section

**File:** `aria_mind/ORCHESTRATION.md`  
**Location:** Replace lines 256–272 (the existing sparse Roundtable/Swarm block)  
**Strategy:** Replace with a full trigger-conditions section

**BEFORE (lines 256–272 — current sparse block):**
```markdown
## Roundtable & Swarm

### Roundtable
Multi-agent discussion orchestrator. Creates a temporary session...
- Endpoint: `POST /api/engine/roundtable`
- Agents each respond independently with their perspective
- A synthesis LLM merges all perspectives into one coherent response

### Swarm
Decision-making orchestrator for binary/multi-choice questions...
- Endpoint: `POST /api/engine/swarm`
- Useful for go/no-go decisions, architecture choices, priority ranking
```

**AFTER:**
```markdown
## Roundtable & Swarm — When to Use and How

### Decision Matrix

| Scenario | Mode | Agents | Why |
|----------|------|--------|-----|
| Complex analysis with multiple domains | **Roundtable** | analyst + creator + devops | Parallel perspectives → synthesized |
| Go/no-go architecture / risk decision | **Swarm** | devops + analyst | Consensus voting — binary outcome |
| Single-domain task with clear owner | **Single-Agent** | matching specialist | Cheaper, faster |
| `six_hour_review` (focus L3) | **Roundtable** | analyst + creator + devops | Full-coverage review |
| `weekly_summary` | **Roundtable** | all active agents | Comprehensive |
| Security code review | **Swarm** | devops + analyst | Vote on risk level |
| Content strategy + community impact | **Roundtable** | creator + analyst | Multiple creative lenses |

### Trigger Rule (apply in this order)

```
1. Is focus level L3?  AND  Does topic span ≥2 focus domains?
   → ROUNDTABLE

2. Is it a binary decision (yes/no, proceed/abort)?  AND  Risk ≥ medium?
   → SWARM

3. Everything else:
   → SINGLE-AGENT (delegate to highest-scoring specialist)
```

### How to Trigger

```tool
# Roundtable — parallel multi-perspective discussion + synthesis
POST /api/engine/roundtable
{
  "topic": "Analyze Q1 performance across content, code, and data",
  "agent_ids": ["analyst", "creator", "devops"],
  "rounds": 2,
  "timeout": 180
}

# Swarm — consensus voting on binary decision
POST /api/engine/swarm
{
  "question": "Should we proceed with migrating litellm to the new config format?",
  "agent_ids": ["devops", "analyst"],
  "consensus_threshold": 0.7,
  "max_iterations": 3
}
```

### six_hour_review — Roundtable at Focus L3

When `active_focus_level = L3` AND cron job = `six_hour_review`:
```tool
POST /api/engine/roundtable
{
  "topic": "6-hour system review: goals, content, health, errors",
  "agent_ids": ["analyst", "creator", "devops"],
  "rounds": 1,
  "timeout": 240
}
```
When `active_focus_level < L3` → delegate to `analyst` only (existing behaviour).

### Why Not Always Use Roundtable?

| Mode | Token cost | Time | Quality |
|------|:----------:|:----:|:-------:|
| Single-agent | 1× | 1× | Good |
| Roundtable | 3–5× | 1.5–2× | Excellent |
| Swarm | 3–5× | 2–3× | Excellent for decisions |

**Reserve Roundtable for tasks where multiple perspectives materially improve the
output. Routine work_cycles, simple lookups, and single-domain tasks should always
use Single-Agent.**

### Roundtable vs Multi-Step Single-Agent

Roundtable ≠ sequential sub-agents. In a roundtable:
- All agents respond in **parallel** to the same topic
- Each agent sees other agents' prior-round responses (collaborative)
- A synthesis model merges all into ONE response
→ Use when you want synthesis, not just delegation
```

### AGENTS.md coordination rules update (cross-reference)

In `aria_mind/AGENTS.md`, append to the coordination rules list:
```markdown
6. At focus L3 on reviews and architectural decisions → prefer roundtable/swarm
   over single-agent delegation (see ORCHESTRATION.md for trigger conditions).
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | Roundtable endpoint is engine-layer; called via api_client from skills layer |
| 2 | `.env` for secrets | ✅ | No secrets involved |
| 3 | `models.yaml` SoT | ✅ | Agent IDs reference named agents, not hardcoded model names |
| 4 | Docker-first testing | ✅ | Verification can use docker exec aria-engine |
| 5 | `aria_memories` only writable | ✅ | No file writes to non-memories paths |
| 6 | No soul modification | ✅ | ORCHESTRATION.md is operational; soul/ files untouched |

---

## Dependencies

- **None** — documentation change only.
- **S-78** establishes L1/L2/L3 in HEARTBEAT.md. S-79 cross-references L3 trigger in HEARTBEAT.md context. They should be done in the same session but have no hard dependency.
- **S-86** will implement the code side. S-79's roundtable API signatures must match what S-86 implements. Verified against `aria_engine/roundtable.py:136` — signatures are correct.

---

## Verification

```bash
# 1. Trigger decision matrix is present
grep -n "Trigger Rule" /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: 1 match

# 2. Roundtable API signature is documented
grep -n "api/engine/roundtable" /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: ≥ 1 match

# 3. Swarm API signature is documented
grep -n "api/engine/swarm" /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: ≥ 1 match

# 4. six_hour_review roundtable condition is present
grep -n "six_hour_review" /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: ≥ 1 match

# 5. Verify actual roundtable.py discuss() signature matches documented payload
grep -n "async def discuss" /Users/najia/aria/aria_engine/roundtable.py
# EXPECTED: line 136 or nearby — shows topic: str, agent_ids: list[str]

# 6. Line count is reasonable (272 original + ~70 added ≈ 340)
wc -l /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: between 330 and 360
```

---

## Prompt for Agent

You are executing ticket **E8-S79** for the Aria project.
Your task is documentation only — **no Python code changes**.

**Files to read first:**
1. `aria_mind/ORCHESTRATION.md` lines 240–272 (existing Roundtable/Swarm section)
2. `aria_engine/roundtable.py` lines 136–165 (verify `discuss()` signature)
3. `aria_engine/swarm.py` lines 155–200 (verify `execute()` signature)
4. `aria_mind/HEARTBEAT.md` — find `six_hour_review` line to understand current single-agent delegation

**Constraints that apply:**
- Constraint 1: Roundtable/swarm calls go through api_client from skill layer — the endpoint paths documented must match engine routes exactly.
- Constraint 6: Do NOT touch soul/ files.

**Exact steps:**

1. Read `aria_mind/ORCHESTRATION.md` lines 240–272.

2. Replace the sparse `## Roundtable & Swarm` section (lines 256–272) with the full trigger-conditions section from the Fix block above. Preserve all content before line 256.

3. Open `aria_mind/AGENTS.md`. Find the coordination rules numbered list. Append rule 6 about L3 preferring roundtable.

4. Verify that `aria_engine/roundtable.py` shows `discuss(topic: str, agent_ids: list[str], ...)` — if the actual signature differs, update the documented API payload to match.

5. Run all 6 verification commands. Every command must return the EXPECTED output.
