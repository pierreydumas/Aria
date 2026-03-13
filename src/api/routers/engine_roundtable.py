"""
Engine Roundtable API — REST endpoints for multi-agent roundtable discussions.

Endpoints:
  POST   /api/engine/roundtable                — start a new roundtable discussion
  GET    /api/engine/roundtable                — list recent roundtables (paginated)
  GET    /api/engine/roundtable/{session_id}   — get roundtable detail (turns, synthesis)
  GET    /api/engine/roundtable/{session_id}/turns — stream-friendly turn list
  DELETE /api/engine/roundtable/{session_id}   — end/archive a roundtable

Wires aria_engine/roundtable.py (Roundtable class) into the REST layer.
"""
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy import func, select, delete, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker
from starlette.websockets import WebSocketDisconnect, WebSocketState

from db.models import (
    EngineChatSession,
    EngineChatMessage,
    EngineAgentState,
    EngineChatSessionArchive,
    EngineChatMessageArchive,
)
from aria_engine.roundtable import Roundtable, RoundtableResult

logger = logging.getLogger("aria.api.engine_roundtable")

router = APIRouter(prefix="/engine/roundtable", tags=["Engine Roundtable"])
ws_router = APIRouter(tags=["Engine Roundtable WebSocket"])


# ── Pydantic Models ──────────────────────────────────────────────────────────


class StartRoundtableRequest(BaseModel):
    """Request body for starting a new roundtable discussion."""
    topic: str = Field(..., min_length=2, max_length=2000, description="Discussion topic")
    agent_ids: list[str] = Field(
        ..., min_length=2, max_length=10,
        description="Agent IDs to participate (min 2)"
    )
    rounds: int = Field(default=3, ge=1, le=10, description="Number of rounds")
    synthesizer_id: str = Field(default="main", description="Agent ID for final synthesis")
    agent_timeout: int = Field(default=60, ge=10, le=300, description="Seconds per agent")
    total_timeout: int = Field(default=300, ge=30, le=900, description="Max total seconds")


class RoundtableTurnResponse(BaseModel):
    """A single turn in a roundtable discussion."""
    agent_id: str
    round: int
    content: str
    duration_ms: int


class RoundtableResponse(BaseModel):
    """Full response for a completed roundtable."""
    session_id: str
    topic: str
    participants: list[str]
    rounds: int
    turn_count: int
    synthesis: str
    synthesizer_id: str
    total_duration_ms: int
    chunked_mode: bool = False
    chunk_count: int = 0
    chunk_notice: str | None = None
    chunk_kind: str | None = None
    created_at: str
    turns: list[RoundtableTurnResponse] = Field(default_factory=list)


class RoundtableSummary(BaseModel):
    """Summary for list endpoints."""
    session_id: str
    session_type: str | None = None
    source: str | None = None
    title: str | None = None
    participants: list[str] = Field(default_factory=list)
    message_count: int = 0
    created_at: str | None = None


# Title patterns that identify cron-triggered roundtable sessions.
_ROUNDTABLE_TITLE_PATTERNS = ("Roundtable:%", "%Roundtable Architecture Review%")
# Session types that are NOT real roundtable parent sessions (sub-agent work).
_EXCLUDED_CRON_RT_TYPES = ("scoped",)


def _roundtable_filter(model, allowed_types: tuple[str, ...]):
    """Build an OR filter: session_type in *allowed_types* OR title matches roundtable patterns."""
    title_clauses = [
        and_(
            model.title.ilike(pat),
            model.session_type.not_in(_EXCLUDED_CRON_RT_TYPES),
        )
        for pat in _ROUNDTABLE_TITLE_PATTERNS
    ]
    return or_(model.session_type.in_(allowed_types), *title_clauses)


async def _load_any_session(
    db: AsyncSession,
    session_id: str,
    allowed_types: tuple[str, ...],
    *,
    include_cron_roundtables: bool = False,
) -> tuple[Any, bool]:
    """Load session row from working first, then archive; returns (row, is_archived)."""
    def _where(model):
        if include_cron_roundtables:
            return and_(model.id == session_id, _roundtable_filter(model, allowed_types))
        return and_(model.id == session_id, model.session_type.in_(allowed_types))

    working_result = await db.execute(select(EngineChatSession).where(_where(EngineChatSession)))
    working_row = working_result.scalar_one_or_none()
    if working_row is not None:
        return working_row, False

    archive_result = await db.execute(select(EngineChatSessionArchive).where(_where(EngineChatSessionArchive)))
    archive_row = archive_result.scalar_one_or_none()
    if archive_row is not None:
        return archive_row, True

    return None, False


async def _load_messages_for_session(
    db: AsyncSession,
    session_id: str,
    from_archive: bool,
) -> list[Any]:
    """Load ordered messages for a session from working or archive table."""
    model = EngineChatMessageArchive if from_archive else EngineChatMessage
    stmt = (
        select(model)
        .where(model.session_id == session_id)
        .order_by(model.created_at.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def _build_cron_roundtable_detail(
    db: AsyncSession,
    session_row: Any,
    messages: list[Any],
    is_archived: bool,
) -> dict[str, Any]:
    """Build roundtable detail from a cron-triggered session.

    Cron roundtables use normal chat messages (user/assistant/tool) instead
    of the structured round-N / synthesis roles.  We reconstruct:

    * **participants** — extracted from tool-result payloads that contain
      sub-agent ``session_id`` + ``focus`` fields.
    * **turns** — the longest assistant response from each sub-agent session.
    * **synthesis** — the last substantial assistant message in the parent session.
    """
    sub_sessions: dict[str, str] = {}  # sub-session-id → focus/display_name
    synthesis = ""

    for msg in messages:
        if msg.role == "tool" and msg.content:
            try:
                payload = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                sid = data.get("session_id")
                focus = data.get("focus") or data.get("display_name")
                if sid and focus and "status" not in data:
                    sub_sessions[sid] = focus
            except (json.JSONDecodeError, AttributeError):
                pass
        elif msg.role == "assistant" and msg.content and len(msg.content) > 200:
            synthesis = msg.content  # keep overwriting; last long one wins

    participants = sorted(set(sub_sessions.values()))
    turns: list[dict[str, Any]] = []

    # Load the primary contribution from each sub-agent session
    if sub_sessions:
        MsgModel = EngineChatMessageArchive if is_archived else EngineChatMessage
        SessModel = EngineChatSessionArchive if is_archived else EngineChatSession
        for sub_id, focus in sub_sessions.items():
            stmt = (
                select(MsgModel.content)
                .where(
                    and_(
                        MsgModel.session_id == sub_id,
                        MsgModel.role == "assistant",
                        func.length(MsgModel.content) > 100,
                    )
                )
                .order_by(func.length(MsgModel.content).desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            content = res.scalar_one_or_none()
            if content:
                turns.append({
                    "agent_id": focus,
                    "round": 1,
                    "content": content,
                    "duration_ms": 0,
                })

    return {
        "session_id": str(session_row.id),
        "topic": (session_row.title or ""),
        "participants": participants,
        "rounds": 1 if turns else 0,
        "turn_count": len(turns),
        "synthesis": synthesis,
        "synthesizer_id": "aria",
        "total_duration_ms": 0,
        "chunked_mode": False,
        "chunk_count": 0,
        "chunk_notice": None,
        "chunk_kind": None,
        "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "turns": turns,
    }


class PaginatedRoundtables(BaseModel):
    """Paginated list of roundtables."""
    items: list[RoundtableSummary]
    total: int
    page: int
    page_size: int
    has_more: bool = False


class RoundtableStatusResponse(BaseModel):
    """Status of a running or completed roundtable."""
    session_id: str
    status: str  # "running" | "completed" | "failed"
    topic: str | None = None
    participants: list[str] = Field(default_factory=list)
    turn_count: int = 0
    message: str | None = None


# ── Dependency Injection ─────────────────────────────────────────────────────

_roundtable: Roundtable | None = None
_db_engine: AsyncEngine | None = None
_db_session: async_sessionmaker | None = None

# In-memory tracking of running roundtable tasks
_running: dict[str, dict[str, Any]] = {}
_completed: dict[str, RoundtableResult] = {}


def configure_roundtable(
    roundtable: Roundtable,
    db_engine: AsyncEngine,
) -> None:
    """Called from main.py lifespan to inject instances."""
    global _roundtable, _db_engine, _db_session
    _roundtable = roundtable
    _db_engine = db_engine
    _db_session = async_sessionmaker(db_engine, expire_on_commit=False)
    logger.info("Roundtable router configured")


def _get_roundtable() -> Roundtable:
    if _roundtable is None:
        raise HTTPException(status_code=503, detail="Roundtable engine not initialized")
    return _roundtable


async def _validate_requested_agents(agent_ids: list[str]) -> None:
    """Ensure requested agents are runnable; auto-heal transient error states."""
    if _db_session is None:
        return

    normalized = [str(a).strip() for a in agent_ids if str(a).strip()]
    if not normalized:
        raise HTTPException(status_code=400, detail="No valid agent_ids provided")

    healed: list[str] = []

    async with _db_session() as session:
        stmt = select(EngineAgentState).where(EngineAgentState.agent_id.in_(normalized))
        result = await session.execute(stmt)
        rows = result.scalars().all()

        for row in rows:
            status = (row.status or "").lower()
            enabled = row.enabled is not False
            if enabled and status == "error":
                row.status = "idle"
                row.consecutive_failures = 0
                row.current_task = None
                row.current_session_id = None
                healed.append(row.agent_id)

        if healed:
            await session.commit()
            logger.warning(
                "Auto-healed agents from error->idle before roundtable/swarm: %s",
                ", ".join(sorted(healed)),
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

    by_id = {row.agent_id: row for row in rows}
    missing = [agent_id for agent_id in normalized if agent_id not in by_id]
    disabled = []
    unavailable = []

    for agent_id in normalized:
        row = by_id.get(agent_id)
        if row is None:
            continue
        status = (row.status or "").lower()
        enabled = row.enabled is not False
        if not enabled or status in {"disabled", "terminated"}:
            disabled.append(agent_id)
        elif status in {"error"} and agent_id not in healed:
            logger.warning(
                "Agent %s still reports status=error; continuing roundtable/swarm preflight",
                agent_id,
            )

    if missing or disabled or unavailable:
        problems: list[str] = []
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if disabled:
            problems.append(f"disabled: {', '.join(disabled)}")
        if unavailable:
            problems.append(f"unavailable: {', '.join(unavailable)}")
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested agents are not runnable ("
                + "; ".join(problems)
                + "). Enable/fix them in Agents DB before starting roundtable/swarm."
            ),
        )


# ── Background task runner ───────────────────────────────────────────────────

async def _run_roundtable_task(
    request: StartRoundtableRequest,
    roundtable: Roundtable,
) -> None:
    """Run a roundtable in the background and store the result."""
    # Generate a predictable session_id prefix so we can track it
    import hashlib
    key = hashlib.sha256(f"{request.topic}:{','.join(request.agent_ids)}".encode()).hexdigest()[:16]

    try:
        _running[key] = {"status": "running", "topic": request.topic, "participants": request.agent_ids}

        result = await roundtable.discuss(
            topic=request.topic,
            agent_ids=request.agent_ids,
            rounds=request.rounds,
            synthesizer_id=request.synthesizer_id,
            agent_timeout=request.agent_timeout,
            total_timeout=request.total_timeout,
        )

        _completed[result.session_id] = result
        _running[key] = {"status": "completed", "session_id": result.session_id}
        logger.info("Roundtable completed: %s (%d turns)", result.session_id, result.turn_count)

    except Exception as e:
        logger.error("Roundtable failed: %s", e)
        _running[key] = {"status": "failed", "error": str(e)}


# ── REST Endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=RoundtableResponse, status_code=201)
async def start_roundtable(
    body: StartRoundtableRequest,
    roundtable: Roundtable = Depends(_get_roundtable),
):
    """
    Start a new roundtable discussion (synchronous — waits for completion).

    Runs all rounds + synthesis, then returns the full result.
    For large discussions, use the /async endpoint instead.
    """
    try:
        await _validate_requested_agents(body.agent_ids)
        result = await roundtable.discuss(
            topic=body.topic,
            agent_ids=body.agent_ids,
            rounds=body.rounds,
            synthesizer_id=body.synthesizer_id,
            agent_timeout=body.agent_timeout,
            total_timeout=body.total_timeout,
        )

        _completed[result.session_id] = result

        return RoundtableResponse(
            session_id=result.session_id,
            topic=result.topic,
            participants=result.participants,
            rounds=result.rounds,
            turn_count=result.turn_count,
            synthesis=result.synthesis,
            synthesizer_id=result.synthesizer_id,
            total_duration_ms=result.total_duration_ms,
            chunked_mode=bool(getattr(result, "chunked_mode", False)),
            chunk_count=int(getattr(result, "chunk_count", 0) or 0),
            chunk_notice=getattr(result, "chunk_notice", None),
            chunk_kind=getattr(result, "chunk_kind", None),
            created_at=result.created_at.isoformat(),
            turns=[
                RoundtableTurnResponse(
                    agent_id=t.agent_id,
                    round=t.round_number,
                    content=t.content,
                    duration_ms=t.duration_ms,
                )
                for t in result.turns
            ],
        )
    except Exception as e:
        logger.error("Roundtable failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async", response_model=RoundtableStatusResponse, status_code=202)
async def start_roundtable_async(
    body: StartRoundtableRequest,
    background_tasks: BackgroundTasks,
    roundtable: Roundtable = Depends(_get_roundtable),
):
    """
    Start a roundtable in the background (non-blocking).

    Returns immediately with a tracking key. Poll /status/{key} to check.
    """
    import hashlib
    await _validate_requested_agents(body.agent_ids)
    key = hashlib.sha256(f"{body.topic}:{','.join(body.agent_ids)}".encode()).hexdigest()[:16]

    background_tasks.add_task(_run_roundtable_task, body, roundtable)

    return RoundtableStatusResponse(
        session_id=key,
        status="running",
        topic=body.topic,
        participants=body.agent_ids,
        message="Roundtable started in background. Poll GET /engine/roundtable/status/{session_id}",
    )


@router.get("", response_model=PaginatedRoundtables)
async def list_roundtables(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    roundtable: Roundtable = Depends(_get_roundtable),
):
    """
    List recent roundtable sessions with pagination.
    """
    offset = (page - 1) * page_size

    try:
        if _db_session is None:
            rows = await roundtable.list_roundtables(limit=page_size, offset=offset)
            return PaginatedRoundtables(
                items=[
                    RoundtableSummary(
                        session_id=r["session_id"],
                        session_type="roundtable",
                        source="working",
                        title=r.get("title"),
                        participants=r.get("participants", []),
                        message_count=r.get("message_count", 0),
                        created_at=r.get("created_at"),
                    )
                    for r in rows
                ],
                total=len(rows),
                page=page,
                page_size=page_size,
                has_more=len(rows) >= page_size,
            )

        async with _db_session() as session:
            allowed_types = ["roundtable", "swarm"]
            _wf = _roundtable_filter(EngineChatSession, tuple(allowed_types))
            _af = _roundtable_filter(EngineChatSessionArchive, tuple(allowed_types))

            working_count_stmt = select(func.count(EngineChatSession.id)).where(_wf)
            archive_count_stmt = select(func.count(EngineChatSessionArchive.id)).where(_af)
            working_count_res = await session.execute(working_count_stmt)
            archive_count_res = await session.execute(archive_count_stmt)
            total = (working_count_res.scalar() or 0) + (archive_count_res.scalar() or 0)

            # S-164: Push ORDER BY + LIMIT to DB to avoid loading all sessions
            fetch_limit = offset + page_size
            working_stmt = (
                select(EngineChatSession)
                .where(_wf)
                .order_by(EngineChatSession.created_at.desc())
                .limit(fetch_limit)
            )
            archive_stmt = (
                select(EngineChatSessionArchive)
                .where(_af)
                .order_by(EngineChatSessionArchive.created_at.desc())
                .limit(fetch_limit)
            )

            working_res = await session.execute(working_stmt)
            archive_res = await session.execute(archive_stmt)
            merged_rows = [
                *[(row, False) for row in working_res.scalars().all()],
                *[(row, True) for row in archive_res.scalars().all()],
            ]

            merged_rows.sort(
                key=lambda pair: pair[0].created_at or pair[0].updated_at,
                reverse=True,
            )
            page_rows = merged_rows[offset: offset + page_size]

            items: list[RoundtableSummary] = []
            for row, is_archived in page_rows:
                metadata = row.metadata_json or {}
                participants = metadata.get("participants", []) if isinstance(metadata, dict) else []
                items.append(
                    RoundtableSummary(
                        session_id=str(row.id),
                        session_type=row.session_type,
                        source="archive" if is_archived else "working",
                        title=row.title,
                        participants=participants,
                        message_count=int(row.message_count or 0),
                        created_at=row.created_at.isoformat() if row.created_at else None,
                    )
                )

        return PaginatedRoundtables(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )
    except Exception as e:
        logger.error("List roundtables failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Static paths MUST come before /{session_id} to avoid route collision ─────


@router.get("/agents/available")
async def get_available_agents():
    """Get list of agents available for roundtable participation."""
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with _db_session() as session:
            stmt = (
                select(EngineAgentState)
                .where(
                    and_(
                        EngineAgentState.status.notin_(["terminated", "disabled"]),
                        EngineAgentState.enabled.is_(True),
                    )
                )
                .order_by(EngineAgentState.pheromone_score.desc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return {
            "agents": [
                {
                    "agent_id": r.agent_id,
                    "display_name": r.display_name,
                    "agent_type": r.agent_type,
                    "status": r.status,
                    "focus_type": r.focus_type,
                    "pheromone_score": float(r.pheromone_score) if r.pheromone_score else 0.0,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error("Get available agents failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{key}")
async def get_roundtable_status(key: str):
    """Check status of an async roundtable started via /async."""
    if key in _running:
        info = _running[key]
        return RoundtableStatusResponse(
            session_id=info.get("session_id", key),
            status=info["status"],
            topic=info.get("topic"),
            participants=info.get("participants", []),
            message=info.get("error"),
        )

    # Maybe it just finished and the key matches a session_id
    if key in _completed:
        return RoundtableStatusResponse(
            session_id=key,
            status="completed",
            topic=_completed[key].topic,
            participants=_completed[key].participants,
            turn_count=_completed[key].turn_count,
        )

    raise HTTPException(status_code=404, detail=f"No roundtable tracking for key: {key}")


# ── Parameterized paths /{session_id} ────────────────────────────────────────


@router.get("/{session_id}")
async def get_roundtable(session_id: str):
    """
    Get roundtable detail — turns, synthesis, metadata.

    First checks in-memory cache of recently completed roundtables,
    then falls back to DB query.
    """
    # Check in-memory cache first (recently completed)
    if session_id in _completed:
        result = _completed[session_id]
        return result.to_dict()

    # Fallback: load from DB
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with _db_session() as session:
            session_row, is_archived = await _load_any_session(
                session,
                session_id,
                ("roundtable",),
                include_cron_roundtables=True,
            )
            if session_row is None:
                raise HTTPException(status_code=404, detail=f"Roundtable {session_id} not found")

            messages = await _load_messages_for_session(session, session_id, is_archived)

            # Cron-triggered roundtable: messages use chat roles (user/assistant/tool)
            # instead of round-N / synthesis.  Reconstruct from sub-agent sessions.
            is_cron_rt = session_row.session_type != "roundtable"
            if is_cron_rt:
                return await _build_cron_roundtable_detail(session, session_row, messages, is_archived)

            metadata = session_row.metadata_json or {}
            participants = metadata.get("participants", []) if isinstance(metadata, dict) else []

            turns = []
            synthesis = ""
            synthesis_meta: dict[str, Any] = {}
            for msg in messages:
                meta = msg.metadata_json or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception as e:
                        logger.warning("Metadata JSON parse error: %s", e)
                        meta = {}

                if msg.role == "synthesis":
                    synthesis = msg.content
                    if isinstance(meta, dict):
                        synthesis_meta = meta
                else:
                    # Parse round number from role like "round-1"
                    round_num = 0
                    role = msg.role or ""
                    if role.startswith("round-"):
                        try:
                            round_num = int(role.split("-")[1])
                        except (IndexError, ValueError):
                            pass

                    turns.append({
                        "agent_id": meta.get("agent_id", "unknown"),
                        "round": round_num,
                        "content": msg.content,
                        "duration_ms": 0,
                    })

            try:
                chunk_count = int(synthesis_meta.get("chunk_count", 0) or 0)
            except (TypeError, ValueError):
                chunk_count = 0

            return {
                "session_id": str(session_row.id),
                "topic": (session_row.title or "").replace("Roundtable: ", ""),
                "participants": participants,
                "rounds": max((t["round"] for t in turns), default=0),
                "turn_count": len(turns),
                "synthesis": synthesis,
                "synthesizer_id": "main",
                "total_duration_ms": 0,
                "chunked_mode": bool(synthesis_meta.get("chunked_mode", False)),
                "chunk_count": chunk_count,
                "chunk_notice": synthesis_meta.get("chunk_notice"),
                "chunk_kind": synthesis_meta.get("chunk_kind"),
                "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
                "turns": turns,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get roundtable failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/turns")
async def get_roundtable_turns(session_id: str):
    """
    Get just the turns for a roundtable — lightweight endpoint for
    progressive loading / polling during a running roundtable.
    """
    if session_id in _completed:
        result = _completed[session_id]
        return {
            "session_id": session_id,
            "turns": [
                {
                    "agent_id": t.agent_id,
                    "round": t.round_number,
                    "content": t.content,
                    "duration_ms": t.duration_ms,
                }
                for t in result.turns
            ],
        }

    # From DB
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Database not available")

    async with _db_session() as session:
        session_row, is_archived = await _load_any_session(
            session,
            session_id,
            ("roundtable",),
            include_cron_roundtables=True,
        )
        if session_row is None:
            raise HTTPException(status_code=404, detail=f"Roundtable {session_id} not found")
        messages = await _load_messages_for_session(session, session_id, is_archived)

    # Cron-triggered roundtable: extract turns from sub-agent sessions
    is_cron_rt = session_row.session_type != "roundtable"
    if is_cron_rt:
        async with _db_session() as session:
            detail = await _build_cron_roundtable_detail(session, session_row, messages, is_archived)
        return {"session_id": session_id, "turns": detail.get("turns", [])}

    turns = []
    for msg in messages:
        role = msg.role or ""
        if role.startswith("round-"):
            meta = msg.metadata_json or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception as e:
                    logger.warning("Metadata JSON parse error: %s", e)
                    meta = {}
            try:
                round_num = int(role.split("-")[1])
            except (IndexError, ValueError):
                round_num = 0
            turns.append({
                "agent_id": meta.get("agent_id", "unknown"),
                "round": round_num,
                "content": msg.content,
                "duration_ms": 0,
            })

    return {"session_id": session_id, "turns": turns}


@router.delete("/{session_id}")
async def delete_roundtable(session_id: str):
    """Immediately archive and delete a roundtable or swarm session."""
    if _db_session is None:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with _db_session() as session:
            async with session.begin():
                # Works for both roundtable and swarm
                row_result = await session.execute(
                    select(EngineChatSession).where(
                        and_(
                            EngineChatSession.id == session_id,
                            EngineChatSession.session_type.in_(("roundtable", "swarm")),
                        )
                    )
                )
                row = row_result.scalar_one_or_none()
                if row is None:
                    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

                # Archive session immediately (idempotent)
                await session.execute(
                    pg_insert(EngineChatSessionArchive)
                    .values(
                        id=row.id,
                        agent_id=row.agent_id,
                        session_type=row.session_type,
                        title=row.title,
                        system_prompt=row.system_prompt,
                        model=row.model,
                        temperature=row.temperature,
                        max_tokens=row.max_tokens,
                        context_window=row.context_window,
                        status="ended",
                        message_count=row.message_count,
                        total_tokens=row.total_tokens,
                        total_cost=row.total_cost,
                        metadata_json=row.metadata_json,
                        created_at=row.created_at,
                        updated_at=func.now(),
                        ended_at=func.now(),
                        archived_at=func.now(),
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

                # Archive messages (idempotent)
                msg_rows = (await session.execute(
                    select(EngineChatMessage).where(
                        EngineChatMessage.session_id == session_id
                    )
                )).scalars().all()
                for msg in msg_rows:
                    await session.execute(
                        pg_insert(EngineChatMessageArchive)
                        .values(
                            id=msg.id,
                            session_id=msg.session_id,
                            agent_id=msg.agent_id,
                            role=msg.role,
                            content=msg.content,
                            thinking=msg.thinking,
                            tool_calls=msg.tool_calls,
                            tool_results=msg.tool_results,
                            model=msg.model,
                            tokens_input=msg.tokens_input,
                            tokens_output=msg.tokens_output,
                            cost=msg.cost,
                            latency_ms=msg.latency_ms,
                            embedding=msg.embedding,
                            metadata_json=msg.metadata_json,
                            created_at=msg.created_at,
                            archived_at=func.now(),
                        )
                        .on_conflict_do_nothing(index_elements=["id"])
                    )

                # Delete messages then session from working table
                await session.execute(
                    delete(EngineChatMessage).where(
                        EngineChatMessage.session_id == session_id
                    )
                )
                await session.execute(
                    delete(EngineChatSession).where(
                        EngineChatSession.id == session_id
                    )
                )

        # Clean up in-memory caches
        _completed.pop(session_id, None)
        _swarm_completed.pop(session_id, None)

        return {"status": "archived", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Delete roundtable/swarm failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Swarm endpoints ──────────────────────────────────────────────────────────

_swarm_orchestrator: Any = None
_swarm_running: dict[str, dict[str, Any]] = {}
_swarm_completed: dict[str, Any] = {}


def configure_swarm(swarm) -> None:
    """Called from main.py lifespan to inject SwarmOrchestrator."""
    global _swarm_orchestrator
    _swarm_orchestrator = swarm
    logger.info("Swarm router configured")


def _get_swarm():
    if _swarm_orchestrator is None:
        raise HTTPException(status_code=503, detail="Swarm engine not initialized")
    return _swarm_orchestrator


class StartSwarmRequest(BaseModel):
    """Request body for starting a swarm decision."""
    topic: str = Field(..., min_length=2, max_length=2000)
    agent_ids: list[str] = Field(..., min_length=2, max_length=12)
    max_iterations: int = Field(default=5, ge=1, le=10)
    consensus_threshold: float = Field(default=0.7, ge=0.3, le=1.0)
    agent_timeout: int = Field(default=60, ge=10, le=300)
    total_timeout: int = Field(default=600, ge=30, le=1800)


class SwarmResponse(BaseModel):
    """Response for a completed swarm."""
    session_id: str
    topic: str
    participants: list[str]
    iterations: int
    vote_count: int
    consensus: str
    consensus_score: float
    converged: bool
    total_duration_ms: int
    chunked_mode: bool = False
    chunk_count: int = 0
    chunk_notice: str | None = None
    chunk_kind: str | None = None
    created_at: str
    votes: list[dict] = Field(default_factory=list)


@router.post("/swarm", response_model=SwarmResponse, status_code=201)
async def start_swarm(body: StartSwarmRequest):
    """Start a synchronous swarm decision process."""
    swarm = _get_swarm()
    try:
        await _validate_requested_agents(body.agent_ids)
        result = await swarm.execute(
            topic=body.topic,
            agent_ids=body.agent_ids,
            max_iterations=body.max_iterations,
            consensus_threshold=body.consensus_threshold,
            agent_timeout=body.agent_timeout,
            total_timeout=body.total_timeout,
        )
        _swarm_completed[result.session_id] = result
        d = result.to_dict()
        return SwarmResponse(**d)
    except Exception as e:
        logger.error("Swarm failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/swarm/async", status_code=202)
async def start_swarm_async(
    body: StartSwarmRequest,
    background_tasks: BackgroundTasks,
):
    """Start a swarm in the background."""
    import hashlib
    swarm = _get_swarm()
    await _validate_requested_agents(body.agent_ids)
    key = hashlib.sha256(
        f"swarm:{body.topic}:{','.join(body.agent_ids)}".encode()
    ).hexdigest()[:16]

    _swarm_running[key] = {
        "status": "running",
        "topic": body.topic,
        "participants": body.agent_ids,
    }

    async def _run():
        try:
            result = await swarm.execute(
                topic=body.topic, agent_ids=body.agent_ids,
                max_iterations=body.max_iterations,
                consensus_threshold=body.consensus_threshold,
            )
            _swarm_completed[result.session_id] = result
            _swarm_running[key] = {
                "status": "completed", "session_id": result.session_id,
            }
        except Exception as e:
            logger.error("Async swarm failed: %s", e)
            _swarm_running[key] = {"status": "failed", "error": str(e)}

    background_tasks.add_task(_run)
    return {
        "key": key, "status": "running",
        "topic": body.topic, "participants": body.agent_ids,
    }


@router.get("/swarm/status/{key}")
async def get_swarm_status(key: str):
    """Poll async swarm status."""
    if key in _swarm_running:
        return _swarm_running[key]
    raise HTTPException(status_code=404, detail=f"No swarm tracking for key: {key}")


@router.get("/swarm/{session_id}")
async def get_swarm(session_id: str):
    """Get swarm detail from cache or DB."""
    if session_id in _swarm_completed:
        return _swarm_completed[session_id].to_dict()

    if _db_session is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Fallback: load from DB (same schema as roundtable but session_type='swarm')
    try:
        async with _db_session() as session:
            row, is_archived = await _load_any_session(
                session,
                session_id,
                ("swarm",),
            )
            if row is None:
                raise HTTPException(status_code=404, detail=f"Swarm {session_id} not found")

            messages = await _load_messages_for_session(session, session_id, is_archived)

            metadata = row.metadata_json or {}
            participants = metadata.get("participants", []) if isinstance(metadata, dict) else []

            votes = []
            consensus = ""
            consensus_meta: dict[str, Any] = {}
            for msg in messages:
                meta = msg.metadata_json or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception as e:
                        logger.warning("Metadata JSON parse error: %s", e)
                        meta = {}

                if msg.role == "consensus":
                    consensus = msg.content
                    if isinstance(meta, dict):
                        consensus_meta = meta
                elif (msg.role or "").startswith("swarm-"):
                    try:
                        iteration = int(msg.role.split("-")[1])
                    except (IndexError, ValueError):
                        iteration = 0
                    votes.append({
                        "agent_id": meta.get("agent_id", "unknown"),
                        "iteration": iteration,
                        "content": msg.content,
                        "vote": "extend",
                        "confidence": 0.5,
                        "duration_ms": 0,
                    })

            try:
                chunk_count = int(consensus_meta.get("chunk_count", 0) or 0)
            except (TypeError, ValueError):
                chunk_count = 0

            return {
                "session_id": str(row.id),
                "topic": (row.title or "").replace("Swarm: ", ""),
                "participants": participants,
                "iterations": max((v["iteration"] for v in votes), default=0),
                "vote_count": len(votes),
                "consensus": consensus,
                "consensus_score": 0.0,
                "converged": False,
                "total_duration_ms": 0,
                "chunked_mode": bool(consensus_meta.get("chunked_mode", False)),
                "chunk_count": chunk_count,
                "chunk_notice": consensus_meta.get("chunk_notice"),
                "chunk_kind": consensus_meta.get("chunk_kind"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "votes": votes,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get swarm failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket streaming for roundtable + swarm ───────────────────────────────


@ws_router.websocket("/ws/roundtable")
async def roundtable_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for streaming roundtable/swarm in real-time.

    S-16: Validates API key from query param before accepting connection.

    Client sends: {"type": "start", "mode": "roundtable"|"swarm", "topic": "...", "agent_ids": [...]}
    Server sends: {"type": "turn", "agent_id": "...", "round": 1, "content": "...", "duration_ms": N}
    Server sends: {"type": "vote", "agent_id": "...", "iteration": 1, "vote": "agree", ...}
    Server sends: {"type": "synthesis"|"consensus", "content": "..."}
    Server sends: {"type": "done", "session_id": "...", ...}
    Server sends: {"type": "error", "message": "..."}
    """
    # S-16: WebSocket authentication
    try:
        from auth import validate_ws_api_key
    except ImportError:
        from ..auth import validate_ws_api_key
    api_key = websocket.query_params.get("api_key")
    if not await validate_ws_api_key(api_key):
        await websocket.close(code=4401, reason="Unauthorized — invalid or missing API key")
        return

    if _roundtable is None:
        await websocket.close(code=1013, reason="Roundtable not initialized")
        return

    await websocket.accept()
    logger.info("Roundtable WS connected")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await _ws_send(websocket, {"type": "pong"})

            elif msg_type == "start":
                mode = data.get("mode", "roundtable")
                topic = data.get("topic", "").strip()
                agent_ids = data.get("agent_ids", [])

                if not topic or len(agent_ids) < 2:
                    await _ws_send(websocket, {
                        "type": "error",
                        "message": "Need topic and at least 2 agent_ids",
                    })
                    continue

                if mode == "swarm" and _swarm_orchestrator is not None:
                    await _handle_swarm_ws(websocket, topic, agent_ids, data)
                else:
                    await _handle_roundtable_ws(websocket, topic, agent_ids, data)

            else:
                await _ws_send(websocket, {
                    "type": "error",
                    "message": f"Unknown type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info("Roundtable WS disconnected")
    except Exception as e:
        logger.error("Roundtable WS error: %s", e)
        try:
            await _ws_send(websocket, {"type": "error", "message": str(e)})
        except Exception as e2:
            logger.debug("Failed to send WS error message: %s", e2)


async def _handle_roundtable_ws(
    websocket: WebSocket,
    topic: str,
    agent_ids: list[str],
    data: dict,
) -> None:
    """Run a roundtable with turn-by-turn WS streaming."""
    rounds = data.get("rounds", 3)
    synthesizer = data.get("synthesizer_id", "main")

    async def on_turn(turn):
        """Callback fired after each agent turn."""
        await _ws_send(websocket, {
            "type": "turn",
            "agent_id": turn.agent_id,
            "round": turn.round_number,
            "content": turn.content,
            "duration_ms": turn.duration_ms,
        })

    try:
        result = await _roundtable.discuss(
            topic=topic,
            agent_ids=agent_ids,
            rounds=rounds,
            synthesizer_id=synthesizer,
            on_turn=on_turn,
        )
        _completed[result.session_id] = result

        await _ws_send(websocket, {
            "type": "synthesis",
            "content": result.synthesis,
            "synthesizer_id": result.synthesizer_id,
            "chunked_mode": bool(getattr(result, "chunked_mode", False)),
            "chunk_count": int(getattr(result, "chunk_count", 0) or 0),
            "chunk_notice": getattr(result, "chunk_notice", None),
            "chunk_kind": getattr(result, "chunk_kind", None),
        })
        await _ws_send(websocket, {
            "type": "done",
            "session_id": result.session_id,
            "turn_count": result.turn_count,
            "total_duration_ms": result.total_duration_ms,
            "chunked_mode": bool(getattr(result, "chunked_mode", False)),
            "chunk_count": int(getattr(result, "chunk_count", 0) or 0),
            "chunk_notice": getattr(result, "chunk_notice", None),
            "chunk_kind": getattr(result, "chunk_kind", None),
        })
    except Exception as e:
        logger.warning("WebSocket roundtable error: %s", e)
        await _ws_send(websocket, {"type": "error", "message": str(e)})


async def _handle_swarm_ws(
    websocket: WebSocket,
    topic: str,
    agent_ids: list[str],
    data: dict,
) -> None:
    """Run a swarm with vote-by-vote WS streaming."""
    max_iterations = data.get("max_iterations", 5)
    threshold = data.get("consensus_threshold", 0.7)

    async def on_vote(vote):
        """Callback fired after each agent vote."""
        await _ws_send(websocket, {
            "type": "vote",
            "agent_id": vote.agent_id,
            "iteration": vote.iteration,
            "content": vote.content,
            "vote": vote.vote,
            "confidence": vote.confidence,
            "duration_ms": vote.duration_ms,
        })

    try:
        result = await _swarm_orchestrator.execute(
            topic=topic,
            agent_ids=agent_ids,
            max_iterations=max_iterations,
            consensus_threshold=threshold,
            on_vote=on_vote,
        )
        _swarm_completed[result.session_id] = result

        await _ws_send(websocket, {
            "type": "consensus",
            "content": result.consensus,
            "consensus_score": result.consensus_score,
            "converged": result.converged,
            "chunked_mode": bool(getattr(result, "chunked_mode", False)),
            "chunk_count": int(getattr(result, "chunk_count", 0) or 0),
            "chunk_notice": getattr(result, "chunk_notice", None),
            "chunk_kind": getattr(result, "chunk_kind", None),
        })
        await _ws_send(websocket, {
            "type": "done",
            "session_id": result.session_id,
            "vote_count": result.vote_count,
            "iterations": result.iterations,
            "total_duration_ms": result.total_duration_ms,
            "chunked_mode": bool(getattr(result, "chunked_mode", False)),
            "chunk_count": int(getattr(result, "chunk_count", 0) or 0),
            "chunk_notice": getattr(result, "chunk_notice", None),
            "chunk_kind": getattr(result, "chunk_kind", None),
        })
    except Exception as e:
        logger.warning("WebSocket swarm error: %s", e)
        await _ws_send(websocket, {"type": "error", "message": str(e)})


async def _ws_send(websocket: WebSocket, data: dict) -> None:
    """Send JSON over WebSocket, silently handling disconnection."""
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(json.dumps(data))
    except Exception as e:
        logger.debug("WS send failed (client likely disconnected): %s", e)


# ── Registration helper ──────────────────────────────────────────────────────


def register_roundtable(app, dependencies: list | None = None) -> None:
    """Register both REST + WebSocket routers."""
    app.include_router(router, dependencies=dependencies)
    app.include_router(ws_router)
    logger.info("Registered roundtable routes: %s + WS /ws/roundtable", router.prefix)
