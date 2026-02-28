# E8-S85 — RPG.md Lean: Activation Note Only
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P3 | **Points:** 1 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None  
**Familiar Value:** RPG.md is loaded exclusively by the `rpg_master` agent (and rpg_npc, rpg_boss, rpg_paladin). At 323 lines it buries the 4-agent roster + turn sequence under 260 lines of Pathfinder 2e lookup tables. The roster is all Aria needs to start a session; PF2e rules are on-demand reference.

---

## Problem

`aria_mind/RPG.md` is **323 lines** (verified 2026-02-28). Loaded only by RPG agents
(`rpg_master`, `rpg_npc`, `rpg_boss`, `rpg_paladin`). These agents are NOT always
active — they are spawned exclusively for tabletop RPG sessions.

**Line analysis:**
- Lines 1–50: System overview + agent roster (50 lines) — **operationally essential**
- Lines 52–100: Architecture (Isolated) section — file paths, folder structure — **reference only**
- Lines 102–120: Turn sequence protocol (19 lines) — **operationally essential**
- Lines 122–200: Full PF2e Core Rules Reference:
  - Ability scores + ability modifiers table (12 lines)
  - Proficiency ranks table (8 lines)
  - Action types table (10 lines)
  - Basic skill checks (12 lines)
  - Conditions list (18 lines)
  - Spell casting rules (15 lines)
  - Character classes summary (12 lines)
  - XP + level table (10 lines)
  → **97 lines of lookup tables never needed until combat resolution**
- Lines 201–270: Character sheet YAML template (70 lines) — format reference
- Lines 271–290: Campaign directory format (20 lines) — file structure reference
- Lines 291–310: Roundtable Protocol — RPG Mode (20 lines) — **operationally useful but loadable on-demand**
- Lines 311–323: Integration Points + Constraints Compliance table — developer audit

The agent roster and turn sequence (the only runtime-critical content) fit in ~30 lines.
Everything else is lookup reference that should be fetched when needed, not preloaded.

---

## Root Cause

RPG.md was authored as a complete specification document for the RPG subsystem —
covering both the runtime behavior of agents AND the Pathfinder 2e rules reference
that agents consult during play. These two concerns have different access patterns:
the agent roster is needed at spawn time; PF2e rules are needed on specific die-roll
or condition lookups. Loading both at spawn burns ~1,000 tokens for every RPG session
start.

---

## Fix

### New RPG.md structure (~30 lines always-loaded + ~293 lines in reference)

Write the file with this exact content (replace current content):

```markdown
# RPG — Activation Note

**Skill:** `rpg_pathfinder` (rules engine) · `rpg_campaign` (session/world state)  
**Data:** `aria_memories/rpg/` · **Prompts:** `prompts/rpg/`  
**Mode:** Use `rpg_master` agent for ALL tabletop RPG sessions. Full PF2e rules in Reference below.

---

## Agent Roster

| Agent | Role | Model | Prompt file |
|-------|------|:-----:|-------------|
| `rpg_master` | DM — narrates, adjudicates rules, controls world state | kimi | `prompts/rpg/dungeon_master.md` |
| `rpg_npc` | NPC Controller — friendly/neutral NPCs with distinct voices | trinity-free | `prompts/rpg/npc.md` |
| `rpg_boss` | Boss Controller — antagonists, tactical combat AI | kimi | `prompts/rpg/boss.md` |
| `rpg_paladin` | Sera Dawnblade — in-party AI Paladin, party advisor | trinity-free | `prompts/rpg/paladin.md` |

---

## Turn Sequence

1. `rpg_master` → scene narration + world state update
2. Human players → declare actions
3. `rpg_npc` → NPC responses (if NPC involved)
4. `rpg_boss` → antagonist actions (if in encounter)
5. `rpg_paladin` → party tactic advice
6. `rpg_master` → resolve via `rpg_pathfinder` skill → narrate outcome

**Data persistence** (ONLY writable path):
```
aria_memories/rpg/characters/   ← player character sheets (YAML)
aria_memories/rpg/campaigns/    ← campaign definitions
aria_memories/rpg/sessions/     ← session logs + state
aria_memories/rpg/world/        ← lore, maps, factions
aria_memories/rpg/encounters/   ← pre-built + active encounters
```

→ PF2e rules, character sheet YAML template, campaign format, roundtable RPG protocol: **see Reference below**

---
<details>
<summary>🎲 Full PF2e Rules, Character Sheet Template, Campaign Format, Roundtable Protocol</summary>

[ALL original content from lines 1–323 of original RPG.md goes here, in full —
including: System Overview, Architecture (Isolated), full PF2e Core Rules Reference
(ability scores, proficiency ranks, action types, skill checks, conditions list,
spell casting, character classes, XP table), character sheet YAML template,
campaign directory format, Roundtable Protocol — RPG Mode, Integration Points,
Constraints Compliance table]

</details>
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | RPG.md documents RPG skill usage — no code change |
| 2 | `.env` for secrets | ✅ | No secrets involved |
| 3 | `models.yaml` SoT | ✅ | Agent roster uses tier labels (kimi, trinity-free), not hardcoded model IDs |
| 4 | Docker-first testing | ✅ | Verification uses local grep + wc |
| 5 | `aria_memories` only writable | ✅ | RPG data path `aria_memories/rpg/` clearly documented; source file edit is by developer |
| 6 | No soul modification | ✅ | RPG.md is configuration; soul/ untouched; RPG agents do NOT modify SOUL.md |

---

## Dependencies

- **None** — fully independent documentation refactor.
- **E7-S75** (roundtable integration) — the RPG roundtable protocol in the Reference block will benefit from the focus-aware agent selection implemented in S-75. No dependency on execution order.

---

## Verification

```bash
# 1. Agent roster is in lean header (within first 20 lines)
head -20 /Users/najia/aria/aria_mind/RPG.md | grep -c "rpg_master\|rpg_npc\|rpg_boss\|rpg_paladin"
# EXPECTED: 4

# 2. Always-loaded section ≤ 35 lines
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/RPG.md
# EXPECTED: a number ≤ 35

# 3. Turn sequence present in lean header
head -35 /Users/najia/aria/aria_mind/RPG.md | grep -c "rpg_master\|rpg_pathfinder"
# EXPECTED: ≥ 2 (in turn sequence + reference pointer)

# 4. aria_memories/rpg/ data paths documented
grep -n "aria_memories/rpg" /Users/najia/aria/aria_mind/RPG.md | head -5
# EXPECTED: ≥ 3 matches (characters/, campaigns/, sessions/ etc.)

# 5. PF2e rules preserved in Reference block
grep -c "Proficiency\|proficiency\|ability score\|Ability Score" /Users/najia/aria/aria_mind/RPG.md
# EXPECTED: ≥ 2 (inside details block)

# 6. Character sheet YAML preserved
grep -n "character_name\|character_class\|hit_points" /Users/najia/aria/aria_mind/RPG.md
# EXPECTED: ≥ 2 matches (inside details block)

# 7. Reference block exists
grep -n "<details>" /Users/najia/aria/aria_mind/RPG.md
# EXPECTED: 1 match

# 8. Prompt file paths documented
grep -n "dungeon_master.md\|npc.md\|boss.md\|paladin.md" /Users/najia/aria/aria_mind/RPG.md | head -5
# EXPECTED: ≥ 4 matches in first 20 lines
```

---

## Prompt for Agent

You are executing ticket **E8-S85** for the Aria project.
Your task is documentation refactoring — **no Python code changes**.

**Files to read first:**
1. `aria_mind/RPG.md` lines 1–50 (agent roster + architecture overview)
2. `aria_mind/RPG.md` lines 100–125 (turn sequence — identify the exact lines)
3. `prompts/rpg/` — verify prompt filenames match the roster table

**Constraints that apply:**
- Constraint 5: `aria_memories/rpg/` is Aria's ONLY writable path for RPG data. The data path block in the lean header correctly documents this.
- Constraint 6: RPG agents have their own personas in soul prompts directories (`prompts/rpg/`). Do NOT modify those files — they are separate from RPG.md.

**Exact steps:**
1. Read RPG.md lines 1–125 to identify the agent roster and turn sequence.
2. Verify all 4 prompt file names exist under `prompts/rpg/`.
3. Rewrite RPG.md using the lean header structure from the Fix section above.
4. Wrap ENTIRE original content in `<details>` Reference block.
5. Run all 8 verification commands. Every command must return EXPECTED output.

**Note:** RPG.md is currently the open file in the editor — work directly on it.
