"""
Auto-sync cron jobs from aria_mind/cron_jobs.yaml → engine_cron_jobs DB table.

Called at API startup to ensure the DB always reflects the YAML source of truth.
Non-destructive: inserts new jobs, updates changed jobs, never deletes.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml
from sqlalchemy import select

from db import AsyncSessionLocal
from db.models import EngineCronJob

logger = logging.getLogger("aria.cron_sync")


# ── Path resolution ──────────────────────────────────────────────────────────

def _resolve_yaml_path() -> Path:
    """Resolve the cron_jobs.yaml path, supporting Docker and local dev."""
    env_path = os.getenv("CRON_JOBS_YAML")
    if env_path:
        return Path(env_path)

    # Docker default (aria_mind is mounted at /aria_mind in compose)
    docker_path = Path("/aria_mind/cron_jobs.yaml")
    if docker_path.exists():
        return docker_path

    # Local dev fallback (relative to project root)
    local_path = Path(__file__).resolve().parent.parent.parent / "aria_mind" / "cron_jobs.yaml"
    if local_path.exists():
        return local_path

    raise FileNotFoundError(
        "cron_jobs.yaml not found. Set CRON_JOBS_YAML env var or ensure "
        "aria_mind/cron_jobs.yaml exists."
    )


# ── YAML parsing helpers ─────────────────────────────────────────────────────

def _parse_schedule(job: Dict[str, Any]) -> str:
    """Extract schedule string from a YAML job ('every' or 'cron')."""
    if "every" in job:
        return str(job["every"])
    if "cron" in job:
        return str(job["cron"])
    raise ValueError(f"Job '{job.get('name', '?')}' has no 'every' or 'cron' field")


def _estimate_max_duration(name: str) -> int:
    """Estimate max duration in seconds based on job type."""
    heavy = {"weekly_summary", "six_hour_review", "daily_reflection",
             "morning_checkin", "memory_consolidation"}
    light = {"health_check", "memory_bridge"}
    if name in heavy:
        return 600
    if name == "db_maintenance":
        return 300
    if name in light:
        return 60
    return 300


def _transform_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a YAML job dict into column values for EngineCronJob."""
    name = job["name"]
    return {
        "id": name,
        "name": name.replace("_", " ").title(),
        "schedule": _parse_schedule(job),
        "agent_id": job.get("agent", "aria"),
        "enabled": job.get("enabled", True),
        "payload_type": "prompt",
        "payload": job.get("text", ""),
        "session_mode": job.get("session", "isolated"),
        "max_duration_seconds": int(job.get("max_duration_seconds", _estimate_max_duration(name))),
        "retry_count": 1 if job.get("enabled", True) else 0,
    }


# ── Core sync function ──────────────────────────────────────────────────────

async def sync_cron_jobs_from_yaml() -> Dict[str, int]:
    """
    Read cron_jobs.yaml and sync into the engine_cron_jobs DB table.

    - INSERT jobs present in YAML but missing from DB.
    - UPDATE schedule/payload if they changed (preserves runtime state).
    - SKIP jobs that are already up-to-date.
    - Never DELETE DB rows missing from YAML.

    Returns:
        {"inserted": N, "updated": N, "unchanged": N}
    """
    yaml_path = _resolve_yaml_path()
    logger.info("Loading cron jobs from %s", yaml_path)

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw_jobs: List[Dict[str, Any]] = data.get("jobs", [])
    if not raw_jobs:
        logger.warning("No jobs found in %s", yaml_path)
        return {"inserted": 0, "updated": 0, "unchanged": 0}

    transformed = [_transform_job(j) for j in raw_jobs]
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Fetch all existing cron jobs in one query
            result = await session.execute(select(EngineCronJob))
            existing = {row.id: row for row in result.scalars().all()}

            for job_data in transformed:
                job_id = job_data["id"]
                existing_row = existing.get(job_id)

                if existing_row is None:
                    # INSERT new job
                    new_job = EngineCronJob(**job_data)
                    session.add(new_job)
                    stats["inserted"] += 1
                    logger.info("Inserted cron job: %s", job_id)
                else:
                    # Check if schedule or payload changed
                    changed = False
                    if existing_row.schedule != job_data["schedule"]:
                        changed = True
                    if existing_row.payload != job_data["payload"]:
                        changed = True
                    if existing_row.agent_id != job_data["agent_id"]:
                        changed = True
                    if existing_row.enabled != job_data["enabled"]:
                        changed = True
                    if existing_row.session_mode != job_data["session_mode"]:
                        changed = True
                    if existing_row.max_duration_seconds != job_data["max_duration_seconds"]:
                        changed = True
                    if existing_row.retry_count != job_data["retry_count"]:
                        changed = True

                    if changed:
                        # UPDATE only config fields — preserve runtime state
                        existing_row.name = job_data["name"]
                        existing_row.schedule = job_data["schedule"]
                        existing_row.agent_id = job_data["agent_id"]
                        existing_row.enabled = job_data["enabled"]
                        existing_row.payload_type = job_data["payload_type"]
                        existing_row.payload = job_data["payload"]
                        existing_row.session_mode = job_data["session_mode"]
                        existing_row.max_duration_seconds = job_data["max_duration_seconds"]
                        existing_row.retry_count = job_data["retry_count"]
                        existing_row.updated_at = datetime.now(timezone.utc)
                        stats["updated"] += 1
                        logger.info("Updated cron job: %s", job_id)
                    else:
                        stats["unchanged"] += 1
                        logger.debug("Unchanged cron job: %s", job_id)

    logger.info(
        "Cron sync complete: %d inserted, %d updated, %d unchanged",
        stats["inserted"], stats["updated"], stats["unchanged"],
    )
    return stats
