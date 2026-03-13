"""
Aria Engine — Standalone Runtime Entrypoint
Native Python runtime entrypoint.

Boot sequence:
  Phase 1: Database connection
  Phase 2: Run pending migrations
  Phase 3: Load agent state
  Phase 4: Start scheduler
  Phase 5: Health endpoint on :8081

Usage:
  python -m aria_engine.entrypoint
  # or via pyproject.toml script:
  aria-engine
"""
import asyncio
import signal
import sys
import logging

from aria_engine.config import EngineConfig

logger = logging.getLogger("aria_engine")


class AriaEngine:
    """Main engine process — manages DB, scheduler, agents, health."""

    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig.from_env()
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._agent_pool = None
        self._health_server = None
        self._db_engine = None
        self._session_factory = None

    @property
    def scheduler(self):
        """Get the EngineScheduler instance."""
        return self._scheduler

    @property
    def agent_pool(self):
        """Get the AgentPool instance."""
        return self._agent_pool

    @property
    def db_engine(self):
        """Get the async SQLAlchemy engine."""
        return self._db_engine

    async def start(self):
        """Boot sequence."""
        logger.info("🚀 Aria Engine starting...")

        # Phase 0: OpenTelemetry (must run before DB / HTTP activity)
        self._init_tracing()
        logger.info("✅ Phase 0: Tracing initialized")

        # Phase 1: Database
        await self._init_database()
        logger.info("✅ Phase 1: Database connected")

        # Phase 2: Schema bootstrapping handled by ensure_schema() in API lifespan
        logger.info("✅ Phase 2: Schema ready (ORM-driven)")

        # Phase 3: Load agent state from DB
        await self._init_agents()
        logger.info("✅ Phase 3: Agents initialized")

        # Phase 4: Start scheduler (cron jobs from DB)
        await self._init_scheduler()
        logger.info("✅ Phase 4: Scheduler started")

        # Phase 5: Health endpoint
        await self._init_health()
        logger.info("✅ Phase 5: Health server on :8081")

        # Register global engine reference
        from aria_engine import set_engine
        set_engine(self)

        logger.info("🟢 Aria Engine running — all systems nominal")

        # Wait for shutdown signal
        await self._shutdown_event.wait()
        await self._cleanup()
        logger.info("🔴 Aria Engine stopped")

    def _init_tracing(self):
        """Phase 0: Configure OpenTelemetry (opt-in via OTEL_EXPORTER_OTLP_ENDPOINT)."""
        try:
            from aria_engine.tracing import configure_tracing, instrument_libraries

            if configure_tracing():
                instrument_libraries()
                logger.info("OpenTelemetry tracing active")
            else:
                logger.debug("OpenTelemetry tracing skipped (no endpoint configured)")
        except Exception as e:
            logger.warning("Tracing init failed (non-fatal): %s", e)

    async def _init_database(self):
        """Create async SQLAlchemy engine + session factory."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import text as sa_text

        # Convert postgres URL to asyncpg driver
        db_url = self.config.database_url
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql+psycopg://"):
            db_url = db_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

        self._db_engine = create_async_engine(
            db_url,
            pool_size=self.config.db_pool_size,
            max_overflow=self.config.db_max_overflow,
            pool_pre_ping=True,
            echo=self.config.debug,
        )
        self._session_factory = async_sessionmaker(
            self._db_engine,
            expire_on_commit=False,
        )
        # Verify connection
        async with self._db_engine.begin() as conn:
            await conn.execute(sa_text("SELECT 1"))

    async def _init_agents(self):
        """Load agent definitions from DB and instantiate pool."""
        from aria_engine.agent_pool import AgentPool

        self._agent_pool = AgentPool(
            config=self.config,
            db_engine=self._db_engine,
        )
        await self._agent_pool.load_agents()

    async def _init_scheduler(self):
        """Start APScheduler with PostgreSQL job store."""
        from aria_engine.scheduler import EngineScheduler

        self._scheduler = EngineScheduler(
            config=self.config,
            db_engine=self._db_engine,
            agent_pool=self._agent_pool,
        )
        await self._scheduler.start()

    async def _init_health(self):
        """Minimal aiohttp health server on port 8081."""
        try:
            from aiohttp import web

            async def health_handler(request):
                return web.json_response({
                    "status": "healthy",
                    "engine": "aria_engine",
                    "version": "2.0.0",
                    "scheduler": self._scheduler.is_running if self._scheduler else False,
                    "agents": len(self._agent_pool._agents) if self._agent_pool else 0,
                    "db": self._db_engine is not None,
                })

            app = web.Application()
            app.router.add_get("/health", health_handler)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", 8081)
            await site.start()
            self._health_server = runner
        except ImportError:
            logger.warning("aiohttp not installed — health endpoint disabled")

    async def _cleanup(self):
        """Graceful shutdown."""
        if self._scheduler:
            await self._scheduler.stop()
        if self._agent_pool:
            await self._agent_pool.shutdown()
        if self._health_server:
            await self._health_server.cleanup()
        if self._db_engine:
            await self._db_engine.dispose()

    def request_shutdown(self):
        """Signal the engine to shut down gracefully."""
        self._shutdown_event.set()


def main():
    """CLI entrypoint — called by Docker CMD."""
    # Use structured logging if available, otherwise fallback to basicConfig
    # Ensure stdlib logging always outputs to stderr at INFO level.
    # This is the definitive config — structlog may or may not bridge
    # stdlib, so we always add a StreamHandler ourselves.
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.root.addHandler(_handler)
    logging.root.setLevel(logging.INFO)

    try:
        from aria_mind.logging_config import configure_logging
        configure_logging()
    except ImportError:
        pass  # stdlib handler already set above

    logger.info("Logging initialized")

    engine = AriaEngine()
    loop = asyncio.new_event_loop()

    # Handle SIGTERM/SIGINT for Docker stop
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, engine.request_shutdown)

    try:
        loop.run_until_complete(engine.start())
    except KeyboardInterrupt:
        engine.request_shutdown()
        loop.run_until_complete(engine._cleanup())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
