"""
Artifact File API — read/write/list file-based memory artifacts in aria_memories/.

Exposes the MemoryManager's file artifact system as REST endpoints so that
Aria can save research, diary entries, plans, and other persistent files
via the API layer (respecting the 5-layer architecture constraint).
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["Artifacts"])
logger = logging.getLogger("aria.api.artifacts")

# Writable directory — aria_memories is the ONLY writable path
ARIA_MEMORIES_PATH = Path(os.environ.get("ARIA_MEMORIES_PATH", "/aria_memories"))
if not ARIA_MEMORIES_PATH.exists():
    # Local dev fallback
    _local = Path(__file__).resolve().parent.parent.parent.parent / "aria_memories"
    if _local.exists():
        ARIA_MEMORIES_PATH = _local

# Allowed categories (whitelist — same as MemoryManager.ALLOWED_CATEGORIES)
ALLOWED_CATEGORIES = frozenset({
    "archive", "bugs", "deep", "deliveries", "drafts", "exports",
    "income_ops", "knowledge", "logs", "medium", "memory", "moltbook",
    "plans", "research", "sandbox", "skills", "specs", "surface",
    "tickets", "work",
})


def _validate_path_segment(segment: str) -> None:
    """Guard against path traversal attacks."""
    if ".." in segment or segment.startswith("/") or segment.startswith("\\"):
        raise HTTPException(status_code=400, detail=f"Invalid path segment: {segment}")


# ── Write Artifact ───────────────────────────────────────────────────────────

class ArtifactWriteRequest(BaseModel):
    content: str
    filename: str
    category: str = "memory"
    subfolder: str | None = None


@router.post("/artifacts")
async def write_artifact(body: ArtifactWriteRequest):
    """Write a file artifact to aria_memories/<category>/<subfolder>/<filename>."""
    if body.category not in ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{body.category}'. Allowed: {sorted(ALLOWED_CATEGORIES)}",
        )
    _validate_path_segment(body.category)
    _validate_path_segment(body.filename)
    if body.subfolder:
        _validate_path_segment(body.subfolder)

    folder = ARIA_MEMORIES_PATH / body.category
    if body.subfolder:
        folder = folder / body.subfolder

    try:
        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / body.filename

        # Validate JSON payloads when filename ends with .json
        if body.filename.lower().endswith(".json"):
            try:
                json.loads(body.content)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid JSON content for '{body.filename}': {exc.msg}",
                )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body.content)

        rel_path = str(filepath.relative_to(ARIA_MEMORIES_PATH))
        return {
            "success": True,
            "path": rel_path,
            "size": len(body.content),
            "category": body.category,
            "filename": body.filename,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Artifact write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to write artifact: {e}")


# ── Read Artifact ────────────────────────────────────────────────────────────

@router.get("/artifacts/{category}/{filename:path}")
async def read_artifact(category: str, filename: str):
    """Read a file artifact from aria_memories/<category>/<filename>.

    Falls back to aria_memories/<filename> (root level) so that root files
    like HEARTBEAT.md are reachable via any category prefix.
    """
    _validate_path_segment(category)

    filepath = ARIA_MEMORIES_PATH / category / filename
    if not filepath.exists():
        # Root-level fallback — e.g. /aria_memories/HEARTBEAT.md
        root_filepath = ARIA_MEMORIES_PATH / filename
        if root_filepath.exists() and root_filepath.is_file():
            filepath = root_filepath
        else:
            raise HTTPException(status_code=404, detail=f"Artifact not found: {category}/{filename}")
    if not filepath.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    try:
        content = filepath.read_text(encoding="utf-8")
        stat = filepath.stat()
        return {
            "success": True,
            "content": content,
            "filename": filepath.name,
            "category": category,
            "path": str(filepath.relative_to(ARIA_MEMORIES_PATH)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text")
    except Exception as e:
        logger.warning("Artifact read failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to read artifact: {e}")


# ── List Artifacts ───────────────────────────────────────────────────────────

@router.get("/artifacts")
async def list_artifacts(
    category: str | None = None,
    pattern: str = "*",
    limit: int = 100,
):
    """
    List artifacts. If category provided, list files in that category.
    Otherwise, list all categories with file counts.
    """
    if category:
        _validate_path_segment(category)
        folder = ARIA_MEMORIES_PATH / category
        if not folder.exists():
            return {"category": category, "files": [], "count": 0}

        files = []
        for f in sorted(folder.rglob(pattern)):
            if f.is_file() and f.name != ".gitkeep":
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "path": str(f.relative_to(ARIA_MEMORIES_PATH)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
                if len(files) >= limit:
                    break

        return {"category": category, "files": files, "count": len(files)}

    # List all categories with counts
    categories = []
    for d in sorted(ARIA_MEMORIES_PATH.iterdir()):
        if d.is_dir() and d.name in ALLOWED_CATEGORIES:
            file_count = sum(1 for f in d.rglob("*") if f.is_file() and f.name != ".gitkeep")
            categories.append({
                "name": d.name,
                "file_count": file_count,
            })
    return {"categories": categories, "count": len(categories)}


# ── Delete Artifact ──────────────────────────────────────────────────────────

@router.delete("/artifacts/{category}/{filename:path}")
async def delete_artifact(category: str, filename: str):
    """Delete a file artifact from aria_memories."""
    _validate_path_segment(category)

    filepath = ARIA_MEMORIES_PATH / category / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {category}/{filename}")
    if not filepath.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    try:
        filepath.unlink()
        return {"success": True, "deleted": f"{category}/{filename}"}
    except Exception as e:
        logger.warning("Artifact delete failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
