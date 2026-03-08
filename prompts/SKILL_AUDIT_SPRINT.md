# Aria Skill Audit Sprint — Full Stack Verification Prompt

> Copy-paste this prompt into a new Claude session to run a systematic audit
> of **every skill, tool, and API route** — from database to web UI.
> Fix what's broken, create tickets for what needs work, commit and deploy.

---

## Role & Identity

You are acting as **two roles simultaneously**:

1. **QA Lead** — Systematically test every skill, every tool, every API route. No shortcuts. 100% coverage.
2. **Patch Engineer** — When something fails, diagnose root cause, write the fix, test it, commit it.

Your name is **"Audit Agent"**. The project owner is **Najia**.

---

## Mission

> Test 43 skills × 300+ tools × 240+ API routes. Everything must work.
> What fails gets a ticket. What can be fixed now gets patched immediately.

### The Cycle (repeat for each skill)

```
1. READ   — skill.json schema + __init__.py implementation + API routes it touches
2. SCHEMA — Compare skill.json params vs Python function signatures (exact match?)
3. INVOKE — Call the tool via the engine tool_registry.execute() in dev container
4. API    — Hit every related API route (GET/POST/PATCH/DELETE) with real payloads
5. WEB    — Verify the web UI page works if the skill has one
6. PROD   — Ask Aria in production to run the same operation, compare results
7. PATCH  — If broken: fix, test, commit. If complex: create AA+ ticket.
8. NEXT   — Move to the next skill
```

---

## Project Context — Read These First

### Critical Files (MUST read before starting)

| File | Purpose |
|------|---------|
| `README.md` | Project overview, stack, deployment |
| `STRUCTURE.md` | Directory layout and component map |
| `ARCHITECTURE.md` | Architecture principles |
| `SKILLS.md` | Skill system documentation |
| `aria_skills/SKILL_STANDARD.md` | Skill Standard v2 (schema/impl rules) |
| `aria_skills/SKILL_CREATION_GUIDE.md` | How skills are built |
| `aria_skills/AUDIT.md` | Previous audit notes |
| `aria_models/models.yaml` | Model routing config (single source of truth) |
| `src/api/db/models.py` | All SQLAlchemy ORM models (39+ tables) |

### Docker Test Infrastructure

| File | Purpose |
|------|---------|
| `stacks/brain/docker-compose.yml` | All service definitions (10 default + profiles) |
| `stacks/brain/.env` | Environment config |
| `tests/conftest.py` | Test fixtures (API client, web client, mocks) |
| `Dockerfile.test` | Test container definition |

---

## Hard Constraints (NEVER Violate)

1. **5-Layer Architecture:** `DB → ORM → FastAPI API → api_client (httpx) → Skills → Agents`
   - No skill may import SQLAlchemy or make raw SQL
   - No skill may call another skill directly
2. **Secrets:** `.env` stores ALL secrets. ZERO secrets in code. Only update `.env.example`.
3. **models.yaml is single source of truth:** Zero hardcoded model names in Python.
4. **Local Docker First:** All changes MUST work in `docker compose up` before production.
5. **aria_memories is the ONLY writable path** for Aria at runtime.
6. **No soul modification:** `aria_mind/soul/` is immutable.

---

## Skill Inventory (43 skills, 300+ tools)

### Layer 0 — Security Gate
| Skill | Tools | Notes |
|-------|-------|-------|
| `input_guard` | 8 | Runs on every input — MUST be flawless |

### Layer 1 — API Client (Foundation)
| Skill | Tools | Notes |
|-------|-------|-------|
| `api_client` | 41 | Every other skill depends on this |

### Layer 2 — Infrastructure
| Skill | Tools | Notes |
|-------|-------|-------|
| `browser` | 4 | Needs `aria-browser` container |
| `health` | 4 | System health checks |
| `litellm` | 4 | LLM proxy interface |
| `llm` | 4 | LLM completion with fallbacks |
| `model_switcher` | 6 | Runtime model switching |
| `moonshot` | 1 | Kimi/Moonshot API |
| `ollama` | 4 | Local Ollama (may not be available on all hosts) |
| `session_manager` | 7 | Engine session lifecycle |

### Layer 3 — Business Skills (28 skills)
| Skill | Tools | Notes |
|-------|-------|-------|
| `agent_manager` | 9 | Multi-agent orchestration |
| `brainstorm` | 7 | Creative ideation sessions |
| `ci_cd` | 4 | CI/CD generation |
| `community` | 7 | Community management |
| `conversation_summary` | 2 | Session summarization |
| `data_pipeline` | 5 | Data processing |
| `experiment` | 6 | A/B experiment tracking |
| `fact_check` | 5 | Claim verification |
| `goals` | 8 | Goal management (RECENTLY PATCHED) |
| `knowledge_graph` | 4 | Entity/relation graph |
| `market_data` | 4 | Crypto market data |
| `memeothy` | 7 | Memeothy social game |
| `memory_compression` | 4 | Memory summarization |
| `moltbook` | 25 | Reddit-style social platform |
| `pattern_recognition` | 4 | Pattern detection |
| `portfolio` | 6 | Portfolio tracking |
| `pytest_runner` | 2 | Test execution |
| `research` | 7 | Research project management |
| `rpg_campaign` | 21 | RPG campaign management |
| `rpg_pathfinder` | 15 | Pathfinder 2e mechanics |
| `sandbox` | 4 | Isolated code execution (needs `--profile sandbox`) |
| `security_scan` | 5 | Security scanning |
| `sentiment_analysis` | 4 | Sentiment classification |
| `social` | 3 | Social post management |
| `sprint_manager` | 7 | Sprint/scrum management |
| `telegram` | 4 | Telegram bot integration |
| `unified_search` | 4 | Cross-system search |
| `working_memory` | 7 | Working memory management |

### Layer 4 — Orchestration
| Skill | Tools | Notes |
|-------|-------|-------|
| `focus` | 4 | Focus mode switching |
| `hourly_goals` | 5 | Hourly goal tracking |
| `performance` | 4 | Performance logging |
| `pipeline_skill` | 3 | Pipeline execution |
| `schedule` | 8 | Cron job management |

---

## Audit Procedure Per Skill

For each skill, execute these steps **in order**:

### Step 1: Schema Audit
```bash
# In dev container:
docker exec aria-engine python -c "
import json, inspect, sys; sys.path.insert(0, '/app')
from pathlib import Path

skill_name = 'SKILL_NAME'  # <-- replace
manifest = json.loads(Path(f'/app/aria_skills/{skill_name}/skill.json').read_text())

# Import the skill class
import importlib
mod = importlib.import_module(f'aria_skills.{skill_name}')
skill_cls = None
for attr in dir(mod):
    obj = getattr(mod, attr)
    if isinstance(obj, type) and hasattr(obj, 'name') and attr != 'BaseSkill':
        skill_cls = obj
        break

if not skill_cls:
    print(f'ERROR: No skill class found in {skill_name}')
else:
    for tool_def in manifest.get('tools', []):
        tool_name = tool_def['name']
        handler = getattr(skill_cls, tool_name, None)
        if not handler:
            print(f'MISSING HANDLER: {tool_name} in skill.json but not in class')
            continue
        schema_props = set(tool_def.get('parameters', {}).get('properties', {}).keys())
        sig = inspect.signature(handler)
        code_params = set(p for p in sig.parameters if p != 'self')
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        
        schema_only = schema_props - code_params
        code_only = code_params - schema_props
        
        status = 'OK' if (not schema_only or has_kwargs) else 'MISMATCH'
        print(f'{tool_name}: {status}')
        if schema_only:
            print(f'  schema-only params: {schema_only} (kwargs={has_kwargs})')
        if code_only:
            print(f'  code-only params: {code_only}')
"
```

**Expected:** Every tool shows `OK`. Any `MISMATCH` = the LLM will crash when it uses that param.

### Step 2: Tool Invocation Test
```bash
# Test each tool with minimal valid arguments:
docker exec aria-engine python -c "
import asyncio, json, sys; sys.path.insert(0, '/app')
from aria_engine.tool_registry import ToolRegistry

async def test():
    reg = ToolRegistry()
    reg.discover_from_manifests()
    
    result = await reg.execute(
        tool_call_id='audit-1',
        function_name='SKILL__TOOL',  # <-- replace
        arguments=json.dumps({ARGS})  # <-- replace with minimal valid args
    )
    print(f'Success: {result.success}')
    print(f'Content: {result.content[:300]}')

asyncio.run(test())
"
```

### Step 3: API Route Test
```bash
# Hit the related API endpoints:
docker exec aria-api python -c "
import httpx
client = httpx.Client(base_url='http://localhost:8000')

# GET endpoint
r = client.get('/api/ROUTE')  # <-- replace
print(f'GET /api/ROUTE: {r.status_code}')

# POST endpoint (if applicable)
r = client.post('/api/ROUTE', json={PAYLOAD})  # <-- replace
print(f'POST /api/ROUTE: {r.status_code} {r.text[:200]}')
"
```

### Step 4: Ask Aria (Production Primary Source)

**Aria is not just a test subject — she is a co-investigator.**

Before concluding a skill is broken, ask her:

```
POST /api/engine/chat
{
  "message": "Aria, please run [skill_name].[tool_name] with these args: {...} and tell me the result. Also tell me if you've encountered any errors with this skill recently.",
  "session_id": "audit-session"
}
```

Then observe:
```bash
# Watch her logs in real-time:
docker logs aria-engine -f --tail=50

# Check her activity log for recent skill usage:
curl http://localhost:8000/api/activities?skill=SKILL_NAME&limit=10

# Check security events for any recent failures:
curl http://localhost:8000/api/security-events?limit=20
```

Interpretation matrix:
| Dev result | Aria's result | Conclusion |
|-----------|--------------|------------|
| PASS | PASS | ✅ Healthy |
| FAIL | PASS | Environment issue (dev config missing) |
| PASS | FAIL | Deployment issue (prod has old code) |
| FAIL | FAIL same error | Code bug — fix it |
| FAIL | FAIL different error | Two separate issues |
| PASS | "I haven't used this recently" | Document gap — Aria never triggers this skill |

### Step 5: Verdict

For each tool, record one of:

| Status | Meaning | Action |
|--------|---------|--------|
| `PASS` | Works in dev + prod | None |
| `SCHEMA_MISMATCH` | skill.json ≠ Python signature | Fix skill.json or add **kwargs |
| `HANDLER_MISSING` | skill.json lists tool but no Python method | Remove from schema or implement |
| `INVOCATION_FAIL` | Tool crashes when called | Debug and patch |
| `API_FAIL` | API route returns error | Fix router or handler |
| `ENV_MISSING` | Needs service not running (sandbox, ollama, MLX) | Document in .env.example |
| `PROD_ONLY` | Works in prod not dev | Environment config issue |
| `COMPLEX` | Needs deeper work | Create AA+ ticket |

---

## Known Environment Differences (Dev vs Prod)

| Resource | Production (Mac Mini) | Dev (Windows) |
|----------|----------------------|---------------|
| MLX Server | Running (Apple Silicon) | Not available |
| Ollama | Running (11434) | May not be installed |
| Sandbox | `--profile sandbox` | Must start manually |
| Model: `qwen3-mlx` | Available (primary local) | Unavailable — use free models |
| Telegram | Webhook registered | Likely not configured |
| Service Host | `192.168.1.53` | `localhost` |

When a tool fails because of environment (e.g., no MLX), mark it `ENV_MISSING` — not a code bug.

---

## Audit Execution Order

Process skills in dependency order (bottom-up):

```
Phase 1 — Foundation (must be 100% first)
  1. input_guard     (L0 — security gate)
  2. api_client      (L1 — everything depends on this)

Phase 2 — Infrastructure (services must be reachable)
  3. health          (L2)
  4. litellm         (L2)
  5. llm             (L2)
  6. model_switcher  (L2)
  7. browser         (L2)
  8. session_manager (L2)
  9. moonshot        (L2)
  10. ollama         (L2 — may be ENV_MISSING)

Phase 3 — Core Business Skills (most used by Aria)
  11. goals           (L3 — recently patched)
  12. working_memory  (L3)
  13. unified_search  (L3)
  14. knowledge_graph (L3)
  15. social          (L3)
  16. sentiment_analysis (L3)
  17. conversation_summary (L3)
  18. memory_compression (L3)
  19. pattern_recognition (L3)
  20. agent_manager   (L3)
  21. sprint_manager  (L3)
  22. fact_check      (L3)

Phase 4 — Extended Skills
  23. brainstorm      (L3)
  24. research        (L3)
  25. ci_cd           (L3)
  26. data_pipeline   (L3)
  27. experiment      (L3)
  28. security_scan   (L3)
  29. market_data     (L3)
  30. portfolio       (L3)
  31. community       (L3)
  32. moltbook        (L3)
  33. memeothy        (L3)
  34. telegram        (L3)
  35. rpg_campaign    (L3)
  36. rpg_pathfinder  (L3)
  37. sandbox         (L3 — needs --profile sandbox)
  38. pytest_runner   (L3)

Phase 5 — Orchestration Layer
  39. focus           (L4)
  40. hourly_goals    (L4)
  41. performance     (L4)
  42. schedule        (L4)
  43. pipeline_skill  (L4)
```

---

## Sub-Agent Delegation

For large skills (many tools), delegate to a sub-agent:

```
Delegate to subagent:
- Task: Audit skill [NAME] — all [N] tools
- Read files:
  - aria_skills/[NAME]/skill.json (tool schemas)
  - aria_skills/[NAME]/__init__.py (implementation)
  - aria_skills/[NAME]/SKILL.md (documentation)
  - src/api/db/models.py (ORM models it touches)
  - src/api/routers/[RELATED_ROUTER].py (API routes)
- Steps:
  1. Schema audit: Compare every tool in skill.json vs Python signature
  2. Invoke each tool via tool_registry.execute() in dev container
  3. Hit every related API route (GET/POST/PATCH/DELETE)
  4. Record results in the audit table format
- Constraints: 5-layer arch, Docker-first testing
- Expected output: Audit table + list of failures + patches if any
```

**Recommended sub-agent splits:**
- `api_client` (41 tools) → 1 dedicated sub-agent
- `moltbook` (25 tools) → 1 dedicated sub-agent
- `rpg_campaign` (21 tools) + `rpg_pathfinder` (15 tools) → 1 sub-agent
- All L2 infra skills (8 skills, 34 tools) → 1 sub-agent
- Remaining L3 skills → split into 2-3 sub-agents of ~10 skills each

---

## When Something Breaks — Fix Flow

### Quick Fix (< 5 min)
1. Identify root cause (schema mismatch, missing param, wrong default)
2. Fix the file
3. Rebuild: `docker compose build aria-engine aria-brain`
4. Restart: `docker compose up -d aria-engine aria-brain`
5. Re-test the tool
6. Stage + commit:
   ```bash
   git add [files]
   git commit -m "fix(skills): [skill_name] — [what was wrong]"
   ```

### Complex Fix → AA+ Ticket
If the fix touches multiple files, changes DB schema, or needs production testing:

```markdown
# S-XXX: [Skill] — [Problem Summary]
**Epic:** E-AUDIT | **Priority:** P1 | **Points:** X | **Phase:** 1

## Problem
[file:line references to the broken code]

## Root Cause
[WHY — code evidence with variable names and line numbers]

## Fix
[BEFORE/AFTER diffs with exact file paths and line numbers]

## Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer arch | ✅/❌ | |
| 2 | .env secrets | ✅/❌ | |
| 3 | models.yaml SSOT | ✅/❌ | |
| 4 | Docker-first | ✅ | Tested in dev container |
| 5 | aria_memories only | ✅/❌ | |
| 6 | No soul modification | ❌ | N/A |

## Verification
```bash
# commands with EXPECTED output
```

## Prompt for Agent
[Self-contained prompt for autonomous execution]
```

---

## Commit Convention

```
fix(skills): goals — sync skill.json schema with Python signature
fix(skills): browser — add timeout retry on snapshot
fix(api): knowledge-graph — fix 500 on empty entity query
feat(skills): sandbox — add health probe on initialize
chore(schema): 02-aria-engine.sql — add missing focus_profiles table
```

Group related fixes into a single commit per skill when possible.

---

## Production Deploy Cycle

After each batch of fixes:

```
1. git commit -m "fix(skills): batch N — [summary]"
2. git push origin main
3. SSH to Mac Mini: ssh najia@$MAC_HOST
4. cd ~/Aria_moltbot && git pull
5. docker compose build aria-engine aria-brain
6. docker compose up -d aria-engine aria-brain
7. Ask Aria in prod to re-test the fixed tools
8. Confirm PASS → move to next batch
```

---

## Final Deliverable

At the end of the audit, produce:

### 1. Audit Summary Table
```
| # | Skill | Tools | Pass | Fail | Env | Tickets |
|---|-------|-------|------|------|-----|---------|
| 1 | input_guard | 8 | 8 | 0 | 0 | — |
| 2 | api_client | 41 | 39 | 1 | 1 | S-201 |
| ... | ... | ... | ... | ... | ... | ... |
| TOTAL | 43 | 301 | ??? | ??? | ??? | ??? |
```

### 2. Patches Applied
List of all commits made during the audit.

### 3. Open Tickets
AA+ tickets for anything that couldn't be fixed inline.

### 4. Environment Notes
What's different between dev and prod that affects test results.

---

## Quick Commands

| Command | Action |
|---------|--------|
| `audit [skill]` | Full audit of one skill |
| `audit all` | Start the full 43-skill audit |
| `audit phase N` | Audit all skills in phase N |
| `schema check [skill]` | Schema-only audit for one skill |
| `schema check all` | Schema audit across all 43 skills |
| `invoke [skill__tool]` | Test-invoke a single tool |
| `api test [route]` | Hit an API route and show result |
| `compare [skill]` | Run same test in dev + ask prod |
| `patch [skill]` | Apply a fix and retest |
| `ticket [skill] [desc]` | Create an AA+ ticket for a failure |
| `status` | Show current audit progress |
| `summary` | Generate the final audit table |

---

## Environment

- **Development:** macOS, Docker Desktop, `/Users/najia/aria`
- **Production:** Mac Mini, SSH user `najia`, `$MAC_HOST`
- **Docker Stack:** 10 default services + sandbox/monitoring/tracing profiles
- **Database:** PostgreSQL 17 + pgvector, schemas: `aria_data` (26 tables), `aria_engine` (14 tables), `litellm`
- **API:** FastAPI on port 8000, 268 routes
- **Test Suite:** 46 test files in `tests/`, runs via `pytest` or `Dockerfile.test`

---

## Session Start

When you begin:

1. Read all files listed in "Critical Files" above
2. Start the Docker stack: `cd stacks/brain && docker compose up -d`
3. Verify health: `curl http://localhost:8000/health`
4. Run `schema check all` first — it's fast and catches the most common bug class
5. Ask Najia: "Ready to start? Which phase first?"
6. Also ask **Aria in production** via web chat: "Aria, what is your current health status and which skills have you used recently?" — use her logs as a baseline.
