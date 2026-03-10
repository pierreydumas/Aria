# SP6-T1: Semantic Memory Pipeline — Consolidation Dead End
**Priority:** P0 (AA+)  
**Points:** 8  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
The 3-tier memory consolidation pipeline (`surface → medium → deep`) writes to local files in `aria_memories/knowledge/` and `aria_memories/deep/` but **never reaches pgvector semantic_memories**. This means Aria's consolidated insights are invisible to semantic search.

### Evidence
- `aria_mind/memory.py`: `_promote_medium_to_deep()` writes to `knowledge/` files
- `aria_mind/heartbeat.py`: `remember_short()` calls store to surface memory only
- The only path to pgvector is: `activity_log/thoughts → seed_memories → semantic_memories`
- Consolidation output never creates thoughts or activities

## Impact
- HIGH: Aria's deepest reflections and consolidated knowledge never become searchable
- Semantic memory only contains raw activities and thoughts, not distilled wisdom

## Acceptance Criteria
- [ ] Consolidation pipeline creates thoughts or activities when promoting to deep
- [ ] Deep memory entries are seeded into pgvector via `seed_memories`
- [ ] Semantic search returns consolidated insights
- [ ] Test: promote a medium memory → verify it appears in semantic search

## Files Affected
- `aria_mind/memory.py` (consolidation logic)
- `aria_mind/heartbeat.py` (trigger point)
- `src/api/routers/memories.py` (seed_memories endpoint)

## Architecture Notes
- Must go through API layer (5-layer compliance)
- Consolidation → `api_client.create_thought()` or `api_client.create_activity()` → seed_memories
