"""
Aria Brain — FastAPI Application Factory (v3.0)

Modular API with:
  • SQLAlchemy 2.0 async ORM + psycopg 3 driver
  • Sub-routers for every domain
  • Strawberry GraphQL on /graphql
  • Prometheus instrumentation
"""

import logging
import os
import asyncio
import time as _time
import traceback
import uuid as _uuid
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

# S-103: Authentication dependencies
from fastapi import Depends
try:
    from .auth import require_api_key, require_admin_key
except ImportError:
    from auth import require_api_key, require_admin_key

# Import-path compatibility for mixed absolute/relative imports across src/api.
_API_DIR = str(Path(__file__).resolve().parent)
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception as e:
        logging.debug("Could not set WindowsSelectorEventLoopPolicy: %s", e)

try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

try:
    from .config import API_VERSION, SKILL_BACKFILL_ON_STARTUP
    from .db import async_engine, ensure_schema
    from .startup_skill_backfill import run_skill_invocation_backfill
except ImportError:
    from config import API_VERSION, SKILL_BACKFILL_ON_STARTUP
    from db import async_engine, ensure_schema
    from startup_skill_backfill import run_skill_invocation_backfill

_logger = logging.getLogger("aria.api")


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Aria Brain API v3.0 starting up…")
    try:
        await ensure_schema()
        print("✅ Database schema ensured (SQLAlchemy 2 + psycopg3)")
    except Exception as e:
        print(f"⚠️  Database init failed: {e}")

    # ── Phase 1: Seed DB tables (models + agents) BEFORE engine pool loads ──
    # Models must be in DB before LLM gateway resolves them.
    # Agents must be in DB before AgentPool.load_agents() reads them.

    # Seed LLM models from models.yaml → llm_models DB table
    try:
        try:
            from .models_sync import sync_models_from_yaml
        except ImportError:
            from models_sync import sync_models_from_yaml
        try:
            from .db import AsyncSessionLocal as _SeedSessionLocal
        except ImportError:
            from db import AsyncSessionLocal as _SeedSessionLocal
        seed_stats = await sync_models_from_yaml(_SeedSessionLocal)
        print(f"✅ Models synced to DB: {seed_stats['inserted']} new, {seed_stats['updated']} updated ({seed_stats['total']} total)")
    except Exception as e:
        print(f"⚠️  Models DB sync failed (non-fatal): {e}")

    # Auto-sync agents from AGENTS.md → agent_state DB table
    try:
        try:
            from .agents_sync import sync_agents_from_markdown
        except ImportError:
            from agents_sync import sync_agents_from_markdown
        try:
            from .db import AsyncSessionLocal as _AgentSessionLocal
        except ImportError:
            from db import AsyncSessionLocal as _AgentSessionLocal
        agent_stats = await sync_agents_from_markdown(_AgentSessionLocal)
        print(f"✅ Agents synced to DB: {agent_stats.get('inserted', 0)} new, {agent_stats.get('updated', 0)} updated ({agent_stats.get('total', 0)} total)")
    except Exception as e:
        print(f"⚠️  Agents DB sync failed (non-fatal): {e}")

    # ── Phase 2: Initialize Aria Engine (chat, streaming, agents) ─────────
    # S-52/S-53: Now that DB is seeded, engine pool will find all agents.
    _rt_pool = None  # Keep reference for reload on POST /agents/db/sync
    try:
        from aria_engine.config import EngineConfig
        from aria_engine.llm_gateway import LLMGateway
        from aria_engine.tool_registry import ToolRegistry
        from aria_engine.chat_engine import ChatEngine
        from aria_engine.streaming import StreamManager
        from aria_engine.context_manager import ContextManager
        from aria_engine.prompts import PromptAssembler
        try:
            from .db import AsyncSessionLocal
        except ImportError:
            from db import AsyncSessionLocal

        engine_cfg = EngineConfig()
        gateway = LLMGateway(engine_cfg)
        tool_registry = ToolRegistry()
        # Auto-discover tools from aria_skills/*/skill.json manifests
        try:
            tool_count = tool_registry.discover_from_manifests()
            print(f"✅ Tool registry: {tool_count} tools discovered from skill manifests")
        except Exception as te:
            print(f"⚠️  Tool manifest discovery failed (non-fatal): {te}")
        chat_engine = ChatEngine(engine_cfg, gateway, tool_registry, AsyncSessionLocal)
        stream_manager = StreamManager(engine_cfg, gateway, tool_registry, AsyncSessionLocal)
        context_manager = ContextManager(engine_cfg)
        prompt_assembler = PromptAssembler(engine_cfg)

        configure_engine(
            config=engine_cfg,
            chat_engine=chat_engine,
            stream_manager=stream_manager,
            context_manager=context_manager,
            prompt_assembler=prompt_assembler,
        )
        # Initialize Roundtable + Swarm engines (multi-agent discussions)
        try:
            from aria_engine.roundtable import Roundtable
            from aria_engine.agent_pool import AgentPool
            from aria_engine.routing import EngineRouter
            from aria_engine.swarm import SwarmOrchestrator

            _rt_pool = AgentPool(engine_cfg, async_engine, llm_gateway=gateway)
            await _rt_pool.load_agents()
            _rt_router = EngineRouter(async_engine)
            _n_patterns = await _rt_router.initialize_patterns()
            print(f"✅ Routing patterns: {_n_patterns} focus profiles loaded from DB")
            _roundtable = Roundtable(async_engine, _rt_pool, _rt_router)
            _swarm = SwarmOrchestrator(async_engine, _rt_pool, _rt_router)
            configure_roundtable(_roundtable, async_engine)
            configure_swarm(_swarm)
            print("✅ Roundtable + Swarm engines initialized")

            # Inject orchestrators into ChatEngine for /roundtable & /swarm commands
            chat_engine.set_roundtable(_roundtable)
            chat_engine.set_swarm(_swarm)
            chat_engine.set_escalation_router(_rt_router)
            print("✅ Slash commands wired (chat → roundtable/swarm)")
        except Exception as rte:
            print(f"⚠️  Roundtable/Swarm init failed (non-fatal): {rte}")

        print("✅ Aria Engine initialized (chat + streaming + agents + roundtable + swarm)")
    except Exception as e:
        print(f"⚠️  Engine init failed (chat will be degraded): {e}")

    # Store pool reference so /agents/db/sync can reload it
    app.state.agent_pool = _rt_pool

    # S4-07: Auto-sync skill graph on startup
    try:
        try:
            from .graph_sync import sync_skill_graph
        except ImportError:
            from graph_sync import sync_skill_graph
        stats = await sync_skill_graph()
        print(f"✅ Skill graph synced: {stats['entities']} entities, {stats['relations']} relations")
    except Exception as e:
        print(f"⚠️  Skill graph sync failed (non-fatal): {e}")

    # S-54: Auto-sync cron jobs from YAML → DB
    try:
        try:
            from .cron_sync import sync_cron_jobs_from_yaml
        except ImportError:
            from cron_sync import sync_cron_jobs_from_yaml
        cron_summary = await sync_cron_jobs_from_yaml()
        print(f"✅ Cron jobs synced: {cron_summary}")
    except Exception as e:
        print(f"⚠️  Cron job sync failed (non-fatal): {e}")

    # Auto-heal skill telemetry gaps on startup (idempotent, toggleable).
    if SKILL_BACKFILL_ON_STARTUP:
        try:
            summary = await run_skill_invocation_backfill()
            print(
                "✅ Skill invocation backfill complete: "
                f"{summary['total']} inserted "
                f"(sessions={summary['agent_sessions']}, "
                f"model_usage={summary['model_usage']}, "
                f"activity_log={summary['activity_log']})"
            )
        except Exception as e:
            print(f"⚠️  Skill invocation backfill failed (non-fatal): {e}")
    else:
        print("ℹ️  Skill invocation backfill skipped (SKILL_BACKFILL_ON_STARTUP=false)")

    # S-AUTO: Background sentiment auto-scorer (zero LLM tokens)
    try:
        from .sentiment_autoscorer import run_autoscorer_loop
    except ImportError:
        from sentiment_autoscorer import run_autoscorer_loop
    scorer_task = asyncio.create_task(run_autoscorer_loop())
    print("🎯 Sentiment auto-scorer background task launched")

    # S-67: Background session auto-cleanup (every 6 hours)
    async def _session_cleanup_loop():
        """Prune stale sessions (>30 days) every 6 hours."""
        from aria_engine.session_manager import NativeSessionManager
        mgr = NativeSessionManager(async_engine)
        while True:
            try:
                await asyncio.sleep(6 * 3600)  # 6 hours
                result = await mgr.prune_old_sessions(days=30, dry_run=False)
                if result["pruned_count"] > 0:
                    _logger.info(
                        "Session cleanup: pruned %d sessions (%d messages)",
                        result["pruned_count"], result["message_count"],
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.warning("Session cleanup error: %s", exc)

    # Ghost session purge: delete 0-message sessions older than 60 min every 10 min
    # RT-01 decision: 1 hour TTL (15 min was too aggressive for slow typers)
    async def _ghost_purge_loop():
        """Delete ghost sessions (message_count=0, >60 min old) every 10 minutes."""
        from aria_engine.session_manager import NativeSessionManager
        mgr = NativeSessionManager(async_engine)
        while True:
            try:
                await asyncio.sleep(10 * 60)  # 10 minutes
                deleted = await mgr.delete_ghost_sessions(older_than_minutes=60)
                if deleted:
                    _logger.info("Ghost purge: removed %d empty sessions", deleted)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.warning("Ghost purge error: %s", exc)

    # Cron session purge: delete cron/swarm sessions older than 1 day (every 1 hour)
    # RT-02/05: 1-day TTL keeps only today's cron sessions; runs hourly to bound accumulation
    async def _cron_session_cleanup_loop():
        """Prune cron/swarm/subagent sessions older than 1 day every hour."""
        from aria_engine.session_manager import NativeSessionManager
        mgr = NativeSessionManager(async_engine)
        # Run once immediately on startup to clear any existing backlog
        try:
            for stype in ("cron", "swarm", "subagent"):
                result = await mgr.prune_sessions_by_type(stype, days=1, dry_run=False)
                if result["pruned_count"] > 0:
                    _logger.info(
                        "Cron startup cleanup: pruned %d '%s' sessions",
                        result["pruned_count"], stype,
                    )
        except Exception as exc:
            _logger.warning("Cron startup cleanup error: %s", exc)
        while True:
            try:
                await asyncio.sleep(3600)  # 1 hour
                for stype in ("cron", "swarm", "subagent"):
                    result = await mgr.prune_sessions_by_type(stype, days=1, dry_run=False)
                    if result["pruned_count"] > 0:
                        _logger.info(
                            "Cron cleanup: pruned %d '%s' sessions",
                            result["pruned_count"], stype,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.warning("Cron session cleanup error: %s", exc)

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    ghost_task = asyncio.create_task(_ghost_purge_loop())
    cron_cleanup_task = asyncio.create_task(_cron_session_cleanup_loop())
    print("🧹 Session auto-cleanup launched (every 6h, >30d) + ghost purge (every 10m, 0-msg >60m) + cron TTL (every 1h, >1d, runs on startup)")

    yield

    # Graceful shutdown
    for task in (scorer_task, cleanup_task, ghost_task, cron_cleanup_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    print("🛑 Background tasks stopped (auto-scorer + session-cleanup + ghost-purge + cron-cleanup)")

    await async_engine.dispose()
    print("🔌 Database engine disposed")


# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Aria Brain API",
    description=(
        "## Aria Blue Data API v3\n\n"
        "Canonical data API for the Aria AI assistant ecosystem.\n\n"
        "### Stack\n"
        "- **ORM**: SQLAlchemy 2.0 async\n"
        "- **Driver**: psycopg 3\n"
        "- **GraphQL**: Strawberry (at `/graphql`)\n\n"
        "### Domains\n"
        "Activities · Thoughts · Memories · Goals · Sessions · Model Usage · "
        "LiteLLM · Providers · Security · Knowledge Graph · Social · "
        "Records · Admin"
    ),
    version=API_VERSION,
    lifespan=lifespan,
    root_path="/api",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ── Middleware ────────────────────────────────────────────────────────────────

_web_port = os.getenv("WEB_INTERNAL_PORT", "5000")
_CORS_ORIGINS = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    f"http://localhost:{_web_port},http://aria-web:{_web_port}",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)

# Security middleware — rate limiting, injection scanning, security headers
from security_middleware import SecurityMiddleware, RateLimiter

app.add_middleware(
    SecurityMiddleware,
    rate_limiter=RateLimiter(
        requests_per_minute=300,
        requests_per_hour=5000,
        burst_limit=50,
    ),
    max_body_size=2_000_000,
)

Instrumentator().instrument(app).expose(app)

_perf_logger = logging.getLogger("aria.perf")


# ── Global Exception Handlers (S6-07) ────────────────────────────────────────
# Catch SQLAlchemy errors globally so missing tables return clean 503 JSON
# instead of crashing the connection (server disconnect).

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — return 500 JSON instead of disconnect."""
    exc_type = type(exc).__name__
    exc_module = type(exc).__module__ or ""

    # SQLAlchemy ProgrammingError (missing table, bad column, etc.)
    if "ProgrammingError" in exc_type or "UndefinedTableError" in exc_type:
        _logger.error("Database schema error on %s %s: %s",
                       request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": "Database table not available",
                "detail": str(exc).split("\n")[0][:200],
                "path": request.url.path,
                "hint": "Run ensure_schema() or check pgvector extension",
            },
        )

    # SQLAlchemy OperationalError (connection issues, etc.)
    if "OperationalError" in exc_type:
        _logger.error("Database connection error on %s %s: %s",
                       request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": "Database connection error",
                "detail": str(exc).split("\n")[0][:200],
                "path": request.url.path,
            },
        )

    # Everything else — log full traceback but return clean JSON
    _logger.error("Unhandled exception on %s %s: %s\n%s",
                   request.method, request.url.path, exc,
                   traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc)[:200],
            "type": exc_type,
            "path": request.url.path,
        },
    )


@app.middleware("http")
async def request_timing_middleware(request, call_next):
    start = _time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (_time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    if elapsed_ms > 100:
        _perf_logger.warning(
            "Slow request: %s %s took %.1fms (status=%s)",
            request.method, request.url.path, elapsed_ms, response.status_code,
        )
    return response


@app.middleware("http")
async def correlation_middleware(request, call_next):
    try:
        from aria_mind.logging_config import correlation_id_var
    except ModuleNotFoundError:
        import contextvars as _ctx
        correlation_id_var = _ctx.ContextVar("correlation_id", default="")
    cid = request.headers.get("X-Correlation-ID", str(_uuid.uuid4())[:8])
    correlation_id_var.set(cid)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


@app.get("/api/metrics")
async def metrics():
    if HAS_PROMETHEUS:
        from starlette.responses import Response
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    return {"error": "prometheus_client not installed"}


# ── REST routers ─────────────────────────────────────────────────────────────

try:
    from .routers.health import router as health_router
    from .routers.activities import router as activities_router
    from .routers.thoughts import router as thoughts_router
    from .routers.memories import router as memories_router
    from .routers.goals import router as goals_router
    from .routers.sessions import router as sessions_router
    from .routers.model_usage import router as model_usage_router
    from .routers.litellm import router as litellm_router
    from .routers.providers import router as providers_router
    from .routers.security import router as security_router
    from .routers.knowledge import router as knowledge_router
    from .routers.social import router as social_router
    from .routers.operations import router as operations_router
    from .routers.records import router as records_router
    from .routers.admin import router as admin_router, files_router
    from .routers.models_config import router as models_config_router
    from .routers.models_crud import router as models_crud_router
    from .routers.working_memory import router as working_memory_router
    from .routers.skills import router as skills_router
    from .routers.lessons import router as lessons_router
    from .routers.proposals import router as proposals_router
    from .routers.analysis import router as analysis_router
    from .routers.sentiment import router as sentiment_router
    from .routers.engine_cron import router as engine_cron_router
    from .routers.engine_sessions import router as engine_sessions_router
    from .routers.engine_agents import router as engine_agents_router
    from .routers.engine_agent_metrics import router as engine_agent_metrics_router
    from .routers.agents_crud import router as agents_crud_router
    from .routers.engine_focus import router as engine_focus_router
    from .routers.engine_roundtable import router as engine_roundtable_router, configure_roundtable, configure_swarm, register_roundtable
    from .routers.engine_chat import register_engine_chat, configure_engine
    from .routers.artifacts import router as artifacts_router
    from .routers.rpg import router as rpg_router
    from .routers.telegram import router as telegram_router
except ImportError:
    from routers.health import router as health_router
    from routers.activities import router as activities_router
    from routers.thoughts import router as thoughts_router
    from routers.memories import router as memories_router
    from routers.goals import router as goals_router
    from routers.sessions import router as sessions_router
    from routers.model_usage import router as model_usage_router
    from routers.litellm import router as litellm_router
    from routers.providers import router as providers_router
    from routers.security import router as security_router
    from routers.knowledge import router as knowledge_router
    from routers.social import router as social_router
    from routers.operations import router as operations_router
    from routers.records import router as records_router
    from routers.admin import router as admin_router, files_router
    from routers.models_config import router as models_config_router
    from routers.models_crud import router as models_crud_router
    from routers.working_memory import router as working_memory_router
    from routers.skills import router as skills_router
    from routers.lessons import router as lessons_router
    from routers.proposals import router as proposals_router
    from routers.analysis import router as analysis_router
    from routers.sentiment import router as sentiment_router
    from routers.engine_cron import router as engine_cron_router
    from routers.engine_sessions import router as engine_sessions_router
    from routers.engine_agents import router as engine_agents_router
    from routers.engine_agent_metrics import router as engine_agent_metrics_router
    from routers.agents_crud import router as agents_crud_router
    from routers.engine_focus import router as engine_focus_router
    from routers.engine_roundtable import router as engine_roundtable_router, configure_roundtable, configure_swarm, register_roundtable
    from routers.engine_chat import register_engine_chat, configure_engine
    from routers.artifacts import router as artifacts_router
    from routers.rpg import router as rpg_router
    from routers.telegram import router as telegram_router

app.include_router(health_router)  # S-103: Health exempt from auth (monitoring)
# S-103: All data routers require API key
_api_deps = [Depends(require_api_key)]
_admin_deps = [Depends(require_admin_key)]
app.include_router(activities_router, dependencies=_api_deps)
app.include_router(thoughts_router, dependencies=_api_deps)
app.include_router(memories_router, dependencies=_api_deps)
app.include_router(goals_router, dependencies=_api_deps)
app.include_router(sessions_router, dependencies=_api_deps)
app.include_router(model_usage_router, dependencies=_api_deps)
app.include_router(litellm_router, dependencies=_api_deps)
app.include_router(providers_router, dependencies=_api_deps)
app.include_router(security_router, dependencies=_api_deps)
app.include_router(knowledge_router, dependencies=_api_deps)
app.include_router(social_router, dependencies=_api_deps)
app.include_router(operations_router, dependencies=_api_deps)
app.include_router(records_router, dependencies=_api_deps)
app.include_router(admin_router, dependencies=_admin_deps)  # Admin needs elevated key
app.include_router(files_router, dependencies=_api_deps)  # Read-only file browser (standard key)
app.include_router(models_config_router, dependencies=_api_deps)
app.include_router(models_crud_router, dependencies=_api_deps)
app.include_router(working_memory_router, dependencies=_api_deps)
app.include_router(skills_router, dependencies=_api_deps)
app.include_router(lessons_router, dependencies=_api_deps)
app.include_router(proposals_router, dependencies=_api_deps)
app.include_router(analysis_router, dependencies=_api_deps)
app.include_router(sentiment_router, dependencies=_api_deps)
app.include_router(engine_cron_router, dependencies=_api_deps)
app.include_router(engine_sessions_router, dependencies=_api_deps)
app.include_router(engine_agent_metrics_router, dependencies=_api_deps)
app.include_router(engine_agents_router, dependencies=_api_deps)
app.include_router(engine_focus_router, dependencies=_api_deps)
app.include_router(agents_crud_router, dependencies=_api_deps)
app.include_router(artifacts_router, dependencies=_api_deps)
app.include_router(rpg_router, dependencies=_api_deps)
# Telegram webhook: no API key (Telegram calls /webhook directly, validated by TELEGRAM_WEBHOOK_SECRET)
# Admin endpoints /register-webhook, /webhook-info protected by the secret + token
app.include_router(telegram_router)

# ── Static file serving (RPG Dashboard at /rpg/) ─────────────────────────────
# Mounted AFTER API routers so /api/* takes priority.
# Path resolved relative to src/api/static/ — bind-mounted in Docker.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_RPG_STATIC = _STATIC_DIR / "rpg"
if _RPG_STATIC.exists():
    app.mount("/rpg", StaticFiles(directory=str(_RPG_STATIC), html=True), name="rpg-dashboard")

# Engine Roundtable + Swarm — REST + WebSocket
register_roundtable(app, dependencies=_api_deps)

# Engine Chat — REST + WebSocket
register_engine_chat(app, dependencies=_api_deps)

# ── GraphQL ──────────────────────────────────────────────────────────────────

try:
    from .gql import graphql_app as gql_router   # noqa: E402
except ImportError:
    from gql import graphql_app as gql_router   # noqa: E402

app.include_router(gql_router, prefix="/graphql", dependencies=_api_deps)

# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("API_INTERNAL_PORT", "8000")))
