# E7-S70 — FocusProfileEntry ORM + DB Table
**Epic:** E7 — Focus System v2 | **Priority:** P0 | **Points:** 3 | **Phase:** 1  
**Status:** NOT STARTED | **Depends on:** None — foundation ticket  
**Familiar Value:** Every other E7 ticket and E8-S86 depends on this row in the DB. Without this table, Aria's focus type is a free-text string tag that means nothing to any system. With it, the system knows that `devsecops` means token_budget=1500, temperature_delta=-0.2, and a specific prompt addon — autonomously, forever.

---

## Problem

**File:** `src/api/db/models.py`  
**Evidence:** `grep -n "FocusProfile\|focus_profile" src/api/db/models.py` → **empty output**

`focus_type` on `EngineAgentState` at **line 986**:
```python
# src/api/db/models.py line 986
focus_type: Mapped[str | None] = mapped_column(String(50))
```

This column exists but points to nothing. There is no backing entity that defines what a focus type IS. Consequences:

- `routing.py` SPECIALTY_PATTERNS (lines 40–61): 5 hardcoded dict entries, compile-time only → adding a focus persona requires a code deploy
- `agent_pool.py` line 63: `focus_type: str | None = None` — stored on agent but never resolved to metadata (token budget, temperature delta, prompt addon)
- `aria_mind/IDENTITY.md` lines 42–50: 7 focus personas defined in markdown, never persisted to DB

**Verified insertion point:** After `EngineAgentState` class which ends at approximately line 1001 (after its `updated_at` column), before `EngineConfigEntry` which starts at **line 1004**.

---

## Root Cause

Focus was added as a string routing hint in an early sprint. It was never elevated to a first-class DB entity. Every downstream consumer (routing, prompt composition, token budgets, delegation levels) therefore has no structured data to read and falls back to hardcoded Python constants.

---

## Fix

### Step 1 — Add `FocusProfileEntry` ORM class to `src/api/db/models.py`

**Insert after `EngineAgentState` block (after line ~1001, before line ~1004 `class EngineConfigEntry`).**

Verify imports already present near top of models.py:
```bash
grep -n "from sqlalchemy\|JSONB\|Integer\|Float\|Text\|Boolean" src/api/db/models.py | head -10
```
All column types (`JSONB`, `Integer`, `Float`, `Text`, `Boolean`) are already imported. Do NOT add duplicate imports.

**INSERT (new class):**
```python
class FocusProfileEntry(Base):
    """
    A named personality layer for agents.
    Composes additively on top of an agent's base system_prompt.
    effective_prompt = base_prompt + "\\n\\n---\\n" + system_prompt_addon
    """
    __tablename__ = "focus_profiles"
    __table_args__ = {"schema": "aria_engine"}

    focus_id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        comment="Slug key, e.g. 'devsecops', 'creative'"
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), server_default=text("'🎯'"))
    description: Mapped[str | None] = mapped_column(Text)

    # Personality
    tone: Mapped[str] = mapped_column(
        String(30), server_default=text("'neutral'"),
        comment="precise | analytical | playful | formal | warm | blunt"
    )
    style: Mapped[str] = mapped_column(
        String(30), server_default=text("'directive'"),
        comment="directive | socratic | analytical | narrative | concise"
    )

    # Delegation: 1=L1(orchestrator), 2=L2(specialist), 3=L3(ephemeral)
    delegation_level: Mapped[int] = mapped_column(
        Integer, server_default=text("2")
    )

    # Token discipline — hard ceiling enforced by agent_pool.py S-74
    token_budget_hint: Mapped[int] = mapped_column(
        Integer, server_default=text("2000"),
        comment="Soft max_tokens ceiling when this focus is active"
    )

    # Temperature — additive delta, applied to agent.temperature in S-73
    temperature_delta: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        comment="+0.3 for creative, -0.2 for precise. Clamped 0.0–1.0."
    )

    # Routing keywords — replaces hardcoded SPECIALTY_PATTERNS in S-72
    expertise_keywords: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"),
        comment="Keyword fragments for specialty routing. Built into regex alternation."
    )

    # Prompt layer — appended to base system_prompt at call time (S-73)
    system_prompt_addon: Mapped[str | None] = mapped_column(
        Text,
        comment="Injected after agent base prompt. Additive only, never replaces."
    )

    # Optional model override — stores slug from models.yaml, not hardcoded name
    model_override: Mapped[str | None] = mapped_column(
        String(200),
        comment="model_id slug (e.g. 'qwen3-coder-free'). Resolved via models.yaml."
    )

    # Skills auto-injected when focus is activated
    auto_skills: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )

    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    def to_dict(self) -> dict:
        """Return JSON-serializable dict. Used by engine_focus router (S-71)."""
        return {
            "focus_id": self.focus_id,
            "display_name": self.display_name,
            "emoji": self.emoji,
            "description": self.description,
            "tone": self.tone,
            "style": self.style,
            "delegation_level": self.delegation_level,
            "token_budget_hint": self.token_budget_hint,
            "temperature_delta": self.temperature_delta,
            "expertise_keywords": self.expertise_keywords or [],
            "system_prompt_addon": self.system_prompt_addon,
            "model_override": self.model_override,
            "auto_skills": self.auto_skills or [],
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


Index("idx_focus_profiles_enabled", FocusProfileEntry.enabled)
```

### Step 2 — Create table via Docker (live migration, no Alembic)

```bash
docker exec aria-db psql -U admin -d aria_warehouse -c "
CREATE TABLE IF NOT EXISTS aria_engine.focus_profiles (
    focus_id           VARCHAR(50)  PRIMARY KEY,
    display_name       VARCHAR(100) NOT NULL,
    emoji              VARCHAR(10)  NOT NULL DEFAULT '🎯',
    description        TEXT,
    tone               VARCHAR(30)  NOT NULL DEFAULT 'neutral',
    style              VARCHAR(30)  NOT NULL DEFAULT 'directive',
    delegation_level   INTEGER      NOT NULL DEFAULT 2,
    token_budget_hint  INTEGER      NOT NULL DEFAULT 2000,
    temperature_delta  FLOAT        NOT NULL DEFAULT 0.0,
    expertise_keywords JSONB        NOT NULL DEFAULT '[]'::jsonb,
    system_prompt_addon TEXT,
    model_override     VARCHAR(200),
    auto_skills        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    enabled            BOOLEAN      NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_focus_profiles_enabled
    ON aria_engine.focus_profiles (enabled);
"
```

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | New class is DB+ORM layer only. API in S-71, skill in S-77. |
| 2 | `.env` for secrets | ✅ | No secrets in profile data |
| 3 | `models.yaml` SoT for model names | ✅ | `model_override` stores slug (e.g. `qwen3-coder-free`). Resolved via models.yaml at call time, not hardcoded. |
| 4 | Docker-first execution | ✅ | All SQL via `docker exec aria-db psql` |
| 5 | `aria_memories` only writable path | ✅ | No writes to aria_memories — pure code + DB |
| 6 | No soul file modification | ✅ | Focus addons are in DB, not soul/IDENTITY.md |
| 7 | `to_dict()` required | ✅ | All ORM models used by routers must expose `to_dict()` — added here |

---

## Dependencies

None — this is the foundation. All E7 tickets depend on it.

---

## Verification

```bash
# 1. ORM class importable, columns correct
docker exec aria-api python3 -c "
from db.models import FocusProfileEntry
cols = [c.key for c in FocusProfileEntry.__table__.columns]
print('columns:', cols)
assert 'focus_id' in cols and 'token_budget_hint' in cols and 'system_prompt_addon' in cols
assert 'to_dict' in dir(FocusProfileEntry)
print('ORM OK')
"
# EXPECTED: columns: [...] then ORM OK

# 2. Table exists in DB
docker exec aria-db psql -U admin -d aria_warehouse -c "\dt aria_engine.focus_profiles"
# EXPECTED: aria_engine | focus_profiles | table | admin

# 3. Index exists
docker exec aria-db psql -U admin -d aria_warehouse -c "\di aria_engine.idx_focus_profiles_enabled"
# EXPECTED: lists idx_focus_profiles_enabled

# 4. Column schema matches ORM
docker exec aria-db psql -U admin -d aria_warehouse -c "\d aria_engine.focus_profiles"
# EXPECTED: 16 columns including expertise_keywords jsonb, system_prompt_addon text, enabled boolean

# 5. Syntax clean
docker exec aria-api python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('src/api/db/models.py').read_text())
print('models.py syntax OK')
"
# EXPECTED: models.py syntax OK
```

---

## Prompt for Agent

You are executing ticket **E7-S70** for the Aria project.

**Pre-check — confirm NOT already done:**
```bash
grep -n "FocusProfileEntry" src/api/db/models.py | head -3
# If any output → S70 already done. Skip.
```

**Constraint:** 5-layer architecture. This ticket touches DB/ORM layers only. No API, no skills, no soul files. `model_override` stores a slug string only — never a full model name or URL.

**Files to read first:**
1. `src/api/db/models.py` lines 970–1010 — read `EngineAgentState` definition to find exact `updated_at` line and `EngineConfigEntry` start line
2. `src/api/db/models.py` lines 1–30 — verify imports (JSONB, Integer, Float, Text, Boolean already imported)

**Steps:**
1. Confirm line numbers: search for `class EngineConfigEntry` to find exact insertion line.
2. Add `FocusProfileEntry` class + `Index` line exactly as specified above, between `EngineAgentState` end and `EngineConfigEntry` start.
3. Run Step 2 SQL block via `docker exec aria-db psql -U admin -d aria_warehouse ...`
4. Run all 5 verification commands. All must pass.
5. Report: "S-70 DONE — FocusProfileEntry added to models.py, table created, 5 verifications passed."
