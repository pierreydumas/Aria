# ST-17: Auto-Trigger Memory Compression for Long Conversations

**Epic:** E12 — Streaming Pipeline Correctness | **Priority:** P1 | **Points:** 5 | **Phase:** 2
**Status:** NOT STARTED | **Reported:** 2026-03-07

---

## Problem

Session `a5c4e594-4d25-482b-b65c-a6f8e0c926da` reached **247,754 input tokens**
with no automatic intervention. The `memory_compression` skill exists (verified
in sprint E10-S58, at `aria_skills/memory_compression/`) and can summarize
conversation history — but it is **never called automatically** when a
conversation grows long.

Current state:
- Memory compression is only triggered by: (a) cron jobs, or (b) manual invocation
- There is no hook that says: "conversation > 80% of model context limit → compress"
- When a session crosses the token threshold, the only outcome is failure (BUG-2/BUG-3)
  or the user seeing an error message (after ST-15).

A better outcome: **at ~70% of token limit**, proactively summarize the
conversation into a compact memory artifact, replace verbose middle history
with the summary, and continue the session with headroom.

---

## Root Cause

There is no integration between the token estimation in the streaming loop and
the memory compression skill. These two systems:

1. `aria_engine/streaming.py` — knows current token count (`iteration_input_tokens`)
2. `aria_skills/memory_compression/` — can compress conversation history

...have never been wired together.

---

## Fix

### Design Overview

The fix adds a **compression trigger** in `StreamManager._build_context`:

- If after context assembly, estimated tokens > 70% of model limit →
  compress the middle portion of the conversation into a summary artifact
- The summary is stored as a `aria_memories/` file AND as a system message
  injected at the compression point in the conversation
- The old verbose middle messages are replaced with a single summary message
- The session's `metadata` is updated with a `compression_applied: true` flag

### Step 1: Check if memory_compression skill is available

Before modifying the streaming engine, verify the skill is wired into
`ToolRegistry`. If `aria_skills/memory_compression/` is not in the registry,
it must be registered.

```bash
grep -rn "memory_compression" aria_engine/tool_registry.py aria_skills/catalog.py
```

### Step 2: Add `_maybe_compress_context` helper to `StreamManager`

**File:** `aria_engine/streaming.py`
**Location:** Add as a method of `StreamManager` (before `_get_model_token_limits`
   from ST-15, or after it):

```python
async def _maybe_compress_context(
    self,
    db,
    session,
    messages: list[dict[str, Any]],
    token_count: int,
    soft_threshold: int,
) -> list[dict[str, Any]]:
    """Compress middle conversation history when approaching token limits.

    If token_count > soft_threshold (70% of model limit):
    1. Identify the "middle" messages (skip system + first message + last 20)
    2. Call memory_compression via the tool registry
    3. Replace middle messages with a single summary system message
    4. Store the summary in aria_memories/ (tool does this)
    5. Update session metadata with compression timestamp

    Returns the (possibly compressed) messages list.
    """
    if token_count <= soft_threshold:
        return messages

    # Find boundaries: pinned head (system + first user msg) and
    # pinned tail (last 20 messages we always keep for context continuity)
    TAIL_SIZE = 20
    head_end = 0
    for i, m in enumerate(messages):
        if m.get("role") == "system" or (i <= 1 and m.get("role") == "user"):
            head_end = i + 1

    if len(messages) <= head_end + TAIL_SIZE + 2:
        # Nothing in the middle to compress
        logger.debug("Context: not enough middle messages to compress (skipping)")
        return messages

    tail_start = max(head_end + 1, len(messages) - TAIL_SIZE)
    head_messages = messages[:head_end]
    middle_messages = messages[head_end:tail_start]
    tail_messages = messages[tail_start:]

    if not middle_messages:
        return messages

    # Build request for memory_compression skill
    conversation_text = "\n\n".join(
        f"[{m.get('role', '?').upper()}] {m.get('content', '')[:2000]}"
        for m in middle_messages
        if m.get("content")
    )
    if not conversation_text.strip():
        return messages

    try:
        compression_result = await self.tools.execute(
            tool_call_id=f"compress_{session.id}_{int(time.monotonic())}",
            function_name="memory_compression__compress_conversation",
            arguments=json.dumps({
                "content": conversation_text,
                "session_id": str(session.id),
                "context": "auto-compression: conversation approaching token limit",
            }),
        )
        if compression_result.success:
            import json as _json
            summary_data = _json.loads(compression_result.content) if isinstance(compression_result.content, str) else {}
            summary_text = summary_data.get("summary") or summary_data.get("compressed") or ""
            if summary_text:
                summary_message = {
                    "role": "system",
                    "content": (
                        "[CONVERSATION SUMMARY — earlier context compressed]\n"
                        f"{summary_text}"
                    ),
                }
                compressed = head_messages + [summary_message] + tail_messages
                logger.info(
                    "Context compression applied: session=%s "
                    "middle=%d msgs compressed, new total=%d msgs",
                    session.id, len(middle_messages), len(compressed),
                )
                return compressed
    except Exception as exc:
        logger.warning("Context compression failed (non-fatal): %s", exc)

    return messages
```

### Step 3: Call `_maybe_compress_context` from `_build_context`

**File:** `aria_engine/streaming.py`
**Location:** In `_build_context`, after the token budget enforcement from ST-14,
add one call before the final `return`:

```python
        # ── Auto-compress if approaching soft token limit ──────────────────
        # Resolve soft threshold (70% of model limit)
        _soft, _hard = self._get_model_token_limits(
            session.model or self.config.default_model
        )
        _compression_threshold = int(_soft * 0.875)  # 70% of hard limit
        if estimated_tokens > _compression_threshold:
            messages = await self._maybe_compress_context(
                db=db,
                session=session,
                messages=messages,
                token_count=estimated_tokens,
                soft_threshold=_compression_threshold,
            )

        return messages
```

(Note: `estimated_tokens` is the token count you should compute using
`self._ctx_manager.estimate_tokens(messages, model_name)` after the token budget
step from ST-14.)

### Step 4: Ensure `memory_compression__compress_conversation` tool exists

Check `aria_skills/memory_compression/skill.json` and `__init__.py` to confirm
the tool name. If it's different (e.g. `memory_compression__compress`), use
that name instead.

```bash
grep -A5 '"name"' aria_skills/memory_compression/skill.json | head -20
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer (DB→ORM→API→api_client→Skills→Agents) | ✅ | Engine calls skill via ToolRegistry — correct path |
| 2 | .env for secrets (zero in code) | ❌ | Not applicable |
| 3 | models.yaml single source of truth | ✅ | Uses `safe_prompt_tokens` from ST-14 via `_get_model_token_limits` |
| 4 | Docker-first testing | ✅ | Full integration test requires Docker with all services up |
| 5 | aria_memories only writable path | ✅ | Compressed summaries written to `aria_memories/` by the compression skill |
| 6 | No soul modification | ❌ | Not applicable |

---

## Dependencies

- **ST-14 must complete first** — this ticket uses `_get_model_token_limits()` 
  (from ST-15) and the token budget estimates (from ST-14).
- **ST-15 must complete first** — `_get_model_token_limits()` is added by ST-15.
- **Verify `memory_compression` skill** is registered in ToolRegistry before
  implementing the `tools.execute()` call.

---

## Verification

```bash
# 1. Helper method exists in StreamManager
grep -n "_maybe_compress_context" aria_engine/streaming.py
# EXPECTED: 2+ matches (definition + call in _build_context)

# 2. Compression threshold calculation exists
grep -n "_compression_threshold" aria_engine/streaming.py
# EXPECTED: 2 matches

# 3. memory_compression skill exists and is registered
grep -rn "memory_compression" aria_engine/tool_registry.py
# EXPECTED: at least 1 match confirming skill is registered

# 4. Unit tests pass
pytest tests/ -k "streaming or context_manager or memory" -v
# EXPECTED: all collected tests pass

# 5. Integration: confirm compression log line appears for long sessions
# (requires a session with 80K+ tokens to trigger)
docker compose logs aria-engine --since 5m | grep "Context compression applied"
# EXPECTED (after triggering a long session):
# Context compression applied: session=... middle=XX msgs compressed, new total=XX msgs

# 6. Verify compressed summary written to aria_memories/
ls aria_memories/memory/ | grep "compress"
# EXPECTED: one or more files created by the compression skill
```

---

## Prompt for Agent

You are wiring Aria's memory compression skill into the streaming engine so
that long conversations trigger automatic summarization before they hit the
token limit, instead of crashing or showing an error.

**Files to read first:**
- `aria_engine/streaming.py` lines 1275–1420 (`_build_context` method)
- `aria_engine/streaming.py` lines 125–180 (`StreamManager` methods area)
- `aria_skills/memory_compression/__init__.py` (full file — understand
  interface: what method names, what args, what return shape)
- `aria_skills/memory_compression/skill.json` (confirm tool name format)
- `aria_engine/tool_registry.py` lines 1–80 (understand `execute()` interface)

**Problem:** No memory compression triggers exist for long conversations.
The solution is a new `_maybe_compress_context` method called from `_build_context`
when token count exceeds 70% of the model limit.

**Exact steps:**
1. Read `aria_skills/memory_compression/__init__.py` and `skill.json`
   to find the correct tool name for the compression method
2. Add `_maybe_compress_context()` to `StreamManager` per Fix Step 2 above
   (adjust tool name from step 1 if different)
3. Read `_build_context` (lines 1275–1420) — find the `return messages` at the end
4. Before the return, add the compression trigger from Fix Step 3 above
5. Compute `estimated_tokens` using `self._ctx_manager.estimate_tokens(messages, model_name)`
   before the trigger — or reuse the token count from Step 14's budget block
6. Run `pytest tests/ -k "streaming" -v`
7. `docker compose restart aria-engine` and verify logs

**Constraints:** #1 (5-layer via ToolRegistry), #3 (models.yaml via ST-15),
#4 (Docker-first), #5 (aria_memories is writable path for compressed artifact).
**Verification:** see Verification section above.
