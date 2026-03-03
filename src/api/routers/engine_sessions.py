"""
Session History API — browse, search, and filter chat sessions.

Provides:
- GET /api/engine/sessions — paginated list with search/filter
- GET /api/engine/sessions/stats — aggregate statistics
- GET /api/engine/sessions/{session_id} — single session detail
- GET /api/engine/sessions/{session_id}/messages — session messages
- DELETE /api/engine/sessions/{session_id} — delete session
- DELETE /api/engine/sessions/ghosts — purge 0-message ghost sessions
- PATCH /api/engine/sessions/{session_id}/title — update session title
- POST /api/engine/sessions/{session_id}/archive — physically archive session
- POST /api/engine/sessions/{session_id}/end — end session
- POST /api/engine/sessions/cleanup — prune old sessions (>N days)
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, computed_field

from aria_engine.config import EngineConfig
from aria_engine.session_manager import NativeSessionManager

logger = logging.getLogger("aria.api.sessions")
router = APIRouter(
    prefix="/engine/sessions",
    tags=["engine-sessions"],
)


# ── Pydantic Models ──────────────────────────────────────────

class SessionResponse(BaseModel):
    """Session summary in list responses."""

    session_id: str
    title: str = "Untitled"
    agent_id: str = "unknown"
    session_type: str = "chat"
    model: str | None = None
    status: str = "active"
    message_count: int = 0
    created_at: str
    updated_at: str | None = None
    last_message_at: str | None = None
    metadata: dict[str, Any] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Alias for session_id — used by the frontend."""
        return self.session_id


class SessionListResponse(BaseModel):
    """Paginated session list."""

    sessions: list[SessionResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class MessageResponse(BaseModel):
    """Chat message in session view."""

    id: str
    session_id: str
    role: str
    content: str = ""
    thinking: str | None = None
    tool_calls: list | dict | None = None
    tool_results: list | dict | None = None
    tool_call_id: str | None = None
    client_message_id: str | None = None
    model: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str


class SessionDetailResponse(SessionResponse):
    """Full session detail with recent messages."""

    recent_messages: list[MessageResponse] = []


class SessionStatsResponse(BaseModel):
    """Aggregate session statistics."""

    total_sessions: int
    total_messages: int
    active_agents: int
    oldest_session: str | None = None
    newest_activity: str | None = None


# ── Helpers ───────────────────────────────────────────────────

_cached_manager: NativeSessionManager | None = None


async def _get_manager() -> NativeSessionManager:
    """Get NativeSessionManager instance (cached engine for connection pooling)."""
    global _cached_manager
    if _cached_manager is not None:
        return _cached_manager

    from sqlalchemy.ext.asyncio import create_async_engine

    config = EngineConfig()
    db_url = config.database_url
    # Use psycopg3 driver (same as the rest of the API)
    for prefix in ("postgresql://", "postgresql+asyncpg://", "postgres://"):
        if db_url.startswith(prefix):
            db_url = db_url.replace(prefix, "postgresql+psycopg://", 1)
            break
    db = create_async_engine(db_url, pool_size=5, max_overflow=10)
    _cached_manager = NativeSessionManager(db)
    return _cached_manager


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=SessionListResponse)
async def list_sessions(
    agent_id: str | None = Query(
        default=None,
        description="Filter by agent ID",
    ),
    session_type: str | None = Query(
        default=None,
        description="Filter by type (chat, roundtable, cron)",
    ),
    exclude_agent_sessions: bool = Query(
        default=False,
        description="When true, exclude cron/swarm/subagent sessions (show only interactive+roundtable)",
    ),
    search: str | None = Query(
        default=None,
        max_length=200,
        description="Search in titles and message content",
    ),
    date_from: str | None = Query(
        default=None,
        description="Start date (ISO format, e.g., 2025-01-01)",
    ),
    date_to: str | None = Query(
        default=None,
        description="End date (ISO format, e.g., 2025-12-31)",
    ),
    sort: str = Query(
        default="updated_at",
        description="Sort field (created_at, updated_at, title)",
    ),
    order: str = Query(
        default="desc",
        description="Sort order (asc, desc)",
    ),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    List chat sessions with filtering, search, and pagination.

    Supports:
    - Agent filtering: ?agent_id=aria-talk
    - Type filtering: ?session_type=chat
    - Full-text search: ?search=deployment (searches titles + messages)
    - Date range: ?date_from=2025-01-01&date_to=2025-01-31
    - Sort: ?sort=created_at&order=asc
    - Pagination: ?limit=20&offset=0
    """
    mgr = await _get_manager()

    # Pass standard filters to manager
    _AGENT_TYPES = ["cron", "swarm", "subagent"]
    result = await mgr.list_sessions(
        agent_id=agent_id,
        session_type=session_type,
        exclude_types=_AGENT_TYPES if exclude_agent_sessions else None,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
    )

    # Apply date range filter at API level
    # (kept out of manager to avoid over-complicating the SQL builder)
    if date_from or date_to:
        sessions = result["sessions"]
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from).replace(
                    tzinfo=timezone.utc
                )
                sessions = [
                    s
                    for s in sessions
                    if datetime.fromisoformat(s["created_at"]) >= dt_from
                ]
            except ValueError:
                raise HTTPException(
                    400, f"Invalid date_from format: {date_from}"
                )

        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to).replace(
                    tzinfo=timezone.utc,
                    hour=23,
                    minute=59,
                    second=59,
                )
                sessions = [
                    s
                    for s in sessions
                    if datetime.fromisoformat(s["created_at"]) <= dt_to
                ]
            except ValueError:
                raise HTTPException(
                    400, f"Invalid date_to format: {date_to}"
                )

        result["sessions"] = sessions
        result["total"] = len(sessions)

    return SessionListResponse(**result)


@router.get("/stats", response_model=SessionStatsResponse)
async def get_session_stats():
    """Get aggregate session statistics."""
    mgr = await _get_manager()
    stats = await mgr.get_stats()
    return SessionStatsResponse(**stats)


@router.get("/archived")
async def list_archived_sessions(
    agent_id: str | None = Query(default=None, description="Filter by agent ID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    List archived sessions.

    Archived sessions have been moved from the working tables to the archive
    tables. They no longer appear in the main session list or chat UI,
    but Aria can still browse them for historical context.
    """
    mgr = await _get_manager()
    result = await mgr.list_archived_sessions(
        limit=limit,
        offset=offset,
        agent_id=agent_id,
    )
    return result


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    """Get session details with recent messages."""
    mgr = await _get_manager()

    session = await mgr.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")

    # Get recent messages (last 10 for overview)
    messages = await mgr.get_messages(session_id, limit=10)

    return SessionDetailResponse(
        **session,
        recent_messages=[
            MessageResponse(**m) for m in messages
        ],
    )


@router.get(
    "/{session_id}/messages",
    response_model=list[MessageResponse],
)
async def get_session_messages(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    since: str | None = Query(
        default=None,
        description="Only messages after this ISO datetime",
    ),
):
    """
    Get all messages for a session.

    Supports pagination and since-filter for incremental loading.
    """
    mgr = await _get_manager()

    # Verify session exists
    session = await mgr.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Session {session_id} not found")

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, f"Invalid since format: {since}")

    messages = await mgr.get_messages(
        session_id=session_id,
        limit=limit,
        offset=offset,
        since=since_dt,
    )

    return [MessageResponse(**m) for m in messages]


# ── Static-path DELETE/POST before /{session_id} to avoid route shadowing ─

@router.delete("/ghosts")
async def purge_ghost_sessions(
    older_than_minutes: int = Query(
        default=15,
        ge=0,
        le=1440,
        description="Delete sessions with 0 messages older than N minutes (0 = all ghosts)",
    ),
):
    """
    Delete all sessions with 0 messages older than N minutes.

    Ghost sessions are created by cron tasks or page visits that never
    received a message. They are safe to purge — no data is lost.
    The background task runs this automatically every 10 minutes.
    """
    mgr = await _get_manager()
    deleted = await mgr.delete_ghost_sessions(older_than_minutes=older_than_minutes)
    logger.info("Ghost purge via API: deleted %d sessions (>%d min)", deleted, older_than_minutes)
    return {"status": "ok", "deleted": deleted, "older_than_minutes": older_than_minutes}


@router.post("/cleanup")
async def cleanup_sessions(
    days: int = Query(default=30, ge=1, le=365, description="Prune sessions inactive for this many days"),
    dry_run: bool = Query(default=True, description="If true, only count — don't delete"),
):
    """
    Archive + prune stale sessions older than N days (S-67 session auto-cleanup).

    Behavior:
    - stale sessions/messages are copied into internal archive tables
    - only then removed from working tables
    - archive tables are not exposed via API/UI yet
    """
    mgr = await _get_manager()
    result = await mgr.prune_old_sessions(days=days, dry_run=dry_run)
    logger.info(
        "Session cleanup: %s (days=%d, dry_run=%s)",
        result, days, dry_run,
    )
    return result


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its messages."""
    mgr = await _get_manager()

    deleted = await mgr.delete_session(session_id)
    if not deleted:
        raise HTTPException(404, f"Session {session_id} not found")

    return {"status": "deleted", "session_id": session_id}


@router.post("/{session_id}/end")
async def end_session(session_id: str):
    """
    Mark a session as ended.

    Does not delete — sets metadata.ended = true.
    """
    mgr = await _get_manager()

    ended = await mgr.end_session(session_id)
    if not ended:
        raise HTTPException(404, f"Session {session_id} not found")

    return {"status": "ended", "session_id": session_id}


class TitleUpdateRequest(BaseModel):
    """Request body for updating a session title."""
    title: str = Field(..., min_length=1, max_length=500)


class SessionUpdateRequest(BaseModel):
    """Request body for updating session fields (model, title)."""
    model: str | None = Field(default=None, description="LLM model to use for this session")
    title: str | None = Field(default=None, min_length=1, max_length=500, description="Session title")


async def _get_db_engine():
    """Get or create a cached async engine for direct ORM operations."""
    mgr = await _get_manager()
    return mgr._db  # reuse the same pooled engine


@router.patch("/{session_id}/title")
async def update_session_title(session_id: str, body: TitleUpdateRequest):
    """
    Update a session's title.

    Used by the frontend for auto-generated titles after first message exchange.
    Uses SQLAlchemy ORM — no raw SQL.
    """
    engine = await _get_db_engine()

    try:
        from db.models import EngineChatSession
    except ImportError:
        from .db.models import EngineChatSession

    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from sqlalchemy import select as _sel

    async with _AS(engine) as db:
        async with db.begin():
            result = await db.execute(
                _sel(EngineChatSession).where(
                    EngineChatSession.id == session_id
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                raise HTTPException(404, f"Session {session_id} not found")

            session.title = body.title
            session.updated_at = datetime.now(timezone.utc)

    logger.info("Title updated for session %s: %s", session_id, body.title[:60])
    return {"status": "updated", "session_id": session_id, "title": body.title}


@router.patch("/{session_id}")
async def update_session(session_id: str, body: SessionUpdateRequest):
    """
    Update session fields (model, title).

    Used by the frontend to persist model selector changes so that the
    correct LLM is used for subsequent messages in this session.
    """
    if body.model is None and body.title is None:
        raise HTTPException(400, "At least one of 'model' or 'title' must be provided")

    engine = await _get_db_engine()

    try:
        from db.models import EngineChatSession
    except ImportError:
        from .db.models import EngineChatSession

    from sqlalchemy.ext.asyncio import AsyncSession as _AS
    from sqlalchemy import select as _sel

    async with _AS(engine) as db:
        async with db.begin():
            result = await db.execute(
                _sel(EngineChatSession).where(
                    EngineChatSession.id == session_id
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                raise HTTPException(404, f"Session {session_id} not found")

            if body.model is not None:
                session.model = body.model
            if body.title is not None:
                session.title = body.title
            session.updated_at = datetime.now(timezone.utc)

    logger.info("Session %s updated: model=%s title=%s", session_id, body.model, body.title)
    return {"status": "updated", "session_id": session_id}


@router.post("/{session_id}/archive")
async def archive_session(session_id: str):
    """
    Physically archive a session.

    Copies session + all messages to archive tables, then removes from working
    tables. Archived sessions no longer appear in GET /sessions by default.
    Uses NativeSessionManager.archive_session() — ORM only, no raw SQL.
    """
    mgr = await _get_manager()
    archived = await mgr.archive_session(session_id)
    if not archived:
        raise HTTPException(404, f"Session {session_id} not found")
    logger.info("Physically archived session %s", session_id)
    return {"status": "archived", "session_id": session_id}


### SQL indexes for performance (add via Alembic migration)
_INDEXES_SQL = """
-- Session listing performance
CREATE INDEX IF NOT EXISTS idx_chat_sessions_agent_id
    ON aria_engine.chat_sessions (agent_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
    ON aria_engine.chat_sessions (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_type
    ON aria_engine.chat_sessions (session_type);

-- Message retrieval performance
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
    ON aria_engine.chat_messages (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_agent_id
    ON aria_engine.chat_messages (agent_id);

-- Full-text search (trigram for ILIKE)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_title_trgm
    ON aria_engine.chat_sessions
    USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chat_messages_content_trgm
    ON aria_engine.chat_messages
    USING gin (content gin_trgm_ops);
"""
