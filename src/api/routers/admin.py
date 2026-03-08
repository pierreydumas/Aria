"""
Admin endpoints — service control + soul file access + DB maintenance.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import ARIA_ADMIN_TOKEN, SERVICE_CONTROL_ENABLED
from db.session import _validate_table_name
from deps import get_db

router = APIRouter(tags=["Admin"])
# Separate router for read-only file browser endpoints — mounted with
# standard API key auth (not admin) so the dashboard can access them
# when requests arrive via Traefik (which bypasses Flask's proxy).
files_router = APIRouter(tags=["Files"])
logger = logging.getLogger("aria.api.admin")

VACUUM_TABLES = ["activity_log", "model_usage", "heartbeat_log", "thoughts"]


class SoulFileUpdate(BaseModel):
    content: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _service_cmd_env(service_id: str, action: str) -> str:
    normalized_service = service_id.upper().replace("-", "_")
    normalized_action = action.upper().replace("-", "_")
    return f"ARIA_SERVICE_CMD_{normalized_service}_{normalized_action}"


async def _run_docker_command(command: str) -> dict | None:
    """Execute a docker container control command via docker-socket-proxy (S-100)."""
    tokens = command.strip().split()
    if len(tokens) < 3 or tokens[0] != "docker":
        return None
    action, target = tokens[1], tokens[2]
    if action not in {"restart", "stop", "start"}:
        return None
    # S-100: Use docker-socket-proxy instead of raw Docker socket
    docker_host = os.environ.get("DOCKER_HOST", "http://docker-socket-proxy:2375")
    endpoint = f"/containers/{target}/{action}"
    async with httpx.AsyncClient(base_url=docker_host, timeout=30.0) as client:
        resp = await client.post(endpoint)
        if resp.status_code in {204, 200}:
            return {"status": "ok", "code": 0, "stdout": "", "stderr": ""}
        return {
            "status": "error", "code": resp.status_code,
            "stdout": "", "stderr": resp.text[:2000],
        }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/admin/services/{service_id}/{action}")
async def api_service_control(service_id: str, action: str, request: Request):
    if not SERVICE_CONTROL_ENABLED:
        raise HTTPException(status_code=403, detail="Service control disabled")
    if not ARIA_ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token not configured")
    token = request.headers.get("X-Admin-Token", "")
    if token != ARIA_ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if action not in {"restart", "stop", "start"}:
        raise HTTPException(status_code=400, detail="Invalid action")

    env_key = _service_cmd_env(service_id, action)
    command = os.getenv(env_key)
    if not command:
        raise HTTPException(
            status_code=400, detail=f"No command configured for {service_id}:{action}"
        )
    try:
        docker_result = await _run_docker_command(command)
        if docker_result is not None:
            return docker_result
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "code": proc.returncode,
            "stdout": (stdout or b"")[-2000:].decode("utf-8", errors="ignore"),
            "stderr": (stderr or b"")[-2000:].decode("utf-8", errors="ignore"),
        }
    except Exception as exc:
        logger.warning("Admin operation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@files_router.get("/soul/{filename}")
async def read_soul_file(filename: str):
    allowed = [
        "SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md",
        "HEARTBEAT.md", "BOOTSTRAP.md",
        "GOALS.md", "SECURITY.md", "MEMORY.md", "SKILLS.md",
        "TOOLS.md", "AWAKENING.md", "ORCHESTRATION.md",
    ]
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Soul file not found")
    soul_path = f"/aria_mind/{filename}"
    try:
        with open(soul_path, "r", encoding="utf-8") as f:
            return {"filename": filename, "content": f.read()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Soul file not found")


@files_router.post("/soul/{filename}")
async def write_soul_file(filename: str, body: SoulFileUpdate):
    allowed = ["HEARTBEAT.md"]
    if filename not in allowed:
        raise HTTPException(status_code=403, detail="Write not allowed for this soul file")

    soul_path = f"/aria_mind/{filename}"
    try:
        with open(soul_path, "r", encoding="utf-8"):
            pass
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Soul file not found")

    try:
        with open(soul_path, "w", encoding="utf-8") as f:
            f.write(body.content)
        stat = os.stat(soul_path)
        return {
            "success": True,
            "filename": filename,
            "path": filename,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning("Soul file write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to write soul file: {e}")


# ── File Browsers (aria_mind & aria_memories) ────────────────────────────────

def _list_tree(base: str, rel: str = "") -> list[dict]:
    """Recursively list files/dirs under *base*, returning a flat list."""
    full = os.path.join(base, rel) if rel else base
    if not os.path.isdir(full):
        return []
    entries: list[dict] = []
    try:
        items = sorted(os.listdir(full))
    except PermissionError:
        return []
    for name in items:
        if name.startswith(".") or name == "__pycache__":
            continue
        child_rel = f"{rel}/{name}" if rel else name
        child_full = os.path.join(full, name)
        if os.path.isdir(child_full):
            entries.append({"path": child_rel, "type": "dir"})
            entries.extend(_list_tree(base, child_rel))
        else:
            try:
                size = os.path.getsize(child_full)
                mtime = os.path.getmtime(child_full)
            except OSError:
                size, mtime = 0, 0
            entries.append({"path": child_rel, "type": "file", "size": size, "mtime": mtime})
    return entries


_SAFE_EXTENSIONS = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".sh", ".toml",
    ".cfg", ".ini", ".log", ".csv", ".html", ".css", ".js",
}

_FILE_ROOTS = {
    "mind": "/aria_mind",
    "memories": "/aria_memories",
    "agents": "/aria_agents",
    "souvenirs": "/aria_souvenirs",
}


def _get_root_path(kind: str) -> str:
    root = _FILE_ROOTS.get(kind)
    if not root:
        raise HTTPException(status_code=404, detail="Unknown file root")
    return root


def _read_root_file(kind: str, path: str) -> dict:
    root = _get_root_path(kind)
    safe = os.path.normpath(path)
    if ".." in safe:
        raise HTTPException(status_code=400, detail="Invalid path")
    full = f"{root}/{safe}"
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="File not found")
    ext = os.path.splitext(full)[1].lower()
    if ext not in _SAFE_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Cannot render {ext} files")
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return {"path": safe, "content": f.read()}
    except Exception as e:
        logger.warning("Health check proxy failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@files_router.get("/admin/files/mind")
async def list_mind_files():
    """List all files under /aria_mind (read-only)."""
    return _list_tree(_get_root_path("mind"))


@files_router.get("/admin/files/memories")
async def list_memories_files():
    """List all files under /aria_memories (read-only)."""
    return _list_tree(_get_root_path("memories"))


@files_router.get("/admin/files/agents")
async def list_agents_files():
    """List all files under /aria_agents (read-only)."""
    return _list_tree(_get_root_path("agents"))


@files_router.get("/admin/files/souvenirs")
async def list_souvenirs_files():
    """List all files under /aria_souvenirs (read-only)."""
    return _list_tree(_get_root_path("souvenirs"))


@files_router.get("/admin/files/mind/{path:path}")
async def read_mind_file(path: str):
    """Read a text file from /aria_mind."""
    return _read_root_file("mind", path)


@files_router.get("/admin/files/memories/{path:path}")
async def read_memories_file(path: str):
    """Read a text file from /aria_memories."""
    return _read_root_file("memories", path)


@files_router.get("/admin/files/agents/{path:path}")
async def read_agents_file(path: str):
    """Read a text file from /aria_agents."""
    return _read_root_file("agents", path)


@files_router.get("/admin/files/souvenirs/{path:path}")
async def read_souvenirs_file(path: str):
    """Read a text file from /aria_souvenirs."""
    return _read_root_file("souvenirs", path)


# ── DB Maintenance ───────────────────────────────────────────────────────────

@router.post("/maintenance")
async def run_maintenance(db: AsyncSession = Depends(get_db)):
    """Run VACUUM ANALYZE on high-write tables."""
    results = {}
    for table in VACUUM_TABLES:
        try:
            # Validate table name to prevent SQL injection (defense in depth)
            table_safe = _validate_table_name(table)
            # VACUUM cannot run in a transaction, use ANALYZE instead
            await db.execute(text(f"ANALYZE {table_safe}"))
            results[table] = "analyzed"
        except Exception as e:
            logger.warning("Data integrity check error for %s: %s", table, e)
            results[table] = f"error: {e}"
    return {"maintenance": "complete", "tables": results}


@router.get("/table-stats")
async def table_stats(db: AsyncSession = Depends(get_db)):
    """Get dead tuple counts for high-write tables."""
    result = await db.execute(text("""
        SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
        FROM pg_stat_user_tables
        WHERE relname = ANY(:tables)
        ORDER BY n_dead_tup DESC
    """), {"tables": VACUUM_TABLES})
    rows = result.all()
    return [
        {"table": r.relname, "live_tuples": r.n_live_tup, "dead_tuples": r.n_dead_tup,
         "last_vacuum": r.last_vacuum.isoformat() if r.last_vacuum else None}
        for r in rows
    ]
