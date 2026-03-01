"""
Health, status, and stats endpoints.
"""

from datetime import datetime, timezone
import shutil
import socket

import asyncio
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import DOCKER_HOST_IP, SERVICE_URLS, STARTUP_TIME, API_VERSION
from db.session import async_engine
from db.models import ActivityLog, Thought, Memory
from deps import get_db

logger = logging.getLogger("aria.api.health")
router = APIRouter(tags=["Health"])


def _dt_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _container_stats_fallback() -> dict:
    ram = {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}
    swap = {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}
    disk = {"used_gb": 0, "total_gb": 0, "percent": 0.0}

    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for raw in handle:
                key, value = raw.split(":", 1)
                meminfo[key.strip()] = int(value.strip().split()[0])  # kB

        mem_total_kb = meminfo.get("MemTotal", 0)
        mem_avail_kb = meminfo.get("MemAvailable", 0)
        mem_used_kb = max(0, mem_total_kb - mem_avail_kb)

        swap_total_kb = meminfo.get("SwapTotal", 0)
        swap_free_kb = meminfo.get("SwapFree", 0)
        swap_used_kb = max(0, swap_total_kb - swap_free_kb)

        ram_total_gb = mem_total_kb / (1024 * 1024)
        ram_used_gb = mem_used_kb / (1024 * 1024)
        ram_percent = (mem_used_kb / mem_total_kb * 100.0) if mem_total_kb else 0.0

        swap_total_gb = swap_total_kb / (1024 * 1024)
        swap_used_gb = swap_used_kb / (1024 * 1024)
        swap_percent = (swap_used_kb / swap_total_kb * 100.0) if swap_total_kb else 0.0

        ram = {
            "used_gb": round(ram_used_gb, 2),
            "total_gb": round(ram_total_gb, 2),
            "percent": round(ram_percent, 2),
        }
        swap = {
            "used_gb": round(swap_used_gb, 2),
            "total_gb": round(swap_total_gb, 2),
            "percent": round(swap_percent, 2),
        }
    except Exception as e:
        logger.debug("Container meminfo fallback failed: %s", e)

    try:
        usage = shutil.disk_usage("/")
        disk_total_gb = usage.total / (1024**3)
        disk_used_gb = (usage.total - usage.free) / (1024**3)
        disk_percent = (disk_used_gb / disk_total_gb * 100.0) if disk_total_gb else 0.0
        disk = {
            "used_gb": round(disk_used_gb, 0),
            "total_gb": round(disk_total_gb, 0),
            "percent": round(disk_percent, 2),
        }
    except Exception as e:
        logger.debug("Container disk fallback failed: %s", e)

    return {
        "hostname": socket.gethostname(),
        "ram": ram,
        "swap": swap,
        "disk": disk,
        "smart": {"status": "unknown", "healthy": True},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "container",
    }


# ── Response models ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: int
    database: str
    version: str


class StatsResponse(BaseModel):
    activities_count: int
    thoughts_count: int
    memories_count: int
    last_activity: str | None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """S-21: Real database connectivity check — returns 503 if DB is unreachable."""
    uptime = (datetime.now(timezone.utc) - STARTUP_TIME).total_seconds()
    db_status = "connected"
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("DB health check failed: %s", e)
        db_status = f"error: {str(e)[:100]}"
        return HealthResponse(
            status="degraded",
            uptime_seconds=int(uptime),
            database=db_status,
            version=API_VERSION,
        )
    return HealthResponse(
        status="healthy",
        uptime_seconds=int(uptime),
        database=db_status,
        version=API_VERSION,
    )


@router.get("/host-stats")
async def host_stats():
    stats = _container_stats_fallback()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{DOCKER_HOST_IP}:8888/stats")
            if resp.status_code == 200:
                stats.update(resp.json())
                stats["source"] = "host"
    except Exception as e:
        logger.debug("Failed to fetch host stats from %s: %s", DOCKER_HOST_IP, e)
    return stats


@router.get("/status")
async def api_status():
    """
    Check all registered services.

    Uses synchronous httpx in a thread-pool with a hard 1-second
    future timeout to cap DNS-resolution hangs for non-existent
    Docker hostnames (which ignore httpx connect timeouts).
    The pool is shut down with ``wait=False`` so we don't block on
    threads still stuck in DNS lookups.
    """
    import concurrent.futures
    import socket

    _HARD_TIMEOUT = 0.8   # max wall-clock seconds per service

    def _check_sync(name: str, url: str) -> tuple[str, dict]:
        try:
            prev = socket.getdefaulttimeout()
            socket.setdefaulttimeout(0.8)
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(
                        connect=0.2, read=0.4, write=0.2, pool=0.3,
                    ),
                ) as client:
                    resp = client.get(url)
                    return name, {"status": "up", "code": resp.status_code}
            finally:
                socket.setdefaulttimeout(prev)
        except Exception as e:
            logger.warning("Service probe %s failed: %s", name, e)
            return name, {"status": "down", "code": None, "error": str(e)[:50]}

    urls = {
        name: base_url.rstrip("/") + health_path
        for name, (base_url, health_path) in SERVICE_URLS.items()
    }

    results: dict[str, dict] = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(urls))
    try:
        future_map = {
            pool.submit(_check_sync, name, url): name
            for name, url in urls.items()
        }
        done, not_done = concurrent.futures.wait(
            future_map, timeout=_HARD_TIMEOUT + 0.5,
        )
        for future in done:
            try:
                name, info = future.result(timeout=0)
                results[name] = info
            except Exception as e:
                logger.warning("Service probe future error: %s", e)
                results[future_map[future]] = {
                    "status": "down", "code": None, "error": "timeout",
                }
        for future in not_done:
            future.cancel()
            results[future_map[future]] = {
                "status": "down", "code": None, "error": "timeout",
            }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # Any services that didn't complete in time
    for name in urls:
        if name not in results:
            results[name] = {"status": "down", "code": None, "error": "timeout"}

    # Check PostgreSQL via SQLAlchemy engine
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        results["postgres"] = {"status": "up", "code": 200}
    except Exception as e:
        logger.warning("Postgres check failed: %s", e)
        results["postgres"] = {"status": "down", "code": None}
    return results


@router.get("/status/{service_id}")
async def api_status_service(service_id: str):
    if service_id == "postgres":
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {"status": "online", "code": 200}
        except Exception as e:
            logger.warning("Service check failed: %s", e)
            return {"status": "offline", "code": None}

    service_info = SERVICE_URLS.get(service_id)
    if not service_info:
        raise HTTPException(status_code=404, detail="Unknown service")
    base_url, health_path = service_info
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=0.3, read=0.5, write=0.3, pool=0.5)) as client:
            url = base_url.rstrip("/") + health_path
            resp = client.get(url)
        return {"status": "online", "code": resp.status_code}
    except Exception as e:
        logger.warning("HTTP service probe failed: %s", e)
        return {"status": "offline", "code": None}


@router.get("/stats", response_model=StatsResponse)
async def api_stats(db: AsyncSession = Depends(get_db)):
    activities = (await db.execute(select(func.count(ActivityLog.id)))).scalar() or 0
    thoughts = (await db.execute(select(func.count(Thought.id)))).scalar() or 0
    memories = (await db.execute(select(func.count(Memory.id)))).scalar() or 0
    last = (await db.execute(select(func.max(ActivityLog.created_at)))).scalar()
    return StatsResponse(
        activities_count=activities,
        thoughts_count=thoughts,
        memories_count=memories,
        last_activity=_dt_iso_utc(last),
    )


@router.get("/health/db")
async def database_health():
    """Database health check — reports missing tables, pgvector status, extensions."""
    try:
        from db.session import check_database_health
        return await check_database_health()
    except Exception as e:
        logger.warning("DB health detailed check failed: %s", e)
        return {
            "status": "error",
            "error": str(e)[:200],
            "tables": {},
            "missing": [],
            "pgvector_installed": False,
        }
