"""
Engine Chat API — REST + WebSocket endpoints for Aria Engine chat.

REST endpoints:
  POST   /api/engine/chat/sessions              — create a new session
  GET    /api/engine/chat/sessions              — list sessions (paginated)
  GET    /api/engine/chat/sessions/{id}         — get session with messages
  POST   /api/engine/chat/sessions/{id}/messages — send message (non-streaming)
  DELETE /api/engine/chat/sessions/{id}         — end/delete session
  GET    /api/engine/chat/sessions/{id}/export   — export JSONL or Markdown

WebSocket:
  WS     /ws/chat/{session_id}                  — streaming chat

All endpoints use the native aria_engine modules.
"""
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aria_engine.config import EngineConfig
from aria_engine.chat_engine import ChatEngine, ChatResponse
from aria_engine.context_manager import ContextManager
from aria_engine.export import export_session
from aria_engine.prompts import PromptAssembler
from aria_engine.streaming import StreamManager

logger = logging.getLogger("aria.api.engine_chat")

router = APIRouter(prefix="/engine/chat", tags=["Engine Chat"])
ws_router = APIRouter(tags=["Engine Chat WebSocket"])


# ── Pydantic Models ──────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Request body for creating a new chat session."""
    agent_id: str = Field(default="aria", description="Agent owning this session")
    model: str | None = Field(default=None, description="LLM model (defaults to config)")
    session_type: str = Field(default="interactive", description="Session type")
    title: str | None = Field(default=None, max_length=200, description="Session title (auto-generated if omitted)")
    system_prompt: str | None = Field(default=None, description="Override system prompt")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=128000)
    context_window: int = Field(default=50, ge=1, le=500)
    metadata: dict | None = Field(default=None, description="Arbitrary metadata")


class CreateSessionResponse(BaseModel):
    """Response for session creation."""
    id: str
    agent_id: str
    model: str | None
    status: str
    session_type: str
    created_at: str | None


class SendMessageRequest(BaseModel):
    """Request body for sending a message."""
    content: str = Field(..., min_length=1, max_length=100000, description="Message content")
    enable_thinking: bool = Field(default=False, description="Request reasoning tokens")
    enable_tools: bool = Field(default=True, description="Allow tool calling")


class SendMessageResponse(BaseModel):
    """Response for a sent message."""
    message_id: str
    session_id: str
    content: str
    thinking: str | None = None
    tool_calls: list | None = None
    tool_results: list | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = ""


class SessionSummary(BaseModel):
    """Summary of a session for list endpoints."""
    id: str
    agent_id: str
    title: str | None = None
    model: str | None = None
    status: str
    session_type: str
    message_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None
    ended_at: str | None = None


class SessionDetail(SessionSummary):
    """Full session with messages."""
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    context_window: int = 50
    messages: list = Field(default_factory=list)
    metadata: dict | None = None


class PaginatedSessions(BaseModel):
    """Paginated list of sessions."""
    items: list[SessionSummary]
    total: int
    page: int
    page_size: int
    pages: int


# ── Dependency Injection ─────────────────────────────────────────────────────

# These will be initialized at app startup and injected via FastAPI depends.
# In production, these are set in src/api/main.py during lifespan.

_engine_config: EngineConfig | None = None
_chat_engine: ChatEngine | None = None
_stream_manager: StreamManager | None = None
_context_manager: ContextManager | None = None
_prompt_assembler: PromptAssembler | None = None


def configure_engine(
    config: EngineConfig,
    chat_engine: ChatEngine,
    stream_manager: StreamManager,
    context_manager: ContextManager,
    prompt_assembler: PromptAssembler,
) -> None:
    """
    Configure the engine chat router with initialized instances.

    Called once during app startup in src/api/main.py.
    """
    global _engine_config, _chat_engine, _stream_manager, _context_manager, _prompt_assembler
    _engine_config = config
    _chat_engine = chat_engine
    _stream_manager = stream_manager
    _context_manager = context_manager
    _prompt_assembler = prompt_assembler
    logger.info("Engine chat router configured")


def _get_engine() -> ChatEngine:
    """Dependency: get ChatEngine instance."""
    if _chat_engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return _chat_engine


def _get_config() -> EngineConfig:
    """Dependency: get EngineConfig instance."""
    if _engine_config is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return _engine_config


def _get_prompt_assembler() -> PromptAssembler | None:
    """Dependency: get PromptAssembler instance (may be None if init failed)."""
    return _prompt_assembler


# ── REST Endpoints ───────────────────────────────────────────────────────────


@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    engine: ChatEngine = Depends(_get_engine),
    assembler: PromptAssembler | None = Depends(_get_prompt_assembler),
):
    """
    Create a new chat session.

    If no system_prompt is provided, assembles one from Aria's soul files
    (IDENTITY.md + SOUL.md), agent-specific prompt, and active goals.
    """
    try:
        # Assemble system prompt from soul files if caller didn't provide one
        system_prompt = body.system_prompt
        if not system_prompt and assembler is not None:
            try:
                try:
                    from .db import AsyncSessionLocal
                except ImportError:
                    from db import AsyncSessionLocal
                assembled = await assembler.assemble_for_session(
                    agent_id=body.agent_id or "aria",
                    db_session_factory=AsyncSessionLocal,
                )
                system_prompt = str(assembled)
                logger.info(
                    "Assembled system prompt for agent=%s: %d chars, sections=%s",
                    body.agent_id, assembled.total_chars, assembled.sections,
                )
            except Exception as pe:
                logger.warning("Prompt assembly failed (using None): %s", pe)

        session = await engine.create_session(
            agent_id=body.agent_id,
            model=body.model,
            session_type=body.session_type,
            title=body.title,
            system_prompt=system_prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            context_window=body.context_window,
            metadata=body.metadata,
        )
        return CreateSessionResponse(
            id=session["id"],
            agent_id=session["agent_id"],
            model=session.get("model"),
            status=session["status"],
            session_type=session["session_type"],
            created_at=session.get("created_at"),
        )
    except Exception as e:
        logger.error("Failed to create session: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=PaginatedSessions)
async def list_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    agent_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    engine: ChatEngine = Depends(_get_engine),
):
    """
    List chat sessions with pagination and optional filtering.
    """
    from db.models import EngineChatSession
    from deps import get_db

    async for db in get_db():
        query = select(EngineChatSession).order_by(
            EngineChatSession.updated_at.desc()
        )

        if agent_id:
            query = query.where(EngineChatSession.agent_id == agent_id)
        if status:
            query = query.where(EngineChatSession.status == status)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        result = await db.execute(query)
        sessions = result.scalars().all()

        items = [
            SessionSummary(
                id=str(s.id),
                agent_id=s.agent_id,
                title=s.title,
                model=s.model,
                status=s.status,
                session_type=s.session_type,
                message_count=s.message_count or 0,
                total_tokens=s.total_tokens or 0,
                total_cost=float(s.total_cost or 0),
                created_at=s.created_at.isoformat() if s.created_at else None,
                updated_at=s.updated_at.isoformat() if s.updated_at else None,
                ended_at=s.ended_at.isoformat() if s.ended_at else None,
            )
            for s in sessions
        ]

        pages = max(1, (total + page_size - 1) // page_size)

        return PaginatedSessions(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    engine: ChatEngine = Depends(_get_engine),
):
    """
    Get a session with its full message history.
    """
    from aria_engine.exceptions import SessionError

    try:
        session = await engine.resume_session(session_id)
        messages = session.pop("messages", [])

        return SessionDetail(
            id=session["id"],
            agent_id=session["agent_id"],
            title=session.get("title"),
            model=session.get("model"),
            status=session["status"],
            session_type=session["session_type"],
            message_count=session.get("message_count", 0),
            total_tokens=session.get("total_tokens", 0),
            total_cost=session.get("total_cost", 0),
            system_prompt=session.get("system_prompt"),
            temperature=session.get("temperature"),
            max_tokens=session.get("max_tokens"),
            context_window=session.get("context_window", 50),
            messages=messages,
            metadata=session.get("metadata"),
            created_at=session.get("created_at"),
            updated_at=session.get("updated_at"),
            ended_at=session.get("ended_at"),
        )
    except SessionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    engine: ChatEngine = Depends(_get_engine),
):
    """
    Get all messages for a session (used by the chat UI to load history).

    Returns ``{"messages": [...]}`` with each message containing role, content,
    thinking, tool_calls, model, and timestamp fields.
    """
    import uuid as _uuid

    from aria_engine.exceptions import SessionError

    # Reject obviously invalid session IDs (e.g. "undefined" from JS)
    try:
        _uuid.UUID(session_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid session ID: {session_id!r}")

    try:
        session = await engine.resume_session(session_id)
        messages = session.get("messages", [])
        return {"messages": messages}
    except SessionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    engine: ChatEngine = Depends(_get_engine),
):
    """
    Send a message to a session and get a non-streaming response.

    For streaming responses, use the WebSocket endpoint at /ws/chat/{session_id}.
    """
    from aria_engine.exceptions import SessionError, LLMError

    try:
        response: ChatResponse = await engine.send_message(
            session_id=session_id,
            content=body.content,
            enable_thinking=body.enable_thinking,
            enable_tools=body.enable_tools,
        )
        return SendMessageResponse(
            message_id=response.message_id,
            session_id=response.session_id,
            content=response.content,
            thinking=response.thinking if body.enable_thinking else None,
            tool_calls=response.tool_calls,
            tool_results=response.tool_results,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            finish_reason=response.finish_reason,
        )
    except SessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("send_message failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    engine: ChatEngine = Depends(_get_engine),
):
    """
    End (close) a session. Marks it as ended but preserves history.
    """
    from aria_engine.exceptions import SessionError

    try:
        session = await engine.end_session(session_id)
        return {"status": "ended", "session_id": session["id"]}
    except SessionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sessions/{session_id}/export")
async def export_session_endpoint(
    session_id: str,
    format: str = Query(default="jsonl", pattern="^(jsonl|markdown|md)$"),
    config: EngineConfig = Depends(_get_config),
    engine: ChatEngine = Depends(_get_engine),
):
    """
    Export a session as JSONL or Markdown.

    Query params:
      - format: 'jsonl' or 'markdown' (default: 'jsonl')

    Returns the export content as a downloadable response.
    """
    from fastapi.responses import Response
    from aria_engine.exceptions import SessionError

    try:
        content = await export_session(
            session_id=session_id,
            db_session_factory=engine._db_factory,
            config=config,
            format=format,
            save_to_disk=False,
        )

        if format == "jsonl":
            return Response(
                content=content,
                media_type="application/x-jsonlines",
                headers={
                    "Content-Disposition": f'attachment; filename="{session_id}.jsonl"'
                },
            )
        else:
            return Response(
                content=content,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{session_id}.md"'
                },
            )
    except SessionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── WebSocket Endpoint ───────────────────────────────────────────────────────


@ws_router.websocket("/ws/chat/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
):
    """
    WebSocket endpoint for streaming chat.

    S-16: Validates API key from query param before accepting connection.

    Protocol:
      Client sends: {"type": "message", "content": "Hello!", "enable_thinking": false}
      Server sends: {"type": "token", "content": "Hi"}, ..., {"type": "done", ...}

    See aria_engine/streaming.py for full protocol documentation.
    """
    # S-16: WebSocket authentication — check API key from query param
    try:
        from auth import validate_ws_api_key
    except ImportError:
        from ..auth import validate_ws_api_key
    api_key = websocket.query_params.get("api_key")
    if not await validate_ws_api_key(api_key):
        await websocket.close(code=4401, reason="Unauthorized — invalid or missing API key")
        return

    if _stream_manager is None:
        await websocket.close(code=1013, reason="Engine not initialized")
        return

    try:
        await _stream_manager.handle_connection(websocket, session_id)
    except Exception as e:
        logger.error("WebSocket error for session %s: %s", session_id, e)
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception as e2:
            logger.debug("Failed to close WebSocket for session %s: %s", session_id, e2)


# ── Registration helper ──────────────────────────────────────────────────────


def register_engine_chat(app, dependencies: list | None = None) -> None:
    """
    Register the engine chat routers with the FastAPI app.

    Called from src/api/main.py:
        from routers.engine_chat import register_engine_chat, configure_engine
        register_engine_chat(app)
    """
    app.include_router(router, dependencies=dependencies)
    app.include_router(ws_router)
    logger.info(
        "Registered engine chat routes: %s + WS /ws/chat/{session_id}",
        router.prefix,
    )
