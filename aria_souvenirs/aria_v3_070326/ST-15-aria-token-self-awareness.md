# ST-15: Pre-Flight Token Guard + Aria Context Self-Awareness

**Epic:** E12 — Streaming Pipeline Correctness | **Priority:** P0 | **Points:** 5 | **Phase:** 1
**Status:** NOT STARTED | **Reported:** 2026-03-07

---

## Problem

Even after ST-13 and ST-14 fix the token overflow and tool_call orphan bugs,
Aria has **zero self-awareness** about her own context size. She cannot:

1. Detect that a conversation is approaching the model's token limit
2. Tell the user "this conversation is getting long — consider starting a new one"
3. Trigger memory compression automatically before hitting the wall
4. Refuse to call a provider if the token estimate exceeds the hard limit

Currently in `aria_engine/streaming.py`, token estimation happens at the
**iteration start** (line ~525):

```python
iteration_input_tokens = self.gateway.estimate_tokens_for_messages(
    model=session.model,
    messages=messages,
)
```

This is **telemetry only** — it is not a guard. There is no code that checks
this value and takes protective action. The estimate is computed but then
ignored except for cost accounting.

---

## Root Cause

The token estimation call exists but its result is never compared against any
threshold. There is no:
- Model-specific soft limit (warn at 80%)
- Model-specific hard limit (refuse at 95%)
- Self-notice injection into Aria's context ("you are approaching your memory limit")
- Automatic memory compression trigger

Aria is driving a car at 150mph toward a cliff and the speedometer works but
no one is watching it.

---

## Fix

### Step 1: Add pre-flight token check in the iteration loop

**File:** `aria_engine/streaming.py`
**Location:** In the `for iteration in range(max_tool_iterations):` loop,
just AFTER the existing `iteration_input_tokens = ...` line (line ~525) and
BEFORE the `async for chunk in self.gateway.stream(...)` call.

```python
# ── Pre-flight token guard ────────────────────────────────────────────────
# Read per-model limits from models.yaml (soft=80%, hard=95% of context window)
# Fall back to safe defaults if models.yaml lookup fails.
_model_soft_limit, _model_hard_limit = self._get_model_token_limits(
    session.model or self.config.default_model
)

if iteration_input_tokens > _model_hard_limit:
    # Hard limit exceeded — refuse the call and surface a user-facing message
    logger.error(
        "Pre-flight hard limit: session=%s tokens=%d > hard_limit=%d — aborting turn",
        session_id, iteration_input_tokens, _model_hard_limit,
    )
    await self._send_json(websocket, {
        "type": "error",
        "message": (
            "This conversation has grown too long for me to continue reliably "
            f"({iteration_input_tokens:,} tokens). Please start a new session "
            "or ask me to summarize and compress this conversation first."
        ),
    })
    break

if iteration_input_tokens > _model_soft_limit and iteration == 0:
    # Soft limit — inject a self-awareness notice into Aria's context
    # (only on the first iteration of a user turn, not mid-tool-loop)
    _pct = int(iteration_input_tokens / _model_hard_limit * 100)
    messages.append({
        "role": "system",
        "content": (
            f"[CONTEXT MONITOR] This conversation is at {_pct}% of your "
            f"memory capacity ({iteration_input_tokens:,} / {_model_hard_limit:,} tokens). "
            "You MUST: (1) keep your response concise, (2) avoid unnecessary "
            "tool calls that produce large outputs, (3) consider informing the "
            "user that starting a new session would give you a fresh memory."
        ),
    })
    logger.warning(
        "Soft token limit reached: session=%s tokens=%d (%d%% of %d)",
        session_id, iteration_input_tokens, _pct, _model_hard_limit,
    )
```

### Step 2: Add `_get_model_token_limits` helper to `StreamManager`

Add this method to the `StreamManager` class (after `_filter_tools_for_turn`,
before `handle_connection`):

```python
def _get_model_token_limits(
    self, model: str
) -> tuple[int, int]:
    """Return (soft_limit, hard_limit) token counts for the given model.

    soft_limit = 80% of context window → inject self-awareness notice
    hard_limit = 95% of context window → refuse the provider call

    Values are read from models.yaml ``safe_prompt_tokens`` / ``context_window``
    fields (added by ST-14). Falls back to conservatively safe defaults.
    """
    try:
        from aria_models.loader import load_catalog, normalize_model_id
        catalog = load_catalog()
        model_def = catalog.get("models", {}).get(normalize_model_id(model), {})
        hard = model_def.get("safe_prompt_tokens") or model_def.get("context_window", 0)
        if not hard:
            hard = 100_000  # conservative default
        soft = int(hard * 0.80)
        return soft, hard
    except Exception:
        return 80_000, 100_000
```

### Step 3: Emit a `context_warning` WS event so the UI can surface the alert

In `streaming.py`, the `_send_json` infrastructure already handles all event
types. Add the context warning emission alongside the soft-limit system message
injection (inside the `if iteration_input_tokens > _model_soft_limit` block):

```python
    await self._send_json(websocket, {
        "type": "context_warning",
        "used_tokens": iteration_input_tokens,
        "limit_tokens": _model_hard_limit,
        "percent_full": _pct,
        "message": f"Conversation memory {_pct}% full",
    })
```

The frontend (`src/web/templates/engine_chat.html`) can display a yellow banner
for this event type. (Frontend change is out of scope for this ticket — logged
as a separate P2 UI ticket.)

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Engine layer only; no DB or skill imports |
| 2 | .env for secrets (zero in code) | ❌ | Not applicable |
| 3 | models.yaml single source of truth | ✅ | Relies on `safe_prompt_tokens` added by ST-14 |
| 4 | Docker-first testing | ✅ | Verify via container logs and test suite |
| 5 | aria_memories only writable path | ❌ | No file writes |
| 6 | No soul modification | ❌ | Not applicable |

---

## Dependencies

- **ST-14 must complete first** — this ticket reads `safe_prompt_tokens` from
  models.yaml which ST-14 adds. If ST-14 is not done, `_get_model_token_limits`
  falls back to the 100K default, which is safe but not model-accurate.
- **ST-13 should be done first** — fixes the immediate crash; ST-15 adds
  prevention to stop it reaching the crash threshold.

---

## Verification

```bash
# 1. Helper method exists in StreamManager
grep -n "_get_model_token_limits" aria_engine/streaming.py
# EXPECTED: at least 2 matches (definition + call)

# 2. Pre-flight guard block exists
grep -n "_model_hard_limit" aria_engine/streaming.py
# EXPECTED: 3+ matches (assignment, comparison, log)

# 3. Soft limit injection logic exists
grep -n "CONTEXT MONITOR" aria_engine/streaming.py
# EXPECTED: 1 match (the injected system message template)

# 4. context_warning WS event emitted
grep -n "context_warning" aria_engine/streaming.py
# EXPECTED: 1 match

# 5. Unit tests pass
pytest tests/ -k "streaming" -v
# EXPECTED: all collected tests pass

# 6. Integration — simulate approaching soft limit
# Create a session, flood it with messages until tokens > 80K, verify:
# - "context_warning" event appears in WS output
# - System message "[CONTEXT MONITOR]" appears injected in chat
# - Hard limit triggers "error" event with human-readable message
docker compose exec aria-engine python -m pytest tests/ -k "token_guard" -v
# EXPECTED: 0 failures
```

---

## Prompt for Agent

You are adding pre-flight token awareness to Aria's streaming engine so that
she can detect and respond to context overflow BEFORE the provider rejects her.

**Files to read first:**
- `aria_engine/streaming.py` lines 510–560 (iteration loop start, around
  `iteration_input_tokens = self.gateway.estimate_tokens_for_messages(...)`)
- `aria_engine/streaming.py` lines 170–220 (StreamManager class setup, to find
  where to add the helper method)
- `aria_engine/streaming.py` lines 1275–1420 (`_build_context` — for context)
- `aria_models/models.yaml` (verify `safe_prompt_tokens` exists from ST-14)
- `aria_engine/config.py` lines 40–80 (`default_max_tokens`, `default_model`)

**Problem:** `iteration_input_tokens` is computed (line ~525) but never acted on.
There is no guard that stops the provider call when tokens exceed the model limit,
and Aria never sees her own context size.

**Exact steps:**
1. Find the `iteration_input_tokens = self.gateway.estimate_tokens_for_messages(...)`
   line (around line 525)
2. Immediately AFTER that line, insert the pre-flight guard block from Fix Step 1
3. Find a good location after `_filter_tools_for_turn` in StreamManager for the
   new helper method; insert `_get_model_token_limits` from Fix Step 2
4. Inside the soft-limit `if` block, add the `context_warning` WS event from Fix Step 3
5. Run `pytest tests/ -k "streaming" -v` and confirm all pass
6. Test manually: `docker compose restart aria-engine` then observe logs for
   `"Soft token limit reached"` or `"Pre-flight hard limit"` messages

**Constraints:** #1 (5-layer), #3 (models.yaml), #4 (Docker-first).
**Verification commands:** see Verification section above.
