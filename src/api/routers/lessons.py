"""
Lessons Learned endpoints — error recovery system (S5-02).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LessonLearned
from deps import get_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateLesson, UpdateLesson

router = APIRouter(tags=["Lessons"])
logger = logging.getLogger("aria.api.lessons")


# ── Known error patterns — seeded on first POST /lessons/seed ──────────────

_KNOWN_PATTERNS = [
    {"error_pattern": "api_429_rate_limit", "error_type": "rate_limit",
     "resolution": "Wait 60s, retry with different model via model_switcher"},
    {"error_pattern": "litellm_timeout", "error_type": "timeout",
     "resolution": "Downgrade to faster local model, reduce max_tokens"},
    {"error_pattern": "tool_hallucinated_function", "error_type": "validation",
     "resolution": "Re-read TOOLS.md, use only documented tool names"},
    {"error_pattern": "db_connection_refused", "error_type": "connection",
     "resolution": "Check aria-db container health, wait 10s and retry"},
    {"error_pattern": "embedding_model_unavailable", "error_type": "model",
     "resolution": "Fallback to keyword search instead of semantic search"},
]


@router.post("/lessons")
async def record_lesson(body: CreateLesson, db: AsyncSession = Depends(get_db)):
    """Record a new lesson or increment occurrence of existing one."""
    existing = await db.execute(
        select(LessonLearned).where(LessonLearned.error_pattern == body.error_pattern)
    )
    found = existing.scalar_one_or_none()

    if found:
        found.occurrences += 1
        found.last_occurred = func.now()
        if body.resolution:
            found.resolution = body.resolution
        await db.commit()
        return {"updated": True, "occurrences": found.occurrences, "id": str(found.id)}

    new_lesson = LessonLearned(
        error_pattern=body.error_pattern,
        error_type=body.error_type,
        resolution=body.resolution or "unresolved — needs investigation",
        skill_name=body.skill_name,
        context=body.context,
        resolution_code=body.resolution_code,
        effectiveness=body.effectiveness,
    )
    db.add(new_lesson)
    await db.commit()
    await db.refresh(new_lesson)
    return {"created": True, "id": str(new_lesson.id)}


@router.get("/lessons/check")
async def check_known_errors(
    error_type: str = None,
    skill_name: str = None,
    error_message: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Check if there's a known resolution for this error type."""
    stmt = select(LessonLearned)
    if error_type:
        stmt = stmt.where(LessonLearned.error_type == error_type)
    if skill_name:
        stmt = stmt.where(LessonLearned.skill_name == skill_name)
    stmt = stmt.order_by(LessonLearned.effectiveness.desc()).limit(5)

    result = await db.execute(stmt)
    lessons = result.scalars().all()
    return {
        "lessons": [l.to_dict() for l in lessons],
        "has_resolution": len(lessons) > 0,
    }


@router.get("/lessons")
async def list_lessons(
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """List all lessons learned, most recent first."""
    base = select(LessonLearned).order_by(LessonLearned.last_occurred.desc())
    total = (await db.execute(select(func.count(LessonLearned.id)))).scalar() or 0
    stmt, _ = paginate_query(base, page, per_page)
    result = await db.execute(stmt)
    items = [l.to_dict() for l in result.scalars().all()]
    return build_paginated_response(items, total, page, per_page)


@router.post("/lessons/seed")
async def seed_lessons(db: AsyncSession = Depends(get_db)):
    """Seed known error patterns (idempotent)."""
    created = 0
    for pattern in _KNOWN_PATTERNS:
        stmt = pg_insert(LessonLearned).values(**pattern).on_conflict_do_nothing(
            constraint="uq_lesson_pattern"
        )
        result = await db.execute(stmt)
        created += max(0, result.rowcount)
    await db.commit()
    return {"seeded": created, "total": len(_KNOWN_PATTERNS)}


@router.get("/lessons/dashboard")
async def get_lessons_dashboard(db: AsyncSession = Depends(get_db)):
    """Dashboard data: vis-network graph + stats + effectiveness distribution."""
    stmt = select(LessonLearned).order_by(LessonLearned.occurrences.desc()).limit(500)
    result = await db.execute(stmt)
    lessons = result.scalars().all()

    nodes: list[dict] = []
    edges: list[dict] = []
    skill_set: set = set()
    error_type_set: set = set()

    for ll in lessons:
        lesson_id = f"lesson_{ll.id}"
        nodes.append({
            "id": lesson_id,
            "label": (ll.error_pattern or "")[:40],
            "type": "lesson",
            "occurrences": ll.occurrences,
            "effectiveness": float(ll.effectiveness or 0),
            "resolution": ll.resolution,
        })
        skill = ll.skill_name or "unknown"
        if skill not in skill_set:
            nodes.append({"id": f"skill_{skill}", "label": skill, "type": "skill"})
            skill_set.add(skill)
        edges.append({"from": f"skill_{skill}", "to": lesson_id, "type": "produces"})

        etype = ll.error_type or "generic"
        if etype not in error_type_set:
            nodes.append({"id": f"etype_{etype}", "label": etype, "type": "error_type"})
            error_type_set.add(etype)
        edges.append({"from": lesson_id, "to": f"etype_{etype}", "type": "classified_as"})

    total = len(lessons)
    avg_eff = sum(float(ll.effectiveness or 0) for ll in lessons) / total if total else 0
    total_occ = sum(ll.occurrences for ll in lessons)

    top_patterns = [
        {
            "pattern": ll.error_pattern,
            "skill": ll.skill_name,
            "occurrences": ll.occurrences,
            "effectiveness": float(ll.effectiveness or 0),
        }
        for ll in lessons[:15]
    ]

    eff_buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for ll in lessons:
        e = float(ll.effectiveness or 0)
        if e < 0.2: eff_buckets["0.0-0.2"] += 1
        elif e < 0.4: eff_buckets["0.2-0.4"] += 1
        elif e < 0.6: eff_buckets["0.4-0.6"] += 1
        elif e < 0.8: eff_buckets["0.6-0.8"] += 1
        else: eff_buckets["0.8-1.0"] += 1

    skill_stats: dict = {}
    for ll in lessons:
        s = ll.skill_name or "unknown"
        skill_stats.setdefault(s, {"count": 0, "total_occ": 0, "avg_eff": 0.0})
        skill_stats[s]["count"] += 1
        skill_stats[s]["total_occ"] += ll.occurrences
        skill_stats[s]["avg_eff"] += float(ll.effectiveness or 0)
    for s in skill_stats:
        n = skill_stats[s]["count"]
        skill_stats[s]["avg_eff"] = round(skill_stats[s]["avg_eff"] / n, 3) if n else 0

    return {
        "graph": {"nodes": nodes, "edges": edges},
        "stats": {
            "total_lessons": total,
            "avg_effectiveness": round(avg_eff, 3),
            "total_occurrences": total_occ,
        },
        "top_patterns": top_patterns,
        "effectiveness_distribution": eff_buckets,
        "skill_breakdown": skill_stats,
    }


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(lesson_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LessonLearned).where(LessonLearned.id == lesson_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": lesson_id}


@router.patch("/lessons/{lesson_id}")
async def update_lesson(lesson_id: str, body: UpdateLesson, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LessonLearned).where(LessonLearned.id == lesson_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found")
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row.to_dict()
