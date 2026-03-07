# Lessons

## General
- Do not use SSH or remote commands unless explicitly requested; prefer local scripts that the user can run on the server.
- Avoid writing secrets or tokens into repo files; prompt for them at runtime or keep them unset by default.
- When refactoring skills, verify file content after edits to avoid duplicated blocks and syntax errors; re-read the file before running tests.

## Sprint Planning (v1.2 — 2026-02-10, historical)
- **Read EVERYTHING before acting.** Full codebase read (200+ files) via parallel subagents is the fastest way. Never plan from summary alone.
- **Parallel subagents work well** for codebase ingestion. 6 subagents reading different directories simultaneously gives full context in minutes.
- **Filename consistency matters.** When a master index references ticket filenames, verify the actual filenames on disk match. Found 5 mismatches in first pass.
- **Dependencies between tickets must be explicit.** If S-17 reads fields that S-16 creates, that's a dependency — write it on the ticket header. Found 8 undocumented dependencies in first cross-review.
- **Watch for ticket overlaps.** S-10/S-11 (both touching DB credentials) and S-13/S-15 (both touching six_hour_review) had overlapping scope. Add cross-reference notes defining ownership boundaries.
- **Epic priority ≠ ticket priority.** An E2 (P0) epic can contain P2 tickets. Note this in sprint overview to avoid confusion during execution.
- **Verification sections are mandatory.** 20/35 tickets were created without explicit verification steps. Every ticket needs testable commands.
- **PO/Scrum prompt lives in prompts/.** Reusable sprint prompt template at `prompts/PO_SCRUM_SPRINT.md` — copy-paste to start any sprint session.

## Architecture
- **5-layer rule:** DB → SQLAlchemy ORM → FastAPI API → api_client (httpx) → Skills → ARIA. No exceptions.
- **9 skills bypass api_client** as of v1.1 — must be migrated (S-08).
- **models.yaml is single source of truth.** Found 3 places with hardcoded model names (S-09).
- **aria_memories/ is the ONLY writable path** for Aria. Code directories are read-only.
- **Container mounts matter.** Verify docker-compose volumes mount aria_memories as rw before assuming file writes work.

## Bugs & Patterns
- **import os missing** in input_guard — always check imports after refactoring.
- **SkillConfig.settings is a dict**, not an object with attributes. Use `config.settings.get()` not `config.settings.attr`.
- **Cron 6-field vs 5-field format** caused massive over-firing. Always validate cron expressions.
- **Empty registries from constructors:** `PipelineExecutor(SkillRegistry())` creates a fresh empty registry instead of using the shared one. Pass the existing registry instance.

## Sprint v1.2 Execution (2026, historical)
- **Swarm execution works.** 44 tickets across 9 epics completed autonomously via parallel subagent dispatch. Tickets grouped into dependency waves avoid blocking.
- **Deprecated code removal (S-18) must happen before init cleanup (S-19).** Removing imports of deleted skills first prevents ImportError cascades.
- **Duplicate index=True + standalone Index() is common.** S-36 found 3 instances. Always check before adding standalone indexes whether inline `index=True` exists.
- **Raw SQL→ORM migration requires reading actual code first.** Ticket diffs may reference stale line numbers. Always read-then-edit.
- **Frontend tickets are independent once routes exist.** S-39/S-40/S-41 ran in parallel with zero conflicts because they touch separate templates and routes.
- **ForeignKey constraints need orphan cleanup first.** S-42 migration DELETEs orphan rows before adding FK to avoid constraint violations on existing data.
- **GIN indexes require pg_trgm extension.** Must `CREATE EXTENSION IF NOT EXISTS pg_trgm` before creating trigram indexes (S-44).
- **Brain→API communication via shared DB table.** SkillStatusRecord pattern (S-40) — brain writes, API reads — is the correct cross-container data sharing approach.
- **AA+ ticket format with Constraints table is essential.** Tickets without explicit constraint evaluation led to architecture violations in v1.1. The full template (Problem, Root Cause, Fix, Constraints, Dependencies, Verification, Prompt) is now the standard.
- **Gateway abstraction (S-31) enables future LLM provider swaps.** GatewayInterface ABC + AriaGateway isolates vendor-specific logic.

## Sprint 1 Execution (2026-02-11)
- **Token counting formula: prefer `total_tokens || (prompt + completion)`.** Never add all three — `total_tokens` already equals `prompt + completion`. Copy-paste bugs made this 3× inflated in two locations.
- **API response shape changes need frontend + backend in same commit.** Changing from bare array to `{logs, total, offset, limit}` broke frontends until both sides deployed together.
- **Shared JS extraction (`aria-common.js`) eliminates template drift.** Balance/spend logic was duplicated across models.html and wallets.html with subtle differences. Centralizing into `fetchBalances()` / `fetchSpendSummary()` ensures consistency.
- **Deduplicate fetch with promise caching pattern.** Store the in-flight promise, return it for concurrent callers, expire after 30s. Reduced 3 `/litellm/spend` calls per page load to 1.
- **Dead code from API migrations lingers.** CNY_TO_USD constant survived months after Kimi switched to USD international API. Always grep for removed-feature references.
- **`tool_calling: false` must be explicit in models.yaml.** Without it, the coordinator assigns tool-needing tasks to models that 404 on tool calls. Chimera-free and trinity-free now marked.
- **DB garbage cleanup via SQL file, not inline shell quotes.** Complex SQL with single quotes inside double-quoted docker exec commands causes shell escaping chaos. Use `docker cp` + `psql -f` instead.
- **`console.log` in production templates leaks internal state.** Gate debug logs behind `window.ARIA_DEBUG` flag so developers can re-enable when needed.

## Sprint 3 Execution (2026-02-11)
- **Direct SQL ALTER TABLE for running containers beats Alembic rebuild.** When containers are up, adding columns via `docker compose exec aria-db psql -c "ALTER TABLE..."` is instant. Save Alembic for cold-start scenarios.
- **Board column mapping must be canonical.** Sprint board uses 5 fixed columns (backlog, todo, doing, on_hold, done). Status-to-column mapping lives in the move endpoint, not the frontend.
- **Token-efficient endpoints save 10x context.** `sprint-summary` returns ~460 bytes vs ~5000 for `get_goals(limit=100)`. Always provide compact alternatives for Aria's cognitive loop.
- **Vanilla drag-and-drop is sufficient for Kanban.** HTML5 `draggable="true"` + `ondragstart/ondrop` events work cleanly without libraries. The `PATCH /goals/{id}/move` endpoint handles column + position + status sync atomically.
- **GraphQL pagination should default to 25, not 100.** Large default limits waste tokens and DB resources. Adding `offset: int = 0` to all resolvers enables cursor-free pagination matching REST endpoints.

## Sprint 5 Execution (2026-02-11)
- **pgvector needs a dedicated Docker image.** `postgres:16-alpine` does not include pgvector. Use `pgvector/pgvector:pg16` instead. Init-scripts only run on first volume creation — use `patch/*.sql` + `docker cp`/`psql -f` for existing databases.
- **FastAPI route order matters for parameterized paths.** `/memories/{key}` intercepted `/memories/search` because it was registered first. Always place specific-path routes BEFORE parameterized `{key}` or `{id}` routes.
- **Integration tests must match actual API response shapes.** Don't guess — read the router to find exact payload format (`{key, value}` not `{content}`), response keys (`{created: true, id}` not the full object), and route prefixes (`/knowledge-graph/` not `/knowledge/`).
- **No `/api` prefix in runtime.** Despite `root_path="/api"`, internal container requests use bare paths (`/goals`, `/memories`). The `/api` prefix is only for reverse-proxy rewriting.
- **Embedding-dependent endpoints should accept 502 in tests.** When the embedding model isn't configured in LiteLLM, semantic endpoints return 502. Tests should `assert status in (200, 502)` rather than hard-failing.
- **DB user comes from `.env`, not convention.** Don't assume `postgres` or `admin` — always check `stacks/brain/.env` for actual credentials (`aria_admin`).

## Sprint Final Review (2026-02-12)
- **Host Python and container Python can diverge hard.** Validate in-container paths (`/app`) before treating host interpreter mismatches as code failures.
- **`configure_python_environment` may return a stale venv path if the venv is missing.** Confirm executable exists before running test commands.
- **Operational scripts need writable artifact targets.** Keep logs, state, backups, and alerts under `aria_memories/` to preserve write-boundary constraints.
- **Deployment verification should include both API and web probes.** Checking container status alone misses route regressions.

## Sprint S-47 — Sentiment Pipeline (2026-02-16)
- **Cognition fire-and-forget pattern is a trap.** Computing analysis in `process()` and injecting into `context` dict without persistence means insights are lost. Any analysis step should persist results via api_client in a non-blocking try/except.
- **Dual storage creates ghost data.** Skill wrote to `semantic_memories` (category=sentiment), dashboard read from `sentiment_events`. Always verify the full read/write path end-to-end before marking a feature done.
- **Hardcoded model names accumulate silently.** Kimi was hardcoded at sentiment skill line 202, burning paid API credits on every call. models.yaml profiles must cover every use case — add profiles proactively.
- **Alembic migrations for every new table.** Relying on `create_all()` is fragile in production with partial schemas. Always create an idempotent migration with `IF NOT EXISTS`.
- **api_client needs methods for every persistence path.** If a table exists in the DB, there must be a corresponding api_client method. The absence of `store_sentiment_event()` was the direct cause of the broken pipeline.
- **Legacy JSONL `content` is a list, not a string.** The legacy gateway stores message content as `[{"type":"text","text":"..."}]`. Any parser that does `isinstance(content, str)` silently drops ALL messages. Always handle both `str` and `list[dict]` formats.
- **Lexicon word lists need common conversational words.** "better", "clean", "easy", "works" were missing — causing 0% confidence on obviously positive messages. Expand lexicon proactively with everyday language, not just strong emotion words.
- **Silent exception swallowing hides critical failures.** `except: pass` in the LLM sentiment fallback meant we had no idea the model calls were failing. Always log at least a warning on fallback paths.
- **Backfill endpoints must write to the correct tables.** `backfill-sessions` wrote to `semantic_memories` only, while the dashboard reads from `sentiment_events`. Both tables need writes for the feature to work end-to-end.

## Sprint S-50→S-57 — Operation Integration (2026-02-19)
- **Routers exist ≠ Routers mounted.** `engine_chat`, `engine_agents`, `engine_agent_metrics` were fully implemented (800+ lines combined) but never added to `main.py`. Always verify new routers appear in the main app's include_router calls.
- **`configure_engine()` must be called in lifespan.** Dependency-injected routers that use module-level globals need explicit initialization during app startup. A mounted but unconfigured router returns 503 on every endpoint.
- **Alembic baseline migration is essential.** 29/36 tables had no migration — `ensure_schema()` at runtime is not enough for fresh installs or CI. Every ORM table needs a corresponding Alembic migration with IF NOT EXISTS for idempotency.
- **Disconnected Alembic heads break `upgrade head`.** s42 had `down_revision = None`, creating two heads. Always run `alembic heads` after adding migrations to verify single-head linear chain.
- **Cron YAML→DB sync must be automatic.** Manual `scripts/migrate_cron_jobs.py` is a deployment trap. Auto-sync on startup with upsert logic (insert new, update changed, preserve runtime state) eliminates deployment drift.
- **Heartbeat tables unused = dashboard shows nothing.** Two heartbeat systems existed but neither wrote to `heartbeat_log`. Always verify the full write→read→display pipeline end-to-end.
- **Swarm execution with dependency waves works.** 8 tickets executed in 4 waves (parallel within wave, sequential between waves). S-52/S-53 combined since both touched main.py. Total: ~10 min wall-clock for 34 points.
- **Subagent also resolved S-51 inside S-50.** When a subagent sees adjacent work (fixing s42 chain while creating baseline), let it do both — saves a round trip.
- **Skills layer was clean — audit confirmed it.** 0 SQLAlchemy violations, 33 skills registered. The architecture boundary between skills and DB held. 4 skills were unregistered due to missing __init__.py imports (not architecture violations, just wiring gaps).
## Epic E10  Prototype Integration Audit (2026-02-19)
- **Subagent file-existence audits can return false negatives.** Subagent reported `aria_skills/sentiment_analysis/` as missing  it existed with 962 lines. Always confirm with `read_file` or `grep_search` before creating a replacement file.
- **Real gaps are often operational, not architectural.** All 6 prototype skills were already implemented in production. The only true gap was that memory compression was never triggered (no cron job). Check the runtime path (cron/event/API call) before auditing the code.
- **"Stopped as over-engineered" in sprint notes does not mean not shipped.** The 2026-02-16 sprint note said `embedding_memory.py` and `pattern_recognition.py` were stopped  both ended up implemented anyway. Sprint decisions evolve; read the code, not only the docs.
- **Import-test pattern for skill verification.** `mcp_pylance_mcp_s_pylanceRunCodeSnippet` with a simple import plus print (no emoji, no unicode) is the fastest way to confirm all exports resolve correctly. Emoji in print strings cause codec errors in some terminals.
- **Compression needs a cron, not just an endpoint.** A skill that is never invoked is the same as a skill that does not exist. For any background-processing skill, creating the cron job is part of the implementation  the endpoint alone is not enough.
- **Docker compose is part of every code change.** New features touching env vars, volume mounts, container paths, or inter-service communication MUST update `docker-compose.yml`, `.env.example`, and `deploy_production.sh` in the same commit. Forgetting these causes "works locally, fails in Docker" bugs.
- **Container mount paths ≠ app paths.** `aria_mind/` is mounted at `/aria_mind` in the API container, NOT `/app/aria_mind`. Always verify volume mounts in compose before hardcoding paths in Python.
- **Env var naming collisions across containers.** `API_BASE_URL` meant `/api` (routing prefix) in `aria-api`/`aria-web` but `http://aria-api:8000` (full URL) in `aria-engine`. Use distinct env var names per purpose: `ENGINE_API_BASE_URL` for the engine's API client URL.
- **Alembic must be in requirements.txt for the container running migrations.** The deploy script runs `alembic upgrade head` in a container — if `alembic` isn't installed there, migration fails silently. Always check the target container's dependency list.
- **`depends_on` prevents race conditions.** `aria-engine` POSTs to `aria-api` for heartbeats but didn't depend on it. Add `condition: service_healthy` so the engine only starts after the API is ready.
- **Self-fetching endpoints simplify cron integration.** `POST /compression/auto-run` fetches its own data from the DB internally. Cron agents need zero payload knowledge  they just call the endpoint. This pattern (self-fetch + skip-if-not-needed guard) is reusable for any scheduled operation.
- **Prototype folder should be archived, not deleted.** `aria_mind/prototypes/` contains design rationale and trade-off notes. Move to `aria_souvenirs/` to preserve the research lineage.

## Test & CI Coverage (2026-02-20)
- **Route inventory must be automated.** Generate an endpoint-to-test audit from router decorators + test client calls and publish it in `docs/TEST_COVERAGE_AUDIT.md` to prevent blind spots.
- **Environment-dependent integrations should skip, not fail.** Endpoints guarded by missing keys/services (LLM, embeddings, admin token, external APIs) should assert expected statuses and `pytest.skip` when unavailable.
- **Security middleware can block realistic payloads.** For cron and similar endpoints, treat explicit security-filter responses as valid environment behavior and skip those paths in integration tests.
- **Vector endpoints require exact dimensions.** `search-by-vector` must use the model’s actual embedding size (768 here), otherwise tests induce avoidable 500s.
- **CI needs two lanes.** Keep a baseline lane for deterministic runs and an optional external-integration lane wired to secrets (`ARIA_TEST_API_URL`, etc.) so skipped paths can be exercised in managed environments.


## Session Hygiene & Model Routing (2026-02-22)
- **Ghost sessions are created on every page load.** /chat page visit without typing creates a DB row instantly. Prune TTL of 30 days is useless for seconds-old ghosts. Fix: defer session creation to first message; add a 15-min ghost purge background task.
- **`routing.primary` in models.yaml is a global override, not a preference.** Setting `primary: "litellm/kimi"` means 100% of traffic goes to kimi regardless of tier_order fallback chain. Only failures trigger the fallback. Change primary to a free model to restore diversity.
- **Archive endpoint is not physical archive.** `POST /archive` sets `status='archived'` (soft-delete). `EngineChatSessionArchive` only gets data from `prune_old_sessions`. Wire `archive_session` to the physical COPY+DELETE flow.
- **Cron sessions pollute chat UX.** Chat sidebar must use `?session_type=chat` to exclude cron/swarm sessions from conversation history.
- **agent_aliases in models.yaml are the source of display names.** Wire them into the chat model picker grouped by tier (local → free → paid).
- **Daily souvenir roundtables are effective PO/SM rituals.** 10 focused 5-min sessions produce actionable AA+ tickets faster than long planning ceremonies. Document in `aria_souvenirs/aria_vX_DDMMYY/roundtable/`.


## 2026-02-22 — v3 Production Audit Sprint (Roundtable with Aria as PO)

**Context:** SSH'd into production Mac Mini (192.168.1.53) and ran 10 live chat sessions
with Aria as PO. She responded with full acceptance criteria for each issue.

**Lessons:**

1. **Ghost sessions are created by page navigation, not just lazy creation.**
   Every /chat page load creates a DB row. Until lazy creation is implemented,
   the ghost purge loop (60-min TTL) is the mitigation.

2. **Aria's routing.primary = "litellm/kimi" in models.yaml is a global override.**
   It bypasses all tier_order logic. Other agents (analyst, devops, coder) won't fire
   until this override is removed or scoped by agent_type.

3. **"Archive" in the UI did not mean archive in the DB.**
   The POST /{id}/archive endpoint previously only set status='archived'.
   The physical copy to EngineChatSessionArchive was only done by prune_old_sessions.
   Fixed by routing the button through archive_session().

4. **TTL conflicts happen when the same concept is asked in different frames.**
   RT-01 (ghost-focused) said 1 hour. RT-05 (TTL list) said 15 minutes.
   Resolution: use the context-specific answer (RT-01 — ghost session discussion) 
   when the TTL was the primary topic.

5. **Cron sessions will always dominate session count if TTL == interactive TTL.**
   With 88/94 sessions being cron at 30-day retention, the DB is ~15x heavier than needed.
   Type-specific TTL (cron=7d, ghost=1h, interactive=30d) is the only sustainable path.

6. **SSH + Python scripts are more reliable than PowerShell one-liners for JSON payloads.**
   PS 5.1 lacks -SkipCertificateCheck. SCP the script then run via SSH.

7. **When Aria says "it's P0" in her own words, log it verbatim in the ticket.**
   The quote is the acceptance criterion — not a paraphrase.

8. **morning_checkin at 16:00 UTC = 4pm in most timezones — completely wrong.**
   Always verify cron times against user's actual timezone before deploying.
   Shiva wakes at ~06:00 UTC; moved to 0 0 6 * * *.

## 2026-02-22 — Knowledge Graph Relationship Bug Fix

**Context:** Aria could not create relationships in the KG. Every `add_relation` call
from the skill returned a 422 — silently caught and swallowed by the in-memory cache
fallback. Six bugs found, all hidden by the same silent-failure pattern.

**Root Cause:** `RelationCreate` Pydantic schema declared `from_entity`/`to_entity`
as `uuid.UUID`, but the LLM/skill layer sends entity **names** (strings).
Every call hit `422 Unprocessable Entity` — Pydantic rejected the input before
the endpoint code even ran.

**Bugs Fixed (6):**

1. **API schema type mismatch (CRITICAL).** `RelationCreate.from_entity`/`to_entity`
   changed from `uuid.UUID` to `str`. Added `_resolve_entity_id()` helper with
   4-step resolution: UUID parse → exact name match → case-insensitive match →
   auto-create entity. This makes the API accept names, UUIDs, or mixed references.

2. **Skill `query()` method signature mismatch.** Accepted `entity_type`/`relation`
   but `skill.json` manifest defines `entity_name`/`depth`. Every LLM call got TypeError.
   Fixed to match manifest and route to new `/kg-traverse` endpoint.

3. **Skill `get_entity()` method signature mismatch.** Accepted `entity_id` but
   manifest defines `query`/`type`. Fixed to match manifest.

4. **Fallback cache key names wrong.** Used `r["from"]`/`r["relation"]` but
   API returns `r["from_entity"]`/`r["relation_type"]`. KeyError on every
   cache read — the fallback itself was broken.

5. **`Dict` type annotation without import.** Used `Dict` (capitalized) which requires
   `from typing import Dict`. Changed to `dict` (Python 3.9+ builtin).

6. **No traversal on organic KG tables.** Existing `/traverse` endpoint only worked
   on the skill-graph tables (`skill_graph_entities`/`skill_graph_relations`).
   Added `/kg-traverse` (BFS) and `/kg-search` (ILIKE) for organic KG tables
   (`knowledge_entities`/`knowledge_relations`).

**Lessons:**

1. **Silent exception swallowing is the #1 production killer.**
   The skill caught ALL exceptions with `except Exception` and fell back to an
   in-memory cache. This masked the 422 for months. The cache itself had wrong
   key names (bug #4), so even the fallback was broken — doubly silent.
   **Rule: every except block must log at WARNING minimum.**

2. **Always test the full 5-layer call chain, not individual layers.**
   The API worked fine with UUIDs. The skill worked fine with names. But the
   *combination* (skill sends name → API expects UUID) was never tested.
   Integration tests must cross layer boundaries.

3. **Pydantic schema types are API contracts.**
   Changing a field from `uuid.UUID` to `str` completely changes what the API accepts.
   Schema types should match what the *actual callers* send, not what the DB stores.

4. **skill.json manifest is the source of truth for LLM tool calls.**
   The LLM only knows what's in the manifest. If the Python method signature
   doesn't match the manifest parameters, every call fails with TypeError.
   **Rule: run a diff between skill.json params and Python method args on every skill change.**

5. **Auto-create on reference is essential for LLM ergonomics.**
   The LLM naturally says "add relation from X to Y" even when X/Y don't exist yet.
   The resolver auto-creates missing entities as `concept` type rather than failing.
   This converts 100% of LLM relation requests into successful operations.

6. **Two parallel graph subsystems need two sets of endpoints.**
   The organic KG (`knowledge_*`) and skill graph (`skill_graph_*`) share structure
   but have different tables. Traverse/search built only for skill graph left the
   organic KG without query capabilities. Always mirror endpoints for both systems.

## 2026-02-24 — Chat Empty-Session Bug & LiteLLM Schema Consolidation

**Context:** Chat sessions were empty then pruned. Cron jobs worked fine.
Root cause: cascade failure in `ensure_schema()` + ghost session accumulation
from the scheduler + LiteLLM in a separate database.

**Bugs Fixed (4):**

1. **ensure_schema() cascade failure (CRITICAL).** All DDL ran in one transaction.
   First failure (e.g., missing pgvector extension → CREATE TABLE fails) poisoned
   the entire transaction with `InFailedSqlTransaction`. Result: ZERO application
   tables created. **Fix:** Added `_run_isolated(conn, label, sql)` helper using
   PostgreSQL SAVEPOINTs. Each DDL now isolated — one failure doesn't cascade.
   **Rule: never batch DDL in a single transaction. Use SAVEPOINTs.**

2. **Scheduler ghost sessions.** `_dispatch_to_agent()` creates a session per call.
   If the message POST fails, the empty session lingers with `message_count=0`.
   Each retry creates ANOTHER session. Ghost purge eventually deletes them but
   the accumulation pollutes the DB. **Fix:** Wrapped step 2 (message POST) in
   try/except that DELETEs the session on failure before re-raising.

3. **message_count never incremented via NativeSessionManager.** `add_message()`
   updated `updated_at` but not `message_count`. Sessions with real messages
   appeared as ghosts (count=0) and got purged. **Fix:** Added
   `message_count=EngineChatSession.message_count + 1` to the UPDATE.

4. **LiteLLM in separate database → consolidated to same DB with schema isolation.**
   LiteLLM had its own `litellm` database. Changed to `litellm` schema inside
   `aria_warehouse`. Init script creates schema + extensions. Docker compose
   passes `?options=-csearch_path%3Dlitellm,public` in LiteLLM's DATABASE_URL.
   API's `deps.py` sets `search_path` on each session. Survives multiple reboots.
   **Files changed:** `00-create-litellm-db.sh`, `docker-compose.yml`,
   `src/api/db/session.py`, `src/api/deps.py`.

**Verification:**
- `docker compose up -d --build` → 10/10 services healthy
- 3 schemas (aria_data: 26 tables, aria_engine: 13 tables, litellm: 49 tables)
- 4 extensions (uuid-ossp, pg_trgm, vector, plpgsql)
- Double restart → all data + schemas intact
- Session create → 201, ghost cleanup on LLM failure → working

**Lessons:**

1. **PostgreSQL SAVEPOINT is the correct isolation primitive for DDL.**
   A failed CREATE TABLE inside a transaction poisons ALL subsequent statements.
   SAVEPOINT + ROLLBACK TO SAVEPOINT isolates each DDL statement while keeping
   the outer transaction alive. This is idempotent and safe.

2. **Schema-based isolation > separate databases for co-located services.**
   Same PostgreSQL instance, same `aria_warehouse` DB, different schemas
   (aria_data, aria_engine, litellm). Benefits: single backup, single connection
   pool, cross-schema JOINs possible, simpler init scripts.

3. **`options=-csearch_path%3Dschema,public` in the URL is the PostgreSQL-native
   way to set schema per connection.** Works with Prisma, asyncpg, psycopg, and
   any driver that passes connection options. More reliable than ORM-level schema
   configuration.

4. **macOS port 5000 is reserved by ControlCenter.** Always remap containers using
   port 5000 to an alternative (5050) on macOS. Use `${ARIA_WEB_PORT:-5050}:5000`
   for configurability.

5. **Init scripts only run on first volume creation.** The PostgreSQL init-scripts
   directory (`/docker-entrypoint-initdb.d/`) executes only when the data volume
   is empty. For existing databases, use `ensure_schema()` or manual migration.

## 2026-02-24 — Full Project Audit (P0 Comprehensive Review)

**Context:** Zero'd the entire project — SSH'd to production, read 21 work cycles +
19 memory/work files, dispatched 4 parallel subagents to audit Docker, APIs, Skills, Docs.
Created aria_souvenirs/aria_v3_240226 with 8 reports + 17 sprint ticket files (55 tickets).

**Key Findings:**

1. **ZERO authentication on 226 API endpoints.** No middleware, no API keys, no JWT.
   Anyone on the network can read/write/delete any resource. This is the single biggest
   security hole in the entire project.

2. **Docker socket mounted into aria-sandbox.** `/var/run/docker.sock:/var/run/docker.sock`
   gives the sandbox container full Docker daemon control — escape to host in one command.
   Combined with root containers and no read-only filesystems, this is a container escape
   waiting to happen.

3. **11 skills access private `_client` on ApiClientSkill.** The underscore convention
   means internal-only, but skills bypass public methods and call `_client.get/post`
   directly. This defeats the abstraction layer and couples skills to raw HTTP.

4. **14 ghost files in STRUCTURE.md.** Files referenced in documentation that don't exist
   on disk. 50+ code modules have zero documentation. 10 contradictions between documents.

5. **28 of 40 active skills have zero tests.** Only health, api_client, and a few others
   have any test coverage. No integration tests cross layer boundaries.

**Lessons:**

1. **Production Aria is stable but under-monitored.** 21 work cycles, 0 crashes, 49 active
   sessions, $38.92 spend. But no alerting, no SLA metrics, no automated health dashboards.
   Stability ≠ observability.

2. **Parallel subagent audits are the fastest way to review a large project.**
   4 subagents (Docker, API, Skills, Docs) running in parallel covered 14 services,
   226 endpoints, 42 skills, and 27 docs in minutes. Each subagent had a focused scope
   and returned structured findings.

3. **AA+ ticket format scales to 55 tickets.** Constraints table + dependencies +
   verification commands + Claude-ready prompts work at scale. Grouped into 5 sprints
   (Security → Architecture → Docs → Testing → Operations) with explicit dependency chains.

4. **Cross-layer violations cluster around api_client.** The skill that exists to abstract
   HTTP calls (api_client) is itself the most-bypassed component. 25+ public methods
   need to be added before the 11 bypassing skills can be fixed.

5. **Sprint ticket files should be grouped by theme, not 1:1.** For 55 tickets,
   individual files per ticket creates too many files. Combine related tickets into
   themed files (e.g., S-107-108-109 for network exposure, S-150-159 for testing).
   Keep individual files only for complex standalone tickets.

## S-45 — Resilient Endpoint Pattern (2026-02-27)

**Lesson:** All specific endpoint methods in `api_client` must call `self._request_with_retry("METHOD", path, ...)` directly — never `self._client.METHOD()`.

**Pattern established:**
```python
# WRONG — bypasses retry + circuit breaker
resp = await self._client.get("/activities")
resp.raise_for_status()
return SkillResult.ok(resp.json())

# CORRECT — uses retry + circuit breaker
resp = await self._request_with_retry("GET", "/activities")
return SkillResult.ok(resp.json())  # raise_for_status() is internally called

# SPECIAL CASE — 404 as valid "not found" response
resp = await self._request_with_retry("GET", f"/memories/{key}")
return SkillResult.ok(resp.json())
# except:
#   if hasattr(e, "response") and e.response.status_code == 404:
#       return SkillResult.ok(None)
```

**LLM fallback chain pattern:**
- Create `LLMSkill` with `LLM_FALLBACK_CHAIN` list (model id, tier, priority).
- Per-model circuit breaker state in `_circuit_open_until[model]`.
- `complete_with_fallback()` iterates sorted by priority, skips open circuits.

**Health degradation pattern:**
- `HealthDegradationLevel` enum (HEALTHY / DEGRADED / CRITICAL / RECOVERY).
- Count failing subsystems → 0=HEALTHY, 1-2=DEGRADED, 3+=CRITICAL.
- `apply_degradation_mode()` returns suspension plan (never suspends heartbeat).

**Key constraint:** heartbeat and health_check are NEVER suspended at any degradation level.

## 2026-03-07 — Context Window Crash & Ghost Sessions Audit

**Context:** Production session crashed at 247,754 input tokens with Kimi
throwing `tool_call_id ":0" has no response message`.

**5 bugs found:**

1. **Partial tool-result orphan (P0 — crash cause).** `_build_context` in
   `streaming.py` lines 1376–1385: `if existing:` is truthy even when only 1
   of N tool results survive context window pruning. The assistant message is
   sent with ALL N tool_calls but only M results follow → Kimi throws `BadRequestError`.
   **Fix:** change to `if len(existing) == len(owned_ids):` and strip only the
   unmatched tool_calls when partial, instead of the all-or-nothing current logic.

2. **No token budget in `_build_context` (P0 — root enabling cause).** `streaming.py`
   limits context by MESSAGE COUNT only (`session.context_window or 50` messages).
   Verbose tool results (API responses, search dumps) can push 50 messages to 200K+
   tokens. `ContextManager.build_context()` has proper token-aware eviction but
   is never called from the streaming path. **Fix:** call `ContextManager.build_context()`
   at the end of `_build_context` as a token-ceiling pass.

3. **Token estimate is telemetry, not a guard (P0).** `iteration_input_tokens`
   is computed on line ~525 but never compared to any threshold. Aria never sees
   her own context size. **Fix:** add `_get_model_token_limits()` helper reading
   `safe_prompt_tokens` from models.yaml; inject `[CONTEXT MONITOR]` system message
   at 80% threshold; hard-abort and surface user message at 95%.

4. **`api_client.post()` missing `params=` → ghost sessions accumulate (P1).**
   `aria_skills/api_client/__init__.py` line 1169: `post(path, data=None)` has
   no `params` kwarg. `prune_stale_sessions` in `agent_manager` calls
   `self._api.post("/engine/sessions/cleanup", params={...})` → `TypeError: post()
   got an unexpected keyword argument 'params'` → caught silently → pruning NEVER
   runs → 72 ghost sessions. **Fix:** add `params: dict | None = None` to `post()`
   and forward to `_request_with_retry`.

5. **Memory compression has no auto-trigger (P1).** The `memory_compression` skill
   exists but is only called manually or via cron. Long conversations have no
   automatic compression before the token wall. **Fix:** call compression in
   `_build_context` at ~70% of model limit, replacing verbose middle messages
   with a summary stored in `aria_memories/`.

**Key patterns learned:**

- **Message count != token count.** Always enforce BOTH limits. Count-only windows
  fail catastrophically when tool results are verbose.
- **`if existing:` for partial collections means if ANY item exists.** When
  enforcing ALL items in a matching set, use `len(existing) == len(required)`.
- **`api_client.get()` has `params=` but `api_client.post()` does not.**
  This asymmetry silently killed session pruning. Always test all HTTP methods
  when adding params to an endpoint.
- **`dry_run=True` is the default on cleanup endpoints for safety.**
  If params are silently dropped, cleanup runs with `dry_run=True` default
  instead of `dry_run=False` as intended. Check Query param defaults.
- **Aria must know her own token count.** No self-awareness = no self-regulation.
  The token monitor pattern (soft warn at 80%, hard stop at 95%) should be
  standard across all long-running contexts.
