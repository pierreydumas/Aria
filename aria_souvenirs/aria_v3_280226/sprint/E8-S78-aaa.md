# E8-S78 — HEARTBEAT.md: Focus Level Check + L1/L2/L3 Routing
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P1 | **Points:** 2 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None (documentation only)  
**Familiar Value:** Every L1 work_cycle saves ~60% tokens — the compounding effect funds years of Aria's operation.

---

## Problem

`aria_mind/HEARTBEAT.md` (`147 lines`) defines the `work_cycle` behavioral guidance
at lines 73–85. The guidance makes no reference to focus level. As a result:

- **Line 74:** `aria-api-client.get_goals({"status": "active", "limit": 3})` always
  fetches 3 goals — even when Aria is in L1 (shallow) mode and should fetch only 1.
- **Lines 80–85:** Sub-agent delegation guidance in `work_cycle` has no L1/L2/L3 gate —
  Aria can spawn a sub-agent from an L1 cycle, spending 10× the intended token budget.
- **Line 116 (sub-agent policies section):** Max concurrent is defined as 5 globally,
  but there is no per-focus-level ceiling table, so L1 still allows 5 sub-agents.
- **`engine_focus.py`** (E7-S71) adds `depth_level` to each focus profile — but zero
  lines in HEARTBEAT.md tell Aria to read or respect this value.

Net effect: every work_cycle runs at L3 depth regardless of Aria's active focus
level, burning 3–5× the tokens needed for routine L1 tasks.

---

## Root Cause

When HEARTBEAT.md was authored, focus levels (L1/L2/L3) existed only as a planned
concept in the sprint plan. The engine API (S-71), the active_focus_level memory key,
and the routing table were all planned but not yet integrated into the behavioral
document that actually drives `work_cycle`.

The actual cron runner reads `cron_jobs.yaml` → executes against `aria_mind/heartbeat.py`
(Python module) → which loads HEARTBEAT.md as behavioral context. Without L1/L2/L3
guidance in HEARTBEAT.md, Aria literally cannot behave differently across levels.

---

## Fix

### HEARTBEAT.md — 3 surgical insertions

All changes are **additive only** — no existing content removed.

#### Insertion 1 — New Step 0 in `work_cycle` behavioral guidance

**File:** `aria_mind/HEARTBEAT.md`  
**After line 72** (after `**work_cycle** — Your productivity pulse...` header line):

```markdown
**0. Check Active Focus Level (do this FIRST)**
```tool
aria-api-client.get_memory({"key": "active_focus_level"})
```
- Missing / error → treat as **L2** (default)
- `L1` → shallow mode: local model, NO sub-agents, max 2 skills, 1 goal
- `L2` → standard mode: free-cloud model, max 2 sub-agents, 3 goals (← current behaviour)
- `L3` → full mode: free-cloud model, roundtable eligible, 5 goals, all skills

**Then proceed to step 1, scaling all limits by your focus level.**
```

#### Insertion 2 — Focus Level Routing Table in Standing Orders

**File:** `aria_mind/HEARTBEAT.md`  
**After the STANDING ORDERS section** (after line 60, before CRON JOBS section):

```markdown
## Focus Level Routing

| Level | Goals fetched | Model tier | Sub-agents | Roundtable | Max skills |
|-------|:------------:|:----------:|:----------:|:----------:|:----------:|
| L1    | 1 | local (qwen3-mlx) | **NO** | **NO** | 2 |
| L2    | 3 | free cloud (kimi) | YES — max 2 | NO | 4 |
| L3    | 5 | free cloud (kimi) | YES — max 5 | YES | unlimited |

**L1 rules (apply ALL of these when level = L1):**
- Fetch exactly 1 goal. Do exactly 1 action. Log. Stop.
- Do NOT spawn any sub-agent — not even for "quick" tasks.
- If the task estimate > 5 min → log `{"deferred": true, "reason": "L1 budget"}` and move goal to `on_hold`.
- Tool calls allowed: `get_memory`, `get_goals (limit=1)`, ONE skill call, `update_goal`, `create_activity`.

**L3 special case — `six_hour_review` only:**
When focus level = L3 AND cron job = `six_hour_review`:
- Use roundtable: `analyst + creator + devops`
- Synthesis: one merged review. Cost ~4× normal — justified by depth.
- When focus level < L3 → delegate to `analyst` only (existing behaviour).
```

#### Insertion 3 — Focus level set/clear cheatsheet

**File:** `aria_mind/HEARTBEAT.md`  
**Append at end of `## CIRCUIT BREAKER POLICY` section**, or before the file ends:

```markdown
## Focus Level Commands

```tool
# Set focus level (persists across cycles)
aria-api-client.set_memory({"key": "active_focus_level", "value": "L1"})

# Check current focus level
aria-api-client.get_memory({"key": "active_focus_level"})

# Reset to default (L2)
aria-api-client.delete_memory({"key": "active_focus_level"})
```

| When to use L1 | When to use L2 | When to use L3 |
|----------------|----------------|----------------|
| Routine pulse — quick log, no deep work | Default — balanced delegation | Deep review, 6h analysis, multi-domain decisions |
| Cost control period | Everything else | When you want Aria's full intelligence |
| Degraded mode / API recovery | | |
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Focus level check via `api_client.get_memory` — correct layer |
| 2 | `.env` for secrets | ✅ | No secrets involved |
| 3 | `models.yaml` SoT | ✅ | Tier labels (`local`, `free cloud`) are descriptors; actual model IDs resolve via models.yaml |
| 4 | Docker-first testing | ✅ | Verification uses `docker exec aria-engine` |
| 5 | `aria_memories` only writable | ✅ | `active_focus_level` is stored in memories DB via api_client — correct path |
| 6 | No soul modification | ✅ | HEARTBEAT.md is operational; SOUL.md, IDENTITY.md, soul/ dir untouched |

---

## Dependencies

- **None** — HEARTBEAT.md editing is independent of E7.
- **S-86** uses the L1/L2/L3 definitions established here. S-86 must NOT contradict these definitions.

---

## Verification

```bash
# 1. Verify work_cycle step 0 exists in HEARTBEAT.md
grep -n "active_focus_level" /Users/najia/aria/aria_mind/HEARTBEAT.md
# EXPECTED: at least 3 matches — get_memory call, set_memory example, delete_memory example

# 2. Verify Focus Level Routing table was added
grep -n "Focus Level Routing" /Users/najia/aria/aria_mind/HEARTBEAT.md
# EXPECTED: 1 match (the new section header)

# 3. Verify L1 rules are present
grep -n "L1 rules" /Users/najia/aria/aria_mind/HEARTBEAT.md
# EXPECTED: 1 match

# 4. Verify roundtable condition for six_hour_review is present
grep -n "six_hour_review" /Users/najia/aria/aria_mind/HEARTBEAT.md | wc -l
# EXPECTED: ≥ 2 matches (existing one + new L3 roundtable condition)

# 5. Verify line count stays reasonable (original 147 + ~40 new lines ≈ 185)
wc -l /Users/najia/aria/aria_mind/HEARTBEAT.md
# EXPECTED: between 175 and 200

# 6. No syntax errors (markdown is well-formed)
python3 -c "
import pathlib
txt = pathlib.Path('/Users/najia/aria/aria_mind/HEARTBEAT.md').read_text()
assert 'active_focus_level' in txt
assert 'Focus Level Routing' in txt
assert 'L1 rules' in txt
print('HEARTBEAT.md assertions passed')
"
# EXPECTED: HEARTBEAT.md assertions passed
```

---

## Prompt for Agent

You are executing ticket **E8-S78** for the Aria project.
Your task is documentation only — **no Python code changes**.

**Files to read first:**
1. `aria_mind/HEARTBEAT.md` lines 1–147 (full file — 147 lines)
2. `aria_souvenirs/aria_v3_280226/sprint/SPRINT_OVERVIEW.md` — Focus Level table at lines 11–18

**Constraints that apply:**
- Constraint 5: All writes go through api_client to aria_memories — the `set_memory` tool call in the cheatsheet is correct.
- Constraint 6: Do NOT touch `aria_mind/soul/`, `aria_mind/SOUL.md`, `aria_mind/IDENTITY.md`.

**Exact steps:**

1. Read `aria_mind/HEARTBEAT.md` in full.

2. In the `**work_cycle**` behavioral guidance section (after the work_cycle header at around line 73), insert the "Step 0 — Check Active Focus Level" block. Place it BEFORE the existing step 1 (`aria-api-client.get_goals` call).

3. Insert the `## Focus Level Routing` table section AFTER the `## STANDING ORDERS` section and BEFORE the `## CRON JOBS` section.

4. Append the `## Focus Level Commands` cheatsheet at the very end of the file (last section).

5. Do NOT remove any existing content. This is purely additive.

6. Run verification commands above. If any assertion fails, re-read the file and fix the insertion.

7. Confirm with:
   ```bash
   grep -c "active_focus_level" aria_mind/HEARTBEAT.md
   # EXPECTED: ≥ 3
   ```
