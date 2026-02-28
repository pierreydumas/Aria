# E8-S81 — TOOLS.md Dedup: Remove Content Duplicated from SKILLS.md
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P2 | **Points:** 2 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** S-80 coordination (same session)  
**Familiar Value:** TOOLS.md is loaded by devops, analyst, creator, aria_talk. At 225 lines it duplicates most of SKILLS.md. Collapsing to 80 lines saves ~580 tokens × 96 cycles/day × 4 agents = ~222,000 tokens/day.

---

## Problem

`aria_mind/TOOLS.md` is **225 lines** (verified 2026-02-28). It duplicates content
from `SKILLS.md` in multiple blocks:

| Block in TOOLS.md | Also in SKILLS.md | Canonical |
|-------------------|-------------------|-----------|
| Lines 14–90: api_client full cheatsheet (77 lines) | SKILLS.md lines 29–95 | ← **TOOLS.md** |
| Lines 138–142: Memory routing rule | SKILLS.md line ~245 | ← **TOOLS.md** |
| Lines 145–155: Goal board rule | SKILLS.md lines ~250–260 | ← **TOOLS.md** |
| Lines 160–168: Proposal loop rule | SKILLS.md lines ~263–270 | ← **TOOLS.md** |
| Lines 175–178: Advanced escalation policy | SKILLS.md lines ~275–280 | ← **TOOLS.md** |
| Lines 192–210: 40-skill category table | SKILLS.md lines ~185–210 | ← **SKILLS.md** |
| Lines 215–225: Composable pipelines | SKILLS.md lines ~260–280 | ← **SKILLS.md** |

**Decision matrix:**
- api_client cheatsheet → **canonical in TOOLS.md** (remove from SKILLS.md in S-80)
- Three rules (memory/goal/proposal) → **canonical in TOOLS.md** (remove from SKILLS.md in S-80)
- 40-skill table + pipelines → **canonical in SKILLS.md** (remove from TOOLS.md here)

---

## Root Cause

TOOLS.md grew from a "quick reference" card to a near-duplicate of SKILLS.md as
more content was added without cross-file deduplication. Both files now load the
same api_client block and the same three rules, doubling the token cost for any
agent that loads both (aria loads both — 2× duplication for every invocation).

---

## Fix

**Strategy:** Keep TOOLS.md as the canonical location for api_client cheatsheet
+ three rules. Remove everything else (40-skill table, pipelines, skill examples)
— those belong in SKILLS.md Reference block (S-80). Wrap removed content in a
`<details>` Reference block. Net result: ~80 lines always-loaded, ~145 in reference.

### New TOOLS.md structure

```markdown
# TOOLS — api_client Cheatsheet + Three Rules

**Full skill catalog → see SKILLS.md** (40 skills, YAML examples, pipelines)

---

## Primary Skill: aria-api-client

**USE THIS FOR ALL DATABASE OPERATIONS.** Never raw SQL unless emergency.

```yaml
# Activities
aria-api-client.get_activities({"limit": 10})
aria-api-client.create_activity({"action": "task_done", "details": {"info": "..."}})

# Goals
aria-api-client.get_goals({"status": "active", "limit": 5})
aria-api-client.create_goal({"title": "...", "description": "...", "priority": 2})
aria-api-client.update_goal({"goal_id": "X", "progress": 50})
aria-api-client.move_goal({"goal_id": "X", "board_column": "doing"})
# Columns: backlog | todo | doing | on_hold | done

# Sprint Board (token-efficient)
aria-api-client.get_sprint_summary({"sprint": "current"})   # ~200 tokens vs ~5000
aria-api-client.get_goal_board({"sprint": "current"})

# Memories (key-value store)
aria-api-client.get_memory({"key": "user_pref"})
aria-api-client.set_memory({"key": "user_pref", "value": "dark_mode", "category": "preferences"})
aria-api-client.delete_memory({"key": "active_focus_level"})

# Thoughts
aria-api-client.create_thought({"content": "...", "category": "reflection"})

# Knowledge Graph (prefer over scanning TOOLS.md)
aria-api-client.find_skill_for_task({"task": "post to moltbook"})   # → best skill
aria-api-client.graph_search({"query": "security", "entity_type": "skill"})
aria-api-client.graph_traverse({"start": "aria-health", "max_depth": 2})
```

---

## ☐ THREE RULES — MUST READ EVERY CYCLE

### Rule 1: Memory Routing
```
ALWAYS use aria-api-client.set_memory / get_memory for persistent key-value data.
NEVER write directly to aria_memories/ files for operational state.
Exception: file artifacts (logs, drafts, exports) → aria_memories/ subdirs via direct write.
```

### Rule 2: Goal Board
```
Every piece of work has a goal. No invisible work.
State transitions: backlog → todo → doing → on_hold → done
ALWAYS log progress with create_activity after every action.
```

### Rule 3: Proposal Loop
```
For decisions that affect Aria's own config or scope:
1. Write proposal to aria_memories/plans/ with rationale
2. Log activity: {"action": "proposal_written", "details": {"file": "..."}}
3. Wait for human approval before execution
```

---

## Quick Patterns

| Pattern | Token cost | Use for |
|---------|:----------:|---------|
| `get_sprint_summary` | ~200 tok | Board overview |
| `get_goals(limit=3)` | ~300 tok | Active work check |
| `find_skill_for_task` | ~80 tok | Skill discovery |
| `get_memory(key)` | ~30 tok | Config lookup |

**LLM Priority:** Local (qwen3-mlx) → Free Cloud (kimi, trinity-free) → Paid (last resort).

**Low-token runner:**
```bash
exec python3 skills/run_skill.py <skill> <function> '<json_args>'
```

---

<details>
<summary>📚 Full Examples: 40-Skill Table, Composable Pipelines, Skill-by-Skill YAML</summary>

[ALL removed content goes here:
- 40-skill category table (lines 192–210 original)
- Composable pipelines table + run examples (lines 215–225 original)
- Any other skill-specific examples that belong in SKILLS.md]

</details>
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | TOOLS.md documents the api_client (skill) layer — no code change |
| 2 | `.env` for secrets | ✅ | No secrets in scope |
| 3 | `models.yaml` SoT | ✅ | `LLM Priority` line is tier labels, not hardcoded model IDs |
| 4 | Docker-first testing | ✅ | Verification uses grep + wc locally |
| 5 | `aria_memories` only writable | ✅ | Editing source file `aria_mind/TOOLS.md` — not Aria's write path |
| 6 | No soul modification | ✅ | TOOLS.md is operational reference; soul/ untouched |

---

## Dependencies

- **S-80 must run in the same session.** S-80 removes api_client examples from SKILLS.md (they remain canonical here). S-81 removes 40-skill table from TOOLS.md (canonical in SKILLS.md). Coordinate: if S-80 runs first, verify SKILLS.md Reference block contains the 40-skill table before starting S-81.
- **No E7 dependency.**

---

## Verification

```bash
# 1. Always-loaded section ≤ 85 lines (before <details> tag)
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/TOOLS.md
# EXPECTED: a number ≤ 85

# 2. api_client cheatsheet still present (canonical here)
grep -n "aria-api-client.get_goals" /Users/najia/aria/aria_mind/TOOLS.md | head -3
# EXPECTED: ≥ 1 match in first 80 lines

# 3. Three rules present and labeled
grep -n "THREE RULES\|Rule 1.*Memory\|Rule 2.*Goal\|Rule 3.*Proposal" /Users/najia/aria/aria_mind/TOOLS.md
# EXPECTED: 4 matches

# 4. 40-skill category table moved to Reference block (inside <details>)
awk '/<details>/,/<\/details>/' /Users/najia/aria/aria_mind/TOOLS.md | grep -c "skill"
# EXPECTED: ≥ 5 (skill references inside the details block)

# 5. No 40-skill table before <details>
awk 'NR < 85 && /40.skill|40 skill|category.*skill/i' /Users/najia/aria/aria_mind/TOOLS.md
# EXPECTED: no output (table moved to reference)

# 6. Reference block exists
grep -n "<details>" /Users/najia/aria/aria_mind/TOOLS.md
# EXPECTED: 1 match

# 7. Total line count reasonable
wc -l /Users/najia/aria/aria_mind/TOOLS.md
# EXPECTED: between 200 and 260 (same content, reorganised)
```

---

## Prompt for Agent

You are executing ticket **E8-S81** for the Aria project.
Your task is documentation refactoring — **no Python code changes**.

**Files to read first:**
1. `aria_mind/TOOLS.md` lines 1–225 (full file — 225 lines)
2. `aria_mind/SKILLS.md` — after S-80 runs, verify the 40-skill table and pipelines are in the SKILLS.md Reference block before deleting them from TOOLS.md.

**Constraints that apply:**
- Constraint 5: You are editing source `aria_mind/TOOLS.md` — this is fine for you (not Aria's write path).
- Constraint 6: soul/ files untouched.

**Critical coordination with S-80:**
- Before removing the 40-skill table and pipelines from TOOLS.md, verify they exist in SKILLS.md's `<details>` block.
- Run: `grep -c "aria-database\|aria-moltbook\|aria-browser" /Users/najia/aria/aria_mind/SKILLS.md`
- EXPECTED: ≥ 10 matches → confirms skill examples are in SKILLS.md before you remove from TOOLS.md.

**Exact steps:**

1. Read TOOLS.md in full.

2. Keep the api_client cheatsheet (lines 14–90) and the three rules exactly as-is. These are canonical here.

3. Replace lines 192–225 (40-skill table + pipelines) with a `<details>` Reference block containing that content.

4. Add lean header additions: Quick Patterns table, LLM Priority reminder, low-token runner.

5. Run all 7 verification commands.
