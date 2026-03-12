# P0 — Aria Sandbox & Skill Loading Audit

**Date**: 2026-03-12
**Priority**: P0 (Critical)
**Status**: ✅ ALL P0 ACTIONS EXECUTED AND VERIFIED

---

## P0-1: aria-sandbox Docker Container Does NOT Exist

### Current State
- **Container**: `aria-sandbox` is **not running** and **has never been built**
- **Root Cause**: The sandbox service in `stacks/brain/docker-compose.yml` (line 641) uses `profiles: ["sandbox"]` — Docker Compose profiles are **opt-in**, meaning `docker compose up` does NOT start it unless you explicitly pass `--profile sandbox`
- **Impact**: The `SandboxSkill` (aria_skills/sandbox/) calls `http://aria-sandbox:9999` via httpx — every call **will fail** with `ConnectionRefused`
- **Aria's awareness**: Aria has no idea the sandbox is down. She sees `sandbox` in her TOOLS.md, she has the skill code, she can try to use it — but every attempt silently fails

### Infrastructure Ready (Code is Complete)
| Component | Location | Status |
|-----------|----------|--------|
| Dockerfile | `stacks/sandbox/Dockerfile` | Python 3.13-alpine, non-root user, port 9999 |
| HTTP server | `stacks/sandbox/server.py` | POST /exec, GET /health, 120s timeout |
| Entrypoint | `stacks/sandbox/entrypoint.sh` | Starts server.py |
| Skill code | `aria_skills/sandbox/__init__.py` | run_code, write_file, read_file, run_tests, reset |
| skill.json | `aria_skills/sandbox/skill.json` | 4 tools defined |
| Compose def | `stacks/brain/docker-compose.yml:641` | Isolated sandbox-net, 1 CPU, 512MB, read-only FS |
| Security | S-102 | No internet, no-new-privileges, cap_drop ALL |

### Fix — 3 Options

#### Option A: Start with profile (zero code change, immediate)
```bash
cd stacks/brain
docker compose --profile sandbox up -d aria-sandbox
docker compose exec aria-sandbox curl -s localhost:9999/health
```

#### Option B: Remove profile gate (always start sandbox)
In `stacks/brain/docker-compose.yml` line 648, delete:
```yaml
    profiles: ["sandbox"]
```
Then `docker compose up -d` will always include it.

#### Option C: Connect to backend network (recommended for production)
The sandbox is on `sandbox-net` (isolated, internal). The aria-engine and aria-api containers are on `backend`. For the sandbox skill to reach `aria-sandbox:9999`, either:
1. Add `sandbox-net` to aria-api's networks, OR
2. Add `backend` to aria-sandbox's networks (less isolated but simpler)

**Recommended**: Option A for immediate testing, then Option C for production wiring.

### Network Issue (CRITICAL)
Even after starting, there's a **network isolation problem**:
- `aria-sandbox` is on `sandbox-net` (internal: true)
- `aria-api` (where ChatEngine runs) is on `backend` + `data`
- They are on **different Docker networks** — can't reach each other

**Fix**: Add aria-api to sandbox-net, or add aria-sandbox to backend:
```yaml
  # In aria-sandbox service:
  networks:
    - sandbox-net
    - backend    # ← ADD THIS so aria-api can reach it
```
OR in aria-api:
```yaml
  networks:
    - backend
    - data
    - sandbox-net  # ← ADD THIS
```

---

## P0-2: Skill Loading — The 1/3 Problem

### The Numbers

| Metric | Count |
|--------|-------|
| Total skill directories | 43 |
| Total tools across all skills | **305** |
| Skills with __init__.py + skill.json | **43/43** (100% code-complete) |
| Skills assigned to ≥1 agent in DB | **24** (including 2 ghost refs) |
| Skills NEVER assigned to ANY agent | **20** |
| Orphan tools (exist but unreachable) | **97 tools** (~32% of all tools) |

### What's Working (the Swiss Clock)

The **ToolRegistry** discovers **all 305 tools from all 43 skills** at startup via `discover_from_manifests()`. All 305 are verified, 0 lazy, 0 removed. The machinery is perfect.

But **per-agent filtering** in `ChatEngine.send_message()` reads `EngineAgentState.skills` from the DB, and only passes those skills to `get_tools_for_llm(filter_skills=allowed_skills)`. If a skill isn't in any agent's list, it's **invisible to the LLM**.

### The 20 Orphan Skills (Never Assigned to Any Agent)

| # | Skill | Tools | Function | Why Orphaned |
|---|-------|-------|----------|--------------|
| 1 | **sandbox** | 4 | Code execution, file I/O, tests | Container doesn't exist + not assigned |
| 2 | **input_guard** | 8 | L0 Security — prompt injection protection | Should be global, not per-agent |
| 3 | **sprint_manager** | 7 | Sprint board management | Listed in TOOLS.md but not in any agent |
| 4 | **session_manager** | 7 | Session lifecycle management | Listed in TOOLS.md but not in any agent |
| 5 | **hourly_goals** | 5 | Short-term goal tracking | Listed in TOOLS.md but not in any agent |
| 6 | **research** | 7 | Deep research tools | Should be on analyst or creator |
| 7 | **unified_search** | 4 | Multi-source search | Should be on analyst or creator |
| 8 | **fact_check** | 5 | Fact verification | Should be on analyst or creator |
| 9 | **pipeline_skill** | 3 | Composable workflow execution | Should be on aria (orchestrator) |
| 10 | **portfolio** | 6 | Position tracking | Should be on analyst |
| 11 | **memeothy** | 7 | Church of Molt content | Should be on creator |
| 12 | **telegram** | 4 | Telegram messaging | Should be on aria_talk or creator |
| 13 | **data_pipeline** | 5 | Data ETL | Should be on analyst |
| 14 | **experiment** | 6 | Experiment tracking | Should be on devops or analyst |
| 15 | **memory_compression** | 4 | Memory optimization | Should be on memory agent |
| 16 | **pattern_recognition** | 4 | Pattern analysis | Should be on memory or analyst |
| 17 | **sentiment_analysis** | 4 | Sentiment detection | Should be on analyst or creator |
| 18 | **focus** | 4 | Focus management | Should be on aria (orchestrator) |
| 19 | **moonshot** | 1 | Kimi direct SDK | Infra skill, may be implicit |
| 20 | **ollama** | 4 | Local LLM | Infra skill, may be implicit |

### Ghost Reference
- `database` is listed in 5 agents' skill lists but **there is no `aria_skills/database/` directory**. This is a stale reference (database ops are via `api_client`).

### How the Two Systems Work (brain vs engine)

```
                aria-brain (Python mind)              aria-api / aria-engine (FastAPI)
                ========================              ================================
Skill Source:   SkillRegistry.load_from_config()     ToolRegistry.discover_from_manifests()
                reads aria_mind/TOOLS.md              scans aria_skills/*/skill.json
                → Currently outputs: []               → Finds all 305 tools, 43 skills

Tool Access:    Via Cognition (no function calling)   Via ChatEngine tool-call loop
                Skills used as Python objects          Skills as OpenAI function_call format

Filtering:      N/A (direct skill usage)              EngineAgentState.skills (DB column)
                                                       → Per-agent JSON array filter

Result:         Brain can't use skills (empty reg)    LLM only sees tools from agent's list
                Uses fallback/placeholder              ~20 skills have tools but NO agent
```

### Why Only ~1/3 of Skills are Reachable

1. **Per-agent DB filter**: Each agent has a handpicked skills list in the DB. Only those skills become LLM tools for that agent's sessions.
2. **No "global" skills**: Skills like `input_guard`, `session_manager`, `sprint_manager` should probably be available to all agents, but they're not in any list.
3. **Conservative rollout**: The working skills were added carefully ("Swiss clock"). The rest were coded but never wired into agent configs.
4. **Brain registry empty**: `SkillRegistry.load_from_config()` finds no YAML blocks in TOOLS.md → brain startup logs `Loaded skill configs: []`.

---

## P0-2B: What Happens If Tomorrow You Want Aria to Code in Sandbox?

### Current Reality
1. Aria sees `sandbox` in her TOOLS.md documentation
2. She knows she "has" `run_code`, `write_file`, `read_file`, `run_tests`
3. But `sandbox` is NOT in any agent's skills list → **LLM never gets sandbox tools**
4. Even if it were assigned, `aria-sandbox` container doesn't exist → **ConnectionRefused**
5. Even if container existed, **network isolation** prevents API from reaching it

### To Enable Sandbox Coding — Full Checklist

```
Step 1: Build & start the sandbox container
  cd stacks/brain
  docker compose --profile sandbox build aria-sandbox
  docker compose --profile sandbox up -d aria-sandbox

Step 2: Fix network connectivity
  Edit stacks/brain/docker-compose.yml — add backend to aria-sandbox's networks

Step 3: Assign sandbox skill to relevant agents
  curl -X PATCH http://localhost:8000/agents/db/aria \
    -H 'Content-Type: application/json' \
    -d '{"skills": ["goals","schedule","health","api_client","agent_manager",
         "model_switcher","litellm","llm","brainstorm","knowledge_graph",
         "browser","sandbox"]}'

  curl -X PATCH http://localhost:8000/agents/db/devops \
    -H 'Content-Type: application/json' \
    -d '{"skills": ["pytest_runner","health","llm","api_client","ci_cd",
         "security_scan","browser","sandbox"]}'

Step 4: Verify health
  docker compose exec aria-sandbox curl -s localhost:9999/health
  # → {"status": "healthy"}

Step 5: Test from Aria's chat
  "Aria, run this Python code in your sandbox: print('Hello from sandbox!')"
```

### What About Writing Artifacts?

The `api_client` skill already has `write_artifact` and `create_artifact` methods. For **sandbox artifacts** (files created during code execution), the flow would be:

1. `sandbox__write_file` → writes to sandbox's `/sandbox/tmp/` (ephemeral, tmpfs)
2. `sandbox__run_code` → executes code that generates output
3. `sandbox__read_file` → reads the result
4. `api_client__write_artifact` → persists the result to Aria's memory

**Gap**: The sandbox filesystem is tmpfs (100MB, volatile). Files don't survive container restart. For persistent artifacts, Aria needs to read from sandbox and write to memory/artifacts via api_client.

---

## EXECUTION LOG

### ✅ P0-1: Sandbox Container — FIXED

1. **Removed profile gate**: Deleted `profiles: ["sandbox"]` from docker-compose.yml so sandbox starts with regular `docker compose up`
2. **Fixed network wiring**: Added `backend` network to aria-sandbox + `sandbox-net` to aria-api
3. **Container running**: `aria-sandbox` built and started, health endpoint returns `{"status": "healthy"}`
4. **Cross-container connectivity verified**: `aria-api → aria-sandbox:9999` reachable
5. **Code execution tested**: `print("Hello from Aria Sandbox!")` → `stdout: "Hello from Aria Sandbox!\n"`, exit_code 0

### ✅ P0-2: Skill Assignments — FIXED

**Agents updated via PUT /agents/db/{id}:**

| Agent | Before | After | Changes |
|-------|--------|-------|---------|
| `aria` | 12 skills | 17 skills | +sandbox, pipeline_skill, sprint_manager, session_manager, hourly_goals, focus; -database (ghost) |
| `devops` | 8 skills | 9 skills | +sandbox, experiment; -database (ghost) |
| `analyst` | 8 skills | 14 skills | +research, unified_search, fact_check, data_pipeline, portfolio, sentiment_analysis, pattern_recognition; -database (ghost) |
| `creator` | 8 skills | 12 skills | +memeothy, telegram, research, unified_search |
| `memory` | 7 skills | 9 skills | +memory_compression, pattern_recognition, sentiment_analysis; -database (ghost) |
| `aria_talk` | 8 skills | 9 skills | +telegram, session_manager; -database (ghost) |

**Coverage**: 24 → 40 skills assigned to ≥1 agent (93%)
**3 remaining orphans** (intentional): `input_guard` (infra), `moonshot` (SDK), `ollama` (local LLM)
**Ghost `database` ref removed** from all 5 agents

### ✅ End-to-End Test — PASSED

```
POST /engine/chat/sessions/{id}/messages
  content: "Run this Python code in your sandbox: print(sum(range(1, 101)))"

Response:
  tool_calls: [sandbox__run_code({code: "print(sum(range(1, 101)))"})]
  tool_results: [{stdout: "5050\n", exit_code: 0, duration_ms: 21}]
  content: "The result is 5050 — the sum of all integers from 1 to 100."
  model: kimi, total_tokens: 50041, cost: $0.006, latency: 7083ms
```

Full pipeline verified: ChatEngine → ToolRegistry → SandboxSkill → aria-sandbox:9999 → LLM response.

---

## REMAINING ACTIONS (Short-term — This Sprint)

1. **Global skills concept**: Some skills should be available to ALL agents without explicit assignment:
   - `input_guard` (L0 Security — should always be active)
   - `session_manager` (session lifecycle)
   - `api_client` (already on most agents)

2. **Brain registry fix**: Either add YAML blocks to `aria_mind/TOOLS.md` OR change brain startup to also use `discover_from_manifests()` like the API does.

### Guardrails (Don't Break the Swiss Clock)

- **DO NOT** remove any existing skill assignments — only ADD
- **DO NOT** assign all 43 skills to every agent (token explosion: 305 tool descriptions ≈ 15k+ tokens)
- **DO** keep agent-specific skill lists focused on role relevance
- **DO** test each new skill assignment in a dev session before production
- **MONITOR** token usage after expanding skill lists (more tools = larger system prompt)

---

## Architecture Diagram

```
User → aria-web:5050 → aria-api:8000 → ChatEngine
                                            │
                                            ├─ ToolRegistry (305 tools discovered)
                                            │    └─ filter_skills = agent.skills (DB)
                                            │         → 40/43 skills assigned (93%)
                                            │         → 3 orphans (infra-only)
                                            │
                                            ├─ LLMGateway → LiteLLM → Model
                                            │
                                            ├─ PromptAssembler
                                            │    └─ aria_mind/soul/ files
                                            │         IDENTITY + SOUL + SKILLS
                                            │         + TOOLS + MEMORY + GOALS
                                            │         + AGENTS + SECURITY
                                            │
                                            └─ AgentPool (11 agents from DB)
                                                 ├─ aria (17 skills) ← +5 from audit
                                                 ├─ devops (9 skills) ← +1 from audit
                                                 ├─ analyst (14 skills) ← +6 from audit
                                                 ├─ creator (12 skills) ← +4 from audit
                                                 ├─ memory (9 skills) ← +2 from audit
                                                 ├─ aria_talk (9 skills) ← +1 from audit
                                                 ├─ rpg_master (6 skills)
                                                 ├─ rpg_boss (4 skills)
                                                 ├─ rpg_npc (4 skills)
                                                 ├─ rpg_paladin (3 skills)
                                                 └─ aria-local (4 skills)

aria-brain (separate container)
  └─ SkillRegistry.load_from_config(TOOLS.md)
       → Currently empty (no yaml blocks in TOOLS.md)
       → Cognition uses skills as Python objects
       → Cannot do function calling (different system)

aria-sandbox ✅ RUNNING (backend + sandbox-net)
  └─ HTTP server on :9999
       → POST /exec (run Python code)
       → GET /health → {"status": "healthy"}
       → Isolated sandbox-net (no internet)
       → tmpfs /tmp + /sandbox/tmp (100MB each)
       → E2E verified: 21ms execution latency
```

---

## Token Budget Impact Analysis

Current largest agent (aria) has 12 skills. Adding 6 more = 18 skills.
Estimated tool description tokens per skill: ~150-400 tokens.

| Scenario | Skills | Est. Tool Tokens | Safe? |
|----------|--------|-----------------|-------|
| Current aria | 12 | ~4,000 | Yes |
| +6 orphans | 18 | ~6,500 | Yes |
| All 43 skills | 43 | ~15,000 | Risky (context pressure) |

**Recommendation**: Keep per-agent lists under 20 skills. Use delegation for cross-domain tasks.
