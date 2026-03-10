"""
Operational endpoints — rate limits, heartbeat, performance, tasks,
schedule, jobs, API key rotations.
"""

import json
import json as json_lib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import ARIA_JOBS_PATH
from db.models import (
    ApiKeyRotation,
    EngineCronJob,
    HeartbeatLog,
    PendingComplexTask,
    PerformanceLog,
    RateLimit,
    ScheduleTick,
    ScheduledJob,
)
from deps import get_db
from schemas.requests import (
    RateLimitCheck,
    RateLimitIncrement,
    CreateKeyRotation,
    CreateHeartbeat,
    CreatePerformanceReview,
    CreateTask,
    PurgeTasks,
    UpdateTask,
)

router = APIRouter(tags=["Operations"])
logger = logging.getLogger("aria.api.operations")

OPEN_TASK_STATUSES = {"pending", "in_progress"}
TERMINAL_TASK_STATUSES = {"done", "completed", "failed", "cancelled"}
NON_PERSISTENT_HEARTBEAT_STATUSES = {"test", "audit"}
NON_PERSISTENT_HEARTBEAT_JOB_PREFIXES = (
    "test-heartbeat",
    "route-audit-heartbeat",
    "api-client-audit-heartbeat",
)


def _normalize_task_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().lower()
    return normalized or None


def _expand_task_status_filters(statuses: list[str]) -> list[str]:
    expanded: set[str] = set()
    for raw in statuses:
        normalized = _normalize_task_status(raw)
        if not normalized:
            continue
        if normalized == "open":
            expanded.update(OPEN_TASK_STATUSES)
        elif normalized == "terminal":
            expanded.update(TERMINAL_TASK_STATUSES)
        else:
            expanded.add(normalized)
    return sorted(expanded)


def _should_persist_heartbeat(status: str | None, job_name: str | None) -> bool:
    if os.getenv("ARIA_PERSIST_TEST_HEARTBEATS") == "1":
        return True

    normalized_status = (status or "").strip().lower()
    normalized_job_name = (job_name or "").strip().lower()

    if normalized_status in NON_PERSISTENT_HEARTBEAT_STATUSES:
        return False

    return not any(
        normalized_job_name.startswith(prefix)
        for prefix in NON_PERSISTENT_HEARTBEAT_JOB_PREFIXES
    )


# ──────────────────────────────────────────────────────────────────────────────
# Rate Limits
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/rate-limits")
async def get_rate_limits(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RateLimit).order_by(RateLimit.updated_at.desc())
    )
    rows = result.scalars().all()
    return {
        "rate_limits": [
            {
                "id": str(r.id),
                "skill": r.skill,
                "last_action": r.last_action.isoformat() if r.last_action else None,
                "last_post": r.last_post.isoformat() if r.last_post else None,
                "action_count": r.action_count,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/rate-limits/check")
async def check_rate_limit(body: RateLimitCheck, db: AsyncSession = Depends(get_db)):
    skill = body.skill
    max_actions = body.max_actions
    window_seconds = body.window_seconds

    result = await db.execute(select(RateLimit).where(RateLimit.skill == skill))
    rl = result.scalar_one_or_none()
    if not rl:
        return {"allowed": True, "remaining": max_actions, "window_age": 0}

    window_age = (datetime.now(timezone.utc) - rl.window_start).total_seconds() if rl.window_start else 0
    if window_age > window_seconds:
        rl.action_count = 0
        await db.commit()
        return {"allowed": True, "remaining": max_actions, "window_age": 0}

    count = rl.action_count or 0
    remaining = max(0, max_actions - count)
    return {
        "allowed": count < max_actions,
        "remaining": remaining,
        "window_age": window_age,
        "action_count": count,
    }


@router.post("/rate-limits/increment")
async def increment_rate_limit(body: RateLimitIncrement, db: AsyncSession = Depends(get_db)):
    skill = body.skill
    action_type = body.action_type

    now = datetime.now(timezone.utc)
    if action_type == "post":
        stmt = pg_insert(RateLimit).values(
            skill=skill, last_post=now, action_count=1,
            window_start=now, updated_at=now,
        ).on_conflict_do_update(
            index_elements=["skill"],
            set_={"last_post": now, "action_count": RateLimit.action_count + 1, "updated_at": now},
        )
    else:
        stmt = pg_insert(RateLimit).values(
            skill=skill, last_action=now, action_count=1,
            window_start=now, updated_at=now,
        ).on_conflict_do_update(
            index_elements=["skill"],
            set_={"last_action": now, "action_count": RateLimit.action_count + 1, "updated_at": now},
        )
    await db.execute(stmt)
    await db.commit()
    return {"incremented": True, "skill": skill}


# ──────────────────────────────────────────────────────────────────────────────
# API Key Rotations
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api-key-rotations")
async def get_api_key_rotations(
    limit: int = 50,
    service: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApiKeyRotation).order_by(ApiKeyRotation.rotated_at.desc()).limit(limit)
    if service:
        stmt = stmt.where(ApiKeyRotation.service == service)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "rotations": [
            {
                "id": str(r.id),
                "service": r.service,
                "rotated_at": r.rotated_at.isoformat() if r.rotated_at else None,
                "reason": r.reason,
                "rotated_by": r.rotated_by,
                "metadata": r.metadata_json or {},
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/api-key-rotations")
async def log_api_key_rotation(body: CreateKeyRotation, db: AsyncSession = Depends(get_db)):
    rotation = ApiKeyRotation(
        id=uuid.uuid4(),
        service=body.service,
        reason=body.reason,
        rotated_by=body.rotated_by,
        metadata_json=body.metadata,
    )
    db.add(rotation)
    await db.commit()
    return {"id": str(rotation.id), "created": True}


# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/heartbeat")
async def get_heartbeats(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HeartbeatLog).order_by(HeartbeatLog.created_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return {"heartbeats": [h.to_dict() for h in rows], "count": len(rows)}


@router.post("/heartbeat")
async def create_heartbeat(body: CreateHeartbeat, db: AsyncSession = Depends(get_db)):
    normalized_details = body.details if isinstance(body.details, dict) else {"raw": body.details}
    heartbeat_id = uuid.uuid4()

    if not _should_persist_heartbeat(body.status, body.job_name):
        logger.info(
            "Skipping persistence for non-production heartbeat job_name=%s status=%s",
            body.job_name,
            body.status,
        )
        return {"id": str(heartbeat_id), "created": True, "persisted": False}

    hb = HeartbeatLog(
        id=heartbeat_id,
        beat_number=body.beat_number,
        job_name=body.job_name,
        status=body.status,
        details=normalized_details,
        executed_at=body.executed_at,
        duration_ms=body.duration_ms,
    )
    db.add(hb)
    await db.commit()
    return {"id": str(hb.id), "created": True, "persisted": True}


@router.get("/heartbeat/latest")
async def get_latest_heartbeat(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HeartbeatLog).order_by(HeartbeatLog.created_at.desc()).limit(1)
    )
    hb = result.scalar_one_or_none()
    if not hb:
        return {"error": "No heartbeats found"}
    return hb.to_dict()


# ──────────────────────────────────────────────────────────────────────────────
# Performance
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/performance")
async def get_performance_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PerformanceLog).order_by(PerformanceLog.created_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return {"logs": [p.to_dict() for p in rows], "count": len(rows)}


@router.post("/performance")
async def create_performance_log(body: CreatePerformanceReview, db: AsyncSession = Depends(get_db)):
    log = PerformanceLog(
        review_period=body.review_period,
        successes=body.successes,
        failures=body.failures,
        improvements=body.improvements,
    )
    db.add(log)
    await db.commit()
    return {"created": True}


# ──────────────────────────────────────────────────────────────────────────────
# Pending Complex Tasks
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/tasks")
async def get_pending_tasks(
    status: str | None = None, db: AsyncSession = Depends(get_db)
):
    stmt = select(PendingComplexTask).order_by(PendingComplexTask.created_at.desc())
    normalized_status = _normalize_task_status(status)
    if normalized_status:
        if normalized_status == "open":
            stmt = stmt.where(PendingComplexTask.status.in_(sorted(OPEN_TASK_STATUSES)))
        elif normalized_status == "terminal":
            stmt = stmt.where(PendingComplexTask.status.in_(sorted(TERMINAL_TASK_STATUSES)))
        else:
            stmt = stmt.where(PendingComplexTask.status == normalized_status)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"tasks": [t.to_dict() for t in rows], "count": len(rows)}


@router.post("/tasks")
async def create_pending_task(body: CreateTask, db: AsyncSession = Depends(get_db)):
    normalized_status = _normalize_task_status(body.status) or "pending"
    task = PendingComplexTask(
        task_id=body.task_id or f"task-{str(uuid.uuid4())[:8]}",
        task_type=body.task_type,
        description=body.description,
        agent_type=body.agent_type,
        priority=body.priority,
        status=normalized_status,
    )
    db.add(task)
    await db.commit()
    return {"task_id": task.task_id, "created": True}


@router.patch("/tasks/{task_id}")
async def update_pending_task(
    task_id: str, body: UpdateTask, db: AsyncSession = Depends(get_db)
):
    values: dict = {}

    normalized_status = _normalize_task_status(body.status)
    if normalized_status is not None:
        values["status"] = normalized_status
        if normalized_status in TERMINAL_TASK_STATUSES:
            values["completed_at"] = text("NOW()")
        elif normalized_status in OPEN_TASK_STATUSES:
            values["completed_at"] = None

    if body.result is not None:
        values["result"] = body.result

    if not values:
        raise HTTPException(status_code=400, detail="No task updates provided")

    result = await db.execute(
        update(PendingComplexTask).where(PendingComplexTask.task_id == task_id).values(**values)
    )
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    return {"updated": True, "task_id": task_id}


@router.delete("/tasks/{task_id}")
async def delete_pending_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        delete(PendingComplexTask).where(PendingComplexTask.task_id == task_id)
    )
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    return {"deleted": True, "task_id": task_id}


@router.post("/tasks/purge")
async def purge_pending_tasks(body: PurgeTasks, db: AsyncSession = Depends(get_db)):
    stmt = delete(PendingComplexTask)
    task_ids = [task_id.strip() for task_id in body.task_ids if task_id and task_id.strip()]
    filters = []

    if body.include_all:
        statuses = []
    elif task_ids:
        statuses = []
        filters.append(PendingComplexTask.task_id.in_(task_ids))
    else:
        statuses = _expand_task_status_filters(body.statuses or sorted(TERMINAL_TASK_STATUSES))
        if not statuses:
            raise HTTPException(status_code=400, detail="No purge targets provided")
        filters.append(PendingComplexTask.status.in_(statuses))

    if body.older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)
        filters.append(PendingComplexTask.created_at < cutoff)

    for task_filter in filters:
        stmt = stmt.where(task_filter)

    result = await db.execute(stmt)
    await db.commit()
    return {
        "purged": result.rowcount or 0,
        "task_ids": task_ids,
        "statuses": statuses,
        "include_all": body.include_all,
        "older_than_days": body.older_than_days,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Schedule
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/schedule")
async def get_schedule(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ScheduleTick).where(ScheduleTick.id == 1))
    tick = result.scalar_one_or_none()
    return tick.to_dict() if tick else {"error": "No schedule found"}


@router.post("/schedule/tick")
async def manual_tick(db: AsyncSession = Depends(get_db)):
    """Manual heartbeat tick — updates schedule_tick from engine cron jobs."""
    # Read stats from engine cron jobs (DB-backed, not legacy jobs.json)
    result = await db.execute(select(EngineCronJob))
    jobs = result.scalars().all()

    jobs_total = len(jobs)
    jobs_successful = 0
    jobs_failed = 0
    last_job_name = None
    last_job_status = None
    next_job_at = None
    latest_run = None

    for job in jobs:
        if job.last_status == "ok":
            jobs_successful += 1
        elif job.last_status == "error":
            jobs_failed += 1
        if job.last_run_at:
            if latest_run is None or job.last_run_at > latest_run:
                latest_run = job.last_run_at
                last_job_name = job.name
                last_job_status = job.last_status
        if job.next_run_at:
            if next_job_at is None or job.next_run_at < next_job_at:
                next_job_at = job.next_run_at

    now = datetime.now(timezone.utc)
    await db.execute(
        update(ScheduleTick).where(ScheduleTick.id == 1).values(
            last_tick=now, tick_count=ScheduleTick.tick_count + 1,
            jobs_total=jobs_total, jobs_successful=jobs_successful,
            jobs_failed=jobs_failed, last_job_name=last_job_name,
            last_job_status=last_job_status, next_job_at=next_job_at,
            updated_at=now,
        )
    )
    await db.commit()
    return {"ticked": True, "at": now.isoformat(), "jobs_total": jobs_total}


# ──────────────────────────────────────────────────────────────────────────────
# Scheduled Jobs — now powered by aria_engine.cron_jobs (EngineCronJob ORM)
# ──────────────────────────────────────────────────────────────────────────────

def _cron_job_to_dict(job: EngineCronJob) -> dict:
    """Serialize an EngineCronJob to the format the heartbeat frontend expects."""
    return {
        "id": job.id,
        "agent_id": job.agent_id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule_kind": "cron",
        "schedule_expr": job.schedule,
        "session_target": job.session_mode,
        "wake_mode": None,
        "payload_kind": job.payload_type,
        "payload_text": job.payload[:200] + "..." if job.payload and len(job.payload) > 200 else job.payload,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
        "last_status": job.last_status,
        "last_duration_ms": job.last_duration_ms,
        "run_count": job.run_count,
        "success_count": job.success_count,
        "fail_count": job.fail_count,
        "max_duration_seconds": job.max_duration_seconds,
    }


@router.get("/jobs")
async def get_scheduled_jobs(db: AsyncSession = Depends(get_db)):
    """List all engine cron jobs from aria_engine.cron_jobs."""
    result = await db.execute(select(EngineCronJob).order_by(EngineCronJob.name))
    rows = result.scalars().all()
    return {"jobs": [_cron_job_to_dict(j) for j in rows], "count": len(rows)}


@router.get("/jobs/live")
async def get_jobs_live(db: AsyncSession = Depends(get_db)):
    """Live cron jobs from DB (replaces legacy jobs.json file read)."""
    result = await db.execute(select(EngineCronJob).order_by(EngineCronJob.name))
    rows = result.scalars().all()
    return {"jobs": [_cron_job_to_dict(j) for j in rows], "count": len(rows), "source": "db"}


@router.get("/jobs/{job_id}")
async def get_scheduled_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single cron job by ID."""
    result = await db.execute(select(EngineCronJob).where(EngineCronJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _cron_job_to_dict(job)


@router.post("/jobs/sync")
async def sync_jobs(db: AsyncSession = Depends(get_db)):
    """Re-sync cron jobs from cron_jobs.yaml → aria_engine.cron_jobs."""
    try:
        from cron_sync import sync_cron_jobs_from_yaml
        stats = await sync_cron_jobs_from_yaml()
        total = stats.get("inserted", 0) + stats.get("updated", 0) + stats.get("unchanged", 0)
        return {"synced": total, "source": "cron_jobs.yaml", **stats}
    except Exception as e:
        logger.warning("Operation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {e}")
    except Exception as e:
        logger.warning("Operation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
