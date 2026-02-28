# E7-S73 — agent_pool.py: Focus Prompt Composition + Temperature Delta
**Epic:** E7 — Focus System v2 | **Priority:** P1 | **Points:** 3 | **Phase:** 2  
**Status:** NOT STARTED | **Depends on:** E7-S70 (FocusProfileEntry + to_dict()), E7-S71 (8 profiles seeded in DB)  
**Familiar Value:** This is where personas come alive. An agent tagged `devsecops` today generates the same system prompt as one tagged `creative`. After this ticket, devsecops gets `temperature -0.2` and its persona instructions appended; creative gets `+0.3` and its own addon — automatically, on every `process()` call.

---

## Problem

**File:** `aria_engine/agent_pool.py`  
**Verified current state:**

```python
# aria_engine/agent_pool.py lines 107–121 (VERIFIED)
        # Build messages for LLM
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        # Sliding window: keep last N context messages
        context_window = kwargs.get("context_window", 50)
        messages.extend(self._context[-context_window:])

        try:
            response = await self._llm_gateway.complete(
                messages=messages,
                model=kwargs.get("model", self.model),
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
```

Three gaps on lines 107–121:
1. `line 108`: Only `self.system_prompt` is used — `self.focus_type` is present (line 63) but never read
2. `line 119`: `temperature=kwargs.get("temperature", self.temperature)` — fixed, no focus delta applied
3. `line 120`: `max_tokens=` — not focus-gated (fixed in S-74 which depends on this ticket)

`EngineAgent` (line 46) is a **`@dataclass`** (verified). `focus_type: str | None = None` at line 63 is a dataclass field. There is no `__init__` to monkey-patch — any cache field must be added to the dataclass field list.

---

## Root Cause

`EngineAgent.process()` was written when `focus_type` was a routing hint only. It never received a DB query path to `FocusProfileEntry`. The `@dataclass` decorator auto-generates `__init__` from field declarations — runtime state must be stored as `field(default=..., repr=False)` entries, not as `self.xxx =` assignments.

---

## Fix

### Step 1 — Add `_focus_profile` to `EngineAgent` dataclass (NOT in __init__)

**File:** `aria_engine/agent_pool.py`

**CRITICAL:** `EngineAgent` is a `@dataclass`. The original sprint ticket (S-73) had a bug suggesting `self._focus_profile = None` in `__init__` — **this would crash** with `TypeError: FocusProfileEntry.__init__() got an unexpected keyword argument`. The fix is a `field()` entry.

**BEFORE (lines 83–89 — end of dataclass fields, "Runtime state" section):**
```python
    # Runtime state (not persisted)
    _task_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    _worker_task: asyncio.Task | None = field(default=None, repr=False)
    _llm_gateway: Any | None = field(default=None, repr=False)
    _context: list[dict[str, str]] = field(default_factory=list, repr=False)
```

**AFTER:**
```python
    # Runtime state (not persisted)
    _task_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    _worker_task: asyncio.Task | None = field(default=None, repr=False)
    _llm_gateway: Any | None = field(default=None, repr=False)
    _context: list[dict[str, str]] = field(default_factory=list, repr=False)
    _focus_profile: dict | None = field(default=None, repr=False)  # populated by load_focus_profile()
```

### Step 2 — Add `load_focus_profile()` method to `EngineAgent`

Add this async method to the `EngineAgent` class (after `process()` method, before `to_dict()` or class end):

```python
    async def load_focus_profile(self, db_engine: "AsyncEngine") -> None:
        """
        Fetch FocusProfileEntry for self.focus_type and cache it in _focus_profile.
        Safe to call multiple times (re-fetches on focus_type change).
        No-op if focus_type is None or DB query fails (graceful degradation).
        """
        if not self.focus_type:
            self._focus_profile = None
            return
        try:
            from db.models import FocusProfileEntry
            from sqlalchemy import select as _select
            async with db_engine.begin() as conn:
                result = await conn.execute(
                    _select(FocusProfileEntry).where(
                        FocusProfileEntry.focus_id == self.focus_type,
                        FocusProfileEntry.enabled.is_(True),
                    )
                )
                row = result.scalars().first()
            self._focus_profile = row.to_dict() if row else None
            logger.debug(
                "Agent %s loaded focus_profile: %s (found=%s)",
                self.agent_id, self.focus_type, self._focus_profile is not None,
            )
        except Exception as exc:
            logger.warning(
                "Agent %s could not load focus profile %s: %s",
                self.agent_id, self.focus_type, exc,
            )
            self._focus_profile = None
```

### Step 3 — Patch `process()` — compose system prompt + apply temperature delta

**File:** `aria_engine/agent_pool.py`

**BEFORE (lines 107–121 — verified exact content):**
```python
        # Build messages for LLM
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        # Sliding window: keep last N context messages
        context_window = kwargs.get("context_window", 50)
        messages.extend(self._context[-context_window:])

        try:
            response = await self._llm_gateway.complete(
                messages=messages,
                model=kwargs.get("model", self.model),
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
```

**AFTER:**
```python
        # Resolve focus profile — use cached, no DB call here
        fp = self._focus_profile  # dict or None, pre-loaded by load_focus_profile()

        # Build effective system prompt — additive composition
        # Rule: effective = base + "\n\n---\n" + addon. Never replaces base.
        base_prompt = self.system_prompt or ""
        if fp and fp.get("system_prompt_addon"):
            effective_system = base_prompt.rstrip() + "\n\n---\n" + fp["system_prompt_addon"]
        else:
            effective_system = base_prompt

        # Build messages for LLM
        messages = []
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        # Sliding window: keep last N context messages
        context_window = kwargs.get("context_window", 50)
        messages.extend(self._context[-context_window:])

        # Apply focus temperature delta — additive, clamped to [0.0, 1.0]
        base_temp = kwargs.get("temperature", self.temperature)
        temp_delta = float(fp["temperature_delta"]) if fp and fp.get("temperature_delta") is not None else 0.0
        effective_temp = max(0.0, min(1.0, base_temp + temp_delta))

        # Apply focus model override — only if caller doesn't force a model
        effective_model = (
            kwargs.get("model")
            or (fp.get("model_override") if fp else None)
            or self.model
        )

        try:
            response = await self._llm_gateway.complete(
                messages=messages,
                model=effective_model,
                temperature=effective_temp,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
```

**Note:** `max_tokens` enforcement by focus budget is handled in S-74. The `kwargs.get("max_tokens", self.max_tokens)` line is left intact here; S-74 wraps it.

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | `@dataclass` field pattern | ✅ | `_focus_profile` added as `field(default=None, repr=False)`, NOT `self.xxx = None` in __init__ |
| 2 | Additive prompt composition | ✅ | `base.rstrip() + "\n\n---\n" + addon` — never replaces base |
| 3 | Temperature clamped | ✅ | `max(0.0, min(1.0, base + delta))` |
| 4 | Graceful degradation | ✅ | `fp = None` → all paths fall back to original behavior |
| 5 | No DB call in `process()` | ✅ | `process()` reads `self._focus_profile` (pre-cached) — stale-cache guard is a dict-key check only, no I/O |
| 6 | No soul files modified | ✅ | None |

---

## Dependencies

- **E7-S70 must complete first** — `FocusProfileEntry.to_dict()` must exist
- **E7-S71 must complete first** — 8 seed profiles must be in DB so `load_focus_profile()` can find them

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

# 2. _focus_profile is a dataclass field (not a crash)
docker exec aria-engine python3 -c "
import dataclasses
from aria_engine.agent_pool import EngineAgent
field_names = [f.name for f in dataclasses.fields(EngineAgent)]
print('fields:', field_names)
assert '_focus_profile' in field_names, '_focus_profile must be a dataclass field'
print('_focus_profile field OK')
"
# EXPECTED: fields: [...] then _focus_profile field OK

# 3. load_focus_profile() fetches from DB
docker exec aria-engine python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from aria_engine.agent_pool import EngineAgent

async def test():
    db = create_async_engine(os.environ['DATABASE_URL'])
    agent = EngineAgent(
        agent_id='test-devsecops',
        system_prompt='You are a DevSecOps engineer.',
        focus_type='devsecops',
        model='claude-3-5-haiku-20241022',
    )
    assert agent._focus_profile is None, 'Should start as None'
    await agent.load_focus_profile(db)
    fp = agent._focus_profile
    print('focus loaded:', fp is not None)
    if fp:
        print('temp_delta:', fp.get('temperature_delta'))
        print('addon preview:', (fp.get('system_prompt_addon') or '')[:80])
        assert fp['temperature_delta'] == -0.2, f'Expected -0.2 got {fp[\"temperature_delta\"]}'
    print('PASS')

asyncio.run(test())
"
# EXPECTED: focus loaded: True / temp_delta: -0.2 / addon preview: ... / PASS

# 4. Prompt composition is additive
docker exec aria-engine python3 -c "
base = 'You are a DevSecOps engineer.'
addon = 'Security is non-negotiable.'
effective = base.rstrip() + '\n\n---\n' + addon
print('separator present:', '\\n\\n---\\n' in effective)
print('base preserved:', base.rstrip() in effective)
print(repr(effective[:60]))
"
# EXPECTED: separator present: True / base preserved: True

# 5. Temperature clamping
docker exec aria-engine python3 -c "
tests = [(0.7, 0.3, 1.0), (0.7, -0.2, 0.5), (0.9, 0.3, 1.0), (0.1, -0.5, 0.0)]
for base, delta, expected in tests:
    result = max(0.0, min(1.0, base + delta))
    assert abs(result - expected) < 0.001, f'{base}+{delta}={result}, expected {expected}'
print('temperature clamping PASS')
"
# EXPECTED: temperature clamping PASS
```

---

## Prompt for Agent

You are executing ticket **E7-S73** for the Aria project.

**⚠️ CRITICAL BEFORE STARTING:** `EngineAgent` is a `@dataclass`. You MUST add `_focus_profile` as:
```python
_focus_profile: dict | None = field(default=None, repr=False)
```
in the dataclass field list — **NOT** as `self._focus_profile = None` in any `__init__` method. Doing the latter will crash with `TypeError`. Verify with: `grep -n "@dataclass" aria_engine/agent_pool.py`

**Pre-check — confirm S70+S71 done:**
```bash
docker exec aria-engine python3 -c "from db.models import FocusProfileEntry; print('S70 OK')"
curl -s http://localhost/api/engine/focus -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'profiles (need 8)')"
```

**Files to read first:**
1. `aria_engine/agent_pool.py` lines 43–95 — full `@dataclass` field list including the `# Runtime state` section, then `process()` start
2. `aria_engine/agent_pool.py` lines 105–125 — exact messages build + llm_gateway.complete() call

**Steps:**
1. Add `_focus_profile: dict | None = field(default=None, repr=False)` to dataclass fields (after `_context` field).
2. Add `load_focus_profile(db_engine)` async method to `EngineAgent` class.
3. Replace the `# Build messages for LLM` block in `process()` with the AFTER block above.
4. Run all 5 verification commands. All must pass before proceeding.
5. Report: "S-73 DONE — focus composition active, dataclass field verified, all 5 verifications passed."
