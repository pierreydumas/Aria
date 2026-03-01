# aria_skills/agent_manager/__init__.py
"""
Agent Manager Skill — runtime agent lifecycle management.

Provides Aria with programmatic control over agent sessions:
spawn, monitor, terminate, prune stale sessions, generate reports.
All data access through aria-api (httpx HTTP client).
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.latency import log_latency
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class AgentManagerSkill(BaseSkill):
    """
    Runtime agent lifecycle management via aria-api.

    Methods:
        list_agents() — list active agent sessions
        spawn_agent(agent_type, context) — create session with context protocol
        terminate_agent(session_id) — graceful shutdown
        get_agent_stats(session_id) — usage metrics for one session
        prune_stale_sessions(max_age_hours) — bulk cleanup
        get_performance_report() — aggregate metrics
    """

    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._api = None
        self._subagent_circuit_until: datetime | None = None

    _SUBAGENT_CIRCUIT_SECONDS = 120

    @property
    def name(self) -> str:
        return "agent_manager"

    async def initialize(self) -> bool:
        """Initialize via centralized API client."""
        try:
            self._api = await get_api_client()
        except Exception as e:
            self.logger.error(f"API client init failed: {e}")
            self._status = SkillStatus.UNAVAILABLE
            return False
        hc = await self._api.health_check()
        if hc != SkillStatus.AVAILABLE:
            self.logger.error("API client not available")
            self._status = SkillStatus.UNAVAILABLE
            return False
        self._status = SkillStatus.AVAILABLE
        return True

    async def health_check(self) -> SkillStatus:
        """Check aria-api health."""
        if not self._api:
            return SkillStatus.UNAVAILABLE
        try:
            result = await self._api.get("/health")
            if result.success:
                self._status = SkillStatus.AVAILABLE
            else:
                self._status = SkillStatus.ERROR
        except Exception:
            self._status = SkillStatus.ERROR
        return self._status

    # ── Helpers ───────────────────────────────────────────────────

    async def _validate_model(self, model: str) -> bool:
        """Check that *model* exists and is enabled in models.yaml via API."""
        try:
            result = await self._api.get("/models")
            if not result or not result.data:
                return False
            models = result.data if isinstance(result.data, list) else result.data.get("models", [])
            for m in models:
                mid = m.get("id") or m.get("model_id") or ""
                if mid == model and m.get("enabled", True):
                    return True
            return False
        except Exception:
            # If we can't validate, allow it through (fail-open)
            self.logger.warning(f"Could not validate model '{model}', allowing")
            return True

    def _trip_subagent_circuit(self, reason: str) -> None:
        self._subagent_circuit_until = datetime.now(timezone.utc) + timedelta(
            seconds=self._SUBAGENT_CIRCUIT_SECONDS
        )
        self.logger.warning(
            "sub-agent circuit opened for %ss: %s",
            self._SUBAGENT_CIRCUIT_SECONDS,
            reason,
        )

    def _subagent_circuit_remaining_seconds(self) -> int:
        if not self._subagent_circuit_until:
            return 0
        remaining = int((self._subagent_circuit_until - datetime.now(timezone.utc)).total_seconds())
        return max(0, remaining)

    # ── Core methods ─────────────────────────────────────────────

    @log_latency
    async def list_agents(
        self,
        status: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> SkillResult:
        """List agent sessions, optionally filtered by status or agent_id."""
        if not self._api:
            return SkillResult.fail("Not initialized")

        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if agent_id:
            params["agent_id"] = agent_id

        try:
            result = await self._api.get("/sessions", params=params)
            if not result:
                raise Exception(result.error)
            data = result.data
            self._log_usage("list_agents", True, count=data.get("count", 0))
            return SkillResult.ok(data)
        except Exception as e:
            self._log_usage("list_agents", False, error=str(e))
            return SkillResult.fail(f"Failed to list agents: {e}")

    async def spawn_agent(
        self,
        agent_type: str,
        context: dict | None = None,
        model: str | None = None,
    ) -> SkillResult:
        """Spawn an agent session with optional context protocol.

        Args:
            agent_type: Agent ID (e.g. "analyst", "creator", "devops")
            context: Optional dict with context protocol fields:
                task, constraints, budget_tokens, deadline_seconds,
                parent_id, priority, tools_allowed, memory_scope
            model: Optional LLM model ID from models.yaml to use for this agent.
                If None, the system default model is used.
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        # Validate context if provided
        if context and not context.get("task"):
            return SkillResult.fail("Context must include a non-empty 'task' field")

        # Validate model if specified
        if model:
            valid = await self._validate_model(model)
            if not valid:
                return SkillResult.fail(f"Unknown or disabled model: {model}")

        body: dict[str, Any] = {
            "agent_id": agent_type,
            "session_type": "managed",
            "title": f"Agent: {agent_type}",
            "metadata": context or {},
        }
        if model:
            body["model"] = model

        try:
            result = await self._api.post("/engine/chat/sessions", data=body)
            if not result:
                raise Exception(result.error)
            data = result.data
            self._log_usage("spawn_agent", True, agent_type=agent_type)
            return SkillResult.ok(data)
        except Exception as e:
            self._log_usage("spawn_agent", False, error=str(e))
            return SkillResult.fail(f"Failed to spawn agent: {e}")

    async def terminate_agent(self, session_id: str) -> SkillResult:
        """Terminate an agent session gracefully.

        Works for both engine sessions (from spawn_focused_agent) and
        legacy data-layer sessions.  Tries the engine endpoint first,
        falls back to data-layer PATCH.

        Args:
            session_id: UUID of the session to terminate
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        try:
            # Try engine endpoint first (covers spawn_focused_agent sessions)
            result = await self._api.delete(
                f"/engine/chat/sessions/{session_id}",
            )
            if result and result.success:
                self._log_usage("terminate_agent", True, session_id=session_id)
                return SkillResult.ok({"session_id": session_id, "status": "ended"})

            # Fallback: legacy data-layer PATCH
            result = await self._api.patch(
                f"/sessions/{session_id}",
                data={"status": "terminated"},
            )
            if not result:
                raise Exception(result.error)
            self._log_usage("terminate_agent", True, session_id=session_id)
            return SkillResult.ok({"session_id": session_id, "status": "terminated"})
        except Exception as e:
            self._log_usage("terminate_agent", False, error=str(e))
            return SkillResult.fail(f"Failed to terminate agent: {e}")

    async def get_agent_stats(self, session_id: str | None = None) -> SkillResult:
        """Get session statistics, optionally for a specific session.

        Args:
            session_id: Optional specific session UUID. If None, returns aggregate stats.
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        try:
            if session_id:
                # Get specific session by listing with agent filter
                # The API doesn't have a GET /sessions/{id} endpoint,
                # so we use the stats endpoint for aggregate and filter list for specific
                result = await self._api.get("/sessions", params={"limit": 100})
                if not result:
                    raise Exception(result.error)
                sessions = result.data.get("sessions", [])
                match = [s for s in sessions if s.get("id") == session_id]
                if not match:
                    return SkillResult.fail(f"Session {session_id} not found")
                data = match[0]
            else:
                result = await self._api.get("/sessions/stats")
                if not result:
                    raise Exception(result.error)
                data = result.data

            self._log_usage("get_agent_stats", True)
            return SkillResult.ok(data)
        except Exception as e:
            self._log_usage("get_agent_stats", False, error=str(e))
            return SkillResult.fail(f"Failed to get agent stats: {e}")

    async def prune_stale_sessions(self, max_age_hours: int = 6) -> SkillResult:
        """Terminate sessions older than max_age_hours that are still active.

        Args:
            max_age_hours: Maximum age in hours before session is considered stale.
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        try:
            # Fetch active sessions
            result = await self._api.get(
                "/sessions",
                params={"status": "active", "limit": 200},
            )
            if not result:
                raise Exception(result.error)
            sessions = result.data.get("sessions", [])

            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            pruned = []

            for s in sessions:
                started = s.get("started_at")
                if not started:
                    continue
                # Parse ISO timestamp
                try:
                    started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue

                if started_dt < cutoff:
                    # Terminate stale session
                    term_result = await self._api.patch(
                        f"/sessions/{s['id']}",
                        data={"status": "terminated"},
                    )
                    if term_result.success:
                        pruned.append(s["id"])

            self._log_usage("prune_stale_sessions", True, pruned_count=len(pruned))
            return SkillResult.ok({
                "pruned": len(pruned),
                "session_ids": pruned,
                "cutoff_hours": max_age_hours,
            })
        except Exception as e:
            self._log_usage("prune_stale_sessions", False, error=str(e))
            return SkillResult.fail(f"Failed to prune sessions: {e}")

    async def get_performance_report(self) -> SkillResult:
        """Generate aggregate performance report across all agents."""
        if not self._api:
            return SkillResult.fail("Not initialized")

        try:
            result = await self._api.get("/sessions/stats")
            if not result:
                raise Exception(result.error)
            stats = result.data

            report = {
                "total_sessions": stats.get("total_sessions", 0),
                "active_sessions": stats.get("active_sessions", 0),
                "total_tokens": stats.get("total_tokens", 0),
                "total_cost_usd": stats.get("total_cost", 0),
                "by_agent": stats.get("by_agent", []),
                "by_status": stats.get("by_status", []),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

            self._log_usage("get_performance_report", True)
            return SkillResult.ok(report)
        except Exception as e:
            self._log_usage("get_performance_report", False, error=str(e))
            return SkillResult.fail(f"Failed to generate report: {e}")

    async def get_agent_health(self) -> SkillResult:
        """Check all active agents, their status, and recent performance."""
        if not self._api:
            return SkillResult.fail("Not initialized")
        try:
            # Get active sessions
            sessions_result = await self._api.get(
                "/sessions", params={"status": "active", "limit": 100}
            )
            if not sessions_result:
                raise Exception(sessions_result.error)
            sessions = sessions_result.data.get("sessions", [])

            # Get performance stats
            stats = {}
            try:
                stats_result = await self._api.get("/sessions/stats")
                if stats_result.success:
                    stats = stats_result.data
            except Exception:
                pass

            now = datetime.now(timezone.utc)
            agents = []
            for s in sessions:
                started = s.get("started_at", "")
                try:
                    started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    uptime_min = int((now - started_dt).total_seconds() / 60)
                except (ValueError, TypeError):
                    uptime_min = 0
                agents.append({
                    "id": s.get("agent_id"),
                    "status": s.get("status"),
                    "model": s.get("model", "unknown"),
                    "uptime_minutes": uptime_min,
                    "last_active": s.get("last_active"),
                })

            self._log_usage("get_agent_health", True)
            return SkillResult.ok({
                "agents": agents,
                "total_active": len([a for a in agents if a["status"] == "active"]),
                "total_stale": len([a for a in agents if a["status"] == "stale"]),
                "stats": stats,
            })
        except Exception as e:
            self._log_usage("get_agent_health", False, error=str(e))
            return SkillResult.fail(f"Health check failed: {e}")

    async def spawn_focused_agent(
        self,
        task: str,
        focus: str,
        tools: list[str],
        model: str | None = None,
        persistent: bool = False,
    ) -> SkillResult:
        """Spawn a sub-agent, send the task, and return its response.

        Args:
            task: Task description for the sub-agent
            focus: Focus area (e.g. "research", "devsecops", "creative")
            tools: List of tool/skill names the sub-agent is allowed to use
            model: Optional LLM model ID from models.yaml to use.
                If None, the system default model is used.
            persistent: If False (default), the session is closed after the
                first response (ephemeral / one-shot).  If True, the session
                stays open so the caller can send follow-ups via
                send_to_agent() and close it later with terminate_agent().
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        remaining = self._subagent_circuit_remaining_seconds()
        if remaining > 0:
            return SkillResult.fail(
                "Sub-agent comms temporarily unavailable "
                f"(circuit open, retry in ~{remaining}s). "
                "Use direct tools in this session instead."
            )

        # Validate model if specified
        if model:
            valid = await self._validate_model(model)
            if not valid:
                return SkillResult.fail(f"Unknown or disabled model: {model}")

        session_id = None
        try:
            # Derive human-readable identity from focus
            _FOCUS_BADGES: dict[str, str] = {
                "research": "\U0001f50d",
                "devsecops": "\U0001f6e1\ufe0f",
                "creative": "\U0001f3a8",
                "data": "\U0001f4ca",
                "orchestrator": "\U0001f3af",
                "social": "\U0001f310",
            }
            display_name = focus.replace("_", " ").title()
            badge = _FOCUS_BADGES.get(focus.lower(), "\u2699\ufe0f")

            # 1. Create the scoped session (engine table so messages work)
            body = {
                "agent_id": f"sub-{focus}",
                "session_type": "scoped",
                "title": f"Agent: {focus} \u2014 {task[:80]}",
                "metadata": {
                    "task": task,
                    "focus": focus,
                    "display_name": display_name,
                    "badge": badge,
                    "tools_allowed": tools,
                    "constraints": [f"Use ONLY these tools: {', '.join(tools)}"],
                    "parent_id": "agent_manager",
                    "persistent": persistent,
                },
            }
            if model:
                body["model"] = model
            result = await self._api.post("/engine/chat/sessions", data=body)
            if not result or not result.success:
                raise Exception(result.error if result else "No response from API")
            session_id = (result.data or {}).get("id")
            if not session_id:
                raise Exception("Session created but no id returned")

            self.logger.info(
                "spawn_focused_agent: session %s created (focus=%s, persistent=%s)",
                session_id, focus, persistent,
            )

            # 2. Send the task as a message and get the LLM response
            msg_result = await self._api.post(
                f"/engine/chat/sessions/{session_id}/messages",
                data={
                    "content": task,
                    "enable_thinking": False,
                    "enable_tools": bool(tools),
                },
            )
            if not msg_result or not msg_result.success:
                err = msg_result.error if msg_result else "No response"
                raise Exception(f"Task send failed: {err}")

            response_data = msg_result.data or {}
            content = response_data.get("content", "")
            total_tokens = response_data.get("total_tokens", 0)
            resp_model = response_data.get("model", model or "default")
            self._subagent_circuit_until = None

            self._log_usage(
                "spawn_focused_agent", True,
                focus=focus,
                model=resp_model,
                tokens=total_tokens,
                persistent=persistent,
            )

            # 3. Ephemeral: close session.  Persistent: leave open.
            if not persistent:
                try:
                    await self._api.delete(
                        f"/engine/chat/sessions/{session_id}"
                    )
                    self.logger.debug(
                        "spawn_focused_agent: ephemeral session %s closed",
                        session_id,
                    )
                except Exception as ce:
                    self.logger.warning(
                        "spawn_focused_agent: cleanup failed for %s: %s",
                        session_id, ce,
                    )

            # 4. Return the full result so the parent can read & decide
            return SkillResult.ok({
                "session_id": session_id,
                "focus": focus,
                "display_name": display_name,
                "badge": badge,
                "model": resp_model,
                "persistent": persistent,
                "content": content,
                "tool_calls": response_data.get("tool_calls"),
                "tool_results": response_data.get("tool_results"),
                "total_tokens": total_tokens,
                "cost_usd": response_data.get("cost_usd", 0),
            })
        except Exception as e:
            self._log_usage("spawn_focused_agent", False, error=str(e))
            self._trip_subagent_circuit(str(e))
            # Clean up engine session on failure if it was created
            if session_id:
                try:
                    await self._api.delete(
                        f"/engine/chat/sessions/{session_id}"
                    )
                except Exception:
                    pass
            return SkillResult.fail(f"Focused agent failed: {e}")

    # ── Follow-up messaging ──────────────────────────────────────

    @log_latency
    async def send_to_agent(
        self,
        session_id: str,
        message: str,
        enable_tools: bool = True,
    ) -> SkillResult:
        """Send a follow-up message to a persistent sub-agent session.

        Use this after spawn_focused_agent(persistent=True) to continue
        the conversation with the same sub-agent.

        Args:
            session_id: The session UUID returned by spawn_focused_agent.
            message: The follow-up message / instruction to send.
            enable_tools: Whether the sub-agent may call tools (default True).

        Returns:
            SkillResult with the sub-agent's response content,
            tool_calls, cost, etc.
        """
        if not self._api:
            return SkillResult.fail("Not initialized")

        remaining = self._subagent_circuit_remaining_seconds()
        if remaining > 0:
            return SkillResult.fail(
                "Sub-agent comms temporarily unavailable "
                f"(circuit open, retry in ~{remaining}s). "
                "Continue directly in this session."
            )

        try:
            msg_result = await self._api.post(
                f"/engine/chat/sessions/{session_id}/messages",
                data={
                    "content": message,
                    "enable_thinking": False,
                    "enable_tools": enable_tools,
                },
            )
            if not msg_result or not msg_result.success:
                err = msg_result.error if msg_result else "No response"
                raise Exception(f"Message send failed: {err}")

            response_data = msg_result.data or {}
            self._subagent_circuit_until = None
            self._log_usage(
                "send_to_agent", True,
                session_id=session_id,
                tokens=response_data.get("total_tokens", 0),
            )

            return SkillResult.ok({
                "session_id": session_id,
                "content": response_data.get("content", ""),
                "tool_calls": response_data.get("tool_calls"),
                "tool_results": response_data.get("tool_results"),
                "model": response_data.get("model", ""),
                "total_tokens": response_data.get("total_tokens", 0),
                "cost_usd": response_data.get("cost_usd", 0),
            })
        except Exception as e:
            self._log_usage("send_to_agent", False, error=str(e))
            self._trip_subagent_circuit(str(e))
            return SkillResult.fail(f"Follow-up failed: {e}")

    # ── (delegate_task removed — use spawn_focused_agent instead) ──
