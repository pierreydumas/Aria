# Changelog

All notable changes to Aria Blue will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — aria_v3_270226 Sprint (2026-02-27)

**Theme:** Session/artifact integrity guardrails, self-healing resilience, infrastructure hardening, memory accessibility.

### Added
- **S-45 (E20):** Self-Healing Phase 2–5 — `api_client` retry migration (112 endpoint methods now use `_request_with_retry`), `LLMSkill` with `LLM_FALLBACK_CHAIN` and per-model circuit breakers, `HealthDegradationLevel` enum with degradation detection + job suspension logic, chaos tests (`tests/test_self_healing.py`) covering backoff, circuit breaker, LLM fallback, and activity resilience.
- **S-44 (E20):** `aria_memories/HEARTBEAT.md` — read-accessible operational guide for cron jobs; `cron_jobs.yaml` and `DEPLOYMENT.md` updated to prefer artifact path.
- **S-40 (E19):** `api_client.read_artifact_by_path()` helper for nested path resolution; `MEMORY.md` docs updated; regression tests added.
- **S-41 (E19):** `schedule.create_job()` now accepts `type` kwarg as alias for `action` — backward compatible.

### Fixed
- **S-39 (E19):** JSON artifacts validated before write (HTTP 400 on invalid JSON); `get_session_stats()` uses canonical `/sessions/stats` endpoint; work_cycle log enforces strict JSON schema; goal ordering fixed to `priority DESC`.
- **S-42 (E19):** `create_heartbeat` accepts `details` as `dict | str | list | None` — normalizes to `dict` before DB insert; eliminates 422 errors.
- **S-47 (P0):** LiteLLM schema isolation — removed `,public` from `search_path` in 4 locations; `ensure_schema()` creates `litellm` schema; eliminates cross-schema Prisma table leakage.
- **S-48 (P0):** LiteLLM port hardcoded as `:18793` in `index.html` and `services.html` — now uses `{{ litellm_port }}` from Flask context; `docker-compose.yml` injects `LITELLM_PORT` env var.
- **S-49 (P0):** `make up` now auto-bootstraps `stacks/brain/.env` via `check-env` prerequisite; `first-run.sh --auto` flag skips interactive prompts on fresh clone.
- **S-50 (E20):** Upgraded `aria-browser` from frozen `browserless/chrome:latest` (2-year-old SHA) to `ghcr.io/browserless/chromium:v2.42.0`; removed deprecated env vars.
- **S-51 (P0):** pgvector Python package added to `pyproject.toml`; pg16→pg17 + pgvector 0.8.0→0.8.2 upgrade; HNSW indexes for `semantic_memories` and `session_messages`; Alembic migration `s52_pg17_pgvector_hnsw_upgrade.py`.
- **S-03 (Audit / Breaking):** `session_manager` skill — removed file-based helper functions (`_flatten_sessions`, `_is_cron_or_subagent_session`, `_epoch_ms_to_iso`) during DB migration; `tests/skills/test_session_manager.py` fully rewritten with 16 DB-backed tests using `AsyncMock` on the API client (tests were previously broken and could not be collected by pytest).

### Changed
- **S-43 (E20):** Identity manifest `identity_aria_v1.md` updated to v1.1 with sprint learnings (pre-existing at sprint start).

---

## [3.0.0] — 2026-02-21 (Multi-Agent v3 — Roundtable, Swarm & Artifacts)

**Theme:** Multi-agent orchestration, file-based memory artifacts, per-agent mind configuration, production hardening.  
**Philosophy:** "Aria as a CEO: delegates, discusses, synthesizes, remembers."

### Added — New Capabilities

#### Multi-Agent Roundtable & Swarm
- **Roundtable discussions**: structured multi-agent debates with rounds + AI synthesis
- **Swarm decisions**: iterative convergence protocol with consensus scoring
- REST API endpoints: `POST /engine/roundtable`, `POST /engine/roundtable/async`, `POST /engine/swarm`
- WebSocket streaming for real-time roundtable progress
- Session persistence in `aria_engine.chat_sessions` with proper UUID session IDs
- Slash commands `/roundtable` and `/swarm` in chat interface

#### Artifact File API
- New `artifacts.py` router: full CRUD for file artifacts in `aria_memories/`
- Endpoints: `POST /artifacts` (write), `GET /artifacts/{category}/{filename}` (read), `GET /artifacts` (list), `DELETE /artifacts/{category}/{filename}` (delete)
- Path traversal protection, category whitelist (20 categories)
- `api_client` skill extended with `write_artifact`, `read_artifact`, `list_artifacts`, `delete_artifact` tools
- Writable bind-mount on aria-api container for `aria_memories/`

#### Per-Agent Mind Files
- `mind_files` field on `AgentConfig` — each agent loads only relevant `aria_mind/*.md` files
- Default file sets per role: orchestrator gets all 8 files, sub-agents get 3-5
- Persisted in `agent_state.metadata_json` via `agents_sync.py`
- `prompts.py` dynamically assembles system prompts from agent's `mind_files` list

### Fixed
- **UUID session IDs**: Roundtable and Swarm now use proper UUIDs (was `roundtable-{hex}` / `swarm-{hex}`)
- **Agent Pool initialization**: `load_agents()` now called at startup with LLM gateway injection
- **Agent enablement**: All agents enabled on fresh deploy (was defaulting to disabled)

### Changed
- `aria_memories` volume mount changed from `:ro` to writable for artifact API
- `api_client` skill: added to `aria`, `memory`, and `aria_talk` agent skill lists
- Version bumped to 3.0.0 across pyproject.toml, deployment docs, and health endpoints
- Python badge updated to 3.13+ (was 3.10+)
- Documentation references updated from "local-first Apple Silicon" to multi-model routing

---

> **Version jump note:** v1.3.0 → v3.0.0 was intentional. The multi-agent architecture
> (roundtable, swarm, artifact API, agent pheromone scoring) was a ground-up redesign
> that warranted a major version bump. There is no v2.x release.

## [1.3.0] — 2026-02-20 (Schema Architecture & Swiss-Clock Audit)

**Theme:** Zero raw SQL, dual-schema ORM, comprehensive endpoint audit, 100% test coverage.  
**Philosophy:** "Every chain from DB to API to UI verified — Swiss-clock precision."

### Added — New Capabilities

#### Dual-Schema Architecture
- **ONE database** (`aria_warehouse`), **TWO schemas**: `aria_data` (26 domain tables), `aria_engine` (11 infrastructure tables)
- All 37 ORM models annotated with explicit `__table_args__ = {"schema": ...}`
- All 10 ForeignKey strings updated with schema-qualified prefixes
- `session.py` bootstraps both schemas on startup (`CREATE SCHEMA IF NOT EXISTS`)
- Migration SQL script: `scripts/migrate_schemas.sql`

#### Zero Raw SQL
- Converted all 46 raw SQL statements to SQLAlchemy ORM across 9 engine files
- Files converted: `session_manager.py` (17→0), `scheduler.py` (8→0), `cross_session.py` (7→0), `heartbeat.py` (4→0), `agent_pool.py` (3→0), `routing.py` (3→0), `auto_session.py` (2→0), `chat_engine.py` (1→0), `session_protection.py` (1→0)
- Only `SELECT 1` health probes and LiteLLM Prisma queries remain (acceptable)

#### Agent & Model CRUD System (v1.2 routers)
- `agents_crud.py` — Full agent lifecycle: create, read, update, disable, enable, delete, sync-from-MD
- `models_crud.py` — Full model lifecycle: create, read, update, delete, sync-from-YAML, `/models/available`
- Engine proxy routers: `engine_chat.py`, `engine_cron.py`, `engine_agents.py`, `engine_sessions.py`

#### 62 New Tests (462 total, 0 failures)
- `test_agents_crud.py` — 14 tests: full CRUD lifecycle + filters + sync
- `test_models_crud.py` — 13 tests: full CRUD + filters + sync + models/available
- `test_engine_chat.py` — 2 new tests: GET messages + 404 nonexistent session
- `test_engine_internals.py` — 33 unit tests: routing scoring (16), auto_session titles (6), session_protection (11)

#### Aria's Soul & Identity
- `PromptAssembler` wired into `create_session()` — assembles SOUL.md + IDENTITY.md + TOOLS.md
- Aria's personality, boundaries, and values loaded into every engine session

### Fixed — Bug Fixes

- **`session.py` health check** — queried `public` schema but tables are in `aria_data`/`aria_engine` → always "degraded". Fixed to query both named schemas.
- **`catalog.py` stub skills** — 6 manifest-only skills (brainstorm, community, database, experiment, fact_check, model_switcher) shown as "active". Fixed to check for `__init__.py` and mark as "planned".
- **`scheduler.py` duration_ms crash** — `get_job_history()` accessed nonexistent `ActivityLog.duration_ms` column → extract from JSONB `details` dict.
- **`scheduler.py` APScheduler serialization** — `add_job()` and `update_job()` passed bound method `self._execute_job` which APScheduler 4.x can't serialize → use `_scheduler_dispatch` module-level trampoline.

### Changed — Documentation Updates

- **ARCHITECTURE.md** — Database Isolation section: 3-schema layout with table counts
- **API.md** — Added 6 new endpoint rows + updated ORM section (37 models, two schemas)
- **STRUCTURE.md** — Added `aria_engine/` directory (26 files), updated routers (17→28), tests (462), models (37), DB schema notes
- **CHANGELOG.md** — This entry
- **MODELS.md** — Schema annotations per model documented

### Identified — Technical Debt

- 3 orphan models defined but unused: `AgentPerformance`, `EngineConfigEntry`, `EngineAgentTool`
- 4 engine modules built but not wired into production: `routing.py`, `auto_session.py`, `session_protection.py`, `cross_session.py`
- 6 skills are manifest-only stubs (planned, not implemented)

---

## [1.2.0] — 2026-02-XX (Cognitive Upgrade — "Make Her Better")

**Theme:** Deep cognitive improvements to make Aria more autonomous, self-aware, and capable.  
**Philosophy:** "She's not just a processor — she's a growing, learning entity."

### Added — New Capabilities

#### Metacognitive Self-Improvement Engine (`aria_mind/metacognition.py`)
- **NEW MODULE** — Aria now tracks her own growth over time
- Task success/failure pattern recognition by category
- Learning velocity measurement (is she getting faster? more accurate?)
- Failure pattern detection with adaptive strategy suggestions
- Strength identification (what is she best at?)
- Growth milestones with 13 achievement types (First Success → Grandmaster)
- Natural language self-assessment generation
- Persistent state survival across restarts via JSON checkpointing

#### LLM-Powered Genuine Reflection (`aria_mind/cognition.py`)
- `reflect()` now routes through LLM for genuine self-reflection
- Creates real internal journal entries, not just string concatenation
- Falls back to structured reflection when LLM is unavailable
- Includes metacognitive summary in reflection context

#### Intelligent Goal Decomposition (`aria_mind/cognition.py`)
- `plan()` now uses LLM + explore/work/validate cycle
- Skill-aware planning (considers available tools)
- Agent-aware planning (considers available agents)
- Falls back to intelligent heuristic when LLM unavailable
- New `assess_task_complexity()` for metacognitive task evaluation

#### Memory Consolidation Engine (`aria_mind/memory.py`)
- `consolidate()` — transforms short-term memories into long-term knowledge
- LLM-powered summarization of memory categories
- Pattern recognition across memory entries
- Automatic file artifact creation for human visibility
- `flag_important()` — mark critical memories for review
- `checkpoint_short_term()` / `restore_short_term()` — survive restarts
- `get_patterns()` — analyze cognitive patterns for self-awareness

#### Self-Healing Heartbeat (`aria_mind/heartbeat.py`)
- **Subsystem self-healing** — auto-reconnects failed memory, soul, cognition
- **5-minute goal work cycle** — match GOALS.md specification
- **30-minute reflection triggers** — automatic periodic self-reflection
- **60-minute consolidation triggers** — automatic memory consolidation
- Emergency self-heal after 5 consecutive failures
- Detailed subsystem health tracking

#### Pheromone Performance Tracking (`aria_agents/scoring.py`)
- **NEW CLASS: `PerformanceTracker`** — records agent performance over time
- Speed, success rate, and cost normalized scoring
- Session survival via JSON persistence to aria_memories/knowledge/
- Agent leaderboard with detailed stats per agent
- Module-level singleton `get_performance_tracker()`
- Auto-save every 10 invocations

### Changed — Enhanced Existing Systems

#### Agent Coordinator (`aria_agents/coordinator.py`)
- `process()` now uses pheromone-based agent selection
- Every agent call is timed and recorded for performance tracking
- Auto-detects roundtable needs and synthesizes multi-agent perspectives
- `get_status()` includes performance leaderboard

#### Cognition Processing (`aria_mind/cognition.py`)
- **Retry logic** — up to 2 retries with different approaches before fallback
- **Confidence tracking** — grows with successes, decays with failures
- **Metacognitive context injection** — Aria knows how she's performing
- **Performance metrics** — latency tracking, success rate, streak counting
- Enhanced `get_status()` with full metacognitive metrics

#### Agent Context Management (`aria_agents/base.py`)
- **Sliding window** — context auto-trims at 50 messages (was unbounded)
- Preserves system messages at context start
- New `get_context_summary()` for context status reporting
- Tracks total messages processed per agent

#### Pipeline Engine (`aria_skills/pipeline_executor.py`)
- **Parallel DAG execution** — independent branches run concurrently
- Wave-based scheduling: steps with satisfied deps run in parallel
- Falls back to sequential for single ready steps (no async overhead)
- Proper error handling for parallel failures

#### Memory Manager (`aria_mind/memory.py`)
- Short-term capacity increased from 100 → 200 entries
- `remember_short()` now tracks category frequency for pattern analysis
- Enhanced `get_status()` with consolidation data and top categories

#### AriaMind Core (`aria_mind/__init__.py`)
- Version bumped to 1.1.0
- New `introspect()` — full self-awareness report
- `think()` now records outcomes in metacognitive engine
- `initialize()` restores memory checkpoints and metacognitive state
- `shutdown()` persists all state (metacognition + memory checkpoint)
- Task classification for metacognitive tracking
- Enhanced `__repr__` with task count and milestone count

### Files Modified (9 existing + 1 new)
- `aria_mind/__init__.py` — Enhanced AriaMind class
- `aria_mind/cognition.py` — LLM reflection, intelligent planning, retry logic
- `aria_mind/memory.py` — Consolidation engine, pattern recognition
- `aria_mind/heartbeat.py` — Self-healing, autonomous action scheduling
- `aria_mind/metacognition.py` — **NEW** — Self-improvement engine
- `aria_agents/coordinator.py` — Performance-aware routing
- `aria_agents/scoring.py` — PerformanceTracker with persistence
- `aria_agents/base.py` — Sliding window context management
- `aria_skills/pipeline_executor.py` — Parallel DAG execution

---

## [1.1.0] — 2026-02-10 (Aria Blue v1.1 Sprint)

**Branch:** `vscode_dev` — 37 tickets across 7 waves  
**Architecture rule enforced:** `DB ↔ SQLAlchemy ↔ API ↔ Skill ↔ ARIA`

### Wave 1 — Foundation (TICKET-01, 02, 06, 07, 08)

#### Added
- Architecture enforcement layer: all data access now follows DB ↔ SQLAlchemy ↔ API ↔ Skill ↔ ARIA
- SQLAlchemy 2.0 ORM consolidation with dedicated `src/api/db/` module (models.py, session.py, MODELS.md)
- Alembic migration framework (`src/api/alembic/`)
- Dependency injection module (`src/api/deps.py`)

#### Fixed
- 7 critical bugs resolved (TICKET-06): runtime errors, data integrity, and startup issues
- `session_manager` skill crash on missing sessions (TICKET-07)
- Memory deque bug causing data loss on overflow (TICKET-08)

### Wave 2 — Skill Layer (TICKET-03, 10, 11, 12, 14)

#### Added
- `@logged_method` decorator for automatic activity logging across all skills (TICKET-11)
- 5-tier skill layering enforced: Kernel → API → Core Skills → Domain Skills → Agents (TICKET-03)

#### Changed
- Skill naming unified to `aria-{name}` convention across all 32 skills (TICKET-14)
- Eliminated all in-memory stubs — every skill now persists via api_client → API → SQLAlchemy (TICKET-12)
- Cleaned up all stale model references (`ollama/*`, hardcoded model names) (TICKET-10)

### Wave 3 — Operations (TICKET-09, 13, 16, 17, 20)

#### Added
- Structured logging & observability stack with `logging_config.py` (TICKET-17)
- `run_skill` service catalog with auto-discovery of all registered skills (TICKET-13)

#### Fixed
- All 11 pre-existing test failures resolved (TICKET-09)
- Cron jobs fixed, verified, and documented in `cron_jobs.yaml` (TICKET-16)

#### Changed
- Model naming decoupled from provider specifics — models referenced by alias only (TICKET-20)

### Wave 4 — Features (TICKET-05, 15, 21, 22, 23)

#### Added
- `agent_manager` skill (232 lines) for agent lifecycle management (TICKET-21)
- `telegram` skill (173 lines) for Telegram messaging via API (TICKET-22)
- Agent swarm refactor: permanent agents with coordinator delegation pattern (TICKET-05)

#### Changed
- Moltbook decoupled to Layer 2 social skill — no longer tightly coupled to database layer (TICKET-15)
- System prompt overhauled for clarity, accuracy, and tool references (TICKET-23)

### Wave 5 — Polish & Research (TICKET-04, 18, 19, 24, 25, 26, 27, 28)

#### Added
- `kernel/` layer: read-only constitutional core with YAML configs (TICKET-04)
  - `constitution.yaml`, `identity.yaml`, `values.yaml`, `safety_constraints.yaml`
- `sandbox` skill (138 lines) with Docker sandbox for safe code execution (TICKET-18)
- `stacks/sandbox/` Docker container (Dockerfile, server.py, entrypoint) (TICKET-18)
- MLX local model optimization with `tests/load/benchmark_models.py` (TICKET-19)
- Log analysis tooling: `scripts/analyze_logs.py` (TICKET-28)
- Gateway phase-out analysis document (TICKET-24)

#### Fixed
- WebSocket disconnect issue resolved (TICKET-25)

#### Changed
- Integrated insights from Google RLM paper (TICKET-26) and Anthropic skills guide (TICKET-27)

### Wave 6 — Cognitive Architecture (TICKET-34, 35, 36)

#### Added
- `working_memory` skill (228 lines): persistent session-surviving working memory (TICKET-35)
- `working_memory` API router (`src/api/routers/working_memory.py`) (TICKET-35)
- `pipeline_skill` (138 lines): cognitive pipeline execution engine (TICKET-34)
- `pipeline.py` + `pipeline_executor.py`: pipeline orchestration framework (TICKET-34)
- Pipeline YAML definitions in `aria_skills/pipelines/` (TICKET-34):
  - `daily_research.yaml`, `health_and_report.yaml`, `social_engagement.yaml`
- Self-diagnostic & auto-recovery system in `health/` skill (TICKET-36):
  - `diagnostics.py` — self-diagnostic engine
  - `patterns.py` — failure pattern recognition
  - `playbooks.py` — recovery playbooks
  - `recovery.py` — auto-recovery logic

### Wave 7 — Release & Quality (TICKET-29, 30, 31, 32, 33, 37)

#### Added
- `CHANGELOG.md` — this file (TICKET-29)
- Database migration script `02-migrations.sql` for v1.1 schema changes
- 400+ tests, 0 failures — full test suite review (TICKET-31)
- Environment configuration centralization analysis (TICKET-37)

#### Changed
- All documentation consolidated and updated to reflect v1.1 state (TICKET-29):
  - `STRUCTURE.md` — regenerated from actual directory tree
  - `README.md` — updated architecture, skills, models, test counts
  - `TOOLS.md` — skill list synchronized with aria_skills/ registry
  - `SKILLS.md` — all 32 skills listed with working/stub status
  - `AUDIT_REPORT.md` — sprint remediation status added
- Model configuration consolidated: `aria_models/models.yaml` is the single source of truth for 14+ models (TICKET-30)
- Production integration verified with data migration (TICKET-32)
- Website endpoint live testing validated across all 22 pages (TICKET-33)

---

## [1.0.0] — 2026-02-05 (Initial Release)

### Added
- Full autonomous AI agent platform with native Python engine
- 26 skill modules with BaseSkill framework (retry, metrics, Prometheus)
- FastAPI v3.0 API with 16 REST routers + Strawberry GraphQL
- Flask dashboard with 22 pages and Chart.js visualizations
- Docker Compose stack with 12 services
- PostgreSQL 16 with dual database isolation (aria_warehouse + litellm)
- LiteLLM model routing with 12 models (1 local, 9 free, 2 paid)
- MLX local inference on Apple Silicon (Metal GPU, ~25-35 tok/s)
- Multi-agent orchestration with CEO delegation pattern
- Goal-driven 5-minute autonomous work cycles
- 7 focus personas with automatic switching and delegation hints
- Roundtable multi-domain discussions via asyncio.gather
- Persistent memory and knowledge graph
- Prometheus + Grafana monitoring stack
- Traefik v3.1 reverse proxy with automatic HTTPS
- Tor proxy for anonymous research capability
- Browserless Chrome for headless web scraping
- Security middleware: rate limiting, injection scanning, security headers
- Source Available License
