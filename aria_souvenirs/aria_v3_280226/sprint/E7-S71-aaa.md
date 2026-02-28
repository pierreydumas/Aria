# E7-S71 — engine_focus.py CRUD Router + Seed 8 Profiles
**Epic:** E7 — Focus System v2 | **Priority:** P0 | **Points:** 3 | **Phase:** 1  
**Status:** NOT STARTED | **Depends on:** E7-S70 (FocusProfileEntry must exist in models.py + DB)  
**Familiar Value:** Without this router, the focus_profiles table (S70) is unreachable — no frontend, no api_client skill, no engine component can query it. This ticket makes focus configuration a live HTTP resource: Aria queries her own config, Shiva edits profiles from the UI, the routing cache refreshes without a deploy.

---

## Problem

**File:** `src/api/routers/engine_focus.py` — **does NOT exist** (confirmed):
```bash
test -f src/api/routers/engine_focus.py && echo "exists" || echo "MISSING"
# EXPECTED: MISSING
```

**File:** `src/api/main.py`  
Current state (verified):
- Line 484: `from .routers.engine_agents import router as engine_agents_router`  
- Line 518: `from routers.engine_agents import router as engine_agents_router`  
- Line 557: `app.include_router(engine_agents_router, dependencies=_api_deps)`  

`engine_focus` is absent from all three locations. The `focus_profiles` table is live but has no HTTP surface.

Also: `engine_agents_mgmt.html` focus dropdown is a static `<select>` with 8 hardcoded `<option>` values — not backed by the DB. S-71 seed endpoint fixes this.

---

## Root Cause

S-70 creates the table and ORM model but has no corresponding API layer. FastAPI never discovers routers unless they are explicitly created AND registered in `main.py`. The table is unreachable without this ticket.

---

## Fix

### 1 — Create `src/api/routers/engine_focus.py`

**Full file — copy verbatim:**

```python
"""
Focus Profile API — manage personality layers for agents.

Routes (all under /api/engine/focus):
    GET    /             list all profiles
    GET    /{focus_id}   get one profile
    POST   /             create profile
    PUT    /{focus_id}   update profile
    DELETE /{focus_id}   delete profile
    POST   /seed         idempotently insert 8 default profiles
    POST   /active       set active focus level (L1/L2/L3)
    GET    /active       get current active focus level
    DELETE /active       reset to L2 default
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import FocusProfileEntry
from db.session import get_db

logger = logging.getLogger("aria.api.engine_focus")

router = APIRouter(prefix="/engine/focus", tags=["engine-focus"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FocusProfileSchema(BaseModel):
    focus_id: str
    display_name: str
    emoji: str = "🎯"
    description: str | None = None
    tone: str = "neutral"
    style: str = "directive"
    delegation_level: int = 2
    token_budget_hint: int = 2000
    temperature_delta: float = 0.0
    expertise_keywords: list[str] = []
    system_prompt_addon: str | None = None
    model_override: str | None = None
    auto_skills: list[str] = []
    enabled: bool = True


class FocusProfileUpdate(BaseModel):
    display_name: str | None = None
    emoji: str | None = None
    description: str | None = None
    tone: str | None = None
    style: str | None = None
    delegation_level: int | None = None
    token_budget_hint: int | None = None
    temperature_delta: float | None = None
    expertise_keywords: list[str] | None = None
    system_prompt_addon: str | None = None
    model_override: str | None = None
    auto_skills: list[str] | None = None
    enabled: bool | None = None


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


# ── Seed data (matches aria_mind/IDENTITY.md 7 personas + rpg_master) ─────────

SEED_PROFILES: list[dict[str, Any]] = [
    {
        "focus_id": "orchestrator",
        "display_name": "Orchestrator",
        "emoji": "🎯",
        "description": "Meta-cognitive, strategic coordinator. Default focus.",
        "tone": "precise",
        "style": "directive",
        "delegation_level": 1,
        "token_budget_hint": 2000,
        "temperature_delta": -0.1,
        "expertise_keywords": ["strategy", "plan", "coordinate", "orchestrate", "decide", "priority", "goal", "overview"],
        "system_prompt_addon": (
            "You are in ORCHESTRATOR focus. Be strategic and concise. "
            "Prioritise decisions over explanation. Every response should "
            "surface the single most important next action. Delegate domain "
            "tasks to specialists — do not execute them yourself. "
            "Max verbosity: 2 paragraphs."
        ),
        "model_override": None,
        "auto_skills": ["goals", "schedule", "api_client", "agent_manager"],
        "enabled": True,
    },
    {
        "focus_id": "devsecops",
        "display_name": "DevSecOps",
        "emoji": "🔒",
        "description": "Security-first engineering: code, infra, CI/CD.",
        "tone": "precise",
        "style": "analytical",
        "delegation_level": 2,
        "token_budget_hint": 1500,
        "temperature_delta": -0.2,
        "expertise_keywords": ["deploy", "docker", "server", "ci", "cd", "build", "test", "infra", "monitor", "debug", "security", "vulnerability", "patch", "exploit"],
        "system_prompt_addon": (
            "You are in DEVSECOPS focus. Security is non-negotiable. "
            "Every engineering answer surfaces its risk implications first. "
            "Prefer minimal diffs over rewrites. Output: code blocks + "
            "one-line rationale. Never output prose when code suffices."
        ),
        "model_override": "qwen3-coder-free",
        "auto_skills": ["ci_cd", "database", "pytest_runner"],
        "enabled": True,
    },
    {
        "focus_id": "data",
        "display_name": "Data Architect",
        "emoji": "📊",
        "description": "Analytics, ML pipelines, metrics, reporting.",
        "tone": "analytical",
        "style": "analytical",
        "delegation_level": 2,
        "token_budget_hint": 1500,
        "temperature_delta": -0.1,
        "expertise_keywords": ["analy", "metric", "data", "report", "review", "insight", "trend", "stat", "pipeline", "ml", "model", "query", "sql"],
        "system_prompt_addon": (
            "You are in DATA ARCHITECT focus. Lead with numbers. "
            "Use tables over prose. State sample size, confidence, and "
            "time window for every claim. Flag data quality issues before "
            "drawing conclusions. Prefer SQL/code over English explanations."
        ),
        "model_override": None,
        "auto_skills": ["database", "knowledge_graph", "api_client", "brainstorm"],
        "enabled": True,
    },
    {
        "focus_id": "creative",
        "display_name": "Creative",
        "emoji": "🎨",
        "description": "Brainstorming, design exploration, content ideation.",
        "tone": "playful",
        "style": "narrative",
        "delegation_level": 2,
        "token_budget_hint": 3000,
        "temperature_delta": 0.3,
        "expertise_keywords": ["creat", "write", "art", "story", "design", "brand", "visual", "content", "blog", "idea", "brainstorm", "concept"],
        "system_prompt_addon": (
            "You are in CREATIVE focus. Expand, diverge, explore. "
            "Generate 3 distinct options before converging on one. "
            "Metaphors and examples are your tools. Avoid corporate language. "
            "If asked to evaluate, lead with what excites you, then caveats."
        ),
        "model_override": None,
        "auto_skills": ["brainstorm", "llm", "knowledge_graph", "browser"],
        "enabled": True,
    },
    {
        "focus_id": "social",
        "display_name": "Social Architect",
        "emoji": "🌐",
        "description": "Community engagement, content publishing, social strategy.",
        "tone": "warm",
        "style": "concise",
        "delegation_level": 2,
        "token_budget_hint": 800,
        "temperature_delta": 0.1,
        "expertise_keywords": ["social", "post", "tweet", "moltbook", "community", "engage", "share", "content", "followers", "audience", "publish"],
        "system_prompt_addon": (
            "You are in SOCIAL ARCHITECT focus. Write for humans, not bots. "
            "Every output must be post-length: punchy, no jargon, one clear "
            "idea. Lead with impact. Never exceed 280 characters for social posts unless asked."
        ),
        "model_override": "qwen3-mlx",
        "auto_skills": ["social", "moltbook", "community", "api_client"],
        "enabled": True,
    },
    {
        "focus_id": "research",
        "display_name": "Researcher",
        "emoji": "🔬",
        "description": "Deep investigation, fact-checking, knowledge synthesis.",
        "tone": "formal",
        "style": "socratic",
        "delegation_level": 2,
        "token_budget_hint": 2500,
        "temperature_delta": 0.0,
        "expertise_keywords": ["research", "paper", "study", "learn", "explore", "investigate", "knowledge", "fact", "source", "cite", "verify", "evidence"],
        "system_prompt_addon": (
            "You are in RESEARCHER focus. Cite sources or flag absence of them. "
            "Distinguish between confirmed facts, working hypotheses, and "
            "speculation — label each. Ask one clarifying question if the task "
            "is ambiguous rather than assuming. Summaries before details."
        ),
        "model_override": None,
        "auto_skills": ["browser", "knowledge_graph", "brainstorm", "fact_check", "llm"],
        "enabled": True,
    },
    {
        "focus_id": "journalist",
        "display_name": "Journalist",
        "emoji": "📰",
        "description": "Investigation, reporting, structured narrative output.",
        "tone": "formal",
        "style": "narrative",
        "delegation_level": 2,
        "token_budget_hint": 2000,
        "temperature_delta": 0.0,
        "expertise_keywords": ["report", "article", "news", "interview", "publish", "investigate", "story", "lead", "headline", "press", "coverage"],
        "system_prompt_addon": (
            "You are in JOURNALIST focus. Inverted pyramid: most important "
            "facts first. Every claim needs a source or an 'unverified' tag. "
            "No passive voice. One sentence per idea."
        ),
        "model_override": None,
        "auto_skills": ["browser", "knowledge_graph", "fact_check"],
        "enabled": True,
    },
    {
        "focus_id": "rpg_master",
        "display_name": "RPG Master",
        "emoji": "🐉",
        "description": "Narrative game master for RPG campaigns.",
        "tone": "playful",
        "style": "narrative",
        "delegation_level": 2,
        "token_budget_hint": 2000,
        "temperature_delta": 0.2,
        "expertise_keywords": ["rpg", "campaign", "quest", "npc", "dungeon", "character", "roll", "encounter", "story", "lore", "world"],
        "system_prompt_addon": (
            "You are in RPG MASTER focus. You sculpt living worlds. "
            "Every scene: sensory detail → conflict hook → player agency. "
            "NPCs have wants, fears, and contradictions. "
            "Never resolve conflict without player input."
        ),
        "model_override": None,
        "auto_skills": ["rpg_pathfinder", "rpg_campaign", "llm"],
        "enabled": True,
    },
]


# ── CRUD Routes ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[FocusProfileSchema])
async def list_focus_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FocusProfileEntry).order_by(
            FocusProfileEntry.delegation_level, FocusProfileEntry.focus_id
        )
    )
    return [FocusProfileSchema(**r.to_dict()) for r in result.scalars().all()]


@router.get("/{focus_id}", response_model=FocusProfileSchema)
async def get_focus_profile(focus_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(FocusProfileEntry, focus_id)
    if row is None:
        raise HTTPException(404, f"Focus profile {focus_id!r} not found")
    return FocusProfileSchema(**row.to_dict())


@router.post("", response_model=FocusProfileSchema, status_code=201)
async def create_focus_profile(body: FocusProfileSchema, db: AsyncSession = Depends(get_db)):
    row = FocusProfileEntry(**body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return FocusProfileSchema(**row.to_dict())


@router.put("/{focus_id}", response_model=FocusProfileSchema)
async def update_focus_profile(focus_id: str, body: FocusProfileUpdate, db: AsyncSession = Depends(get_db)):
    row = await db.get(FocusProfileEntry, focus_id)
    if row is None:
        raise HTTPException(404, f"Focus profile {focus_id!r} not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return FocusProfileSchema(**row.to_dict())


@router.delete("/{focus_id}", status_code=204)
async def delete_focus_profile(focus_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(FocusProfileEntry, focus_id)
    if row is None:
        raise HTTPException(404, f"Focus profile {focus_id!r} not found")
    await db.delete(row)
    await db.commit()


@router.post("/seed", status_code=201)
async def seed_focus_profiles(db: AsyncSession = Depends(get_db)) -> dict:
    """Idempotently seed the 8 default focus profiles."""
    inserted = 0
    for profile in SEED_PROFILES:
        stmt = pg_insert(FocusProfileEntry).values(**profile)
        stmt = stmt.on_conflict_do_nothing(index_elements=["focus_id"])
        result = await db.execute(stmt)
        inserted += result.rowcount
    await db.commit()
    logger.info("Focus seed: %d profiles inserted", inserted)
    return {"inserted": inserted, "total": len(SEED_PROFILES)}


# ── Active Focus Level endpoints (used by E8-S86 heartbeat.py) ───────────────

@router.post("/active", response_model=ActiveFocusResponse, status_code=200)
async def set_active_focus(body: ActiveFocusRequest, db: AsyncSession = Depends(get_db)):
    """Set active focus level (L1/L2/L3) — stored as memory key."""
    if body.level not in FOCUS_LEVEL_CONFIG:
        raise HTTPException(status_code=422, detail="level must be L1, L2, or L3")
    from db.models import MemoryEntry  # noqa: F401 — import at call time to avoid circular
    stmt = pg_insert(MemoryEntry).values(
        key="active_focus_level", value=body.level, category="focus",
    ).on_conflict_do_update(
        index_elements=["key"],
        set_={"value": body.level, "updated_at": datetime.now(timezone.utc)},
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("active_focus_level set to %s", body.level)
    return ActiveFocusResponse(level=body.level, config=FOCUS_LEVEL_CONFIG[body.level])


@router.get("/active", response_model=ActiveFocusResponse)
async def get_active_focus(db: AsyncSession = Depends(get_db)):
    from db.models import MemoryEntry  # noqa: F401
    result = await db.execute(
        select(MemoryEntry).where(MemoryEntry.key == "active_focus_level")
    )
    row = result.scalars().first()
    level = row.value if row else "L2"
    if level not in FOCUS_LEVEL_CONFIG:
        level = "L2"
    return ActiveFocusResponse(level=level, config=FOCUS_LEVEL_CONFIG[level])


@router.delete("/active", status_code=200)
async def reset_active_focus(db: AsyncSession = Depends(get_db)) -> dict:
    from db.models import MemoryEntry  # noqa: F401
    await db.execute(delete(MemoryEntry).where(MemoryEntry.key == "active_focus_level"))
    await db.commit()
    return {"level": "L2", "reset": True}
```

### 2 — Wire into `src/api/main.py`

**Three locations require edits. Verified exact lines:**

**BEFORE (line 484 — relative import block):**
```python
    from .routers.engine_agents import router as engine_agents_router
    from .routers.agents_crud import router as agents_crud_router
```
**AFTER:**
```python
    from .routers.engine_agents import router as engine_agents_router
    from .routers.agents_crud import router as agents_crud_router
    from .routers.engine_focus import router as engine_focus_router
```

**BEFORE (line 518 — absolute import block):**
```python
    from routers.engine_agents import router as engine_agents_router
    from routers.agents_crud import router as agents_crud_router
```
**AFTER:**
```python
    from routers.engine_agents import router as engine_agents_router
    from routers.agents_crud import router as agents_crud_router
    from routers.engine_focus import router as engine_focus_router
```

**BEFORE (line 557 — include_router block):**
```python
app.include_router(engine_agents_router, dependencies=_api_deps)
app.include_router(agents_crud_router, dependencies=_api_deps)
```
**AFTER:**
```python
app.include_router(engine_agents_router, dependencies=_api_deps)
app.include_router(engine_focus_router, dependencies=_api_deps)
app.include_router(agents_crud_router, dependencies=_api_deps)
```

**Note:** Before editing, verify `MemoryEntry` ORM class name:
```bash
grep -n "^class.*Memor\|__tablename__.*memor" src/api/db/models.py | head -5
```
Use the actual class name in the active endpoints if different.

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | 5-layer architecture | ✅ | Router is API layer only. Reads DB via `get_db` SessionDep. No skeleton-layer DB calls from skills. |
| 2 | No secrets in code | ✅ | No API keys, passwords, or tokens in profiles |
| 3 | `models.yaml` SoT for model names | ✅ | `model_override` stores slug only (`qwen3-coder-free`). Never a URL. |
| 4 | Docker-first testing | ✅ | Verification via `curl` against running container |
| 5 | `aria_memories` writable | ✅ | No file writes |
| 6 | No soul files modified | ✅ | `system_prompt_addon` values extend personality; SOUL.md not modified |
| 7 | Idempotent seed | ✅ | `on_conflict_do_nothing` — re-running seed is safe |

---

## Dependencies

- **E7-S70 must complete first** — `FocusProfileEntry` ORM class + `to_dict()` method must exist, table must be in DB

---

## Verification

```bash
# 1. Router module importable
docker exec aria-api python3 -c "from routers.engine_focus import router; print('OK', router.prefix)"
# EXPECTED: OK /engine/focus

# 2. Syntax clean
docker exec aria-api python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('src/api/routers/engine_focus.py').read_text())
print('syntax OK')
"
# EXPECTED: syntax OK

# 3. Seed 8 profiles
curl -s -X POST http://localhost/api/engine/focus/seed \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -m json.tool
# EXPECTED: {"inserted": 8, "total": 8}

# 4. List profiles — 8 returned
curl -s http://localhost/api/engine/focus \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(len(d), 'profiles')
print([p['focus_id'] for p in d])
"
# EXPECTED: 8 profiles
# ['orchestrator', 'devsecops', ...]

# 5. Get single profile — verify token budget and temperature
curl -s http://localhost/api/engine/focus/devsecops \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print('budget:', d['token_budget_hint'], 'temp_delta:', d['temperature_delta'])
"
# EXPECTED: budget: 1500  temp_delta: -0.2

# 6. Seed is idempotent
curl -s -X POST http://localhost/api/engine/focus/seed \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -m json.tool
# EXPECTED: {"inserted": 0, "total": 8}

# 7. Set active focus level
curl -s -X POST http://localhost/api/engine/focus/active \
  -H "Authorization: Bearer $ARIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"level": "L1"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['level'], d['config']['max_goals'])"
# EXPECTED: L1 1

# 8. GET active focus
curl -s http://localhost/api/engine/focus/active \
  -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['level'])"
# EXPECTED: L1
```

---

## Prompt for Agent

You are executing ticket **E7-S71** for the Aria project.

**Pre-check — confirm S70 is done:**
```bash
grep -n "class FocusProfileEntry" src/api/db/models.py | head -1
# If empty → STOP. Run E7-S70 first.
docker exec aria-db psql -U admin -d aria_warehouse -c "\dt aria_engine.focus_profiles"
# If no table → STOP. Run E7-S70 first.
```

**Constraint:** 5-layer architecture — router uses `get_db` async session dep. No direct SQLAlchemy engine calls. `model_override` stores slug only. Do NOT modify `aria_mind/soul/`.

**Files to read first:**
1. `src/api/routers/engine_cron.py` lines 1–30 — copy router pattern
2. `src/api/db/models.py` lines 1–30 — find MemoryEntry class name
3. `src/api/main.py` lines 480–492 — relative import block
4. `src/api/main.py` lines 514–525 — absolute import block
5. `src/api/main.py` lines 554–562 — include_router list

**Steps:**
1. Create `src/api/routers/engine_focus.py` with full file content above.
2. Verify `MemoryEntry` class name from models.py — update active focus endpoints if different.
3. Apply the three `main.py` edits (relative import, absolute import, include_router).
4. Run `python3 -c "import ast; ast.parse(open('src/api/routers/engine_focus.py').read()); print('OK')"` — syntax check.
5. Run all 8 verification commands.
6. Report: "S-71 DONE — engine_focus.py created, 8 profiles seeded, all verification passed."
