"""
Native Scheduler — APScheduler 4.x with PostgreSQL persistence.

Python-native scheduler replacing legacy Node.js cron.
Features:
- APScheduler 4.x async scheduler with SQLAlchemy data store
- Job definitions stored in aria_engine.cron_jobs table
- Job execution routed to agents via AgentPool
- Job state tracking (last_run, status, duration, next_run)
- Error handling with retry + exponential backoff
- Dynamic job management (add/remove/update at runtime)
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from apscheduler import AsyncScheduler, ConflictPolicy
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker

from aria_engine.config import EngineConfig
from aria_engine.exceptions import SchedulerError
from aria_engine.metrics import METRICS
from db.models import EngineCronJob, ActivityLog

# aria-api base URL.
# Inside Docker: ENGINE_API_BASE_URL is unset, so the default "http://aria-api:8000"
# resolves via the Docker-internal hostname.  Locally you MUST export
# ENGINE_API_BASE_URL=http://localhost:8000 (or whatever port aria-api maps to)
# or scheduler job HTTP callbacks will silently fail because "aria-api" is not
# resolvable outside the container network.
_ENGINE_API_BASE_OVERRIDE = os.getenv("ENGINE_API_BASE_URL")
_API_BASE = _ENGINE_API_BASE_OVERRIDE or "http://aria-api:8000"
if not _ENGINE_API_BASE_OVERRIDE and not os.getenv("RUNNING_IN_DOCKER"):
    # Only warn once at module import; not in Docker where the default is correct.
    import logging as _logging
    _logging.getLogger("aria.engine.scheduler").warning(
        "ENGINE_API_BASE_URL is not set and RUNNING_IN_DOCKER is not set. "
        "Scheduler HTTP callbacks will target http://aria-api:8000 which is "
        "only resolvable inside the Docker network. "
        "Set ENGINE_API_BASE_URL=http://localhost:8000 for local development."
    )

logger = logging.getLogger("aria.engine.scheduler")

# Maximum concurrent job executions
MAX_CONCURRENT_JOBS = 5

# Retry backoff cap (seconds)
MAX_BACKOFF_SECONDS = 600

# Module-level reference to the active EngineScheduler instance.
# Required because APScheduler 4.x serializes task references and cannot
# handle bound methods — only module-level callables.
_active_scheduler: "EngineScheduler | None" = None


async def _scheduler_dispatch(
    job_id: str,
    agent_id: str,
    payload_type: str,
    payload: str,
    session_mode: str,
    max_duration: int,
    retry_count: int,
    model: str = "",
    job_name: str = "",
) -> None:
    """Module-level trampoline that APScheduler can serialize.

    IMPORTANT: This function MUST NOT raise — any unhandled exception
    kills APScheduler's background task group and stops ALL scheduling.
    """
    try:
        if _active_scheduler is None:
            logger.error("Scheduler dispatch called but no active scheduler")
            return
        await _active_scheduler._execute_job(
            job_id=job_id,
            agent_id=agent_id,
            payload_type=payload_type,
            payload=payload,
            session_mode=session_mode,
            max_duration=max_duration,
            retry_count=retry_count,
            model=model,
            job_name=job_name,
        )
    except Exception as exc:
        logger.error(
            "CRITICAL: _scheduler_dispatch for %s raised: %s",
            job_id, exc, exc_info=True,
        )


def parse_schedule(schedule_str: str) -> CronTrigger | IntervalTrigger:
    """
    Parse a schedule string into an APScheduler trigger.

    Supports:
    - Cron expressions (6-field node-cron or 5-field standard):
      "0 0 6 * * *" → sec min hour dom month dow
    - Interval shorthand: "15m", "60m", "1h", "30s"

    Args:
        schedule_str: Cron expression or interval shorthand.

    Returns:
        APScheduler trigger instance.

    Raises:
        SchedulerError: If the schedule string cannot be parsed.
    """
    schedule_str = schedule_str.strip()

    # Interval shorthand: "15m", "60m", "1h", "30s"
    if schedule_str.endswith("m") and schedule_str[:-1].isdigit():
        minutes = int(schedule_str[:-1])
        return IntervalTrigger(minutes=minutes)
    if schedule_str.endswith("h") and schedule_str[:-1].isdigit():
        hours = int(schedule_str[:-1])
        return IntervalTrigger(hours=hours)
    if schedule_str.endswith("s") and schedule_str[:-1].isdigit():
        seconds = int(schedule_str[:-1])
        return IntervalTrigger(seconds=seconds)

    # Cron expression
    parts = schedule_str.split()
    if len(parts) == 6:
        # 6-field node-cron: sec min hour dom month dow
        second, minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            second=second,
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    elif len(parts) == 5:
        # 5-field standard cron: min hour dom month dow
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
    else:
        raise SchedulerError(f"Cannot parse schedule: {schedule_str!r}")


class EngineScheduler:
    """
    Native async scheduler backed by PostgreSQL.

    Lifecycle:
        scheduler = EngineScheduler(config, db_engine)
        await scheduler.start()   # loads jobs from DB, starts APScheduler
        ...
        await scheduler.stop()    # graceful shutdown

    Usage:
        scheduler = EngineScheduler(config, db_engine)
        await scheduler.start()

        # Jobs auto-loaded from DB on start
        # Manual trigger:
        await scheduler.trigger_job("work_cycle")

        # Dynamic management:
        await scheduler.add_job({...})
        await scheduler.update_job("work_cycle", {"enabled": False})
        await scheduler.remove_job("old_job")
    """

    def __init__(
        self,
        config: EngineConfig,
        db_engine: AsyncEngine,
        agent_pool: Any | None = None,
    ):
        self.config = config
        self._db_engine = db_engine
        self._agent_pool = agent_pool
        self._scheduler: AsyncScheduler | None = None
        self._running = False
        self._job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        # ORM session maker for queries that need mapped instances
        self._session_factory = async_sessionmaker(
            self._db_engine, expire_on_commit=False,
        )
        self._active_executions: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """
        Start the scheduler: initialize APScheduler data store,
        load enabled jobs from DB, and begin scheduling.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting EngineScheduler...")

        global _active_scheduler

        # Create APScheduler with PostgreSQL data store
        data_store = SQLAlchemyDataStore(self._db_engine)
        self._scheduler = AsyncScheduler(data_store=data_store)

        # Enter async context manager (initializes services + task group)
        await self._scheduler.__aenter__()
        self._running = True
        _active_scheduler = self

        # Load and register all enabled jobs from the DB
        await self._load_jobs_from_db()

        # Start the background task processor so schedules actually fire.
        # Without this, APScheduler 4.x registers schedules but never
        # processes them — __aenter__ alone only sets up the data store.
        await self._scheduler.start_in_background()

        # Wait for aria-api to be reachable before jobs start dispatching.
        # IntervalTrigger jobs fire immediately, so without this check
        # they fail with "Cannot connect to host aria-api:8000" on cold start.
        await self._wait_for_api()

        logger.info("EngineScheduler started — jobs loaded and processing")

    async def _wait_for_api(self, timeout: int = 60) -> None:
        """Block until aria-api is reachable, up to *timeout* seconds."""
        import aiohttp

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with aiohttp.ClientSession() as http:
                    async with http.get(
                        f"{_API_BASE}/api/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            logger.info("aria-api is reachable")
                            return
            except Exception as e:
                logger.debug("Health check attempt: %s", e)
            await asyncio.sleep(2)
        logger.warning("aria-api not reachable after %ds — jobs may fail initially", timeout)

    async def stop(self) -> None:
        """Gracefully stop the scheduler and wait for active jobs."""
        if not self._running:
            return

        global _active_scheduler
        logger.info("Stopping EngineScheduler...")
        self._running = False
        _active_scheduler = None

        # Cancel active executions
        for job_id, task in list(self._active_executions.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            logger.debug("Cancelled active execution: %s", job_id)

        self._active_executions.clear()

        # Shutdown APScheduler
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
            except Exception as e:
                logger.debug("APScheduler stop: %s", e)
            await self._scheduler.__aexit__(None, None, None)
            self._scheduler = None

        logger.info("EngineScheduler stopped")

    async def _load_jobs_from_db(self) -> None:
        """Load all enabled cron jobs from aria_engine.cron_jobs and register them."""
        async with self._db_engine.begin() as conn:
            stmt = (
                select(EngineCronJob)
                .where(EngineCronJob.enabled == True)
                .order_by(EngineCronJob.name)
            )
            result = await conn.execute(stmt)
            rows = result.mappings().all()

            # Also load disabled jobs so we can purge them from APScheduler's data store
            stmt_disabled = (
                select(EngineCronJob)
                .where(EngineCronJob.enabled == False)
            )
            result_disabled = await conn.execute(stmt_disabled)
            disabled_rows = result_disabled.mappings().all()

        # Remove disabled jobs from APScheduler's persistent data store
        # (APScheduler stores schedules in PG and replays them on restart)
        for row in disabled_rows:
            try:
                await self._scheduler.remove_schedule(row["id"])
                logger.info("Removed disabled job from APScheduler: %s", row["id"])
            except Exception:
                pass  # Already absent — that's fine

        registered = 0
        for row in rows:
            try:
                trigger = parse_schedule(row["schedule"])
                await self._scheduler.add_schedule(
                    _scheduler_dispatch,
                    trigger=trigger,
                    id=row["id"],
                    kwargs={
                        "job_id": row["id"],
                        "agent_id": row["agent_id"],
                        "payload_type": row["payload_type"],
                        "payload": row["payload"],
                        "session_mode": row["session_mode"],
                        "max_duration": row["max_duration_seconds"],
                        "retry_count": row["retry_count"],
                        "model": row.get("model", "") or "",
                        "job_name": row["name"],
                    },
                    conflict_policy=ConflictPolicy.replace,
                    misfire_grace_time=60,  # skip if >60s late (prevents backfill storm on restart)
                )
                registered += 1
                logger.debug("Registered job: %s (%s)", row["name"], row["schedule"])
            except Exception as e:
                logger.error("Failed to register job %s: %s", row["id"], e, exc_info=True)

        logger.info("Loaded %d/%d enabled cron jobs", registered, len(rows))

    async def _execute_job(
        self,
        job_id: str,
        agent_id: str,
        payload_type: str,
        payload: str,
        session_mode: str,
        max_duration: int,
        retry_count: int,
        model: str = "",
        job_name: str = "",
    ) -> None:
        """
        Execute a single cron job with concurrency control, timeout,
        and retry with exponential backoff.
        """
        async with self._job_semaphore:
            attempt = 0
            max_attempts = retry_count + 1
            last_error: str | None = None
            elapsed_ms = 0
            dispatch_result: dict = {}

            while attempt < max_attempts:
                start_time = time.monotonic()
                try:
                    # Update state: running
                    await self._update_job_state(
                        job_id,
                        status="running",
                        last_run_at=datetime.now(timezone.utc),
                    )

                    # Execute with timeout
                    dispatch_result = await asyncio.wait_for(
                        self._dispatch_to_agent(
                            job_id=job_id,
                            agent_id=agent_id,
                            payload_type=payload_type,
                            payload=payload,
                            session_mode=session_mode,
                            model=model,
                            job_name=job_name,
                        ),
                        timeout=max_duration,
                    ) or {}

                    elapsed_ms = int((time.monotonic() - start_time) * 1000)

                    # Update state: success
                    await self._update_job_state(
                        job_id,
                        status="success",
                        last_duration_ms=elapsed_ms,
                        increment_success=True,
                    )

                    # Write heartbeat log entry
                    model = dispatch_result.get("model", "")
                    tokens = dispatch_result.get("total_tokens", 0)
                    cost = dispatch_result.get("cost_usd", 0)
                    details = f"model={model}, tokens={tokens}, cost=${cost}" if model else "OK"
                    await self._write_heartbeat_log(
                        job_name=job_id,
                        status="success",
                        details=details,
                        duration_ms=elapsed_ms,
                    )

                    logger.info(
                        "Job %s completed in %dms", job_id, elapsed_ms
                    )
                    return

                except asyncio.TimeoutError:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    last_error = f"Timeout after {max_duration}s"
                    logger.warning("Job %s timed out (attempt %d)", job_id, attempt + 1)

                except Exception as e:
                    elapsed_ms = int((time.monotonic() - start_time) * 1000)
                    last_error = str(e)
                    logger.error(
                        "Job %s failed (attempt %d): %s", job_id, attempt + 1, e
                    )

                attempt += 1

                if attempt < max_attempts:
                    # Exponential backoff: 2^attempt seconds, capped
                    backoff = min(2**attempt, MAX_BACKOFF_SECONDS)
                    logger.info(
                        "Job %s retrying in %ds (attempt %d/%d)",
                        job_id, backoff, attempt + 1, max_attempts,
                    )
                    await asyncio.sleep(backoff)

            # All retries exhausted
            await self._update_job_state(
                job_id,
                status="failed",
                last_duration_ms=elapsed_ms,
                last_error=last_error,
                increment_fail=True,
            )

            # Write heartbeat log entry for failure
            await self._write_heartbeat_log(
                job_name=job_id,
                status="error",
                details=last_error or "Unknown error",
                duration_ms=elapsed_ms,
            )

            logger.error(
                "Job %s failed after %d attempts: %s", job_id, max_attempts, last_error
            )

    async def _dispatch_to_agent(
        self,
        job_id: str,
        agent_id: str,
        payload_type: str,
        payload: str,
        session_mode: str,
        model: str = "",
        job_name: str = "",
    ) -> dict:
        """
        Dispatch a job by creating a session via aria-api and sending
        the payload as a message.  This reuses the same proven code path
        as the web UI: prompt assembly, litellm proxy, session tracking.

        Returns dict with model, total_tokens, cost_usd from the API response.
        """
        import aiohttp

        if payload_type != "prompt":
            # skill / pipeline payloads are not session-based
            await self._dispatch_non_prompt(job_id, payload_type, payload)
            return {}

        async with aiohttp.ClientSession() as http:
            # S-103: Build auth headers for API calls
            _headers = {}
            _api_key = os.getenv("ARIA_API_KEY", "")
            if _api_key:
                _headers["X-API-Key"] = _api_key

            # 0. Fetch working memory context and prepend to payload
            #    This gives cron sessions awareness of recent tasks,
            #    goals, and observations — closing the blind-spot where
            #    cognition.py auto-injects WM but ChatEngine doesn't.
            wm_context_block = ""
            try:
                async with http.get(
                    f"{_API_BASE}/api/working-memory/context",
                    params={"limit": "8", "touch_access": "false"},
                    headers=_headers,
                ) as wm_resp:
                    if wm_resp.status == 200:
                        wm_data = await wm_resp.json()
                        items = wm_data.get("context", [])
                        if items:
                            lines = []
                            for it in items[:8]:
                                cat = it.get("category", "")
                                key = it.get("key", "")
                                val = it.get("value", "")
                                # Compact representation
                                val_str = (
                                    str(val)[:200]
                                    if not isinstance(val, str)
                                    else val[:200]
                                )
                                lines.append(f"- [{cat}/{key}] {val_str}")
                            wm_context_block = (
                                "\n\n## Working Memory (recent context)\n"
                                + "\n".join(lines)
                                + "\n"
                            )
            except Exception as wm_err:
                logger.debug("Job %s: WM context fetch skipped: %s", job_id, wm_err)

            enriched_payload = payload + wm_context_block if wm_context_block else payload

            # 1. Create a session via aria-api
            # Build a human-readable title: "⏱ work_cycle · 14:30"
            from datetime import datetime as _dt
            _time_label = _dt.now().strftime("%H:%M")
            _title = f"⏱ {job_name} · {_time_label}" if job_name else None
            session_body: dict = {
                "agent_id": agent_id,
                "session_type": "cron",
                "title": _title,
                "metadata": {"cron_job_id": job_id, "job_name": job_name, "origin": "scheduler"},
            }
            if model:
                session_body["model"] = model
            async with http.post(
                f"{_API_BASE}/api/engine/chat/sessions",
                json=session_body,
                headers=_headers,
            ) as create_resp:
                if create_resp.status != 201:
                    body = await create_resp.text()
                    raise SchedulerError(
                        f"Failed to create session for job {job_id}: "
                        f"HTTP {create_resp.status} — {body}"
                    )
                session_data = await create_resp.json()
            session_id = session_data["id"]

            logger.info(
                "Job %s: created session %s (agent=%s)",
                job_id, session_id, agent_id,
            )

            try:
                # 2. Send the cron payload as a message
                async with http.post(
                    f"{_API_BASE}/api/engine/chat/sessions/{session_id}/messages",
                    json={
                        "content": enriched_payload,
                        "enable_thinking": False,
                        "enable_tools": True,
                    },
                    headers=_headers,
                ) as msg_resp:
                    if msg_resp.status != 200:
                        body = await msg_resp.text()
                        raise SchedulerError(
                            f"Job {job_id} message failed: HTTP {msg_resp.status} — {body}"
                        )
                    result = await msg_resp.json()
            except Exception:
                # Clean up the empty session so it doesn't become a ghost
                try:
                    async with http.delete(
                        f"{_API_BASE}/api/engine/chat/sessions/{session_id}",
                        headers=_headers,
                    ) as cleanup_resp:
                        if cleanup_resp.status >= 400:
                            cleanup_body = await cleanup_resp.text()
                            METRICS.scheduler_session_close_failures_total.labels(
                                job_id=job_id,
                                phase="cleanup",
                            ).inc()
                            logger.warning(
                                "Job %s: cleanup session %s returned HTTP %s: %s",
                                job_id, session_id, cleanup_resp.status, cleanup_body,
                            )
                    logger.info(
                        "Job %s: cleaned up empty session %s after failure",
                        job_id, session_id,
                    )
                except Exception as cleanup_err:
                    METRICS.scheduler_session_close_failures_total.labels(
                        job_id=job_id,
                        phase="cleanup",
                    ).inc()
                    logger.warning(
                        "Job %s: failed to cleanup session %s: %s",
                        job_id, session_id, cleanup_err,
                    )
                raise

            logger.info(
                "Job %s: completed (model=%s, tokens=%s, cost=$%s)",
                job_id,
                result.get("model", "?"),
                result.get("total_tokens", "?"),
                result.get("cost_usd", "?"),
            )

            # 2b. Create a thought from productive cron jobs
            #     This ensures work_cycle output reaches the cognitive pipeline
            #     (thoughts → seed_memories → semantic_memories) since cognition.py
            #     doesn't run during cron sessions.
            _productive_jobs = {"work_cycle", "social_post", "browser_research",
                                "six_hour_review", "morning_checkin", "daily_reflection",
                                "weekly_summary"}
            if job_name in _productive_jobs:
                assistant_content = result.get("content", "") or ""
                # 2b-i. Create thought for cognitive pipeline
                try:
                    if len(assistant_content) > 30:
                        thought_content = (
                            f"[{job_name}] {assistant_content[:500]}"
                        )
                        async with http.post(
                            f"{_API_BASE}/api/thoughts",
                            json={
                                "content": thought_content,
                                "category": "work_cycle" if job_name == "work_cycle" else "reflection",
                            },
                            headers=_headers,
                        ) as thought_resp:
                            if thought_resp.status in (200, 201):
                                logger.debug("Job %s: thought created for cognitive pipeline", job_id)
                except Exception as thought_err:
                    logger.debug("Job %s: thought creation skipped: %s", job_id, thought_err)

                # 2b-ii. Write summary back to working memory so the NEXT
                #        cron session sees it via the WM context injection above.
                try:
                    if len(assistant_content) > 30:
                        async with http.post(
                            f"{_API_BASE}/api/working-memory",
                            json={
                                "key": f"last_{job_name}",
                                "value": {
                                    "summary": assistant_content[:400],
                                    "model": result.get("model", ""),
                                    "tokens": result.get("total_tokens", 0),
                                    "completed_at": datetime.now(timezone.utc).isoformat(),
                                },
                                "category": "cron_output",
                                "importance": 0.7,
                                "ttl_hours": 48,
                                "source": f"scheduler.{job_name}",
                            },
                            headers=_headers,
                        ) as wm_resp:
                            if wm_resp.status in (200, 201):
                                logger.debug("Job %s: result written to working memory", job_id)
                except Exception as wm_err:
                    logger.debug("Job %s: WM write-back skipped: %s", job_id, wm_err)

            # 3. Close the session
            async with http.delete(
                f"{_API_BASE}/api/engine/chat/sessions/{session_id}",
                headers=_headers,
            ) as close_resp:
                if close_resp.status >= 400:
                    close_body = await close_resp.text()
                    METRICS.scheduler_session_close_failures_total.labels(
                        job_id=job_id,
                        phase="close",
                    ).inc()
                    logger.warning(
                        "Job %s: failed to close session %s: HTTP %s — %s",
                        job_id,
                        session_id,
                        close_resp.status,
                        close_body,
                    )

            return result

    async def _dispatch_non_prompt(
        self, job_id: str, payload_type: str, payload: str,
    ) -> None:
        """Handle skill/pipeline payloads that don't need a chat session."""
        if payload_type == "skill":
            import json as _json

            parts = payload.strip().split(" ", 1)
            skill_func = parts[0]
            args_str = parts[1] if len(parts) > 1 else "{}"
            skill_name, func_name = skill_func.rsplit(".", 1)
            args = _json.loads(args_str)

            if self._agent_pool is None:
                raise SchedulerError("AgentPool not available for skill dispatch")
            skill = self._agent_pool.get_skill(skill_name)
            if skill is None:
                raise SchedulerError(f"Skill {skill_name!r} not found")
            func = getattr(skill, func_name, None)
            if func is None:
                raise SchedulerError(
                    f"Function {func_name!r} not found on skill {skill_name!r}"
                )
            await func(**args)

        elif payload_type == "pipeline":
            from aria_skills.pipeline_executor import PipelineExecutor
            executor = PipelineExecutor()
            await executor.run(payload)

        else:
            raise SchedulerError(f"Unknown payload_type: {payload_type!r}")

    async def _update_job_state(
        self,
        job_id: str,
        status: str | None = None,
        last_run_at: datetime | None = None,
        last_duration_ms: int | None = None,
        last_error: str | None = None,
        increment_success: bool = False,
        increment_fail: bool = False,
    ) -> None:
        """Update job execution state in the database."""
        values: dict[str, Any] = {"updated_at": func.now()}

        if status is not None:
            values["last_status"] = status
        if last_run_at is not None:
            values["last_run_at"] = last_run_at
        if last_duration_ms is not None:
            values["last_duration_ms"] = last_duration_ms
        if last_error is not None:
            values["last_error"] = last_error
        if increment_success:
            values["run_count"] = EngineCronJob.run_count + 1
            values["success_count"] = EngineCronJob.success_count + 1
        if increment_fail:
            values["run_count"] = EngineCronJob.run_count + 1
            values["fail_count"] = EngineCronJob.fail_count + 1

        stmt = (
            update(EngineCronJob)
            .where(EngineCronJob.id == job_id)
            .values(**values)
        )

        async with self._db_engine.begin() as conn:
            await conn.execute(stmt)

    async def _write_heartbeat_log(
        self,
        job_name: str,
        status: str,
        details: str,
        duration_ms: int,
    ) -> None:
        """Write a heartbeat_log entry via aria-api so the heartbeat page shows it."""
        import aiohttp

        try:
            async with aiohttp.ClientSession() as http:
                _hb_headers = {}
                _hb_key = os.getenv("ARIA_API_KEY", "")
                if _hb_key:
                    _hb_headers["X-API-Key"] = _hb_key
                async with http.post(
                    f"{_API_BASE}/api/heartbeat",
                    json={
                        "job_name": job_name,
                        "status": status,
                        "details": details,
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                        "duration_ms": duration_ms,
                    },
                    headers=_hb_headers,
                ):
                    pass
        except Exception as e:
            logger.warning("Failed to write heartbeat log for %s: %s", job_name, e)

    # ── Public management API ────────────────────────────────────────

    async def add_job(self, job_data: dict[str, Any]) -> str:
        """
        Add a new cron job to the database and register it with APScheduler.

        Args:
            job_data: Dict with keys: id (optional), name, schedule, agent_id,
                      payload_type, payload, session_mode, enabled, etc.

        Returns:
            The job ID.
        """
        job_id = job_data.get("id") or str(uuid4())

        async with self._db_engine.begin() as conn:
            stmt = insert(EngineCronJob).values(
                id=job_id,
                name=job_data["name"],
                schedule=job_data["schedule"],
                agent_id=job_data.get("agent_id", "aria"),
                enabled=job_data.get("enabled", True),
                payload_type=job_data.get("payload_type", "prompt"),
                payload=job_data["payload"],
                session_mode=job_data.get("session_mode", "isolated"),
                max_duration_seconds=job_data.get("max_duration_seconds", 300),
                retry_count=job_data.get("retry_count", 0),
            )
            await conn.execute(stmt)

        # Register with APScheduler if enabled
        if job_data.get("enabled", True) and self._scheduler:
            trigger = parse_schedule(job_data["schedule"])
            await self._scheduler.add_schedule(
                _scheduler_dispatch,
                trigger=trigger,
                id=job_id,
                kwargs={
                    "job_id": job_id,
                    "agent_id": job_data.get("agent_id", "aria"),
                    "payload_type": job_data.get("payload_type", "prompt"),
                    "payload": job_data["payload"],
                    "session_mode": job_data.get("session_mode", "isolated"),
                    "max_duration": job_data.get("max_duration_seconds", 300),
                    "retry_count": job_data.get("retry_count", 0),
                },
            )

        logger.info("Added job: %s (%s)", job_data["name"], job_id)
        return job_id

    async def update_job(self, job_id: str, updates: dict[str, Any]) -> bool:
        """
        Update an existing cron job in the DB and re-register with APScheduler.

        Args:
            job_id: Job identifier.
            updates: Dict of field→value pairs to update.

        Returns:
            True if the job was updated.
        """
        allowed_fields = {
            "name", "schedule", "agent_id", "enabled", "payload_type",
            "payload", "session_mode", "max_duration_seconds", "retry_count",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            return False

        filtered["updated_at"] = func.now()

        stmt = (
            update(EngineCronJob)
            .where(EngineCronJob.id == job_id)
            .values(**filtered)
        )

        async with self._db_engine.begin() as conn:
            result = await conn.execute(stmt)
            if result.rowcount == 0:
                return False

        # Re-register with APScheduler if schedule or enabled changed
        if self._scheduler and ("schedule" in updates or "enabled" in updates):
            # Remove old schedule
            try:
                await self._scheduler.remove_schedule(job_id)
            except Exception:
                pass

            # Re-add if enabled
            if updates.get("enabled", True):
                # Re-read full job from DB
                job = await self.get_job(job_id)
                if job:
                    trigger = parse_schedule(job["schedule"])
                    await self._scheduler.add_schedule(
                        _scheduler_dispatch,
                        trigger=trigger,
                        id=job_id,
                        kwargs={
                            "job_id": job_id,
                            "agent_id": job["agent_id"],
                            "payload_type": job["payload_type"],
                            "payload": job["payload"],
                            "session_mode": job["session_mode"],
                            "max_duration": job["max_duration_seconds"],
                            "retry_count": job["retry_count"],
                        },
                    )

        logger.info("Updated job: %s", job_id)
        return True

    async def remove_job(self, job_id: str) -> bool:
        """Remove a job from the database and APScheduler."""
        async with self._db_engine.begin() as conn:
            result = await conn.execute(
                delete(EngineCronJob)
                .where(EngineCronJob.id == job_id)
            )

        if self._scheduler:
            try:
                await self._scheduler.remove_schedule(job_id)
            except Exception:
                pass

        removed = result.rowcount > 0
        if removed:
            logger.info("Removed job: %s", job_id)
        return removed

    async def trigger_job(self, job_id: str) -> bool:
        """
        Manually trigger a job immediately (run now), regardless of schedule.

        Args:
            job_id: Job identifier.

        Returns:
            True if the job was triggered.
        """
        job = await self.get_job(job_id)
        if not job:
            return False

        # Run in background task
        task = asyncio.create_task(
            self._execute_job(
                job_id=job_id,
                agent_id=job["agent_id"],
                payload_type=job["payload_type"],
                payload=job["payload"],
                session_mode=job["session_mode"],
                max_duration=job["max_duration_seconds"],
                retry_count=0,  # No retry for manual triggers
            )
        )
        self._active_executions[job_id] = task
        task.add_done_callback(lambda _: self._active_executions.pop(job_id, None))

        logger.info("Manually triggered job: %s", job_id)
        return True

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get a single job by ID."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(EngineCronJob)
                .where(EngineCronJob.id == job_id)
            )
            row = result.scalars().first()
            if not row:
                return None
            return {
                "id": row.id, "name": row.name, "schedule": row.schedule,
                "agent_id": row.agent_id, "enabled": row.enabled,
                "payload_type": row.payload_type, "payload": row.payload,
                "session_mode": row.session_mode,
                "max_duration_seconds": row.max_duration_seconds,
                "retry_count": row.retry_count,
                "last_run_at": row.last_run_at, "last_status": row.last_status,
                "last_duration_ms": row.last_duration_ms,
                "last_error": row.last_error, "next_run_at": row.next_run_at,
                "run_count": row.run_count, "success_count": row.success_count,
                "fail_count": row.fail_count,
                "metadata": row.metadata_json,
                "created_at": row.created_at, "updated_at": row.updated_at,
            }

    async def list_jobs(self) -> list[dict[str, Any]]:
        """List all cron jobs with current state."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(EngineCronJob).order_by(EngineCronJob.name)
            )
            rows = result.scalars().all()

        return [
            {
                "id": r.id, "name": r.name, "schedule": r.schedule,
                "agent_id": r.agent_id, "enabled": r.enabled,
                "payload_type": r.payload_type,
                "session_mode": r.session_mode,
                "last_run_at": r.last_run_at, "last_status": r.last_status,
                "last_duration_ms": r.last_duration_ms,
                "last_error": r.last_error, "next_run_at": r.next_run_at,
                "run_count": r.run_count, "success_count": r.success_count,
                "fail_count": r.fail_count,
                "created_at": r.created_at, "updated_at": r.updated_at,
            }
            for r in rows
        ]

    async def get_job_history(
        self, job_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Get execution history for a job from activity_log.

        Cron job executions are logged as activities with
        action='cron_execution' and details.job=<job_id>.
        """
        stmt = (
            select(ActivityLog)
            .where(
                ActivityLog.action == "cron_execution",
                ActivityLog.details["job"].astext == job_id,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "id": str(r.id), "action": r.action, "skill": r.skill,
                "details": r.details, "success": r.success,
                "created_at": r.created_at, "duration_ms": (r.details or {}).get("duration_ms"),
            }
            for r in rows
        ]

    @property
    def is_running(self) -> bool:
        """Whether the scheduler is currently running."""
        return self._running

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status summary."""
        return {
            "running": self._running,
            "active_executions": len(self._active_executions),
            "active_job_ids": list(self._active_executions.keys()),
            "max_concurrent": MAX_CONCURRENT_JOBS,
        }
