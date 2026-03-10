# SP6-T5: SkillResult JSON Serialization Bug in conversation_summary
**Priority:** P1  
**Points:** 2  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
The `conversation_summary` skill returns a `SkillResult` object that is not JSON serializable. When Aria uses this skill, the summary content is generated and stored successfully, but the return value fails serialization.

### Evidence
- Aria's test (chat session 013a8877): "Object of type SkillResult is not JSON serializable"
- The summary was generated and stored via `api_client.set_memory()` ✅
- The thought was created via `api_client.create_thought()` ✅  
- Only the return wrapper fails

## Impact
- MEDIUM: Skill works functionally but the response wrapper breaks JSON serialization
- Aria can't cleanly display the result to users

## Acceptance Criteria
- [ ] `conversation_summary` skill returns a dict, not a SkillResult object
- [ ] OR: SkillResult implements `__json__()` / `to_dict()` for serialization
- [ ] Test: call conversation_summary → verify response is JSON serializable

## Files Affected
- `aria_skills/conversation_summary/__init__.py`
- `aria_skills/base.py` (SkillResult class)
