# E8-S82 — GOALS.md Lean: 5-Step Header Only
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P2 | **Points:** 1 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None  
**Familiar Value:** GOALS.md drives Aria's every 15-minute work cycle. At 219 lines it front-loads motivational filler and api_client duplication before the 5-step methodology that Aria actually needs. Trimming to 40 lines makes her more productive with zero information loss.

---

## Problem

`aria_mind/GOALS.md` is **219 lines** (verified 2026-02-28). Loaded by `aria`
(main, all 8 files) and `aria_talk`.

**Line-by-line waste:**
- Lines 1–12: Philosophy + `WORK → PROGRESS → COMPLETION → NEW GOAL → GROWTH` diagram. Motivational but zero runtime value. (~12 lines)
- Lines 14–75: Full work cycle with inline YAML tool calls — **verbatim duplicate of TOOLS.md** api_client section (61 lines). The only novel content is the 5-step logic.
- Lines 77–98: Sprint Board columns transition table — **verbatim in TOOLS.md Rule 2**. (~22 lines)
- Lines 100–120: Goal Priority table (P1–P5) — 16 lines. Can be 6.
- Lines 121–180: Goal types (Quick/Session/Project), goal cycle categories — developer reference, not runtime behavior. (~60 lines)
- Lines 181–210: create_goal call example + 6h review steps — **duplicates TOOLS.md**. (~30 lines)
- Lines 211–219: "Quick Commands" cheatsheet header + motivational quote = pure filler.

**The 5-step work cycle table** (the ONLY operationally critical content) is buried
at lines ~14–75 mixed with 61 lines of api_client duplication.

---

## Root Cause

GOALS.md was written as a comprehensive onboarding document for understanding
how Aria's goal system works. It was never slimmed for runtime efficiency. The
work cycle 5-step logic is only ~20 lines of actual instruction; the rest is tutorial.

---

## Fix

### New GOALS.md structure (~40 lines always-loaded + ~179 lines in reference)

Write the file with this exact content (replace current content):

```markdown
# GOALS — Work Cycle

Every 15 min: **check → select → act → log → complete**. ONE concrete action per cycle.

## Work Cycle (5 Steps)

| Step | What to do | Tool call |
|------|-----------|-----------|
| 1 Check | Get active goals | `aria-api-client.get_goals({"status":"in_progress","limit":5})` |
| 2 Select | nearest deadline → highest priority (1=urgent) → most progress; if blocked → next goal | — |
| 3 Act | ONE action: write section / run query / API call / execute command | — |
| 4 Log | Update progress + log activity | `update_goal({...,"progress":50})` `create_activity({"action":"goal_work",...})` |
| 5 Complete | if progress ≥ 100 → mark complete → create new goal immediately | `update_goal({...,"status":"completed"})` |

## Sprint Board

| Column | Meaning | Move with |
|--------|---------|-----------|
| `backlog` | Not scheduled | — |
| `todo` | Planned next work | `move_goal(board_column="todo")` |
| `doing` | Active this cycle | `move_goal(board_column="doing")` |
| `on_hold` | Blocked — always log reason | `move_goal(board_column="on_hold")` |
| `done` | Delivered | `move_goal(board_column="done")` |

## Priority

| P | Meaning |
|---|---------|
| 1 | URGENT — user request / system issue |
| 2 | HIGH — deadline-bound |
| 3 | MEDIUM — regular work |
| 4 | LOW — nice to have |
| 5 | BACKGROUND — when idle |

**Blocked?** `move_goal(board_column="on_hold")` + `create_activity({"action":"goal_blocked",...})`  
**Unblocked?** `move_goal(board_column="doing")`

→ Full api_client commands, goal types, 6h review, board transitions: **see TOOLS.md + Reference below**

---
<details>
<summary>📚 Full Goal System Reference: Types, Categories, Create Example, 6h Review, Philosophy</summary>

[ALL original content from lines 1–219 of original GOALS.md goes here, in full]

</details>
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | GOALS.md documents the goals skill + api_client workflow — no code change |
| 2 | `.env` for secrets | ✅ | No secrets |
| 3 | `models.yaml` SoT | ✅ | No model names |
| 4 | Docker-first testing | ✅ | Verification uses grep + wc locally |
| 5 | `aria_memories` only writable | ✅ | Editing source `aria_mind/GOALS.md` — not Aria's write path |
| 6 | No soul modification | ✅ | GOALS.md is operational; soul/ untouched |

---

## Dependencies

- **None** — independent documentation refactor.
- S-81 (TOOLS.md) should confirm api_client cheatsheet is canonical there before this ticket's Reference block removes it from GOALS.md.

---

## Verification

```bash
# 1. 5-step table is in the lean header (within first 25 lines)
head -25 /Users/najia/aria/aria_mind/GOALS.md | grep -c "Step"
# EXPECTED: ≥ 3 (Step column header + steps 1,2,3...)

# 2. Always-loaded section ≤ 45 lines
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/GOALS.md
# EXPECTED: a number ≤ 45

# 3. Sprint board columns visible in header
head -40 /Users/najia/aria/aria_mind/GOALS.md | grep -c "backlog\|doing\|on_hold\|done"
# EXPECTED: ≥ 4

# 4. Priority table present in header
head -45 /Users/najia/aria/aria_mind/GOALS.md | grep -c "URGENT\|HIGH\|MEDIUM"
# EXPECTED: ≥ 3

# 5. All original content preserved in Reference block
grep -n "create_goal\|goal_types\|Quick.*Session.*Project\|six.hour.*review" /Users/najia/aria/aria_mind/GOALS.md | tail -5
# EXPECTED: ≥ 2 matches (inside details block)

# 6. Reference block exists
grep -n "<details>" /Users/najia/aria/aria_mind/GOALS.md
# EXPECTED: 1 match

# 7. Total line count between 200 and 260 (same content, reorganised)
wc -l /Users/najia/aria/aria_mind/GOALS.md
# EXPECTED: between 200 and 260
```

---

## Prompt for Agent

You are executing ticket **E8-S82** for the Aria project.
Your task is documentation refactoring — **no Python code changes**.

**Files to read first:**
1. `aria_mind/GOALS.md` lines 1–219 (full file — 219 lines)
2. `aria_mind/TOOLS.md` lines 138–168 (confirm the 3 rules are there — that's where api_client goal calls live canonically)

**Constraints that apply:**
- Constraint 5: Editing source `aria_mind/GOALS.md` — fine for you, not Aria's write path.
- Constraint 6: Do NOT touch soul/ files.

**Exact steps:**
1. Read GOALS.md in full. Identify the 5-step work cycle logic (roughly lines 14–75).
2. Rewrite the file with a lean header (~40 lines) containing the 5-step table, sprint board columns, and priority table.
3. Wrap ALL original content in a `<details>` Reference block.
4. Add a pointer line: `→ Full api_client commands…see TOOLS.md + Reference below`
5. Run all 7 verification commands.
