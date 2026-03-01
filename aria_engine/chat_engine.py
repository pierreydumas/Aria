"""
Chat Engine — Native session lifecycle management.

PostgreSQL-backed session lifecycle management.
Features:
- Create/resume/end sessions with full state tracking
- Send messages with LLM completion and tool calling
- Auto-generate session titles from first user message
- Track token counts and costs per message and per session
- Context window integration for conversation history
- Tool call loop: LLM → tool → result → LLM until done

Uses:
- EngineChatSession / EngineChatMessage ORM models (S1-05)
- LLMGateway for completions (S1-02)
- ToolRegistry for function calling (S1-04)
- ThinkingHandler for reasoning tokens (S1-03)
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from aria_engine.config import EngineConfig
from aria_engine.exceptions import SessionError, LLMError
from aria_engine.llm_gateway import LLMGateway, LLMResponse
from aria_engine.telemetry import log_model_usage, log_skill_invocation, _parse_skill_from_tool
from aria_engine.tool_registry import ToolRegistry, ToolResult
from aria_engine.thinking import extract_thinking_from_response, strip_thinking_from_content

logger = logging.getLogger("aria.engine.chat")


@dataclass
class ChatResponse:
    """Response from a chat message."""
    message_id: str
    session_id: str
    content: str
    thinking: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "content": self.content,
            "thinking": self.thinking,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
        }


class ChatEngine:
    """
    Native chat session lifecycle manager.

    Usage:
        engine = ChatEngine(config, gateway, tool_registry, db_session_factory)

        # Create a new session:
        session = await engine.create_session(agent_id="main", model="qwen3-30b-mlx")

        # Send a message and get a response:
        response = await engine.send_message(session.id, "Hello, Aria!")

        # Resume an existing session:
        session = await engine.resume_session(session_id)

        # End a session:
        await engine.end_session(session_id)
    """

    # Maximum tool call iterations to prevent infinite loops
    MAX_TOOL_ITERATIONS = 50

    # Per-tool consecutive failure cap — after this many failures of the
    # *same* tool in one turn, we inject a rejection so the LLM stops retrying.
    MAX_PER_TOOL_FAILURES = 3

    # Window (seconds) for deduplicating identical user messages
    DEDUP_WINDOW_SECONDS = 5

    # Slash commands that trigger multi-agent orchestration
    SLASH_COMMANDS = {"/roundtable", "/swarm"}

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
        # Optional multi-agent orchestration (set by main.py after init)
        self._roundtable: Any | None = None
        self._swarm: Any | None = None
        self._escalation_router: Any | None = None

    def set_roundtable(self, roundtable: Any) -> None:
        """Inject Roundtable instance for /roundtable slash command."""
        self._roundtable = roundtable

    def set_swarm(self, swarm: Any) -> None:
        """Inject SwarmOrchestrator instance for /swarm slash command."""
        self._swarm = swarm

    def set_escalation_router(self, router: Any) -> None:
        """Inject EngineRouter for auto-escalation detection."""
        self._escalation_router = router  # async sessionmaker

    async def create_session(
        self,
        agent_id: str = "main",
        model: str | None = None,
        session_type: str = "interactive",
        title: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        context_window: int = 50,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new chat session.

        Args:
            agent_id: Agent owning this session.
            model: LLM model to use (defaults to config.default_model).
            session_type: 'interactive', 'cron', 'subagent', etc.
            system_prompt: Override system prompt (normally assembled by PromptAssembler).
            temperature: Override temperature.
            max_tokens: Override max tokens.
            context_window: Number of messages to keep in context.
            metadata: Arbitrary JSON metadata.

        Returns:
            Dict with session fields (id, agent_id, model, status, …).
        """
        from db.models import EngineChatSession

        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        async with self._db_factory() as db:
            session = EngineChatSession(
                id=session_id,
                agent_id=agent_id,
                session_type=session_type,
                title=title,
                model=model or self.config.default_model,
                temperature=temperature or self.config.default_temperature,
                max_tokens=max_tokens or self.config.default_max_tokens,
                context_window=context_window,
                system_prompt=system_prompt,
                status="active",
                message_count=0,
                total_tokens=0,
                total_cost=0,
                metadata_json=metadata or {},
                created_at=now,
                updated_at=now,
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            logger.info(
                "Created session %s for agent=%s model=%s",
                session_id, agent_id, session.model,
            )

            return self._session_to_dict(session)

    async def resume_session(self, session_id: str | uuid.UUID) -> dict[str, Any]:
        """
        Resume an existing session by ID.

        Raises SessionError if session not found or already ended.
        Returns session dict with message history.
        """
        from db.models import EngineChatSession, EngineChatMessage

        sid = uuid.UUID(str(session_id)) if not isinstance(session_id, uuid.UUID) else session_id

        async with self._db_factory() as db:
            result = await db.execute(
                select(EngineChatSession).where(EngineChatSession.id == sid)
            )
            session = result.scalar_one_or_none()

            if session is None:
                raise SessionError(f"Session {sid} not found")

            if session.status == "ended":
                raise SessionError(f"Session {sid} has already ended")

            # Load messages ordered by creation time
            msg_result = await db.execute(
                select(EngineChatMessage)
                .where(EngineChatMessage.session_id == sid)
                .order_by(EngineChatMessage.created_at.asc())
            )
            messages = msg_result.scalars().all()

            session_dict = self._session_to_dict(session)
            session_dict["messages"] = [self._message_to_dict(m) for m in messages]
            return session_dict

    async def end_session(self, session_id: str | uuid.UUID) -> dict[str, Any]:
        """
        End (close) a session. Marks status='ended' and sets ended_at.

        Returns the final session dict.
        """
        from db.models import EngineChatSession

        sid = uuid.UUID(str(session_id)) if not isinstance(session_id, uuid.UUID) else session_id
        now = datetime.now(timezone.utc)

        async with self._db_factory() as db:
            result = await db.execute(
                select(EngineChatSession).where(EngineChatSession.id == sid)
            )
            session = result.scalar_one_or_none()

            if session is None:
                raise SessionError(f"Session {sid} not found")

            session.status = "ended"
            session.ended_at = now
            session.updated_at = now
            await db.commit()
            await db.refresh(session)

            logger.info("Ended session %s", sid)
            return self._session_to_dict(session)

    async def send_message(
        self,
        session_id: str | uuid.UUID,
        content: str,
        *,
        enable_thinking: bool = False,
        enable_tools: bool = True,
        context_messages: list[dict[str, str]] | None = None,
    ) -> ChatResponse:
        """
        Send a user message and get an assistant response.

        Flow:
        1. Persist user message to DB
        2. Build message list (system prompt + context window)
        3. Call LLMGateway.complete() with tools
        4. If tool_calls returned — execute each, append results, re-call LLM
        5. Persist assistant message (and tool messages) to DB
        6. Update session counters (message_count, total_tokens, total_cost)
        7. Auto-generate title from first user message if none set
        8. Return ChatResponse

        Args:
            session_id: Target session.
            content: User message text.
            enable_thinking: Request reasoning tokens from the model.
            enable_tools: Whether to provide tool definitions to the LLM.
            context_messages: Pre-built context (from ContextManager). If None,
                              loads last N messages from DB.

        Returns:
            ChatResponse with assistant content, thinking, tool_calls, usage.
        """
        from db.models import EngineChatSession, EngineChatMessage

        sid = uuid.UUID(str(session_id)) if not isinstance(session_id, uuid.UUID) else session_id
        overall_start = time.monotonic()

        async with self._db_factory() as db:
            # ── 1. Load session ───────────────────────────────────────────
            result = await db.execute(
                select(EngineChatSession).where(EngineChatSession.id == sid)
            )
            session = result.scalar_one_or_none()
            if session is None:
                raise SessionError(f"Session {sid} not found")
            if session.status == "ended":
                raise SessionError(f"Session {sid} has ended — create a new session")

            # ── 2. Persist user message (with dedup) ─────────────────
            now = datetime.now(timezone.utc)
            dedup_cutoff = now - __import__('datetime').timedelta(
                seconds=self.DEDUP_WINDOW_SECONDS,
            )
            dup_check = await db.execute(
                select(EngineChatMessage.id)
                .where(
                    EngineChatMessage.session_id == sid,
                    EngineChatMessage.role == "user",
                    EngineChatMessage.content == content,
                    EngineChatMessage.created_at >= dedup_cutoff,
                )
                .limit(1)
            )
            if dup_check.scalar_one_or_none() is not None:
                logger.warning(
                    "Duplicate user message suppressed in session %s (within %ds)",
                    sid, self.DEDUP_WINDOW_SECONDS,
                )
                raise SessionError(
                    "Duplicate message — same content sent within "
                    f"{self.DEDUP_WINDOW_SECONDS}s"
                )

            user_msg_id = uuid.uuid4()
            user_msg = EngineChatMessage(
                id=user_msg_id,
                session_id=sid,
                role="user",
                content=content,
                created_at=now,
            )
            db.add(user_msg)
            await db.flush()

            # ── 2b. Slash command: /roundtable or /swarm ──────────────────
            slash_result = await self._handle_slash_command(
                db, session, sid, content, overall_start
            )
            if slash_result is not None:
                return slash_result

            # ── 3. Build conversation context ─────────────────────────────
            if context_messages is not None:
                messages = list(context_messages)
            else:
                messages = await self._build_context(db, session, content)

            # ── 4. LLM completion with tool-call loop ─────────────────────
            # Filter tools by agent's allowed skills (capability matching)
            allowed_skills = None
            if enable_tools and session.agent_id:
                from db.models import EngineAgentState
                agent_skills = await db.execute(
                    select(EngineAgentState.skills).where(
                        EngineAgentState.agent_id == session.agent_id
                    )
                )
                row = agent_skills.first()
                if row and row[0]:
                    try:
                        skills_list = (
                            json.loads(row[0])
                            if isinstance(row[0], str)
                            else row[0]
                        )
                        if isinstance(skills_list, list) and skills_list:
                            allowed_skills = skills_list
                    except (json.JSONDecodeError, TypeError, KeyError) as e:
                        logger.warning("Malformed skills filter: %s", e)

            tools_for_llm = (
                self.tools.get_tools_for_llm(filter_skills=allowed_skills)
                if enable_tools
                else None
            )
            accumulated_tool_calls: list[dict[str, Any]] = []
            accumulated_tool_results: list[dict[str, Any]] = []
            # Per-tool failure tracking (P0 — prevent infinite retry loops)
            tool_failure_counts: dict[str, int] = {}
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = 0.0
            final_content = ""
            final_thinking = None
            final_finish_reason = ""
            # Execution trace for UI graph reconstruction
            _exec_trace: dict[str, Any] = {
                "iterations": 0,
                "tools": [],
                "nodes": [],
                "edges": [],
            }

            for iteration in range(self.MAX_TOOL_ITERATIONS):
                try:
                    llm_response: LLMResponse = await self.gateway.complete(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=tools_for_llm,
                        enable_thinking=enable_thinking,
                    )
                except LLMError as e:
                    logger.error("LLM call failed in session %s: %s", sid, e)
                    asyncio.ensure_future(log_model_usage(
                        self._db_factory,
                        model=session.model or "unknown",
                        latency_ms=int((time.monotonic() - overall_start) * 1000),
                        success=False,
                        error_message=str(e)[:200],
                    ))
                    raise SessionError(f"LLM call failed: {e}") from e

                total_input_tokens += llm_response.input_tokens
                total_output_tokens += llm_response.output_tokens
                total_cost += llm_response.cost_usd
                final_content = llm_response.content
                final_thinking = llm_response.thinking or final_thinking
                final_finish_reason = llm_response.finish_reason

                # Telemetry → aria_data.model_usage
                iter_latency = int((time.monotonic() - overall_start) * 1000)
                asyncio.ensure_future(log_model_usage(
                    self._db_factory,
                    model=session.model or "unknown",
                    input_tokens=llm_response.input_tokens,
                    output_tokens=llm_response.output_tokens,
                    cost_usd=llm_response.cost_usd,
                    latency_ms=iter_latency,
                    success=True,
                ))

                # No tool calls — done
                if not llm_response.tool_calls:
                    break

                # ── 4a. Execute tool calls ────────────────────────────────
                _exec_trace["iterations"] = iteration + 1
                # Add LLM node to trace
                _llm_nid = f"llm_{iteration + 1}"
                _exec_trace["nodes"].append({
                    "id": _llm_nid, "label": f"LLM #{iteration + 1}",
                    "shape": "box", "level": iteration + 1,
                    "color": {"background": "#1e2d3a", "border": "#4a9eed"},
                    "font": {"color": "#4a9eed", "size": 12},
                })
                if iteration > 0:
                    # Connect previous iteration's tool nodes → this LLM node
                    prev_tools = [n["id"] for n in _exec_trace["nodes"] if n["id"].startswith("tool_") and n.get("_iter") == iteration]
                    for pt in prev_tools:
                        _exec_trace["edges"].append({"from": pt, "to": _llm_nid, "label": "result", "arrows": "to", "font": {"size": 10, "color": "#888"}})
                accumulated_tool_calls.extend(llm_response.tool_calls)

                # Append assistant message with tool_calls to conversation
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
                    session_id=sid,
                    role="assistant",
                    content=llm_response.content or "",
                    thinking=llm_response.thinking or None,
                    tool_calls=llm_response.tool_calls,
                    model=session.model,
                    tokens_input=llm_response.input_tokens,
                    tokens_output=llm_response.output_tokens,
                    cost=llm_response.cost_usd,
                    latency_ms=int((time.monotonic() - overall_start) * 1000),
                    created_at=datetime.now(timezone.utc),
                )
                db.add(intermediate_msg)
                await db.flush()

                for tc in llm_response.tool_calls:
                    fn_name = tc["function"]["name"]

                    # ── Per-tool failure cap ──────────────────────────────
                    if tool_failure_counts.get(fn_name, 0) >= self.MAX_PER_TOOL_FAILURES:
                        logger.warning(
                            "Tool %s failed %d times in session %s — blocking further calls",
                            fn_name, tool_failure_counts[fn_name], sid,
                        )
                        tool_result = ToolResult(
                            tool_call_id=tc["id"],
                            name=fn_name,
                            content=json.dumps({
                                "error": f"Tool '{fn_name}' has failed "
                                f"{tool_failure_counts[fn_name]} consecutive times "
                                "this turn. Do NOT call it again — use an "
                                "alternative approach or inform the user."
                            }),
                            success=False,
                        )
                    # Capability enforcement: reject tools outside agent's skills
                    elif allowed_skills:
                        skill_part = fn_name.split("__")[0] if "__" in fn_name else ""
                        if skill_part and skill_part not in allowed_skills:
                            logger.warning(
                                "Agent %s blocked from tool %s (skill %s not in %s)",
                                session.agent_id, fn_name, skill_part, allowed_skills,
                            )
                            tool_result = ToolResult(
                                tool_call_id=tc["id"],
                                name=fn_name,
                                content=json.dumps({
                                    "error": f"Capability denied: agent '{session.agent_id}' "
                                    f"does not have access to skill '{skill_part}'"
                                }),
                                success=False,
                            )
                        else:
                            tool_result = await self.tools.execute(
                                tool_call_id=tc["id"],
                                function_name=fn_name,
                                arguments=tc["function"]["arguments"],
                            )
                    else:
                        tool_result = await self.tools.execute(
                            tool_call_id=tc["id"],
                            function_name=fn_name,
                            arguments=tc["function"]["arguments"],
                        )
                    accumulated_tool_results.append({
                        "tool_call_id": tool_result.tool_call_id,
                        "name": tool_result.name,
                        "content": tool_result.content,
                        "success": tool_result.success,
                        "duration_ms": tool_result.duration_ms,
                    })

                    # Track tool in exec trace
                    _tn_id = f"tool_{tc['id']}"
                    _tcolor = {"background": "#1e3a2f", "border": "#2ea86f"} if tool_result.success else {"background": "#3a1e1e", "border": "#d44a4a"}
                    _exec_trace["tools"].append({
                        "name": fn_name, "id": tc["id"],
                        "success": tool_result.success,
                        "duration_ms": tool_result.duration_ms,
                    })
                    _exec_trace["nodes"].append({
                        "id": _tn_id, "label": fn_name.replace("_", "\n"),
                        "shape": "diamond", "level": iteration + 1.5,
                        "color": _tcolor,
                        "font": {"color": _tcolor["border"], "size": 11},
                        "_iter": iteration + 1,
                    })
                    _exec_trace["edges"].append({"from": f"llm_{iteration + 1}", "to": _tn_id, "label": "call", "arrows": "to", "font": {"size": 10, "color": "#888"}})

                    # Track per-tool failures for circuit-break
                    if tool_result.success:
                        tool_failure_counts.pop(fn_name, None)
                    else:
                        tool_failure_counts[fn_name] = tool_failure_counts.get(fn_name, 0) + 1

                    # Telemetry → aria_data.skill_invocations
                    asyncio.ensure_future(log_skill_invocation(
                        self._db_factory,
                        skill_name=_parse_skill_from_tool(fn_name),
                        tool_name=fn_name,
                        duration_ms=tool_result.duration_ms,
                        success=tool_result.success,
                        model_used=session.model,
                    ))

                    # Append tool result to conversation for next LLM turn
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_result.tool_call_id,
                        "content": tool_result.content,
                    })

                    # Persist tool result as a message
                    tool_msg = EngineChatMessage(
                        id=uuid.uuid4(),
                        session_id=sid,
                        role="tool",
                        content=tool_result.content,
                        tool_results={"tool_call_id": tc["id"], "name": tc["function"]["name"]},
                        latency_ms=tool_result.duration_ms,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(tool_msg)

            # ── 4b. If loop exhausted (hit MAX_TOOL_ITERATIONS) or final
            #        content is empty, force one plain summary call ─────────
            if not final_content or (final_content.rstrip().endswith(":") and accumulated_tool_calls):
                logger.warning(
                    "Session %s: forcing summary call (content=%r, iterations=%d)",
                    sid, final_content[:60] if final_content else "", iteration + 1,
                )
                try:
                    summary_response: LLMResponse = await self.gateway.complete(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=None,  # No tools — force a plain text answer
                        enable_thinking=False,
                    )
                    total_input_tokens += summary_response.input_tokens
                    total_output_tokens += summary_response.output_tokens
                    total_cost += summary_response.cost_usd
                    if summary_response.content:
                        final_content = summary_response.content
                        final_finish_reason = summary_response.finish_reason
                except Exception as e:
                    logger.error("Summary call failed in session %s: %s", sid, e)
                    if not final_content:
                        final_content = "I completed the requested actions. Let me know if you need anything else."

            # ── 5. Persist assistant message ──────────────────────────────
            elapsed_ms = int((time.monotonic() - overall_start) * 1000)

            # Finalize exec trace
            _trace_meta: dict[str, Any] = {}
            if _exec_trace["tools"]:
                _resp_label = f"Response\n{(elapsed_ms / 1000):.1f}s" if elapsed_ms else "Response"
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
                    _from = f"llm_{_exec_trace['iterations']}" if _exec_trace["iterations"] else "llm_1"
                    _exec_trace["edges"].append({"from": _from, "to": "response", "arrows": "to"})
                _exec_trace["latency_ms"] = elapsed_ms
                _exec_trace["total_tools"] = len(_exec_trace["tools"])
                # Strip internal _iter tag from nodes before serializing
                for n in _exec_trace["nodes"]:
                    n.pop("_iter", None)
                _trace_meta = {"exec_trace": _exec_trace}

            assistant_msg_id = uuid.uuid4()
            assistant_msg = EngineChatMessage(
                id=assistant_msg_id,
                session_id=sid,
                role="assistant",
                content=final_content,
                thinking=final_thinking,
                tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
                tool_results=accumulated_tool_results if accumulated_tool_results else None,
                model=session.model,
                tokens_input=total_input_tokens,
                tokens_output=total_output_tokens,
                cost=total_cost,
                latency_ms=elapsed_ms,
                metadata_json=_trace_meta if _trace_meta else {},
                created_at=datetime.now(timezone.utc),
            )
            db.add(assistant_msg)

            # ── 6. Update session counters ────────────────────────────────
            new_msg_count = 2  # user + assistant
            if accumulated_tool_results:
                new_msg_count += len(accumulated_tool_results)

            session.message_count = (session.message_count or 0) + new_msg_count
            session.total_tokens = (session.total_tokens or 0) + total_input_tokens + total_output_tokens
            session.total_cost = float(session.total_cost or 0) + total_cost
            session.updated_at = datetime.now(timezone.utc)

            # ── 7. Auto-generate title from first message ─────────────────
            if not session.title and session.message_count <= 2:
                session.title = self._generate_title(content)

            await db.commit()

            logger.info(
                "Message in session %s: in=%d out=%d cost=%.6f latency=%dms tools=%d",
                sid, total_input_tokens, total_output_tokens,
                total_cost, elapsed_ms, len(accumulated_tool_calls),
            )

            return ChatResponse(
                message_id=str(assistant_msg_id),
                session_id=str(sid),
                content=final_content,
                thinking=final_thinking,
                tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
                tool_results=accumulated_tool_results if accumulated_tool_results else None,
                model=session.model or "",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_input_tokens + total_output_tokens,
                cost_usd=total_cost,
                latency_ms=elapsed_ms,
                finish_reason=final_finish_reason,
            )

    # ── Private helpers ───────────────────────────────────────────────────

    async def _build_context(
        self,
        db: AsyncSession,
        session,
        current_content: str,
    ) -> list[dict[str, str]]:
        """
        Build conversation context from DB messages.

        Always includes:
        - System prompt (if set on session)
        - Last N messages up to context_window limit
        - Current user message
        """
        from db.models import EngineChatMessage

        messages: list[dict[str, str]] = []

        # System prompt
        if session.system_prompt:
            messages.append({"role": "system", "content": session.system_prompt})

        # Load recent messages from DB.
        # Fetch MORE than context_window so we can guarantee a minimum number
        # of user/assistant turns survive even when tool messages dominate.
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

    # ── Slash commands & auto-escalation ──────────────────────────────

    async def _handle_slash_command(
        self,
        db,
        session,
        sid: uuid.UUID,
        content: str,
        overall_start: float,
    ) -> ChatResponse | None:
        """
        Detect and handle /roundtable or /swarm slash commands.

        Returns a ChatResponse if a command was handled, None otherwise.

        Usage in chat:
            /roundtable <topic> — start a roundtable with available agents
            /swarm <topic>      — start a swarm decision with available agents
        """
        stripped = content.strip()
        lower = stripped.lower()

        orchestrator = None
        mode = None

        if lower.startswith("/roundtable"):
            if self._roundtable is None:
                return None  # Fall through to normal LLM flow
            orchestrator = self._roundtable
            mode = "roundtable"
            topic = stripped[len("/roundtable"):].strip()
        elif lower.startswith("/swarm"):
            if self._swarm is None:
                return None
            orchestrator = self._swarm
            mode = "swarm"
            topic = stripped[len("/swarm"):].strip()
        else:
            return None  # Not a slash command

        if not topic:
            return self._make_slash_response(
                sid, overall_start,
                f"Usage: /{mode} <topic>\n\n"
                f"Example: /{mode} Should we migrate to microservices?",
            )

        # Auto-select agents: get top 3-4 available agents by pheromone score
        agent_ids = await self._get_auto_agents(db, session.agent_id)
        if len(agent_ids) < 2:
            return self._make_slash_response(
                sid, overall_start,
                f"⚠️ Need at least 2 active agents for /{mode}. "
                f"Only found: {agent_ids or 'none'}",
            )

        try:
            if mode == "roundtable":
                result = await orchestrator.discuss(
                    topic=topic,
                    agent_ids=agent_ids,
                    rounds=3,
                    synthesizer_id=session.agent_id or "main",
                )
                content_out = (
                    f"## 🔄 Roundtable: {topic}\n\n"
                    f"**Participants:** {', '.join(result.participants)}\n"
                    f"**Rounds:** {result.rounds} | "
                    f"**Turns:** {result.turn_count} | "
                    f"**Duration:** {result.total_duration_ms}ms\n\n"
                    f"### Synthesis\n{result.synthesis}\n\n"
                    f"---\n*Session: {result.session_id}*"
                )
            else:  # swarm
                result = await orchestrator.execute(
                    topic=topic,
                    agent_ids=agent_ids,
                )
                content_out = (
                    f"## 🐝 Swarm Decision: {topic}\n\n"
                    f"**Participants:** {', '.join(result.participants)}\n"
                    f"**Iterations:** {result.iterations} | "
                    f"**Votes:** {result.vote_count} | "
                    f"**Consensus:** {result.consensus_score:.0%}\n"
                    f"**Converged:** {'✅ Yes' if result.converged else '❌ No'}\n\n"
                    f"### Consensus\n{result.consensus}\n\n"
                    f"---\n*Session: {result.session_id}*"
                )

            return self._make_slash_response(sid, overall_start, content_out)

        except Exception as e:
            logger.error("/%s command failed: %s", mode, e)
            return self._make_slash_response(
                sid, overall_start,
                f"⚠️ /{mode} failed: {e}",
            )

    async def _get_auto_agents(
        self, db, current_agent_id: str
    ) -> list[str]:
        """
        Auto-select agents for a roundtable/swarm based on pheromone score.

        Returns top 4 enabled agents (including current agent).
        """
        from db.models import EngineAgentState

        result = await db.execute(
            select(EngineAgentState.agent_id)
            .where(
                EngineAgentState.enabled == True,
                EngineAgentState.status != "disabled",
                EngineAgentState.status != "terminated",
            )
            .order_by(EngineAgentState.pheromone_score.desc())
            .limit(6)
        )
        candidates = [r[0] for r in result]

        # Ensure current agent is included
        if current_agent_id and current_agent_id not in candidates:
            candidates.insert(0, current_agent_id)

        # Return top 4
        return candidates[:4]

    def _make_slash_response(
        self,
        sid: uuid.UUID,
        overall_start: float,
        content: str,
    ) -> ChatResponse:
        """Build a ChatResponse for slash command output."""
        elapsed_ms = int((time.monotonic() - overall_start) * 1000)
        return ChatResponse(
            message_id=str(uuid.uuid4()),
            session_id=str(sid),
            content=content,
            model="orchestration",
            latency_ms=elapsed_ms,
            finish_reason="slash_command",
        )

    @staticmethod
    def _generate_title(first_message: str) -> str:
        """
        Generate a short session title from the first user message.
        Truncates to 80 chars and adds ellipsis if needed.
        """
        # Strip whitespace and newlines
        title = first_message.strip().replace("\n", " ").replace("\r", "")
        # Remove excessive whitespace
        title = " ".join(title.split())
        if len(title) > 80:
            title = title[:77] + "..."
        return title

    @staticmethod
    def _session_to_dict(session) -> dict[str, Any]:
        """Convert ORM session to plain dict."""
        return {
            "id": str(session.id),
            "agent_id": session.agent_id,
            "session_type": session.session_type,
            "title": session.title,
            "model": session.model,
            "system_prompt": session.system_prompt,
            "temperature": session.temperature,
            "max_tokens": session.max_tokens,
            "context_window": session.context_window,
            "status": session.status,
            "message_count": session.message_count,
            "total_tokens": session.total_tokens,
            "total_cost": float(session.total_cost or 0),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "metadata": session.metadata_json if hasattr(session, "metadata_json") else {},
        }

    @staticmethod
    def _message_to_dict(msg) -> dict[str, Any]:
        """Convert ORM message to plain dict."""
        return {
            "id": str(msg.id),
            "session_id": str(msg.session_id),
            "role": msg.role,
            "content": msg.content,
            "thinking": msg.thinking,
            "tool_calls": msg.tool_calls,
            "tool_results": msg.tool_results,
            "model": msg.model,
            "tokens_input": msg.tokens_input,
            "tokens_output": msg.tokens_output,
            "cost": float(msg.cost) if msg.cost else None,
            "latency_ms": msg.latency_ms,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
