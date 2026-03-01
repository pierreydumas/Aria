"""
LLM Models CRUD Router — manage the model catalog stored in ``llm_models`` DB.

Endpoints:
  GET    /models/db                — list all models (with filtering)
  GET    /models/db/{model_id}     — get one model
  POST   /models/db                — create a new model
  PUT    /models/db/{model_id}     — update a model
  DELETE /models/db/{model_id}     — delete a model
  POST   /models/db/sync           — re-sync from models.yaml → DB
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("aria.api.models_crud")

router = APIRouter(tags=["Models DB"])


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class ModelCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=300)
    provider: str = Field(default="litellm", max_length=50)
    tier: str = Field(default="free", max_length=30)
    reasoning: bool = False
    vision: bool = False
    tool_calling: bool = False
    input_types: list[str] = Field(default=["text"])
    context_window: int = Field(default=8192, ge=1)
    max_tokens: int = Field(default=4096, ge=1)
    cost_input: float = 0.0
    cost_output: float = 0.0
    cost_cache_read: float = 0.0
    litellm_model: str | None = None
    litellm_api_key: str | None = None
    litellm_api_base: str | None = None
    route_skill: str | None = None
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 100
    extra: dict = Field(default_factory=dict)


class ModelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    tier: str | None = None
    reasoning: bool | None = None
    vision: bool | None = None
    tool_calling: bool | None = None
    input_types: list[str] | None = None
    context_window: int | None = None
    max_tokens: int | None = None
    cost_input: float | None = None
    cost_output: float | None = None
    cost_cache_read: float | None = None
    litellm_model: str | None = None
    litellm_api_key: str | None = None
    litellm_api_base: str | None = None
    route_skill: str | None = None
    aliases: list[str] | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    extra: dict | None = None


class ModelResponse(BaseModel):
    id: str
    name: str
    provider: str
    tier: str
    reasoning: bool
    vision: bool
    tool_calling: bool
    input_types: list[str]
    context_window: int
    max_tokens: int
    cost_input: float
    cost_output: float
    cost_cache_read: float
    litellm_model: str | None
    litellm_api_key_set: bool  # never expose raw key, just flag
    litellm_api_base: str | None
    route_skill: str | None
    aliases: list[str]
    enabled: bool
    sort_order: int
    app_managed: bool = False
    extra: dict
    created_at: str | None
    updated_at: str | None


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_db():
    try:
        from db import AsyncSessionLocal
    except ImportError:
        from .db import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        yield db


def _dt_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _row_to_response(row) -> ModelResponse:
    return ModelResponse(
        id=row.id,
        name=row.name,
        provider=row.provider,
        tier=row.tier,
        reasoning=row.reasoning,
        vision=row.vision,
        tool_calling=row.tool_calling,
        input_types=row.input_types or ["text"],
        context_window=row.context_window,
        max_tokens=row.max_tokens,
        cost_input=float(row.cost_input or 0),
        cost_output=float(row.cost_output or 0),
        cost_cache_read=float(row.cost_cache_read or 0),
        litellm_model=row.litellm_model,
        litellm_api_key_set=bool(row.litellm_api_key),
        litellm_api_base=row.litellm_api_base,
        route_skill=row.route_skill,
        aliases=row.aliases or [],
        enabled=row.enabled,
        sort_order=row.sort_order,
        app_managed=getattr(row, "app_managed", False) or False,
        extra=row.extra or {},
        created_at=_dt_iso_utc(row.created_at),
        updated_at=_dt_iso_utc(row.updated_at),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/models/db", response_model=list[ModelResponse])
async def list_models_db(
    provider: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
):
    """List all models from DB, with optional filtering."""
    from db.models import LlmModelEntry

    async for db in _get_db():
        q = select(LlmModelEntry).order_by(
            LlmModelEntry.sort_order.asc(),
            LlmModelEntry.name.asc(),
        )
        if provider is not None:
            q = q.where(LlmModelEntry.provider == provider)
        if tier is not None:
            q = q.where(LlmModelEntry.tier == tier)
        if enabled is not None:
            q = q.where(LlmModelEntry.enabled == enabled)

        result = await db.execute(q)
        rows = result.scalars().all()
        return [_row_to_response(r) for r in rows]


@router.get("/models/db/{model_id}", response_model=ModelResponse)
async def get_model_db(model_id: str):
    """Get a single model by ID."""
    from db.models import LlmModelEntry

    async for db in _get_db():
        result = await db.execute(
            select(LlmModelEntry).where(LlmModelEntry.id == model_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Model '{model_id}' not found")
        return _row_to_response(row)


@router.post("/models/db", response_model=ModelResponse, status_code=201)
async def create_model_db(body: ModelCreate):
    """Create a new LLM model entry."""
    from db.models import LlmModelEntry

    async for db in _get_db():
        existing = await db.execute(
            select(LlmModelEntry).where(LlmModelEntry.id == body.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Model '{body.id}' already exists")

        row = LlmModelEntry(**body.model_dump())
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


@router.put("/models/db/{model_id}", response_model=ModelResponse)
async def update_model_db(model_id: str, body: ModelUpdate):
    """Update an existing model. Only provided fields are changed."""
    from db.models import LlmModelEntry

    async for db in _get_db():
        result = await db.execute(
            select(LlmModelEntry).where(LlmModelEntry.id == model_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Model '{model_id}' not found")

        updates = body.model_dump(exclude_unset=True)
        for k, v in updates.items():
            setattr(row, k, v)
        row.app_managed = True
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        return _row_to_response(row)


@router.delete("/models/db/{model_id}")
async def delete_model_db(model_id: str):
    """Delete a model entry."""
    from db.models import LlmModelEntry

    async for db in _get_db():
        result = await db.execute(
            select(LlmModelEntry).where(LlmModelEntry.id == model_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, f"Model '{model_id}' not found")
        await db.delete(row)
        await db.commit()
        return {"status": "deleted", "model_id": model_id}


@router.post("/models/db/sync")
async def sync_models_db(force: bool = False):
    """Re-sync models.yaml → DB (upsert).

    Pass ``?force=true`` to overwrite app-managed rows.
    """
    try:
        from models_sync import sync_models_from_yaml
    except ImportError:
        from .models_sync import sync_models_from_yaml
    try:
        from db import AsyncSessionLocal
    except ImportError:
        from .db import AsyncSessionLocal

    stats = await sync_models_from_yaml(AsyncSessionLocal, force=force)
    return {"status": "synced", **stats}
