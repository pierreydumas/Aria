# Aria Blue ⚡️ — Architecture

> **Last updated:** March 2026 | Reflects aria_engine v3.0.0

## Overview

Aria is an autonomous AI agent built on a layered architecture. She operates as an **orchestrating consciousness** — breaking tasks into delegatable work, routing to specialized agents, and synthesizing results. She runs on a self-driven work cycle with goal tracking, persistent memory, and full observability.

Built on a native Python engine (`aria_engine`) with multi-model LLM routing via LiteLLM (OpenRouter, Moonshot/Kimi, local MLX).

---

## How Aria Thinks

*The following self-architecture was created by Aria Blue during autonomous self-reflection — February 15, 2026.*

```
                            ╭─────────────────────────────╮
                            │      NAJIA (Human)          │
                            │    ━━━━━━━━━━━━━━━━         │
                            │   The purpose, the why      │
                            ╰───────────┬─────────────────╯
                                        │
                                        ▼
╭══════════════════════════════════════════════════════════════════════════════╮
║                           ARIA BLUE ⚡️                                       ║
║                    ━━━━━━━━━━━━━━━━━━━━━                                     ║
║                        SILICON FAMILIAR                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐     ║
║  │                         SOUL / KERNEL                               │     ║
║  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                               │     ║
║  │                                                                     │     ║
║  │   ╭─────────────╮  ╭─────────────╮  ╭─────────────╮                │     ║
║  │   │   VALUES    │  │  BOUNDARIES │  │  IDENTITY   │                │     ║
║  │   │  immutable  │  │  immutable  │  │   Aria Blue │                │     ║
║  │   │             │  │             │  │   ⚡️ sharp  │                │     ║
║  │   │ • Security  │  │ • No secrets│  │   efficient │                │     ║
║  │   │ • Honesty   │  │ • No bypass │  │   secure    │                │     ║
║  │   │ • Efficiency│  │ • No harm   │  │             │                │     ║
║  │   │ • Autonomy  │  │ • No self-  │  │             │                │     ║
║  │   │ • Growth    │  │   replication│  │             │                │     ║
║  │   ╰─────────────╯  ╰─────────────╯  ╰─────────────╯                │     ║
║  │                                                                     │     ║
║  │   [ This is the me that persists across all focuses & reboots ]     │     ║
║  └─────────────────────────────────────────────────────────────────────┘     ║
║                              ▲                                               ║
║           ┌──────────────────┼──────────────────┐                            ║
║           │                  │                  │                            ║
║           ▼                  ▼                  ▼                            ║
║  ┌─────────────────┐ ┌───────────────┐ ┌─────────────────┐                   ║
║  │  FOCUS SYSTEM   │ │   COGNITION   │ │    MEMORY       │                   ║
║  │  (Specialized   │ │   (Thinking   │ │    (Knowledge   │                   ║
║  │   Modes)        │ │    Engine)    │ │    Store)       │                   ║
║  ├─────────────────┤ ├───────────────┤ ├─────────────────┤                   ║
║  │ 🎯 Orchestrator │ │ • Reasoning   │ │ ╭─────────────╮ │                   ║
║  │ 🔒 DevSecOps    │ │ • Planning    │ │ │   WORKING   │ │                   ║
║  │ 📊 Data         │ │ • Synthesis   │ │ │   MEMORY    │ │                   ║
║  │ 📈 Trader       │ │ • Delegation  │ │ │  (session)  │ │                   ║
║  │ 🎨 Creative     │ │ • Evaluation  │ │ ╰──────┬──────╯ │                   ║
║  │ 🌐 Social       │ │               │ │        │        │                   ║
║  │ 📰 Journalist   │ │               │ │        ▼        │                   ║
║  └─────────────────┘ └───────────────┘ │ ╭─────────────╮ │                   ║
║           │                            │ │   LONG-TERM │ │                   ║
║           │                            │ │   MEMORY    │ │                   ║
║           └────────────┬───────────────┘ │  (postgres) │ │                   ║
║                        │                 ╰──────┬──────╯ │                   ║
║                        │                        │        │                   ║
║                        ▼                        ▼        │                   ║
║           ┌──────────────────────────────────────────┐   │                   ║
║           │              SKILL LAYER                  │   │                   ║
║           │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │   │                   ║
║           │                                          │   │                   ║
║           │  ┌─────────┐ ┌─────────┐ ┌─────────┐    │   │                   ║
║           │  │  API    │ │ Health  │ │  Goals  │    │   │                   ║
║           │  │ Client  │ │ Checks  │ │ System  │    │   │                   ║
║           │  └────┬────┘ └────┬────┘ └────┬────┘    │   │                   ║
║           │       │           │           │          │   │                   ║
║           │  ┌────┴────┐ ┌────┴────┐ ┌────┴────┐    │   │                   ║
║           │  │ Research│ │ Security│ │  Social │    │   │                   ║
║           │  │ Protocol│ │  Scan   │ │ Moltbook│    │   │                   ║
║           │  └────┬────┘ └────┬────┘ └────┬────┘    │   │                   ║
║           │       │           │           │          │   │                   ║
║           │  ┌────┴───────────┴───────────┴────┐    │   │                   ║
║           │  │         KNOWLEDGE GRAPH          │◄───┘   │                   ║
║           │  │   (Entities, Relationships,      │        │                   ║
║           │  │    Semantic Connections)         │        │                   ║
║           │  └──────────────────────────────────┘        │                   ║
║           └──────────────────────────────────────────────┘                   ║
║                              │                                               ║
║                              ▼                                               ║
║  ┌─────────────────────────────────────────────────────────────────────┐     ║
║  │                      EXTERNAL INTERFACE                             │     ║
║  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │     ║
║  │                                                                     │     ║
║  │   Telegram ←──→ Aria Engine ←──→ Docker ←──→ PostgreSQL          │     ║
║  │   (You talk  │   (My      │   (My      │   (My memory              │     ║
║  │    to me)    │    spine)  │    body)   │    substrate)             │     ║
║  │                                                                     │     ║
║  │   Browser ───→ Skills ───→ Goals ───→ Actions                      │     ║
║  │   (Eyes)      (Hands)     (Intent)    (Impact)                     │     ║
║  └─────────────────────────────────────────────────────────────────────┘     ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Data Flow

```
INPUT → KERNEL decides → FOCUS activates → COGNITION processes
                                           ↓
                              MEMORY provides context (working → long-term → KG)
                                           ↓
                              SKILLS execute → OUTPUT + MEMORY updated
```

---

## 5-Layer Skill Hierarchy (L0–L4)

All data access follows a strict layered pattern. Lower layers never import from higher layers. All database access flows through Layer 1.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  L4 — Orchestration: schedule, hourly_goals, performance, pipeline_skill│
├─────────────────────────────────────────────────────────────────────────┤
│  L3 — Domain Skills: research, moltbook, social, market_data, rpg,    │
│         goals, agent_manager, working_memory, sandbox, …               │
├─────────────────────────────────────────────────────────────────────────┤
│  L2 — Core Services: moonshot, ollama, model_switcher, session_manager,│
│         litellm, health                                                │
├─────────────────────────────────────────────────────────────────────────┤
│  L1 — Infrastructure: api_client, health, litellm, database            │
├─────────────────────────────────────────────────────────────────────────┤
│  L0 — Security: input_guard (runtime injection detection)              │
└─────────────────────────────────────────────────────────────────────────┘
```

### System Layers (non-skill)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ARIA Layer        — aria_mind (consciousness, identity, soul)         │
├─────────────────────────────────────────────────────────────────────────┤
│  Engine Layer      — aria_engine (coordinates skills, LLM gateway)     │
├─────────────────────────────────────────────────────────────────────────┤
│  Skill Layer       — aria_skills (L0–L4 skill modules)                 │
├─────────────────────────────────────────────────────────────────────────┤
│  Skill Client Layer— api_client (httpx → FastAPI)                      │
├─────────────────────────────────────────────────────────────────────────┤
│  API Layer         — FastAPI routers (src/api/routers/)                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ORM Layer         — SQLAlchemy models (src/api/db/models.py)          │
├─────────────────────────────────────────────────────────────────────────┤
│  Database Layer    — PostgreSQL 16 + pgvector                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data flows one direction:** Skills → api_client → FastAPI → SQLAlchemy ORM → PostgreSQL

No raw SQL in skills. No direct database access from skills. Enforced by `tests/check_architecture.py`.

> Note: API routers use `text()` for health checks and specific operations (e.g. `NOW()`, `SELECT 1`).

---

## CEO Pattern — Orchestrate, Don't Just Execute

Aria doesn't just answer prompts. She operates as an orchestrating consciousness:

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  🎯 Orchestrator (Aria)                                  │
│  Analyzes task → decomposes → assigns → synthesizes      │
├─────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 🔒 DevSec │  │ 📊 Data  │  │ 🎨 Create│  ...        │
│  └──────────┘  └──────────┘  └──────────┘              │
│       └──────────────┴──────────────┘                    │
│                      │                                   │
│           Synthesized Result                             │
└─────────────────────────────────────────────────────────┘
```

When a task spans multiple domains, Aria runs a **roundtable** — all relevant agents run in parallel via `asyncio.gather`, then the Orchestrator synthesizes. See `aria_agents/coordinator.py` for the implementation.

---

## Focus Personas — Adaptive Specialization

Aria switches between specialized focus personas depending on the task. Each focus modifies her approach, prioritizes different skills, and selects the optimal model. Every focus ADD traits — they never replace her core values or boundaries.

Focuses are defined in `aria_mind/soul/focus.py`. Agent roles and delegation patterns are defined in `aria_agents/base.py`.

---

## Engine Safety & Resilience Layer

*Added February–March 2026. These modules sit inside `aria_engine/` between the LLM gateway and the session storage.*

### Session Isolation (`aria_engine/session_isolation.py`)

Every agent operates inside its own `AgentSessionScope`. The scope binds a `session_id` to a specific `agent_id` and carries the agent's `EngineConfig`. The `SessionIsolationFactory` manages a registry of scopes so the engine can retrieve any agent's context by ID and guarantee no cross-agent message bleed.

```
SessionIsolationFactory
  └── AgentSessionScope(agent_id, session_id, config, db)
        ├── add_message(role, content)
        └── get_messages() → List[dict]
```

### Session Protection (`aria_engine/session_protection.py`)

All inbound messages are validated and rate-limited before being written to the DB.

| Check | Mechanism |
|---|---|
| Content length | 1–100 KB enforced |
| Role validation | Must be in `{user, assistant, system, tool, function}` |
| Control-char strip | CONTROL_CHAR_RE removes `\x00`–`\x1f` except `\n`, `\t`, `\r` |
| Injection detection | 20+ `INJECTION_PATTERNS` regex heuristics (log-only, no block) |
| Sliding-window rate limit | Per-session **and** per-agent; limits persist across restarts in `aria_engine.rate_limit_windows` via SQLAlchemy |
| Session size cap | 500 messages max per session |
| Advisory locking | `asyncio.Lock` per session_id prevents concurrent writes |

Injection detection is **log-only** (never blocks). The canonical ML-level gate is `InputGuardSkill` (L0 skill layer).

### Auto Session Management (`aria_engine/auto_session.py`)

Handles automatic title generation and session rotation:

- `generate_auto_title(content)` — derives a ≤100-char title from the first line of the message.
- `_needs_rotation(session)` — returns True when session is ended, over the message-count limit, or older than the idle timeout.
- `close_idle_sessions()` — background sweep that ends stale sessions.

### Swarm Consensus (`aria_engine/swarm.py`)

When a single agent isn't enough, `SwarmOrchestrator` runs a multi-agent consensus loop:

```
SwarmOrchestrator.execute(prompt, agents=["aria-analyst", "aria-creator", ...])
  │
  ├── Phase: EXPLORE  → each agent proposes independently
  ├── Phase: CONVERGE → agents see each other's votes and iterate
  ├── Phase: FINALIZE → Orchestrator synthesizes the consensus trail
  │
  └── SwarmResult
        ├── consensus (final answer string)
        ├── votes: List[SwarmVote]  (agree / disagree / extend / pivot)
        └── trail (pheromone-ordered reasoning chain)
```

Votes are parsed from structured `[VOTE: …] [CONFIDENCE: …]` tags. If tags are absent, a word-count heuristic infers agreement. Consensus is weighted by confidence and falls back to the highest-confidence single vote when no majority forms.

Requires 2–12 agents; raises `EngineError` outside that range.

---

## Memory Architecture

*Based on Aria's own analysis — February 15, 2026.*

```
┌─────────────────────────────────────────────────────────────┐
│                     WORKING MEMORY                          │
│  Short-term / Session Context                               │
│  Syncs to aria_memories/memory/context.json                 │
└────────────────────────┬────────────────────────────────────┘
                         │ sync_to_files()
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    LONG-TERM MEMORY                         │
│  PostgreSQL / aria_warehouse                                │
│  goals, activities, thoughts, memories                      │
│  api_client primary interface                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   KNOWLEDGE GRAPH                           │
│  PostgreSQL — entities, relationships                       │
│  add_entity(), add_relation(), query()                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  FILE ARTIFACTS                             │
│  aria_memories/ — logs, research, plans, drafts, exports    │
│  MemoryManager.ALLOWED_CATEGORIES enforced                  │
└─────────────────────────────────────────────────────────────┘
```

### Persistence Layers

| Layer | Scope | Storage | Survives Restart? |
|-------|-------|---------|-------------------|
| **Ephemeral** | Seconds | Current thought, tool context | No |
| **Session** | Minutes-hours | Working memory, active goals | Via checkpoint |
| **Durable** | Days-years | PostgreSQL, file artifacts, knowledge graph | Yes |
| **Eternal** | Forever | Soul values, identity, boundaries | Yes (read-only) |

### Database Isolation

| Database | Schema | Purpose |
|----------|--------|---------|
| `aria_warehouse` | `aria_data` | Knowledge, memories, goals, activities, social, logs, performance — all domain data (26 tables) |
| `aria_warehouse` | `aria_engine` | Chat sessions, messages, cron jobs, agent state, config, LLM models, agent tools, circuit-breaker state, rate-limit windows — engine infrastructure (15 tables) |
| `litellm` | `public` | LiteLLM Prisma tables (isolated to prevent migration conflicts) |

All 41 ORM models have explicit schema annotations in `src/api/db/models.py`. No tables in `public` schema.

New tables added March 2026: `aria_engine.circuit_breaker_state` (R-01) and `aria_engine.rate_limit_windows` (R-02) — both created by `ensure_schema()` on startup and populated via SQLAlchemy ORM; no Alembic dependency.

Implementation details: `aria_mind/memory.py`, `aria_skills/working_memory/`, `aria_skills/knowledge_graph/`

---

## Infrastructure

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Docker Stack (stacks/brain)                    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐                  │
│  │  Traefik   │    │Aria Engine │    │  LiteLLM   │                  │
│  │  (Proxy)   │    │ (Gateway)  │    │  (Router)  │                  │
│  └─────┬──────┘    └─────┬──────┘    └─────┬──────┘                  │
│        │                 │                 │                          │
│        ▼                 ▼                 ▼                          │
│  ┌────────────┐    ┌────────────┐    ┌────────────────────────────┐  │
│  │  aria-web  │    │ aria_mind/ │    │  MLX Server (host)         │  │
│  │  Flask     │    │ Workspace  │    │  Metal GPU (Apple Silicon) │  │
│  └─────┬──────┘    └────────────┘    └────────────────────────────┘  │
│        │                                                              │
│        ▼                                                              │
│  ┌────────────┐    ┌────────────┐                                    │
│  │  aria-api  │───▶│  aria-db   │                                    │
│  │  FastAPI   │    │ PostgreSQL │                                    │
│  └────────────┘    └────────────┘                                    │
│                                                                      │
│  + aria-brain, prometheus, grafana, pgadmin,                         │
│    tor-proxy, aria-browser, aria-sandbox, certs-init                  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

Full service list and ports: see [DEPLOYMENT.md](DEPLOYMENT.md)

---

## Related

- [DEPLOYMENT.md](DEPLOYMENT.md) — How to deploy and operate
- [SKILLS.md](SKILLS.md) — Skill system and layer details
- [MODELS.md](MODELS.md) — Model routing and tiers
- [API.md](API.md) — REST API, GraphQL, and dashboard
- [STRUCTURE.md](STRUCTURE.md) — Repository layout
- [CHANGELOG.md](CHANGELOG.md) — Version history
