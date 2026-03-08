# Aria RPG System — Pathfinder 2e

> Full documentation of Aria's integrated tabletop RPG engine.
> Aria acts as Dungeon Master, NPCs, and Bosses while human players control their characters.

---

## Overview

Aria runs a complete Pathfinder 2e campaign using her multi-agent roundtable system. Each RPG role is an isolated agent with its own persona, prompts, and context. Campaign state is persisted to `aria_memories/rpg/` as YAML/Markdown files.

**Game System:** Pathfinder 2nd Edition (Paizo)  
**Engine:** Aria Engine multi-agent roundtable  
**Storage:** File-based (YAML) in `aria_memories/rpg/`  
**Dashboard:** `rpg.html` web template with Knowledge Graph visualization  

---

## Architecture

```
┌──────────────────────── RPG System ─────────────────────────┐
│                                                              │
│  prompts/rpg/             ← Agent system prompts (per role)  │
│    ├── dungeon_master.md                                     │
│    ├── npc.md                                                │
│    ├── boss.md                                               │
│    ├── paladin.md                                            │
│    └── roundtable_rpg.md  ← RPG roundtable protocol         │
│                                                              │
│  aria_skills/                                                │
│    ├── rpg_pathfinder/    ← PF2e rules engine (dice, combat) │
│    └── rpg_campaign/      ← Campaign state manager           │
│                                                              │
│  aria_memories/rpg/       ← All persistent RPG data          │
│    ├── characters/        ← Player character sheets (YAML)   │
│    ├── campaigns/         ← Campaign definitions + sessions  │
│    ├── sessions/          ← Session logs                     │
│    ├── world/             ← World lore, maps, factions       │
│    └── encounters/        ← Pre-built and active encounters  │
│                                                              │
│  src/api/routers/rpg.py   ← REST API (4 endpoints)          │
│  src/web/templates/rpg.html ← Dashboard page                │
│  aria_mind/RPG.md         ← Master configuration document    │
│  aria_mind/AGENTS.md      ← RPG agent definitions            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## RPG Agents

Four specialized agents form the RPG system, all defined in `aria_mind/AGENTS.md`:

| Agent ID | Role | Model | Description |
|----------|------|-------|-------------|
| `rpg_master` | Dungeon Master | kimi | Narrates story, adjudicates rules, controls world state |
| `rpg_npc` | NPC Controller | trinity-free | Plays friendly/neutral NPCs with distinct personalities |
| `rpg_boss` | Boss Controller | kimi | Plays antagonists, bosses, enemy tacticians |
| `rpg_paladin` | Party Advisor | trinity-free | In-party AI companion (Seraphina "Sera" Dawnblade, Champion/Paladin of Iomedae) |

### Agent Hierarchy

```
rpg_master (parent: aria)
  ├── rpg_npc (parent: rpg_master)
  ├── rpg_boss (parent: rpg_master)
  └── rpg_paladin (parent: rpg_master)
```

All RPG agents load `[IDENTITY.md, SOUL.md, RPG.md]` as mind files.

---

## Skills

### rpg_campaign — Campaign Manager

**Module:** `aria_skills/rpg_campaign/__init__.py` (1145 lines)  
**Class:** `RPGCampaignSkill`  
**Storage:** `aria_memories/rpg/`

Manages persistent campaign state including:

| Function | Description |
|----------|-------------|
| `create_campaign()` | Create a new campaign with setting, description, starting level |
| `get_campaign()` | Load campaign state from YAML |
| `update_campaign()` | Update campaign metadata and world state |
| `create_session()` | Start a new game session with scene and objectives |
| `end_session()` | Close session with summary and XP awards |
| `add_character()` | Register a player character to the campaign |
| `update_character()` | Update character stats, inventory, conditions |
| `create_encounter()` | Create combat encounters with monsters and terrain |
| `get_world_state()` | Get current world state (locations, factions, events) |
| `update_world_state()` | Modify world state after events |

### rpg_pathfinder — Pathfinder 2e Rules Engine

**Module:** `aria_skills/rpg_pathfinder/__init__.py` (745 lines)  
**Class:** `RPGPathfinderSkill`  
**Storage:** `aria_memories/rpg/characters/`, `aria_memories/rpg/encounters/`

Provides mechanical resolution for Pathfinder 2e:

| Function | Description |
|----------|-------------|
| `roll_dice()` | Roll dice with standard notation (NdX+M) |
| `ability_check()` | Resolve ability/skill checks with proficiency |
| `attack_roll()` | Resolve attack with MAP (Multiple Attack Penalty) |
| `damage_roll()` | Calculate damage with modifiers |
| `saving_throw()` | Resolve saving throws (Fort/Ref/Will) |
| `degree_of_success()` | Determine PF2e degree (crit success → crit fail) |
| `apply_condition()` | Apply/remove conditions with value tracking |
| `cast_spell()` | Resolve spell casting with components |
| `initiative_roll()` | Roll initiative for encounter start |
| `get_character()` | Load character sheet from YAML |

### Dice Engine

Standard notation support: `1d20`, `2d6+4`, `4d8-2`, `d20`, `1d20+12`

```python
roll_dice("1d20+12")
# → {"expression": "1d20+12", "rolls": [15], "subtotal": 15, "modifier": 12,
#    "total": 27, "natural_20": false, "natural_1": false}
```

### Degrees of Success

| Roll vs DC | Degree |
|-----------|--------|
| ≥ DC + 10 | Critical Success |
| ≥ DC | Success |
| < DC | Failure |
| ≤ DC - 10 | Critical Failure |

Natural 20 improves by one step. Natural 1 worsens by one step.

---

## REST API Endpoints

**Router:** `src/api/routers/rpg.py` (432 lines)  
**Tags:** `RPG Dashboard`  
**Dashboard data source for `rpg.html`**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/rpg/campaigns` | List all campaigns with summary (YAML + KG entities) |
| GET | `/api/rpg/campaign/{id}` | Full campaign detail: party, world state, sessions, KG stats |
| GET | `/api/rpg/session/{id}/transcript` | Session message history (from engine chat sessions) |
| GET | `/api/rpg/campaign/{id}/kg` | Knowledge Graph subgraph for vis-network visualization |

### Knowledge Graph Integration

The `/campaign/{id}/kg` endpoint performs BFS traversal from the campaign entity through knowledge graph relations, returning vis-network compatible nodes and edges. Entity types are color-coded:

| Entity Type | Color | Hex |
|-------------|-------|-----|
| player_character | Blue | `#4A90D9` |
| npc | Green | `#27AE60` |
| location | Orange | `#F39C12` |
| monster | Red | `#E74C3C` |
| quest | Purple | `#9B59B6` |
| artifact | Gold | `#F1C40F` |
| campaign | Bright Blue | `#3498DB` |
| session | Teal | `#1ABC9C` |

---

## Prompt Templates

System prompts for each RPG agent are isolated in `prompts/rpg/`:

| File | Agent | Purpose |
|------|-------|---------|
| `dungeon_master.md` | rpg_master | World narration, rules adjudication, encounter management |
| `npc.md` | rpg_npc | NPC roleplay, social interaction, information delivery |
| `boss.md` | rpg_boss | Tactical combat AI, villain roleplay, threat escalation |
| `paladin.md` | rpg_paladin | Party advisement, combat support, moral compass |
| `roundtable_rpg.md` | (all) | RPG-adapted roundtable protocol for multi-agent play |

---

## Roundtable Protocol — RPG Mode

The RPG roundtable adapts Aria's multi-agent roundtable for tabletop play:

### Phase Mapping

| Roundtable Phase | RPG Phase | Description |
|-----------------|-----------|-------------|
| EXPLORE | Scene Setting | DM describes scene, NPCs introduce themselves |
| WORK | Player Actions | Players declare actions, DM resolves mechanics |
| VALIDATE | Resolution | DM narrates outcomes, updates world state |

### Turn Order

1. `rpg_master` sets the scene / narrates
2. Players (humans) declare actions via chat
3. `rpg_npc` responds as active NPCs
4. `rpg_boss` acts for antagonists (if in encounter)
5. `rpg_paladin` advises party (if AI companion active)
6. `rpg_master` resolves actions using Pathfinder rules
7. Repeat

### Combat Roundtable

During combat, the roundtable follows strict initiative order:
1. `rpg_master` announces round and current initiative
2. Each agent/player acts in initiative order
3. `rpg_pathfinder` skill resolves dice rolls, damage, conditions
4. `rpg_master` narrates results after each action
5. End of round — check conditions, ongoing effects

---

## Data Storage

All RPG data is persisted as YAML files under `aria_memories/rpg/`:

### Campaign Structure

```
aria_memories/rpg/campaigns/<campaign_id>/
├── campaign.yaml        ← Master campaign file (title, setting, party, status)
├── world.yaml           ← World state (locations, factions, events)
├── npcs.yaml            ← NPC roster with personalities/stats
├── encounters/          ← Encounter definitions
│   ├── E001_goblin_ambush.yaml
│   └── E002_dragon_lair.yaml
└── sessions/            ← Session logs
    ├── session_001.yaml
    └── session_002.yaml
```

### Character Sheets

Stored in `aria_memories/rpg/characters/` as YAML files following the Pathfinder 2e character sheet format. Includes abilities, skills, weapons, armor, feats, spells, inventory, and conditions.

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/rpg/rpg_chat.py` | Interactive RPG chat CLI interface |
| `scripts/rpg/rpg_roundtable.py` | Run RPG roundtable sessions |
| `scripts/rpg/rpg_session.py` | RPG session management utilities |
| `scripts/rpg/rpg_send.py` | Send campaign messages into an existing RPG session |

---

## Dashboard

The `rpg.html` template provides:
- Campaign listing with status and party size
- Campaign detail view with world state
- Session transcript viewer
- Interactive Knowledge Graph visualization (vis-network)
- Entity type color coding for visual clarity

---

## Constraints Compliance

| # | Constraint | Status | Notes |
|---|-----------|--------|-------|
| 1 | 5-layer architecture | ✅ | Skills at L3 (Domain), use api_client for DB access |
| 2 | .env secrets | ✅ | No secrets needed for RPG |
| 3 | models.yaml source of truth | ✅ | Agents use model refs from models.yaml |
| 4 | Docker-first | ✅ | Pure Python + YAML, no new services |
| 5 | aria_memories writable | ✅ | All RPG data in aria_memories/rpg/ |
| 6 | No soul modification | ✅ | RPG is separate from soul/identity |

---

*See also: [aria_mind/RPG.md](../aria_mind/RPG.md) for Pathfinder 2e rules reference and character sheet format.*
