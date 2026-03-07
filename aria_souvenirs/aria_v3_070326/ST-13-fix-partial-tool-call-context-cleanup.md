# ST-13: Fix Partial Tool-Call Context Cleanup — tool_call_id Orphan Bug

**Epic:** E12 — Streaming Pipeline Correctness | **Priority:** P0 | **Points:** 3 | **Phase:** 1
**Status:** NOT STARTED | **Reported:** 2026-03-07

---

## Problem

Production session `a5c4e594-4d25-482b-b65c-a6f8e0c926da` crashed at 20:46 UTC
with:

```
litellm.BadRequestError: MoonshotException - Invalid request: an assistant
message with 'tool_calls' must be followed by tool messages responding to
each 'tool_call_id'. The following tool_call_ids did not have response
messages: :0
```

`aria_engine/streaming.py` lines 1376–1385, function `_build_context`, step 3
("Rebuild: after each assistant with tool_calls, inject its tool results"):

```python
# line 1376
owned_ids = [tc.get("id", "") for tc in m["tool_calls"]]
# line 1377
existing = [tool_msgs_by_id[tid] for tid in owned_ids if tid in tool_msgs_by_id]
# line 1378 — BUG IS HERE
if existing:                        # ← truthy even if only 1 of N results found
    cleaned.append(m)               # appends assistant with ALL N tool_calls
    cleaned.extend(existing)        # appends only the partial M results
```

When a turn has 2+ tool calls (e.g. `:0` and `:1`) and context window pruning
drops the result for `:1`, `existing` has length 1 (truthy). The assistant
message with `tool_calls: [{id:":0"}, {id:":1"}]` is sent to Kimi with only
one tool result (`tool_call_id: ":0"`). Kimi rejects with the above error.

---

## Root Cause

`if existing:` only checks that SOME results are found. It should check that
ALL results are found (`len(existing) == len(owned_ids)`).

When `existing` is a partial match (M < N):

- **Current behaviour:** Assistant + M results appended → Kimi sees N tool_calls,
  M responses → `BadRequestError`
- **Correct behaviour:** Strip the `(N - M)` unmatched tool_calls from the
  assistant message before appending, OR if ALL are missing: strip all and
  keep the text content only

---

## Fix

**File:** `aria_engine/streaming.py`
**Lines:** 1376–1392 (step 3 of context post-processing in `_build_context`)

### BEFORE (lines 1373–1392)

```python
        # 3. Rebuild: after each assistant with tool_calls, inject its tool results
        cleaned: list[dict[str, Any]] = []
        for m in non_tool_msgs:
            if m.get("tool_calls"):
                # Check which tool results exist for this assistant
                owned_ids = [tc.get("id", "") for tc in m["tool_calls"]]
                existing = [tool_msgs_by_id[tid] for tid in owned_ids if tid in tool_msgs_by_id]
                if existing:
                    cleaned.append(m)
                    cleaned.extend(existing)
                else:
                    # No tool results found — strip tool_calls, drop if empty
                    stripped = {k: v for k, v in m.items() if k != "tool_calls"}
                    if stripped.get("role") == "assistant" and not stripped.get("content"):
                        continue
                    cleaned.append(stripped)
```

### AFTER (lines 1373–1400, replacing above block)

```python
        # 3. Rebuild: after each assistant with tool_calls, inject its tool results
        cleaned: list[dict[str, Any]] = []
        for m in non_tool_msgs:
            if m.get("tool_calls"):
                # Check which tool results exist for this assistant
                owned_ids = [tc.get("id", "") for tc in m["tool_calls"]]
                existing = [tool_msgs_by_id[tid] for tid in owned_ids if tid in tool_msgs_by_id]
                found_ids = {tr["tool_call_id"] for tr in existing}

                if len(existing) == len(owned_ids):
                    # All tool results present — safe to include as-is
                    cleaned.append(m)
                    cleaned.extend(existing)
                elif existing:
                    # Partial match: strip tool_calls that have no result to avoid
                    # provider rejecting the message (e.g. Kimi BadRequestError)
                    surviving_calls = [
                        tc for tc in m["tool_calls"]
                        if tc.get("id", "") in found_ids
                    ]
                    entry = dict(m)
                    entry["tool_calls"] = surviving_calls
                    cleaned.append(entry)
                    cleaned.extend(existing)
                    logger.debug(
                        "Context repair: kept %d/%d tool_calls for assistant message "
                        "(evicted: %s)",
                        len(surviving_calls),
                        len(owned_ids),
                        [tid for tid in owned_ids if tid not in found_ids],
                    )
                else:
                    # No tool results found — strip tool_calls, drop if empty
                    stripped = {k: v for k, v in m.items() if k != "tool_calls"}
                    if stripped.get("role") == "assistant" and not stripped.get("content"):
                        continue
                    cleaned.append(stripped)
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Change is inside `aria_engine` only |
| 2 | .env for secrets (zero in code) | ❌ | Not applicable |
| 3 | models.yaml single source of truth | ❌ | Not applicable |
| 4 | Docker-first testing | ✅ | Run `pytest tests/ -k "streaming"` in container |
| 5 | aria_memories only writable path | ❌ | No file writes |
| 6 | No soul modification | ❌ | Not applicable |

---

## Dependencies

None — this is a self-contained fix in `_build_context`. ST-14 should be
applied after this to also add token budget enforcement, but this fix is
independently deployable and unblocks the crash immediately.

---

## Verification

```bash
# 1. Confirm the fix is applied
grep -n "len(existing) == len(owned_ids)" aria_engine/streaming.py
# EXPECTED: 1 match on the target line (≈ line 1381)

grep -n "surviving_calls" aria_engine/streaming.py
# EXPECTED: 2-3 matches in the repair block

# 2. Unit tests pass
pytest tests/ -k "streaming or context or tool_call" -v
# EXPECTED: all collected tests pass

# 3. Integration — simulate partial tool result context
# (manual or via fixture: create session with 2-tool turn, evict 1 result,
#  verify next call succeeds without BadRequestError)
docker compose exec aria-engine pytest tests/test_streaming.py -v
# EXPECTED: no MoonshotException / BadRequestError in test output
```

---

## Prompt for Agent

You are fixing a P0 production crash in Aria's chat streaming engine.

**Files to read first:**
- `aria_engine/streaming.py` lines 1275–1420 (entire `_build_context` method)
- `aria_engine/context_manager.py` lines 1–100 (for ContextManager reference)

**Problem:**
`aria_engine/streaming.py` line 1378: `if existing:` allows an assistant message
with N tool_calls to be sent to the LLM even when only M < N tool results exist.
Kimi rejects this with `BadRequestError: tool_call_id ":X" has no response message`.

**Exact steps:**
1. Open `aria_engine/streaming.py`
2. Find the `_build_context` method (line ~1275)
3. Navigate to step 3 "Rebuild" comment (line ~1373)
4. Replace the `if existing:` block with the AFTER block shown in the Fix section above
5. Ensure `logger.debug` call uses the existing `logger` instance (defined at
   module top: `logger = logging.getLogger("aria.engine.stream")`)
6. Run `grep -n "surviving_calls" aria_engine/streaming.py` to confirm the change
7. Run `pytest tests/ -k "streaming" -v` and confirm all tests pass
8. Apply change within Docker: `docker compose exec aria-engine pytest tests/ -k streaming`

**Constraints to obey:** #1 (5-layer), #4 (Docker-first).

**Verification commands:** see Verification section above.
