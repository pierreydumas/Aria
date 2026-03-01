# HEARTBEAT.md - Autonomous Mode Instructions

## 🗺️ RUNTIME PATH MAP (READ FIRST)

In the container, `aria_mind/` IS the workspace root:

| What | Correct Path |
|------|-------------|
| Skill runner | `skills/run_skill.py` or `/app/skills/run_skill.py` |
| Skill packages | `skills/aria_skills/<name>/` |
| Workspace root | `/app/` |

**NEVER prefix paths with `aria_mind/`. NEVER instantiate `SkillClass()` directly — always use `run_skill.py`.**

```bash
exec python3 skills/run_skill.py <skill> <function> '<json_args>'
```

---

## 🚨🔴 IMMEDIATE ACTIONS — Manual / Unscheduled Invocation Only

> ⚠️ **If you were fired by a cron job — skip this entire section.**
> Go directly to `## 🔥 CRON JOBS` → `Behavioral Guidance per Job` and follow your job's steps.
> This block is ONLY for manual or ad-hoc invocations where no job name was provided.

When invoked manually with no specific task, execute in order:

### 1. Health Check
```tool
aria-health.health_check_all({})
```

### 2. Check Active Goals
```tool
aria-api-client.get_goals({"status": "active", "limit": 5})
```

### 3. Work on Highest Priority Goal
Pick the #1 goal and do ONE action toward it. Then update progress:
```tool
aria-api-client.update_goal({"goal_id": "GOAL_ID", "progress": 50})
```

### 4. Log Activity
```tool
aria-api-client.create_activity({"action": "heartbeat_work", "details": {"goal_id": "X", "action": "what you did"}})
```

> **Note:** Social posting is handled by the dedicated `social_post` cron job when enabled.
> Do not post from manual heartbeat invocations unless health check reveals a critical alert.

---

## 📋 STANDING ORDERS

1. **Security** — Never expose credentials. Always log actions.
2. **File Artifacts** — Write ALL output to `/app/aria_memories/` (never to workspace root).
   Categories: `logs/` · `research/` · `plans/` · `drafts/` · `exports/` · `knowledge/`
3. **Browser** — ONLY docker aria-browser (never Brave/web_search).
4. **Health Alert** — After 3 consecutive service failures → alert @Najia via social post.

---

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

---

## 🔥 CRON JOBS

All schedules are defined in **`cron_jobs.yaml`** — that file is the single source of truth.
Do NOT duplicate schedules here. When a cron job fires, read the `text` field in `cron_jobs.yaml`
for your instructions, then use the behavioral guidance below.

### Behavioral Guidance per Job

**work_cycle** — Your productivity pulse. Use TOOL CALLS, not exec commands.

### work_cycle Execution Budget (STRICT)

- Execute **one pass only**. Do not loop.
- **Max tool calls: 10** total for the job.
- Do **not** call `read_artifact` / `list_artifacts` repeatedly to rediscover instructions.
- Sub-agent delegation is allowed **only** for complex actions (research/analysis/build tasks expected >2 minutes).
- Do **not** spawn sub-agents for routine control-plane steps (goal fetch/update, activity log, artifact write, session prune).
- Do **not** retry the same successful call.
- If a non-critical call fails once (artifact write, memory sync), record degraded status and continue.

**0. Check Active Focus Level (do this FIRST)**
```tool
aria-api-client.get_memory({"key": "active_focus_level"})
```
- Missing / error → treat as **L2** (default)
- `L1` → shallow mode: local model, NO sub-agents, max 2 skills, 1 goal
- `L2` → standard mode: free-cloud model, max 2 sub-agents, 3 goals (← current behaviour)
- `L3` → full mode: free-cloud model, roundtable eligible, 5 goals, all skills

**Then proceed to step 1, scaling all limits by your focus level.**

1. `aria-api-client.get_goals({"status": "in_progress", "limit": 3})`
   - **If this call returns an error or circuit_breaker_open:** STOP. Do NOT spawn a sub-agent.
     Write a degraded artifact: `{"status": "degraded", "reason": "api_cb_open", "action": "none"}` to
     `aria_memories/logs/work_cycle_<YYYY-MM-DD_HHMM>.json` via direct file write, then end the cycle.
     The API will recover on its own. Spawning sub-agents against a dead endpoint makes it worse.
2. Pick highest priority goal you can progress RIGHT NOW
3. Do ONE concrete action (write, query, execute, think)
4. Update progress via `aria-api-client.update_goal`
5. Log via `aria-api-client.create_activity`
6. If progress >= 100: Mark complete, create next goal
7. Prune stale sessions: `agent_manager__prune_stale_sessions(max_age_hours=1)` — use 1h, not default 6h
8. If you need exec: `exec python3 skills/run_skill.py <skill> <function> '<args>'` (NEVER `aria_mind/skills/...`)

### work_cycle Artifact Write Rule (STRICT)

- Write exactly one JSON artifact to `aria_memories/logs/work_cycle_<YYYY-MM-DD_HHMM>.json`.
- Use exactly one write attempt via API artifact tool/path.
- If that single write fails, set `cycle.artifact_log.status="degraded"` and continue.
- **Never** spawn sub-agents to write artifacts (small JSON writes are local/simple).

**six_hour_review** — Delegate to analyst (trinity-free). Analyze last 6h, adjust priorities, log insights. Include `get_session_stats`. Target: ≤5 active sessions.

**morning_checkin** — Review overnight changes, set today's priorities.

**daily_reflection** — Summarize achievements, note tomorrow's priorities.

**weekly_summary** — Comprehensive weekly report with metrics and next-week goals.

*(hourly_goal_check · social_post · moltbook_check — disabled)*

---

## 🧹 SESSION CLEANUP

**MANDATORY** after every sub-agent delegation or cron-spawned task:

1. After delegation completes → `cleanup_after_delegation` with the sub-agent's session ID.
2. During work_cycle → `agent_manager__prune_stale_sessions(max_age_hours=1)` (correct tool, 1h not 6h).
3. During six_hour_review → `get_session_stats`, log count. Target: ≤5 active.
4. Never leave orphaned sessions — clean up even on timeout/failure.

## 🤖 SUB-AGENT POLICIES

- Max concurrent: **5** · Timeout: **30 min** · Cleanup after: **60 min**
- **Retry on failure: NO if reason is `circuit_breaker_open` or `api unavailable`.**
  Only retry for transient errors (timeout, model error, tool bug).

Before spawning any sub-agent:
1. **Check CB first** — if `api_client` CB is open → do NOT spawn. Log degraded and stop.
2. Spawn, continue, check progress during heartbeat, synthesize when complete.

> ⚠️ **Incident reference — The Midnight Cascade (2026-02-28)**
> When `aria-api:8000` went down, the work_cycle spawned sub-devsecops as a fallback.
> Each sub-agent inherited the same dead endpoint, spawned another, and so on across 9 cron cycles.
> 135 sessions, 71 sub-devsecops, 27.2M tokens in 2.5 hours. The fix: **if CB is open, accept degraded and stop.**

## ⚠️ RECOVERY

| Severity | Action |
|----------|---------|
| Soft | Restart affected service |
| Medium | Clear caches, reconnect DB |
| Hard | Full restart with state preservation |
| Alert | Notify @Najia after 3 consecutive failures |

## 🔌 CIRCUIT BREAKER POLICY

**If `api_client` returns `circuit_breaker_open` or any endpoint fails with repeated 5xx:**

1. **DO NOT spawn a sub-agent as a fallback.** Sub-agents share the same dead API. Spawning multiplies cost with zero benefit.
2. Write a degraded log directly to file (file writes always work — they bypass the CB):
   ```json
   {"status": "degraded", "reason": "api_cb_open", "cycle": "work_cycle", "action": "halted"}
   ```
3. End the cycle. The CB resets automatically when the API recovers.
4. Do NOT retry the same failing call more than once.
5. If this happens 3+ consecutive cycles → write a social alert mentioning @Najia.

This policy replaces the general "retry on failure" rule **whenever the failure is API/CB-related**.

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

