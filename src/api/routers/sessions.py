"""
Agent sessions endpoints - CRUD + stats.
Reads from agent_sessions (PostgreSQL-native). No external sync.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentSession, EngineChatMessage, EngineChatSession, ModelUsage
from deps import get_db, get_litellm_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateSession, UpdateSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sessions"])


# -- List sessions -----------------------------------------------------------

@router.get("/sessions")
async def get_agent_sessions(
    page: int = 1,
    limit: int = 25,
    status: str | None = None,
    agent_id: str | None = None,
    session_type: str | None = None,
    search: str | None = None,
    include_runtime_events: bool = False,
    include_cron_events: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List engine chat sessions with filtering, search, and pagination."""
    base = select(EngineChatSession).order_by(EngineChatSession.updated_at.desc())

    if not include_runtime_events:
        base = base.where(EngineChatSession.session_type != "skill_exec")
    if not include_cron_events:
        base = base.where(EngineChatSession.session_type != "cron")
    if status:
        base = base.where(EngineChatSession.status == status)
    if agent_id:
        base = base.where(EngineChatSession.agent_id == agent_id)
    if session_type:
        base = base.where(EngineChatSession.session_type == session_type)
    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                EngineChatSession.agent_id.ilike(pattern),
                EngineChatSession.title.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    rows = (await db.execute(stmt)).scalars().all()

    session_ids = [s.id for s in rows if getattr(s, "id", None) is not None]
    chat_tokens_by_session: dict[str, int] = {}
    if session_ids:
        chat_tokens_result = await db.execute(
            select(
                EngineChatMessage.session_id,
                func.coalesce(func.sum(func.coalesce(EngineChatMessage.tokens_output, 0)), 0).label("chat_tokens"),
            )
            .where(EngineChatMessage.session_id.in_(session_ids))
            .where(EngineChatMessage.role == "assistant")
            .where(
                or_(
                    EngineChatMessage.tool_results.is_not(None),
                    EngineChatMessage.tool_calls.is_(None),
                )
            )
            .group_by(EngineChatMessage.session_id)
        )
        chat_tokens_by_session = {
            str(row.session_id): int(row.chat_tokens or 0)
            for row in chat_tokens_result.all()
        }

    items = [
        _engine_session_to_dict(
            s,
            chat_tokens=chat_tokens_by_session.get(str(s.id), 0),
            model_tokens=int(s.total_tokens or 0),
        )
        for s in rows
    ]
    return build_paginated_response(items, total, page, limit)


# -- Hourly breakdown --------------------------------------------------------

@router.get("/sessions/hourly")
async def get_sessions_hourly(
    hours: int = 24,
    include_runtime_events: bool = False,
    include_cron_events: bool = False,
    status: str | None = None,
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Hourly session counts grouped by agent for time-series charts."""
    bounded_hours = max(1, min(int(hours), 168))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=bounded_hours)
    hour_bucket = func.date_trunc("hour", EngineChatSession.created_at).label("hour")

    hourly_stmt = (
        select(
            hour_bucket,
            EngineChatSession.agent_id,
            func.count(EngineChatSession.id).label("count"),
        )
        .where(EngineChatSession.created_at.is_not(None))
        .where(EngineChatSession.created_at >= cutoff)
    )

    if not include_runtime_events:
        hourly_stmt = hourly_stmt.where(EngineChatSession.session_type != "skill_exec")
    if not include_cron_events:
        hourly_stmt = hourly_stmt.where(EngineChatSession.session_type != "cron")
    if status:
        hourly_stmt = hourly_stmt.where(EngineChatSession.status == status)
    if agent_id:
        hourly_stmt = hourly_stmt.where(EngineChatSession.agent_id == agent_id)

    result = await db.execute(
        hourly_stmt
        .group_by(hour_bucket, EngineChatSession.agent_id)
        .order_by(hour_bucket.asc(), EngineChatSession.agent_id.asc())
    )

    items = [
        {
            "hour": _dt_iso_utc(row.hour),
            "agent_id": row.agent_id,
            "count": int(row.count or 0),
        }
        for row in result.all()
        if row.hour is not None
    ]

    return {"hours": bounded_hours, "timezone": "UTC", "items": items}


# -- Create session ----------------------------------------------------------

@router.post("/sessions")
async def create_agent_session(body: CreateSession, db: AsyncSession = Depends(get_db)):
    """Create a new chat session."""
    status_val = str(body.status or "active").strip().lower()
    allowed_status = {"active", "completed", "ended", "error"}
    if status_val not in allowed_status:
        status_val = "active"

    started_at = _parse_iso_dt(body.started_at)
    ended_at = _parse_iso_dt(body.ended_at)
    if status_val in {"completed", "ended", "error"} and ended_at is None:
        ended_at = datetime.now(timezone.utc)

    metadata_payload = body.metadata
    if not isinstance(metadata_payload, dict):
        metadata_payload = {}

    external_session_id = str(body.external_session_id or "").strip()
    if external_session_id:
        metadata_payload["external_session_id"] = external_session_id

    payload = {
        "id": uuid.uuid4(),
        "agent_id": body.agent_id,
        "session_type": body.session_type,
        "messages_count": body.messages_count,
        "tokens_used": body.tokens_used,
        "cost_usd": body.cost_usd,
        "status": status_val,
        "metadata_json": metadata_payload,
    }
    if started_at is not None:
        payload["started_at"] = started_at
    if ended_at is not None:
        payload["ended_at"] = ended_at

    session = AgentSession(**payload)
    db.add(session)
    await db.commit()
    return {"id": str(session.id), "created": True}


# -- Update session ----------------------------------------------------------

@router.patch("/sessions/{session_id}")
async def update_agent_session(
    session_id: str, body: UpdateSession, db: AsyncSession = Depends(get_db)
):
    """Update session status, metadata, or counters."""
    values = {}

    if body.status:
        values["status"] = body.status
        if body.status in ("completed", "ended", "error"):
            values["ended_at"] = text("NOW()")
    if body.messages_count is not None:
        values["messages_count"] = body.messages_count
    if body.tokens_used is not None:
        values["tokens_used"] = body.tokens_used
    if body.cost_usd is not None:
        values["cost_usd"] = body.cost_usd

    if values:
        await db.execute(
            update(AgentSession)
            .where(AgentSession.id == uuid.UUID(session_id))
            .values(**values)
        )
        await db.commit()
    return {"updated": True}


# -- Delete session ----------------------------------------------------------

@router.delete("/sessions/{session_id}")
async def delete_agent_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a session by ID."""
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session_id") from exc

    result = await db.execute(
        delete(AgentSession).where(AgentSession.id == session_uuid)
    )
    await db.commit()

    if not (result.rowcount or 0):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "id": session_id}


# -- Session stats -----------------------------------------------------------


def _engine_filters(include_cron=False, include_runtime=False, status=None, agent_id=None):
    """Build a list of WHERE clauses for EngineChatSession queries."""
    f = []
    if not include_runtime:
        f.append(EngineChatSession.session_type != "skill_exec")
    if not include_cron:
        f.append(EngineChatSession.session_type != "cron")
    if status:
        f.append(EngineChatSession.status == status)
    if agent_id:
        f.append(EngineChatSession.agent_id == agent_id)
    return f


def _apply(stmt, filters):
    for clause in filters:
        stmt = stmt.where(clause)
    return stmt


@router.get("/sessions/stats")
async def get_session_stats(
    include_runtime_events: bool = False,
    include_cron_events: bool = False,
    status: str | None = None,
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    litellm_db: AsyncSession = Depends(get_litellm_db),
):
    """Session statistics from engine chat sessions + LiteLLM."""
    filters = _engine_filters(include_cron_events, include_runtime_events, status, agent_id)

    total = (await db.execute(
        _apply(select(func.count(EngineChatSession.id)), filters)
    )).scalar() or 0

    active = (await db.execute(
        _apply(
            select(func.count(EngineChatSession.id)).where(EngineChatSession.status == "active"),
            filters,
        )
    )).scalar() or 0

    agg = (await db.execute(
        _apply(
            select(
                func.coalesce(func.sum(EngineChatSession.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(EngineChatSession.total_cost), 0).label("cost"),
            ),
            filters,
        )
    )).one()
    engine_tokens, engine_cost = int(agg.tokens), float(agg.cost)

    # LiteLLM aggregates
    llm = {"rows": 0, "tokens": 0, "cost": 0.0}
    try:
        r = (await litellm_db.execute(text(
            'SELECT COUNT(*) AS rows, COALESCE(SUM(total_tokens),0) AS tokens, '
            'COALESCE(SUM(spend),0) AS cost FROM "LiteLLM_SpendLogs"'
        ))).mappings().one()
        llm = {"rows": int(r["rows"]), "tokens": int(r["tokens"]), "cost": float(r["cost"])}
    except Exception as e:
        logger.warning("LiteLLM spend query failed: %s", e)

    # By agent (sessions + tokens + cost in one query)
    by_agent_result = await db.execute(
        _apply(
            select(
                EngineChatSession.agent_id,
                func.count(EngineChatSession.id).label("sessions"),
                func.coalesce(func.sum(EngineChatSession.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(EngineChatSession.total_cost), 0).label("cost"),
            ),
            filters,
        ).group_by(EngineChatSession.agent_id)
        .order_by(func.count(EngineChatSession.id).desc())
    )
    by_agent = [
        {"agent_id": r[0], "sessions": int(r[1]), "tokens": int(r[2]), "cost": float(r[3])}
        for r in by_agent_result.all()
    ]

    by_status_result = await db.execute(
        _apply(
            select(EngineChatSession.status, func.count(EngineChatSession.id)),
            filters,
        ).group_by(EngineChatSession.status)
    )
    by_status = [{"status": r[0], "count": r[1]} for r in by_status_result.all()]

    by_type_result = await db.execute(
        _apply(
            select(EngineChatSession.session_type, func.count(EngineChatSession.id)),
            filters,
        ).group_by(EngineChatSession.session_type)
    )
    by_type = [{"type": r[0], "count": r[1]} for r in by_type_result.all()]

    return {
        "total_sessions": total,
        "active_sessions": active,
        "total_tokens": engine_tokens + llm["tokens"],
        "total_cost": engine_cost + llm["cost"],
        "by_agent": by_agent,
        "by_status": by_status,
        "by_type": by_type,
        "litellm": llm,
        "sources": {
            "engine": {"tokens": engine_tokens, "cost": engine_cost},
            "litellm": {"tokens": llm["tokens"], "cost": llm["cost"]},
        },
    }


# -- Helpers -----------------------------------------------------------------

def _parse_iso_dt(value):
    """Parse an ISO datetime string, tolerating Z suffix."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _dt_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _session_to_dict(s):
    """Convert an AgentSession ORM object to a JSON-serializable dict."""
    return {
        "id": str(s.id),
        "agent_id": s.agent_id,
        "session_type": s.session_type,
        "started_at": _dt_iso_utc(s.started_at),
        "ended_at": _dt_iso_utc(s.ended_at),
        "messages_count": s.messages_count,
        "tokens_used": s.tokens_used,
        "cost_usd": float(s.cost_usd) if s.cost_usd else 0,
        "status": s.status,
        "metadata": s.metadata_json or {},
    }


def _engine_session_to_dict(s, chat_tokens: int | None = None, model_tokens: int | None = None):
    """Convert an EngineChatSession ORM object to a JSON-serializable dict."""
    resolved_model_tokens = int(s.total_tokens or 0) if model_tokens is None else int(model_tokens)
    resolved_chat_tokens = 0 if chat_tokens is None else int(chat_tokens)
    return {
        "id": str(s.id),
        "agent_id": s.agent_id,
        "session_type": s.session_type,
        "title": s.title,
        "model": s.model,
        "started_at": _dt_iso_utc(s.created_at),
        "ended_at": _dt_iso_utc(s.ended_at),
        "messages_count": s.message_count or 0,
        "tokens_used": resolved_model_tokens,
        "model_tokens": resolved_model_tokens,
        "chat_tokens": resolved_chat_tokens,
        "cost_usd": float(s.total_cost) if s.total_cost else 0,
        "status": s.status,
        "metadata": s.metadata_json or {},
    }
