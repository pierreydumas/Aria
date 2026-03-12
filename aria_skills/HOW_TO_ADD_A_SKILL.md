# How to Add a New Skill to Aria

> Quick-reference guide. Follow these 3 steps and the system auto-wires everything.

---

## Step 1: Create the Skill Directory

```bash
cp -r aria_skills/_template aria_skills/my_new_skill
```

You get:
```
aria_skills/my_new_skill/
    __init__.py     # Skill class (edit this)
    skill.json      # Manifest (edit this)
    SKILL.md        # Documentation for Aria to read (edit this)
```

## Step 2: Edit the 3 Files

### skill.json — The Manifest

This is the **only config file** the auto-wiring engine reads. Get this right and everything else follows.

```json
{
  "name": "my_new_skill",
  "version": "1.0.0",
  "description": "Short description of what this skill does.",
  "author": "Your Name",
  "layer": 3,
  "status": "active",
  "dependencies": ["api_client"],
  "focus_affinity": ["data", "devsecops"],
  "tools": [
    {
      "name": "my_new_skill__do_thing",
      "description": "What this tool does. When to use it.",
      "input_schema": {
        "type": "object",
        "properties": {
          "param": {
            "type": "string",
            "description": "What this param means"
          }
        },
        "required": ["param"]
      }
    }
  ]
}
```

**Key fields:**

| Field | What it controls |
|-------|-----------------|
| `layer` | **Who gets it**: 0 = global (must be in allowlist), 1-2 = all agents, 3-4 = affinity-matched only |
| `focus_affinity` | **Which agents**: matches against agent `focus_type`. See table below. |
| `dependencies` | **Auto-included**: if agent gets your skill, dependencies come too |
| `status` | `active`, `stub`, `experimental`, `deprecated` |

**Focus affinity mapping:**

| Agent | focus_type | Matches affinity tags |
|-------|-----------|----------------------|
| aria | orchestrator | `orchestrator` |
| devops | devsecops | `devsecops` |
| analyst | data | `data`, `trader`, `research` |
| creator | social | `social`, `creative`, `journalist` |
| aria_talk | social | `social`, `creative`, `journalist` |
| memory | memory | `memory`, `cognitive` |
| rpg_master | rpg_master | `rpg_master` |
| aria-local | conversational | *(none — only gets L0-L2 skills)* |

**Example:** `"focus_affinity": ["devsecops"]` → only devops + aria (orchestrator gets L1-L2) get this skill.

### __init__.py — The Skill Class

Follow the template. Key rules:
- Class name: `PascalCase` + `Skill` suffix (e.g. `MyNewSkillSkill`)
- `.name` property must return the directory name (`my_new_skill`)
- Tool methods must match `skill.json` tool names exactly
- Use `@SkillRegistry.register` decorator

### SKILL.md — Documentation for Aria

This file is what Aria reads via `skill_guide__read("my_new_skill")`.

Include:
- **Purpose**: What problem does this solve?
- **Tools**: Name, parameters, return format for each tool
- **Examples**: Input/output examples so Aria knows how to call it
- **Error handling**: Common errors and how to fix them

Use the template in `aria_skills/_template/SKILL.md`.

## Step 3: Restart

```bash
docker restart aria-api
```

That's it. On startup:

1. `ToolRegistry.discover_from_manifests()` scans `aria_skills/*/skill.json` → finds your new skill
2. `build_agent_skill_map()` reads `layer` + `focus_affinity` → computes which agents get it
3. DB is updated with new skill assignments
4. Aria can now call `skill_guide__read("my_new_skill")` to learn how to use it

---

## Layer Reference

| Layer | Name | Who gets it | Examples |
|-------|------|------------|---------|
| 0 | Kernel | All agents (if in allowlist) | `input_guard` |
| 1 | API Client | All agents | `api_client` |
| 2 | Core | All agents | `llm`, `health`, `browser`, `skill_guide` |
| 3 | Domain | Affinity-matched agents | `research`, `market_data`, `ci_cd` |
| 4 | Orchestration | Affinity-matched agents | `schedule`, `pipeline_skill` |

Most new skills are **Layer 3**.

## Safety Limits

- **25 skills max per agent** — if exceeded, lower-layer skills are kept, higher are trimmed
- **L0 allowlist** — only `input_guard` can declare layer 0 (prevents manifest poisoning)
- **Fail-closed** — if an agent has no skills in DB, only L0 tools are available
- **Streaming enforce** — capability is checked both at tool-list time AND at execution time

## Troubleshooting

| Problem | Check |
|---------|-------|
| Skill not discovered | `skill.json` must be valid JSON in `aria_skills/<name>/` |
| Tool not available to agent | Check `layer` and `focus_affinity` in `skill.json` match agent's focus |
| Aria doesn't know how to use it | Create/improve `SKILL.md` with examples |
| Skill removed from agent after restart | `ARIA_SKILL_AUTO_WIRE=false` in env restores manual mode |
| Agent has too many skills (trimmed) | Cap is 25. Increase `MAX_SKILLS_PER_AGENT` in `tool_registry.py` or use `exclude_skills` |

## Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `ARIA_SKILL_AUTO_WIRE` | `true` | Enable/disable auto-wiring. When false, `agents_sync.py` writes skills from AGENTS.md |
