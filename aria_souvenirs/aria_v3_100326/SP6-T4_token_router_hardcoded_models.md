# SP6-T4: Token Router Draft Skill — Hardcoded Model Names
**Priority:** P2  
**Points:** 2  
**Status:** Open  
**Created:** 2026-03-10  
**Sprint:** 6  

## Problem
Aria's self-created `token_router` skill in `aria_memories/skills/token_router/__init__.py` contains hardcoded model names (`qwen3-mlx`, `trinity-free`, `kimi`, `deepseek-free`). This violates the ZERO model names outside models.yaml rule.

### Evidence
- Line 167: `ModelTier.LOCAL: ["qwen3-mlx"]`
- Line 168: `ModelTier.FREE: ["trinity-free", "qwen3-next-free"]`
- Line 169: `ModelTier.PREMIUM: ["kimi"]`
- Line 170: `ModelTier.EXPERT: ["deepseek-free", "kimi"]`
- Line 239: `return self.MODEL_ROUTES.get(tier, ["qwen3-mlx"])[0]`

## Note
Aria attempted to fix this herself (chat session 95ae6630) by writing an updated version with `ModelConfigLoader` that reads from the API dynamically, but the `write_artifact` call failed due to a parameter mismatch.

## Acceptance Criteria
- [ ] Aria rewrites token_router to fetch model list from API dynamically
- [ ] ZERO hardcoded model names in the skill
- [ ] Fallback uses `get_primary_model()` or API-fetched defaults

## Files Affected
- `aria_memories/skills/token_router/__init__.py` (Aria's memory space)
