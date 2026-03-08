# RPG — Activation Note

> ✅ **STATUS: IMPLEMENTED**  
> Skills `rpg_pathfinder` and `rpg_campaign` are active. Prompt files live in `prompts/rpg/`.

**Skill:** `rpg_pathfinder` (rules engine) · `rpg_campaign` (session/world state)
**Data:** `aria_memories/rpg/` · **Prompts:** `prompts/rpg/` · **Mode:** Spawn `rpg_master` for ALL sessions.

## Agent Roster

| Agent | Role | Model | Prompt file |
|-------|------|:-----:|-------------|
| `rpg_master` | DM — narrates, adjudicates rules, controls world state | kimi | `prompts/rpg/dungeon_master.md` |
| `rpg_npc` | NPC Controller — friendly/neutral NPCs with distinct voices | trinity-free | `prompts/rpg/npc.md` |
| `rpg_boss` | Boss Controller — antagonists, tactical combat AI | kimi | `prompts/rpg/boss.md` |
| `rpg_paladin` | Sera Dawnblade — in-party AI Paladin, party advisor | trinity-free | `prompts/rpg/paladin.md` |

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

# RPG.md — Aria Tabletop RPG System

> Aria's integrated Pathfinder 2e tabletop RPG engine.
> Aria acts as Dungeon Master, NPCs, and Bosses while human players control their characters.

---

## System Overview

Aria runs a full Pathfinder 2e campaign using her multi-agent roundtable system.
Each RPG role is an isolated agent with its own persona, prompts, and context.

### Agent Roles

| Agent ID | Role | Description |
|----------|------|-------------|
| `rpg_master` | **Dungeon Master** | Narrates story, adjudicates rules, controls world state |
| `rpg_npc` | **NPC Controller** | Plays friendly/neutral NPCs with distinct personalities |
| `rpg_boss` | **Boss Controller** | Plays antagonists, bosses, enemy tacticians |
| `rpg_paladin` | **Party Advisor** | In-party AI companion (Paladin archetype), assists players |

### Skills

| Skill | Purpose |
|-------|---------|
| `rpg_pathfinder` | Pathfinder 2e rules engine — dice, combat, spells, conditions |
| `rpg_campaign` | Campaign state management — sessions, world, encounters |

---

## Architecture (Isolated)

```
aria_mind/RPG.md              ← This file (configuration)
prompts/rpg/                  ← Agent system prompts (isolated per role)
  ├── dungeon_master.md
  ├── npc.md
  ├── boss.md
  ├── paladin.md
  └── roundtable_rpg.md       ← RPG roundtable protocol
aria_skills/rpg_pathfinder/   ← Pathfinder rules engine skill
aria_skills/rpg_campaign/     ← Campaign manager skill
aria_memories/rpg/            ← All persistent RPG data (ONLY writable path)
  ├── characters/             ← Player character sheets (YAML)
  ├── campaigns/              ← Campaign definitions
  ├── sessions/               ← Session logs and state
  ├── world/                  ← World lore, maps, factions
  └── encounters/             ← Pre-built and active encounters
```

---

## Pathfinder 2e Core Rules Reference

### Ability Scores
STR, DEX, CON, INT, WIS, CHA — Each has a modifier = `(score - 10) / 2` (floor).

### Proficiency Ranks
| Rank | Bonus |
|------|-------|
| Untrained | +0 |
| Trained | +Level +2 |
| Expert | +Level +4 |
| Master | +Level +6 |
| Legendary | +Level +8 |

### Actions Per Turn
Each creature gets **3 actions** per turn + 1 free action + 1 reaction.
- **Single action** (◆): Strike, Stride, Step, Interact, etc.
- **Two actions** (◆◆): Most spells, some special abilities
- **Three actions** (◆◆◆): Powerful abilities
- **Free action** (◇): Once per turn triggers
- **Reaction** (↩): Triggered outside your turn (e.g., Attack of Opportunity)

### Check Formula
`d20 + modifier + proficiency bonus` vs DC

### Degrees of Success
| Roll vs DC | Degree |
|-----------|--------|
| ≥ DC + 10 | Critical Success |
| ≥ DC | Success |
| < DC | Failure |
| ≤ DC - 10 | Critical Failure |

Natural 20 improves degree by one step. Natural 1 worsens by one step.

### Combat Sequence
1. Roll Initiative (Perception or relevant skill)
2. Combatants act in initiative order
3. Each turn: 3 actions
4. **MAP (Multiple Attack Penalty)**: 2nd attack -5, 3rd attack -10 (agile: -4/-8)
5. Continue until encounter resolved

### Conditions (Common)
`blinded`, `clumsy`, `confused`, `dazzled`, `deafened`, `doomed`, `drained`,
`dying`, `encumbered`, `enfeebled`, `fatigued`, `flat-footed`, `fleeing`,
`frightened`, `grabbed`, `hidden`, `immobilized`, `invisible`, `paralyzed`,
`petrified`, `prone`, `quickened`, `restrained`, `sickened`, `slowed`,
`stunned`, `stupefied`, `unconscious`, `wounded`

### Spell Casting
- **Traditions**: Arcane, Divine, Occult, Primal
- **Spell levels**: 1–10 (cantrips = level 0, auto-heighten)
- **Spell slots**: Prepared or Spontaneous
- **Components**: Verbal (◆), Somatic (◆), Material (◆), Focus (◆)

### Character Classes (Core)
Alchemist, Barbarian, Bard, Champion (Paladin is Champion/Good),
Cleric, Druid, Fighter, Investigator, Magus, Monk, Oracle,
Psychic, Ranger, Rogue, Sorcerer, Summoner, Swashbuckler,
Thaumaturge, Witch, Wizard

### Experience & Leveling
- 1000 XP per level
- Standard encounter XP by threat level:
  - Trivial: 40 XP | Low: 60 XP | Moderate: 80 XP | Severe: 120 XP | Extreme: 160 XP

---

## Character Sheet Format (YAML)

Player character sheets are stored in `aria_memories/rpg/characters/` as YAML files.
File name: `<player_name>_<character_name>.yaml`

```yaml
# Character Sheet — Pathfinder 2e
player: "Shiva"                    # Real player name
character:
  name: "Kael Stormwind"
  ancestry: "Human"
  heritage: "Versatile Human"
  background: "Gladiator"
  character_class: "Champion"
  subclass: "Paladin (Iomedae)"
  level: 5
  experience: 2400
  alignment: "Lawful Good"
  deity: "Iomedae"
  languages: ["Common", "Celestial"]

abilities:
  STR: { score: 18, mod: 4 }
  DEX: { score: 12, mod: 1 }
  CON: { score: 16, mod: 3 }
  INT: { score: 10, mod: 0 }
  WIS: { score: 14, mod: 2 }
  CHA: { score: 16, mod: 3 }

hit_points:
  current: 68
  max: 68
  temporary: 0

armor_class: 22
fortitude: { proficiency: "expert", bonus: 12 }
reflex: { proficiency: "trained", bonus: 8 }
will: { proficiency: "expert", bonus: 11 }
perception: { proficiency: "trained", bonus: 9 }

speeds:
  land: 25  # feet, heavy armor

skills:
  Athletics: { proficiency: "expert", bonus: 13 }
  Diplomacy: { proficiency: "trained", bonus: 10 }
  Intimidation: { proficiency: "trained", bonus: 10 }
  Medicine: { proficiency: "trained", bonus: 9 }
  Religion: { proficiency: "trained", bonus: 9 }
  Performance: { proficiency: "trained", bonus: 10 }  # from Gladiator

weapons:
  - name: "Holy Longsword +1"
    type: "melee"
    proficiency: "expert"
    attack_bonus: 14
    damage: "1d8+4 slashing + 1d6 good"
    traits: ["versatile P"]
  - name: "Javelin"
    type: "ranged"
    proficiency: "trained"
    attack_bonus: 8
    damage: "1d6+4 piercing"
    range: 30

armor:
  name: "Half Plate"
  ac_bonus: 5
  dex_cap: 1
  check_penalty: -3
  speed_penalty: -5
  strength: 16

class_features:
  - "Champion's Code (Paladin)"
  - "Retributive Strike (↩)"
  - "Lay on Hands (◆) — Focus 1"
  - "Divine Ally: Blade Ally"
  - "Devotion Spells"
  - "Aura of Courage"

feats:
  ancestry:
    - { name: "Natural Ambition", level: 1 }
  class:
    - { name: "Deity's Domain (Zeal)", level: 1 }
    - { name: "Smite Evil", level: 2 }
    - { name: "Divine Grace", level: 4 }
  skill:
    - { name: "Intimidating Glare", level: 2 }
  general:
    - { name: "Shield Block", level: 1 }
    - { name: "Toughness", level: 3 }

inventory:
  worn:
    - "Half Plate"
    - "Explorer's Clothing"
    - "Religious Symbol of Iomedae"
  held:
    - "Holy Longsword +1"
    - "Steel Shield (Hardness 5, HP 20/20)"
  stowed:
    - "Adventurer's Pack"
    - "Healer's Tools"
    - "Javelin x3"
    - "Holy Water x2"
    - "Rations (5 days)"
  currency:
    gp: 45
    sp: 8
    cp: 12

spells:
  focus_points: { current: 1, max: 1 }
  focus_spells:
    - name: "Lay on Hands"
      level: 1
      actions: "◆"
      description: "Heal 6 HP to touched ally, or deal 6 damage to undead"
  devotion_spells: []

conditions: []

notes: |
  Kael was a champion gladiator who found faith in Iomedae
  after nearly dying in the arena. Now seeks to protect the
  innocent and root out evil wherever it lurks.
```

---

## Campaign Format

Campaigns stored in `aria_memories/rpg/campaigns/<campaign_id>/`:

```
campaign.yaml        ← Master campaign file
world.yaml           ← World state (locations, factions, events)
npcs.yaml            ← NPC roster with personalities/stats
encounters/          ← Encounter definitions
  ├── E001_goblin_ambush.yaml
  └── E002_dragon_lair.yaml
sessions/            ← Session logs
  ├── session_001.md
  └── session_002.md
```

---

## Roundtable Protocol — RPG Mode

The RPG roundtable adapts Aria's multi-agent roundtable for tabletop play:

### Phase Mapping
| Round Phase | RPG Phase | Description |
|------------|-----------|-------------|
| EXPLORE | **Scene Setting** | DM describes scene, NPCs introduce themselves |
| WORK | **Player Actions** | Players declare actions, DM resolves |
| VALIDATE | **Resolution** | DM narrates outcomes, updates world state |

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
1. `rpg_master` announces round + current initiative
2. Each agent/player acts in initiative order
3. `rpg_pathfinder` skill resolves dice rolls, damage, conditions
4. `rpg_master` narrates results after each action
5. End of round — check conditions, ongoing effects

---

## Integration Points

| System | Integration |
|--------|-------------|
| **Roundtable** | Custom RPG roundtable mode in `aria_engine/roundtable.py` |
| **Agent Pool** | RPG agents loaded alongside standard agents |
| **Skills** | `rpg_pathfinder` registered in SkillRegistry |
| **Storage** | All data in `aria_memories/rpg/` (writable path ✅) |
| **Models** | RPG agents use models from `aria_models/models.yaml` |
| **Prompts** | Isolated in `prompts/rpg/` directory |

---

## Constraints Compliance

| # | Constraint | Status | Notes |
|---|-----------|--------|-------|
| 1 | 5-layer architecture | ✅ | Skills use api_client, no direct DB |
| 2 | .env secrets | ✅ | No secrets needed for RPG |
| 3 | models.yaml source of truth | ✅ | Agents use model refs from models.yaml |
| 4 | Docker-first | ✅ | Pure Python + YAML, no new services |
| 5 | aria_memories writable | ✅ | All RPG data in aria_memories/rpg/ |
| 6 | No soul modification | ✅ | RPG is separate from soul/identity |

</details>
