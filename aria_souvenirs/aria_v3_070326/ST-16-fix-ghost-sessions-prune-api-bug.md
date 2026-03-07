# ST-16: Fix Ghost Sessions — `api_client.post()` Missing `params` Argument

**Epic:** E12 — Streaming Pipeline Correctness | **Priority:** P1 | **Points:** 3 | **Phase:** 2
**Status:** NOT STARTED | **Reported:** 2026-03-07

---

## Problem

`aria_memories/logs/ghost_sessions_investigation_2026-03-07.md` reports:
> "72 active sessions (target: <5) — Pruning function has API bug preventing cleanup"
> "~50+ ghost sessions from previous days are accumulating"

The `prune_stale_sessions` method in `aria_skills/agent_manager/__init__.py`
line 270 calls:

```python
result = await self._api.post(
    "/engine/sessions/cleanup",
    params={"max_age_hours": int(max_age_hours), "dry_run": False},   # ← BUG
)
```

But `api_client`'s `post` method (`aria_skills/api_client/__init__.py` line 1169)
only accepts `(self, path: str, data: dict | None = None)`:

```python
async def post(self, path: str, data: dict | None = None) -> SkillResult:
    resp = await self._request_with_retry("POST", path, json=data)
```

There is **no `params` keyword argument**. Python raises:
```
TypeError: post() got an unexpected keyword argument 'params'
```

This is caught by the `except Exception as e:` at line 289 in `agent_manager/__init__.py`:

```python
except Exception as e:
    self._log_usage("prune_stale_sessions", False, error=str(e))
    return SkillResult.fail(f"Failed to prune sessions: {e}")
```

Result: every invocation of `prune_stale_sessions` **silently fails** with this
TypeError. Ghost sessions from previous days are never cleaned up. The DB
accumulates stale `active` sessions indefinitely.

---

## Root Cause

`api_client.post()` (line 1169) provides no `params=` passthrough to the
underlying `_request_with_retry("POST", path, **kwargs)` call. The `get()` method
(line 1158) correctly accepts and passes `params`:

```python
# get() — correct (line 1158)
async def get(self, path: str, params: dict | None = None) -> SkillResult:
    resp = await self._request_with_retry("GET", path, params=params)

# post() — broken (line 1169)
async def post(self, path: str, data: dict | None = None) -> SkillResult:
    resp = await self._request_with_retry("POST", path, json=data)
    # ← missing params= passthrough
```

The `/engine/sessions/cleanup` endpoint uses FastAPI `Query` parameters
(not request body), so the params MUST be passed as URL query string, not JSON.

---

## Fix

### Fix 1: Add `params` to `api_client.post()` (2 lines)

**File:** `aria_skills/api_client/__init__.py`
**Lines:** 1169–1174

#### BEFORE

```python
    @log_latency
    async def post(self, path: str, data: dict | None = None) -> SkillResult:
        """Generic POST request."""
        try:
            resp = await self._request_with_retry("POST", path, json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"POST {path} failed: {e}")
```

#### AFTER

```python
    @log_latency
    async def post(
        self,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> SkillResult:
        """Generic POST request."""
        try:
            resp = await self._request_with_retry(
                "POST", path, json=data, params=params
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"POST {path} failed: {e}")
```

### Fix 2: Remove the misleading `dry_run=False` when sending real cleanup call

In `agent_manager/__init__.py` line 271, the call already passes `dry_run=False`
as a param — but it was silently ignored. With Fix 1 applied, this will now
actually run for real. **Verify the cron schedule** before deployment to avoid
accidentally pruning sessions too aggressively. The current default
`max_age_hours=6` means sessions idle for 6+ hours are archived.

No code change needed for `agent_manager/__init__.py` — the call is already
correct once `api_client.post()` is fixed.

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Fix is in api_client layer; agent_manager skill calls through it correctly |
| 2 | .env for secrets (zero in code) | ❌ | Not applicable |
| 3 | models.yaml single source of truth | ❌ | Not applicable |
| 4 | Docker-first testing | ✅ | Verify in container: call `prune_stale_sessions` and confirm it returns pruned_count > 0 |
| 5 | aria_memories only writable path | ❌ | No file writes by this code |
| 6 | No soul modification | ❌ | Not applicable |

---

## Dependencies

None — this is an isolated 2-line fix in `api_client`. ST-13/ST-14/ST-15 are
independent and can run in parallel.

---

## Verification

```bash
# 1. Verify the fix is applied
grep -n "params: dict | None = None" aria_skills/api_client/__init__.py
# EXPECTED: multiple matches — one is the new post() signature

grep -A8 "async def post" aria_skills/api_client/__init__.py | grep "params"
# EXPECTED: "params: dict | None = None" in the post method signature

# 2. Unit test — call post() with params and verify they are forwarded
pytest tests/ -k "api_client" -v
# EXPECTED: all collected tests pass

# 3. Integration — verify prune_stale_sessions now executes
# (in container, call the skill directly)
docker compose exec aria-engine python -c "
import asyncio
from aria_skills.api_client import AriaApiClient
from aria_skills.agent_manager import AgentManagerSkill
async def test():
    skill = AgentManagerSkill()
    await skill.initialize()
    result = await skill.prune_stale_sessions(max_age_hours=24)
    print(result)
asyncio.run(test())
"
# EXPECTED: SkillResult with success=True, data contains pruned_count (≥0)
# NOT expected: 'TypeError: post() got an unexpected keyword argument params'

# 4. Check ghost session count drops after fix
docker compose exec aria-db psql -U admin aria_warehouse -c \
  "SELECT status, COUNT(*) FROM engine_chat_sessions GROUP BY status;"
# EXPECTED: active count < 10 after running prune (was 72 before fix)
```

---

## Prompt for Agent

You are fixing a silent failure in Aria's session pruning system. 72 ghost
sessions have accumulated because `api_client.post()` silently rejects the
`params` keyword argument, causing `TypeError: post() got an unexpected keyword
argument 'params'` that prevents session cleanup from ever running.

**Files to read first:**
- `aria_skills/api_client/__init__.py` lines 1155–1185 (`get`, `post`, `patch` methods)
- `aria_skills/api_client/__init__.py` lines 1120–1155 (`_request_with_retry`)
- `aria_skills/agent_manager/__init__.py` lines 257–295 (`prune_stale_sessions`)
- `src/api/routers/engine_sessions.py` lines 348–375 (the cleanup endpoint)

**Problem:** `api_client.post()` signature is `(path, data=None)` — no `params`
parameter. The method calls `_request_with_retry("POST", path, json=data)` without
forwarding params. The `_request_with_retry` uses `**kwargs` so it CAN
handle params — they just aren't passed.

**Exact steps:**
1. Open `aria_skills/api_client/__init__.py` line 1169
2. Replace the `async def post(self, path: str, data: dict | None = None)` definition
   with the AFTER block from the Fix section (adds `params=None`, passes to request)
3. Run `grep -A8 "async def post" aria_skills/api_client/__init__.py | grep params`
   to confirm the change
4. Run `pytest tests/ -k "api_client" -v` to confirm existing tests pass
5. In Docker, call `prune_stale_sessions` and confirm it no longer throws TypeError

**Constraints to obey:** #1 (5-layer — fix is in api_client only), #4 (Docker-first).
**Verification:** see Verification section above.
