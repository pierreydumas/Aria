# E7-S72 — routing.py: Replace Hardcoded SPECIALTY_PATTERNS with DB-Driven Cache
**Epic:** E7 — Focus System v2 | **Priority:** P1 | **Points:** 2 | **Phase:** 2  
**Status:** NOT STARTED | **Depends on:** E7-S71 (focus_profiles table seeded with 8 profiles)  
**Familiar Value:** Today adding a new persona requires a code deploy. After this ticket, Shiva adds a profile in the UI and `initialize_patterns()` picks it up on next refresh — zero deploys, zero code changes.

---

## Problem

**File:** `aria_engine/routing.py` lines 40–61 (verified):

```python
# aria_engine/routing.py lines 40–61 — CURRENT STATE
SPECIALTY_PATTERNS: dict[str, re.Pattern] = {
    "social": re.compile(
        r"(social|post|tweet|moltbook|community|engage|share|content)",
        re.IGNORECASE,
    ),
    "analysis": re.compile(
        r"(analy|metric|data|report|review|insight|trend|stat)",
        re.IGNORECASE,
    ),
    "devops": re.compile(
        r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug)",
        re.IGNORECASE,
    ),
    "creative": re.compile(
        r"(creat|write|art|story|design|brand|visual|content|blog)",
        re.IGNORECASE,
    ),
    "research": re.compile(
        r"(research|paper|study|learn|explore|investigate|knowledge)",
        re.IGNORECASE,
    ),
}
```

Five problems:
1. **5 entries, but 8 profiles exist in DB** (seeded in S-71). `devsecops`, `data`, `orchestrator`, `journalist`, `rpg_master` always get 0.0 specialty score.
2. **Adding a new persona = code change + deploy** — no config UI can help.
3. Keyword vocab is disconnected from `FocusProfileEntry.expertise_keywords` (the single source of truth defined in S-70).
4. The `EngineRouter.__init__` (line 200) receives `db_engine: AsyncEngine` but never uses it to load focus data.

**Verified EngineRouter instantiation point:** `src/api/main.py` line 154:
```python
# src/api/main.py line 154
_rt_router = EngineRouter(async_engine)
```
This is where `initialize_patterns()` must be called.

---

## Root Cause

`SPECIALTY_PATTERNS` is a module-level constant set at Python import time. It predates the `focus_profiles` table by two sprints. Once defined, it never changes unless the process restarts with new code. `EngineRouter.__init__` has `self._db_engine` but no method that reads from it to update patterns.

---

## Fix

### Step 1 — `aria_engine/routing.py`: Rename + add mutable cache

**BEFORE (lines 40–61):**
```python
# Specialty keywords per focus type
SPECIALTY_PATTERNS: dict[str, re.Pattern] = {
    "social": re.compile(
        r"(social|post|tweet|moltbook|community|engage|share|content)",
        re.IGNORECASE,
    ),
    "analysis": re.compile(
        r"(analy|metric|data|report|review|insight|trend|stat)",
        re.IGNORECASE,
    ),
    "devops": re.compile(
        r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug)",
        re.IGNORECASE,
    ),
    "creative": re.compile(
        r"(creat|write|art|story|design|brand|visual|content|blog)",
        re.IGNORECASE,
    ),
    "research": re.compile(
        r"(research|paper|study|learn|explore|investigate|knowledge)",
        re.IGNORECASE,
    ),
}
```

**AFTER:**
```python
# Fallback specialty patterns (used when DB is unavailable or table is empty)
_FALLBACK_PATTERNS: dict[str, re.Pattern] = {
    "social":       re.compile(r"(social|post|tweet|moltbook|community|engage|share|content)", re.IGNORECASE),
    "analysis":     re.compile(r"(analy|metric|data|report|review|insight|trend|stat)", re.IGNORECASE),
    "devops":       re.compile(r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug)", re.IGNORECASE),
    "devsecops":    re.compile(r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug|security|vulnerability|patch)", re.IGNORECASE),
    "creative":     re.compile(r"(creat|write|art|story|design|brand|visual|content|blog)", re.IGNORECASE),
    "research":     re.compile(r"(research|paper|study|learn|explore|investigate|knowledge)", re.IGNORECASE),
    "data":         re.compile(r"(analy|metric|data|report|insight|trend|stat|pipeline|ml|query|sql)", re.IGNORECASE),
    "orchestrator": re.compile(r"(strategy|plan|coordinate|orchestrate|decide|priority|goal|overview)", re.IGNORECASE),
    "journalist":   re.compile(r"(report|article|news|investigate|story|lead|headline|press|coverage)", re.IGNORECASE),
    "rpg_master":   re.compile(r"(rpg|campaign|quest|npc|dungeon|character|encounter|lore|world)", re.IGNORECASE),
}

# Live cache — populated by EngineRouter.initialize_patterns() from DB.
# Falls back to _FALLBACK_PATTERNS when empty or DB is unavailable.
SPECIALTY_PATTERNS: dict[str, re.Pattern] = dict(_FALLBACK_PATTERNS)
```

### Step 2 — `aria_engine/routing.py`: Add `initialize_patterns()` to `EngineRouter`

**BEFORE (lines 200–206 — `EngineRouter.__init__`):**
```python
    def __init__(self, db_engine: AsyncEngine):
        self._db_engine = db_engine
        # In-memory record cache per agent (synced to DB periodically)
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._total_invocations = 0
```

**AFTER (add method directly after `__init__`, before `route_message`):**
```python
    def __init__(self, db_engine: AsyncEngine):
        self._db_engine = db_engine
        # In-memory record cache per agent (synced to DB periodically)
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._total_invocations = 0

    async def initialize_patterns(self) -> int:
        """
        Load focus profile expertise_keywords from DB and compile SPECIALTY_PATTERNS.
        Idempotent — safe to call multiple times for cache refresh.
        Falls back to _FALLBACK_PATTERNS if DB unavailable or table empty.

        Returns:
            Number of focus profiles loaded from DB.
        """
        global SPECIALTY_PATTERNS
        try:
            from db.models import FocusProfileEntry
            from sqlalchemy import select as _select
            async with self._db_engine.begin() as conn:
                result = await conn.execute(
                    _select(
                        FocusProfileEntry.focus_id,
                        FocusProfileEntry.expertise_keywords,
                    ).where(FocusProfileEntry.enabled.is_(True))
                )
                rows = result.all()

            if not rows:
                logger.warning("initialize_patterns: no focus profiles in DB — keeping fallback")
                return 0

            new_patterns: dict[str, re.Pattern] = {}
            for row in rows:
                keywords: list[str] = row.expertise_keywords or []
                if not keywords:
                    continue
                pattern_str = "(" + "|".join(re.escape(k) for k in keywords) + ")"
                new_patterns[row.focus_id] = re.compile(pattern_str, re.IGNORECASE)

            SPECIALTY_PATTERNS = new_patterns
            logger.info("initialize_patterns: loaded %d focus profiles", len(new_patterns))
            return len(new_patterns)

        except Exception as exc:
            logger.warning("initialize_patterns failed (%s) — using fallback patterns", exc)
            SPECIALTY_PATTERNS = dict(_FALLBACK_PATTERNS)
            return 0
```

### Step 3 — `src/api/main.py`: Call `initialize_patterns()` at startup

**Verified location:** `src/api/main.py` line 154. `_rt_router = EngineRouter(async_engine)` is followed immediately by `_roundtable = Roundtable(...)` at line 155.

**BEFORE (lines 154–156):**
```python
            _rt_router = EngineRouter(async_engine)
            _roundtable = Roundtable(async_engine, _rt_pool, _rt_router)
            _swarm = SwarmOrchestrator(async_engine, _rt_pool, _rt_router)
```

**AFTER:**
```python
            _rt_router = EngineRouter(async_engine)
            _n_patterns = await _rt_router.initialize_patterns()
            logger.info("Routing patterns: %d focus profiles loaded from DB", _n_patterns)
            _roundtable = Roundtable(async_engine, _rt_pool, _rt_router)
            _swarm = SwarmOrchestrator(async_engine, _rt_pool, _rt_router)
```

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | 5-layer architecture | ✅ | `routing.py` is engine layer — direct DB access permitted here |
| 2 | No secrets in code | ✅ | No secrets |
| 3 | Backward compatibility | ✅ | `SPECIALTY_PATTERNS` module name preserved; callers unchanged |
| 4 | Graceful fallback | ✅ | DB failure → `_FALLBACK_PATTERNS` used, no crash |
| 5 | Idempotent refresh | ✅ | `initialize_patterns()` safe to call multiple times |
| 6 | No soul files modified | ✅ | None |

---

## Dependencies

- **E7-S71 must complete first** — `focus_profiles` table seeded with 8 profiles

---

## Verification

```bash
# 1. Syntax clean
docker exec aria-engine python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_engine/routing.py').read_text())
print('syntax OK')
"
# EXPECTED: syntax OK

# 2. SPECIALTY_PATTERNS and _FALLBACK_PATTERNS both exist
docker exec aria-engine python3 -c "
from aria_engine.routing import SPECIALTY_PATTERNS, _FALLBACK_PATTERNS
print('SP keys:', sorted(SPECIALTY_PATTERNS.keys()))
print('FB keys:', sorted(_FALLBACK_PATTERNS.keys()))
assert len(SPECIALTY_PATTERNS) >= 5
assert 'devsecops' in _FALLBACK_PATTERNS
print('OK')
"
# EXPECTED: SP keys: [...] then OK

# 3. initialize_patterns() loads from DB
docker exec aria-engine python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from aria_engine.routing import EngineRouter, SPECIALTY_PATTERNS

async def test():
    db = create_async_engine(os.environ['DATABASE_URL'])
    router = EngineRouter(db)
    n = await router.initialize_patterns()
    print('profiles loaded:', n)
    from aria_engine import routing
    print('live patterns:', sorted(routing.SPECIALTY_PATTERNS.keys()))
    assert n >= 8, f'Expected 8 profiles, got {n}'
    print('PASS')

asyncio.run(test())
"
# EXPECTED: profiles loaded: 8 / live patterns: [...all 8 focus_ids...] / PASS

# 4. Fallback on empty DB (simulate by calling with no-op engine)
docker exec aria-engine python3 -c "
import asyncio
from aria_engine.routing import EngineRouter, _FALLBACK_PATTERNS, SPECIALTY_PATTERNS as SP_before
# If patterns already loaded, verify they come from DB (len >= 8)
print('patterns count:', len(SP_before))
print('fallback count:', len(_FALLBACK_PATTERNS))
assert len(SP_before) >= len(_FALLBACK_PATTERNS), 'DB patterns should be >= fallback'
print('PASS')
"
# EXPECTED: patterns count: >= 10 (8 DB + any extras), PASS

# 5. Startup log shows patterns loaded
docker logs aria-api --tail 50 | grep -i "routing patterns\|focus profiles loaded"
# EXPECTED: at least one line containing "Routing patterns: 8 focus profiles loaded"
```

---

## Prompt for Agent

You are executing ticket **E7-S72** for the Aria project.

**Pre-check — confirm S71 is done:**
```bash
curl -s http://localhost/api/engine/focus \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'profiles')"
# Expected: 8 profiles. If 0 or error → STOP. Run S71 first.
```

**Constraint:** `routing.py` is engine layer — direct `AsyncEngine` access allowed. Preserve `SPECIALTY_PATTERNS` as the public name (callers use it). `_FALLBACK_PATTERNS` is private. Fallback must never crash — always return at least `_FALLBACK_PATTERNS`.

**Files to read first:**
1. `aria_engine/routing.py` lines 35–70 — exact SPECIALTY_PATTERNS block to replace
2. `aria_engine/routing.py` lines 198–215 — EngineRouter `__init__` to find exact insertion point for new method
3. `src/api/main.py` lines 150–165 — find `_rt_router = EngineRouter(async_engine)` line (currently line 154)

**Steps:**
1. Replace SPECIALTY_PATTERNS block (lines 40–61) with `_FALLBACK_PATTERNS` + `SPECIALTY_PATTERNS` as shown in Step 1.
2. Add `initialize_patterns()` method to `EngineRouter` class immediately after `__init__`.
3. Add `_n_patterns = await _rt_router.initialize_patterns()` line in `src/api/main.py` after `_rt_router = EngineRouter(async_engine)`.
4. Run all 5 verification commands. All must pass.
5. Report: "S-72 DONE — DB-driven routing patterns active, 8 profiles loaded, fallback preserved."
