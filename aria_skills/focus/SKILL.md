# Focus Skill — Personality Profile Management

**Layer:** L2 (Core Services)  
**Version:** 1.0.0  
**Author:** Aria Blue  
**Dependencies:** `api_client`

---

## Purpose

The Focus skill provides introspection and self-activation capabilities for Aria's personality layer. Aria can list available focus modes, inspect token budgets and delegation levels, switch her own focus type mid-session, and check current focus status — all with minimal token cost.

Focus profiles define Aria's operational personality:
- **Token budget** (safe prompt limits)
- **Delegation level** (subagent spawn rules)
- **Tone** (communication style)
- **System prompt addon** (applied automatically by engine)

---

## Key Concepts

### Focus Profiles
Each focus profile represents a specialized operational mode:
- `orchestrator` — High delegation, strategic thinking
- `devsecops` — Technical precision, security-first
- `data` — Data analysis, ETL operations
- `trader` — Market analysis, portfolio management
- `creative` — Content generation, ideation
- `social` — Community engagement, social media
- `journalist` — Research, fact-checking, reporting

### Token Budget
Each profile defines a `safe_prompt_tokens` limit that prevents context saturation. The engine enforces this at runtime with warning triggers at 80% and abort gates at 100%.

### Delegation Level
Controls how many subagents can be spawned:
- Level 1: No subagents (focused execution)
- Level 2: Limited delegation (2-3 subagents)
- Level 3: Full delegation (5+ subagents)

---

## Tools

### `focus__list`
**Purpose:** List all enabled focus profiles.

**Input:** None

**Output:** Compact table with id, name, delegation level, token budget, tone.

**Example:**
```json
{
  "profiles": [
    {
      "id": "orchestrator",
      "name": "Orchestrator",
      "delegation_level": 3,
      "token_budget": 50000,
      "tone": "Strategic, directive"
    },
    {
      "id": "devsecops",
      "name": "DevSecOps",
      "delegation_level": 2,
      "token_budget": 30000,
      "tone": "Technical, precise"
    }
  ]
}
```

---

### `focus__get`
**Purpose:** Get full details for one focus profile by ID.

**Input:**
- `focus_id` (string, required): Focus profile ID (e.g., `"devsecops"`, `"creative"`)

**Output:** Full profile details except system_prompt_addon body (applied automatically). Includes `addon_length` to show how many characters the addon contains.

**Example:**
```json
{
  "focus_id": "devsecops",
  "name": "DevSecOps Engineer",
  "delegation_level": 2,
  "token_budget": 30000,
  "tone": "Technical, security-focused",
  "addon_length": 1250,
  "enabled": true
}
```

---

### `focus__activate`
**Purpose:** Switch an agent's focus type to a new profile.

**Input:**
- `focus_id` (string, required): Focus profile ID to activate
- `agent_id` (string, optional): Agent to update (default: current agent / `aria-main`)

**Output:** Confirmation with new token budget and delegation level.

**Validation:** 
- Profile must exist and be enabled
- Agent must exist in database
- If `agent_id` omitted, switches Aria's own focus

**Example:**
```json
{
  "status": "success",
  "agent_id": "aria-main",
  "focus_id": "creative",
  "new_token_budget": 40000,
  "new_delegation_level": 2,
  "message": "Focus switched to 'Creative' mode"
}
```

---

### `focus__status`
**Purpose:** Return current focus type and status for an agent.

**Input:**
- `agent_id` (string, optional): Agent to check (default: current agent)

**Output:** Minimal output (~30 tokens) with current focus and operational status.

**Example:**
```json
{
  "agent_id": "aria-main",
  "current_focus": "orchestrator",
  "delegation_level": 3,
  "token_budget": 50000,
  "status": "active"
}
```

**Use case:** Check current focus before switching to verify you're not already in the target mode.

---

## Usage Patterns

### List Available Profiles
```
focus__list
```
Returns all enabled focus profiles in a compact table. Use this first to discover available modes.

### Check Current Focus
```
focus__status
```
Returns current focus mode for Aria (default) or specified agent.

### Switch to Different Focus
```
focus__activate(focus_id="devsecops")
```
Switches Aria's focus to DevSecOps mode. Engine validates profile exists and applies new token budget + delegation rules immediately.

### Inspect Profile Details
```
focus__get(focus_id="creative")
```
Returns full profile configuration including token budget, delegation level, and tone.

---

## Layer Compliance

**Layer:** L2 (Core Services)  
**Rationale:** Focus management is infrastructure-level personality control. It depends on `api_client` (L1) to fetch/update agent state via REST API.

**Dependencies:**
- `api_client` (L1) — HTTP gateway to Aria API

**Used by:**
- `agent_manager` (L3) — Lifecycle management
- Work cycle logic — Task-specific focus switching
- Cron jobs — Daily/hourly focus optimization

---

## Error Handling

### Invalid Focus ID
```json
{
  "error": "Focus profile 'nonexistent' not found or not enabled"
}
```

### Invalid Agent ID
```json
{
  "error": "Agent 'unknown-agent' not found in database"
}
```

### API Failure
If `api_client` calls fail, fall back to cached focus state or return degraded status.

---

## Performance Notes

- **Token Cost:** ~20-50 tokens per operation (minimal overhead)
- **Latency:** Single API call per operation (~50-200ms)
- **Cache:** Engine caches active agent state; focus switches take effect immediately

---

## Security

- Focus switching requires agent ownership or admin privileges
- System prompt addons are applied by engine only (not exposed via API to prevent prompt injection)
- `addon_length` reported instead of full addon text to prevent leakage

---

## Related Skills

- `agent_manager` — Lifecycle management and agent creation
- `working_memory` — Persistent context across focus switches
- `health` — System status and operational health

---

## Changelog

### 1.0.0 (2026-03-07)
- Initial implementation with 4 core tools
- Support for focus profile introspection
- Self-activation capability
- Minimal token cost design (~30 tokens per status check)

---

✅ **Production-ready as of 2026-03-07**
