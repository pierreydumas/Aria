# Streaming & Tool Pipeline — Full Review Project

## Mission
Stabilize Aria chat streaming and tool execution pipeline end-to-end, reduce latency/cost regressions, and remove behavior band-aids by moving to deterministic orchestration.

## Scope
- Web chat event handling (`src/web/templates/engine_chat.html`)
- WS API boundary (`src/api/routers/engine_chat.py`)
- Streaming orchestrator (`aria_engine/streaming.py`)
- Model gateway (`aria_engine/llm_gateway.py`)
- Tool execution (`aria_engine/tool_registry.py`)
- Session replay/history (`aria_engine/session_manager.py`)
- DB message schema (`src/api/db/models.py`)
- WS/integration/e2e tests (`tests/**`)

## Executive Summary (Validated)
1. Tool turns are often executed with a stream pass plus a second complete pass, which can inflate latency/cost.
2. Current `tool_result` WS payload shape does not fully match frontend expectations.
3. Message replay path lacks normalized tool linkage fields needed by UI (`tool_call_id`/`tool_results`).
4. Streaming usage accounting is incomplete for all stream-only paths.
5. Circuit-breaker handling differs between `complete()` and `stream()` paths.
6. The promised-action regex repair in `streaming.py` works as a P0 safety net, but remains heuristic.

---

## Project Plan

### Phase 1 (P0): Contract & Correctness Hardening (Days 1-3)
Goal: eliminate immediate user-visible failures and protocol mismatch.

#### Ticket ST-01 — Normalize WS Event Contract
**Problem:** frontend expects `result/output/error/status/duration_ms`, backend sends mostly `content/success` for tool results.

**Fix:** emit backward-compatible superset payload for `tool_result`:
- Keep: `name`, `content`, `id`, `success`
- Add: `result`, `status`, `error`, `duration_ms`, `tool_call_id`, `protocol_version`, `trace_id`

**Verification:**
```bash
pytest tests/ -k "websocket or engine_chat" -v
```

**Acceptance Criteria:** UI tool cards render success/failure details without merge hacks in live stream.

#### Ticket ST-02 — Replay DTO Parity for Tool Cards
**Problem:** history reload path cannot always reconstruct tool cards.

**Fix:** include normalized tool linkage in session messages API:
- `tool_results`
- derived `tool_call_id` (from `tool_results.tool_call_id`)

**Verification:**
```bash
pytest tests/ -k "session_manager and messages" -v
```

**Acceptance Criteria:** opening old sessions shows complete tool cards + results from persisted history.

#### Ticket ST-03 — Feature-Flag Promised-Action Repair
**Problem:** regex repair is useful but heuristic.

**Fix:** gate repair path with env/config flag, default `on` for now, with counters:
- `repair_triggered`
- `repair_success`
- `repair_skipped`

**Verification:**
```bash
pytest tests/ -k "streaming" -v
```

**Acceptance Criteria:** repair behavior can be toggled safely and is observable.

---

### Phase 2 (P0/P1): Cost & State-Machine Refactor (Days 4-7)
Goal: remove duplicate model calls and convert to deterministic tool orchestration.

#### Ticket ST-04 — Deterministic Tool-Request Assembly from Stream Deltas
**Problem:** stream->complete fallback introduces duplicate provider roundtrip.

**Fix:** accumulate structured tool call deltas during stream and execute directly when complete call data is sufficient.

**Verification:**
```bash
pytest tests/ -k "stream and tool" -v
```

**Acceptance Criteria:** no second model completion call needed for standard tool-call turns.

#### Ticket ST-05 — Unified LLM Health Handling
**Problem:** circuit-breaker logic diverges between `complete()` and `stream()`.

**Fix:** route stream failures/successes through shared breaker accounting.

**Verification:**
```bash
pytest tests/ -k "llm_gateway and circuit" -v
```

**Acceptance Criteria:** breaker behavior is consistent across stream and complete paths.

#### Ticket ST-06 — Deterministic Turn State Machine
**Problem:** mixed orchestration paths increase edge-case behavior.

**Fix:** introduce explicit turn states:
- `accepted`
- `streaming`
- `tool_requested`
- `tool_executing`
- `followup_generation`
- `finalized`

**Verification:**
```bash
pytest tests/ -k "state_machine" -v
```

**Acceptance Criteria:** illegal transitions are blocked, and end state always emitted.

---

### Phase 3 (P1): Accounting, Idempotency, and Persistence Integrity (Days 8-10)
Goal: reliable billing/usage and duplicate-safe processing.

#### Ticket ST-07 — Usage Ledger for Streaming Turns
**Problem:** session totals can undercount streamed responses.

**Fix:** persist per-model-call usage records and compute session totals from ledger.

**Verification:**
```bash
pytest tests/ -k "usage and streaming" -v
```

**Acceptance Criteria:** session totals reconcile with ledger within 1%.

#### Ticket ST-08 — Client Message Idempotency Keys
**Problem:** content+time-window dedup is fragile.

**Fix:** add `client_message_id` support and enforce unique `(session_id, client_message_id)` for user turns.

**Verification:**
```bash
pytest tests/ -k "idempotency" -v
```

**Acceptance Criteria:** retried sends do not create duplicate user/assistant turns.

#### Ticket ST-09 — Atomic Session Counter Updates
**Problem:** non-atomic counters can drift under concurrency.

**Fix:** use SQL atomic increment expressions for counters.

**Verification:**
```bash
pytest tests/ -k "counter" -v
```

**Acceptance Criteria:** concurrent sends keep accurate totals.

---

### Phase 4 (P1/P2): Test Matrix + Rollout (Days 11-14)
Goal: prevent regressions and ship safely.

#### Ticket ST-10 — WS Contract Integration Tests
Add sequence assertions for:
- `stream_start`
- `content` / `thinking`
- `tool_call`
- `tool_result`
- `stream_end`

#### Ticket ST-11 — Replay Consistency Tests
Assert historical tool cards can be reconstructed purely from API messages.

#### Ticket ST-12 — Canary Rollout + Observability
Dashboards:
- repair trigger rate
- tool execution success rate
- tool-turn latency P50/P95
- model call count per user turn
- cost per successful tool-turn

**Verification:**
```bash
pytest tests/ -k "websocket or engine_chat or session_manager" -v
```

**Acceptance Criteria:** 48h canary with no P0 regressions.

---

## Constraints Check (Project-Level)
| # | Constraint | Applies | Notes |
|---|---|---|---|
| 1 | 5-layer architecture | ✅ | Work stays inside engine/API boundaries; no direct skill-to-skill DB shortcuts |
| 2 | Secrets in `.env` only | ✅ | No secrets added; config flags only |
| 3 | `models.yaml` source of truth | ✅ | No hardcoded model IDs introduced |
| 4 | Docker-first validation | ✅ | Verification commands are CI/local docker-friendly |
| 5 | `aria_memories` only writable for Aria | ✅ | This is developer-side code update flow, not runtime memory writer behavior |
| 6 | No soul modification | ✅ | No changes planned under `aria_mind/soul/` |

---

## Immediate Quick Wins (Today)
1. Ship `tool_result` payload superset with compatibility fields.
2. Add replay `tool_call_id` + `tool_results` in session messages endpoint.
3. Add `protocol_version` + `trace_id` to all stream events.
4. Gate promised-action repair behind a flag and track metrics.
5. Add one real WS integration test that asserts full event sequence.

## Success Metrics
- 30%+ reduction in tool-turn latency (P95)
- 20%+ reduction in model calls per tool-enabled turn
- <1% mismatch between usage ledger and session totals
- Zero “promise without execution” incidents in canary logs
- Zero UI missing-tool-result card incidents on replay
