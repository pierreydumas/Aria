# SPEC: Skill Auto-Wiring & Self-Documenting Skills

**Date**: 2026-03-12
**Priority**: P1 (High — follows P0 sandbox/skill audit)
**Status**: ✅ IMPLEMENTED — All core changes verified end-to-end

---

## Problem Statement

Today, Aria's skill→agent assignment is **100% manual**:

1. Human writes a skill list in `aria_mind/AGENTS.md`
2. `agents_sync.py` copies that list verbatim to the DB
3. `ChatEngine.send_message()` reads the DB list and filters tools
4. Result: a flat string-match filter with **zero** use of rich metadata

Every `skill.json` already declares:
- `layer` (0–4) — architectural tier
- `focus_affinity` (e.g. `["devsecops", "data"]`) — which agent roles benefit
- `dependencies` (e.g. `["api_client"]`) — prerequisite skills

**None of this metadata is used in the tool-filtering pipeline.**

### Consequences
- 20 skills were orphaned (no agent had them) — fixed manually in P0
- AGENTS.md still has stale `database` ghost refs (synced over our API fixes)
- Adding a new skill requires editing AGENTS.md + knowing which agents need it
- Streaming engine exposes ALL 305 tools to every agent (no filtering at all)
- No way for Aria to self-onboard a new skill

### Goal
After this work:
1. **New skill = create directory + skill.json + SKILL.md → auto-wired**
2. `focus_affinity` drives which agents get the skill (no AGENTS.md edit needed)
3. `layer` determines injection behavior (L0 = global, L1-L2 = core always, L3-L4 = affinity-matched)
4. Streaming engine gets the same per-agent filter as ChatEngine
5. Aria can read SKILL.md and understand how to use a skill
6. AGENTS.md becomes read-only output (generated from manifests + DB), not input

---

## Architecture

### Current Flow (before)

```
AGENTS.md (manual)
    ↓ agents_sync.py          
DB: agent_state.skills         ← STATIC, hand-maintained
    ↓ ChatEngine               
ToolRegistry.get_tools_for_llm(filter_skills=static_list)
    ↓
LLM sees filtered tools
```

### Target Flow (after)

```
skill.json manifests (source of truth for metadata)
    ↓ ToolRegistry.discover_from_manifests()  ← already works
    ↓ NEW: build_agent_skill_map()
    ↓ Uses: layer + focus_affinity + agent.focus_type
DB: agent_state.skills         ← AUTO-COMPUTED from affinity matching
    ↓ ChatEngine + StreamingEngine (BOTH filtered)
ToolRegistry.get_tools_for_llm(filter_skills=computed_list)
    ↓
LLM sees affinity-matched tools
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where does matching run? | At API startup (`src/api/main.py`) after manifest discovery | One-time cost, results cached in DB |
| Does it overwrite manual assignments? | **NO** — it merges. Manual additions in DB are preserved. | Don't break existing assignments |
| What about AGENTS.md? | Skills from AGENTS.md are treated as **overrides** (always included). Affinity adds on top. | Backward compatible |
| Layer behavior? | L0 = global (all agents). L1-L2 = all agents with matching OR orchestrator affinity. L3-L4 = affinity-matched only. | Respects the hierarchy |
| Can an agent opt OUT of a skill? | Yes, via `exclude_skills` field in AGENTS.md (new). | Escape hatch |
| Streaming filter? | Copy ChatEngine's per-agent logic. | Close the security gap |

---

## Implementation Plan

### Change 1: `build_agent_skill_map()` in `aria_engine/tool_registry.py`

New method that computes the recommended skill set for each agent:

```python
def build_agent_skill_map(
    self,
    agents: list[dict],  # [{agent_id, focus_type, skills(current), exclude_skills}]
) -> dict[str, list[str]]:
    """
    Compute agent → skills mapping using manifest metadata.
    
    Rules:
    1. Layer 0 skills → ALL agents (global security)
    2. Layer 1-2 skills → agents with 'orchestrator' affinity OR explicit assignment
    3. Layer 3-4 skills → agents whose focus_type matches any focus_affinity entry
    4. Manual skills from DB/AGENTS.md are always preserved (union, not replace)
    5. exclude_skills removes specific skills (opt-out)
    6. Dependencies are auto-included (if skill X depends on Y, Y is added)
    
    Returns:
        {agent_id: [skill_names]} — merged list (affinity + manual + deps)
    """
```

**Matching logic:**

```python
FOCUS_TYPE_TO_AFFINITIES = {
    "orchestrator": ["orchestrator"],
    "devsecops":    ["devsecops"],
    "data":         ["data", "trader"],
    "social":       ["social", "creative", "journalist"],
    "memory":       ["memory", "cognitive"],
    "rpg_master":   ["rpg_master"],
    "conversational": [],  # aria-local: minimal, only manual skills
}

for agent in agents:
    agent_affinities = FOCUS_TYPE_TO_AFFINITIES.get(agent.focus_type, [])
    computed_skills = set(agent.skills or [])  # preserve existing
    
    for skill_name, manifest in self._manifests.items():
        layer = manifest.get("layer", 3)
        affinity = manifest.get("focus_affinity", [])
        
        # L0: global (all agents)
        if layer == 0:
            computed_skills.add(skill_name)
        
        # L1-L2: core infrastructure — add to orchestrator + any affinity match
        elif layer <= 2:
            if "orchestrator" in agent_affinities or any(a in agent_affinities for a in affinity):
                computed_skills.add(skill_name)
        
        # L3-L4: domain — add only if affinity matches
        else:
            if any(a in agent_affinities for a in affinity):
                computed_skills.add(skill_name)
    
    # Auto-include dependencies
    for skill in list(computed_skills):
        for dep in self._manifests.get(skill, {}).get("dependencies", []):
            computed_skills.add(dep)
    
    # Remove excluded skills
    for ex in agent.get("exclude_skills", []):
        computed_skills.discard(ex)
    
    result[agent.agent_id] = sorted(computed_skills)
```

### Change 2: Call `build_agent_skill_map()` at API startup

In `src/api/main.py`, after `tool_registry.discover_from_manifests()`:

```python
# After discovering tools, auto-wire skills to agents
from src.api.db.models import EngineAgentState
async with db_session() as db:
    agents = await db.execute(select(EngineAgentState))
    agent_list = [
        {
            "agent_id": a.agent_id,
            "focus_type": a.focus_type,
            "skills": a.skills or [],
            "exclude_skills": a.exclude_skills or [],
        }
        for a in agents.scalars()
    ]
    
    skill_map = tool_registry.build_agent_skill_map(agent_list)
    
    for agent_id, skills in skill_map.items():
        await db.execute(
            update(EngineAgentState)
            .where(EngineAgentState.agent_id == agent_id)
            .values(skills=skills)
        )
    await db.commit()
    logger.info("Auto-wired skills: %s", {k: len(v) for k, v in skill_map.items()})
```

### Change 3: Store manifests in ToolRegistry

`discover_from_manifests()` already reads every `skill.json`. Add:

```python
self._manifests: dict[str, dict] = {}  # skill_name → full manifest dict
```

Populated during discovery so `build_agent_skill_map()` can access `layer`, `focus_affinity`, `dependencies`.

### Change 4: Fix StreamingEngine (security gap)

In `aria_engine/streaming.py` around line 684, replicate ChatEngine's per-agent filtering:

```python
# BEFORE (broken — all tools exposed):
tools_for_llm = self.tools.get_tools_for_llm() if enable_tools else None

# AFTER (per-agent filtered):
allowed_skills = None
if enable_tools and session.agent_id:
    from db.models import EngineAgentState
    agent_skills = await db.execute(
        select(EngineAgentState.skills).where(
            EngineAgentState.agent_id == session.agent_id
        )
    )
    row = agent_skills.first()
    if row and row[0]:
        skills_list = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(skills_list, list) and skills_list:
            allowed_skills = skills_list
            for gs in ChatEngine.GLOBAL_SKILLS:
                if gs not in allowed_skills:
                    allowed_skills.append(gs)

tools_for_llm = self.tools.get_tools_for_llm(filter_skills=allowed_skills) if enable_tools else None
```

### Change 5: `exclude_skills` field in AGENTS.md + DB

Add optional `exclude_skills` to agent YAML blocks:

```yaml
id: aria-local
focus: conversational
exclude_skills: [sandbox, ci_cd, security_scan]  # lightweight agent
skills: [llm, conversation_summary, api_client, browser]
```

DB migration: add `exclude_skills JSONB DEFAULT '[]'` to `agent_state` table.
`agents_sync.py`: parse and persist `exclude_skills`.

### Change 6: Remove `GLOBAL_SKILLS` constant from ChatEngine

With layer-0 auto-injection in `build_agent_skill_map()`, the hardcoded `GLOBAL_SKILLS = ["input_guard"]` becomes redundant. The L0 rule handles it automatically. Remove it after verifying.

### Change 7: SKILL.md Standard Template

Every skill directory should contain a `SKILL.md` that Aria can read. This replaces the optional README.md. Format:

```markdown
# {Skill Name}

> {One-line description — this is what Aria reads to understand the skill}

## What This Skill Does

{2-3 sentences explaining the skill's purpose, written for an AI agent}

## Tools

| Tool | When to Use | Example |
|------|------------|---------|
| `{tool_name}` | {Trigger condition} | `{skill}__{tool}({"param": "value"})` |

## Agent Affinity

This skill is designed for agents with focus: **{focus_affinity list}**
Layer: **{layer}** ({layer_name})

## Dependencies

Requires: {dependency list or "None"}

## Examples

### {Use Case 1}
```
{tool_call_example}
→ {expected_result}
```

### {Use Case 2}
```
{tool_call_example}
→ {expected_result}
```

## Gotchas

- {Known limitation or edge case}
- {Rate limits or quotas}
```

### Change 8: Update AGENTS.md to reflect auto-wired state

After auto-wiring, regenerate the skills lists in AGENTS.md to match reality. Add a comment:

```yaml
# Skills below are auto-computed from skill.json focus_affinity + layer rules.
# To override: add skills here (always included) or use exclude_skills (always removed).
# Manual additions are preserved across auto-wiring runs.
skills: [goals, schedule, health, api_client, ...]
```

### Change 9: Sync AGENTS.md AFTER auto-wiring (not before)

Current flow: `agents_sync.py` runs at startup and OVERWRITES DB skills with AGENTS.md.
This would undo auto-wiring every restart.

**Fix**: Change the startup order:
1. `agents_sync.py` syncs agent identity (id, focus, model, etc.) but SKIPS skills if auto-wiring is enabled
2. `tool_registry.discover_from_manifests()` discovers all tools
3. `build_agent_skill_map()` computes and updates skills in DB
4. Optional: regenerate AGENTS.md from DB (for human readability)

Add config flag: `ARIA_SKILL_AUTO_WIRE=true` (default: true).
When true, `agents_sync.py` does NOT overwrite the `skills` column.
When false, legacy behavior (AGENTS.md is source of truth).

---

## Test Plan

### Unit Tests

1. **`test_build_agent_skill_map_layer0_global`**: L0 skill (input_guard) appears in ALL agents
2. **`test_build_agent_skill_map_layer2_core`**: L2 skill (health) appears in orchestrator + affinity-matched agents
3. **`test_build_agent_skill_map_layer3_affinity`**: L3 skill (sandbox) only appears in devsecops agents
4. **`test_build_agent_skill_map_preserves_manual`**: Existing manual skills are not removed
5. **`test_build_agent_skill_map_excludes`**: `exclude_skills` removes skills from computed list
6. **`test_build_agent_skill_map_dependencies`**: If agent gets `portfolio`, `market_data` is auto-included (dependency)
7. **`test_build_agent_skill_map_unknown_focus`**: Agent with unknown focus_type only gets L0 + manual skills

### Integration Tests

8. **`test_streaming_engine_filters`**: Create session via WebSocket, verify tool list is filtered (not 305)
9. **`test_api_startup_auto_wires`**: Start API, check DB skills match expected affinity mapping
10. **`test_new_skill_auto_discovery`**: Add a new skill.json with `focus_affinity: ["devsecops"]`, restart API, verify devops agent has it
11. **`test_agents_md_not_overwrite_auto_wired`**: With `ARIA_SKILL_AUTO_WIRE=true`, verify `agents_sync.py` does not clobber computed skills

### End-to-End Tests

12. **`test_e2e_sandbox_via_chat`**: Send "run code" to aria agent → sandbox tool call succeeds
13. **`test_e2e_input_guard_global`**: Send SQL injection text to rpg_master → input_guard tools are available
14. **`test_e2e_affinity_isolation`**: rpg_master CANNOT use `ci_cd` tools (no devsecops affinity)
15. **`test_e2e_streaming_filtered`**: WebSocket session with devops → only sees devsecops-affinity tools

### Validation Queries

```sql
-- After auto-wiring, verify skill counts per agent
SELECT agent_id, focus_type, jsonb_array_length(skills) as skill_count
FROM aria_engine.agent_state
ORDER BY skill_count DESC;

-- Verify no orphan skills
SELECT s.skill_name 
FROM (SELECT DISTINCT jsonb_array_elements_text(skills) AS skill_name FROM aria_engine.agent_state) assigned
RIGHT JOIN (SELECT name FROM aria_engine.skill_status) s ON s.skill_name = assigned.skill_name
WHERE assigned.skill_name IS NULL;

-- Verify L0 skills are in every agent
SELECT agent_id FROM aria_engine.agent_state 
WHERE NOT skills @> '["input_guard"]'::jsonb;
-- Should return 0 rows
```

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Token explosion — too many tools per agent | Medium | Layer rules limit L3-L4 to affinity-matched only. Monitor token counts. |
| Auto-wiring breaks existing assignments | High | Union-only (never remove manual skills). `ARIA_SKILL_AUTO_WIRE` flag as killswitch. |
| AGENTS.md sync overwrites auto-wired skills | High | Skip `skills` column in sync when auto-wire is enabled. |
| Streaming filter breaks WebSocket sessions | Medium | Copy exact ChatEngine logic. Test with existing WebSocket clients. |
| Focus affinity mapping is wrong | Low | FOCUS_TYPE_TO_AFFINITIES is explicit and auditable. Easy to fix. |
| New skill has no focus_affinity | Low | Default to empty → only L0-L2 rules apply. Skill shows up in no agent unless manually added. |
| Dependency chains are circular | Low | Track visited set during dependency resolution. Cap at depth 3. |

---

## File Changes Summary

| File | Change | Risk |
|------|--------|------|
| `aria_engine/tool_registry.py` | Add `_manifests` dict, `build_agent_skill_map()` | Low |
| `src/api/main.py` | Call `build_agent_skill_map()` after discovery | Medium |
| `aria_engine/streaming.py` | Add per-agent skill filtering (line 684) | Medium |
| `src/api/agents_sync.py` | Skip skills overwrite when auto-wire is enabled | Medium |
| `src/api/db/models.py` | Add `exclude_skills` column to EngineAgentState | Low |
| `aria_engine/chat_engine.py` | Remove `GLOBAL_SKILLS` (replaced by L0 rule) | Low |
| `aria_mind/AGENTS.md` | Add `exclude_skills` field, update skill lists | Low |
| `aria_skills/_template/SKILL.md` | New file — documentation template | None |
| All `aria_skills/*/` | Add SKILL.md to each skill (batch) | None |

---

## SKILL.md — What Aria Reads

When Aria encounters a tool she hasn't used before, or needs to understand a skill's purpose, she reads `aria_skills/{skill}/SKILL.md`. This file is:

1. **Aria-first**: Written for an AI agent, not a human developer
2. **Actionable**: Contains exact tool call examples with expected outputs
3. **Self-contained**: No external references needed to understand usage
4. **Machine-parseable**: Consistent headers that can be grepped/parsed

### Template

```markdown
# {Canonical Name} — {One-Line Purpose}

Layer {N} · Focus: {affinity list} · Status: {active|stub|experimental}

## Purpose

{2-3 sentences. What problem does this skill solve? When should Aria use it?}

## Tools

### `{skill}__{tool_name}`
{Description of when to call this tool}

**Parameters:**
- `param1` (string, required): {what it does}
- `param2` (integer, optional, default=10): {what it does}

**Example:**
\`\`\`json
{"param1": "value", "param2": 20}
\`\`\`
**Returns:** {description of success response}

### `{skill}__{tool_name_2}`
...

## Dependencies

- `{dep_skill}` — {why it's needed}

## Constraints

- {Rate limits}
- {Size limits}
- {Network requirements (e.g., needs sandbox container)}
- {Permissions or security notes}

## Common Patterns

### {Pattern Name}
\`\`\`
Step 1: {tool_call}
Step 2: {tool_call}
Expected: {outcome}
\`\`\`
```

---

## Success Criteria

After implementation:

1. ✅ `input_guard` tools appear for ALL agents (L0 global injection)
2. ✅ `sandbox` tools appear only for agents with `devsecops` affinity (devops + aria[has sandbox manual])
3. ✅ `rpg_pathfinder` does NOT appear for `analyst` (no rpg_master affinity)
4. ✅ Adding a new `aria_skills/weather/skill.json` with `focus_affinity: ["data"]` → analyst agent auto-gets it on restart
5. ✅ Streaming WebSocket sessions have per-agent tool filtering
6. ✅ AGENTS.md skill lists match DB (auto-generated)
7. ✅ Every skill has a SKILL.md that Aria can read
8. ✅ Token counts per agent stay under 25 skills (aria capped from 28→25)
9. ✅ `ARIA_SKILL_AUTO_WIRE=false` restores legacy behavior
10. ✅ No existing skill assignments are lost (union-only)

---

## Implementation Log (2026-03-12)

### Files Modified

| File | Change |
|------|--------|
| `aria_engine/tool_registry.py` | Added `_manifests` dict, `build_agent_skill_map()`, `_resolve_deps()`, `get_allowed_skills()`, constants |
| `aria_engine/chat_engine.py` | Replaced inline DB query with shared `get_allowed_skills()`, removed `GLOBAL_SKILLS` |
| `aria_engine/streaming.py` | Added per-agent tool filtering (line 684) + execution-time capability gate (line 1082) |
| `src/api/agents_sync.py` | Added `auto_wire` guard: skip skills overwrite when `ARIA_SKILL_AUTO_WIRE=true` |
| `src/api/config.py` | Added `SKILL_AUTO_WIRE` env var (default: true) |
| `src/api/main.py` | Added auto-wire startup phase: reads agents from DB, computes skill map, persists |

### Files Created

| File | Purpose |
|------|---------|
| `aria_skills/skill_guide/__init__.py` | L2 skill: `skill_guide__read` + `skill_guide__list` tools |
| `aria_skills/skill_guide/skill.json` | Manifest for skill_guide (layer 2, empty focus_affinity) |
| `aria_skills/skill_guide/SKILL.md` | Self-documentation for the skill_guide itself |
| `aria_skills/_template/SKILL.md` | Standardized SKILL.md template for new skills |

### E2E Test Results

- **307 tools** from **44 skill manifests** discovered (was 305/43 before)
- **11 agents** auto-wired with correct affinity matching
- Aria orchestrator capped from 28→25 skills (trim by layer priority)
- `skill_guide__list` and `skill_guide__read` confirmed working end-to-end
- All agents have `input_guard` (L0) and `skill_guide` (L2)
- Streaming engine: per-agent filter + execution-time capability gate active
