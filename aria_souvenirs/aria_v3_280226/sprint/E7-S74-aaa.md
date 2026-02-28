# E7-S74 — Token Budget Enforcement: Focus Hard Ceiling on max_tokens
**Epic:** E7 — Focus System v2 | **Priority:** P1 | **Points:** 2 | **Phase:** 2  
**Status:** NOT STARTED | **Depends on:** E7-S73 (sets up `fp = self._focus_profile` in process())  
**Familiar Value:** A `social` post requesting 4096 tokens currently gets 4096 tokens. After this ticket it's hard-capped at 800 — the `token_budget_hint` column becomes an enforced economic constraint, not decorative data.

---

## Problem

**File:** `aria_engine/agent_pool.py` line 120 (verified, after S-73 AFTER block is applied):

```python
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
```

This allows any caller — including Aria's own work_cycle, sub-agents, and roundtable participants — to request arbitrarily high token counts, fully bypassing the `token_budget_hint` column added in S-70. The focus budget column is live in DB but has **zero enforcement** in the Python runtime.

**Token budget reference (from S-71 seed profiles):**

| Focus ID | token_budget_hint | Without enforcement |
|----------|:-----------------:|:------------------:|
| social | 800 | caller can request 4096 |
| creative | 3000 | caller can request 4096 |
| orchestrator | 2000 | caller can request 4096 |
| devsecops | 1500 | caller can request 4096 |

The social agent's 800-token discipline — critical for keeping post output short and punchy — is completely optional today.

---

## Root Cause

`max_tokens` is a pass-through parameter in `process()`. When `FocusProfileEntry.token_budget_hint` was designed, no enforcement code was written. S-73 added `fp = self._focus_profile` to `process()` as a prerequisite — S-74 uses that same `fp` variable to apply the ceiling.

---

## Fix

### Step 1 — Add `_budget_cap()` module-level pure function

**File:** `aria_engine/agent_pool.py`  
**Insert:** After imports, before `class EngineAgent`.

```python
def _budget_cap(caller: int | None, fp: dict | None) -> int | None:
    """
    Apply focus token_budget_hint as a hard ceiling on max_tokens.

    Design contract:
        - If no focus profile OR token_budget_hint == 0: caller passes through unchanged.
        - Otherwise: min(caller, token_budget_hint) — focus budget cannot be exceeded,
          even by explicit caller overrides.
        - If caller is None and budget is set: use budget as the ceiling.

    Args:
        caller: Caller-requested max_tokens (int or None = use model default).
        fp:     Resolved FocusProfileEntry dict (or None if no focus loaded).

    Returns:
        Capped int, or None if both caller and budget are unset.

    Examples:
        _budget_cap(4096, {"token_budget_hint": 800})  → 800   (capped)
        _budget_cap(500,  {"token_budget_hint": 800})  → 500   (under budget)
        _budget_cap(None, {"token_budget_hint": 800})  → 800   (budget is ceiling)
        _budget_cap(4096, None)                         → 4096  (no focus, pass through)
        _budget_cap(4096, {"token_budget_hint": 0})    → 4096  (budget disabled)
    """
    budget: int | None = fp.get("token_budget_hint") if fp else None
    if not budget:       # 0, None, missing, or no focus profile → pass through
        return caller
    if caller is None:   # no explicit caller value → enforce budget ceiling
        return budget
    return min(caller, budget)
```

### Step 2 — Patch `process()` max_tokens line

**File:** `aria_engine/agent_pool.py`  
**Target:** The `max_tokens=` line inside `process()`, after S-73 AFTER block is applied.

**BEFORE:**
```python
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
```

**AFTER:**
```python
                max_tokens=_budget_cap(
                    caller=kwargs.get("max_tokens", self.max_tokens),
                    fp=fp,
                ),
```

`fp` is available at this point because S-73 sets `fp = self._focus_profile` earlier in `process()`.

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | Hard ceiling (not advisory) | ✅ | `min(caller, budget)` — caller can never exceed focus budget |
| 2 | Graceful degradation | ✅ | `budget=0` or `budget=None` → pass through; zero new behavior risk |
| 3 | Pure function | ✅ | `_budget_cap()` is side-effect free, no DB calls, trivially testable |
| 4 | S-73 prerequisite | ✅ | `fp` variable must be set by S-73 before this line runs |
| 5 | No soul files modified | ✅ | None |

---

## Dependencies

- **E7-S73 must complete first** — `fp = self._focus_profile` must exist in `process()` to pass to `_budget_cap()`
- **E7-S70** — `token_budget_hint` column must exist on `focus_profiles` table

---

## Verification

```bash
# 1. Syntax clean
docker exec aria-engine python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_engine/agent_pool.py').read_text())
print('syntax OK')
"
# EXPECTED: syntax OK

# 2. _budget_cap() exists and is importable
docker exec aria-engine python3 -c "
from aria_engine.agent_pool import _budget_cap
print('_budget_cap importable OK')
"
# EXPECTED: _budget_cap importable OK

# 3. Budget cap logic — all 6 cases
docker exec aria-engine python3 -c "
from aria_engine.agent_pool import _budget_cap

cases = [
    # (caller, fp, expected)
    (4096, {'token_budget_hint': 800}, 800),    # capped
    (500,  {'token_budget_hint': 800}, 500),    # under budget, caller wins
    (None, {'token_budget_hint': 800}, 800),    # no caller, budget is ceiling
    (4096, None, 4096),                          # no focus, pass through
    (None, None, None),                          # no caller, no focus
    (4096, {'token_budget_hint': 0}, 4096),     # budget=0, disabled
]

for caller, fp, expected in cases:
    result = _budget_cap(caller, fp)
    assert result == expected, f'_budget_cap({caller}, {fp}) = {result}, expected {expected}'
    print(f'  _budget_cap({caller}, budget={fp.get(\"token_budget_hint\") if fp else None}) → {result} ✓')

print('ALL PASS')
"
# EXPECTED: all 6 lines with ✓ then ALL PASS

# 4. Social agent hard-capped to 800
docker exec aria-engine python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from aria_engine.agent_pool import EngineAgent, _budget_cap

async def test():
    db = create_async_engine(os.environ['DATABASE_URL'])
    agent = EngineAgent(
        agent_id='test-social',
        system_prompt='You are a social media manager.',
        focus_type='social',
        model='claude-3-5-haiku-20241022',
        max_tokens=4096,
    )
    await agent.load_focus_profile(db)
    fp = agent._focus_profile
    result = _budget_cap(4096, fp)
    print(f'social max_tokens capped: 4096 → {result}')
    assert result == 800, f'Expected 800, got {result}'
    print('PASS')

asyncio.run(test())
"
# EXPECTED: social max_tokens capped: 4096 → 800 / PASS

# 5. Orchestrator agent passes through at 2000 when caller requests 1000
docker exec aria-engine python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from aria_engine.agent_pool import EngineAgent, _budget_cap

async def test():
    db = create_async_engine(os.environ['DATABASE_URL'])
    agent = EngineAgent(
        agent_id='test-orchestrator',
        system_prompt='You are the orchestrator.',
        focus_type='orchestrator',
        model='claude-3-5-haiku-20241022',
        max_tokens=4096,
    )
    await agent.load_focus_profile(db)
    fp = agent._focus_profile
    # Caller requests 1000 < budget 2000 → caller wins
    result = _budget_cap(1000, fp)
    print(f'orchestrator: caller=1000 budget=2000 → {result}')
    assert result == 1000, f'Expected 1000, got {result}'
    print('PASS')

asyncio.run(test())
"
# EXPECTED: orchestrator: caller=1000 budget=2000 → 1000 / PASS
```

---

## Prompt for Agent

You are executing ticket **E7-S74** for the Aria project.

**This is a two-change ticket.** S-73 must be complete first.

**Pre-check:**
```bash
# Verify S73 done: fp variable and load_focus_profile must exist
grep -n "_focus_profile\|load_focus_profile\|fp = self\._focus_profile" aria_engine/agent_pool.py | head -5
# If empty → STOP. Run S73 first.
```

**Constraint:** `_budget_cap()` is a pure function (no side effects, no DB calls). Never raise exceptions — always return a value. Do NOT modify `aria_mind/soul/`.

**Files to read first:**
1. `aria_engine/agent_pool.py` — find the `# imports` section (before class EngineAgent), and find `max_tokens=kwargs.get("max_tokens", self.max_tokens)` line inside `process()`

**Steps:**
1. Add `_budget_cap()` function at module level, after imports, before `class EngineAgent`.
2. Find the `max_tokens=kwargs.get("max_tokens", self.max_tokens)` line inside `process()` and replace it with the `_budget_cap(...)` call.
3. Run all 5 verification commands. All must pass.
4. Report: "S-74 DONE — _budget_cap() added, social capped to 800, all 5 verifications passed."
