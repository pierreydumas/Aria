# Sprint 7 — Cognitive Depth & Autonomous Reasoning
**Sprint:** 7  
**Created:** 2026-03-12  
**Total Points:** 21  
**Theme:** Close the gaps between "autonomous agent" and "agent that reasons about its own approach"

---

## Board

| ID | Title | Priority | Pts | Status | Assignee |
|----|-------|----------|-----|--------|----------|
| SP7-01 | Consolidation→Semantic Bridge | P0 | 3 | ✅ Done | Claude |
| SP7-02 | Metacognition Active Strategy Routing | P0 | 5 | ✅ Done | Claude |
| SP7-03 | Plan-Execute-Verify-Reflect Loop | P0 | 8 | ✅ Done | Claude |
| SP7-04 | Dynamic Focus Auto-Switching | P1 | 3 | ✅ Done | Claude |
| SP7-05 | Semantic Memory Recall in process() | P0 | 5 | ✅ Done | Claude |
| SP7-06 | PEVR Integration in Heartbeat Goals | P1 | 3 | ✅ Done | Claude |
| SP7-07 | LLM-Powered Focus Classification | P2 | 2 | ✅ Done | Claude |
| SP7-08 | Memory Quality Feedback Loop | P2 | 3 | ✅ Done | Claude |

---

## SP7-01 · Consolidation→Semantic Bridge
**Priority:** P0 · **Points:** 3 · **Status:** ✅ Done

**Problem:** Consolidation pipeline wrote distilled wisdom to files but never pushed to pgvector. Semantic search couldn't find Aria's consolidated insights.

**Solution:** `memory.py` `consolidate()` now calls `api.store_memory_semantic()` for each category summary (importance=0.7) and each lesson (importance=0.85). Found already implemented.

**Files:** `aria_mind/memory.py`

---

## SP7-02 · Metacognition Active Strategy Routing
**Priority:** P0 · **Points:** 5 · **Status:** ✅ Done

**Problem:** `get_strategy_for_category()` and `predict_outcome()` existed in metacognition but were never used by `cognition.process()` to change execution behavior. Aria tracked her failures but never adapted.

**Solution:** Step 4 of `process()` now:
1. Calls `mc.get_strategy_for_category(task_category)` and `mc.predict_outcome()`
2. If strategy says `use_roundtable: True` → routes to `self._agents.roundtable()`
3. Adjusts `max_retries` based on strategy confidence
4. Injects strategy + prediction into context for agent awareness

**Acceptance Criteria:**
- [x] `process()` consults metacognition before execution
- [x] Roundtable routing triggers when strategy recommends it
- [x] Max retries adapt to category confidence
- [x] Strategy + prediction injected into agent context

**Files:** `aria_mind/cognition.py`

---

## SP7-03 · Plan-Execute-Verify-Reflect Loop
**Priority:** P0 · **Points:** 8 · **Status:** ✅ Done

**Problem:** `plan()` generated a plan as text. Nobody executed, verified, or reflected on it. No structured multi-step reasoning.

**Solution:** New `plan_execute_verify_reflect(goal, context)` method:
1. **Plan** — calls existing `plan()` for decomposition
2. **Execute** — runs each step, passing output N as context to step N+1
3. **Verify** — checks success per step, aborts after 3 consecutive failures
4. **Reflect** — LLM-powered reflection on outcomes, stored as `pevr_reflection` thought

Returns: `{plan, step_results, overall_success, failures, reflection}`

**Acceptance Criteria:**
- [x] PEVR method exists on Cognition
- [x] Steps execute sequentially with context propagation
- [x] Failure counting with early abort
- [x] LLM reflection on outcomes
- [x] Outcome recorded in metacognition
- [x] Reflection stored as thought

**Files:** `aria_mind/cognition.py`

---

## SP7-04 · Dynamic Focus Auto-Switching
**Priority:** P1 · **Points:** 3 · **Status:** ✅ Done

**Problem:** 7 focus modes existed but only switched manually. Crypto questions processed in Orchestrator mode with wrong model/skills.

**Solution:** Step 2.05 in `process()` calls `fm.get_focus_for_task(keywords)` before any processing. Focus switch cascades model hint, system prompt overlay, and skill affinity into context.

**Acceptance Criteria:**
- [x] Auto-detect focus from prompt keywords
- [x] Switch focus before processing
- [x] Inject focus overlay into context

**Files:** `aria_mind/cognition.py`

---

## SP7-05 · Semantic Memory Recall in process()
**Priority:** P0 · **Points:** 5 · **Status:** ✅ Done

**Problem:** Consolidation now pushes TO pgvector (SP7-01), but `process()` only recalls from short-term deque (keyword/recency). Aria can't pull semantically relevant memories during inference.

**Solution:** New Step 2.7 in `process()` calls `api_client.search_memories_semantic(prompt, limit=5, min_importance=0.3)`. Results injected as `context["semantic_memory"]`. Goes through api_client → /memories/search → pgvector cosine distance. Non-blocking on failure.

**Acceptance Criteria:**
- [x] `process()` queries pgvector with prompt embedding before agent delegation
- [x] Top-K semantic matches injected into context as `semantic_memory`
- [x] Relevance threshold prevents noise injection (min_importance=0.3)
- [x] Non-blocking: failure skipped with debug log

**Files:** `aria_mind/cognition.py`

---

## SP7-06 · PEVR Integration in Heartbeat Goals
**Priority:** P1 · **Points:** 3 · **Status:** ✅ Done

**Problem:** PEVR loop exists but heartbeat's `_check_goals()` still uses simple single-shot goal work. Complex goals deserve structured reasoning.

**Solution:** After goal moves to "doing", checks `_complex_signals` keywords (implement, build, research, etc.) + focus level L2/L3. Complex goals delegate to `cognition.plan_execute_verify_reflect()` with max 5 steps. PEVR success → 2x progress step. Failure → standard increment preserved.

**Acceptance Criteria:**
- [x] `_check_goals()` uses PEVR for goals with complexity signals at L2/L3
- [x] Simple goals still use direct approach (fast path)
- [x] PEVR reflection feeds back into goal progress tracking
- [x] Graceful fallback if PEVR fails

**Files:** `aria_mind/heartbeat.py`

---

## SP7-07 · LLM-Powered Focus Classification
**Priority:** P2 · **Points:** 2 · **Status:** ✅ Done

**Problem:** Focus auto-switching uses keyword matching which misses ambiguous queries.

**Solution:** New `classify_focus_llm(task_text, llm_skill)` on FocusManager. Uses local model (qwen3.5_mlx, cost=$0) with ~50 token prompt, max_tokens=32, temperature=0.1. Falls back to keyword matching if LLM unavailable. Wired into cognition Step 2.05: tries LLM first, keyword fallback second.

**Cost:** $0 — uses local model. If local is down, free-tier OpenRouter via litellm. Keyword matching always available as last resort.

**Acceptance Criteria:**
- [x] Single cheap LLM call for focus classification
- [x] Fallback to keyword matching if LLM unavailable
- [x] Wired into cognition.process() Step 2.05

**Files:** `aria_mind/soul/focus.py`, `aria_mind/cognition.py`

---

## SP7-08 · Memory Quality Feedback Loop
**Priority:** P2 · **Points:** 3 · **Status:** ✅ Done

**Problem:** No tracking of whether recalled memories were useful in responses. Consolidation can't distinguish high-utility memories from noise.

**Solution:** New `record_retrieval_quality(memory_id, was_used, source)` and `get_retrieval_quality_report()` on MemoryManager. Cognition Step 7.3 checks token overlap between semantic memories and the response. Per-memory stats (retrieved/used counts) persist in memory. Quality report exposed in `get_status()`. Noise candidates (retrieved 3+ times, never used) identified for consolidation pruning.

**Acceptance Criteria:**
- [x] Tag memories as used/unused after each response
- [x] Track retrieval hit rate per memory
- [x] Noise candidates identified (retrieved but never used)
- [x] Quality report in memory status

**Files:** `aria_mind/memory.py`, `aria_mind/cognition.py`
