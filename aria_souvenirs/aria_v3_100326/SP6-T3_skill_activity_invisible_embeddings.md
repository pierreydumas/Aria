# SP6-T3: Skill Activity Details Invisible to Semantic Embeddings
**Priority:** P1  
**Points:** 5  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
Skills (experiment, fact_check, memeothy) log activities with `_persist_activity()`, but the content stored under custom keys is not picked up by `seed_memories` which looks for `result_preview` and `args_preview` fields.

### Evidence
- `aria_skills/experiment/__init__.py`: stores under "experiment_name", "tags", "status" keys
- `aria_skills/fact_check/__init__.py`: stores under "claim", "verdict" keys
- `aria_skills/memeothy/__init__.py`: stores under "prophecy", "offering" keys
- `seed_memories` (in `src/api/routers/memories.py`): looks for `result_preview`, `args_preview`, `content` — misses skill-specific keys

## Impact
- MEDIUM: Activity entries exist in DB but their semantic content is too sparse for useful embeddings
- Skill-specific details (experiment names, fact-check claims, prophecies) don't make it into the embedding text

## Acceptance Criteria
- [ ] `_persist_activity()` includes a `result_preview` field with a human-readable summary
- [ ] OR: `seed_memories` is updated to extract content from known skill-specific keys
- [ ] Test: create experiment activity → verify semantic_memory contains experiment name and tags

## Files Affected
- `aria_skills/experiment/__init__.py`
- `aria_skills/fact_check/__init__.py`
- `aria_skills/memeothy/__init__.py`
- `src/api/routers/memories.py` (seed_memories logic)
