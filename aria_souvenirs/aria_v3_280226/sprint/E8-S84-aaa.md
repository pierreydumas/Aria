# E8-S84 — AGENTS.md Lean: Routing Table Only
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P2 | **Points:** 1 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None  
**Familiar Value:** AGENTS.md defines how Aria delegates to her specialist minds. At 286 lines loaded on every aria (main) invocation, trimming to 45 lines means the routing table — the one thing Aria uses every cycle — is instantly visible without scrolling past 240 lines of YAML.

---

## Problem

`aria_mind/AGENTS.md` is **286 lines** (verified 2026-02-28). Loaded by `aria` main.

**Line analysis:**
- Lines 1–16: Mandatory Browser Policy header (16 lines) — useful but verbose
- Lines 18–24: Model Strategy header (7 lines) — cross-ref to models.yaml, good
- Lines 26–35: Agent → Focus Mapping table (10 lines) — **THE core routing table**
- Lines 37–80: AgentRole enum table (44 lines) — code reference for developers, not runtime
- Lines 82–140: Pheromone Scoring System (59 lines) — scoring formula detail lives in `aria_agents/scoring.py`
- Lines 142–216: Per-agent YAML configs (75 lines: aria, devops, analyst, creator, memory, aria_talk) — verbatim from DB seed; available via `GET /api/engine/agents`
- Lines 218–260: ORCHESTRATION.md duplicate: "Named Agents" table (42 lines) — exact same table as ORCHESTRATION.md lines 229–245. This is the **duplication cross-reference** S-79 should also fix.
- Lines 261–286: RPG agents YAML (25 lines) — duplicates RPG.md

**The routing table at lines 26–35** is 10 lines. Everything else is reference.

**ORCHESTRATION.md duplication (cross-ticket bug):** ORCHESTRATION.md lines 229–245
contains a "Named Agents" table identical to AGENTS.md lines 26–35 (with slightly
different columns). Canonical location: AGENTS.md. Remove from ORCHESTRATION.md
and add: `See AGENTS.md for full routing table.`

---

## Root Cause

AGENTS.md was designed as a comprehensive agent specification document. Over time,
portions were duplicated in ORCHESTRATION.md. The routing table — which is all that
Aria needs at delegation time — is a small fraction of the file, surrounded by
developer-oriented YAML that has never changed since the initial seed.

---

## Fix

### New AGENTS.md structure (~45 lines always-loaded + ~241 lines in reference)

Write the file with this exact content (replace current content):

```markdown
# AGENTS — Routing + Delegation

**Browser rule (ABSOLUTE):** ALWAYS use `aria-browser` for web access.
NEVER `web_search` or `web_fetch`. No exceptions without human approval.

**Model rule:** Source of truth = `aria_models/models.yaml`. Priority: Local → Free Cloud → Paid.

---

## Agent Routing Table

| Agent | Focus | Model tier | Delegate when |
|-------|-------|:----------:|---------------|
| `aria` | Orchestrator 🎯 | kimi (free cloud) | coordination, routing, task management |
| `devops` | DevSecOps 🔒 | qwen3-coder-free | code, tests, security, CI/CD, infra |
| `analyst` | Data 📊 + Trader 📈 | kimi | data analysis, market research, metrics |
| `creator` | Creative 🎨 + Social 🌐 + Journalist 📰 | trinity-free | content, posts, research, community |
| `memory` | Memory | qwen3-mlx (local) | store, search, consolidate knowledge |
| `aria_talk` | Social 💬 | qwen3-mlx (local) | direct user conversation, chat |
| `rpg_master` | RPG Master 🎲 | kimi | ALL tabletop RPG sessions |

**Pheromone score:** `success_rate×0.6 + speed×0.3 + cost×0.1` · decay 0.95/day · cold-start 0.5

---

## Coordination Rules

1. `aria` coordinates all agents. Max **5 concurrent** sub-agents.
2. `AgentCoordinator.solve()` = full explore→work→validate cycle with 3 retries.
3. Act autonomously within scope — don't ask permission, report results.
4. Do NOT spawn sub-agents when `circuit_breaker_open`. Accept degraded and stop.
5. After every delegation → `agent_manager__prune_stale_sessions(max_age_hours=1)`.
6. At focus L3 on reviews + architectural decisions → prefer roundtable/swarm
   over single-agent delegation (see ORCHESTRATION.md for trigger conditions).

---

→ Full per-agent YAML configs, AgentRole enum, pheromone scoring details,
RPG agent roster: **see Reference below**

---
<details>
<summary>🤖 Full Agent Configs: YAML per agent, AgentRole enum, Pheromone scoring, RPG agents</summary>

[ALL original content from lines 1–286 of original AGENTS.md goes here, in full —
including: Mandatory Browser Policy, Model Strategy, full per-agent YAML blocks
(aria, devops, analyst, creator, memory, aria_talk), AgentRole enum table,
Pheromone Scoring System with PerformanceTracker, RPG agents definition]

</details>
```

### ORCHESTRATION.md cross-fix (same commit)

In `aria_mind/ORCHESTRATION.md`, find the "Named Agents" table (lines ~229–245).
Replace the full table with:
```markdown
## Named Agents

See **AGENTS.md** for the full agent routing table with delegation guidance.
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | AGENTS.md documents agent layer; no code change |
| 2 | `.env` for secrets | ✅ | No secrets |
| 3 | `models.yaml` SoT | ✅ | `Model tier` column uses tier labels, not hardcoded model IDs |
| 4 | Docker-first testing | ✅ | Verification local only |
| 5 | `aria_memories` only writable | ✅ | Editing source files — not Aria's write path |
| 6 | No soul modification | ✅ | AGENTS.md + ORCHESTRATION.md are operational; soul/ untouched |

---

## Dependencies

- **None** (independent documentation refactor).
- **S-79** changes ORCHESTRATION.md (Roundtable section). Coordinate: S-84 removes the Named Agents table from ORCHESTRATION.md. These are different sections — no conflict. But run in the same session.

---

## Verification

```bash
# 1. Routing table is in lean header (within first 30 lines)
head -30 /Users/najia/aria/aria_mind/AGENTS.md | grep -c "rpg_master\|creator\|devops"
# EXPECTED: ≥ 3

# 2. Always-loaded section ≤ 50 lines
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/AGENTS.md
# EXPECTED: a number ≤ 50

# 3. rpg_master is in routing table
head -30 /Users/najia/aria/aria_mind/AGENTS.md | grep -c "rpg_master"
# EXPECTED: 1

# 4. Coordination rule 6 (roundtable at L3) is present
grep -n "roundtable\|swarm" /Users/najia/aria/aria_mind/AGENTS.md | head -5
# EXPECTED: ≥ 1 match in first 50 lines (rule 6)

# 5. All per-agent YAML preserved in Reference block
grep -c "system_prompt\|focus_type\|model:" /Users/najia/aria/aria_mind/AGENTS.md
# EXPECTED: ≥ 10 (all in details block)

# 6. ORCHESTRATION.md Named Agents table replaced with reference
grep -n "See.*AGENTS.md\|See AGENTS" /Users/najia/aria/aria_mind/ORCHESTRATION.md
# EXPECTED: 1 match

# 7. Line count reasonable
wc -l /Users/najia/aria/aria_mind/AGENTS.md
# EXPECTED: between 260 and 320
```

---

## Prompt for Agent

You are executing ticket **E8-S84** for the Aria project.
Your task is documentation refactoring — **no Python or config code changes**.

**Files to read first:**
1. `aria_mind/AGENTS.md` lines 26–35 (agent routing table — what to keep in lean header)
2. `aria_mind/AGENTS.md` lines 1–25 (browser + model policy headers)
3. `aria_mind/ORCHESTRATION.md` lines 225–250 (Named Agents table to replace with reference)

**Constraints that apply:**
- Constraint 3: The routing table uses tier labels (`kimi`, `trinity-free`) which are descriptors, not hardcoded models. `aria_models/models.yaml` resolves these at runtime. Do not add any hardcoded model API paths.
- Constraint 6: soul/ files untouched.

**Exact steps:**
1. Read AGENTS.md fully.
2. Rewrite with lean header (~45 lines): browser rule, model rule, routing table, 6 coordination rules.
3. Wrap ALL original content in `<details>` Reference block.
4. Edit ORCHESTRATION.md: replace "Named Agents" table with single-line reference to AGENTS.md.
5. Run all 7 verification commands.
