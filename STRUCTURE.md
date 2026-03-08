# Aria Blue ⚡️ — Project Structure

> Verified against filesystem: 2026-02-24

---

## Complete Directory Layout

```
Aria_moltbot/
├── README.md                     # Project overview & quick start
├── ARCHITECTURE.md               # System design, layer diagram
├── DEPLOYMENT.md                 # Deployment & operations guide
├── SKILLS.md                     # Skill system overview & layer hierarchy
├── MODELS.md                     # Model routing strategy & tiers
├── API.md                        # REST API, GraphQL, dashboard overview
├── STRUCTURE.md                  # This file

├── CHANGELOG.md                  # Version history
├── ROLLBACK.md                   # Rollback procedures
├── LICENSE                       # Source Available License
├── pyproject.toml                # Python project configuration
├── Makefile                      # Development shortcuts
├── Dockerfile                    # Agent container build
├── Dockerfile.test               # Test container build
│
├── aria_mind/                    # Engine workspace (mounted to gateway)
│   ├── SOUL.md                   # Persona, boundaries, model preferences
│   ├── SOUL_EVIL.md              # Evil mode soul document
│   ├── IDENTITY.md               # Agent identity configuration
│   ├── AGENTS.md                 # Sub-agent definitions
│   ├── ARIA.md                   # Aria self-description
│   ├── AWAKENING.md              # Awakening narrative
│   ├── TOOLS.md                  # Skill registry & execution guide
│   ├── HEARTBEAT.md              # Scheduled task configuration (30m cycles)
│   ├── GOALS.md                  # Goal-driven work system (5-min cycles)
│   ├── ORCHESTRATION.md          # Sub-agent & infrastructure awareness
│   ├── MEMORY.md                 # Long-term curated knowledge
│   ├── SECURITY.md               # Security policies & guidelines
│   ├── SKILLS.md                 # Skill documentation
│   ├── USER.md                   # User profile
│   ├── RPG.md                    # RPG campaign documentation
│   ├── __init__.py
│   ├── cli.py                    # Command-line interface
│   ├── cognition.py              # Cognitive functions
│   ├── heartbeat.py              # Heartbeat implementation
│   ├── logging_config.py         # Structured logging configuration
│   ├── memory.py                 # Memory management
│   ├── metacognition.py          # Metacognitive functions
│   ├── security.py               # Security implementation
│   ├── startup.py                # Startup routines
│   ├── skill_health_dashboard.py # Skill health dashboard
│   ├── cron_jobs.yaml            # Cron schedule definitions
│   ├── pyproject.toml            # Mind package config
│   ├── aria-profile-v1.png       # Profile image
│   ├── kernel/                   # Kernel layer — read-only core (v1.1)
│   │   ├── __init__.py
│   │   ├── constitution.yaml     # Core constitution
│   │   ├── identity.yaml         # Identity definition
│   │   ├── safety_constraints.yaml # Safety constraints
│   │   └── values.yaml           # Core values
│   ├── soul/                     # Soul implementation
│   │   ├── __init__.py
│   │   ├── identity.py           # Identity module
│   │   ├── values.py             # Core values
│   │   ├── boundaries.py         # Operational boundaries
│   │   └── focus.py              # Focus management
│   ├── skills/                   # Runtime skill mounts (populated at deploy)
│   │   ├── __init__.py
│   │   ├── run_skill.py          # Skill runner script
│   │   ├── _cli_tools.py         # CLI tool helpers
│   │   ├── _coherence.py         # Coherence checks
│   │   ├── _kernel_router.py     # Kernel routing
│   │   ├── _skill_introspection.py # Skill introspection
│   │   ├── _skill_registry.py    # Skill registry
│   │   ├── _tracking.py          # Tracking utilities
│   │   └── aria_memories/        # Memory mount
│   ├── config/                   # Configuration files
│   ├── aria_analytics/           # Analytics data
│   ├── aria_memories/            # Memory mount
│   └── articles/                 # Article content
│
├── aria_skills/                  # Skill modules (41 skills)
│   ├── __init__.py               # Package exports
│   ├── base.py                   # BaseSkill, SkillConfig, SkillResult
│   ├── catalog.py                # Skill catalog generator (--list-skills CLI)
│   ├── registry.py               # SkillRegistry with auto-discovery
│   ├── pipeline.py               # Pipeline definition engine
│   ├── pipeline_executor.py      # Pipeline execution runtime
│   ├── SKILL_STANDARD.md         # Skill development standard
│   ├── SKILL_CREATION_GUIDE.md   # Guide for creating new skills
│   ├── AUDIT.md                  # Skill audit report
│   ├── _template/                # Skill template for scaffolding new skills
│   ├── agent_manager/            # Agent lifecycle management
│   ├── api_client/               # Centralized HTTP client for aria-api
│   ├── brainstorm/               # Brainstorming & ideation
│   ├── ci_cd/                    # CI/CD pipeline automation
│   ├── community/                # Community engagement
│   ├── conversation_summary/     # Conversation summarization
│   ├── data_pipeline/            # ETL & data pipeline operations
│   ├── experiment/               # Experimentation framework
│   ├── fact_check/               # Fact checking & verification
│   ├── goals/                    # Goal & habit tracking
│   ├── health/                   # System health & self-diagnostic
│   ├── hourly_goals/             # Micro-task tracking
│   ├── input_guard/              # Runtime security (injection detection)
│   ├── knowledge_graph/          # Entity-relationship graph
│   ├── litellm/                  # LiteLLM proxy management
│   ├── market_data/              # Cryptocurrency market data
│   ├── memeothy/                 # Meme generation & content
│   ├── memory_compression/       # Memory compression & optimization
│   ├── model_switcher/           # Dynamic model switching
│   ├── moltbook/                 # Moltbook social platform
│   ├── moonshot/                 # Moonshot SDK (legacy fallback)
│   ├── ollama/                   # Ollama direct access (legacy fallback)
│   ├── pattern_recognition/      # Pattern detection & analysis
│   ├── performance/              # Performance reviews
│   ├── pipeline_skill/           # Cognitive pipeline execution
│   ├── pipelines/                # Pipeline YAML definitions
│   │   ├── daily_research.yaml
│   │   ├── health_and_report.yaml
│   │   └── social_engagement.yaml
│   ├── portfolio/                # Portfolio management
│   ├── pytest_runner/            # Pytest execution
│   ├── research/                 # Information gathering
│   ├── rpg_campaign/             # RPG campaign management
│   ├── rpg_pathfinder/           # RPG pathfinder system
│   ├── sandbox/                  # Docker sandbox execution
│   ├── schedule/                 # Scheduled jobs
│   ├── security_scan/            # Vulnerability detection
│   ├── sentiment_analysis/       # Sentiment analysis
│   ├── session_manager/          # Session lifecycle management
│   ├── social/                   # Cross-platform social presence
│   ├── sprint_manager/           # Sprint & project management
│   ├── telegram/                 # Telegram messaging skill
│   ├── unified_search/           # Unified search across sources
│   └── working_memory/           # Persistent working memory
│
├── aria_agents/                  # Multi-agent orchestration
│   ├── __init__.py
│   ├── base.py                   # BaseAgent, AgentConfig, AgentMessage
│   ├── context.py                # Agent context management
│   ├── loader.py                 # AGENTS.md parser
│   ├── scoring.py                # Pheromone scoring & agent evaluation
│   └── coordinator.py            # Agent lifecycle, routing & solve() method
│
├── aria_models/                  # Model configuration
│   ├── __init__.py
│   ├── loader.py                 # Model loader
│   ├── models.yaml               # Model catalog (single source of truth)
│   └── README.md                 # Model documentation
│
├── aria_memories/                # Persistent memory storage (22 subdirectories)
│   ├── README.md
│   ├── surface/                  # Surface-level memory (ephemeral, recent)
│   ├── medium/                   # Medium-term memory (days–weeks)
│   ├── deep/                     # Deep memory (long-term, curated)
│   ├── archive/                  # Archived data and old outputs
│   ├── bugs/                     # Bug reports & tracking
│   ├── deliveries/               # Delivery records
│   ├── drafts/                   # Draft content
│   ├── exports/                  # Exported data
│   ├── income_ops/               # Operational income data
│   ├── knowledge/                # Knowledge base files
│   ├── logs/                     # Activity & heartbeat logs
│   ├── memory/                   # Core memory files (context.json, skills.json)
│   ├── moltbook/                 # Moltbook drafts and content
│   ├── plans/                    # Planning documents
│   │   └── sprint/               # Sprint tickets & tracking
│   ├── research/                 # Research archives
│   ├── rpg/                      # RPG campaign data & sessions
│   ├── sandbox/                  # Sandbox execution artifacts
│   ├── semantic_graph/           # Semantic graph exports
│   ├── skills/                   # Skill state and persistence data
│   ├── specs/                    # Specification documents
│   ├── tickets/                  # Ticket tracking
│   └── work/                     # Working documents
│
├── aria_souvenirs/               # Souvenir artifacts
│
├── stacks/
│   ├── brain/                    # Docker deployment
│   │   ├── docker-compose.yml    # Full stack orchestration
│   │   ├── .env                  # Environment configuration (DO NOT COMMIT)
│   │   ├── .env.example          # Template for .env
│   │   ├── aria-entrypoint.sh    # Aria Engine startup with Python + skills
│   │   ├── aria-config.json      # Aria Engine provider template
│   │   ├── aria-auth-profiles.json # Auth profile configs
│   │   ├── litellm-config.yaml   # LLM model routing
│   │   ├── prometheus.yml        # Prometheus scrape config
│   │   ├── traefik-dynamic.yaml  # Traefik dynamic routing config
│   │   ├── traefik-entrypoint.sh # Traefik startup script
│   │   ├── certs/                # TLS certificates
│   │   ├── init-scripts/         # PostgreSQL initialization
│   │   │   ├── 00-create-litellm-db.sh  # Creates separate litellm database
│   │   │   ├── 01-schema.sql            # Core tables + seed data
│   │   │   └── 02-migrations.sql        # Schema migrations
│   │   └── grafana/              # Grafana provisioning
│   │       └── provisioning/
│   │           ├── dashboards/
│   │           │   └── json/     # Dashboard JSON definitions
│   │           └── datasources/
│   │               └── datasources.yml
│   └── sandbox/                  # Docker sandbox for code execution
│       ├── Dockerfile
│       ├── entrypoint.py
│       ├── entrypoint.sh
│       ├── server.py
│       └── README.md
│
├── aria_engine/                  # Async chat engine (25 modules)
│   ├── __init__.py
│   ├── __main__.py               # Engine CLI entrypoint
│   ├── agent_pool.py             # Agent pool management
│   ├── auto_session.py           # Auto-session title generation
│   ├── chat_engine.py            # Core chat loop & LLM streaming
│   ├── config.py                 # Engine configuration
│   ├── context_manager.py        # Context window management
│   ├── entrypoint.py             # HTTP server (FastAPI)
│   ├── exceptions.py             # Engine exceptions
│   ├── export.py                 # Session export
│   ├── heartbeat.py              # Heartbeat scheduler
│   ├── llm_gateway.py            # LLM provider gateway
│   ├── metrics.py                # Prometheus metrics
│   ├── prompts.py                # PromptAssembler (soul/identity/tools)
│   ├── roundtable.py             # Multi-agent roundtable (structured rounds + synthesizer)
│   ├── routing.py                # Agent routing & scoring
│   ├── scheduler.py              # APScheduler 4.x cron system
│   ├── session_isolation.py      # Session isolation
│   ├── session_manager.py        # Session CRUD (ORM)
│   ├── session_protection.py     # Rate limiting & input sanitization
│   ├── streaming.py              # SSE streaming
│   ├── swarm.py                  # Swarm orchestrator — pheromone-weighted voting, stigmergy, iterative convergence
│   ├── telemetry.py              # Telemetry — fire-and-forget LLM usage & skill invocation logging to aria_data
│   ├── thinking.py               # Thinking/reasoning extraction
│   └── tool_registry.py          # Tool registry — translates aria_skills into LiteLLM function-calling definitions
│
├── src/                          # Application source
│   ├── api/                      # FastAPI backend
│   │   ├── main.py               # App factory, middleware, routers
│   │   ├── config.py             # Environment config + service endpoints
│   │   ├── deps.py               # Dependency injection
│   │   ├── schema.py             # Pydantic schemas
│   │   ├── security_middleware.py # Rate limiter, injection scanner, headers
│   │   ├── requirements.txt
│   │   ├── alembic/              # Database migrations
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   ├── db/                   # SQLAlchemy 2.0 ORM layer
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # 39 ORM models (aria_data + aria_engine schemas)
│   │   │   ├── session.py        # Async engine + sessionmaker + schema bootstrap
│   │   │   └── MODELS.md         # Model documentation
│   │   ├── gql/                  # Strawberry GraphQL
│   │   │   ├── __init__.py
│   │   │   ├── schema.py         # GraphQL schema
│   │   │   ├── types.py          # GraphQL type definitions
│   │   │   └── resolvers.py      # Query resolvers
│   │   └── routers/              # 32 REST router files
│   │       ├── activities.py     # Activity log CRUD + stats (7 endpoints)
│   │       ├── admin.py          # Admin operations (12 endpoints)
│   │       ├── agents_crud.py    # Agent CRUD lifecycle (10 endpoints)
│   │       ├── analysis.py       # Pattern analysis + compression (6 endpoints)
│   │       ├── artifacts.py      # File artifact CRUD in aria_memories (4 endpoints)
│   │       ├── engine_agents.py  # Engine agent proxy (3 endpoints)
│   │       ├── engine_agent_metrics.py # Agent performance metrics (3 endpoints)
│   │       ├── engine_chat.py    # Engine chat proxy + WS (7+1 endpoints)
│   │       ├── engine_cron.py    # Cron/scheduler proxy (8 endpoints)
│   │       ├── engine_roundtable.py # Multi-agent roundtable + swarm (12+1 endpoints)
│   │       ├── engine_sessions.py# Engine session proxy (10 endpoints)
│   │       ├── goals.py          # Goal tracking + progress (13 endpoints)
│   │       ├── health.py         # Liveness, readiness, service status (6 endpoints)
│   │       ├── knowledge.py      # Knowledge graph entities (14 endpoints)
│   │       ├── lessons.py        # Lessons learned (6 endpoints)
│   │       ├── litellm.py        # LiteLLM proxy stats + spend (4 endpoints)
│   │       ├── memories.py       # Long-term memory storage (11 endpoints)
│   │       ├── models_config.py  # Dynamic model config from models.yaml (4 endpoints)
│   │       ├── models_crud.py    # Model DB CRUD lifecycle (6 endpoints)
│   │       ├── model_usage.py    # LLM usage metrics + cost tracking (4 endpoints)
│   │       ├── operations.py     # Operational metrics (19 endpoints)
│   │       ├── proposals.py      # Feature proposals (5 endpoints)
│   │       ├── providers.py      # Model provider management (1 endpoint)
│   │       ├── records.py        # General record management (3 endpoints)
│   │       ├── rpg.py            # RPG campaign dashboard (4 endpoints)
│   │       ├── security.py       # Security audit log + threats (4 endpoints)
│   │       ├── sentiment.py      # Sentiment analysis + NLP (11 endpoints)
│   │       ├── sessions.py       # Session management + analytics (6 endpoints)
│   │       ├── skills.py         # Skill registry endpoints (11 endpoints)
│   │       ├── social.py         # Social posts + community (7 endpoints)
│   │       ├── thoughts.py       # Thought stream + analysis (4 endpoints)
│   │       └── working_memory.py # Working memory API (10 endpoints)
│   ├── database/                 # Database utilities
│   │   └── models.py
│   └── web/                      # Flask dashboard (43 pages)
│       ├── app.py                # Flask app + routes
│       ├── static/               # CSS, JS, favicon
│       │   ├── css/              # Component styles (base, layout, variables)
│       │   ├── js/
│       │   │   └── pricing.js    # Shared pricing helpers
│       │   └── favicon.svg
│       └── templates/            # 43 Jinja2 templates + Chart.js
│           ├── base.html
│           ├── index.html
│           ├── activities.html
│           ├── agent_manager.html
│           ├── api_key_rotations.html
│           ├── creative_pulse.html
│           ├── engine_agents.html
│           ├── engine_agents_mgmt.html
│           ├── engine_agent_dashboard.html
│           ├── engine_chat.html
│           ├── engine_cron.html
│           ├── engine_health.html
│           ├── engine_operations.html
│           ├── engine_prompt_editor.html
│           ├── engine_roundtable.html
│           ├── engine_swarm_recap.html
│           ├── heartbeat.html
│           ├── knowledge.html
│           ├── memories.html
│           ├── memory_explorer.html
│           ├── models.html
│           ├── models_manager.html
│           ├── model_usage.html
│           ├── operations.html
│           ├── patterns.html
│           ├── performance.html
│           ├── proposals.html
│           ├── records.html
│           ├── rpg.html
│           ├── search.html
│           ├── security.html
│           ├── sentiment.html
│           ├── services.html
│           ├── sessions.html
│           ├── skills.html
│           ├── skill_graph.html
│           ├── skill_health.html
│           ├── skill_stats.html
│           ├── social.html
│           ├── soul.html
│           ├── sprint_board.html
│           ├── thoughts.html
│           └── working_memory.html
│
├── scripts/                      # Utility scripts
│   ├── analyze_logs.py           # Log analysis tool
│   ├── apply_patch.sh            # Patch application
│   ├── aria_backup.sh            # Backup script
│   ├── benchmark_models.py       # Model benchmarking
│   ├── check_architecture.py     # Architecture validation
│   ├── deploy_production.sh      # Production deployment
│   ├── first-run.sh              # Quick-start setup script
│   ├── generate_endpoint_matrix.py # Endpoint matrix generation
│   ├── generate_litellm_config.py # LiteLLM config generator
│   ├── guardrail_web_api_path.py # Web/API path guardrail check
│   ├── health_check.sh           # System health check
│   ├── health_watchdog.sh        # Health watchdog daemon
│   ├── install_hooks.sh          # Git hooks installer
│   ├── pre-commit-hook.sh        # Pre-commit hook
│   ├── retrieve_logs.sh          # Log retrieval
│   ├── rpg_chat.py               # RPG chat interface
│   ├── rpg_roundtable.py         # RPG roundtable runner
│   ├── rpg_session.py            # RPG session management
│   ├── run-load-test.sh          # Load test runner
│   ├── runtime_smoke_check.py    # Runtime smoke check
│   ├── talk_to_aria.py           # Interactive Aria CLI
│   └── verify_deployment.sh      # Deployment verification
│
├── prompts/                      # Prompt templates
│   ├── agent-workflow.md
│   └── ARIA_COMPLETE_REFERENCE.md
│
├── docs/                         # Documentation
│   ├── ANALYSIS_SYSTEM.md
│   ├── API_ENDPOINT_INVENTORY.md
│   ├── RPG_SYSTEM.md
│   ├── RUNBOOK.md
│   ├── TEST_COVERAGE_AUDIT.md
│   ├── article_llm_self_awareness_experiment.md
│   ├── benchmarks.json
│   ├── benchmarks.md
│   └── archive/
│       └── AUDIT_REPORT.md
│
├── deploy/                       # Deployment utilities
│   ├── grafana/
│   └── mac/                      # macOS-specific deployment
│
├── images/                       # Image assets
│
├── articles/                     # Published articles
│   ├── article_llm_self_awareness_experiment.md
│   ├── article_shadows_of_absalom.html
│   └── linkedin_article_llm_self_awareness.md
│
├── tasks/                        # Task documentation
│   └── lessons.md
│
└── tests/                        # Pytest test suite (79 test files, 948 test functions)
    ├── __init__.py
    ├── conftest.py               # Fixtures, DB health gate, API client
    ├── test_activities.py        # Activity CRUD tests
    ├── test_admin.py             # Admin endpoint tests
    ├── test_advanced_memory.py   # Advanced memory tests
    ├── test_agents_crud.py       # Agent CRUD lifecycle tests
    ├── test_analysis.py          # Analysis endpoint tests
    ├── test_architecture.py      # Architecture validation tests
    ├── test_artifacts_router.py  # Artifact router tests
    ├── test_cross_entity.py      # Cross-entity integration tests
    ├── test_docker_health.py     # Docker health check tests
    ├── test_engine_agents.py     # Engine agent proxy tests
    ├── test_engine_chat.py       # Engine chat + messages tests
    ├── test_engine_cron.py       # Engine cron/scheduler tests
    ├── test_engine_internals.py  # Engine pure-function unit tests
    ├── test_engine_roundtable_router.py # Roundtable router tests
    ├── test_engine_sessions.py   # Engine session proxy tests
    ├── test_goals.py             # Goal tracking tests
    ├── test_graphql.py           # GraphQL schema tests
    ├── test_health.py            # Health endpoint tests
    ├── test_knowledge.py         # Knowledge graph tests
    ├── test_lessons.py           # Lessons learned tests
    ├── test_litellm.py           # LiteLLM proxy tests
    ├── test_memories.py          # Memory CRUD tests
    ├── test_models_config.py     # Model config tests
    ├── test_models_crud.py       # Model DB CRUD lifecycle tests
    ├── test_model_usage.py       # Model usage metric tests
    ├── test_noise_filters.py     # Noise filter tests
    ├── test_operations.py        # Operations endpoint tests
    ├── test_proposals.py         # Proposal endpoint tests
    ├── test_providers.py         # Provider endpoint tests
    ├── test_records.py           # Record endpoint tests
    ├── test_rpg_router.py        # RPG router tests
    ├── test_security.py          # Security tests
    ├── test_security_middleware.py # Security middleware tests
    ├── test_sessions.py          # Session management tests
    ├── test_skills.py            # Skill unit tests
    ├── test_smoke.py             # Smoke tests
    ├── test_social.py            # Social platform tests
    ├── test_thoughts.py          # Thought stream tests
    ├── test_validation.py        # Input validation tests
    ├── test_websocket.py         # WebSocket tests
    ├── test_web_routes.py        # Flask web route tests
    ├── test_working_memory.py    # Working memory tests
    ├── test_workflows.py         # Workflow end-to-end tests
    ├── e2e/                      # End-to-end test suite
    ├── integration/              # Integration test suite
    ├── load/                     # Load/performance tests
    ├── skills/                   # Skill-specific tests (36 files)
    └── unit/                     # Unit test suite
```

---

## Key Files

### aria_mind/ (Engine Workspace)

| File | Purpose | Loaded |
|------|---------|--------|
| `SOUL.md` | Persona, boundaries, tone | Every session |
| `IDENTITY.md` | Agent identity configuration | Every session |
| `AGENTS.md` | Sub-agent definitions | Every session |
| `TOOLS.md` | Available skills & limits | Every session |
| `HEARTBEAT.md` | Periodic task checklist | Every heartbeat (30m) |
| `GOALS.md` | Goal-driven work cycles | Every session |
| `MEMORY.md` | Long-term knowledge | Main session only |
| `USER.md` | User profile | Every session |
| `SECURITY.md` | Security policies | Every session |
| `ORCHESTRATION.md` | Infrastructure awareness | Every session |

### stacks/brain/ (Docker Deployment)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Orchestrates all services |
| `aria-entrypoint.sh` | Generates Aria Engine config at startup |
| `aria-config.json` | Template for LiteLLM provider |
| `litellm-config.yaml` | Routes model aliases to MLX/OpenRouter |
| `init-scripts/` | PostgreSQL database initialization |
| `prometheus.yml` | Prometheus scrape targets |

### Database Initialization

```
init-scripts/
├── 00-create-litellm-db.sh     # Creates separate 'litellm' database
├── 01-schema.sql               # Creates Aria's tables in 'aria_warehouse'
└── 02-migrations.sql           # Schema migrations
```

> **Schema layout:** One database `aria_warehouse` with two schemas — `aria_data` (26 domain tables) and `aria_engine` (13 infrastructure tables). LiteLLM uses a separate `litellm` database with its own Prisma-managed schema. All 39 ORM models have explicit `__table_args__ = {"schema": ...}` annotations.

---

## Skill Architecture

### Skill Module Structure

Each skill directory follows the same pattern:

```
aria_skills/<skill>/
├── __init__.py      # Skill class extending BaseSkill
├── skill.json       # Skill manifest (name, description, emoji)
└── SKILL.md         # Documentation (optional)
```

### BaseSkill Framework (base.py)

| Component | Description |
|-----------|-------------|
| `SkillStatus` (Enum) | `AVAILABLE`, `UNAVAILABLE`, `RATE_LIMITED`, `ERROR` |
| `SkillConfig` (dataclass) | `name`, `enabled`, `config` dict, optional `rate_limit` |
| `SkillResult` (dataclass) | `success`, `data`, `error`, `timestamp`; factories `.ok()` / `.fail()` |
| `BaseSkill` (ABC) | Abstract base with metrics, retry, Prometheus integration |

### Registry (registry.py)

- `@SkillRegistry.register` decorator for auto-discovery
- `load_from_config(path)` parses `TOOLS.md` for YAML config blocks
- Lookup via `get(name)`, `list_available()`, `check_all_health()`

### Execution Flow

```
Aria Engine Agent (exec tool)
       │
       ▼
python3 aria_mind/skills/run_skill.py <skill> <function> '<args_json>'
       │
       ▼
SkillRegistry → imports aria_skills.<skill>
       │
       ▼
BaseSkill.safe_execute() → retry + metrics + result
       │
       ▼
JSON output → returned to Aria Engine
```

---

## Service Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Docker Stack (stacks/brain)                    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐                  │
│  │  Traefik   │    │Aria Engine │    │  LiteLLM   │                  │
│  │  :80/:443  │    │  :8100     │    │  :18793    │                  │
│  └─────┬──────┘    └─────┬──────┘    └─────┬──────┘                  │
│        │                 │                 │                          │
│        ▼                 ▼                 ▼                          │
│  ┌────────────┐    ┌────────────┐    ┌──────────────────┐            │
│  │  aria-web  │    │ aria_mind/ │    │  MLX Server      │            │
│  │  Flask UI  │    │ Workspace  │    │  (host:8080)     │            │
│  │  :5000     │    │ + Skills   │    │  Metal GPU       │            │
│  └─────┬──────┘    └────────────┘    └──────────────────┘            │
│        │                                                              │
│        ▼                                                              │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐                  │
│  │  aria-api  │───▶│  aria-db   │    │  grafana   │                  │
│  │  FastAPI   │    │ PostgreSQL │    │  :3001     │                  │
│  │  :8000     │    │  :5432     │    └────────────┘                  │
│  └────────────┘    └────────────┘                                    │
│                                                                      │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐                  │
│  │ Prometheus │    │  PGAdmin   │    │ aria-brain │                  │
│  │  :9090     │    │  :5050     │    │  (Agent)   │                  │
│  └────────────┘    └────────────┘    └────────────┘                  │
│                                                                      │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐                  │
│  │ tor-proxy  │    │  browser   │    │ certs-init │                  │
│  │  :9050     │    │  :3000     │    │  (oneshot) │                  │
│  └────────────┘    └────────────┘    └────────────┘                  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Deployment

### From Windows (PowerShell)

```powershell
cd C:\git\Aria_moltbot\stacks\brain
docker compose up -d
```

### From macOS / Linux

```bash
cd Aria_moltbot/stacks/brain
docker compose up -d
```

### Service URLs

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | `https://{HOST}/` | Main web UI |
| API Docs | `https://{HOST}/api/docs` | Swagger documentation |
| Aria Engine | `http://{HOST}:8100` | Engine API |
| LiteLLM | `http://{HOST}:18793` | Model router |
| Grafana | `https://{HOST}/grafana` | Monitoring dashboards |
| PGAdmin | `https://{HOST}/pgadmin` | Database admin |
| Prometheus | `https://{HOST}/prometheus` | Metrics |
| Traefik | `https://{HOST}/traefik/dashboard` | Proxy dashboard |

---

## Counts Summary

| Category | Count |
|----------|-------|
| Skill modules | 41 |
| Engine modules | 25 |
| REST router files | 32 |
| REST endpoints | 235 |
| WebSocket endpoints | 2 |
| GraphQL endpoint | 1 |
| Dashboard pages | 43 |
| Test files | 79 |
| Test functions | 948 |

---

## Engine Module Reference (aria_engine/)

The `aria_engine` package is the async runtime that powers Aria's LLM interactions, agent coordination, and scheduled tasks. Below are the key modules grouped by function.

### Core Chat & LLM

| Module | Description |
|--------|-------------|
| `chat_engine.py` | Core chat loop — streams LLM responses, handles tool calls, manages conversation turns |
| `llm_gateway.py` | LLM provider gateway — routes requests through LiteLLM with retry and fallback |
| `prompts.py` | PromptAssembler — builds system prompts from soul, identity, tools, and mind files |
| `streaming.py` | Server-Sent Events (SSE) streaming for real-time chat output |
| `thinking.py` | Extracts and formats `<think>` reasoning blocks from LLM responses |
| `context_manager.py` | Context window management — tracks token budgets and truncates history |

### Multi-Agent Orchestration

| Module | Description |
|--------|-------------|
| `agent_pool.py` | Agent pool — loads agent definitions, manages lifecycle and capability routing |
| `roundtable.py` | Multi-agent roundtable — structured discussion rounds with a central synthesizer |
| `swarm.py` | Swarm orchestrator — pheromone-weighted voting, stigmergy trails, iterative convergence until consensus threshold is met |
| `routing.py` | Agent routing — scores agents against task requirements for best-fit selection |

### Session & Scheduling

| Module | Description |
|--------|-------------|
| `session_manager.py` | Session CRUD — creates, retrieves, and persists chat sessions via ORM |
| `session_isolation.py` | Session isolation — ensures agents operate in separate contexts |
| `session_protection.py` | Rate limiting and input sanitization for session endpoints |
| `auto_session.py` | Auto-generates session titles from conversation content |
| `scheduler.py` | APScheduler 4.x cron system — manages recurring jobs (heartbeat, goals) |
| `heartbeat.py` | Heartbeat scheduler — triggers periodic agent turns every 30 minutes |

### Observability & Infrastructure

| Module | Description |
|--------|-------------|
| `telemetry.py` | Fire-and-forget telemetry — logs LLM usage (`model_usage`) and skill invocations (`skill_invocations`) to `aria_data` schema for observability dashboards |
| `metrics.py` | Prometheus metrics — exposes counters, histograms for scraping |
| `tool_registry.py` | Tool registry — auto-discovers `skill.json` manifests, converts Python function signatures to JSON Schema, executes skill methods with timeout enforcement |
| `config.py` | Engine configuration — loads env vars and defaults |
| `entrypoint.py` | HTTP server (FastAPI) — `/health`, `/metrics`, WebSocket endpoints |
| `exceptions.py` | Engine-specific exception hierarchy (`EngineError`, `ToolError`, etc.) |
| `export.py` | Session export — serializes sessions to shareable formats |

---

## Dashboard Templates (44 files)

All templates are in `src/web/templates/`. Flask renders them via Jinja2 with Chart.js for visualizations.

| Template | Description |
|----------|-------------|
| `base.html` | Base layout template — shared header, navigation, footer, CSS/JS includes |
| `index.html` | Homepage — system stats, status cards, quick links, service indicators |
| `activities.html` | Activity log — filtering, search, CRUD operations |
| `activity_visualization.html` | Activity pattern visualizations (Chart.js time series) |
| `agent_manager.html` | Legacy agent manager interface |
| `api_key_rotations.html` | API key rotation tracking and management |
| `creative_pulse.html` | Creative content feed and draft management |
| `engine_agents.html` | Engine agent status monitoring and health |
| `engine_agents_mgmt.html` | Engine agent management — enable/disable, configure, sync |
| `engine_agent_dashboard.html` | Per-agent performance dashboard with metrics |
| `engine_chat.html` | Real-time chat interface with Aria Engine (WebSocket) |
| `engine_cron.html` | Cron job scheduler — view, create, trigger, manage jobs |
| `engine_health.html` | Engine health and subsystem status dashboard |
| `engine_operations.html` | Engine operational metrics and diagnostics |
| `engine_prompt_editor.html` | System prompt editor for agent mind files |
| `engine_roundtable.html` | Multi-agent roundtable and swarm discussion interface |
| `heartbeat.html` | Heartbeat monitoring and health timeline |
| `knowledge.html` | Knowledge graph browser with vis-network visualization |
| `memories.html` | Long-term memory browser, editor, and search |
| `models.html` | Model catalog and routing configuration viewer |
| `models_manager.html` | Model CRUD management — add, edit, delete, sync |
| `model_usage.html` | LLM usage metrics and cost tracking (Chart.js) |
| `operations.html` | Operational metrics dashboard — uptime, throughput, errors |
| `patterns.html` | Behavioral pattern detection results and heatmaps |
| `performance.html` | Performance review dashboard with trend analysis |
| `proposals.html` | Self-improvement proposals tracker and review |
| `rate_limits.html` | Rate limiting status and configuration viewer |
| `records.html` | General record browser with filtering |
| `rpg.html` | RPG campaign dashboard with KG visualization (vis-network) |
| `search.html` | Unified search interface across all data sources |
| `security.html` | Security audit log, threat scanner, and event viewer |
| `sentiment.html` | Sentiment analysis dashboard — timeline, VAD breakdown (Chart.js) |
| `services.html` | Docker service status and health for all containers |
| `sessions.html` | Chat session browser, analytics, and message viewer |
| `skills.html` | Skill registry browser — status, layer, health |
| `skill_graph.html` | Skill dependency graph visualization (vis-network) |
| `skill_health.html` | Skill health status dashboard with diagnostics |
| `skill_stats.html` | Skill usage statistics and invocation metrics |
| `social.html` | Social platform (Moltbook) feed, posting, and scheduling |
| `soul.html` | Aria's soul, values, identity, and boundaries viewer |
| `sprint_board.html` | Sprint/Kanban board for goal management (drag-and-drop) |
| `thoughts.html` | Thought stream browser and analysis |
| `wallets.html` | Cost tracking, wallet balances, and spend breakdown |
| `working_memory.html` | Working memory inspector — keys, values, TTL, sync |

---

*Aria Blue ⚡️ — Project Structure — verified 2026-02-24*
