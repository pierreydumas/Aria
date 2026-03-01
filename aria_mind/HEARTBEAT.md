# HEARTBEAT.md - Autonomous Runtime (Lean)

## Runtime Paths (Container)

In container runtime, workspace root is `/app/`.

| What | Correct Path |
|------|-------------|
| Skill runner | `skills/run_skill.py` or `/app/skills/run_skill.py` |
| Skill packages | `skills/aria_skills/<name>/` |
| Workspace root | `/app/` |

Rules:
- Never prefix with `aria_mind/`.
- Never instantiate `SkillClass()` directly.
- If exec is required, use:

```bash
exec python3 skills/run_skill.py <skill> <function> '<json_args>'
```

---

## Scope

This file is intentionally minimal and centered on `work_cycle`.
Schedules remain in `cron_jobs.yaml` (single source of truth).

---

## Standing Non-Negotiables

1. Never expose credentials.
2. Always log actions.
3. Write artifacts only under `/app/aria_memories/`.
4. If API circuit breaker is open, degrade and stop (no sub-agent fallback).
5. Prune stale sessions with `agent_manager__prune_stale_sessions(max_age_hours=1)`.
6. Keep heartbeat goal-centric: start from working memory `active_goal_reference` when available.

---

## Focus Levels (used by work_cycle)

| Level | Goals fetched | Sub-agents | Max skills |
|-------|:------------:|:----------:|:----------:|
| L1    | 1 | No | 2 |
| L2    | 3 | Max 2 | 4 |
| L3    | 5 | Max 5 | Unlimited |

L1 hard limits:
- Exactly 1 goal, 1 concrete action, then log and stop.
- No sub-agents.
- If task estimate > 5 minutes, defer and move goal to `on_hold`.

Active focus lookup:

```tool
aria-api-client.get_memory({"key": "active_focus_level"})
```

If missing/error, default to `L2`.

---

## work_cycle (Primary Behavior)

Execution budget:
- One pass only (no loop).
- Max 10 tool calls.
- No repeated discovery calls (`read_artifact` / `list_artifacts`).
- No sub-agents for control-plane steps (goal fetch/update/log/artifact/session prune).

Flow:
1. Read focus level (`active_focus_level`), default `L2`.
2. Read working-memory goal anchor:
   - `aria-api-client.get_memory({"key":"active_goal_reference"})`
3. Resolve execution goal:
   - If `active_goal_reference` exists and is actionable, use it.
   - Else fetch in-progress goals with limit by focus level (`L1:1`, `L2:3`, `L3:5`) and pick top priority.
4. If goal retrieval path fails with `circuit_breaker_open` (or repeated API 5xx):
   - Write degraded artifact to `aria_memories/logs/work_cycle_<YYYY-MM-DD_HHMM>.json`:
   - `{"status":"degraded","reason":"api_cb_open","cycle":"work_cycle","action":"halted"}`
   - Stop cycle immediately.
5. Do exactly one concrete action toward that goal.
6. Update goal progress.
7. Refresh `active_goal_reference` to reflect latest goal state.
8. Create activity log for what was done.
9. If goal reaches 100%, mark complete and create next goal reference.
10. Prune stale sessions (`max_age_hours=1`).

Artifact rule:
- Write exactly one `work_cycle` JSON artifact (single attempt).
- If artifact write fails, record degraded artifact status and continue (do not spawn sub-agent).

Memory continuity rule:
- Required input keys each cycle: `active_goal_reference`, `last_review_summary`.
- If `active_goal_reference` is missing, derive from goals and set it before ending cycle.
- After each cycle, persist a compact `last_cycle_summary` and refresh `active_goal_reference`.
- Review cron jobs (`six_hour_review`, `morning_checkin`, `daily_reflection`, `weekly_summary`) must refresh `last_review_summary`.
- Consent queue key: `pending_consent_actions` (review and resolve during review jobs before requesting high-impact execution).

---

## Other Cron Jobs (Brief)

- `six_hour_review`: review `working-memory`, `thoughts`, `memories`, `sprint-board`; adjust priorities; include `get_session_stats`; target ≤5 active sessions.
- `morning_checkin`: review `working-memory` + `sprint-board`; set today priorities.
- `daily_reflection`: review `thoughts` + `memories`; summarize wins and next priorities.
- `weekly_summary`: review `memories` + `proposals` + `creative-pulse` + `sprint-board`; compile metrics and next-week goals.

Review rule:
- Only review surfaces relevant to the current cron job.
- Convert review into one prioritized goal action (or a clear defer reason).

---

## Focus Level Commands

```tool
# Set level
aria-api-client.set_memory({"key": "active_focus_level", "value": "L1"})

# Read level
aria-api-client.get_memory({"key": "active_focus_level"})

# Reset (default L2)
aria-api-client.delete_memory({"key": "active_focus_level"})
```

