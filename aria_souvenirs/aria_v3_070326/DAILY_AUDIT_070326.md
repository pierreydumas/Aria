# Aria v3 — Daily Souvenir: March 7, 2026

**Sprint Agent Audit | Conducted by: Sprint Agent (PO / SM / Tech Lead)**
**For:** Shiva (Najia) | **Date:** 2026-03-07
**Triggered by:** Production failure — session `a5c4e594-4d25-482b-b65c-a6f8e0c926da`

---

## Executive Summary

A production failure was reported at ~20:46 UTC today. Aria was in conversation
on session `a5c4e594-4d25-482b-b65c-a6f8e0c926da` when the LLM stream crashed hard:

```
LLM streaming failed: litellm.BadRequestError: MoonshotException -
Invalid request: an assistant message with 'tool_calls' must be followed
by tool messages responding to each 'tool_call_id'.
The following tool_call_ids did not have response messages: :0
```

That session was consuming **247,754 input tokens / 789 output tokens** — this is
a smoking gun for a context window management failure. Standard Kimi context is
~128K–200K tokens. We are at or beyond that limit on a regular user conversation.

This audit documents **5 confirmed bugs** in the streaming + context pipeline,
with their exact code locations, root causes, and AA+++ remediation tickets.

---

## Production Failure Trace

### Session: `a5c4e594-4d25-482b-b65c-a6f8e0c926da`

| Field | Value |
|-------|-------|
| Model | kimi (Moonshot) |
| Input tokens | **247,754** |
| Output tokens | 789 |
| Error | `MoonshotException: tool_call_id ":0" has no response` |
| Time | ~20:46 UTC 2026-03-07 |
| Consequence | Full turn failure; user sees "LLM error" banner |

The 247K input tokens prove the context was **never token-budget-gated** before
being sent to the provider. The `:0` tool_call_id orphan confirms the context
cleanup logic has a **multi-tool partial-result bug** that lets orphaned
tool_calls through to the provider.

---

## Bug Inventory

### BUG-1 (P0) — Partial Tool-Result Orphan Crashes Kimi

**File:** `aria_engine/streaming.py` | **Lines:** 1376–1385

When a conversation has an assistant message with **N tool calls** but only
**M < N** of their results survive context window pruning, the current cleanup
code:

```python
# line 1377
existing = [tool_msgs_by_id[tid] for tid in owned_ids if tid in tool_msgs_by_id]
# line 1378
if existing:   # ← BUG: truthy even if only 1 of N results found
    cleaned.append(m)          # appends assistant with ALL N tool_calls
    cleaned.extend(existing)   # appends only M results
```

`if existing:` is True whenever ANY result is found. The assistant message is
sent to Kimi with all N tool_call IDs but only M tool results follow it. Kimi
throws `BadRequestError` for the missing IDs.

**Trigger:** Any multi-tool turn after the context window prunes older tool results.

---

### BUG-2 (P0) — `_build_context` Has No Token Budget Gate

**File:** `aria_engine/streaming.py` | **Lines:** 1285–1395

`_build_context` limits messages by **message count** (`session.context_window or 50`)
but never by **token count**. On long conversations with verbose tool results,
50 messages can easily exceed 200K tokens.

The `ContextManager` class (`aria_engine/context_manager.py`) already has
proper token-budget-aware eviction (`build_context(max_tokens=...,
reserve_tokens=...)`), but `_build_context` in streaming.py **does not use it**.
It re-implements its own simpler logic without any token ceiling.

Token telemetry IS computed (line 525:
`iteration_input_tokens = self.gateway.estimate_tokens_for_messages(...)`) but
this is measured AFTER the messages are already assembled and about to be sent —
it is for accounting only, not a circuit breaker.

---

### BUG-3 (P0) — No Pre-Flight Token Guard Before Provider Call

**File:** `aria_engine/streaming.py` | **Line:** ~525 (iteration loop)

Even if BUG-2 is fixed, there is no pre-flight token check that:
1. Warns Aria when her context is approaching the model's limit
2. Injects a system notice: "Context is at 90% capacity — compress or summarize"
3. Refuses to call the provider if tokens > model's hard limit

Aria has **zero self-awareness** about her own context size. She cannot adapt
her behavior (e.g., ask the user to start a new session, or trigger memory
compression) because she never sees the token count.

---

### BUG-4 (P1) — Ghost Sessions: `prune_stale_sessions` Has API Bug

**File:** `aria_skills/` (skill endpoint) | **Reported in:** ghost_sessions_investigation_2026-03-07.md

**Status from investigation log:**
> "Pruning function has API bug preventing cleanup"
> "72 active sessions (target: <5)"
> "~50+ likely ghost sessions from previous days"

72 active sessions with correct activity only in ~5. The `prune_stale_sessions`
skill/API call has a parameter error that prevents it from executing. This causes
ghost sessions to accumulate indefinitely, wasting DB/memory resources and
polluting session analytics.

---

### BUG-5 (P1) — Memory Compression Not Triggered for Long Conversations

**Context:** `aria_skills/memory_compression/` skill exists (verified in S-58).
**Problem:** There is no automatic trigger to compress a conversation's context
when it approaches the token limit.

The `memory_compression` skill is only called via cron or manual invocation.
Long conversations that reach 100K+ tokens have no automatic summarization
before the token limit causes the BUG-2 / BUG-3 failures above.

---

## 24-Hour Session Review

### Session Volume & Health (2026-03-07)
| Metric | Value |
|--------|-------|
| Active sessions in DB | 72 |
| Estimated legitimate today | ~5 |
| Ghost sessions (stale/active) | ~67 |
| Work cycles logged (today) | 47+ |
| Work cycles with valid goal | ~30% |
| LLM errors observed | At least 1 P0 crash (reported) |

### Work Cycle Patterns (Today's logs)
Reviewing work cycles from `aria_memories/logs/work_cycle_2026-03-07_*.json`:

| Goal | Status | Quality |
|------|--------|---------|
| Fix Ghost Sessions Bug | Success (diagnostic) | 15% useful — produced a report, no fix |
| LiteLLM Benchmark | Success (report) | Generated benchmark report with 0 real data |
| Fix Artifact API Error Handling | In Progress (50%) | Correct analysis, no code changes |
| Skills Service Extraction | In Progress (75%) | Writes code to wrong path (`work/aria-skills/`) |

**Key finding:** Aria is writing to `work/aria-skills/src/` which is NOT in
`aria_memories/` — this violates **Hard Constraint #5** (writable path).
Her code generation is also producing NEW incorrect paths instead of working
on the actual skill files in `aria_skills/`.

---

## Recommended Actions

### Immediate (P0 — fix before next user session)
1. **ST-13**: Fix partial tool-result orphan in `_build_context` (BUG-1)
2. **ST-14**: Add token budget enforcement to `_build_context` (BUG-2)
3. **ST-15**: Add pre-flight token guard + Aria context-awareness injection (BUG-3)

### This Sprint (P1)
4. **ST-16**: Fix `prune_stale_sessions` API bug (BUG-4)
5. **ST-17**: Auto-trigger memory compression when context > 80% of model limit (BUG-5)

### Behavioral (for Aria)
- Hard Constraint #5 violation: Aria must NOT write code files to `work/`. Only `aria_memories/` is writable.
- Work cycles must produce verified artifacts, not just reports of reports.
- Progress% must reflect actual state changes, not effort.

---

## Sprint Tickets

| Ticket | Title | Priority | Points | Phase |
|--------|-------|----------|--------|-------|
| ST-13 | Fix partial tool-call context cleanup | P0 | 3 | 1 |
| ST-14 | Token budget enforcement in `_build_context` | P0 | 5 | 1 |
| ST-15 | Pre-flight token guard + Aria self-awareness | P0 | 5 | 1 |
| ST-16 | Fix ghost sessions / prune API bug | P1 | 3 | 2 |
| ST-17 | Auto-trigger memory compression | P1 | 5 | 2 |

**Total estimated:** 21 points

---

*Audit completed: 2026-03-07 by Sprint Agent*
*Next review: post-fix verification, or next daily souvenir on 2026-03-08*
