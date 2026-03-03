"""
Analysis endpoints — Patterns, Compression, Seed.

Provides REST endpoints that integrate with
aria_skills/{pattern_recognition,memory_compression}.
All heavy lifting is done in the skills; these endpoints serve as a thin
HTTP façade for the web dashboard and external callers.

Sentiment endpoints have been extracted to routers/sentiment.py.
"""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ActivityLog,
    SemanticMemory,
    Thought,
    WorkingMemory,
)
from deps import get_db

try:
    from aria_models.loader import get_embedding_model as _get_embedding_model
except ImportError:
    def _get_embedding_model() -> str:
        return ""

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


async def _generate_embedding(text: str) -> list[float]:
    """Generate embedding via LiteLLM embedding endpoint.
    Falls back to zero-vector if Ollama/LiteLLM is unreachable (timeout 5s).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/embeddings",
            json={"model": _get_embedding_model(), "input": text},
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]








# ── Request / Response Schemas ──────────────────────────────────────────────

class PatternDetectionRequest(BaseModel):
    memories: list[dict[str, Any]] | None = None
    min_confidence: float = Field(0.3, ge=0, le=1)
    store: bool = True


class CompressionRequest(BaseModel):
    memories: list[dict[str, Any]] = Field(..., min_items=5)
    store_semantic: bool = True


class SessionCompressionRequest(BaseModel):
    hours_back: int = Field(6, ge=1, le=48)


# ── Pattern Endpoints ──────────────────────────────────────────────────────

@router.post("/patterns/detect")
async def detect_patterns(req: PatternDetectionRequest, db: AsyncSession = Depends(get_db)):
    """Run pattern detection on memories."""
    from aria_skills.pattern_recognition import PatternRecognizer, MemoryItem

    memories = req.memories
    if not memories:
        # Fetch from semantic memory
        stmt = (
            select(SemanticMemory)
            .order_by(SemanticMemory.created_at.desc())
            .limit(200)
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
        memories = [
            {
                "id": str(m.id),
                "content": m.content,
                "category": m.category,
                "timestamp": m.created_at.isoformat() if m.created_at else None,
                "metadata": m.metadata_json or {},
            }
            for m in items
        ]

    if len(memories) < 10:
        return {"patterns_found": 0, "patterns": [],
                "message": "Need >= 10 memories for pattern detection"}

    recognizer = PatternRecognizer(window_days=30)
    mem_items = [MemoryItem.from_dict(m) for m in memories]
    detection = await recognizer.analyze(mem_items, min_confidence=req.min_confidence)

    # Store in semantic memory if requested (dedup: update existing patterns)
    stored_ids = []
    if req.store:
        for p in detection.patterns_found[:20]:
            content_text = (f"Pattern: {p.type.value} — {p.subject} "
                           f"(confidence={p.confidence:.2f})")
            new_meta = {
                "pattern_type": p.type.value,
                "subject": p.subject,
                "confidence": p.confidence,
                "evidence": p.evidence[:5],
            }
            try:
                embedding = await _generate_embedding(content_text)
            except Exception as e:
                logger.warning("Embedding generation failed: %s", e)
                embedding = [0.0] * 768

            # Check for existing pattern with same type+subject
            existing_stmt = (
                select(SemanticMemory)
                .where(SemanticMemory.category == "pattern_detection")
                .where(SemanticMemory.metadata_json["pattern_type"].astext == p.type.value)
                .where(SemanticMemory.metadata_json["subject"].astext == p.subject)
                .limit(1)
            )
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()
            if existing:
                existing.content = content_text
                existing.summary = content_text[:100]
                existing.importance = p.confidence
                existing.metadata_json = new_meta
                existing.embedding = embedding
            else:
                mem = SemanticMemory(
                    content=content_text,
                    summary=content_text[:100],
                    category="pattern_detection",
                    embedding=embedding,
                    importance=p.confidence,
                    source="analysis_api",
                    metadata_json=new_meta,
                )
                db.add(mem)
        await db.commit()

    return {
        "patterns_found": len(detection.patterns_found),
        "patterns": [p.to_dict() for p in detection.patterns_found],
        "new_patterns": detection.new_patterns,
        "persistent_patterns": detection.persistent_patterns,
        "memories_analyzed": detection.total_memories_analyzed,
    }


@router.get("/patterns/history")
async def get_pattern_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get stored pattern detections from semantic memory."""
    stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.category == "pattern_detection")
        .order_by(SemanticMemory.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": str(m.id),
                "content": m.content,
                "category": m.category,
                "importance": m.importance,
                "metadata": m.metadata_json,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ],
        "total": len(items),
    }


# ── Compression Endpoints ──────────────────────────────────────────────────

@router.post("/compression/run")
async def run_compression(req: CompressionRequest, db: AsyncSession = Depends(get_db)):
    """Run memory compression on provided memories."""
    from aria_skills.memory_compression import (
        MemoryEntry, MemoryCompressor, CompressionManager)

    mem_objects = [MemoryEntry.from_dict(m) for m in req.memories]
    compressor = MemoryCompressor()
    manager = CompressionManager(compressor)
    result = await manager.process_all(mem_objects)

    # Store compressed summaries
    stored_ids = []
    if req.store_semantic:
        for cm in manager.compressed_store:
            try:
                embedding = await _generate_embedding(cm.summary)
            except Exception as e:
                logger.warning("Embedding generation failed: %s", e)
                embedding = [0.0] * 768
            mem = SemanticMemory(
                content=cm.summary,
                summary=cm.summary[:100],
                category=f"compressed_{cm.tier}",
                embedding=embedding,
                importance=0.7 if cm.tier == "archive" else 0.5,
                source="compression_api",
                metadata_json={
                    "tier": cm.tier,
                    "original_count": cm.original_count,
                    "key_entities": cm.key_entities,
                    "key_facts": cm.key_facts,
                },
            )
            db.add(mem)
        await db.commit()

    return {
        "compressed": result.success,
        "memories_processed": result.memories_processed,
        "compression_ratio": round(result.compression_ratio, 3),
        "tokens_saved_estimate": result.tokens_saved_estimate,
        "tiers_updated": result.tiers_updated,
        "summaries": [cm.to_dict() for cm in manager.compressed_store],
    }


@router.get("/compression/history")
async def get_compression_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get stored compressed memories from semantic memory."""
    stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.category.in_(["compressed_recent", "compressed_archive"]))
        .order_by(SemanticMemory.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": str(m.id),
                "content": m.content,
                "category": m.category,
                "importance": m.importance,
                "metadata": m.metadata_json,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ],
        "total": len(items),
    }


# ── Compression Auto-Run (self-fetching, designed for cron calls) ────────────


class AutoCompressionRequest(BaseModel):
    raw_limit: int = Field(20, ge=5, le=100)
    store_semantic: bool = True
    dry_run: bool = False


@router.post("/compression/auto-run")
async def run_auto_compression(
    req: AutoCompressionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-compress working memory when count exceeds raw_limit.
    Self-fetches working memory — no memories payload needed.
    Designed for cron job invocation (every 6 hours).
    """
    from aria_skills.memory_compression import MemoryEntry, MemoryCompressor, CompressionManager

    stmt = select(WorkingMemory).order_by(WorkingMemory.updated_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()

    if len(rows) <= req.raw_limit:
        return {
            "skipped": True,
            "reason": f"Only {len(rows)} items (raw_limit={req.raw_limit}), no compression needed",
            "count": len(rows),
        }

    mem_objects = [
        MemoryEntry(
            id=str(r.id),
            content=str(r.value or r.key),
            category=r.category or "general",
            timestamp=r.updated_at or r.created_at,
            importance_score=float(r.importance if r.importance is not None else 0.5),
        )
        for r in rows
    ]

    if req.dry_run:
        return {
            "dry_run": True,
            "would_compress": len(mem_objects),
            "raw_limit": req.raw_limit,
        }

    compressor = MemoryCompressor(raw_limit=req.raw_limit)
    manager = CompressionManager(compressor)
    result = await manager.process_all(mem_objects)

    if req.store_semantic and manager.compressed_store:
        for cm in manager.compressed_store:
            try:
                embedding = await _generate_embedding(cm.summary)
            except Exception as e:
                logger.warning("Embedding generation failed: %s", e)
                embedding = [0.0] * 768
            db.add(SemanticMemory(
                content=cm.summary,
                summary=cm.summary[:100],
                category=f"compressed_{cm.tier}",
                embedding=embedding,
                importance=0.7 if cm.tier == "archive" else 0.5,
                source="compression_auto",
                metadata_json={
                    "tier": cm.tier,
                    "original_count": cm.original_count,
                    "key_entities": cm.key_entities,
                    "key_facts": cm.key_facts,
                },
            ))
        await db.commit()

    return {
        "skipped": False,
        "compressed": result.success,
        "memories_processed": result.memories_processed,
        "compression_ratio": round(result.compression_ratio, 3),
        "tokens_saved_estimate": getattr(result, "tokens_saved_estimate", 0),
        "tiers_updated": result.tiers_updated,
        "summaries_stored": len(manager.compressed_store),
    }


# ── Seed: backfill semantic_memories from activity_log + thoughts ────────────


@router.post("/seed-memories")
async def seed_semantic_memories(
    limit: int = 200,
    skip_existing: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Backfill semantic_memories from activity_log + thoughts.

    Reads recent activities and thoughts, generates embeddings via LiteLLM,
    and stores them in semantic_memories so pattern_recognition,
    sentiment_analysis, and unified_search have data to work with.
    """
    import logging

    logger = logging.getLogger("aria.analysis.seed")
    seeded = 0
    skipped = 0
    errors = 0
    batch_size = 10

        # ── 1. Thoughts → semantic_memories ──
    thought_stmt = (
        select(Thought)
        .order_by(Thought.created_at.desc())
        .limit(limit)
    )
    thoughts = (await db.execute(thought_stmt)).scalars().all()

    for i in range(0, len(thoughts), batch_size):
        batch = thoughts[i : i + batch_size]
        for t in batch:
            content = t.content.strip()
            if not content or len(content) < 10:
                skipped += 1
                continue

            if skip_existing:
                fp = content[:100]
                exists = await db.execute(
                    select(func.count())
                    .select_from(SemanticMemory)
                    .where(
                        SemanticMemory.source == "seed_thoughts",
                        SemanticMemory.summary == fp,
                    )
                )
                if (exists.scalar() or 0) > 0:
                    skipped += 1
                    continue

            try:
                embedding = await _generate_embedding(content[:2000])
            except Exception as e:
                logger.warning("Embedding failed for thought %s: %s", t.id, e)
                embedding = [0.0] * 768
                errors += 1

            cat = t.category or "general"
            mem = SemanticMemory(
                content=content[:5000],
                summary=content[:100],
                category=f"thought_{cat}",
                embedding=embedding,
                importance=0.6,
                source="seed_thoughts",
                metadata_json={
                    "original_id": str(t.id),
                    "thought_category": cat,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                },
            )
            db.add(mem)
            seeded += 1
        await db.commit()

        # ── 2. Activities → semantic_memories ──
    activity_stmt = (
        select(ActivityLog)
        .where(
            ActivityLog.action.notin_(["skill.health_check", "heartbeat"]),
            ActivityLog.error_message.is_(None),
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    activities = (await db.execute(activity_stmt)).scalars().all()

    for i in range(0, len(activities), batch_size):
        batch = activities[i : i + batch_size]
        for a in batch:
            details = a.details or {}
            result_preview = details.get("result_preview", "")
            args_preview = details.get("args_preview", "")
            content = (
                f"Action: {a.action}"
                + (f" | Skill: {a.skill}" if a.skill else "")
                + (f" | {result_preview[:200]}" if result_preview else "")
                + (f" | Args: {args_preview[:100]}" if args_preview else "")
            )
            content = content.strip()
            if len(content) < 15:
                skipped += 1
                continue

            if skip_existing:
                fp = content[:100]
                exists = await db.execute(
                    select(func.count())
                    .select_from(SemanticMemory)
                    .where(
                        SemanticMemory.source == "seed_activities",
                        SemanticMemory.summary == fp,
                    )
                )
                if (exists.scalar() or 0) > 0:
                    skipped += 1
                    continue

            try:
                embedding = await _generate_embedding(content[:2000])
            except Exception as e:
                logger.warning("Embedding failed for activity %s: %s", a.id, e)
                embedding = [0.0] * 768
                errors += 1

            importance = 0.4
            if a.action.startswith("goal"):
                importance = 0.7
            elif a.action == "cron_execution":
                importance = 0.3
            elif not a.success:
                importance = 0.6

            mem = SemanticMemory(
                content=content[:5000],
                summary=content[:100],
                category="activity",
                embedding=embedding,
                importance=importance,
                source="seed_activities",
                metadata_json={
                    "original_id": str(a.id),
                    "action": a.action,
                    "skill": a.skill,
                    "success": a.success,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                },
            )
            db.add(mem)
            seeded += 1
        await db.commit()

    return {
        "seeded": seeded,
        "skipped": skipped,
        "errors": errors,
        "sources": {
            "thoughts": len(thoughts),
            "activities": len(activities),
        },
    }
