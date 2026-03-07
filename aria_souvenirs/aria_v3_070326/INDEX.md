# Aria v3 — Sprint Souvenir Index: March 7, 2026

**Triggered by:** Production crash — session `a5c4e594-4d25-482b-b65c-a6f8e0c926da`
**Status:** 5 tickets — ALL COMPLETED ✅
**Executed:** 2026-03-07 (tonight) | **Priority order:** ST-13 → ST-16 → ST-14 → ST-15 → ST-17

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `DAILY_AUDIT_070326.md` | Full 24h audit, bug inventory, session statistics |
| `SOUVENIR_070326.md` | **Daily highlights** — what Aria actually did, nice stuff from memories, sprint recap |
| `ST-13-fix-partial-tool-call-context-cleanup.md` | P0 — Fix tool_call_id orphan crash |
| `ST-14-token-budget-enforcement-context-build.md` | P0 — Add token budget to `_build_context` |
| `ST-15-aria-token-self-awareness.md` | P0 — Pre-flight guard + Aria context awareness |
| `ST-16-fix-ghost-sessions-prune-api-bug.md` | P1 — Fix silent TypeError killing session pruning |
| `ST-17-auto-trigger-memory-compression.md` | P1 — Wire memory compression into streaming |

---

## Bug Summary

| Ticket | File | Lines | Bug | Severity |
|--------|------|-------|-----|----------|
| ST-13 | `aria_engine/streaming.py` | 1376–1385 | `if existing:` allows partial tool-call orphans | 💀 P0 |
| ST-14 | `aria_engine/streaming.py` | 1285–1395 | No token budget — message count only | 💀 P0 |
| ST-15 | `aria_engine/streaming.py` | ~525 | Token estimate computed but never guarded | 💀 P0 |
| ST-16 | `aria_skills/api_client/__init__.py` | 1169 | `post()` missing `params=` → TypeError | ⚠️ P1 |
| ST-17 | `aria_engine/streaming.py` | — | No auto-compression for long sessions | ⚠️ P1 |

---

## Execution Order

```
Phase 1 (P0 — immediate, blocks user chat):
  ST-13  →  ST-16  (independent, can run in parallel)
  then:
  ST-14
  then:
  ST-15  (depends on ST-14 for _get_model_token_limits + models.yaml)

Phase 2 (P1 — this sprint):
  ST-17  (depends on ST-14 + ST-15)
```

---

## Hard Constraint Check

All 5 tickets comply with all 6 hard constraints:
1. ✅ 5-layer architecture — all changes are in `aria_engine` or `aria_skills/api_client`
2. ✅ No secrets in code
3. ✅ models.yaml extended (ST-14/ST-15) — `safe_prompt_tokens` per model
4. ✅ Docker-first all tickets
5. ✅ No write outside `aria_memories/` (compression artifacts go to `aria_memories/memory/`)
6. ✅ No soul modification

---

## Token Count Before/After Expectation

| Scenario | Before | After (ST-13+ST-14+ST-15+ST-17) |
|----------|--------|----------------------------------|
| Session with 50 messages, large tool results | 247K tokens crashed | <120K with budget gate |
| Multi-tool turn with 1 evicted result | BadRequestError | Partial tool_calls stripped, clean context |
| Token at 80% of limit | No warning | "CONTEXT MONITOR" injected, user alerted |
| Token at 100% of limit | Provider crash | Pre-flight guard blocks call, user told to compress |
| Ghost sessions in DB | 72 active | <5 after prune runs correctly |
