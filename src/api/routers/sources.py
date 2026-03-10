"""
Website sources endpoints — curated source preferences and reviews.

Allows Aria (journalist focus, research skills) to manage a database of
preferred, cautionary, and avoided websites for knowledge-graph population
and semantic memory enrichment.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WebsiteSource
from deps import get_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateWebsiteSource, UpdateWebsiteSource

router = APIRouter(tags=["Sources"])
logger = logging.getLogger("aria.api.sources")


@router.get("/sources")
async def list_sources(
    page: int = 1,
    limit: int = 50,
    category: str | None = None,
    rating: str | None = None,
    q: str | None = Query(None, description="Search name/url/reason"),
    db: AsyncSession = Depends(get_db),
):
    """List website sources with optional filters."""
    base = select(WebsiteSource).order_by(WebsiteSource.updated_at.desc())
    if category:
        base = base.where(WebsiteSource.category == category)
    if rating:
        base = base.where(WebsiteSource.rating == rating)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            WebsiteSource.name.ilike(pattern)
            | WebsiteSource.url.ilike(pattern)
            | WebsiteSource.reason.ilike(pattern)
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [r.to_dict() for r in rows]
    return build_paginated_response(items, total, page, limit)


@router.get("/sources/stats/summary")
async def sources_stats(db: AsyncSession = Depends(get_db)):
    """Summary statistics for website sources."""
    total = (await db.execute(
        select(func.count()).select_from(WebsiteSource)
    )).scalar() or 0

    by_rating = {}
    for row in (await db.execute(
        select(WebsiteSource.rating, func.count()).group_by(WebsiteSource.rating)
    )).all():
        by_rating[row[0]] = row[1]

    by_category = {}
    for row in (await db.execute(
        select(WebsiteSource.category, func.count()).group_by(WebsiteSource.category)
    )).all():
        by_category[row[0]] = row[1]

    return {
        "total": total,
        "by_rating": by_rating,
        "by_category": by_category,
    }


@router.get("/sources/{source_id}")
async def get_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single website source by ID."""
    row = (await db.execute(
        select(WebsiteSource).where(WebsiteSource.id == source_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    return row.to_dict()


@router.post("/sources")
async def create_source(body: CreateWebsiteSource, db: AsyncSession = Depends(get_db)):
    """Create or upsert a website source (unique by URL)."""
    # Check for existing URL — upsert if found
    existing = (await db.execute(
        select(WebsiteSource).where(WebsiteSource.url == body.url)
    )).scalar_one_or_none()

    if existing:
        # Upsert: update existing record
        existing.name = body.name
        existing.category = body.category
        existing.rating = body.rating
        existing.reason = body.reason
        existing.alternative = body.alternative
        if body.last_used:
            try:
                existing.last_used = datetime.fromisoformat(body.last_used.replace("Z", "+00:00"))
            except ValueError:
                pass
        existing.metadata_json = body.metadata
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return {"id": str(existing.id), "created": False, "updated": True}

    row = WebsiteSource(
        id=uuid.uuid4(),
        url=body.url,
        name=body.name,
        category=body.category,
        rating=body.rating,
        reason=body.reason,
        alternative=body.alternative,
        metadata_json=body.metadata,
    )
    if body.last_used:
        try:
            row.last_used = datetime.fromisoformat(body.last_used.replace("Z", "+00:00"))
        except ValueError:
            pass
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "created": True, "updated": False}


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str, body: UpdateWebsiteSource, db: AsyncSession = Depends(get_db),
):
    """Update a website source."""
    row = (await db.execute(
        select(WebsiteSource).where(WebsiteSource.id == source_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "last_used" and value:
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
        if key == "metadata":
            setattr(row, "metadata_json", value)
        else:
            setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row.to_dict()


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a website source."""
    row = (await db.execute(
        select(WebsiteSource).where(WebsiteSource.id == source_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": source_id}
