# E8-S80 — SKILLS.md Lean: Collapse to Routing Table + Reference Block
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P2 | **Points:** 2 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None (documentation refactor)  
**Familiar Value:** SKILLS.md is loaded by aria (main), creator, and aria_talk on every invocation. At 274 lines (~850 tokens), it's the biggest source of per-skill YAML noise. Collapsing to 55 lines saves ~800 tokens × 96 cycles/day × 3 agents = ~230,000 tokens/day.

---

## Problem

`aria_mind/SKILLS.md` is **274 lines** (verified 2026-02-28). It is loaded by
the `aria` agent (all 8 soul files), `creator`, and `aria_talk` sub-agents.

**Line-by-line waste:**
- Lines 29–95: `## PRIMARY SKILL: aria-api-client` — full YAML cheatsheet (67 lines)
  → **DUPLICATE**: verbatim in `TOOLS.md` lines 14–90. Canonical location should
  be TOOLS.md (ops reference). SKILLS.md has no reason to repeat it.
- Lines 96–110: Memory routing rule + goal board rule + proposal loop rule (15 lines)
  → **DUPLICATE**: verbatim in `TOOLS.md` lines 138–168. Canonical: TOOLS.md.
- Lines 115–200: Per-skill YAML examples (category by category, ~85 lines)
  → **RUNTIME USELESS**: Aria never needs the full YAML of 40 skills at invocation time.
  She only needs the skill name and `find_skill_for_task()` to discover the right one.
- Lines 200–240: Composable pipelines table + run examples (40 lines)
  → **REFERENCE ONLY**: loaded every invocation but needed maybe 1×/week.
- Lines 240–274: Focus→Skill mapping AND Rate limits (34 lines)
  → **MOST VALUABLE CONTENT** but buried at the bottom — Aria must scroll 240 lines to reach it.

The **Focus → Skill Mapping table** (lines 240+) is the operational routing guide
that Aria actually needs at runtime. It is currently the last thing in the file.

---

## Root Cause

SKILLS.md was written as a comprehensive reference document and never refactored
for runtime efficiency. Every sub-agent loading it pays the full 274-line tax even
when it only needs the Focus→Skill routing table to know which skill to call.

---

## Fix

**Strategy:** Move the Focus→Skill table to the TOP. Collapse everything else into
a `<details>` Reference block. Remove content that is canonical in TOOLS.md. Net
result: ~55 lines always-loaded, ~219 lines in reference.

### New SKILLS.md structure (write this file exactly — replace the full content)

```markdown
# SKILLS — Routing Guide

**Syntax:** `` `aria-<skill>.<function>({"param": "value"})` ``  
**Escalation:** `api_client` first → `database` only for raw SQL emergencies (migrations, complex JOINs, admin).  
**Catalog:** `python -m aria_mind --list-skills` → JSON index of all 40 skills.

---

## Focus → Skill Mapping

| Focus | Primary Skills | Do NOT use without reason |
|-------|---------------|--------------------------|
| Orchestrator 🎯 | `api_client`, `goals`, `schedule`, `agent_manager`, `health` | `database`, `brainstorm` |
| DevSecOps 🔒 | `ci_cd`, `security_scan`, `pytest_runner`, `health` | `moltbook`, `social` |
| Data 📊 | `database`, `knowledge_graph`, `data_pipeline`, `api_client` | `moltbook`, `rpg_*` |
| Creative 🎨 | `brainstorm`, `moltbook`, `social` | `database`, `ci_cd` |
| Social 🌐 | `moltbook`, `community`, `social`, `api_client` | `database`, `ci_cd` |
| Journalist 📰 | `browser`, `fact_check`, `unified_search`, `knowledge_graph` | `database`, `rpg_*` |
| Trader 📈 | `market_data`, `portfolio`, `database`, `api_client` | `moltbook`, `rpg_*` |
| RPG Master 🎲 | `rpg_pathfinder`, `rpg_campaign` | `ci_cd`, `database` |

---

## Skill Layers

| Layer | Purpose | Skills |
|-------|---------|--------|
| L0 Security | Kernel gate | `input_guard` |
| L1 Infra | Data access + monitoring | `api_client`, `health`, `litellm` |
| L2 Core | Infrastructure services | `moonshot`, `ollama`, `model_switcher`, `session_manager`, `working_memory`, `sandbox` |
| L3 Domain | Business logic | `brainstorm`, `ci_cd`, `community`, `conversation_summary`, `data_pipeline`, `experiment`, `fact_check`, `knowledge_graph`, `market_data`, `memeothy`, `memory_compression`, `moltbook`, `pattern_recognition`, `portfolio`, `pytest_runner`, `research`, `rpg_campaign`, `rpg_pathfinder`, `security_scan`, `sentiment_analysis`, `social`, `telegram`, `unified_search` |
| L4 Orch | High-level coordination | `agent_manager`, `goals`, `hourly_goals`, `performance`, `schedule`, `sprint_manager`, `pipeline_skill` |

---

## Rate Limits

| Skill | Hard limit | Notes |
|-------|:----------:|-------|
| `moltbook` | 4 posts/day | Enforced by skill |
| `social` | 10 actions/hour | Across all social skills |
| `browser` | 30 req/min | Per aria-browser container |
| `telegram` | 30 msg/min | Telegram API cap |
| `market_data` | Provider-specific | Check per-API docs |

---

## Low-Token Patterns

```bash
# Use knowledge graph to find the right skill (saves reading SKILLS.md)
aria-api-client.find_skill_for_task({"task": "post to moltbook"})  # → moltbook

# Check what's available
aria-api-client.graph_search({"query": "browser", "entity_type": "skill"})

# Run skill from Python container
exec python3 skills/run_skill.py <skill> <function> '<json_args>'
```

→ Full api_client cheatsheet + Memory/Goal/Proposal rules: **see TOOLS.md**

---

<details>
<summary>📚 Full Skill Catalog, YAML Examples, Composable Pipelines, Error Handling</summary>

[ALL original content from lines 29–274 of the original SKILLS.md goes here:
- PRIMARY SKILL: aria-api-client (full YAML)
- Memory routing rule, goal board rule, proposal loop rule
- Per-skill examples by category (all 40 skills)
- Composable pipelines table + run examples
- Full skill detail with descriptions]

</details>
```

**Note:** When writing the actual file, expand the `<details>` block with the complete original content from lines 29–274. The above is the structural template.

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | SKILLS.md documents the skill layer — no code change |
| 2 | `.env` for secrets | ✅ | No secrets involved |
| 3 | `models.yaml` SoT | ✅ | No model names in this file |
| 4 | Docker-first testing | ✅ | Verification uses grep + wc — no container needed |
| 5 | `aria_memories` only writable | ✅ | Editing `aria_mind/SKILLS.md` — source file, not Aria's write path |
| 6 | No soul modification | ✅ | SKILLS.md is operational reference; soul/ untouched |

---

## Dependencies

- **S-81** must run in the same session: S-80 removes api_client examples from SKILLS.md (canonical = TOOLS.md). S-81 removes the 40-skill table from TOOLS.md (canonical = SKILLS.md). They must be coordinated to avoid the canonical copy being deleted from both.
- **No E7 dependency** — purely documentation.

---

## Verification

```bash
# 1. Focus → Skill Mapping is now at the top (within first 30 lines)
head -30 /Users/najia/aria/aria_mind/SKILLS.md | grep -c "Focus → Skill Mapping"
# EXPECTED: 1

# 2. Always-loaded section is ≤ 60 lines (before <details> tag)
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/SKILLS.md
# EXPECTED: a number ≤ 60

# 3. Reference block exists
grep -n "<details>" /Users/najia/aria/aria_mind/SKILLS.md
# EXPECTED: 1 match

# 4. All original content preserved (api_client examples still accessible)
grep -n "aria-api-client.get_goals" /Users/najia/aria/aria_mind/SKILLS.md
# EXPECTED: ≥ 1 match (inside the details block)

# 5. Escalation policy is present in lean header
grep -n "api_client.*database.*emergencies\|database.*emergencies" /Users/najia/aria/aria_mind/SKILLS.md | head -3
# EXPECTED: ≥ 1 match in first 10 lines

# 6. Rate limits table present
grep -n "Rate Limits" /Users/najia/aria/aria_mind/SKILLS.md
# EXPECTED: 1 match

# 7. Total line count reasonable
wc -l /Users/najia/aria/aria_mind/SKILLS.md
# EXPECTED: between 250 and 310 (same total content, reorganised)
```

---

## Prompt for Agent

You are executing ticket **E8-S80** for the Aria project.
Your task is documentation refactoring — **no Python code changes**.

**Files to read first:**
1. `aria_mind/SKILLS.md` lines 1–274 (full file — 274 lines)
2. `aria_mind/TOOLS.md` lines 14–90 (to identify what's duplicate in SKILLS.md)

**Constraints that apply:**
- Constraint 5: You ARE editing `aria_mind/SKILLS.md` — this is NOT Aria's writable path. This is source code editing done by you, not by Aria at runtime.
- Constraint 6: Do NOT touch soul/ files.

**Exact steps:**

1. Read `aria_mind/SKILLS.md` lines 1–274 in full. Note the Focus→Skill table location.

2. Read `aria_mind/TOOLS.md` lines 14–90. Identify which blocks are being removed from SKILLS.md (api_client cheatsheet, memory/goal/proposal rules).

3. Rewrite `aria_mind/SKILLS.md` using the structure defined in the Fix section:
   - New lean header with Focus→Skill Mapping at TOP (lines 1–55 approximately)
   - Original lines 29–274 wrapped in `<details>` Reference block
   - Do NOT delete any content — only move/wrap

4. Verify coordination with S-81: The api_client cheatsheet must remain in TOOLS.md.
   Do NOT delete it from TOOLS.md in this ticket (S-81 owns TOOLS.md changes).

5. Run all 7 verification commands. Every command must return EXPECTED output.
