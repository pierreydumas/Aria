# SP6-T6: Importance Scoring Bifurcation
**Priority:** P3  
**Points:** 3  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
Two independent importance scoring systems exist and never reconcile:
1. `aria_mind/memory.py`: File-based scoring with work output keywords, category bonuses, content length
2. `seed_memories` (pgvector): Simple importance from activity_type/thought_category mapping

### Evidence
- `memory.py`: Scores up to 1.0 using semantic analysis (implemented, created, delivered keywords +0.25 bonuses)
- `seed_memories`: Maps activity types to fixed importance levels (e.g., "goal_work" → 0.8, "heartbeat" → 0.3)
- Neither system feeds into the other

## Impact
- LOW: Memory prioritization is inconsistent between file-based and pgvector systems
- A memory could be high-importance in one system and low in the other

## Acceptance Criteria
- [ ] Unified importance scoring, or explicit mapping between the two systems
- [ ] When consolidation feeds into pgvector (SP6-T1), importance scores carry through

## Files Affected
- `aria_mind/memory.py` (file-based scoring)
- `src/api/routers/memories.py` (seed_memories importance mapping)
