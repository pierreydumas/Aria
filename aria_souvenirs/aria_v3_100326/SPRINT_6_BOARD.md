# Sprint 6 — Memory Pipeline & Model Hygiene
**Sprint:** 6  
**Created:** 2026-03-10  
**Total Points:** 23  
**Theme:** Fix dead-end memory pipelines, enforce models.yaml as single source of truth, serialization bugs

---

## Board

| ID | Title | Priority | Pts | Status | Assignee |
|----|-------|----------|-----|--------|----------|
| SP6-T1 | Semantic Memory Pipeline — Consolidation Dead End | P0 (AA+) | 8 | Open | — |
| SP6-T2 | Heartbeat Reflection Output — Dead End to pgvector | P1 | 3 | Open | — |
| SP6-T3 | Skill Activity Details Invisible to Embeddings | P1 | 5 | Open | — |
| SP6-T4 | Token Router — Hardcoded Model Names | P2 | 2 | Open | — |
| SP6-T5 | SkillResult JSON Serialization Bug | P1 | 2 | Open | — |
| SP6-T6 | Importance Scoring Bifurcation | P3 | 3 | Open | — |

---

## SP6-T1 · Semantic Memory Pipeline — Consolidation Dead End
**Priority:** P0 (AA+) · **Points:** 8 · **Status:** Open

**Problem:** The 3-tier consolidation (`surface → medium → deep`) writes to local files in `aria_memories/knowledge/` and `aria_memories/deep/` but never reaches pgvector `semantic_memories`. Consolidated insights are invisible to semantic search.

**Evidence:**
- `aria_mind/memory.py`: `_promote_medium_to_deep()` writes to `knowledge/` files
- `aria_mind/heartbeat.py`: `remember_short()` stores to surface memory only
- Only path to pgvector: `activity_log/thoughts → seed_memories → semantic_memories`
- Consolidation output never creates thoughts or activities

**Impact:** Aria's deepest reflections and distilled wisdom never become searchable. Semantic memory only contains raw activities/thoughts.

**Acceptance Criteria:**
- [ ] Consolidation creates thoughts/activities when promoting to deep
- [ ] Deep entries are seeded into pgvector via `seed_memories`
- [ ] Semantic search returns consolidated insights
- [ ] Test: promote medium memory → verify it appears in semantic search

**Files:** `aria_mind/memory.py` · `aria_mind/heartbeat.py` · `src/api/routers/memories.py`

**Notes:** Must go through API layer (5-layer compliance). Consolidation → `api_client.create_thought()` or `api_client.create_activity()` → seed_memories.

---

## SP6-T2 · Heartbeat Reflection Output — Dead End to pgvector
**Priority:** P1 · **Points:** 3 · **Status:** Open

**Problem:** `heartbeat.py` calls `remember_short(reflection_output)` at end of reflection cycles. Stores to surface memory (file-based) but never reaches pgvector.

**Evidence:**
- `aria_mind/heartbeat.py`: `self.memory.remember_short(reflection, "reflection")`
- `remember_short()` → surface tier → consolidation → files (dead end)
- Reflection output = self-assessments, goal progress reviews — high-value content

**Impact:** Valuable self-reflection content lost to semantic search. Aria cannot semantically recall her own reflections.

**Acceptance Criteria:**
- [ ] Reflection output creates thought via `api_client.create_thought(category="reflection")`
- [ ] Thought picked up by `seed_memories` and embedded in pgvector
- [ ] Test: run heartbeat reflection → verify thought in `semantic_memories`

**Files:** `aria_mind/heartbeat.py`

---

## SP6-T3 · Skill Activity Details Invisible to Embeddings
**Priority:** P1 · **Points:** 5 · **Status:** Open

**Problem:** Skills log activities with `_persist_activity()`, but content stored under custom keys is not picked up by `seed_memories` which looks for `result_preview` and `args_preview` fields.

**Evidence:**
- `experiment`: stores "experiment_name", "tags", "status"
- `fact_check`: stores "claim", "verdict"
- `memeothy`: stores "prophecy", "offering"
- `seed_memories`: looks for `result_preview`, `args_preview`, `content` — misses all of the above

**Impact:** Activity entries exist in DB but embedding text is too sparse. Skill-specific details don't make it into vectors.

**Acceptance Criteria:**
- [ ] `_persist_activity()` includes `result_preview` with human-readable summary
- [ ] OR: `seed_memories` extracts from known skill-specific keys
- [ ] Test: create experiment activity → verify semantic_memory contains experiment name + tags

**Files:** `aria_skills/experiment/__init__.py` · `aria_skills/fact_check/__init__.py` · `aria_skills/memeothy/__init__.py` · `src/api/routers/memories.py`

---

## SP6-T4 · Token Router — Hardcoded Model Names
**Priority:** P2 · **Points:** 2 · **Status:** Open

**Problem:** Aria's self-created `token_router` skill has hardcoded model names (`qwen3-mlx`, `trinity-free`, `kimi`, `deepseek-free`). Violates ZERO model names outside `models.yaml` rule.

**Evidence:**
- L167: `ModelTier.LOCAL: ["qwen3-mlx"]`
- L168: `ModelTier.FREE: ["trinity-free", "qwen3-next-free"]`
- L169: `ModelTier.PREMIUM: ["kimi"]`
- L170: `ModelTier.EXPERT: ["deepseek-free", "kimi"]`
- L239: fallback `["qwen3-mlx"][0]`

**Note:** Aria attempted self-fix (session 95ae6630) writing `ModelConfigLoader` to read from API dynamically, but `write_artifact` failed on parameter mismatch.

**Acceptance Criteria:**
- [ ] Token router fetches model list from API dynamically
- [ ] ZERO hardcoded model names
- [ ] Fallback uses `get_primary_model()` or API-fetched defaults

**Files:** `aria_memories/skills/token_router/__init__.py`

---

## SP6-T5 · SkillResult JSON Serialization Bug
**Priority:** P1 · **Points:** 2 · **Status:** Open

**Problem:** `conversation_summary` returns a `SkillResult` object that is not JSON serializable. Summary is generated and stored, but the return wrapper breaks.

**Evidence:**
- Session 013a8877: "Object of type SkillResult is not JSON serializable"
- Summary stored via `api_client.set_memory()` ✅
- Thought created via `api_client.create_thought()` ✅
- Only the return value fails

**Impact:** Skill works but response wrapper breaks JSON serialization. Aria can't display result cleanly.

**Acceptance Criteria:**
- [ ] Skill returns dict, not raw `SkillResult`
- [ ] OR: `SkillResult` implements `to_dict()` / `__json__()`
- [ ] Test: call conversation_summary → verify response is JSON serializable

**Files:** `aria_skills/conversation_summary/__init__.py` · `aria_skills/base.py`

---

## SP6-T6 · Importance Scoring Bifurcation
**Priority:** P3 · **Points:** 3 · **Status:** Open

**Problem:** Two independent importance scoring systems exist and never reconcile:
1. **File-based** (`aria_mind/memory.py`): scores up to 1.0 using keyword bonuses (+0.25 for "implemented", "created", "delivered"), category bonuses, content length
2. **pgvector** (`seed_memories`): fixed mapping from activity_type/thought_category (e.g. "goal_work" → 0.8, "heartbeat" → 0.3)

**Impact:** Memory prioritization inconsistent. A memory could be high-importance in one system and low in the other.

**Acceptance Criteria:**
- [ ] Unified scoring, or explicit mapping between the two systems
- [ ] When consolidation feeds into pgvector (SP6-T1), importance scores carry through

**Files:** `aria_mind/memory.py` · `src/api/routers/memories.py`

---

## Dependencies
```
SP6-T1 ← SP6-T6 (importance scores must carry through consolidation→pgvector)
SP6-T1 ← SP6-T2 (reflection dead-end is a subset of consolidation dead-end)
SP6-T3   (independent)
SP6-T4   (independent)
SP6-T5   (independent)
```

## Suggested Execution Order
1. **SP6-T5** (2 pts) — quick fix, unblocks skill return values
2. **SP6-T4** (2 pts) — quick fix, model hygiene
3. **SP6-T1** (8 pts) — core pipeline fix, unblocks T2 and T6
4. **SP6-T2** (3 pts) — trivial once T1 establishes the pattern
5. **SP6-T3** (5 pts) — skill-by-skill embedding enrichment
6. **SP6-T6** (3 pts) — scoring alignment, finish after T1
