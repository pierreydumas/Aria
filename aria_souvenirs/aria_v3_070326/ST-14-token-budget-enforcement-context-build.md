# ST-14: Token Budget Enforcement in `_build_context`

**Epic:** E12 — Streaming Pipeline Correctness | **Priority:** P0 | **Points:** 5 | **Phase:** 1
**Status:** NOT STARTED | **Reported:** 2026-03-07

---

## Problem

Session `a5c4e594-4d25-482b-b65c-a6f8e0c926da` sent **247,754 input tokens**
to Kimi in a single request. This is at or beyond Kimi's context window limit,
causes extreme latency (a 247K-token prompt at $0.0002/1K = ~$0.05 per turn),
and is the upstream enabler of BUG-1 (partial tool result orphans occur because
so many message pairs are being managed without a hard token ceiling).

`aria_engine/streaming.py` method `_build_context` (line 1275):

```python
# line 1290
window = session.context_window or 50   # ← message count only
# No token budget anywhere in this method
```

The `ContextManager` class in `aria_engine/context_manager.py` already implements
token-budget-aware eviction with:
- `build_context(all_messages, max_tokens, model, reserve_tokens)`
- litellm-based per-token counting
- Pinning system (system prompt always included, last N messages pinned)
- Score-based eviction for middle messages

But `_build_context` in streaming.py **does not use ContextManager**. It is an
independent reimplementation with only message-count culling.

---

## Root Cause

Two separate implementations of context assembly exist:
1. `ContextManager.build_context()` — token-budget-aware, in `context_manager.py`
2. `StreamManager._build_context()` — message-count-only, in `streaming.py`

The streaming path uses #2, which has no token ceiling. On conversations with
verbose tool results (e.g. large API responses, long search results), 50 messages
can produce 200K+ tokens.

---

## Fix

**File:** `aria_engine/streaming.py`
**Method:** `_build_context` (lines 1275–1395)

After the message assembly + cleanup steps (steps 1–3), pass the resulting
`messages` list through `ContextManager.build_context()` to apply a hard
token budget before returning.

### Step 1: Import / instantiate ContextManager

At the top of `StreamManager.__init__` (around line 118, after the existing
`self._repair_stats` assignment), add:

```python
# BEFORE (line ~127)
        self._repair_stats: dict[str, int] = {
            "triggered": 0,
            "succeeded": 0,
            "skipped_disabled": 0,
        }

# AFTER
        self._repair_stats: dict[str, int] = {
            "triggered": 0,
            "succeeded": 0,
            "skipped_disabled": 0,
        }
        # Context window manager for token-budget-aware message eviction
        from aria_engine.context_manager import ContextManager
        self._ctx_manager = ContextManager(config)
```

### Step 2: Apply token budget at the end of `_build_context`

At the very end of `_build_context`, just before `return messages` (line ~1395),
add:

```python
        # ── Token budget enforcement ──────────────────────────────────────
        # Apply ContextManager's token-aware eviction after the structural
        # cleanup above so that the final context fits within the model's limit.
        model_name = session.model or self.config.default_model
        # Reserve tokens for the model's response (session.max_tokens or default)
        reserve = session.max_tokens or self.config.default_max_tokens
        # Hard cap: use session's configured limit, fall back to a safe default
        # Kimi 128K hard cap; most models safe at 100K prompt budget
        max_prompt_tokens = max(4096, (session.context_window or 50) * 3000)
        messages = self._ctx_manager.build_context(
            all_messages=messages,
            max_tokens=max_prompt_tokens,
            model=model_name,
            reserve_tokens=reserve,
        )
        logger.info(
            "Context budget applied: session=%s model=%s max_prompt=%d reserve=%d → %d messages",
            session.id, model_name, max_prompt_tokens, reserve, len(messages),
        )
        return messages
```

Remove the bare `return messages` that was there before.

### Step 3: Add model-limit table to `aria_models/models.yaml`

Each model entry in `models.yaml` should have a `context_window` field so
the token budget can be set correctly per model. Add to the `kimi` entry:

```yaml
# BEFORE (in kimi model entry)
  kimi:
    display_name: "Kimi"
    provider: moonshot
    litellm:
      model: "moonshot/moonshot-v1-128k"
      api_key: "os.environ/MOONSHOT_API_KEY"

# AFTER
  kimi:
    display_name: "Kimi"
    provider: moonshot
    context_window: 131072       # 128K hard limit
    safe_prompt_tokens: 120000   # leave 8K for response
    litellm:
      model: "moonshot/moonshot-v1-128k"
      api_key: "os.environ/MOONSHOT_API_KEY"
```

Then update the token budget calculation in `_build_context` to use the
model's `safe_prompt_tokens` when available:

```python
        # Resolve per-model context limit from models.yaml
        try:
            from aria_models.loader import load_catalog, normalize_model_id
            catalog = load_catalog()
            model_def = catalog.get("models", {}).get(normalize_model_id(model_name), {})
            safe_tokens = model_def.get("safe_prompt_tokens", 0)
            max_prompt_tokens = safe_tokens if safe_tokens > 0 else max(
                4096, (session.context_window or 50) * 3000
            )
        except Exception:
            max_prompt_tokens = max(4096, (session.context_window or 50) * 3000)
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Change is inside `aria_engine` only |
| 2 | .env for secrets (zero in code) | ❌ | Not applicable |
| 3 | models.yaml single source of truth | ✅ | Per-model `context_window` + `safe_prompt_tokens` added to models.yaml |
| 4 | Docker-first testing | ✅ | Container restart required after models.yaml change |
| 5 | aria_memories only writable path | ❌ | No runtime file writes |
| 6 | No soul modification | ❌ | Not applicable |

---

## Dependencies

- **ST-13 must complete first** — ST-13 fixes the tool_call orphan cleanup;
  this ticket layers token budget on top. Both operate in `_build_context` but
  on different parts. Applying ST-14 second avoids conflicts from nearby edits.

---

## Verification

```bash
# 1. ContextManager is instantiated in StreamManager
grep -n "_ctx_manager" aria_engine/streaming.py
# EXPECTED: at least 2 matches (init + usage in _build_context)

# 2. Token budget log line appears in container logs after a message send
docker compose logs aria-engine --since 1m | grep "Context budget applied"
# EXPECTED: line like:
# Context budget applied: session=... model=kimi max_prompt=120000 reserve=4096 → 42 messages

# 3. models.yaml has context_window for kimi
grep -A2 "safe_prompt_tokens" aria_models/models.yaml
# EXPECTED: at least one match under a model entry

# 4. Unit tests pass
pytest tests/ -k "streaming or context_manager" -v
# EXPECTED: all collected tests pass

# 5. Regression: verify old long-context session no longer sends 247K tokens
# (manual: open a conversation with 100+ messages, confirm logs show < 120K budget)
```

---

## Prompt for Agent

You are fixing a P0 token overflow vulnerability in Aria's streaming engine.
A production conversation sent 247,754 tokens to Kimi, which is at the provider's
hard limit.

**Files to read first:**
- `aria_engine/streaming.py` lines 100–135 (StreamManager.__init__)
- `aria_engine/streaming.py` lines 1275–1420 (`_build_context` method)
- `aria_engine/context_manager.py` lines 1–100 (ContextManager interface)
- `aria_models/models.yaml` (full file — understand existing model entry format)
- `aria_engine/config.py` lines 1–80 (EngineConfig fields)

**Problem:** `_build_context` uses message-count windowing but no token budget.
`ContextManager.build_context()` has the right logic but is not called.

**Exact steps:**
1. Read `aria_engine/streaming.py` lines 100–135 to understand `StreamManager.__init__`
2. Add `self._ctx_manager = ContextManager(config)` at the end of `__init__`
   (import `from aria_engine.context_manager import ContextManager` at top of
   `__init__` or use local import inside the method)
3. Read `_build_context` (lines 1275–1420) — find the final `return messages`
4. Before that `return`, add the token budget block from the Fix section Step 2
5. Read `aria_models/models.yaml` — find the `kimi` entry and add
   `context_window: 131072` and `safe_prompt_tokens: 120000`
6. Update the token budget calculation to read from models.yaml (Fix section Step 3)
7. Remove the old bare `return messages`
8. Run `pytest tests/ -k "streaming or context_manager" -v`
9. Rebuild and restart: `docker compose restart aria-engine`
10. Check logs: `docker compose logs aria-engine --since 1m | grep "Context budget"`

**Constraints to obey:** #1 (5-layer), #3 (models.yaml), #4 (Docker-first).

**Verification commands:** see Verification section above.
