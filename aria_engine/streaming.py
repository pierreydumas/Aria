"""
Stream Manager — WebSocket streaming for chat responses.

Bridges LLMGateway.stream() to FastAPI WebSocket connections with:
- Structured JSON protocol (token, thinking, tool_call, tool_result, done, error)
- Full response accumulation for DB persistence after stream completes
- Graceful disconnection handling (saves partial response)
- Ping/pong keepalive every 30 seconds
- Connection lifecycle management

Protocol:
  Client → Server:
    {"type": "message", "content": "Hello!", "enable_thinking": false}
        {"type": "message", "content": "Hello!", "client_message_id": "uuid-or-key"}
    {"type": "ping"}

  Server → Client:
        {"type": "stream_start"}
        {"type": "content", "content": "Hello"}
    {"type": "thinking", "content": "Let me consider..."}
    {"type": "tool_call", "name": "search", "arguments": {"q": "..."}, "id": "tc_1"}
    {"type": "tool_result", "name": "search", "content": "...", "id": "tc_1", "success": true}
        {"type": "stream_end", "message_id": "uuid", "finish_reason": "stop"}
    {"type": "idempotent_replay", "client_message_id": "uuid-or-key"}
    {"type": "error", "message": "..."}
    {"type": "pong"}

    Note: all typed events include `protocol_version`; per-turn events include `trace_id`.
"""
import asyncio
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from aria_engine.config import EngineConfig
from aria_engine.exceptions import SessionError, LLMError
from aria_engine.llm_gateway import LLMGateway, StreamChunk
from aria_engine.telemetry import log_model_usage, log_skill_invocation, _parse_skill_from_tool
from aria_engine.tool_registry import ToolRegistry, ToolResult

logger = logging.getLogger("aria.engine.stream")
STREAM_PROTOCOL_VERSION = "2.0"
_stream_trace_id_ctx: ContextVar[str] = ContextVar("stream_trace_id", default="")


@dataclass
class StreamAccumulator:
    """Accumulates a full response from stream chunks for DB persistence."""
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: str = ""
    started_at: float = 0.0
    model: str = ""

    @property
    def latency_ms(self) -> int:
        if self.started_at:
            return int((time.monotonic() - self.started_at) * 1000)
        return 0


@dataclass
class TurnStateMachine:
    """Deterministic turn-state tracker for streaming orchestration."""
    current: str = "accepted"
    history: list[str] = field(default_factory=lambda: ["accepted"])

    _ALLOWED_TRANSITIONS: dict[str, set[str]] = field(default_factory=lambda: {
        "accepted": {"streaming", "finalized"},
        "streaming": {"tool_requested", "finalized"},
        "tool_requested": {"tool_executing", "finalized"},
        "tool_executing": {"followup_generation", "finalized"},
        "followup_generation": {"streaming", "finalized"},
        "finalized": set(),
    })

    def transition(self, next_state: str) -> None:
        if next_state == self.current:
            return
        if next_state not in self._ALLOWED_TRANSITIONS.get(self.current, set()):
            raise RuntimeError(
                f"Invalid turn state transition: {self.current} -> {next_state}"
            )
        self.current = next_state
        self.history.append(next_state)


class StreamManager:
    """
    Manages WebSocket streaming chat sessions.

    Usage:
        manager = StreamManager(config, gateway, tool_registry, db_factory)

        # In a FastAPI WebSocket endpoint:
        @app.websocket("/ws/chat/{session_id}")
        async def chat_ws(websocket: WebSocket, session_id: str):
            await manager.handle_connection(websocket, session_id)
    """

    def __init__(
        self,
        config: EngineConfig,
        gateway: LLMGateway,
        tool_registry: ToolRegistry,
        db_session_factory,
    ):
        self.config = config
        self.gateway = gateway
        self.tools = tool_registry
        self._db_factory = db_session_factory
        self._active_connections: dict[str, WebSocket] = {}
        # Per-session locks to serialize message handling and prevent DB deadlocks
        # when multiple WS connections target the same session simultaneously.
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._repair_stats: dict[str, int] = {
            "triggered": 0,
            "succeeded": 0,
            "skipped_disabled": 0,
        }
        # Context window manager for token-budget-aware message eviction
        from aria_engine.context_manager import ContextManager
        self._ctx_manager = ContextManager(config)

    MAX_DELEGATION_FAILURES = 4
    DELEGATION_TOOL_PREFIXES = ("agent_manager__",)
    DELEGATION_FAILURE_MARKERS = (
        "circuit open",
        "temporarily unavailable",
        "no response",
        "timed out",
        "connection refused",
        "task send failed",
    )

    _PROMISED_ACTION_PATTERN = re.compile(
        r"\b("
        r"making the call now|"
        r"getting goals now|"
        r"trying .* now|"
        r"executing now|"
        r"no commentary"
        r")\b",
        re.IGNORECASE,
    )

    @classmethod
    def _looks_like_promised_action_without_execution(cls, text: str) -> bool:
        """Detect empty/procedural assistant replies that promise action but do not execute it."""
        if not text:
            return False
        compact = " ".join(text.strip().split())
        if not compact:
            return False
        return bool(cls._PROMISED_ACTION_PATTERN.search(compact))

    @classmethod
    def _is_delegation_tool(cls, tool_name: str) -> bool:
        return any(tool_name.startswith(prefix) for prefix in cls.DELEGATION_TOOL_PREFIXES)

    @staticmethod
    def _extract_tool_error(tool_content: str) -> str:
        if not tool_content:
            return ""
        try:
            parsed = json.loads(tool_content)
            if isinstance(parsed, dict):
                err = parsed.get("error")
                if isinstance(err, str):
                    return err
        except Exception:
            pass
        return tool_content[:200]

    @classmethod
    def _is_blocking_delegation_failure(cls, error_text: str) -> bool:
        lowered = (error_text or "").lower()
        return any(marker in lowered for marker in cls.DELEGATION_FAILURE_MARKERS)

    @classmethod
    def _filter_tools_for_turn(
        cls,
        tools: list[dict[str, Any]] | None,
        *,
        delegation_blocked: bool,
    ) -> list[dict[str, Any]] | None:
        if not tools or not delegation_blocked:
            return tools
        filtered: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else ""
            if isinstance(name, str) and cls._is_delegation_tool(name):
                continue
            filtered.append(tool)
        return filtered

    def _get_model_token_limits(self, model: str) -> tuple[int, int]:
        """Return (soft_limit, hard_limit) token counts for the given model.

        soft_limit = 80% of safe_prompt_tokens → inject self-awareness notice
        hard_limit = safe_prompt_tokens → refuse the provider call

        Falls back to conservatively safe defaults if models.yaml lookup fails.
        """
        try:
            from aria_models.loader import load_catalog, normalize_model_id
            catalog = load_catalog()
            model_def = catalog.get("models", {}).get(normalize_model_id(model), {})
            hard = model_def.get("safe_prompt_tokens") or model_def.get("contextWindow", 0)
            if not hard:
                hard = 100_000
            soft = int(hard * 0.80)
            return soft, hard
        except Exception:
            return 80_000, 100_000

    async def _maybe_compress_context(
        self,
        db,
        session,
        messages: list[dict[str, Any]],
        token_count: int,
        soft_threshold: int,
    ) -> list[dict[str, Any]]:
        """Compress middle conversation history when approaching token limits.

        If token_count > soft_threshold (70% of model limit):
        1. Identify the "middle" messages (skip system + first user + last 20)
        2. Call memory_compression__compress_session via ToolRegistry
        3. Replace middle messages with a single summary system message
        4. Summary is stored in aria_memories/ by the compression skill

        Returns the (possibly compressed) messages list.
        """
        if token_count <= soft_threshold:
            return messages

        TAIL_SIZE = 20
        head_end = 0
        for i, m in enumerate(messages):
            if m.get("role") == "system" or (i <= 1 and m.get("role") == "user"):
                head_end = i + 1

        if len(messages) <= head_end + TAIL_SIZE + 2:
            logger.debug("Context: not enough middle messages to compress (skipping)")
            return messages

        tail_start = max(head_end + 1, len(messages) - TAIL_SIZE)
        head_messages = messages[:head_end]
        middle_messages = messages[head_end:tail_start]
        tail_messages = messages[tail_start:]

        if not middle_messages:
            return messages

        try:
            import time as _time
            compression_result = await self.tools.execute(
                tool_call_id=f"compress_{session.id}_{int(_time.monotonic())}",
                function_name="memory_compression__compress_session",
                arguments={"hours_back": 6},
            )
            if compression_result.success:
                import json as _json
                summary_data = _json.loads(compression_result.content) if isinstance(compression_result.content, str) else {}
                summary_text = summary_data.get("summary") or summary_data.get("compressed") or ""
                if summary_text:
                    summary_message = {
                        "role": "system",
                        "content": (
                            "[CONVERSATION SUMMARY — earlier context compressed]\n"
                            f"{summary_text}"
                        ),
                    }
                    compressed = head_messages + [summary_message] + tail_messages
                    logger.info(
                        "Context compression applied: session=%s "
                        "middle=%d msgs compressed, new total=%d msgs",
                        session.id, len(middle_messages), len(compressed),
                    )
                    return compressed
        except Exception as exc:
            logger.warning("Context compression failed (non-fatal): %s", exc)

        return messages

    async def handle_connection(
        self,
        websocket: WebSocket,
        session_id: str,
    ) -> None:
        """
        Handle a WebSocket connection for a chat session.

        Lifecycle:
        1. Accept connection
        2. Validate session exists and is active
        3. Start keepalive task
        4. Listen for messages and stream responses
        5. Clean up on disconnect
        """
        try:
            await self._validate_session(session_id)
        except SessionError as e:
            logger.info("Rejected websocket for invalid session %s: %s", session_id, e)
            await websocket.close()
            return
        except (ValueError, TypeError) as e:
            logger.info("Rejected websocket for malformed session id %s: %s", session_id, e)
            await websocket.close()
            return
        except Exception as e:
            # Catch-all: DB import errors, connection issues, etc.
            # Accept the WS anyway — the first message will fail gracefully.
            logger.warning(
                "Session validation failed for %s (non-fatal, accepting WS): %s",
                session_id, e,
            )

        await websocket.accept()

        connection_id = f"{session_id}:{uuid.uuid4().hex[:8]}"
        self._active_connections[connection_id] = websocket

        logger.info("WebSocket connected: %s", connection_id)

        # Start keepalive task
        keepalive_task = asyncio.create_task(
            self._keepalive(websocket, connection_id)
        )

        try:
            # Listen for messages
            while True:
                try:
                    raw = await websocket.receive_text()
                    data = json.loads(raw)

                    msg_type = data.get("type", "")

                    if msg_type == "ping":
                        await self._send_json(websocket, {"type": "pong"})

                    elif msg_type == "message":
                        content = data.get("content", "").strip()
                        if not content:
                            await self._send_json(websocket, {
                                "type": "error",
                                "message": "Empty message content",
                            })
                            continue

                        enable_thinking = data.get("enable_thinking", False)
                        enable_tools = data.get("enable_tools", True)
                        raw_client_message_id = data.get("client_message_id")
                        client_message_id = (
                            str(raw_client_message_id).strip()
                            if raw_client_message_id is not None
                            else None
                        )
                        if client_message_id == "":
                            client_message_id = None
                        if client_message_id and len(client_message_id) > 128:
                            await self._send_json(websocket, {
                                "type": "error",
                                "message": "client_message_id too long (max 128)",
                            })
                            continue

                        # Acquire per-session lock to prevent concurrent DB
                        # mutations (FK ShareLock + UPDATE deadlock pattern).
                        lock = self._session_locks.setdefault(
                            session_id, asyncio.Lock()
                        )
                        async with lock:
                            await self._handle_message(
                                websocket=websocket,
                                session_id=session_id,
                                content=content,
                                enable_thinking=enable_thinking,
                                enable_tools=enable_tools,
                                client_message_id=client_message_id,
                            )

                    else:
                        await self._send_json(websocket, {
                            "type": "error",
                            "message": f"Unknown message type: {msg_type}",
                        })

                except json.JSONDecodeError:
                    await self._send_json(websocket, {
                        "type": "error",
                        "message": "Invalid JSON",
                    })

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected: %s", connection_id)
        except Exception as e:
            logger.error("WebSocket error in %s: %s", connection_id, e)
            try:
                await self._send_json(websocket, {
                    "type": "error",
                    "message": str(e),
                })
            except Exception as e:
                logger.debug("Failed to send error to WS: %s", e)
        finally:
            keepalive_task.cancel()
            self._active_connections.pop(connection_id, None)
            logger.info("WebSocket cleaned up: %s", connection_id)

    async def _handle_message(
        self,
        websocket: WebSocket,
        session_id: str,
        content: str,
        enable_thinking: bool = False,
        enable_tools: bool = True,
        client_message_id: str | None = None,
    ) -> None:
        """
        Handle a single chat message: persist user msg, stream LLM response,
        handle tool calls, persist assistant msg.
        """
        from db.models import EngineChatSession, EngineChatMessage

        accumulator = StreamAccumulator(started_at=time.monotonic())

        trace_token = None
        async with self._db_factory() as db:
            # Load session
            from sqlalchemy import select, and_, or_
            result = await db.execute(
                select(EngineChatSession).where(
                    EngineChatSession.id == uuid.UUID(session_id)
                )
            )
            session = result.scalar_one_or_none()
            if session is None:
                await self._send_json(websocket, {
                    "type": "error",
                    "message": f"Session {session_id} not found",
                })
                return

            if session.status == "ended":
                # Auto-reactivate ended sessions (matches _validate_session behaviour)
                session.status = "active"
                session.ended_at = None

            accumulator.model = session.model or self.config.default_model
            trace_id = f"tr_{uuid.uuid4().hex[:12]}"
            trace_token = _stream_trace_id_ctx.set(trace_id)

            # Signal frontend to create streaming message bubble
            await self._send_json(websocket, {"type": "stream_start"})

            if client_message_id:
                existing_user_result = await db.execute(
                    select(EngineChatMessage)
                    .where(
                        EngineChatMessage.session_id == uuid.UUID(session_id),
                        EngineChatMessage.role == "user",
                        or_(
                            EngineChatMessage.client_message_id == client_message_id,
                            and_(
                                EngineChatMessage.client_message_id.is_(None),
                                EngineChatMessage.metadata_json["client_message_id"].astext == client_message_id,
                            ),
                        ),
                    )
                    .order_by(EngineChatMessage.created_at.desc())
                    .limit(1)
                )
                existing_user = existing_user_result.scalar_one_or_none()
                if existing_user is not None:
                    logger.info(
                        "Idempotent replay for session=%s client_message_id=%s",
                        session_id,
                        client_message_id,
                    )
                    await self._send_json(websocket, {
                        "type": "idempotent_replay",
                        "client_message_id": client_message_id,
                    })
                    replayed = await self._replay_existing_turn(
                        db=db,
                        websocket=websocket,
                        session_id=session_id,
                        user_message=existing_user,
                        model=session.model or self.config.default_model,
                    )
                    if not replayed:
                        await self._send_json(websocket, {
                            "type": "error",
                            "message": "Duplicate message is still processing; retry shortly",
                        })
                    if trace_token is not None:
                        _stream_trace_id_ctx.reset(trace_token)
                    return

            # Persist user message (with dedup)
            now = datetime.now(timezone.utc)
            dedup_cutoff = now - __import__('datetime').timedelta(seconds=5)
            dup_check = await db.execute(
                select(EngineChatMessage.id)
                .where(
                    EngineChatMessage.session_id == uuid.UUID(session_id),
                    EngineChatMessage.role == "user",
                    EngineChatMessage.content == content,
                    EngineChatMessage.created_at >= dedup_cutoff,
                )
                .limit(1)
            )
            if dup_check.scalar_one_or_none() is not None:
                logger.warning("Duplicate user message suppressed (streaming) %s", session_id)
                await self._send_json(websocket, {
                    "type": "error",
                    "message": "Duplicate message — same content sent within 5s",
                })
                if trace_token is not None:
                    _stream_trace_id_ctx.reset(trace_token)
                return

            user_msg_id = uuid.uuid4()
            user_msg = EngineChatMessage(
                id=user_msg_id,
                session_id=uuid.UUID(session_id),
                role="user",
                content=content,
                client_message_id=client_message_id,
                metadata_json=(
                    {"client_message_id": client_message_id}
                    if client_message_id
                    else {}
                ),
                created_at=now,
            )
            db.add(user_msg)
            try:
                await db.flush()
            except Exception as flush_err:
                from sqlalchemy.exc import IntegrityError

                if not isinstance(flush_err, IntegrityError) or not client_message_id:
                    raise
                await db.rollback()
                logger.info(
                    "Idempotent race detected; replaying existing turn for session=%s client_message_id=%s",
                    session_id,
                    client_message_id,
                )
                async with self._db_factory() as db_retry:
                    existing_user_result = await db_retry.execute(
                        select(EngineChatMessage)
                        .where(
                            EngineChatMessage.session_id == uuid.UUID(session_id),
                            EngineChatMessage.role == "user",
                            or_(
                                EngineChatMessage.client_message_id == client_message_id,
                                and_(
                                    EngineChatMessage.client_message_id.is_(None),
                                    EngineChatMessage.metadata_json["client_message_id"].astext == client_message_id,
                                ),
                            ),
                        )
                        .order_by(EngineChatMessage.created_at.desc())
                        .limit(1)
                    )
                    existing_user = existing_user_result.scalar_one_or_none()
                    if existing_user is not None:
                        await self._send_json(websocket, {
                            "type": "idempotent_replay",
                            "client_message_id": client_message_id,
                        })
                        replayed = await self._replay_existing_turn(
                            db=db_retry,
                            websocket=websocket,
                            session_id=session_id,
                            user_message=existing_user,
                            model=session.model or self.config.default_model,
                        )
                        if replayed:
                            if trace_token is not None:
                                _stream_trace_id_ctx.reset(trace_token)
                            return
                await self._send_json(websocket, {
                    "type": "error",
                    "message": "Duplicate message is still processing; retry shortly",
                })
                if trace_token is not None:
                    _stream_trace_id_ctx.reset(trace_token)
                return

            # Build conversation context
            messages = await self._build_context(db, session, content)
            tools_for_llm = self.tools.get_tools_for_llm() if enable_tools else None
            turn_state = TurnStateMachine()
            turn_state.transition("streaming")

            # ── Stream LLM response ───────────────────────────────────────
            max_tool_iterations = 20
            max_per_tool_failures = 3
            promise_repair_used = False
            promise_repair_triggered = False
            tool_failure_counts: dict[str, int] = {}
            delegation_failures = 0
            delegation_blocked_reason: str | None = None
            delegation_guidance_added = False
            total_tool_failures = 0
            max_total_tool_failures = 8
            intermediate_assistant_count = 0
            # Execution trace for UI graph reconstruction
            _exec_trace: dict[str, Any] = {
                "iterations": 0,
                "tools": [],   # [{name, id, success, duration_ms}]
                "nodes": [],   # vis.js compatible node list
                "edges": [],   # vis.js compatible edge list
            }
            for iteration in range(max_tool_iterations):
                active_tools = tools_for_llm
                if delegation_blocked_reason:
                    active_tools = self._filter_tools_for_turn(
                        tools_for_llm,
                        delegation_blocked=True,
                    )
                    if not delegation_guidance_added:
                        messages.append({
                            "role": "system",
                            "content": (
                                "Delegation/sub-agent channel is unavailable in this turn. "
                                f"Reason: {delegation_blocked_reason}. "
                                "Do not call agent_manager tools again. Continue with direct tools "
                                "and provide a concrete final answer now."
                            ),
                        })
                        delegation_guidance_added = True

                saw_tool_call_delta = False
                streamed_tool_calls: dict[int, dict[str, Any]] = {}
                iteration_stream_content = ""
                iteration_stream_thinking = ""
                iteration_input_tokens = 0

                def _apply_tool_call_delta(delta: dict[str, Any]) -> None:
                    idx_raw = delta.get("index")
                    try:
                        idx = int(idx_raw) if idx_raw is not None else 0
                    except (TypeError, ValueError):
                        idx = 0

                    existing = streamed_tool_calls.setdefault(
                        idx,
                        {
                            "id": None,
                            "function": {
                                "name": "",
                                "arguments": "",
                            },
                        },
                    )

                    if delta.get("id"):
                        existing["id"] = delta["id"]

                    fn = delta.get("function") or {}
                    fn_name = fn.get("name")
                    if fn_name:
                        existing["function"]["name"] = fn_name

                    fn_args = fn.get("arguments")
                    if isinstance(fn_args, str) and fn_args:
                        existing["function"]["arguments"] += fn_args

                def _finalize_streamed_tool_calls() -> list[dict[str, Any]]:
                    calls: list[dict[str, Any]] = []
                    for idx in sorted(streamed_tool_calls.keys()):
                        item = streamed_tool_calls[idx]
                        fn_name = (item.get("function") or {}).get("name") or ""
                        fn_args = (item.get("function") or {}).get("arguments") or "{}"
                        if not fn_name:
                            continue

                        # Keep arguments as JSON string for ToolRegistry.execute.
                        # Validate to catch clearly incomplete fragments.
                        try:
                            json.loads(fn_args)
                        except Exception:
                            continue

                        call_id = item.get("id") or f"stream_tc_{iteration}_{idx}"
                        calls.append(
                            {
                                "id": call_id,
                                "function": {
                                    "name": fn_name,
                                    "arguments": fn_args,
                                },
                            }
                        )
                    return calls

                # Notify frontend: iteration starting
                await self._send_json(websocket, {
                    "type": "iteration_start",
                    "iteration": iteration + 1,
                    "tool_calls_so_far": len(accumulator.tool_calls),
                })
                iteration_input_tokens = self.gateway.estimate_tokens_for_messages(
                    model=session.model,
                    messages=messages,
                )

                # ── Pre-flight token guard ────────────────────────────────────────
                _model_soft_limit, _model_hard_limit = self._get_model_token_limits(
                    session.model or self.config.default_model
                )
                if iteration_input_tokens > _model_hard_limit:
                    logger.error(
                        "Pre-flight hard limit: session=%s tokens=%d > hard_limit=%d — aborting turn",
                        session_id, iteration_input_tokens, _model_hard_limit,
                    )
                    await self._send_json(websocket, {
                        "type": "error",
                        "message": (
                            "This conversation has grown too long for me to continue reliably "
                            f"({iteration_input_tokens:,} tokens). Please start a new session "
                            "or ask me to summarize and compress this conversation first."
                        ),
                    })
                    break
                if iteration_input_tokens > _model_soft_limit and iteration == 0:
                    _pct = int(iteration_input_tokens / _model_hard_limit * 100)
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[CONTEXT MONITOR] This conversation is at {_pct}% of your "
                            f"memory capacity ({iteration_input_tokens:,} / {_model_hard_limit:,} tokens). "
                            "You MUST: (1) keep your response concise, (2) avoid unnecessary "
                            "tool calls that produce large outputs, (3) consider informing the "
                            "user that starting a new session would give you a fresh memory."
                        ),
                    })
                    await self._send_json(websocket, {
                        "type": "context_warning",
                        "used_tokens": iteration_input_tokens,
                        "limit_tokens": _model_hard_limit,
                        "percent_full": _pct,
                        "message": f"Conversation memory {_pct}% full",
                    })
                    logger.warning(
                        "Soft token limit reached: session=%s tokens=%d (%d%% of %d)",
                        session_id, iteration_input_tokens, _pct, _model_hard_limit,
                    )

                try:
                    async for chunk in self.gateway.stream(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=active_tools,
                        enable_thinking=enable_thinking,
                    ):
                        if not await self._is_connected(websocket):
                            logger.warning("Client disconnected during stream")
                            break

                        # Stream thinking tokens
                        if chunk.thinking:
                            accumulator.thinking += chunk.thinking
                            iteration_stream_thinking += chunk.thinking
                            await self._send_json(websocket, {
                                "type": "thinking",
                                "content": chunk.thinking,
                            })

                        # Stream content tokens
                        if chunk.content:
                            accumulator.content += chunk.content
                            iteration_stream_content += chunk.content
                            await self._send_json(websocket, {
                                "type": "content",
                                "content": chunk.content,
                            })

                        # Capture finish reason
                        if chunk.finish_reason:
                            accumulator.finish_reason = chunk.finish_reason

                        # Some providers stream tool-call deltas but do not set
                        # finish_reason="tool_calls" reliably.
                        if chunk.tool_call_delta:
                            saw_tool_call_delta = True
                            _apply_tool_call_delta(chunk.tool_call_delta)

                except LLMError as e:
                    await self._send_json(websocket, {
                        "type": "error",
                        "message": f"LLM error: {e}",
                    })
                    break

                # Provider streaming usage is often unavailable; estimate so
                # telemetry/session totals are not reported as zero.
                accumulator.input_tokens += max(0, iteration_input_tokens)
                iteration_generated = f"{iteration_stream_content}{iteration_stream_thinking}"
                accumulator.output_tokens += self.gateway.estimate_tokens_for_text(
                    model=session.model,
                    text=iteration_generated,
                )

                # Notify frontend: iteration result
                await self._send_json(websocket, {
                    "type": "iteration_end",
                    "iteration": iteration + 1,
                    "has_tool_calls": accumulator.finish_reason == "tool_calls" or saw_tool_call_delta,
                    "tool_count": len(streamed_tool_calls),
                })

                # Check for tool calls in accumulated content
                # If the model requested tool calls, we re-call non-streaming
                if accumulator.finish_reason == "tool_calls" or saw_tool_call_delta:
                    turn_state.transition("tool_requested")
                    resolved_tool_calls = _finalize_streamed_tool_calls()

                    # Fallback only when streamed deltas were present but incomplete.
                    if not resolved_tool_calls:
                        try:
                            llm_response = await self.gateway.complete(
                                messages=messages,
                                model=session.model,
                                temperature=session.temperature,
                                max_tokens=session.max_tokens,
                                tools=active_tools,
                                enable_thinking=enable_thinking,
                            )
                        except LLMError as e:
                            await self._send_json(websocket, {
                                "type": "error",
                                "message": f"Tool call LLM error: {e}",
                            })
                            break

                        if not llm_response.tool_calls:
                            # No tool calls after all — use the response content
                            accumulator.content = llm_response.content
                            accumulator.thinking = llm_response.thinking or accumulator.thinking
                            break

                        resolved_tool_calls = llm_response.tool_calls
                        fallback_thinking = llm_response.thinking
                        fallback_content = llm_response.content or ""
                        fallback_tokens_in = llm_response.input_tokens if hasattr(llm_response, "input_tokens") else 0
                        fallback_tokens_out = llm_response.output_tokens if hasattr(llm_response, "output_tokens") else 0
                        fallback_cost = llm_response.cost_usd if hasattr(llm_response, "cost_usd") else 0.0
                    else:
                        fallback_thinking = ""
                        fallback_content = accumulator.content or ""
                        fallback_tokens_in = 0
                        fallback_tokens_out = 0
                        fallback_cost = 0.0

                    # Execute tool calls
                    turn_state.transition("tool_executing")
                    accumulator.tool_calls.extend(resolved_tool_calls)
                    accumulator.input_tokens += int(fallback_tokens_in or 0)
                    accumulator.output_tokens += int(fallback_tokens_out or 0)
                    accumulator.cost_usd += float(fallback_cost or 0.0)

                    # Track LLM iteration node in exec trace
                    _exec_trace["iterations"] += 1
                    _llm_node_id = f"llm_{_exec_trace['iterations']}"
                    _exec_trace["nodes"].append({
                        "id": _llm_node_id,
                        "label": f"LLM #{_exec_trace['iterations']}",
                        "shape": "box",
                        "level": iteration + 1,
                        "color": {"background": "#1e2d3a", "border": "#4a9eed"},
                        "font": {"color": "#4a9eed", "size": 12},
                    })
                    # Connect from previous iteration's tools (if any) or from start
                    if _exec_trace["iterations"] > 1:
                        # Link previous tool nodes → this LLM node
                        prev_iter = _exec_trace["iterations"] - 1
                        prev_tools = [n["id"] for n in _exec_trace["nodes"] if n["id"].startswith("tool_") and n.get("_iter") == prev_iter]
                        for pt in prev_tools:
                            _exec_trace["edges"].append({"from": pt, "to": _llm_node_id, "label": "result", "arrows": "to", "font": {"size": 10, "color": "#888"}})

                    assistant_entry: dict[str, Any] = {
                        "role": "assistant",
                        "content": fallback_content,
                        "tool_calls": resolved_tool_calls,
                    }
                    # Include thinking so models that require reasoning_content
                    # on tool-call messages (e.g. Kimi) don't reject the request
                    if fallback_thinking or accumulator.thinking:
                        assistant_entry["reasoning_content"] = fallback_thinking or accumulator.thinking
                    messages.append(assistant_entry)

                    # Persist intermediate assistant message so tool results
                    # aren't orphaned if the session ends mid-iteration.
                    intermediate_msg = EngineChatMessage(
                        id=uuid.uuid4(),
                        session_id=uuid.UUID(session_id),
                        role="assistant",
                        content=fallback_content,
                        thinking=fallback_thinking or None,
                        tool_calls=resolved_tool_calls,
                        model=accumulator.model,
                        tokens_input=fallback_tokens_in,
                        tokens_output=fallback_tokens_out,
                        cost=fallback_cost,
                        latency_ms=accumulator.latency_ms,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(intermediate_msg)
                    await db.flush()
                    intermediate_assistant_count += 1

                    for tc in resolved_tool_calls:
                        fn_name = tc["function"]["name"]

                        # Notify client about tool call
                        await self._send_json(websocket, {
                            "type": "tool_call",
                            "name": fn_name,
                            "arguments": tc["function"]["arguments"],
                            "id": tc["id"],
                        })

                        # Per-tool failure cap
                        if delegation_blocked_reason and self._is_delegation_tool(fn_name):
                            tool_result = ToolResult(
                                tool_call_id=tc["id"],
                                name=fn_name,
                                content=json.dumps({
                                    "error": (
                                        "Delegation is disabled for this turn due to previous failures: "
                                        f"{delegation_blocked_reason}. Use direct tools and conclude."
                                    )
                                }),
                                success=False,
                            )
                        elif tool_failure_counts.get(fn_name, 0) >= max_per_tool_failures:
                            logger.warning(
                                "Tool %s failed %d times in stream %s — blocking",
                                fn_name, tool_failure_counts[fn_name], session_id,
                            )
                            tool_result = ToolResult(
                                tool_call_id=tc["id"],
                                name=fn_name,
                                content=json.dumps({
                                    "error": f"Tool '{fn_name}' has failed "
                                    f"{tool_failure_counts[fn_name]} consecutive "
                                    "times this turn. Do NOT call it again — "
                                    "use an alternative or inform the user."
                                }),
                                success=False,
                            )
                        else:
                            # Execute tool
                            tool_result = await self.tools.execute(
                                tool_call_id=tc["id"],
                                function_name=fn_name,
                                arguments=tc["function"]["arguments"],
                            )

                        # Track failures
                        if tool_result.success:
                            tool_failure_counts.pop(fn_name, None)
                        else:
                            tool_failure_counts[fn_name] = tool_failure_counts.get(fn_name, 0) + 1
                            total_tool_failures += 1
                            if self._is_delegation_tool(fn_name):
                                delegation_failures += 1
                                err_text = self._extract_tool_error(tool_result.content)
                                if (
                                    delegation_blocked_reason is None
                                    and (
                                        delegation_failures >= self.MAX_DELEGATION_FAILURES
                                        or self._is_blocking_delegation_failure(err_text)
                                    )
                                ):
                                    delegation_blocked_reason = (
                                        err_text
                                        or "delegation/sub-agent communication unavailable"
                                    )
                                    logger.warning(
                                        "Streaming session %s delegation blocked after %d failure(s): %s",
                                        session_id,
                                        delegation_failures,
                                        delegation_blocked_reason,
                                    )

                        accumulator.tool_results.append({
                            "tool_call_id": tool_result.tool_call_id,
                            "name": tool_result.name,
                            "content": tool_result.content,
                            "success": tool_result.success,
                            "duration_ms": tool_result.duration_ms,
                        })

                        # Track tool in exec trace
                        tool_node_id = f"tool_{tc['id']}"
                        _exec_trace["tools"].append({
                            "name": fn_name, "id": tc["id"],
                            "success": tool_result.success,
                            "duration_ms": tool_result.duration_ms,
                        })
                        _color = {"background": "#1e3a2f", "border": "#2ea86f"} if tool_result.success else {"background": "#3a1e1e", "border": "#d44a4a"}
                        _label = fn_name.replace("_", "\n")
                        _exec_trace["nodes"].append({
                            "id": tool_node_id, "label": _label,
                            "shape": "diamond", "level": iteration + 1.5,
                            "color": _color,
                            "font": {"color": _color["border"], "size": 11},
                            "_iter": _exec_trace["iterations"],
                        })
                        _exec_trace["edges"].append({"from": f"llm_{_exec_trace['iterations']}", "to": tool_node_id, "label": "call", "arrows": "to", "font": {"size": 10, "color": "#888"}})

                        # Telemetry → aria_data.skill_invocations
                        asyncio.ensure_future(log_skill_invocation(
                            self._db_factory,
                            skill_name=_parse_skill_from_tool(fn_name),
                            tool_name=fn_name,
                            duration_ms=tool_result.duration_ms,
                            success=tool_result.success,
                            model_used=accumulator.model,
                        ))

                        # Notify client about tool result
                        parsed_content = None
                        content_error = None
                        try:
                            parsed_content = json.loads(tool_result.content)
                            if isinstance(parsed_content, dict):
                                content_error = parsed_content.get("error")
                        except Exception:
                            parsed_content = tool_result.content

                        status = "success" if tool_result.success else "error"
                        await self._send_json(websocket, {
                            "type": "tool_result",
                            "name": tool_result.name,
                            "content": tool_result.content,
                            "result": parsed_content,
                            "status": status,
                            "error": content_error,
                            "duration_ms": tool_result.duration_ms,
                            "tool_call_id": tool_result.tool_call_id,
                            "id": tool_result.tool_call_id,
                            "success": tool_result.success,
                        })

                        # Add to messages for next LLM turn
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_result.tool_call_id,
                            "content": tool_result.content,
                        })

                        # Persist tool message
                        tool_msg = EngineChatMessage(
                            id=uuid.uuid4(),
                            session_id=uuid.UUID(session_id),
                            role="tool",
                            content=tool_result.content,
                            tool_results={
                                "tool_call_id": tc["id"],
                                "name": fn_name,
                            },
                            latency_ms=tool_result.duration_ms,
                            created_at=datetime.now(timezone.utc),
                        )
                        db.add(tool_msg)

                    # Reset accumulator content for next stream
                    accumulator.content = ""
                    accumulator.finish_reason = ""
                    if total_tool_failures >= max_total_tool_failures:
                        logger.warning(
                            "Streaming session %s reached %d tool failures; stopping tool loop",
                            session_id,
                            total_tool_failures,
                        )
                        break
                    turn_state.transition("followup_generation")
                    turn_state.transition("streaming")
                    continue  # Re-stream with tool results

                # No tool calls — done
                if (
                    enable_tools
                    and not promise_repair_used
                    and self._looks_like_promised_action_without_execution(accumulator.content)
                ):
                    if not self.config.streaming_promised_action_repair:
                        self._repair_stats["skipped_disabled"] += 1
                        break

                    promise_repair_used = True
                    promise_repair_triggered = True
                    self._repair_stats["triggered"] += 1
                    logger.warning(
                        "Repairing promised-action turn without tool execution for session %s",
                        session_id,
                    )
                    messages.append({
                        "role": "assistant",
                        "content": accumulator.content,
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            "You said you are executing now. Execute the relevant tool call in this turn "
                            "or provide the concrete final result immediately. Do not promise future actions."
                        ),
                    })
                    accumulator.content = ""
                    accumulator.finish_reason = ""
                    continue

                break

            if (
                delegation_blocked_reason is not None
                or total_tool_failures >= max_total_tool_failures
                or self._looks_like_promised_action_without_execution(accumulator.content)
            ):
                try:
                    if delegation_blocked_reason:
                        messages.append({
                            "role": "system",
                            "content": (
                                "End this turn now with a direct answer. "
                                "Delegation is unavailable. "
                                "State limits explicitly and do not promise future actions."
                            ),
                        })
                    summary_response = await self.gateway.complete(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=None,
                        enable_thinking=False,
                    )
                    if summary_response.content:
                        accumulator.content = summary_response.content
                    accumulator.thinking = summary_response.thinking or accumulator.thinking
                    accumulator.finish_reason = summary_response.finish_reason or accumulator.finish_reason
                    accumulator.input_tokens += int(summary_response.input_tokens or 0)
                    accumulator.output_tokens += int(summary_response.output_tokens or 0)
                    accumulator.cost_usd += float(summary_response.cost_usd or 0.0)
                except Exception as summary_err:
                    logger.warning("Streaming summary fallback failed for %s: %s", session_id, summary_err)

            if not (accumulator.content or "").strip() and delegation_blocked_reason:
                accumulator.content = (
                    "I could not delegate this task because the sub-agent channel is unavailable "
                    f"({delegation_blocked_reason}). I continued with direct tools in this session. "
                    "Please retry delegation in a new turn after the agent channel recovers."
                )

            # ── Persist assistant message ─────────────────────────────────
            # Finalize exec trace
            if turn_state.current != "finalized":
                turn_state.transition("finalized")
            _trace_meta: dict[str, Any] = {}
            if _exec_trace["tools"]:
                _total_ms = accumulator.latency_ms or 0
                # Add response node
                _resp_label = f"Response\n{(_total_ms / 1000):.1f}s" if _total_ms else "Response"
                _exec_trace["nodes"].append({
                    "id": "response", "label": _resp_label,
                    "shape": "star", "level": _exec_trace["iterations"] + 1,
                    "color": {"background": "#2a1a3e", "border": "#9b59d4"},
                    "font": {"color": "#9b59d4", "size": 12},
                })
                # Connect last iteration's tool nodes → response
                last_tools = [n["id"] for n in _exec_trace["nodes"] if n["id"].startswith("tool_") and n.get("_iter") == _exec_trace["iterations"]]
                if last_tools:
                    for lt in last_tools:
                        _exec_trace["edges"].append({"from": lt, "to": "response", "arrows": "to"})
                else:
                    _from_node = f"llm_{_exec_trace['iterations']}" if _exec_trace["iterations"] else "llm_1"
                    _exec_trace["edges"].append({"from": _from_node, "to": "response", "arrows": "to"})
                _exec_trace["latency_ms"] = _total_ms
                _exec_trace["total_tools"] = len(_exec_trace["tools"])
                # Strip internal _iter tag from nodes before serializing
                for n in _exec_trace["nodes"]:
                    n.pop("_iter", None)
                _trace_meta = {"exec_trace": _exec_trace}
            _trace_meta.setdefault("turn_state", {
                "current": turn_state.current,
                "history": turn_state.history,
            })

            assistant_msg_id = uuid.uuid4()
            assistant_msg = EngineChatMessage(
                id=assistant_msg_id,
                session_id=uuid.UUID(session_id),
                role="assistant",
                content=accumulator.content,
                thinking=accumulator.thinking or None,
                tool_calls=accumulator.tool_calls if accumulator.tool_calls else None,
                tool_results=accumulator.tool_results if accumulator.tool_results else None,
                model=accumulator.model,
                tokens_input=accumulator.input_tokens,
                tokens_output=accumulator.output_tokens,
                cost=accumulator.cost_usd,
                latency_ms=accumulator.latency_ms,
                metadata_json=_trace_meta if _trace_meta else {},
                created_at=datetime.now(timezone.utc),
            )
            db.add(assistant_msg)

            # Commit messages first (critical data).
            await db.commit()

            # ── Update session counters (separate transaction) ────────────
            # Done in its own transaction so a transient lock/deadlock doesn't
            # roll back the already-committed messages.
            try:
                async with self._db_factory() as db2:
                    from sqlalchemy import update, func
                    msg_count = 2 + len(accumulator.tool_results) + intermediate_assistant_count

                    values: dict[str, Any] = {
                        "message_count": func.coalesce(EngineChatSession.message_count, 0) + msg_count,
                        "total_tokens": (
                            func.coalesce(EngineChatSession.total_tokens, 0)
                            + accumulator.input_tokens
                            + accumulator.output_tokens
                        ),
                        "total_cost": func.coalesce(EngineChatSession.total_cost, 0.0) + accumulator.cost_usd,
                        "updated_at": datetime.now(timezone.utc),
                    }

                    # Auto-title on first message
                    if not session.title and (session.message_count or 0) <= msg_count:
                        title = content.strip().replace("\n", " ")
                        title = " ".join(title.split())
                        if len(title) > 80:
                            title = title[:77] + "..."
                        values["title"] = title

                    await db2.execute(
                        update(EngineChatSession)
                        .where(EngineChatSession.id == uuid.UUID(session_id))
                        .values(**values)
                    )
                    await db2.commit()
            except Exception as counter_err:
                logger.warning(
                    "Session counter update failed for %s (messages safe): %s",
                    session_id, counter_err,
                )

            # Telemetry → aria_data.model_usage
            asyncio.ensure_future(log_model_usage(
                self._db_factory,
                model=accumulator.model or "unknown",
                input_tokens=accumulator.input_tokens,
                output_tokens=accumulator.output_tokens,
                cost_usd=accumulator.cost_usd,
                latency_ms=accumulator.latency_ms,
                success=True,
            ))

            if promise_repair_triggered and (accumulator.tool_calls or accumulator.tool_results or accumulator.content.strip()):
                self._repair_stats["succeeded"] += 1

            # ── Send stream_end (combines usage + done for frontend) ────
            await self._send_json(websocket, {
                "type": "stream_end",
                "message_id": str(assistant_msg_id),
                "finish_reason": accumulator.finish_reason,
                "model": accumulator.model,
                "tokens_input": accumulator.input_tokens,
                "tokens_output": accumulator.output_tokens,
                "cost": accumulator.cost_usd,
                "repair_applied": promise_repair_triggered,
                "usage_estimated": True,
            })
            if trace_token is not None:
                _stream_trace_id_ctx.reset(trace_token)

    async def _replay_existing_turn(
        self,
        db,
        websocket: WebSocket,
        session_id: str,
        user_message,
        model: str,
    ) -> bool:
        """Replay a previously completed turn for idempotent client retries."""
        from db.models import EngineChatMessage
        from sqlalchemy import select

        result = await db.execute(
            select(EngineChatMessage)
            .where(
                EngineChatMessage.session_id == uuid.UUID(session_id),
                EngineChatMessage.created_at >= user_message.created_at,
            )
            .order_by(EngineChatMessage.created_at.asc(), EngineChatMessage.id.asc())
            .limit(200)
        )
        window = result.scalars().all()
        assistant_msg = None

        for msg in window:
            if msg.role == "user" and msg.id != user_message.id:
                break

            if msg.role == "tool":
                tr = msg.tool_results or {}
                await self._send_json(websocket, {
                    "type": "tool_result",
                    "name": tr.get("name", "tool"),
                    "id": tr.get("tool_call_id", ""),
                    "success": True,
                    "content": msg.content,
                    "result": msg.content,
                    "status": "success",
                    "error": None,
                    "duration_ms": msg.latency_ms or 0,
                    "tool_call_id": tr.get("tool_call_id", ""),
                })
                continue

            if msg.role == "assistant":
                assistant_msg = msg
                break

        if assistant_msg is None:
            return False

        if assistant_msg.content:
            await self._send_json(websocket, {
                "type": "content",
                "content": assistant_msg.content,
            })

        if assistant_msg.thinking:
            await self._send_json(websocket, {
                "type": "thinking",
                "content": assistant_msg.thinking,
            })

        await self._send_json(websocket, {
            "type": "stream_end",
            "message_id": str(assistant_msg.id),
            "finish_reason": "idempotent_replay",
            "model": assistant_msg.model or model,
            "tokens_input": assistant_msg.tokens_input or 0,
            "tokens_output": assistant_msg.tokens_output or 0,
            "cost": float(assistant_msg.cost or 0.0),
            "repair_applied": False,
            "usage_estimated": bool((assistant_msg.metadata_json or {}).get("usage_estimated", True)),
        })
        return True

    async def _validate_session(self, session_id: str) -> None:
        """Validate that a session exists and is active.

        If the session status is 'ended', it is automatically reactivated so the
        user can reconnect without creating a new session.
        """
        from db.models import EngineChatSession
        from sqlalchemy import select, update

        async with self._db_factory() as db:
            # Select id+status so a NULL status doesn't look like "row not found"
            result = await db.execute(
                select(EngineChatSession.id, EngineChatSession.status).where(
                    EngineChatSession.id == uuid.UUID(session_id)
                )
            )
            row = result.one_or_none()
            if row is None:
                raise SessionError(f"Session {session_id} not found")
            status = row[1]  # may be None
            if status == "ended":
                # Auto-reactivate ended sessions so users can reconnect
                await db.execute(
                    update(EngineChatSession)
                    .where(EngineChatSession.id == uuid.UUID(session_id))
                    .values(status="active", ended_at=None)
                )
                await db.commit()
                logger.info("Reactivated ended session %s for WS reconnect", session_id)

    async def _build_context(
        self,
        db,
        session,
        current_content: str,
    ) -> list[dict[str, Any]]:
        """Build conversation context from DB messages (same as ChatEngine)."""
        from db.models import EngineChatMessage
        from sqlalchemy import select

        messages: list[dict[str, Any]] = []

        if session.system_prompt:
            messages.append({"role": "system", "content": session.system_prompt})

        window = session.context_window or 50
        MIN_CONVERSATION_TURNS = 10  # always keep at least this many user+assistant msgs
        fetch_limit = max(window * 3, 200)  # over-fetch so we have room to pick
        result = await db.execute(
            select(EngineChatMessage)
            .where(EngineChatMessage.session_id == session.id)
            .order_by(EngineChatMessage.created_at.desc())
            .limit(fetch_limit)
        )
        all_db_messages = list(reversed(result.scalars().all()))

        # Split into conversation (user/assistant) and tool/system messages
        conversation_msgs = [m for m in all_db_messages if m.role in ("user", "assistant")]
        tool_msgs = [m for m in all_db_messages if m.role not in ("user", "assistant")]

        # Always keep at least MIN_CONVERSATION_TURNS of conversation history
        # plus the most recent tool messages that fit within the window
        keep_conv = conversation_msgs[-max(MIN_CONVERSATION_TURNS, window // 2):]
        keep_conv_ids = {id(m) for m in keep_conv}

        # Budget remaining window slots for tool messages (most recent first)
        tool_budget = max(window - len(keep_conv), 10)
        keep_tools = tool_msgs[-tool_budget:]
        keep_tool_ids = {id(m) for m in keep_tools}

        # Merge back in original chronological order
        db_messages = [
            m for m in all_db_messages
            if id(m) in keep_conv_ids or id(m) in keep_tool_ids
        ]

        if len(all_db_messages) > window:
            logger.info(
                "Context protection: %d total msgs → kept %d conversation + %d tool "
                "(window=%d, fetched=%d)",
                len(all_db_messages), len(keep_conv), len(keep_tools),
                window, fetch_limit,
            )

        for msg in db_messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            # Include thinking as reasoning_content for models that require it
            # (e.g. Kimi/Moonshot rejects assistant tool-call msgs without it)
            if msg.role == "assistant" and hasattr(msg, "thinking") and msg.thinking:
                entry["reasoning_content"] = msg.thinking
            # Tool messages MUST have a valid tool_call_id or the provider rejects them
            if msg.role == "tool":
                tc_id = (msg.tool_results or {}).get("tool_call_id", "") if msg.tool_results else ""
                if tc_id:
                    entry["tool_call_id"] = tc_id
                else:
                    continue  # Skip orphan / corrupt tool messages
            messages.append(entry)

        # ── Post-process: fix tool-call ordering anomalies ────────────────
        # DB may store tool results BEFORE the assistant message that triggered
        # them (race in persistence timing).  We re-order so each assistant
        # with tool_calls is immediately followed by its tool results, and any
        # orphaned tool/assistant messages are dropped.

        # 1. Build a set of all tool_call_ids declared by assistant messages
        declared_tc_ids: set[str] = set()
        for m in messages:
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    declared_tc_ids.add(tc.get("id", ""))

        # 2. Separate tool messages into a map keyed by tool_call_id
        tool_msgs_by_id: dict[str, dict] = {}
        non_tool_msgs: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                tc_id = m["tool_call_id"]
                if tc_id in declared_tc_ids:
                    tool_msgs_by_id[tc_id] = m
                # else: orphan tool message — drop silently
            else:
                non_tool_msgs.append(m)

        # 3. Rebuild: after each assistant with tool_calls, inject its tool results
        cleaned: list[dict[str, Any]] = []
        for m in non_tool_msgs:
            if m.get("tool_calls"):
                # Check which tool results exist for this assistant
                owned_ids = [tc.get("id", "") for tc in m["tool_calls"]]
                existing = [tool_msgs_by_id[tid] for tid in owned_ids if tid in tool_msgs_by_id]
                found_ids = {tr["tool_call_id"] for tr in existing}

                if len(existing) == len(owned_ids):
                    # All tool results present — safe to include as-is
                    cleaned.append(m)
                    cleaned.extend(existing)
                elif existing:
                    # Partial match: strip tool_calls that have no result to avoid
                    # provider rejecting the message (e.g. Kimi BadRequestError)
                    surviving_calls = [
                        tc for tc in m["tool_calls"]
                        if tc.get("id", "") in found_ids
                    ]
                    entry = dict(m)
                    entry["tool_calls"] = surviving_calls
                    cleaned.append(entry)
                    cleaned.extend(existing)
                    logger.debug(
                        "Context repair: kept %d/%d tool_calls for assistant message "
                        "(evicted: %s)",
                        len(surviving_calls),
                        len(owned_ids),
                        [tid for tid in owned_ids if tid not in found_ids],
                    )
                else:
                    # No tool results found — strip tool_calls, drop if empty
                    stripped = {k: v for k, v in m.items() if k != "tool_calls"}
                    if stripped.get("role") == "assistant" and not stripped.get("content"):
                        continue
                    cleaned.append(stripped)
            else:
                # Drop empty assistant messages (no content, no tool_calls)
                # — these are often artifacts from failed LLM calls.
                if m.get("role") == "assistant" and not m.get("content") and not m.get("tool_calls"):
                    continue
                cleaned.append(m)
        messages = cleaned

        # NOTE: user message is already persisted (flush) before _build_context
        # is called, so the DB query above includes it — do NOT append again.

        # ── Token budget enforcement ───────────────────────────────────────────────────────────
        # Apply ContextManager's token-aware eviction after the structural
        # cleanup above so that the final context fits within the model's limit.
        model_name = session.model or self.config.default_model
        reserve = session.max_tokens or self.config.default_max_tokens
        try:
            from aria_models.loader import load_catalog, normalize_model_id
            catalog = load_catalog()
            model_def = catalog.get("models", {}).get(normalize_model_id(model_name), {})
            safe_tokens = model_def.get("safe_prompt_tokens", 0)
            max_prompt_tokens = safe_tokens if safe_tokens > 0 else max(
                4096, (session.context_window or 50) * 3000
            )
        except Exception:
            max_prompt_tokens = max(4096, (session.context_window or 50) * 3000)
        messages = self._ctx_manager.build_context(
            all_messages=messages,
            max_tokens=max_prompt_tokens,
            model=model_name,
            reserve_tokens=reserve,
        )
        logger.info(
            "Context budget applied: session=%s model=%s max_prompt=%d reserve=%d → %d messages",
            session.id, model_name, max_prompt_tokens, reserve, len(messages),
        )

        # ── Auto-compress if approaching soft token limit ──────────────────
        # Resolve compression threshold (70% of hard limit)
        _soft, _hard = self._get_model_token_limits(model_name)
        _compression_threshold = int(_hard * 0.70)
        estimated_tokens = self.gateway.estimate_tokens_for_messages(
            model=model_name,
            messages=messages,
        )
        if estimated_tokens > _compression_threshold:
            messages = await self._maybe_compress_context(
                db=db,
                session=session,
                messages=messages,
                token_count=estimated_tokens,
                soft_threshold=_compression_threshold,
            )

        return messages

    async def _keepalive(self, websocket: WebSocket, connection_id: str) -> None:
        """Send ping every ws_ping_interval seconds to keep connection alive."""
        try:
            while True:
                await asyncio.sleep(self.config.ws_ping_interval)
                if await self._is_connected(websocket):
                    await self._send_json(websocket, {"type": "pong"})
                else:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Keepalive loop error: %s", e)

    @staticmethod
    async def _is_connected(websocket: WebSocket) -> bool:
        """Check if WebSocket is still connected."""
        return websocket.client_state == WebSocketState.CONNECTED

    @staticmethod
    async def _send_json(websocket: WebSocket, data: dict[str, Any]) -> None:
        """Send JSON data over WebSocket, silently catching disconnection."""
        try:
            if "type" in data:
                data.setdefault("protocol_version", STREAM_PROTOCOL_VERSION)
                trace_id = _stream_trace_id_ctx.get("")
                if trace_id:
                    data.setdefault("trace_id", trace_id)
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_text(json.dumps(data))
        except Exception as e:
            logger.debug("WS send_json failed: %s", e)

    @property
    def active_connections(self) -> int:
        """Number of active WebSocket connections."""
        return len(self._active_connections)
