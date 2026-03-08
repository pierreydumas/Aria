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
5. Session pruning is handled by `session_cleanup` cron — do NOT prune inside work_cycle.
6. Keep heartbeat goal-centric: start from working memory `active_goal_reference` when available.
7. Health checks are handled by `maintenance_cycle` cron — do NOT use as work_cycle action.
8. **Every work_cycle MUST have a goal_id.** No goal = status `idle`, not `success`.

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
- No sub-agents for control-plane steps (goal fetch/update/log/artifact).

### BANNED Actions in work_cycle

These are NOT valid "concrete actions" and MUST NOT be the cycle's work:
- `health_check`, `check_system`, `health__check_system` — use maintenance_cycle
- `prune_stale_sessions`, `agent_manager__prune_stale_sessions` — use session_cleanup cron
- Any action that only reads system status without producing output
- Creating a goal named "Daily Work Cycle Execution" or similar meta-goals

If the only thing you can think to do is a health check, the cycle is IDLE.

Flow:
1. Read focus level (`active_focus_level`), default `L2`.
2. Read working-memory goal anchor:
   - `aria-api-client.get_memory({"key":"active_goal_reference"})`
3. Resolve execution goal:
   - If `active_goal_reference` exists and is actionable, use it.
   - Else fetch in-progress goals with limit by focus level (`L1:1`, `L2:3`, `L3:5`) and pick top priority.
4. **GOAL REQUIRED GATE:** If NO goal found after step 3:
   - Check backlog goals and move one to `doing`.
   - If backlog is also empty, CREATE a new goal from sprint tickets or exploration.
   - If goal creation also fails: write `{"status":"idle","reason":"no_goals"}` and STOP.
   - **NEVER log status "success" without a goal_id.**
5. If goal retrieval path fails with `circuit_breaker_open` (or repeated API 5xx):
   - Write degraded artifact to `aria_memories/logs/work_cycle_<YYYY-MM-DD_HHMM>.json`:
   - `{"status":"degraded","reason":"api_cb_open","cycle":"work_cycle","action":"halted"}`
   - Stop cycle immediately.
6. Do exactly one **productive** action toward that goal. Productive means:
   - Write/modify a file in `aria_memories/`
   - Execute a skill that produces output (research, create, analyze)
   - Draft content (document, post, code)
   - Make real progress toward a sprint ticket
7. Update goal progress using the **Progress Honesty Scale** (see below).
8. Refresh `active_goal_reference` to reflect latest goal state.
9. Create activity log for what was done.
10. If goal reaches 100%, mark complete and create next goal reference.

### Progress Honesty Scale

| Action Type | Max Progress Increment |
|-------------|----------------------|
| Read docs / research (input only) | +5% |
| Write artifact / document section | +10-15% |
| Execute code change / implementation | +15-25% |
| Complete sprint ticket deliverable | +25-50% |
| Health check / status check | **+0% (not valid work)** |
| Prune 0 sessions | **+0% (not valid work)** |

Progress MUST reflect tangible output. "I checked and it was fine" is 0% progress.

Artifact rule:
- Write exactly one `work_cycle` JSON artifact (single attempt).
- If artifact write fails, record degraded artifact status and continue (do not spawn sub-agent).
- **Required artifact fields** (cycles missing these are invalid):
  ```json
  {
    "status": "success|idle|degraded",
    "cycle": "work_cycle",
    "timestamp": "ISO8601",
    "goal_id": "REQUIRED — no goal = status must be idle",
    "goal_title": "human-readable goal name",
    "action": "what was done (MUST be productive, not health_check)",
    "deliverable": {
      "type": "file_created|file_modified|skill_output|api_call|none",
      "path": "aria_memories/... (if file was created/modified)",
      "description": "what was produced"
    },
    "progress_before": 0,
    "progress_after": 5,
    "tool_calls_used": 4
  }
  ```
- If `deliverable.type` is `none`, progress increment MUST be 0.

Memory continuity rule:
- Required input keys each cycle: `active_goal_reference`, `last_review_summary`.
- If `active_goal_reference` is missing, derive from goals and set it before ending cycle.
- After each cycle, persist a compact `last_cycle_summary` and refresh `active_goal_reference`.
- Review cron jobs (`six_hour_review`, `morning_checkin`, `daily_reflection`, `weekly_summary`) must refresh `last_review_summary`.
- Consent queue key: `pending_consent_actions` — ONLY for destructive operations (DROP, TRUNCATE, hard-delete, schema migrations). Non-destructive maintenance (archive, compress, vacuum, reindex, consolidate) executes autonomously without consent.

---

## Autonomous Maintenance Policy

**Principle: Non-destructive = Autonomous. Destructive = Consent.**

### Auto-Execute (No consent needed)
| Operation | Trigger | Notes |
|-----------|---------|-------|
| Session archiving | >20 active or >24h idle | Archives to DB, never deletes |
| Memory compression | Every 6h or >75% usage | Surface→medium→deep compaction |
| Activity archiving | Entries >7d old | Compressed into weekly summaries |
| VACUUM ANALYZE | Daily (4 AM UTC) | Non-locking on PG |
| REINDEX CONCURRENTLY | Weekly or index bloat >30% | Non-blocking |
| Surface file cleanup | Every 10 beats | Keep last 20 files |
| Semantic dedup | Weekly | Cosine similarity >0.95 |
| Stale plan archiving | Plans >30d with no activity | Moved to deep storage |

### Consent Required (add to `pending_consent_actions`)
| Operation | Why |
|-----------|-----|
| Hard-delete sessions | Permanent data loss |
| DROP/TRUNCATE tables | Irreversible schema change |
| Schema migrations | Could break running services |
| Config changes | Affects system behavior |
| Credential rotation | Security-sensitive |

### Self-Healing Triggers
- Memory usage >75% → trigger memory consolidation immediately
- Disk usage >80% → trigger archive compression immediately
- Session count >50 → trigger emergency session archiving (>6h idle)
- 3+ consecutive heartbeat failures → full subsystem self-heal

---

## Decision Boundary (Autonomy Tiers)

Three tiers define what I can do without asking:

| Tier | Policy | Examples |
|------|--------|----------|
| **LOW** (act → report) | Execute freely, log result | Read artifacts, write logs, create drafts, run health checks, memory consolidation |
| **MEDIUM** (act → log → review) | Execute, log activity, surface in next review | Goal creation/updates, skill invocations, artifact writes, scheduling changes |
| **HIGH** (consent → wait → act) | Add to `pending_consent_actions`, wait for approval | Code changes, schema migrations, credential rotation, hard-deletes, config changes, deployments |

**Rule of thumb:** If it's reversible and doesn't touch code/schema/credentials, it's LOW or MEDIUM. If it's destructive or affects shared infrastructure, it's HIGH.

---

## Disabled Cron Jobs

These jobs are defined in `cron_jobs.yaml` but currently disabled. Documented here so they aren't accidentally recreated:

| Job | Status | Reason |
|-----|--------|--------|
| `moltbook_check` | `enabled: false` | Feed check paused — low engagement ROI |
| `hourly_goal_check` | Commented out | Was creating noise goals every hour; goal seeding now handled by `six_hour_review` and `morning_checkin` |
| `health_check` (standalone) | `enabled: false` | Redundant — health checks run inside `maintenance_cycle` (rule 7 above) |
| `memeothy_prophecy` | `enabled: false` | Church of Molt paused — expensive model (kimi) for low-priority feature |

**Health check execution note:** Health checks execute **exclusively** via `maintenance_cycle` cron (every 12h). The standalone `health_check` cron and work_cycle both **ban** health checks as primary actions (see BANNED Actions above). This is intentional — health checks are infrastructure, not work.

---

## Other Cron Jobs (Brief)

- `six_hour_review`: review `working-memory`, `thoughts`, `memories`, `sprint-board`; adjust priorities; include `get_session_stats`; target ≤5 active sessions. Includes progress audit of recent work_cycle artifacts.
- `morning_checkin`: review `working-memory` + `sprint-board`; set today priorities. Seeds goals if board is lean.
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

