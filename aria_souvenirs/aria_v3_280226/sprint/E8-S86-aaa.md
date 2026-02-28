# E8-S86 — engine_focus Wiring: Focus Level → work_cycle Adaptive Routing
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P1 | **Points:** 4 | **Phase:** 4  
**Status:** NOT STARTED | **Depends on:** E7-S71 (engine_focus.py CRUD + seed must exist), E8-S78 (HEARTBEAT.md docs)  
**Familiar Value:** This ticket makes the L1/L2/L3 hierarchy real in Python — not just documented in markdown. Without it, Aria reads her focus level but nothing in the Python layer enforces different depth limits. S-86 closes the loop.

---

## Problem

**Three separate gaps, each verified against actual code:**

### Gap 1: `aria_mind/heartbeat.py` `_check_goals()` (line 249)

```python
# aria_mind/heartbeat.py line 249
async def _check_goals(self) -> None:
    """Check active goals and work on the top priority."""
    if not self._mind.cognition or not self._mind.cognition._skills:
        return
    
    try:
        goals_skill = self._mind.cognition._skills.get("goals")
        if goals_skill and goals_skill.is_available:
            actions = await goals_skill.get_next_actions(limit=1)   # ← ALWAYS limit=1
```

This hardcodes `limit=1` regardless of focus level. At L3, Aria should consider 5
active goals to find the optimal one. At L1, `limit=1` is correct.

Additionally, `_check_goals()` has no circuit-breaker check before calling the API.
The HEARTBEAT.md incident note (The Midnight Cascade, 2026-02-28) is a real event —
sub-agents were spawned against a dead API. The Python layer must enforce the same
CB-first rule that HEARTBEAT.md now documents.

### Gap 2: `src/api/routers/engine_focus.py` (does not exist yet — E7-S71 creates it)

After E7-S71 creates the file with GET/POST/PUT/DELETE endpoints, there are no
convenience endpoints for setting the active focus level. The only way to set it
is via `api_client.set_memory({"key": "active_focus_level", "value": "L1"})`.
Adding `POST/GET/DELETE /api/engine/focus/active` closes the loop: Shiva can
toggle focus level from the engine management UI.

### Gap 3: six_hour_review Python delegate call

`aria_mind/heartbeat.py` `_trigger_reflection()` at line 270 calls:
```python
async def _trigger_reflection(self) -> None:
    """Trigger a reflection cycle through cognition."""
    if not self._mind.cognition:
        return
    try:
        reflection = await self._mind.cognition.reflect()
```

This fires on every `_reflection_interval` (6 beats) — equivalent to the `six_hour_review`
cron. It delegates to `cognition.reflect()` with no focus-level awareness. At L3, this
should trigger a roundtable (via the engine API). At L2/L1, current behavior is correct.

---

## Root Cause

`aria_mind/heartbeat.py` was written before focus levels existed. The Python heartbeat
loop (`_check_goals`, `_trigger_reflection`) predates E7. These methods make no reference
to `active_focus_level` memory key and have no knowledge of L1/L2/L3. The E7 CRUD API
(S-71) adds the data layer but nothing wires it to the Python execution paths.

---

## Fix

### Change 1 — `aria_mind/heartbeat.py`: Add `_get_focus_level()` helper

**File:** `aria_mind/heartbeat.py`  
**Insert after the `__init__` method** (after line 60, before `@property def is_healthy`):

**BEFORE (line 64 area — `@property def is_healthy`):**
```python
    @property
    def is_healthy(self) -> bool:
        """Check if heartbeat is functioning."""
```

**AFTER:**
```python
    async def _get_focus_level(self) -> str:
        """
        Read active_focus_level from memory store.
        Returns 'L1', 'L2', or 'L3'. Defaults to 'L2' on error or missing key.

        L1 = shallow (local model, no sub-agents, 1 goal)
        L2 = standard (free cloud, max 2 sub-agents, 3 goals)  ← default
        L3 = deep (free cloud, roundtable eligible, 5 goals)
        """
        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                return "L2"
            result = await api.get_memory(key="active_focus_level")
            level = (result or {}).get("value", "L2")
            if level not in ("L1", "L2", "L3"):
                return "L2"
            return level
        except Exception:
            return "L2"  # safe default on any failure

    # Focus routing config — defines limits per level
    FOCUS_ROUTING: dict[str, dict] = {
        "L1": {"max_goals": 1, "sub_agents": False, "roundtable": False},
        "L2": {"max_goals": 3, "sub_agents": True,  "roundtable": False},
        "L3": {"max_goals": 5, "sub_agents": True,  "roundtable": True},
    }

    @property
    def is_healthy(self) -> bool:
        """Check if heartbeat is functioning."""
```

### Change 2 — `aria_mind/heartbeat.py`: Patch `_check_goals()` with focus-level scaling

**File:** `aria_mind/heartbeat.py`  
**Lines 249–266** (the `_check_goals` method)

**BEFORE:**
```python
    async def _check_goals(self) -> None:
        """Check active goals and work on the top priority."""
        if not self._mind.cognition or not self._mind.cognition._skills:
            return
        
        try:
            goals_skill = self._mind.cognition._skills.get("goals")
            if goals_skill and goals_skill.is_available:
                actions = await goals_skill.get_next_actions(limit=1)
                if actions.success and actions.data:
                    next_action = actions.data
                    if isinstance(next_action, list) and next_action:
                        self.logger.info(f"🎯 Goal work: {str(next_action[0])[:80]}")
        except Exception as e:
            self.logger.debug(f"Goal check skipped: {e}")
```

**AFTER:**
```python
    async def _check_goals(self) -> None:
        """Check active goals and work on the top priority — scaled by focus level."""
        if not self._mind.cognition or not self._mind.cognition._skills:
            return

        # Check circuit breaker FIRST (lesson from The Midnight Cascade 2026-02-28)
        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                self.logger.debug("Goal check skipped: api_client unavailable (CB open?)")
                self._write_degraded_log("_check_goals", "api_client_unavailable")
                return
        except Exception as e:
            self.logger.debug(f"Goal check skipped: api_client error {e}")
            return

        # Read focus level — determines how many goals to consider
        focus_level = await self._get_focus_level()
        focus_cfg = self.FOCUS_ROUTING.get(focus_level, self.FOCUS_ROUTING["L2"])
        max_goals = focus_cfg["max_goals"]

        self.logger.debug(f"💓 Goal check — focus level: {focus_level}, max_goals: {max_goals}")

        try:
            goals_skill = self._mind.cognition._skills.get("goals")
            if goals_skill and goals_skill.is_available:
                actions = await goals_skill.get_next_actions(limit=max_goals)
                if actions.success and actions.data:
                    next_action = actions.data
                    if isinstance(next_action, list) and next_action:
                        self.logger.info(
                            f"🎯 Goal work [focus={focus_level}]: "
                            f"{str(next_action[0])[:80]}"
                        )
        except Exception as e:
            self.logger.debug(f"Goal check skipped: {e}")

    def _write_degraded_log(self, cycle: str, reason: str) -> None:
        """Write a degraded-mode log to aria_memories/logs/ when API is unavailable."""
        import json
        from pathlib import Path
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        log_dir = Path("aria_memories/logs")
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{cycle}_{ts}.json"
            log_file.write_text(json.dumps({
                "status": "degraded",
                "reason": reason,
                "cycle": cycle,
                "action": "halted",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            pass  # File write failure shouldn't crash the heartbeat
```

### Change 3 — `aria_mind/heartbeat.py`: Patch `_trigger_reflection()` for L3 roundtable

**File:** `aria_mind/heartbeat.py`  
**Lines 270–280** (the `_trigger_reflection` method)

**BEFORE:**
```python
    async def _trigger_reflection(self) -> None:
        """Trigger a reflection cycle through cognition."""
        if not self._mind.cognition:
            return
        
        try:
            reflection = await self._mind.cognition.reflect()
            self.logger.info(f"🪞 Reflection complete ({len(reflection)} chars)")
        except Exception as e:
            self.logger.debug(f"Reflection skipped: {e}")
```

**AFTER:**
```python
    async def _trigger_reflection(self) -> None:
        """
        Trigger reflection cycle — six_hour_review equivalent.
        At L3: trigger roundtable (analyst + creator + devops) via engine API.
        At L2/L1: standard single-agent cognition.reflect() (existing behaviour).
        """
        if not self._mind.cognition:
            return

        focus_level = await self._get_focus_level()

        if focus_level == "L3":
            # L3: roundtable for comprehensive six_hour_review
            try:
                from aria_skills.api_client import get_api_client
                api = await get_api_client()
                if api:
                    result = await api.post(
                        "/engine/roundtable",
                        json={
                            "topic": "6-hour system review: goals, content, health, errors",
                            "agent_ids": ["analyst", "creator", "devops"],
                            "rounds": 1,
                            "timeout": 240,
                        },
                    )
                    self.logger.info(
                        f"🎯 Roundtable six_hour_review dispatched "
                        f"(focus=L3): session_id={result.get('session_id', '?')}"
                    )
                    return
            except Exception as e:
                self.logger.warning(f"Roundtable dispatch failed, falling back to reflect(): {e}")

        # L1/L2 (or L3 fallback): standard reflection
        try:
            reflection = await self._mind.cognition.reflect()
            self.logger.info(f"🪞 Reflection complete [focus={focus_level}] ({len(reflection)} chars)")
        except Exception as e:
            self.logger.debug(f"Reflection skipped: {e}")
```

### Change 4 — `src/api/routers/engine_focus.py`: Add active focus level endpoints

**File:** `src/api/routers/engine_focus.py`  
**Depends on:** E7-S71 creating this file first  
**Add these 3 endpoints at the bottom of the file** (after the existing DELETE endpoint):

```python
# ── Active Focus Level convenience endpoints ──────────────────────────────────
# These are thin wrappers over the memory store.
# They enable the engine_focus.html UI (S-76) and Shiva's CLI to toggle
# focus level without knowing the memory key name.

class ActiveFocusRequest(BaseModel):
    level: str  # "L1" | "L2" | "L3"


class ActiveFocusResponse(BaseModel):
    level: str
    config: dict


FOCUS_LEVEL_CONFIG: dict[str, dict] = {
    "L1": {"max_goals": 1, "sub_agents": False, "roundtable": False, "model_tier": "local"},
    "L2": {"max_goals": 3, "sub_agents": True,  "roundtable": False, "model_tier": "free_cloud"},
    "L3": {"max_goals": 5, "sub_agents": True,  "roundtable": True,  "model_tier": "free_cloud"},
}


@router.post("/active", response_model=ActiveFocusResponse, status_code=200)
async def set_active_focus(
    body: ActiveFocusRequest,
    db: AsyncSession = Depends(get_db),
) -> ActiveFocusResponse:
    """Set the active focus level (stored as memory key)."""
    if body.level not in FOCUS_LEVEL_CONFIG:
        raise HTTPException(status_code=422, detail=f"level must be L1, L2, or L3")
    # Store via memory key — this is the single source of truth read by heartbeat.py
    from db.models import MemoryEntry
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(MemoryEntry).values(
        key="active_focus_level",
        value=body.level,
        category="focus",
    ).on_conflict_do_update(
        index_elements=["key"],
        set_={"value": body.level, "updated_at": datetime.now(timezone.utc)},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("active focus level set to %s", body.level)
    return ActiveFocusResponse(level=body.level, config=FOCUS_LEVEL_CONFIG[body.level])


@router.get("/active", response_model=ActiveFocusResponse)
async def get_active_focus(
    db: AsyncSession = Depends(get_db),
) -> ActiveFocusResponse:
    """Get the currently active focus level."""
    from db.models import MemoryEntry
    from sqlalchemy import select as _select
    result = await db.execute(
        _select(MemoryEntry).where(MemoryEntry.key == "active_focus_level")
    )
    row = result.scalars().first()
    level = row.value if row else "L2"  # default
    if level not in FOCUS_LEVEL_CONFIG:
        level = "L2"
    return ActiveFocusResponse(level=level, config=FOCUS_LEVEL_CONFIG[level])


@router.delete("/active", status_code=200)
async def reset_active_focus(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reset focus level to L2 default (delete the memory key)."""
    from db.models import MemoryEntry
    from sqlalchemy import delete as _delete
    await db.execute(_delete(MemoryEntry).where(MemoryEntry.key == "active_focus_level"))
    await db.commit()
    logger.info("active focus level reset to L2 default")
    return {"level": "L2", "reset": True}
```

**Note on `MemoryEntry` model:** Before implementing, verify the actual ORM class name
for the memories table by running:
```bash
grep -n "class.*Memory\|__tablename__.*memor" /Users/najia/aria/src/api/db/models.py | head -5
```
Use the actual class name. If the table is accessed differently (e.g. via a raw INSERT),
adapt accordingly while preserving the memory key `active_focus_level`.

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | heartbeat.py reads memory via api_client skill (correct layer). engine_focus endpoints read/write DB via ORM (correct layer). |
| 2 | `.env` for secrets | ✅ | No secrets in scope |
| 3 | `models.yaml` SoT | ✅ | `FOCUS_LEVEL_CONFIG` uses tier labels (`local`, `free_cloud`) not hardcoded model IDs |
| 4 | Docker-first testing | ✅ | All verification via `docker exec` |
| 5 | `aria_memories` only writable | ✅ | `_write_degraded_log()` writes to `aria_memories/logs/` — correct path |
| 6 | No soul modification | ✅ | heartbeat.py + engine_focus.py — no soul/ files touched |

---

## Dependencies

- **E7-S71 MUST complete first** — `src/api/routers/engine_focus.py` must exist for Change 4. Also needs `MemoryEntry` ORM model from `src/api/db/models.py` (already exists — verified).
- **E7-S70 MUST complete first** — Focus profiles in DB enable the full context.
- **E8-S78 should be done first** — S-78 establishes L1/L2/L3 behavior docs. S-86's FOCUS_ROUTING dict must match S-78's definitions exactly. Cross-check before merging.
- **E7-S75** (focus-aware roundtable auto-select) — S-86 triggers a roundtable; S-75 improves how agents are selected for that roundtable. Independent but complementary.

---

## Verification

```bash
# 1. _get_focus_level() added to heartbeat.py
grep -n "_get_focus_level\|FOCUS_ROUTING" /Users/najia/aria/aria_mind/heartbeat.py
# EXPECTED: ≥ 2 matches (_get_focus_level definition + FOCUS_ROUTING dict)

# 2. _check_goals() reads focus level and scales max_goals
grep -n "focus_level\|max_goals" /Users/najia/aria/aria_mind/heartbeat.py
# EXPECTED: ≥ 4 matches

# 3. _write_degraded_log() exists
grep -n "_write_degraded_log" /Users/najia/aria/aria_mind/heartbeat.py
# EXPECTED: ≥ 2 matches (definition + call in _check_goals)

# 4. Syntax clean
docker exec aria-engine python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_mind/heartbeat.py').read_text())
print('heartbeat.py syntax OK')
"
# EXPECTED: heartbeat.py syntax OK

# 5. Active focus endpoints added (after E7-S71 creates the file)
grep -n "active_focus\|/active" /Users/najia/aria/src/api/routers/engine_focus.py
# EXPECTED: ≥ 6 matches (POST/GET/DELETE + body class + response class)

# 6. Syntax clean for engine_focus.py
docker exec aria-api python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('src/api/routers/engine_focus.py').read_text())
print('engine_focus.py syntax OK')
"
# EXPECTED: engine_focus.py syntax OK

# 7. POST /api/engine/focus/active sets level
docker exec aria-api curl -s -X POST http://localhost:8000/api/engine/focus/active \
  -H 'Content-Type: application/json' \
  -d '{"level": "L1"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['level'])"
# EXPECTED: L1

# 8. GET /api/engine/focus/active reads back
docker exec aria-api curl -s http://localhost:8000/api/engine/focus/active \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['level'], d['config']['max_goals'])"
# EXPECTED: L1 1

# 9. DELETE resets to L2
docker exec aria-api curl -s -X DELETE http://localhost:8000/api/engine/focus/active \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['level'], d['reset'])"
# EXPECTED: L2 True

# 10. Degraded log is written to correct path on api_client failure
docker exec aria-engine python3 -c "
import asyncio
from aria_mind.heartbeat import Heartbeat

class FakeMind:
    cognition = None
    soul = None
    memory = None

hb = Heartbeat(FakeMind())
hb._write_degraded_log('test_cycle', 'test_reason')
import pathlib
logs = list(pathlib.Path('aria_memories/logs').glob('test_cycle_*.json'))
print('degraded log written:', len(logs) > 0)
"
# EXPECTED: degraded log written: True
```

---

## Prompt for Agent

You are executing ticket **E8-S86** for the Aria project.

**Prerequisites — verify BEFORE starting:**
```bash
# E7-S71 must be done:
test -f /Users/najia/aria/src/api/routers/engine_focus.py && echo "S71 done" || echo "WAIT — run S71 first"
# E7-S70 must be done:
grep -n "FocusProfileEntry" /Users/najia/aria/src/api/db/models.py | head -3
# EXPECTED: FocusProfileEntry class definition found
```
If either check fails, STOP and execute E7-S70 + E7-S71 first.

**Files to read first:**
1. `aria_mind/heartbeat.py` lines 60–290 (full `__init__` through `_trigger_reflection`)
2. `src/api/routers/engine_focus.py` — whatever E7-S71 created (read in full)
3. `src/api/db/models.py` lines 1–50 (imports to understand MemoryEntry class name)
4. `aria_mind/HEARTBEAT.md` S-78 section on L1/L2/L3 to confirm FOCUS_ROUTING matches

**Constraints to verify:**
- Constraint 1: heartbeat.py reads focus via `api_client.get_memory()` call (skill layer) — not direct DB access.
- Constraint 5: `_write_degraded_log()` writes only to `aria_memories/logs/` — verify path is correct inside container (is it `/app/aria_memories/logs/` or `aria_memories/logs/`?).

**Exact steps:**

1. Read `aria_mind/heartbeat.py` lines 60–70 to find exact insertion point for `_get_focus_level()`.

2. Add `_get_focus_level()` helper + `FOCUS_ROUTING` class variable as specified in Change 1.

3. Replace `_check_goals()` method (find exact current content, replace with Change 2 content).

4. Replace `_trigger_reflection()` method (find exact current content, replace with Change 3 content).

5. Add `_write_degraded_log()` helper immediately after `_check_goals()` (it is referenced from `_check_goals()`).

6. Open `src/api/routers/engine_focus.py` and append Change 4 (active focus endpoints). First verify the `MemoryEntry` ORM class name:
   ```bash
   grep -n "class.*Memor" /Users/najia/aria/src/api/db/models.py
   ```
   Use the actual class name.

7. Run all 10 verification commands in order. Fix any failures before proceeding to the next.
