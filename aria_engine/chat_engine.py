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
from aria_engine.session_protection import SessionProtection
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
    context_compacted: bool = False
    context_notice: str | None = None
    context_tokens_before: int | None = None
    context_tokens_after: int | None = None

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
            "context_compacted": self.context_compacted,
            "context_notice": self.context_notice,
            "context_tokens_before": self.context_tokens_before,
            "context_tokens_after": self.context_tokens_after,
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
        session_protection: SessionProtection | None = None,
    ):
        self.config = config
        self.gateway = gateway
        self.tools = tool_registry
        self._db_factory = db_session_factory
        self._protector = session_protection  # injection + rate-limit guard
        # Optional multi-agent orchestration (set by main.py after init)
        self._roundtable: Any | None = None
        self._swarm: Any | None = None
        self._escalation_router: Any | None = None
        from aria_engine.context_manager import ContextManager
        self._ctx_manager = ContextManager(config)

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
                metadata_json={"origin": "api", **(metadata or {})},
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

            # ── 1b. Session protection: injection check + rate limiting ───────────
            if self._protector is not None and content:
                await self._protector.validate_and_check(
                    session_id=str(sid),
                    agent_id=session.agent_id or "unknown",
                    role="user",
                    content=content,
                )

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
                allowed_skills = await self.tools.get_allowed_skills(db, session.agent_id)

            tools_for_llm = (
                self.tools.get_tools_for_llm(filter_skills=allowed_skills)
                if enable_tools
                else None
            )
            accumulated_tool_calls: list[dict[str, Any]] = []
            accumulated_tool_results: list[dict[str, Any]] = []
            # Per-tool failure tracking (P0 — prevent infinite retry loops)
            tool_failure_counts: dict[str, int] = {}
            delegation_failures = 0
            delegation_blocked_reason: str | None = None
            delegation_guidance_added = False
            intermediate_assistant_count = 0
            total_input_tokens = 0
            total_output_tokens = 0
            total_cost = 0.0
            final_content = ""
            final_thinking = None
            final_finish_reason = ""
            context_compaction_meta: dict[str, Any] | None = None
            # Execution trace for UI graph reconstruction
            _exec_trace: dict[str, Any] = {
                "iterations": 0,
                "tools": [],
                "nodes": [],
                "edges": [],
            }

            for iteration in range(self.MAX_TOOL_ITERATIONS):
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
                                "available in this session and provide a concrete final answer now."
                            ),
                        })
                        delegation_guidance_added = True

                # ── ST-15: Pre-flight token guard ─────────────────────────────
                _iter_tokens = self.gateway.estimate_tokens_for_messages(
                    model=session.model or self.config.default_model,
                    messages=messages,
                )
                _soft_lim, _hard_lim = self._get_model_token_limits(
                    session.model or self.config.default_model
                )
                if _iter_tokens > _hard_lim:
                    _tokens_before = _iter_tokens
                    # Try one emergency shrink pass before aborting the turn.
                    messages, _iter_tokens = await self._shrink_context_to_fit_hard_limit(
                        db=db,
                        session=session,
                        messages=messages,
                        hard_limit=_hard_lim,
                        token_count=_iter_tokens,
                    )
                    if _iter_tokens > _hard_lim:
                        logger.error(
                            "Pre-flight hard limit: session=%s tokens=%d > hard_limit=%d — aborting turn",
                            sid, _iter_tokens, _hard_lim,
                        )
                        final_content = (
                            "This conversation has grown too long for me to continue reliably "
                            f"({_iter_tokens:,} tokens). Please start a new session "
                            "or ask me to summarize and compress this conversation first."
                        )
                        break
                    model_name = session.model or self.config.default_model
                    context_compaction_meta = {
                        "mode": "hard_limit_shrink",
                        "tokens_before": _tokens_before,
                        "tokens_after": _iter_tokens,
                        "hard_limit": _hard_lim,
                        "model": model_name,
                        "notice": (
                            "Auto-compacted context to fit model limit "
                            f"({_tokens_before:,} -> {_iter_tokens:,} tokens)."
                        ),
                    }
                    logger.warning(
                        "Hard limit avoided via emergency context shrink: session=%s tokens=%d <= %d",
                        sid,
                        _iter_tokens,
                        _hard_lim,
                    )
                if _iter_tokens > _soft_lim and iteration == 0:
                    _pct = int(_iter_tokens / _hard_lim * 100)
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[CONTEXT MONITOR] This conversation is at {_pct}% of your "
                            f"memory capacity ({_iter_tokens:,} / {_hard_lim:,} tokens). "
                            "You MUST: (1) keep your response concise, (2) avoid unnecessary "
                            "tool calls that produce large outputs, (3) consider informing the "
                            "user that starting a new session would give you a fresh memory."
                        ),
                    })
                    logger.warning(
                        "Soft token limit reached: session=%s tokens=%d (%d%% of %d)",
                        sid, _iter_tokens, _pct, _hard_lim,
                    )

                try:
                    llm_response: LLMResponse = await self.gateway.complete(
                        messages=messages,
                        model=session.model,
                        temperature=session.temperature,
                        max_tokens=session.max_tokens,
                        tools=active_tools,
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
                if llm_response.thinking or final_thinking:
                    assistant_entry["reasoning_content"] = llm_response.thinking or final_thinking
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
                intermediate_assistant_count += 1

                for tc in llm_response.tool_calls:
                    fn_name = tc["function"]["name"]

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

                    # ── Per-tool failure cap ──────────────────────────────
                    elif tool_failure_counts.get(fn_name, 0) >= self.MAX_PER_TOOL_FAILURES:
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
                                    "Session %s delegation blocked after %d failure(s): %s",
                                    sid,
                                    delegation_failures,
                                    delegation_blocked_reason,
                                )

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
            if (
                delegation_blocked_reason is not None
                or not final_content
                or (final_content.rstrip().endswith(":") and accumulated_tool_calls)
                or self._looks_like_promised_action_without_execution(final_content)
            ):
                logger.warning(
                    "Session %s: forcing summary call (content=%r, iterations=%d, delegation_blocked=%s)",
                    sid, final_content[:60] if final_content else "", iteration + 1, bool(delegation_blocked_reason),
                )
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
                if not (final_content or "").strip():
                    if delegation_blocked_reason:
                        final_content = (
                            "I could not delegate this task because the sub-agent channel is unavailable "
                            f"({delegation_blocked_reason}). I continued with direct tools in this session. "
                            "Please retry delegation in a new turn after the agent channel recovers."
                        )
                    else:
                        final_content = (
                            "I completed the requested actions, but the final summary content was empty. "
                            "Please continue and I will provide a concise recap in the next turn."
                        )

            final_content = self._apply_tool_result_consistency_guards(
                final_content,
                accumulated_tool_results,
            )

            # ── 5. Persist assistant message ──────────────────────────────
            elapsed_ms = int((time.monotonic() - overall_start) * 1000)

            # Finalize exec trace
            _trace_meta: dict[str, Any] = {}
            if context_compaction_meta:
                _trace_meta["context_compaction"] = context_compaction_meta
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
            should_auto_title = not session.title and (session.message_count or 0) == 0
            new_msg_count = 2 + intermediate_assistant_count  # user + intermediate assistants + final assistant
            if accumulated_tool_results:
                new_msg_count += len(accumulated_tool_results)

            session.message_count = (session.message_count or 0) + new_msg_count
            session.total_tokens = (session.total_tokens or 0) + total_input_tokens + total_output_tokens
            session.total_cost = float(session.total_cost or 0) + total_cost
            session.updated_at = datetime.now(timezone.utc)

            # ── 7. Auto-generate title from first message ─────────────────
            if should_auto_title:
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
                context_compacted=bool(context_compaction_meta),
                context_notice=(
                    context_compaction_meta.get("notice")
                    if context_compaction_meta
                    else None
                ),
                context_tokens_before=(
                    int(context_compaction_meta.get("tokens_before"))
                    if context_compaction_meta
                    and context_compaction_meta.get("tokens_before") is not None
                    else None
                ),
                context_tokens_after=(
                    int(context_compaction_meta.get("tokens_after"))
                    if context_compaction_meta
                    and context_compaction_meta.get("tokens_after") is not None
                    else None
                ),
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

        # ── ST-14: Token budget enforcement ──────────────────────────────────
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

        # ── ST-17: Auto-compress if approaching soft token limit (70%) ────────
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
    def _extract_schedule_job_total(tool_results: list[dict[str, Any]]) -> int | None:
        """Best-effort extraction of schedule total jobs from tool result payloads."""
        total: int | None = None
        for item in tool_results:
            name = str(item.get("name", ""))
            if "schedule__list_jobs" not in name and "schedule" not in name:
                continue

            raw = item.get("content")
            payload: Any = raw
            if isinstance(raw, str):
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue

            if isinstance(payload, dict):
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                candidate = data.get("total") if isinstance(data, dict) else None
                if isinstance(candidate, int):
                    total = candidate
                elif isinstance(candidate, str) and candidate.isdigit():
                    total = int(candidate)
        return total

    def _apply_tool_result_consistency_guards(
        self,
        content: str,
        tool_results: list[dict[str, Any]],
    ) -> str:
        """Apply lightweight factual guards so summaries don't contradict tool outputs."""
        if not content or not tool_results:
            return content

        schedule_total = self._extract_schedule_job_total(tool_results)
        if schedule_total is None:
            return content

        lowered = content.lower()
        contradiction_markers = (
            "0 scheduled jobs",
            "zero scheduled jobs",
            "registry: empty",
            "empty job registry",
            "0 jobs total",
        )
        if schedule_total > 0 and any(marker in lowered for marker in contradiction_markers):
            return (
                f"{content}\n\n"
                f"⚠️ Correction: tool results report {schedule_total} scheduled job(s), "
                "so the scheduler registry is not empty."
            )

        return content

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

    def _get_model_token_limits(self, model: str) -> tuple[int, int]:
        """Return (soft_limit, hard_limit) for the model.

        soft_limit = 80% of safe_prompt_tokens → inject self-awareness notice
        hard_limit = safe_prompt_tokens → refuse the provider call
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
        """Compress middle history when session approaches 70% of token limit."""
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

    async def _shrink_context_to_fit_hard_limit(
        self,
        db,
        session,
        messages: list[dict[str, Any]],
        hard_limit: int,
        token_count: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Emergency context reduction for oversized iterative tool loops.

        Order of operations:
        1. Try semantic compression of middle history.
        2. Re-apply ContextManager at hard limit.
        3. As a last resort, drop oldest non-system messages until it fits.
        """
        model_name = session.model or self.config.default_model
        current = list(messages)
        current_tokens = token_count

        if current_tokens <= hard_limit:
            return current, current_tokens

        try:
            compressed = await self._maybe_compress_context(
                db=db,
                session=session,
                messages=current,
                token_count=current_tokens,
                soft_threshold=int(hard_limit * 0.70),
            )
            current = compressed
            current_tokens = self.gateway.estimate_tokens_for_messages(
                model=model_name,
                messages=current,
            )
            if current_tokens <= hard_limit:
                return current, current_tokens
        except Exception as exc:
            logger.warning("Emergency compression pass failed (non-fatal): %s", exc)

        reserve = min(
            int(session.max_tokens or self.config.default_max_tokens),
            max(512, hard_limit // 8),
        )
        try:
            current = self._ctx_manager.build_context(
                all_messages=current,
                max_tokens=hard_limit,
                model=model_name,
                reserve_tokens=reserve,
            )
            current_tokens = self.gateway.estimate_tokens_for_messages(
                model=model_name,
                messages=current,
            )
            if current_tokens <= hard_limit:
                return current, current_tokens
        except Exception as exc:
            logger.warning("Emergency context manager pass failed (non-fatal): %s", exc)

        # Final safety net: drop oldest non-system messages progressively.
        while current_tokens > hard_limit and len(current) > 3:
            drop_idx = next(
                (
                    i
                    for i, msg in enumerate(current)
                    if msg.get("role") != "system"
                ),
                None,
            )
            if drop_idx is None or drop_idx >= len(current) - 1:
                break
            current.pop(drop_idx)
            current_tokens = self.gateway.estimate_tokens_for_messages(
                model=model_name,
                messages=current,
            )

        return current, current_tokens

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

    @classmethod
    def _looks_like_promised_action_without_execution(cls, text: str) -> bool:
        if not text:
            return False
        lowered = " ".join(text.strip().lower().split())
        if not lowered:
            return False
        markers = (
            "let me",
            "i will",
            "i'll",
            "checking",
            "trying",
            "searching",
            "getting",
        )
        return any(m in lowered for m in markers) and lowered.endswith((":", "..."))

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
