"""
Memories endpoints — CRUD with upsert by key + semantic memory (S5-01).
"""

import asyncio
import json as json_lib
import logging
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, func, or_, select, delete, String
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Memory, SemanticMemory, WorkingMemory, Thought, LessonLearned
from deps import get_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateMemory, CreateSemanticMemory, SearchByVector, SummarizeSession, UpdateMemory

# LiteLLM connection for embeddings
LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
EMBED_REMOTE_TIMEOUT_SECONDS = float(os.environ.get("EMBED_REMOTE_TIMEOUT_SECONDS", "2.5"))
EMBED_REMOTE_RETRY_AFTER_SECONDS = int(os.environ.get("EMBED_REMOTE_RETRY_AFTER_SECONDS", "120"))
_EMBED_REMOTE_DISABLED_UNTIL: datetime | None = None

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Memories"])

_NOISE_NAME_MARKERS = (
    "[test]",
    "pytest",
    "goal_test",
    "skill_test",
    "test_entry",
    "live test goal",
    "test goal",
    "testing skill functionality",
    "creative pulse ingestion test",
    "creative pulse full visualization test",
    "pulse-exp-",
    "live test post",
    "moltbook test",
    "abc123",
    "post 42",
    "x: 1",
    "\"x\": 1",
    "{\"x\": 1}",
    "{\"x\":1}",
    "x; 1",
)


def _contains_noise_name(text: str) -> bool:
    normalized = (text or "").lower()
    if any(marker in normalized for marker in _NOISE_NAME_MARKERS):
        return True
    if any(prefix in normalized for prefix in ("test-", "test_", "goal-test", "goal_test", "skill-test", "skill_test")):
        return True
    # token-aware fallback for standalone "test"
    return bool(re.search(r"\btest\b", normalized))


def _is_noise_activity_for_summary(action: str | None, skill: str | None, details: dict | None) -> bool:
    action_s = (action or "").lower()
    skill_s = (skill or "").lower()
    details_s = json_lib.dumps(details or {}, default=str).lower()

    hay = f"{action_s} {skill_s} {details_s}"
    if _contains_noise_name(hay):
        return True

    if action_s in {"heartbeat", "cron_execution"}:
        return True

    return "health_check" in hay


def _is_noise_memory_payload(
    key: str | None = None,
    value: str | None = None,
    content: str | None = None,
    summary: str | None = None,
    source: str | None = None,
    metadata: dict | None = None,
) -> bool:
    hay = " ".join(
        [
            key or "",
            str(value or ""),
            content or "",
            summary or "",
            source or "",
            json_lib.dumps(metadata or {}, default=str),
        ]
    )
    if _contains_noise_name(hay):
        return True

    key_s = (key or "").lower().strip()
    source_s = (source or "").lower().strip()
    if key_s.startswith(("test-", "test_", "goal-test", "goal_test", "skill-test", "skill_test")):
        return True
    if key_s.startswith("lookup-") and any(token in hay.lower() for token in ("\"x\": 1", "{\"x\":1}", "x: 1")):
        return True
    if source_s in {"pytest", "test", "test_runner", "sandbox_test"}:
        return True

    return False


def _dt_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


@router.get("/memories")
async def get_memories(
    page: int = 1,
    limit: int = 25,
    category: str = None,
    db: AsyncSession = Depends(get_db),
):
    base = select(Memory).order_by(Memory.updated_at.desc())
    if category:
        base = base.where(Memory.category == category)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [m.to_dict() for m in rows]
    return build_paginated_response(items, total, page, limit)


@router.post("/memories")
async def create_or_update_memory(
    body: CreateMemory, db: AsyncSession = Depends(get_db)
):
    key = body.key
    value = body.value
    category = body.category
    if _is_noise_memory_payload(key=key, value=str(value), metadata={"category": category}):
        return {"stored": False, "skipped": True, "reason": "test_or_noise_payload"}

    # Try update first
    result = await db.execute(select(Memory).where(Memory.key == key))
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value
        existing.category = category
        await db.commit()
        return {"id": str(existing.id), "key": key, "upserted": True}

    memory = Memory(key=key, value=value, category=category)
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return {"id": str(memory.id), "key": key, "upserted": True}


# ===========================================================================
# Semantic Memory (S5-01 — pgvector)
# Must be registered BEFORE /memories/{key} to avoid route collision
# ===========================================================================

async def generate_embedding(text: str) -> list[float]:
    """Generate embedding via LiteLLM endpoint with local fallback."""
    import httpx
    global _EMBED_REMOTE_DISABLED_UNTIL

    def _local_embedding_fallback(value: str, dims: int = 768) -> list[float]:
        tokens = re.findall(r"[a-z0-9_]+", (value or "").lower())
        vector = [0.0] * dims
        if not tokens:
            return vector

        for token in tokens:
            bucket = hash(token) % dims
            sign = -1.0 if (hash(token + "_s") % 2) else 1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm > 0:
            vector = [component / norm for component in vector]
        return vector

    now_utc = datetime.now(timezone.utc)
    if _EMBED_REMOTE_DISABLED_UNTIL and now_utc < _EMBED_REMOTE_DISABLED_UNTIL:
        return _local_embedding_fallback(text)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{LITELLM_URL}/v1/embeddings",
                json={"model": "nomic-embed-text", "input": text},
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                timeout=httpx.Timeout(EMBED_REMOTE_TIMEOUT_SECONDS),
            )
            resp.raise_for_status()
            embedding = resp.json().get("data", [{}])[0].get("embedding")
            if isinstance(embedding, list) and embedding:
                _EMBED_REMOTE_DISABLED_UNTIL = None
                return embedding
            raise ValueError("empty embedding from LiteLLM response")
    except Exception as exc:
        _EMBED_REMOTE_DISABLED_UNTIL = datetime.now(timezone.utc) + timedelta(seconds=EMBED_REMOTE_RETRY_AFTER_SECONDS)
        logger.warning("LiteLLM embedding failed, using local fallback: %s", exc)
        return _local_embedding_fallback(text)


@router.get("/memories/semantic/stats")
async def semantic_memory_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregate statistics for the semantic memory store."""
    from sqlalchemy import case, cast, String, text as sa_text

    total = (await db.execute(
        select(func.count()).select_from(SemanticMemory)
    )).scalar() or 0

    # Breakdown by category
    cat_rows = (await db.execute(
        select(SemanticMemory.category, func.count())
        .group_by(SemanticMemory.category)
        .order_by(func.count().desc())
    )).all()
    by_category = {r[0] or "general": r[1] for r in cat_rows}

    # Breakdown by source
    src_rows = (await db.execute(
        select(SemanticMemory.source, func.count())
        .group_by(SemanticMemory.source)
        .order_by(func.count().desc())
    )).all()
    by_source = {r[0] or "unknown": r[1] for r in src_rows}

    # Average importance
    avg_imp = (await db.execute(
        select(func.avg(SemanticMemory.importance))
    )).scalar()

    # Most recent and oldest
    newest = (await db.execute(
        select(func.max(SemanticMemory.created_at))
    )).scalar()
    oldest = (await db.execute(
        select(func.min(SemanticMemory.created_at))
    )).scalar()

    # Most accessed
    top_accessed = (await db.execute(
        select(SemanticMemory.summary, SemanticMemory.category, SemanticMemory.access_count)
        .where(SemanticMemory.access_count > 0)
        .order_by(SemanticMemory.access_count.desc())
        .limit(10)
    )).all()

    return {
        "total": total,
        "by_category": by_category,
        "by_source": by_source,
        "avg_importance": round(avg_imp or 0, 3),
        "newest": _dt_iso_utc(newest),
        "oldest": _dt_iso_utc(oldest),
        "top_accessed": [
            {"summary": r[0], "category": r[1], "access_count": r[2]}
            for r in top_accessed
        ],
    }


@router.get("/memories/semantic")
async def list_semantic_memories(
    category: str = None,
    source: str = None,
    limit: int = 50,
    page: int = 1,
    min_importance: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """List semantic memories with optional category/source filter. No embedding query needed."""
    base = select(SemanticMemory).order_by(SemanticMemory.created_at.desc())
    if category:
        base = base.where(SemanticMemory.category == category)
    if source:
        base = base.where(SemanticMemory.source == source)
    if min_importance > 0:
        base = base.where(SemanticMemory.importance >= min_importance)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [m.to_dict() for m in rows]
    return build_paginated_response(items, total, page, limit)


@router.post("/memories/semantic")
async def store_semantic_memory(
    body: CreateSemanticMemory,
    db: AsyncSession = Depends(get_db),
):
    """Store a memory with its vector embedding for semantic search."""
    content = body.content

    category = body.category
    importance = body.importance
    source = body.source
    summary = body.summary or content[:100]
    metadata = body.metadata
    if _is_noise_memory_payload(content=content, summary=summary, source=source, metadata=metadata):
        return {"stored": False, "skipped": True, "reason": "test_or_noise_payload"}

    try:
        embedding = await generate_embedding(content)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding generation failed: {e}")

    memory = SemanticMemory(
        content=content,
        summary=summary,
        category=category,
        embedding=embedding,
        importance=importance,
        source=source,
        metadata_json={"original_length": len(content), **(metadata or {})},
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return {"id": str(memory.id), "stored": True}


@router.get("/memories/search")
async def search_memories(
    query: str,
    limit: int = 5,
    category: str = None,
    min_importance: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Search memories by semantic similarity using pgvector cosine distance."""
    try:
        query_embedding = await generate_embedding(query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding generation failed: {e}")

    distance_col = SemanticMemory.embedding.cosine_distance(query_embedding).label("distance")
    stmt = select(SemanticMemory, distance_col).order_by("distance").limit(limit)

    if category:
        stmt = stmt.where(SemanticMemory.category == category)
    if min_importance > 0:
        stmt = stmt.where(SemanticMemory.importance >= min_importance)

    result = await db.execute(stmt)
    memories = []
    for mem, dist in result.all():
        mem.accessed_at = datetime.now(timezone.utc)
        mem.access_count = int(mem.access_count or 0) + 1
        d = mem.to_dict()
        d["similarity"] = round(1 - dist, 4)
        memories.append(d)
    await db.commit()
    return {"memories": memories, "query": query}


@router.post("/memories/search-by-vector")
async def search_memories_by_vector(
    body: SearchByVector,
    db: AsyncSession = Depends(get_db),
):
    """Search memories by a pre-computed embedding vector (pgvector cosine distance).

    Used by the EmbeddingSentimentClassifier when it already has an embedding
    and wants to skip the redundant server-side embedding generation.
    """
    embedding = body.embedding

    category = body.category
    limit = body.limit
    min_importance = body.min_importance

    distance_col = SemanticMemory.embedding.cosine_distance(embedding).label("distance")
    stmt = select(SemanticMemory, distance_col).order_by("distance").limit(limit)

    if category:
        stmt = stmt.where(SemanticMemory.category == category)
    if min_importance > 0:
        stmt = stmt.where(SemanticMemory.importance >= min_importance)

    result = await db.execute(stmt)
    memories = []
    for mem, dist in result.all():
        d = mem.to_dict()
        d["similarity"] = 0.0 if (dist is None or math.isnan(dist)) else round(1 - dist, 4)
        memories.append(d)

    return {"memories": memories, "count": len(memories)}


@router.post("/memories/summarize-session")
async def summarize_session(
    body: SummarizeSession,
    db: AsyncSession = Depends(get_db),
):
    """Summarize recent activity into an episodic semantic memory (S5-03)."""
    hours_back = body.hours_back

    from db.models import ActivityLog
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    stmt = (
        select(ActivityLog)
        .where(ActivityLog.created_at >= cutoff)
        .order_by(ActivityLog.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    activities = [
        item
        for item in result.scalars().all()
        if not _is_noise_activity_for_summary(item.action, item.skill, item.details if isinstance(item.details, dict) else {})
    ]

    if not activities:
        return {"summary": "No recent activities to summarize.", "decisions": [], "stored": False}

    activity_text = "\n".join(
        f"- [{a.action}] {a.skill or 'system'}: {json_lib.dumps(a.details) if a.details else ''}"
        for a in activities[:50]
    )

    # Build summary via LLM
    import httpx
    prompt = (
        "Summarize this work session in 2-3 sentences. Extract:\n"
        "1. What was the main task?\n2. What was decided?\n"
        "3. What was the emotional tone? (frustrated/satisfied/neutral)\n"
        "4. Any unresolved issues?\n\n"
        f"Activities:\n{activity_text}\n\n"
        'Format: JSON with keys: summary, decisions (list), tone, unresolved (list)'
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{LITELLM_URL}/v1/chat/completions",
                json={
                    "model": "kimi",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            # Try to parse JSON from response
            import re
            json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
            if json_match:
                parsed = json_lib.loads(json_match.group())
            else:
                parsed = {"summary": raw.strip(), "decisions": [], "tone": "neutral", "unresolved": []}
    except Exception as e:
        parsed = {"summary": f"Session with {len(activities)} activities (auto-summary failed: {e})",
                  "decisions": [], "tone": "neutral", "unresolved": []}

    summary_text = parsed.get("summary", "No summary available")
    decisions = parsed.get("decisions", [])

    # Store episodic summary as semantic memory
    stored_ids = []
    try:
        emb = await generate_embedding(summary_text)
        mem = SemanticMemory(
            content=summary_text,
            summary=summary_text[:100],
            category="episodic",
            embedding=emb,
            importance=0.7,
            source="conversation_summary",
            metadata_json={"hours_back": hours_back, "activity_count": len(activities), "tone": parsed.get("tone")},
        )
        db.add(mem)
        await db.flush()
        stored_ids.append(str(mem.id))
    except Exception as e:
        logger.error("Failed to store conversation summary: %s", e)

    for decision in decisions:
        if isinstance(decision, str) and decision.strip():
            try:
                emb = await generate_embedding(decision)
                dmem = SemanticMemory(
                    content=decision,
                    summary=decision[:100],
                    category="decision",
                    embedding=emb,
                    importance=0.8,
                    source="conversation_summary",
                )
                db.add(dmem)
                await db.flush()
                stored_ids.append(str(dmem.id))
            except Exception as e:
                logger.error("Failed to store decision memory: %s", e)

    await db.commit()
    return {"summary": summary_text, "decisions": decisions, "stored": bool(stored_ids), "ids": stored_ids}


# ===========================================================================
# Embedding projection — MUST be before /memories/{key} catch-all
# ===========================================================================


@router.get("/memories/embedding-projection")
async def get_embedding_projection(
    limit: int = Query(200, ge=10, le=1000, description="Default 200; >500 may be slow"),
    method: str = Query("pca", pattern="^(pca|tsne)$"),
    category: Optional[str] = Query(None),
    min_importance: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Project semantic memory embeddings to 2D for scatter plot visualization."""
    import numpy as np

    stmt = select(SemanticMemory).where(
        SemanticMemory.embedding.isnot(None),
        SemanticMemory.importance >= min_importance,
    )
    if category:
        stmt = stmt.where(SemanticMemory.category == category)
    stmt = stmt.order_by(SemanticMemory.importance.desc()).limit(limit)

    result = await db.execute(stmt)
    memories = result.scalars().all()

    if len(memories) < 3:
        return {"points": [], "method": method, "error": "Need at least 3 memories with embeddings"}

    embeddings = []
    valid_memories = []
    for m in memories:
        emb = m.embedding
        if emb is not None and len(emb) > 0:
            embeddings.append(list(emb))  # cast Vector to plain list for numpy
            valid_memories.append(m)

    if len(embeddings) < 3:
        return {"points": [], "method": method, "error": "Not enough valid embeddings"}

    X = np.array(embeddings, dtype=np.float32)

    if method == "tsne":
        try:
            from sklearn.manifold import TSNE
            perplexity = min(30, len(X) - 1)
            reducer = TSNE(n_components=2, perplexity=perplexity, random_state=42, n_iter=500)
            coords = reducer.fit_transform(X)
        except ImportError:
            method = "pca"

    if method == "pca":
        X_centered = X - X.mean(axis=0)
        cov = np.cov(X_centered, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        idx = np.argsort(eigenvalues)[::-1][:2]
        coords = X_centered @ eigenvectors[:, idx]

    coords_min = coords.min(axis=0)
    coords_max = coords.max(axis=0)
    coords_range = coords_max - coords_min
    coords_range[coords_range == 0] = 1
    coords_normalized = 2 * (coords - coords_min) / coords_range - 1

    points = []
    for i, m in enumerate(valid_memories):
        points.append({
            "id": str(m.id),
            "x": round(float(coords_normalized[i][0]), 4),
            "y": round(float(coords_normalized[i][1]), 4),
            "label": (m.summary or m.content or "")[:80],
            "category": m.category,
            "importance": m.importance,
            "source": m.source,
            "access_count": m.access_count,
            "created_at": _dt_iso_utc(m.created_at),
        })

    categories: dict = {}
    for p in points:
        cat = p["category"]
        categories.setdefault(cat, {"count": 0, "avg_x": 0.0, "avg_y": 0.0})
        categories[cat]["count"] += 1
        categories[cat]["avg_x"] += p["x"]
        categories[cat]["avg_y"] += p["y"]
    for cat in categories:
        n = categories[cat]["count"]
        categories[cat]["avg_x"] = round(categories[cat]["avg_x"] / n, 4)
        categories[cat]["avg_y"] = round(categories[cat]["avg_y"] / n, 4)

    return {"points": points, "method": method, "total": len(points), "categories": categories}


# ===========================================================================
# Key-value memory by key (MUST be after /memories/search to avoid collision)
# ===========================================================================


@router.get("/memories/{key}")
async def get_memory_by_key(key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Memory).where(Memory.key == key))
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory.to_dict()


@router.delete("/memories/{key}")
async def delete_memory(key: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Memory).where(Memory.key == key))
    await db.commit()
    return {"deleted": True, "key": key}


@router.patch("/memories/{key}")
async def update_memory(key: str, body: UpdateMemory, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Memory).where(Memory.key == key))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")
    updates = body.model_dump(exclude_unset=True)
    for k, value in updates.items():
        setattr(row, k, value)
    await db.commit()
    await db.refresh(row)
    return row.to_dict()


@router.get("/memory-graph")
async def get_memory_graph(
    limit: int = Query(200, ge=1, le=2000),
    include_types: str = Query(
        "all",
        description="Comma-separated types to include: semantic,working,kv,thought,lesson",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Build a vis-network graph of all memory types and inferred relationships.

    Node types: semantic_memory, working_memory, kv_memory, thought, lesson
    Edge types: same_category (star topology), shared_source (star topology)
    """
    types = (
        ["semantic", "working", "kv", "thought", "lesson"]
        if include_types == "all"
        else [t.strip() for t in include_types.split(",")]
    )

    nodes: list[dict] = []
    edges: list[dict] = []
    category_index: dict[str, list[str]] = {}
    source_index: dict[str, list[str]] = {}
    edge_id = 0

    # ── Semantic Memories ──────────────────────────────────────────
    if "semantic" in types:
        stmt = (
            select(SemanticMemory)
            .order_by(SemanticMemory.importance.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        for mem in rows:
            nid = f"sem_{mem.id}"
            nodes.append({
                "id": nid,
                "label": (mem.summary or mem.content or "")[:60],
                "type": "semantic_memory",
                "category": mem.category,
                "importance": float(mem.importance or 0),
                "source": mem.source,
                "access_count": mem.access_count,
                "created_at": _dt_iso_utc(mem.created_at),
            })
            category_index.setdefault(mem.category or "general", []).append(nid)
            if mem.source:
                source_index.setdefault(mem.source, []).append(nid)

    # ── Working Memory ─────────────────────────────────────────────
    if "working" in types:
        stmt = (
            select(WorkingMemory)
            .order_by(WorkingMemory.importance.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()
        for wm in rows:
            nid = f"wm_{wm.id}"
            nodes.append({
                "id": nid,
                "label": f"{wm.category}/{wm.key}"[:60],
                "type": "working_memory",
                "category": wm.category,
                "importance": float(wm.importance or 0),
                "source": wm.source,
                "ttl_hours": wm.ttl_hours,
                "created_at": _dt_iso_utc(wm.created_at),
            })
            category_index.setdefault(wm.category or "general", []).append(nid)
            if wm.source:
                source_index.setdefault(wm.source, []).append(nid)

    # ── KV Memories ────────────────────────────────────────────────
    if "kv" in types:
        stmt = select(Memory).order_by(Memory.updated_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        for m in rows:
            nid = f"kv_{m.id}"
            nodes.append({
                "id": nid,
                "label": (m.key or "")[:60],
                "type": "kv_memory",
                "category": m.category,
                "created_at": _dt_iso_utc(m.created_at),
            })
            category_index.setdefault(m.category or "general", []).append(nid)

    # ── Thoughts ───────────────────────────────────────────────────
    if "thought" in types:
        stmt = (
            select(Thought)
            .order_by(Thought.created_at.desc())
            .limit(min(limit, 100))
        )
        rows = (await db.execute(stmt)).scalars().all()
        for t in rows:
            nid = f"th_{t.id}"
            nodes.append({
                "id": nid,
                "label": (t.content or "")[:60],
                "type": "thought",
                "category": t.category,
                "created_at": _dt_iso_utc(t.created_at),
            })
            category_index.setdefault(t.category or "general", []).append(nid)

    # ── Lessons Learned ───────────────────────────────────────────
    if "lesson" in types:
        stmt = (
            select(LessonLearned)
            .order_by(LessonLearned.occurrences.desc())
            .limit(min(limit, 100))
        )
        rows = (await db.execute(stmt)).scalars().all()
        for ll in rows:
            nid = f"ll_{ll.id}"
            nodes.append({
                "id": nid,
                "label": (ll.error_pattern or "")[:60],
                "type": "lesson",
                "category": ll.skill_name or "general",
                "occurrences": ll.occurrences,
                "effectiveness": float(ll.effectiveness or 0),
                "created_at": _dt_iso_utc(ll.created_at),
            })
            if ll.skill_name:
                category_index.setdefault(ll.skill_name, []).append(nid)

    # ── Build edges: same_category (star topology per category) ───
    for cat, nids in category_index.items():
        if len(nids) < 2:
            continue
        hub = nids[0]
        for spoke in nids[1 : min(len(nids), 9)]:  # max 8 spokes per hub
            edges.append({
                "id": f"e_{edge_id}",
                "from": hub,
                "to": spoke,
                "type": "same_category",
                "label": cat,
            })
            edge_id += 1

    # ── Build edges: shared_source ─────────────────────────────────
    for src, nids in source_index.items():
        if len(nids) < 2:
            continue
        hub = nids[0]
        for spoke in nids[1 : min(len(nids), 7)]:
            edges.append({
                "id": f"e_{edge_id}",
                "from": hub,
                "to": spoke,
                "type": "shared_source",
                "label": src,
            })
            edge_id += 1

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "by_type": type_counts,
            "categories": list(category_index.keys()),
        },
    }


# ===========================================================================
# Unified Memory Search — S-37
# ===========================================================================


@router.get("/memory-search")
async def unified_memory_search(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
    types: str = Query("all", description="Comma-separated: semantic,kv,working,thought,lesson"),
    db: AsyncSession = Depends(get_db),
):
    """Unified search across all memory types."""
    search_types = (
        ["semantic", "kv", "working", "thought", "lesson"]
        if types == "all"
        else [t.strip() for t in types.split(",")]
    )
    results: list[dict] = []

    # 1. Semantic search (vector)
    if "semantic" in search_types:
        try:
            embedding = await generate_embedding(query)
            if embedding:
                from pgvector.sqlalchemy import Vector
                stmt = (
                    select(
                        SemanticMemory,
                        SemanticMemory.embedding.cosine_distance(embedding).label("distance"),
                    )
                    .where(SemanticMemory.embedding.isnot(None))
                    .order_by("distance")
                    .limit(limit)
                )
                result = await db.execute(stmt)
                for row in result.all():
                    mem = row[0]
                    similarity = max(0.0, 1 - float(row[1]))
                    results.append({
                        "type": "semantic_memory",
                        "id": str(mem.id),
                        "title": mem.summary or (mem.content or "")[:80],
                        "content": (mem.content or "")[:300],
                        "category": mem.category,
                        "relevance": round(similarity, 4),
                        "importance": mem.importance,
                        "source": mem.source,
                        "created_at": _dt_iso_utc(mem.created_at),
                    })
        except Exception:
            pass

    # 2. KV Memory text search
    if "kv" in search_types:
        pattern = f"%{query}%"
        stmt = (
            select(Memory)
            .where(or_(Memory.key.ilike(pattern), cast(Memory.value, String).ilike(pattern)))
            .order_by(Memory.updated_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        for m in result.scalars().all():
            results.append({
                "type": "kv_memory",
                "id": str(m.id),
                "title": m.key,
                "content": str(m.value)[:300] if m.value else "",
                "category": m.category,
                "relevance": 0.5,
                "created_at": _dt_iso_utc(m.created_at),
            })

    # 3. Working Memory text search
    if "working" in search_types:
        pattern = f"%{query}%"
        stmt = (
            select(WorkingMemory)
            .where(or_(
                WorkingMemory.key.ilike(pattern),
                cast(WorkingMemory.value, String).ilike(pattern),
            ))
            .order_by(WorkingMemory.importance.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        for wm in result.scalars().all():
            results.append({
                "type": "working_memory",
                "id": str(wm.id),
                "title": f"{wm.category}/{wm.key}",
                "content": str(wm.value)[:300] if wm.value else "",
                "category": wm.category,
                "relevance": 0.45,
                "importance": wm.importance,
                "created_at": _dt_iso_utc(wm.created_at),
            })

    # 4. Thoughts text search
    if "thought" in search_types:
        stmt = (
            select(Thought)
            .where(Thought.content.ilike(f"%{query}%"))
            .order_by(Thought.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        for t in result.scalars().all():
            results.append({
                "type": "thought",
                "id": str(t.id),
                "title": (t.content or "")[:80],
                "content": (t.content or "")[:300],
                "category": t.category,
                "relevance": 0.4,
                "created_at": _dt_iso_utc(t.created_at),
            })

    # 5. Lessons text search
    if "lesson" in search_types:
        stmt = (
            select(LessonLearned)
            .where(or_(
                LessonLearned.error_pattern.ilike(f"%{query}%"),
                LessonLearned.resolution.ilike(f"%{query}%"),
            ))
            .order_by(LessonLearned.occurrences.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        for ll in result.scalars().all():
            results.append({
                "type": "lesson",
                "id": str(ll.id),
                "title": (ll.error_pattern or "")[:80],
                "content": (ll.resolution or "")[:300],
                "category": ll.skill_name or "general",
                "relevance": 0.35,
                "occurrences": ll.occurrences,
                "created_at": _dt_iso_utc(ll.created_at),
            })

    results.sort(key=lambda r: r.get("relevance", 0), reverse=True)
    type_counts: dict[str, int] = {}
    for r in results:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1

    return {
        "query": query,
        "results": results[:limit * 2],
        "total": len(results),
        "by_type": type_counts,
    }


# ===========================================================================
# Memory Timeline — S-32
# ===========================================================================


@router.get("/memory-timeline")
async def get_memory_timeline(
    hours: int = Query(168, ge=1, le=720, description="Hours lookback (default 7 days)"),
    bucket_hours: int = Query(1, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """Time-bucketed memory creation data for Chart.js timeline charts."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    sem_stmt = (
        select(
            func.date_trunc("hour", SemanticMemory.created_at).label("bucket"),
            func.count().label("count"),
            func.avg(SemanticMemory.importance).label("avg_importance"),
        )
        .where(SemanticMemory.created_at >= cutoff)
        .group_by("bucket")
        .order_by("bucket")
    )
    sem_result = await db.execute(sem_stmt)
    sem_buckets = [
        {"t": _dt_iso_utc(r.bucket), "count": r.count, "avg_imp": round(float(r.avg_importance or 0), 3)}
        for r in sem_result.all()
    ]

    wm_stmt = (
        select(
            func.date_trunc("hour", WorkingMemory.created_at).label("bucket"),
            func.count().label("count"),
        )
        .where(WorkingMemory.created_at >= cutoff)
        .group_by("bucket")
        .order_by("bucket")
    )
    wm_result = await db.execute(wm_stmt)
    wm_buckets = [{"t": _dt_iso_utc(r.bucket), "count": r.count} for r in wm_result.all()]

    th_stmt = (
        select(
            func.date_trunc("hour", Thought.created_at).label("bucket"),
            func.count().label("count"),
        )
        .where(Thought.created_at >= cutoff)
        .group_by("bucket")
        .order_by("bucket")
    )
    th_result = await db.execute(th_stmt)
    th_buckets = [{"t": _dt_iso_utc(r.bucket), "count": r.count} for r in th_result.all()]

    ttl_stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.ttl_hours.isnot(None))
        .order_by(WorkingMemory.importance.desc())
        .limit(50)
    )
    ttl_result = await db.execute(ttl_stmt)
    ttl_items = []
    now = datetime.now(timezone.utc)
    for wm in ttl_result.scalars().all():
        expires_at = (
            wm.created_at + timedelta(hours=wm.ttl_hours)
            if wm.created_at and wm.ttl_hours
            else None
        )
        remaining_hours = (
            (expires_at - now).total_seconds() / 3600
            if expires_at and expires_at > now
            else 0
        )
        ttl_items.append({
            "id": str(wm.id),
            "key": f"{wm.category}/{wm.key}",
            "importance": wm.importance,
            "ttl_hours": wm.ttl_hours,
            "remaining_hours": round(remaining_hours, 1),
            "expired": remaining_hours <= 0,
            "created_at": _dt_iso_utc(wm.created_at),
        })

    heatmap_stmt = (
        select(
            func.extract("dow", SemanticMemory.created_at).label("dow"),
            func.extract("hour", SemanticMemory.created_at).label("hour"),
            func.count().label("count"),
        )
        .where(SemanticMemory.created_at >= cutoff)
        .group_by("dow", "hour")
    )
    heatmap_result = await db.execute(heatmap_stmt)
    heatmap = [
        {"dow": int(r.dow), "hour": int(r.hour), "count": r.count}
        for r in heatmap_result.all()
    ]

    return {
        "semantic_timeline": sem_buckets,
        "working_memory_timeline": wm_buckets,
        "thoughts_timeline": th_buckets,
        "ttl_countdowns": ttl_items,
        "creation_heatmap": heatmap,
        "period_hours": hours,
        "bucket_hours": bucket_hours,
    }


# ===========================================================================
# Memory Consolidation Dashboard — S-35
# ===========================================================================


@router.get("/memory-consolidation")
async def get_memory_consolidation_dashboard(
    db: AsyncSession = Depends(get_db),
):
    """Memory consolidation dashboard: file tier counts, source distribution, promo candidates."""
    from pathlib import Path

    def _scan_tier(tier_path: Path) -> dict:
        if not tier_path.exists():
            return {"count": 0, "total_bytes": 0, "newest": 0, "oldest": 0}
        files = [f for f in tier_path.rglob("*") if f.is_file()]
        file_stats = [f.stat() for f in files]
        return {
            "count": len(file_stats),
            "total_bytes": sum(s.st_size for s in file_stats),
            "newest": max((s.st_mtime for s in file_stats), default=0),
            "oldest": min((s.st_mtime for s in file_stats), default=0),
        }

    base = Path(os.environ.get("ARIA_MEMORIES_PATH", "/aria_memories"))
    tier_names = ["surface", "medium", "deep"]
    candidate_roots = [base, base / "memory"]

    def _tier_dir_score(root: Path) -> int:
        return sum(1 for tier in tier_names if (root / tier).exists())

    tier_root = max(candidate_roots, key=_tier_dir_score)
    if _tier_dir_score(tier_root) == 0:
        tier_root = base / "memory" if (base / "memory").exists() else base
    tiers = {}
    for tier in tier_names:
        tiers[tier] = await asyncio.to_thread(_scan_tier, tier_root / tier)

    source_stmt = select(
        SemanticMemory.source,
        func.count().label("count"),
        func.avg(SemanticMemory.importance).label("avg_importance"),
    ).group_by(SemanticMemory.source)
    source_result = await db.execute(source_stmt)
    sources = {
        (r.source or "unknown"): {
            "count": r.count,
            "avg_importance": round(float(r.avg_importance or 0), 3),
        }
        for r in source_result.all()
    }

    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.created_at >= cutoff_24h)
        .order_by(SemanticMemory.created_at.desc())
        .limit(20)
    )
    recent_result = await db.execute(recent_stmt)
    recent_memories = [
        {
            "id": str(m.id),
            "summary": (m.summary or m.content or "")[:120],
            "category": m.category,
            "source": m.source,
            "importance": m.importance,
            "created_at": _dt_iso_utc(m.created_at),
        }
        for m in recent_result.scalars().all()
    ]

    promo_stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.importance >= 0.7)
        .order_by(WorkingMemory.importance.desc())
        .limit(15)
    )
    promo_result = await db.execute(promo_stmt)
    promotion_candidates = [
        {
            "id": str(wm.id),
            "key": f"{wm.category}/{wm.key}",
            "importance": wm.importance,
            "access_count": wm.access_count,
            "created_at": _dt_iso_utc(wm.created_at),
        }
        for wm in promo_result.scalars().all()
    ]

    category_stmt = select(
        SemanticMemory.category,
        func.count().label("count"),
        func.avg(func.length(SemanticMemory.content)).label("avg_content_len"),
        func.avg(func.length(SemanticMemory.summary)).label("avg_summary_len"),
    ).group_by(SemanticMemory.category)
    cat_result = await db.execute(category_stmt)
    compression_stats: dict = {}
    for r in cat_result.all():
        content_len = float(r.avg_content_len or 0)
        summary_len = float(r.avg_summary_len or 0)
        ratio = round(summary_len / content_len, 2) if content_len > 0 else 0
        compression_stats[r.category] = {
            "count": r.count,
            "avg_content_len": round(content_len),
            "avg_summary_len": round(summary_len),
            "compression_ratio": ratio,
        }

    semantic_total = (await db.execute(select(func.count()).select_from(SemanticMemory))).scalar() or 0

    return {
        "file_tiers": tiers,
        "file_tier_root": str(tier_root),
        "semantic_total": int(semantic_total),
        "source_distribution": sources,
        "recent_consolidations": recent_memories,
        "promotion_candidates": promotion_candidates,
        "compression_stats": compression_stats,
    }
