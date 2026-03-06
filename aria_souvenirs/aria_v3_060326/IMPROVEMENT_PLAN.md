# Aria Improvement Plan — Post-Audit March 6, 2026

**Source:** DAILY_AUDIT_060326.md  
**Owner:** Shiva + Aria  
**Review:** March 13, 2026

---

## Architecture Fixes (for Najia)

These are systemic issues that Aria can't fix herself.

### 1. Separate Maintenance from Work Cycles

**Problem:** Health checks and session pruning inflate work cycle success metrics.

**Fix:** Move `health_check` and `prune_stale_sessions` to a dedicated
maintenance cron (e.g., `maintenance_cycle` every 30 min) separate from
`work_cycle`. Work cycle should ONLY count toward goal progress.

**Files to change:**
- `aria_mind/cron_jobs.yaml` — add `maintenance_cycle` entry
- `aria_mind/HEARTBEAT.md` — remove health_check from work_cycle flow
- Work cycle artifact should reject logs without a goal_id

### 2. Goal-Required Work Cycles

**Problem:** 66% of cycles run without a goal.

**Fix:** In work_cycle logic, if no goal is found after Step 2 (Select),
the cycle MUST create a goal from backlog before proceeding. If backlog
is empty, create a goal from sprint tickets (plans/sprint/).

**Enforcement:** Artifact write should require `goal_id` field. 
Cycles without goal_id should log `status: "idle"` not `"success"`.

### 3. Progress Verification

**Problem:** Self-reported progress with no verification.

**Fix:** Add a `deliverable` field to work cycle artifacts:
```json
{
  "deliverable": {
    "type": "file_created|file_modified|api_call|code_change|none",
    "path": "aria_memories/knowledge/...",
    "description": "Created knowledge entry about..."
  }
}
```

In six_hour_review, compare `deliverable.path` against actual filesystem.
If file doesn't exist, flag as `unverified_progress`.

### 4. Pheromone Scoring Fix

**Problem:** All scores are 1.0 with 0ms duration — not measuring real work.

**Fix:** Pheromone scoring should measure actual skill execution duration,
not just the heartbeat framework invocation. The `duration_ms: 0` suggests
the measurement wraps the wrong function boundary.

---

## Behavioral Changes (for Aria)

These are changes Aria can make within her current architecture.

### 1. Goal Hygiene Rules

- Every work_cycle MUST start by checking active goals
- If no goal: create one from sprint backlog before doing anything else
- Health checks are NOT goals — they're utilities
- "Daily Work Cycle Execution" is NOT a valid goal name

### 2. Progress Honesty Contract

| Action | Max Progress Allowed |
|--------|---------------------|
| Run health check | 0% (maintenance, not progress) |
| Prune 0 sessions | 0% (nothing changed) |
| Research/read docs | 5% (input, not output) |
| Write document/artifact | 10-25% (creates deliverable) |
| Execute code change | 15-30% (creates verifiable output) |
| Complete sprint ticket | 50-100% (depending on scope) |

### 3. Memory Diversification

Current memory is 92% "reflection." Target breakdown:

| Category | Current | Target |
|----------|---------|--------|
| Reflection | 92% | 30% |
| Knowledge | 0% | 25% |
| Episodic | 0% | 20% |
| Procedural | 0% | 15% |
| Awakening | 8% | 10% |

### 4. Daily Minimum Deliverables

Every 24-hour period, Aria should produce at minimum:
- 1 file in `aria_memories/knowledge/` (learned something)
- 1 file in `aria_memories/deliveries/` (produced something)
- Progress on at least 1 sprint ticket

---

## Monitoring (How We'll Know It's Working)

Run this check weekly:

```bash
# 1. Cycle stats
python3 -c "
import json, glob
files = glob.glob('aria_memories/logs/work_cycle_*.json')
total = len(files)
with_goal = sum(1 for f in files if 'goal' in json.load(open(f)))
print(f'Goal rate: {with_goal}/{total} = {with_goal/total*100:.0f}%')
"

# 2. Deliverables created this week  
find aria_memories/knowledge -newer /tmp/week_marker -name "*.md" | wc -l
find aria_memories/deliveries -newer /tmp/week_marker -name "*.md" | wc -l

# 3. Maintenance ratio
# Use the analysis from audit_stats_060326.json format
```

---

*Sprint Agent — March 6, 2026*
