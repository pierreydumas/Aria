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
    {"type": "ping"}

  Server → Client:
    {"type": "token", "content": "Hello"}
    {"type": "thinking", "content": "Let me consider..."}
    {"type": "tool_call", "name": "search", "arguments": {"q": "..."}, "id": "tc_1"}
    {"type": "tool_result", "name": "search", "content": "...", "id": "tc_1", "success": true}
    {"type": "usage", "input_tokens": 100, "output_tokens": 50, "cost": 0.001}
    {"type": "done", "message_id": "uuid", "finish_reason": "stop"}
    {"type": "error", "message": "..."}
    {"type": "pong"}
"""
import asyncio
import json
import logging
import time
import uuid
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
    ) -> None:
        """
        Handle a single chat message: persist user msg, stream LLM response,
        handle tool calls, persist assistant msg.
        """
        from db.models import EngineChatSession, EngineChatMessage

        accumulator = StreamAccumulator(started_at=time.monotonic())

        async with self._db_factory() as db:
            # Load session
            from sqlalchemy import select
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

            # Signal frontend to create streaming message bubble
            await self._send_json(websocket, {"type": "stream_start"})

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
                return

            user_msg_id = uuid.uuid4()
            user_msg = EngineChatMessage(
                id=user_msg_id,
                session_id=uuid.UUID(session_id),
                role="user",
                content=content,
                created_at=now,
            )
            db.add(user_msg)
            await db.flush()

            # Build conversation context
            messages = await self._build_context(db, session, content)
            tools_for_llm = self.tools.get_tools_for_llm() if enable_tools else None

            # ── Stream LLM response ───────────────────────────────────────
            max_tool_iterations = 20
            max_per_tool_failures = 3
            tool_failure_counts: dict[str, int] = {}
            # Execution trace for UI graph reconstruction
            _exec_trace: dict[str, Any] = {
                "iterations": 0,
                "tools": [],   # [{name, id, success, duration_ms}]
                "nodes": [],   # vis.js compatible node list
                "edges": [],   # vis.js compatible edge list
            }
            for iteration in range(max_tool_iterations):
                # Notify frontend: iteration starting
                await self._send_json(websocket, {
                    "type": "iteration_start",
                    "iteration": iteration + 1,
                    "tool_calls_so_far": len(accumulator.tool_calls),
                })
                try:
                    async for chunk in self.gateway.stream(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=tools_for_llm,
                        enable_thinking=enable_thinking,
                    ):
                        if not await self._is_connected(websocket):
                            logger.warning("Client disconnected during stream")
                            break

                        # Stream thinking tokens
                        if chunk.thinking:
                            accumulator.thinking += chunk.thinking
                            await self._send_json(websocket, {
                                "type": "thinking",
                                "content": chunk.thinking,
                            })

                        # Stream content tokens
                        if chunk.content:
                            accumulator.content += chunk.content
                            await self._send_json(websocket, {
                                "type": "content",
                                "content": chunk.content,
                            })

                        # Capture finish reason
                        if chunk.finish_reason:
                            accumulator.finish_reason = chunk.finish_reason

                except LLMError as e:
                    await self._send_json(websocket, {
                        "type": "error",
                        "message": f"LLM error: {e}",
                    })
                    break

                # Notify frontend: iteration result
                await self._send_json(websocket, {
                    "type": "iteration_end",
                    "iteration": iteration + 1,
                    "has_tool_calls": accumulator.finish_reason == "tool_calls",
                    "tool_count": 0,  # updated below after resolving tool_calls
                })

                # Check for tool calls in accumulated content
                # If the model requested tool calls, we re-call non-streaming
                if accumulator.finish_reason == "tool_calls":
                    # Fall back to non-streaming for tool call execution
                    try:
                        llm_response = await self.gateway.complete(
                            messages=messages,
                            model=session.model,
                            temperature=session.temperature,
                            max_tokens=session.max_tokens,
                            tools=tools_for_llm,
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

                    # Execute tool calls
                    accumulator.tool_calls.extend(llm_response.tool_calls)

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
                        "content": llm_response.content or "",
                        "tool_calls": llm_response.tool_calls,
                    }
                    # Include thinking so models that require reasoning_content
                    # on tool-call messages (e.g. Kimi) don't reject the request
                    if llm_response.thinking:
                        assistant_entry["reasoning_content"] = llm_response.thinking
                    messages.append(assistant_entry)

                    # Persist intermediate assistant message so tool results
                    # aren't orphaned if the session ends mid-iteration.
                    intermediate_msg = EngineChatMessage(
                        id=uuid.uuid4(),
                        session_id=uuid.UUID(session_id),
                        role="assistant",
                        content=llm_response.content or "",
                        thinking=llm_response.thinking or None,
                        tool_calls=llm_response.tool_calls,
                        model=accumulator.model,
                        tokens_input=llm_response.input_tokens if hasattr(llm_response, 'input_tokens') else 0,
                        tokens_output=llm_response.output_tokens if hasattr(llm_response, 'output_tokens') else 0,
                        cost=llm_response.cost_usd if hasattr(llm_response, 'cost_usd') else 0,
                        latency_ms=accumulator.latency_ms,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(intermediate_msg)
                    await db.flush()

                    for tc in llm_response.tool_calls:
                        fn_name = tc["function"]["name"]

                        # Notify client about tool call
                        await self._send_json(websocket, {
                            "type": "tool_call",
                            "name": fn_name,
                            "arguments": tc["function"]["arguments"],
                            "id": tc["id"],
                        })

                        # Per-tool failure cap
                        if tool_failure_counts.get(fn_name, 0) >= max_per_tool_failures:
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
                        await self._send_json(websocket, {
                            "type": "tool_result",
                            "name": tool_result.name,
                            "content": tool_result.content,
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
                    continue  # Re-stream with tool results

                # No tool calls — done
                break

            # ── Persist assistant message ─────────────────────────────────
            # Finalize exec trace
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
                    from sqlalchemy import update
                    msg_count = 2 + len(accumulator.tool_results)

                    values: dict[str, Any] = {
                        "message_count": (session.message_count or 0) + msg_count,
                        "total_tokens": (
                            (session.total_tokens or 0)
                            + accumulator.input_tokens
                            + accumulator.output_tokens
                        ),
                        "total_cost": float(session.total_cost or 0) + accumulator.cost_usd,
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

            # ── Send stream_end (combines usage + done for frontend) ────
            await self._send_json(websocket, {
                "type": "stream_end",
                "message_id": str(assistant_msg_id),
                "finish_reason": accumulator.finish_reason,
                "model": accumulator.model,
                "tokens_input": accumulator.input_tokens,
                "tokens_output": accumulator.output_tokens,
                "cost": accumulator.cost_usd,
            })

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
                if existing:
                    cleaned.append(m)
                    cleaned.extend(existing)
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
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_text(json.dumps(data))
        except Exception as e:
            logger.debug("WS send_json failed: %s", e)

    @property
    def active_connections(self) -> int:
        """Number of active WebSocket connections."""
        return len(self._active_connections)
