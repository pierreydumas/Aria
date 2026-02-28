# E7-S77 — aria_skills/focus/ — Focus Introspection + Activation Skill
**Epic:** E7 — Focus System v2 | **Priority:** P2 | **Points:** 3 | **Phase:** 4  
**Status:** NOT STARTED | **Depends on:** E7-S71, E7-S73  
**Familiar Value:** After S70–S76 the focus system exists but Aria cannot use it herself. This skill closes the loop: Aria says "switch to creative mode", lists profiles, verifies the target is enabled, PATCHes herself, and confirms the new token budget. Cache clears automatically on the next `process()` call via S73's stale-cache guard.

---

## Problem

1. Aria cannot introspect her own or any agent's current `focus_type` without a raw HTTP call from a conversation.
2. There is no typed, token-efficient skill for listing focus profiles — falling back to `api_client` costs hundreds of extra tokens on header construction and URL composition.
3. The switch sequence (verify → patch → confirm) needs to be atomic from Aria's perspective.

---

## Fix — 3 new files

```
aria_skills/focus/
├── __init__.py      ← skill class + 4 tool handlers
├── skill.json       ← tool/action manifest read by LLM
└── skill.yaml       ← registry metadata
```

### Verify base class pattern before writing

```bash
sed -n '1,60p' aria_skills/base.py
```

Confirm: `BaseSkill`, `SkillConfig`, `SkillResult`, `SkillStatus` are the correct names. Use whatever the file shows.

---

## File 1: `aria_skills/focus/__init__.py`

```python
"""
Focus Skill — Aria focus profile introspection and self-activation.

Tools:
    focus__list        List all enabled profiles (id, name, level, budget, tone)
    focus__get         Full details for one focus_id  (omits addon body → saves ~1500 tokens)
    focus__activate    PATCH agent focus_type + return confirmation
    focus__status      Return current focus_type + status for agent

Token cost targets:
    focus__list     <= 80 tokens output    (compact, 8 profiles)
    focus__get      <= 250 tokens output   (no addon text)
    focus__activate <= 50 tokens output    (confirmation only)
    focus__status   <= 30 tokens output    (2-field dict)
"""
from __future__ import annotations

import os
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

ARIA_API_BASE = os.environ.get("ARIA_API_URL", "http://aria-api:8000/api")
LEVEL_NAMES = {1: "L1-Orchestrator", 2: "L2-Specialist", 3: "L3-Ephemeral"}


@SkillRegistry.register
class FocusSkill(BaseSkill):
    """
    Focus profile introspection and self-activation.
    Aria can list, inspect, and switch her own focus_type mid-session.
    """

    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._http = None

    @property
    def name(self) -> str:
        return "focus"

    async def initialize(self) -> bool:
        try:
            import httpx
            self._http = httpx.AsyncClient(
                base_url=ARIA_API_BASE,
                timeout=15.0,
            )
            self._status = SkillStatus.READY
            return True
        except ImportError:
            self.logger.error("httpx not installed — focus skill unavailable")
            self._status = SkillStatus.UNAVAILABLE
            return False

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()

    # ─────────────────────────── DISPATCH ────────────────────────────────────

    async def _run(self, action: str, **kwargs: Any) -> SkillResult:
        dispatch = {
            "focus__list":     self._list,
            "focus__get":      self._get,
            "focus__activate": self._activate,
            "focus__status":   self._status_check,
        }
        handler = dispatch.get(action)
        if handler is None:
            return SkillResult(
                success=False,
                data=None,
                error=f"Unknown focus action: {action}. Available: {sorted(dispatch)}",
            )
        return await handler(**kwargs)

    # ────────────────────────── focus__list ──────────────────────────────────

    async def _list(self, **_: Any) -> SkillResult:
        """
        List enabled focus profiles — compact output.
        Token cost target: <= 80 tokens.
        """
        resp = await self._http.get("/engine/focus")
        resp.raise_for_status()
        raw = resp.json()
        profiles = raw.get("profiles", raw) if isinstance(raw, dict) else raw

        compact = [
            {
                "id":     p["focus_id"],
                "name":   p.get("display_name") or p["focus_id"],
                "level":  LEVEL_NAMES.get(p.get("delegation_level", 2), "L2"),
                "budget": p.get("token_budget_hint", 0),
                "tone":   p.get("tone", ""),
            }
            for p in profiles
            if p.get("enabled", True)
        ]
        return SkillResult(success=True, data=compact)

    # ────────────────────────── focus__get ───────────────────────────────────

    async def _get(self, focus_id: str, **_: Any) -> SkillResult:
        """
        Full profile details — addon body omitted (applied invisibly by process()).
        Token cost target: <= 250 tokens.
        """
        resp = await self._http.get(f"/engine/focus/{focus_id}")
        if resp.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Focus '{focus_id}' not found. "
                                     "Use focus__list to see available profiles.")
        resp.raise_for_status()
        profile = resp.json()

        # Strip addon body — saves ~1500 tokens; agent receives it via process()
        summary = {k: v for k, v in profile.items() if k != "system_prompt_addon"}
        summary["addon_length"] = len(profile.get("system_prompt_addon") or "")
        return SkillResult(success=True, data=summary)

    # ────────────────────────── focus__activate ───────────────────────────────

    async def _activate(
        self,
        focus_id: str,
        agent_id: str | None = None,
        **_: Any,
    ) -> SkillResult:
        """
        Switch focus_type for an agent (default: ARIA_AGENT_ID env var or 'aria-main').

        1. Validates profile exists + is enabled.
        2. PATCHes the agent record via REST API.
        3. Returns confirmation.

        Cache refresh: S73's process() stale-cache guard detects the focus_type
        change on the very next LLM call and clears _focus_profile automatically.
        No explicit cache-bust endpoint needed.

        Token cost target: <= 50 tokens output.
        """
        target = agent_id or os.environ.get("ARIA_AGENT_ID", "aria-main")

        # Step 1: verify profile
        check = await self._http.get(f"/engine/focus/{focus_id}")
        if check.status_code == 404:
            return SkillResult(
                success=False, data=None,
                error=f"Focus profile '{focus_id}' not found. "
                      "Use focus__list to see available profiles.",
            )
        profile = check.json()
        if not profile.get("enabled", True):
            return SkillResult(
                success=False, data=None,
                error=f"Focus profile '{focus_id}' is disabled. Choose an active profile.",
            )

        # Step 2: PATCH agent
        patch = await self._http.patch(
            f"/engine/agents/{target}",
            json={"focus_type": focus_id},
        )
        if patch.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Agent '{target}' not found.")
        patch.raise_for_status()

        return SkillResult(
            success=True,
            data={
                "agent_id":     target,
                "focus_id":     focus_id,
                "token_budget": profile.get("token_budget_hint"),
                "level":        LEVEL_NAMES.get(profile.get("delegation_level", 2), "L2"),
                "message":      f"Focus switched to '{focus_id}'",
            },
        )

    # ────────────────────────── focus__status ─────────────────────────────────

    async def _status_check(
        self,
        agent_id: str | None = None,
        **_: Any,
    ) -> SkillResult:
        """
        Return current focus_type and status for an agent.
        Token cost target: <= 30 tokens output.
        """
        target = agent_id or os.environ.get("ARIA_AGENT_ID", "aria-main")
        resp = await self._http.get(f"/engine/agents/{target}")
        if resp.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Agent '{target}' not found.")
        resp.raise_for_status()
        agent = resp.json()
        return SkillResult(
            success=True,
            data={
                "agent_id":   target,
                "focus_type": agent.get("focus_type"),
                "status":     agent.get("status"),
            },
        )
```

---

## File 2: `aria_skills/focus/skill.json`

```json
{
  "name": "focus",
  "version": "1.0.0",
  "description": "Focus profile introspection and self-activation. Aria can list focus modes, inspect token budgets and delegation levels, and switch her own focus_type mid-session with minimal token cost.",
  "tools": [
    {
      "name": "focus__list",
      "description": "List all enabled focus profiles. Returns compact table: id, name, delegation level, token budget, tone. Call this before activating to find the right focus_id.",
      "input_schema": {
        "type": "object",
        "properties": {}
      }
    },
    {
      "name": "focus__get",
      "description": "Get full details for one focus profile by ID. Returns all fields except system_prompt_addon body (applied automatically by the engine). addon_length shows how many characters the addon contains.",
      "input_schema": {
        "type": "object",
        "properties": {
          "focus_id": {
            "type": "string",
            "description": "Focus profile ID (e.g. 'devsecops', 'creative', 'orchestrator')"
          }
        },
        "required": ["focus_id"]
      }
    },
    {
      "name": "focus__activate",
      "description": "Switch an agent's focus_type to a new profile. Validates the profile is enabled, then PATCHes the agent and returns confirmation with new token budget. If agent_id is omitted, switches Aria's own focus.",
      "input_schema": {
        "type": "object",
        "properties": {
          "focus_id": {
            "type": "string",
            "description": "Focus profile ID to activate"
          },
          "agent_id": {
            "type": "string",
            "description": "Agent to update (default: current agent / aria-main)"
          }
        },
        "required": ["focus_id"]
      }
    },
    {
      "name": "focus__status",
      "description": "Return the current focus_type and status for an agent. Minimal output (~30 tokens). Use to check current focus before switching.",
      "input_schema": {
        "type": "object",
        "properties": {
          "agent_id": {
            "type": "string",
            "description": "Agent ID to inspect (default: current agent)"
          }
        }
      }
    }
  ]
}
```

---

## File 3: `aria_skills/focus/skill.yaml`

```yaml
name: focus
version: "1.0.0"
enabled: true
description: >
  Focus profile introspection and self-activation skill.
  Aria can list, inspect, and switch her own focus_type mid-session
  with minimal token cost. addon body is never returned in tool output.
config:
  api_url: "${ARIA_API_URL:-http://aria-api:8000/api}"
tags:
  - meta
  - self-awareness
  - token-management
  - focus
```

---

## Token Economy

The `system_prompt_addon` body is **never returned to Aria via tool output**. It is applied invisibly by `agent_pool.process()` (E7-S73). Without this strip, each `focus__get` call would cost ~1500 extra tokens.

| Tool | Input tokens | Output tokens max |
|------|:-----------:|:-----------------:|
| `focus__list` | ~10 | 80 |
| `focus__get` | ~15 | 250 |
| `focus__activate` | ~15 | 50 |
| `focus__status` | ~10 | 30 |

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | No direct DB access | ✅ | All calls via `/api/engine/focus` + `/api/engine/agents` REST API |
| 2 | addon never in tool output | ✅ | Stripped in `_get`, never included in `_list` |
| 3 | Activation validates before patching | ✅ | Existence + enabled check before PATCH; cache auto-clears on next `process()` via S73 stale-cache guard |
| 4 | Defaults to ARIA_AGENT_ID env | ✅ | `os.environ.get("ARIA_AGENT_ID", "aria-main")` |
| 5 | No soul modification | ✅ | — |

---

## Dependencies

- **E7-S71** — `/api/engine/focus` CRUD endpoints live
- **E7-S73** — `PATCH /api/engine/agents/{id}` accepts `focus_type` field; S73's stale-cache guard in `process()` detects the mismatch (`_focus_profile.get('focus_id') != self.focus_type`) and clears the stale dict on the next LLM call

---

## Verification

```bash
# 1. Syntax clean
python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_skills/focus/__init__.py').read_text())
print('syntax OK')
"
# EXPECTED: syntax OK

# 2. Skill registers
python3 -c "
from aria_skills.focus import FocusSkill
from aria_skills.registry import SkillRegistry
s = SkillRegistry.get('focus')
print('registered:', s is not None)
"
# EXPECTED: registered: True

# 3. focus__list returns compact rows + no addon field
python3 -c "
import asyncio
from aria_skills.base import SkillConfig
from aria_skills.focus import FocusSkill

async def t():
    skill = FocusSkill(SkillConfig(name='focus', config={}))
    await skill.initialize()
    r = await skill._run('focus__list')
    assert r.success, r.error
    assert len(r.data) >= 1
    row = r.data[0]
    assert 'system_prompt_addon' not in row, 'addon must NOT appear in list'
    assert 'id' in row and 'budget' in row
    print('list PASS — rows:', len(r.data))

asyncio.run(t())
"
# EXPECTED: list PASS — rows: 8

# 4. focus__activate validates + patches
python3 -c "
import asyncio
from aria_skills.base import SkillConfig
from aria_skills.focus import FocusSkill

async def t():
    skill = FocusSkill(SkillConfig(name='focus', config={}))
    await skill.initialize()
    r = await skill._run('focus__activate', focus_id='creative', agent_id='aria-main')
    assert r.success, r.error
    assert r.data['focus_id'] == 'creative'
    assert 'token_budget' in r.data
    print('activate PASS — budget:', r.data['token_budget'])

asyncio.run(t())
"
# EXPECTED: activate PASS — budget: <number>

# 5. focus__activate rejects missing profile
python3 -c "
import asyncio
from aria_skills.base import SkillConfig
from aria_skills.focus import FocusSkill

async def t():
    skill = FocusSkill(SkillConfig(name='focus', config={}))
    await skill.initialize()
    r = await skill._run('focus__activate', focus_id='nonexistent_xyz')
    assert not r.success
    assert 'not found' in r.error
    print('validation PASS:', r.error[:60])

asyncio.run(t())
"
# EXPECTED: validation PASS: Focus profile 'nonexistent_xyz' not found...
```

---

## Prompt for Agent

You are executing ticket **E7-S77** for the Aria project.

**Constraint:** Skill layer — NO direct DB access. All HTTP calls go through `ARIA_API_URL` (default `http://aria-api:8000/api`). `system_prompt_addon` must NEVER appear in tool output — it is stripped in `_get` and never included in `_list`. Do NOT modify `aria_mind/soul/`.

**Files to read first:**
```bash
sed -n '1,60p' aria_skills/base.py          # SkillConfig, SkillResult, SkillStatus exact names
sed -n '1,40p' aria_skills/registry.py      # @SkillRegistry.register pattern
ls aria_skills/api_client/__init__.py        # verify an existing skill for structure comparison
```

**Steps:**
1. Read base.py + registry.py to confirm exact class names.
2. Create `aria_skills/focus/` directory (or it will be created by the files).
3. Create `aria_skills/focus/__init__.py` with content above.
4. Create `aria_skills/focus/skill.json` with content above.
5. Create `aria_skills/focus/skill.yaml` with content above.
6. Run all 5 verification commands.
7. Report: "S-77 DONE — Focus skill registered, list/get/activate/status verified, addon stripped, token targets enforced."
