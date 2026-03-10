# SP6-T2: Heartbeat Reflection Output — Dead End to pgvector
**Priority:** P1  
**Points:** 3  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
`heartbeat.py` calls `remember_short(reflection_output)` at the end of reflection cycles. This stores to surface memory (file-based) but **never reaches pgvector**.

### Evidence
- `aria_mind/heartbeat.py`: `self.memory.remember_short(reflection, "reflection")`
- `remember_short()` → surface tier → consolidation → files (dead end)
- Reflection output contains Aria's self-assessments, goal progress reviews — high-value content

## Impact
- MEDIUM: Valuable self-reflection content is lost to semantic search
- Aria cannot semantically recall her own reflections

## Acceptance Criteria
- [ ] Reflection output creates a thought via `api_client.create_thought(category="reflection")`
- [ ] Thought is picked up by `seed_memories` and embedded in pgvector
- [ ] Test: run heartbeat reflection → verify thought appears in semantic_memories

## Files Affected
- `aria_mind/heartbeat.py` (reflection output handling)
