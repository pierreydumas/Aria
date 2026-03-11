"""
Native Session Manager — PostgreSQL-backed session lifecycle (ORM).

Uses SQLAlchemy ORM models (EngineChatSession, EngineChatMessage) instead of
raw SQL.  All schema-awareness comes from the model __table_args__.

Replaces aria_skills/session_manager with direct DB access:
- No sessions.json, no JSONL files
- Full CRUD via ORM on chat_sessions + chat_messages
- Native pagination, search, and filtering
- Backward-compatible method signatures
- Agent-scoped queries via agent_id parameter
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, insert, update, delete, func, and_, or_, cast, literal
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from aria_engine.session_titles import resolve_session_title
from db.models import (
    Base,
    EngineChatSession,
    EngineChatMessage,
    EngineChatSessionArchive,
    EngineChatMessageArchive,
)

logger = logging.getLogger("aria.engine.session_manager")

# Defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200
MAX_TITLE_LENGTH = 200
MAX_MESSAGE_LENGTH = 100_000  # 100KB per message


class NativeSessionManager:
    """
    PostgreSQL-backed session manager (ORM).

    Manages the full lifecycle of chat sessions and messages
    using aria_engine.chat_sessions and aria_engine.chat_messages.

    Usage:
        mgr = NativeSessionManager(db_engine)

        # Create session
        session = await mgr.create_session(
            agent_id="aria-talk",
            title="Morning chat",
        )

        # Add messages
        await mgr.add_message(
            session_id=session["session_id"],
            role="user",
            content="Hello!",
        )

        # Get full conversation
        messages = await mgr.get_messages(session["session_id"])

        # List sessions with search
        sessions = await mgr.list_sessions(
            agent_id="aria-talk",
            search="morning",
            limit=10,
        )
    """

    def __init__(self, db_engine: AsyncEngine):
        self._db = db_engine
        self._async_session = async_sessionmaker(
            db_engine, expire_on_commit=False,
        )

    # ── Session CRUD ──────────────────────────────────────────

    async def create_session(
        self,
        agent_id: str = "main",
        title: str | None = None,
        session_type: str = "chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new chat session.

        Args:
            agent_id: Owning agent ID.
            title: Session title (auto-generated if None).
            session_type: Type ('chat', 'roundtable', 'cron').
            metadata: Optional JSON metadata.

        Returns:
            Session dict with session_id, title, agent_id, etc.
        """
        session_id = str(uuid4())
        if not title:
            title = f"Session {session_id[:8]}"
        title = title[:MAX_TITLE_LENGTH]

        async with self._async_session() as session:
            async with session.begin():
                obj = EngineChatSession(
                    id=session_id,
                    title=title,
                    agent_id=agent_id,
                    session_type=session_type,
                    metadata_json=metadata or {},
                )
                session.add(obj)
                await session.flush()

                logger.info(
                    "Created session %s for %s: %s",
                    session_id, agent_id, title,
                )

                return {
                    "session_id": str(obj.id),
                    "title": resolve_session_title(
                        obj.title,
                        obj.session_type,
                        dict(obj.metadata_json) if obj.metadata_json else None,
                        obj.created_at,
                    ),
                    "agent_id": obj.agent_id,
                    "session_type": obj.session_type,
                    "created_at": obj.created_at.isoformat(),
                    "message_count": 0,
                }

    async def get_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """
        Get session details by ID.

        Returns:
            Session dict or None if not found.
        """
        stmt = (
            select(
                EngineChatSession,
                func.count(EngineChatMessage.id).label("message_count"),
                func.max(EngineChatMessage.created_at).label("last_message_at"),
            )
            .outerjoin(
                EngineChatMessage,
                EngineChatMessage.session_id == EngineChatSession.id,
            )
            .where(EngineChatSession.id == session_id)
            .group_by(EngineChatSession.id)
        )

        archive_stmt = (
            select(
                EngineChatSessionArchive,
                func.count(EngineChatMessageArchive.id).label("message_count"),
                func.max(EngineChatMessageArchive.created_at).label("last_message_at"),
            )
            .outerjoin(
                EngineChatMessageArchive,
                EngineChatMessageArchive.session_id == EngineChatSessionArchive.id,
            )
            .where(EngineChatSessionArchive.id == session_id)
            .group_by(EngineChatSessionArchive.id)
        )

        async with self._async_session() as session:
            result = await session.execute(stmt)
            row = result.first()

            if row:
                s = row[0]
                return {
                    "session_id": str(s.id),
                    "title": resolve_session_title(
                        s.title,
                        s.session_type,
                        dict(s.metadata_json) if s.metadata_json else None,
                        s.created_at,
                    ),
                    "agent_id": s.agent_id or "unknown",
                    "session_type": s.session_type,
                    "model": s.model,
                    "status": s.status or "active",
                    "metadata": dict(s.metadata_json) if s.metadata_json else None,
                    "message_count": row.message_count,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                    "last_message_at": (
                        row.last_message_at.isoformat()
                        if row.last_message_at
                        else None
                    ),
                    "source_table": "working",
                }

            archive_result = await session.execute(archive_stmt)
            archive_row = archive_result.first()

        if not archive_row:
            return None

        s = archive_row[0]
        return {
            "session_id": str(s.id),
            "title": resolve_session_title(
                s.title,
                s.session_type,
                dict(s.metadata_json) if s.metadata_json else None,
                s.created_at,
            ),
            "agent_id": s.agent_id or "unknown",
            "session_type": s.session_type,
            "model": s.model,
            "status": s.status or "archived",
            "metadata": dict(s.metadata_json) if s.metadata_json else None,
            "message_count": archive_row.message_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "last_message_at": (
                archive_row.last_message_at.isoformat()
                if archive_row.last_message_at
                else None
            ),
            "source_table": "archive",
        }

    async def list_sessions(
        self,
        agent_id: str | None = None,
        session_type: str | None = None,
        exclude_types: list[str] | None = None,
        search: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        sort: str = "updated_at",
        order: str = "desc",
    ) -> dict[str, Any]:
        """
        List sessions with filtering, search, and pagination.

        Args:
            agent_id: Filter by agent.
            session_type: Filter by type ('chat', 'roundtable', 'cron').
            exclude_types: Exclude sessions with these session_type values.
            search: Full-text search in title and messages.
            limit: Page size (max 100).
            offset: Offset for pagination.
            sort: Sort field ('created_at', 'updated_at', 'title').
            order: Sort order ('asc', 'desc').

        Returns:
            Dict with 'sessions' list, 'total' count, pagination info.
        """
        limit = min(max(limit, 1), MAX_PAGE_SIZE)

        # Validate sort
        allowed_sorts = {"created_at", "updated_at", "title"}
        if sort not in allowed_sorts:
            sort = "updated_at"
        if order not in ("asc", "desc"):
            order = "desc"

        # Build WHERE filters
        filters = []
        if agent_id:
            filters.append(EngineChatSession.agent_id == agent_id)
        if session_type:
            filters.append(EngineChatSession.session_type == session_type)
        if exclude_types:
            filters.append(EngineChatSession.session_type.not_in(exclude_types))
        if search:
            pattern = f"%{search}%"
            search_in_messages = (
                select(literal(1))
                .where(
                    and_(
                        EngineChatMessage.session_id == EngineChatSession.id,
                        EngineChatMessage.content.ilike(pattern),
                    )
                )
                .correlate(EngineChatSession)
                .exists()
            )
            filters.append(
                or_(
                    EngineChatSession.title.ilike(pattern),
                    search_in_messages,
                )
            )

        where = and_(*filters) if filters else True

        # Sort column
        sort_col = getattr(EngineChatSession, sort, EngineChatSession.updated_at)
        order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

        async with self._async_session() as session:
            # Count total
            count_stmt = (
                select(func.count())
                .select_from(EngineChatSession)
                .where(where)
            )
            total = (await session.execute(count_stmt)).scalar() or 0

            # Fetch page
            data_stmt = (
                select(
                    EngineChatSession,
                    func.count(EngineChatMessage.id).label("message_count"),
                    func.max(EngineChatMessage.created_at).label("last_message_at"),
                )
                .outerjoin(
                    EngineChatMessage,
                    EngineChatMessage.session_id == EngineChatSession.id,
                )
                .where(where)
                .group_by(EngineChatSession.id)
                .order_by(order_clause)
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(data_stmt)).all()

        sessions_list = []
        for row in rows:
            s = row[0]
            sessions_list.append({
                "session_id": str(s.id),
                "title": resolve_session_title(
                    s.title,
                    s.session_type,
                    dict(s.metadata_json) if s.metadata_json else None,
                    s.created_at,
                ),
                "agent_id": s.agent_id or "unknown",
                "session_type": s.session_type,
                "model": s.model,
                "status": s.status or "active",
                "metadata": dict(s.metadata_json) if s.metadata_json else None,
                "message_count": row.message_count,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "last_message_at": (
                    row.last_message_at.isoformat()
                    if row.last_message_at
                    else None
                ),
            })

        return {
            "sessions": sessions_list,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        }

    async def update_session(
        self,
        session_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update session title and/or metadata."""
        values: dict[str, Any] = {"updated_at": func.now()}

        if title is not None:
            values["title"] = title[:MAX_TITLE_LENGTH]
        if metadata is not None:
            values["metadata_json"] = metadata

        stmt = (
            update(EngineChatSession)
            .where(EngineChatSession.id == session_id)
            .values(**values)
            .returning(EngineChatSession.id)
        )

        async with self._async_session() as session:
            async with session.begin():
                result = await session.execute(stmt)
                if not result.first():
                    return None

        return await self.get_session(session_id)

    async def delete_session(
        self,
        session_id: str,
    ) -> bool:
        """
        Delete a session and all its messages.

        Uses CASCADE from chat_messages FK, but explicit delete
        handles cases where FK constraints don't exist yet.

        Returns:
            True if session existed and was deleted.
        """
        async with self._async_session() as session:
            async with session.begin():
                # Delete messages first (safe even with CASCADE)
                await session.execute(
                    delete(EngineChatMessage)
                    .where(EngineChatMessage.session_id == session_id)
                )

                result = await session.execute(
                    delete(EngineChatSession)
                    .where(EngineChatSession.id == session_id)
                    .returning(EngineChatSession.id)
                )
                deleted = result.first() is not None

        if deleted:
            logger.info("Deleted session %s", session_id)

        return deleted

    async def end_session(
        self,
        session_id: str,
    ) -> bool:
        """
        Mark a session as ended (set updated_at, add end marker).

        Does not delete — just marks as inactive.

        Returns:
            True if session exists.
        """
        stmt = (
            update(EngineChatSession)
            .where(EngineChatSession.id == session_id)
            .values(
                status="ended",
                ended_at=func.now(),
                updated_at=func.now(),
                metadata_json=func.coalesce(
                    EngineChatSession.metadata_json,
                    cast("{}", PG_JSONB),
                ).op("||")(cast({"ended": True}, PG_JSONB)),
            )
            .returning(EngineChatSession.id)
        )

        async with self._async_session() as session:
            async with session.begin():
                result = await session.execute(stmt)
                return result.first() is not None

    # ── Message Operations ────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Add a message to a session.

        Args:
            session_id: Session to add to.
            role: Message role ('user', 'assistant', 'system').
            content: Message content (max 100KB).
            agent_id: Agent that created the message.
            metadata: Optional JSON metadata (token_count, latency, etc).

        Returns:
            Message dict.

        Raises:
            EngineError: If session not found.
        """
        content = content[:MAX_MESSAGE_LENGTH]

        async with self._async_session() as session:
            async with session.begin():
                # Verify session exists
                check = await session.execute(
                    select(EngineChatSession.id)
                    .where(EngineChatSession.id == session_id)
                )
                if not check.first():
                    raise EngineError(f"Session {session_id} not found")

                # Build metadata with agent_id
                meta = dict(metadata) if metadata else {}
                if agent_id:
                    meta["agent_id"] = agent_id

                # Insert message
                msg = EngineChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    metadata_json=meta,
                )
                session.add(msg)
                await session.flush()

                # Touch session updated_at and increment message_count
                await session.execute(
                    update(EngineChatSession)
                    .where(EngineChatSession.id == session_id)
                    .values(
                        updated_at=func.now(),
                        message_count=EngineChatSession.message_count + 1,
                    )
                )

                return {
                    "id": str(msg.id),
                    "session_id": str(msg.session_id),
                    "role": msg.role,
                    "content": msg.content,
                    "agent_id": agent_id,
                    "created_at": msg.created_at.isoformat(),
                }

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get messages for a session, ordered chronologically.

        Args:
            session_id: Session ID.
            limit: Max messages to return.
            offset: Offset for pagination.
            since: Only return messages after this datetime.

        Returns:
            List of message dicts.
        """
        filters = [EngineChatMessage.session_id == session_id]
        if since:
            filters.append(EngineChatMessage.created_at > since)

        stmt = (
            select(EngineChatMessage)
            .where(and_(*filters))
            .order_by(EngineChatMessage.created_at.asc())
            .limit(min(limit, 500))
            .offset(offset)
        )

        archive_filters = [EngineChatMessageArchive.session_id == session_id]
        if since:
            archive_filters.append(EngineChatMessageArchive.created_at > since)

        archive_stmt = (
            select(EngineChatMessageArchive)
            .where(and_(*archive_filters))
            .order_by(EngineChatMessageArchive.created_at.asc())
            .limit(min(limit, 500))
            .offset(offset)
        )

        async with self._async_session() as session:
            result = await session.execute(stmt)
            messages = result.scalars().all()

            if not messages:
                working_exists_stmt = select(EngineChatSession.id).where(
                    EngineChatSession.id == session_id
                )
                working_exists = (await session.execute(working_exists_stmt)).scalar_one_or_none()
                if working_exists is None:
                    archive_result = await session.execute(archive_stmt)
                    messages = archive_result.scalars().all()

        return [
            {
                "id": str(m.id),
                "session_id": str(m.session_id),
                "role": m.role,
                "content": m.content or "",
                "thinking": m.thinking if hasattr(m, "thinking") else None,
                "tool_calls": m.tool_calls if hasattr(m, "tool_calls") else None,
                "tool_results": m.tool_results if hasattr(m, "tool_results") else None,
                "tool_call_id": (
                    (m.tool_results or {}).get("tool_call_id")
                    if hasattr(m, "tool_results") and isinstance(m.tool_results, dict)
                    else None
                ),
                "client_message_id": (
                    m.client_message_id
                    if hasattr(m, "client_message_id") and m.client_message_id
                    else ((m.metadata_json or {}).get("client_message_id") if m.metadata_json else None)
                ),
                "model": m.model if hasattr(m, "model") else None,
                "agent_id": (m.metadata_json or {}).get("agent_id"),
                "metadata": dict(m.metadata_json) if m.metadata_json else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]

    async def delete_message(
        self,
        message_id: int,
        session_id: str,
    ) -> bool:
        """Delete a single message (must match session_id for safety)."""
        stmt = (
            delete(EngineChatMessage)
            .where(
                and_(
                    EngineChatMessage.id == message_id,
                    EngineChatMessage.session_id == session_id,
                )
            )
            .returning(EngineChatMessage.id)
        )

        async with self._async_session() as session:
            async with session.begin():
                result = await session.execute(stmt)
                return result.first() is not None

    # ── Maintenance ───────────────────────────────────────────

    async def _ensure_archive_tables(self) -> None:
        """Create archive tables/indexes lazily if they do not exist yet."""
        async with self._db.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    bind=sync_conn,
                    tables=[
                        EngineChatSessionArchive.__table__,
                        EngineChatMessageArchive.__table__,
                    ],
                    checkfirst=True,
                )
            )

    async def prune_old_sessions(
        self,
        days: int = 30,
        dry_run: bool = False,
        max_age_hours: int | None = None,
    ) -> dict[str, Any]:
        """
        Archive + delete sessions older than N days (or hours if max_age_hours given).

        Also auto-closes any scoped/cron sessions that are still marked
        'active' but have not been updated in the last 2 hours (zombie sessions
        that never got end_session() called on them).

        Args:
            days: Sessions inactive for this many days are pruned.
            dry_run: If True, only count without deleting.
            max_age_hours: When set, overrides `days` with hour-level precision
                           (useful for sub-day cleanup thresholds like 1h or 6h).

        Returns:
            Dict with 'pruned_count', 'archived_count', 'message_count', and
            'zombies_closed'.
        """
        await self._ensure_archive_tables()

        # ── Step 0: auto-close zombie scoped/cron sessions ──────────────────
        zombie_cutoff = func.now() - func.make_interval(0, 0, 0, 0, 2)  # 2h
        zombie_stmt = (
            update(EngineChatSession)
            .where(
                EngineChatSession.status == "active",
                EngineChatSession.session_type.in_(["scoped", "cron"]),
                EngineChatSession.updated_at < zombie_cutoff,
            )
            .values(status="ended", ended_at=func.now(), updated_at=func.now())
            .returning(EngineChatSession.id)
        )

        zombies_closed = 0
        if not dry_run:
            async with self._async_session() as session:
                async with session.begin():
                    result = await session.execute(zombie_stmt)
                    zombies_closed = len(result.all())
            if zombies_closed:
                logger.info("prune_old_sessions: closed %d zombie sessions", zombies_closed)

        if max_age_hours is not None:
            cutoff = func.now() - func.make_interval(0, 0, 0, 0, max_age_hours)
        else:
            cutoff = func.now() - func.make_interval(0, 0, 0, days)

        # Find stale working sessions.
        stale_stmt = (
            select(
                EngineChatSession.id,
                func.count(EngineChatMessage.id).label("msg_count"),
            )
            .outerjoin(
                EngineChatMessage,
                EngineChatMessage.session_id == EngineChatSession.id,
            )
            .where(EngineChatSession.updated_at < cutoff)
            .group_by(EngineChatSession.id)
        )

        async with self._async_session() as session:
            async with session.begin():
                result = await session.execute(stale_stmt)
                stale = result.all()

                if dry_run or not stale:
                    return {
                        "pruned_count": len(stale),
                        "archived_count": len(stale),
                        "message_count": sum(r.msg_count for r in stale),
                        "zombies_closed": zombies_closed,
                        "dry_run": dry_run,
                    }

                stale_ids = [r.id for r in stale]

                # Archive sessions (idempotent by PK id).
                session_archive_select = (
                    select(
                        EngineChatSession.id,
                        EngineChatSession.agent_id,
                        EngineChatSession.session_type,
                        EngineChatSession.title,
                        EngineChatSession.system_prompt,
                        EngineChatSession.model,
                        EngineChatSession.temperature,
                        EngineChatSession.max_tokens,
                        EngineChatSession.context_window,
                        EngineChatSession.status,
                        EngineChatSession.message_count,
                        EngineChatSession.total_tokens,
                        EngineChatSession.total_cost,
                        EngineChatSession.metadata_json,
                        EngineChatSession.created_at,
                        EngineChatSession.updated_at,
                        EngineChatSession.ended_at,
                        func.now(),
                    )
                    .where(EngineChatSession.id.in_(stale_ids))
                )
                await session.execute(
                    pg_insert(EngineChatSessionArchive)
                    .from_select(
                        [
                            "id", "agent_id", "session_type", "title", "system_prompt", "model",
                            "temperature", "max_tokens", "context_window", "status", "message_count",
                            "total_tokens", "total_cost", "metadata", "created_at", "updated_at",
                            "ended_at", "archived_at",
                        ],
                        session_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Archive messages (idempotent by PK id).
                message_archive_select = (
                    select(
                        EngineChatMessage.id,
                        EngineChatMessage.session_id,
                        EngineChatMessage.agent_id,
                        EngineChatMessage.role,
                        EngineChatMessage.content,
                        EngineChatMessage.thinking,
                        EngineChatMessage.tool_calls,
                        EngineChatMessage.tool_results,
                        EngineChatMessage.client_message_id,
                        EngineChatMessage.model,
                        EngineChatMessage.tokens_input,
                        EngineChatMessage.tokens_output,
                        EngineChatMessage.cost,
                        EngineChatMessage.latency_ms,
                        EngineChatMessage.embedding,
                        EngineChatMessage.metadata_json,
                        EngineChatMessage.created_at,
                        func.now(),
                    )
                    .where(EngineChatMessage.session_id.in_(stale_ids))
                )
                await session.execute(
                    pg_insert(EngineChatMessageArchive)
                    .from_select(
                        [
                            "id", "session_id", "agent_id", "role", "content", "thinking",
                            "tool_calls", "tool_results", "client_message_id", "model", "tokens_input", "tokens_output",
                            "cost", "latency_ms", "embedding", "metadata", "created_at", "archived_at",
                        ],
                        message_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Delete messages
                msg_result = await session.execute(
                    delete(EngineChatMessage)
                    .where(EngineChatMessage.session_id.in_(stale_ids))
                )
                msg_count = msg_result.rowcount or 0

                # Delete sessions
                await session.execute(
                    delete(EngineChatSession)
                    .where(EngineChatSession.id.in_(stale_ids))
                )

        logger.info(
            "Pruned %d sessions after archive (%d messages, >%d days old)",
            len(stale_ids), msg_count, days,
        )

        return {
            "pruned_count": len(stale_ids),
            "archived_count": len(stale_ids),
            "message_count": msg_count,
            "zombies_closed": zombies_closed,
            "dry_run": False,
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get session statistics including ghost session count."""
        stmt = (
            select(
                func.count(func.distinct(EngineChatSession.id)).label("total_sessions"),
                func.count(EngineChatMessage.id).label("total_messages"),
                func.count(func.distinct(EngineChatSession.agent_id)).label("active_agents"),
                func.min(EngineChatSession.created_at).label("oldest_session"),
                func.max(EngineChatSession.updated_at).label("newest_activity"),
            )
            .select_from(EngineChatSession)
            .outerjoin(
                EngineChatMessage,
                EngineChatMessage.session_id == EngineChatSession.id,
            )
        )

        ghost_stmt = select(
            func.count(EngineChatSession.id).label("ghost_count")
        ).where(EngineChatSession.message_count == 0)

        async with self._async_session() as session:
            result = await session.execute(stmt)
            row = result.first()
            ghost_result = await session.execute(ghost_stmt)
            ghost_row = ghost_result.first()

        return {
            "total_sessions": row.total_sessions,
            "total_messages": row.total_messages,
            "active_agents": row.active_agents,
            "ghost_sessions": ghost_row.ghost_count if ghost_row else 0,
            "oldest_session": (
                row.oldest_session.isoformat()
                if row.oldest_session
                else None
            ),
            "newest_activity": (
                row.newest_activity.isoformat()
                if row.newest_activity
                else None
            ),
        }

    async def prune_sessions_by_type(
        self,
        session_type: str,
        days: int = 1,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Archive then delete sessions of a specific type older than N days.

        All pruned sessions (cron/swarm/subagent) are copied to the archive tables
        first so the full audit trail is preserved.  They are not visible in the
        normal session list — only accessible via roundtable/swarm audit queries.

        Args:
            session_type: Session type to target (e.g. ``"cron"``, ``"swarm"``).
            days: Sessions of this type inactive for this many days are removed.
            dry_run: If True, only count without deleting.

        Returns:
            Dict with ``pruned_count``, ``archived_count``, ``message_count`` and ``dry_run`` keys.
        """
        await self._ensure_archive_tables()

        cutoff = func.now() - func.make_interval(0, 0, 0, days)

        where_clause = and_(
            EngineChatSession.session_type == session_type,
            EngineChatSession.updated_at < cutoff,
        )

        async with self._async_session() as session:
            async with session.begin():
                # Get IDs to prune
                id_result = await session.execute(
                    select(EngineChatSession.id).where(where_clause)
                )
                stale_ids = [r[0] for r in id_result.all()]

                if not stale_ids:
                    return {"pruned_count": 0, "archived_count": 0, "message_count": 0, "dry_run": dry_run}

                if dry_run:
                    return {"pruned_count": len(stale_ids), "archived_count": 0, "message_count": 0, "dry_run": True}

                # Archive sessions → EngineChatSessionArchive
                session_archive_select = (
                    select(
                        EngineChatSession.id,
                        EngineChatSession.agent_id,
                        EngineChatSession.session_type,
                        EngineChatSession.title,
                        EngineChatSession.system_prompt,
                        EngineChatSession.model,
                        EngineChatSession.temperature,
                        EngineChatSession.max_tokens,
                        EngineChatSession.context_window,
                        EngineChatSession.status,
                        EngineChatSession.message_count,
                        EngineChatSession.total_tokens,
                        EngineChatSession.total_cost,
                        EngineChatSession.metadata_json,
                        EngineChatSession.created_at,
                        EngineChatSession.updated_at,
                        EngineChatSession.ended_at,
                        func.now(),
                    )
                    .where(EngineChatSession.id.in_(stale_ids))
                )
                await session.execute(
                    pg_insert(EngineChatSessionArchive)
                    .from_select(
                        [
                            "id", "agent_id", "session_type", "title", "system_prompt", "model",
                            "temperature", "max_tokens", "context_window", "status", "message_count",
                            "total_tokens", "total_cost", "metadata", "created_at", "updated_at",
                            "ended_at", "archived_at",
                        ],
                        session_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Archive messages → EngineChatMessageArchive
                message_archive_select = (
                    select(
                        EngineChatMessage.id,
                        EngineChatMessage.session_id,
                        EngineChatMessage.agent_id,
                        EngineChatMessage.role,
                        EngineChatMessage.content,
                        EngineChatMessage.thinking,
                        EngineChatMessage.tool_calls,
                        EngineChatMessage.tool_results,
                        EngineChatMessage.client_message_id,
                        EngineChatMessage.model,
                        EngineChatMessage.tokens_input,
                        EngineChatMessage.tokens_output,
                        EngineChatMessage.cost,
                        EngineChatMessage.latency_ms,
                        EngineChatMessage.embedding,
                        EngineChatMessage.metadata_json,
                        EngineChatMessage.created_at,
                        func.now(),
                    )
                    .where(EngineChatMessage.session_id.in_(stale_ids))
                )
                await session.execute(
                    pg_insert(EngineChatMessageArchive)
                    .from_select(
                        [
                            "id", "session_id", "agent_id", "role", "content", "thinking",
                            "tool_calls", "tool_results", "client_message_id", "model", "tokens_input", "tokens_output",
                            "cost", "latency_ms", "embedding", "metadata", "created_at", "archived_at",
                        ],
                        message_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Delete messages then sessions
                msg_result = await session.execute(
                    delete(EngineChatMessage)
                    .where(EngineChatMessage.session_id.in_(stale_ids))
                )
                msg_count = msg_result.rowcount or 0

                await session.execute(
                    delete(EngineChatSession)
                    .where(EngineChatSession.id.in_(stale_ids))
                )

        logger.info(
            "Type purge: archived+deleted %d '%s' sessions (%d messages, >%d days old)",
            len(stale_ids), session_type, msg_count, days,
        )
        return {"pruned_count": len(stale_ids), "archived_count": len(stale_ids), "message_count": msg_count, "dry_run": False}

    async def archive_session(self, session_id: str) -> bool:
        """
        Physically archive a session: copy session + messages to archive tables,
        then delete from working tables.

        Returns:
            True if session existed and was archived, False if not found.
        """
        await self._ensure_archive_tables()

        async with self._async_session() as session:
            async with session.begin():
                # Verify session exists first
                check = await session.execute(
                    select(EngineChatSession.id)
                    .where(EngineChatSession.id == session_id)
                )
                if not check.first():
                    return False

                # Copy session row to archive
                session_archive_select = (
                    select(
                        EngineChatSession.id,
                        EngineChatSession.agent_id,
                        EngineChatSession.session_type,
                        EngineChatSession.title,
                        EngineChatSession.system_prompt,
                        EngineChatSession.model,
                        EngineChatSession.temperature,
                        EngineChatSession.max_tokens,
                        EngineChatSession.context_window,
                        EngineChatSession.status,
                        EngineChatSession.message_count,
                        EngineChatSession.total_tokens,
                        EngineChatSession.total_cost,
                        EngineChatSession.metadata_json,
                        EngineChatSession.created_at,
                        EngineChatSession.updated_at,
                        EngineChatSession.ended_at,
                        func.now(),
                    )
                    .where(EngineChatSession.id == session_id)
                )
                await session.execute(
                    pg_insert(EngineChatSessionArchive)
                    .from_select(
                        [
                            "id", "agent_id", "session_type", "title", "system_prompt", "model",
                            "temperature", "max_tokens", "context_window", "status", "message_count",
                            "total_tokens", "total_cost", "metadata", "created_at", "updated_at",
                            "ended_at", "archived_at",
                        ],
                        session_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Copy messages to archive
                message_archive_select = (
                    select(
                        EngineChatMessage.id,
                        EngineChatMessage.session_id,
                        EngineChatMessage.agent_id,
                        EngineChatMessage.role,
                        EngineChatMessage.content,
                        EngineChatMessage.thinking,
                        EngineChatMessage.tool_calls,
                        EngineChatMessage.tool_results,
                        EngineChatMessage.client_message_id,
                        EngineChatMessage.model,
                        EngineChatMessage.tokens_input,
                        EngineChatMessage.tokens_output,
                        EngineChatMessage.cost,
                        EngineChatMessage.latency_ms,
                        EngineChatMessage.embedding,
                        EngineChatMessage.metadata_json,
                        EngineChatMessage.created_at,
                        func.now(),
                    )
                    .where(EngineChatMessage.session_id == session_id)
                )
                await session.execute(
                    pg_insert(EngineChatMessageArchive)
                    .from_select(
                        [
                            "id", "session_id", "agent_id", "role", "content", "thinking",
                            "tool_calls", "tool_results", "client_message_id", "model", "tokens_input", "tokens_output",
                            "cost", "latency_ms", "embedding", "metadata", "created_at", "archived_at",
                        ],
                        message_archive_select,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Delete messages then session from working tables
                await session.execute(
                    delete(EngineChatMessage)
                    .where(EngineChatMessage.session_id == session_id)
                )
                await session.execute(
                    delete(EngineChatSession)
                    .where(EngineChatSession.id == session_id)
                )

        logger.info("Archived session %s to archive tables", session_id)
        return True

    async def list_archived_sessions(
        self,
        limit: int = 200,
        offset: int = 0,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        List sessions that have been archived.

        Returns:
            Dict with 'sessions' list and 'total' count.
        """
        await self._ensure_archive_tables()

        filters = []
        if agent_id:
            filters.append(EngineChatSessionArchive.agent_id == agent_id)

        count_stmt = select(func.count(EngineChatSessionArchive.id))
        if filters:
            count_stmt = count_stmt.where(and_(*filters))

        stmt = (
            select(EngineChatSessionArchive)
            .where(and_(*filters)) if filters
            else select(EngineChatSessionArchive)
        )
        stmt = stmt.order_by(EngineChatSessionArchive.archived_at.desc()).limit(limit).offset(offset)

        async with self._async_session() as session:
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            result = await session.execute(stmt)
            rows = result.scalars().all()

        sessions = []
        for r in rows:
            sessions.append({
                "session_id": str(r.id),
                "agent_id": r.agent_id,
                "session_type": r.session_type,
                "title": resolve_session_title(
                    r.title,
                    r.session_type,
                    dict(r.metadata_json) if r.metadata_json else None,
                    r.created_at,
                ),
                "model": r.model,
                "status": r.status,
                "message_count": r.message_count,
                "total_tokens": r.total_tokens,
                "total_cost": float(r.total_cost) if r.total_cost else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "archived_at": r.archived_at.isoformat() if r.archived_at else None,
            })

        return {
            "sessions": sessions,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def delete_ghost_sessions(self, older_than_minutes: int = 15) -> int:
        """
        Delete sessions with 0 messages older than ``older_than_minutes``.

        These are sessions created by agents or page loads that never received
        a message. No archival — pure garbage collection.

        Args:
            older_than_minutes: Sessions with message_count=0 older than this
                are deleted. Pass 0 to delete all ghosts regardless of age.

        Returns:
            Number of sessions deleted.
        """
        async with self._async_session() as session:
            async with session.begin():
                if older_than_minutes > 0:
                    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
                    where_clause = and_(
                        EngineChatSession.message_count == 0,
                        EngineChatSession.created_at < cutoff,
                    )
                else:
                    where_clause = EngineChatSession.message_count == 0

                result = await session.execute(
                    delete(EngineChatSession)
                    .where(where_clause)
                    .returning(EngineChatSession.id)
                )
                deleted = len(result.all())

        if deleted:
            logger.info(
                "Ghost purge: deleted %d empty sessions (older_than=%d min)",
                deleted, older_than_minutes,
            )
        return deleted
