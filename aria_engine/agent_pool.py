"""
Agent Pool — Async lifecycle management for engine agents.

Manages agent instances backed by aria_engine.agent_state table.
Features:
- Load agents from DB on startup
- Spawn/terminate agents with lifecycle events
- Concurrent execution with asyncio.TaskGroup
- Agent state persistence (status, current_session, task)
- Integration with LLM gateway and skill registry
- Max 5 concurrent agents (configurable)
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session as _OrmSession

from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from db.models import EngineAgentState

logger = logging.getLogger("aria.engine.agent_pool")

MAX_CONCURRENT_AGENTS = 5

# Hard ceiling on active sub-agents by type prefix (last-resort cascade guard).
# Primary defence is CB-aware spawn logic in the work cycle.
# These limits prevent runaway spawning when that logic fails or is bypassed.
# Incident reference: The Midnight Cascade — 71 sub-devsecops, 27.2M tokens (2026-02-28)
MAX_SUB_AGENTS_PER_TYPE: dict[str, int] = {
    "sub-devsecops": 10,
    "sub-social": 10,
    "sub-orchestrator": 5,
    "sub-aria": 5,
}


def _budget_cap(caller: int | None, fp: dict | None) -> int | None:
    """
    Apply focus token_budget_hint as a hard ceiling on max_tokens.

    Design contract:
        - If no focus profile OR token_budget_hint == 0: caller passes through unchanged.
        - Otherwise: min(caller, token_budget_hint) — focus budget cannot be exceeded,
          even by explicit caller overrides.
        - If caller is None and budget is set: use budget as the ceiling.

    Args:
        caller: Caller-requested max_tokens (int or None = use model default).
        fp:     Resolved FocusProfileEntry dict (or None if no focus loaded).

    Returns:
        Capped int, or None if both caller and budget are unset.

    Examples:
        _budget_cap(4096, {"token_budget_hint": 800})  → 800   (capped)
        _budget_cap(500,  {"token_budget_hint": 800})  → 500   (under budget)
        _budget_cap(None, {"token_budget_hint": 800})  → 800   (budget is ceiling)
        _budget_cap(4096, None)                         → 4096  (no focus, pass through)
        _budget_cap(4096, {"token_budget_hint": 0})    → 4096  (budget disabled)
    """
    budget: int | None = fp.get("token_budget_hint") if fp else None
    if not budget:       # 0, None, missing, or no focus profile → pass through
        return caller
    if caller is None:   # no explicit caller value → enforce budget ceiling
        return budget
    return min(caller, budget)


@dataclass
class EngineAgent:
    """
    Runtime representation of an agent in the engine.

    Holds agent configuration, current state, and a task queue
    for processing messages asynchronously.
    """

    agent_id: str
    display_name: str = ""
    agent_type: str = "agent"  # agent, sub_agent, sub_aria, swarm, focus
    parent_agent_id: str | None = None
    model: str = ""
    fallback_model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = ""
    focus_type: str | None = None
    status: str = "idle"  # idle, busy, error, disabled
    enabled: bool = True
    skills: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    timeout_seconds: int = 600
    rate_limit: dict[str, Any] = field(default_factory=dict)
    current_session_id: str | None = None
    current_task: str | None = None
    pheromone_score: float = 0.500
    consecutive_failures: int = 0
    last_active_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Runtime state (not persisted)
    _task_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=100)
    )
    _worker_task: asyncio.Task | None = field(default=None, repr=False)
    _llm_gateway: Any | None = field(default=None, repr=False)
    _context: list[dict[str, str]] = field(default_factory=list, repr=False)
    _focus_profile: dict | None = field(default=None, repr=False)  # populated by load_focus_profile()

    async def process(self, message: str, **kwargs: Any) -> dict[str, Any]:
        """
        Process a message using the LLM gateway.

        Builds the message context, sends to LLM, and returns the response.

        Args:
            message: User/system message to process.
            **kwargs: Additional parameters (temperature, max_tokens overrides).

        Returns:
            Dict with content, thinking, tool_calls, model, usage stats.
        """
        if self._llm_gateway is None:
            raise EngineError(f"Agent {self.agent_id} has no LLM gateway")

        self.status = "busy"
        self.current_task = message[:200]

        # Add user message to context
        self._context.append({"role": "user", "content": message})

        # Resolve focus profile — use cached, no DB call here
        fp = self._focus_profile  # dict or None, pre-loaded by load_focus_profile()

        # Build effective system prompt — additive composition
        # Rule: effective = base + "\n\n---\n" + addon. Never replaces base.
        base_prompt = self.system_prompt or ""
        if fp and fp.get("system_prompt_addon"):
            effective_system = base_prompt.rstrip() + "\n\n---\n" + fp["system_prompt_addon"]
        else:
            effective_system = base_prompt

        # Build messages for LLM
        messages = []
        if effective_system:
            messages.append({"role": "system", "content": effective_system})
        # Sliding window: keep last N context messages
        context_window = kwargs.get("context_window", 50)
        messages.extend(self._context[-context_window:])

        # Apply focus temperature delta — additive, clamped to [0.0, 1.0]
        base_temp = kwargs.get("temperature", self.temperature)
        temp_delta = float(fp["temperature_delta"]) if fp and fp.get("temperature_delta") is not None else 0.0
        effective_temp = max(0.0, min(1.0, base_temp + temp_delta))

        # Apply focus model override — only if caller doesn't force a model
        effective_model = (
            kwargs.get("model")
            or (fp.get("model_override") if fp else None)
            or self.model
        )

        try:
            response = await self._llm_gateway.complete(
                messages=messages,
                model=effective_model,
                temperature=effective_temp,
                max_tokens=_budget_cap(
                    caller=kwargs.get("max_tokens", self.max_tokens),
                    fp=fp,
                ),
                tools=kwargs.get("tools"),
                enable_thinking=kwargs.get("enable_thinking", False),
            )

            # Add assistant response to context
            self._context.append(
                {"role": "assistant", "content": response.content}
            )

            self.status = "idle"
            self.current_task = None
            self.consecutive_failures = 0
            self.last_active_at = datetime.now(timezone.utc)

            return {
                "content": response.content,
                "thinking": response.thinking,
                "tool_calls": response.tool_calls,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "latency_ms": response.latency_ms,
            }

        except Exception as e:
            self.consecutive_failures += 1
            self.status = "error" if self.consecutive_failures >= 3 else "idle"
            self.current_task = None
            logger.error("Agent %s process failed: %s", self.agent_id, e)
            raise

    async def load_focus_profile(self, db_engine: "AsyncEngine") -> None:
        """Load and cache the focus profile for this agent from the DB.

        Must be called before process() to enable focus-aware prompt composition
        and temperature delta. Safe to call multiple times (re-fetches from DB).
        """
        if not self.focus_type:
            self._focus_profile = None
            return
        try:
            from db.models import FocusProfileEntry
            from sqlalchemy import select as _select
            from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
            async with _AsyncSession(db_engine) as session:
                result = await session.execute(
                    _select(FocusProfileEntry).where(
                        FocusProfileEntry.focus_id == self.focus_type,
                        FocusProfileEntry.enabled.is_(True),
                    )
                )
                row = result.scalars().first()
            self._focus_profile = row.to_dict() if row else None
            logger.debug(
                "Agent %s loaded focus_profile: %s (found=%s)",
                self.agent_id,
                self.focus_type,
                self._focus_profile is not None,
            )
        except Exception as exc:
            logger.warning(
                "Agent %s failed to load focus profile %r: %s",
                self.agent_id,
                self.focus_type,
                exc,
            )
            self._focus_profile = None

    def clear_context(self) -> None:
        """Clear the agent's conversation context."""
        self._context.clear()

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the agent's current state."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "agent_type": self.agent_type,
            "parent_agent_id": self.parent_agent_id,
            "model": self.model,
            "fallback_model": self.fallback_model,
            "status": self.status,
            "enabled": self.enabled,
            "focus_type": self.focus_type,
            "skills": self.skills,
            "capabilities": self.capabilities,
            "timeout_seconds": self.timeout_seconds,
            "current_session_id": self.current_session_id,
            "current_task": self.current_task,
            "pheromone_score": self.pheromone_score,
            "consecutive_failures": self.consecutive_failures,
            "last_active_at": (
                self.last_active_at.isoformat() if self.last_active_at else None
            ),
            "context_length": len(self._context),
            "system_prompt": self.system_prompt,
        }


class AgentPool:
    """
    Manages the lifecycle of all engine agents.

    Lifecycle:
        pool = AgentPool(config, db_engine, llm_gateway)
        await pool.load_agents()     # load from DB
        agent = pool.get_agent("main")
        result = await agent.process("Hello")
        await pool.terminate_agent("aria-talk")
    """

    def __init__(
        self,
        config: EngineConfig,
        db_engine: AsyncEngine,
        llm_gateway: Any | None = None,
    ):
        self.config = config
        self._db_engine = db_engine
        self._llm_gateway = llm_gateway
        self._agents: dict[str, EngineAgent] = {}
        self._concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
        self._skill_registry: Any | None = None

    def set_llm_gateway(self, gateway: Any) -> None:
        """Set the LLM gateway for all agents."""
        self._llm_gateway = gateway
        for agent in self._agents.values():
            agent._llm_gateway = gateway

    def set_skill_registry(self, registry: Any) -> None:
        """Set the skill registry for tool resolution."""
        self._skill_registry = registry

    async def load_agents(self) -> int:
        """
        Load all agents from the engine_agent_state table.

        Creates EngineAgent instances for each row and stores them
        in the pool. Agents with status='disabled' are loaded but
        not activated.

        Calling this again reloads from DB (replaces in-memory state).

        Returns:
            Number of agents loaded.
        """
        # Use an ORM session so .scalars() returns model instances
        # (raw conn.execute + .scalars() yields first-column strings).
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(self._db_engine) as session:
            result = await session.execute(
                select(EngineAgentState)
                .order_by(EngineAgentState.agent_id)
            )
            rows = result.scalars().all()

        # Clear previous state so removed agents don't linger
        self._agents.clear()

        for row in rows:
            is_enabled = row.enabled
            if is_enabled is None:
                is_enabled = True
            agent = EngineAgent(
                agent_id=row.agent_id,
                display_name=row.display_name or row.agent_id,
                agent_type=row.agent_type or "agent",
                parent_agent_id=row.parent_agent_id,
                model=row.model,
                fallback_model=row.fallback_model,
                temperature=row.temperature or 0.7,
                max_tokens=row.max_tokens or 4096,
                system_prompt=row.system_prompt or "",
                focus_type=row.focus_type,
                status=row.status or "idle",
                enabled=is_enabled,
                skills=row.skills or [],
                capabilities=row.capabilities or [],
                timeout_seconds=row.timeout_seconds or 600,
                rate_limit=row.rate_limit or {},
                current_session_id=(
                    str(row.current_session_id)
                    if row.current_session_id
                    else None
                ),
                pheromone_score=float(row.pheromone_score or 0.5),
                consecutive_failures=row.consecutive_failures or 0,
                last_active_at=row.last_active_at,
                metadata=row.metadata_json or {},
            )
            agent._llm_gateway = self._llm_gateway
            self._agents[row.agent_id] = agent

        logger.info("Loaded %d agents from database", len(self._agents))
        return len(self._agents)

    async def spawn_agent(
        self,
        agent_id: str,
        model: str = "",
        display_name: str = "",
        system_prompt: str = "",
        focus_type: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> EngineAgent:
        """
        Create and register a new agent.

        Inserts a row into agent_state and creates an EngineAgent instance.

        Args:
            agent_id: Unique identifier for the agent.
            model: LLM model to use.
            display_name: Human-readable name.
            system_prompt: System prompt for the agent.
            focus_type: Agent's focus area.
            temperature: LLM temperature.
            max_tokens: LLM max tokens.

        Returns:
            The new EngineAgent instance.

        Raises:
            EngineError: If agent already exists or pool is full.
        """
        if agent_id in self._agents:
            raise EngineError(f"Agent {agent_id!r} already exists")

        if len(self._agents) >= MAX_CONCURRENT_AGENTS:
            raise EngineError(
                f"Agent pool full ({MAX_CONCURRENT_AGENTS} max). "
                "Terminate an agent first."
            )

        # Per-type ceiling: query DB for current sub-agent count before spawning.
        # Uses rsplit to extract prefix: "sub-devsecops-7" → "sub-devsecops"
        # Prevents cascade spawning when a circuit breaker is permanently open.
        type_prefix = agent_id.rsplit("-", 1)[0] if "-" in agent_id else agent_id
        if type_prefix in MAX_SUB_AGENTS_PER_TYPE:
            async with self._db_engine.begin() as _check:
                count_q = (
                    select(func.count())
                    .select_from(EngineAgentState)
                    .where(
                        EngineAgentState.agent_id.like(f"{type_prefix}-%"),
                        EngineAgentState.status != "disabled",
                    )
                )
                _count_result = await _check.execute(count_q)
                current_count: int = _count_result.scalar_one()
            ceiling = MAX_SUB_AGENTS_PER_TYPE[type_prefix]
            if current_count >= ceiling:
                raise EngineError(
                    f"Sub-agent ceiling reached: {type_prefix!r} has "
                    f"{current_count}/{ceiling} active agents. "
                    "Circuit breaker must reset or stale agents must be terminated first."
                )

        # Insert to DB (upsert)
        async with self._db_engine.begin() as conn:
            stmt = pg_insert(EngineAgentState).values(
                agent_id=agent_id,
                display_name=display_name or agent_id,
                agent_type="agent",
                model=model or self.config.default_model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                focus_type=focus_type,
                status="idle",
                enabled=True,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["agent_id"],
                set_={
                    "status": "idle",
                    "model": stmt.excluded.model,
                    "display_name": stmt.excluded.display_name,
                    "system_prompt": stmt.excluded.system_prompt,
                    "updated_at": func.now(),
                },
            )
            await conn.execute(stmt)

        # Create in-memory agent
        agent = EngineAgent(
            agent_id=agent_id,
            display_name=display_name or agent_id,
            model=model or self.config.default_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            focus_type=focus_type,
            status="idle",
        )
        agent._llm_gateway = self._llm_gateway
        self._agents[agent_id] = agent

        logger.info("Spawned agent: %s (model=%s)", agent_id, agent.model)
        return agent

    def get_agent(self, agent_id: str) -> EngineAgent | None:
        """Get an agent by ID. Returns None if not found."""
        return self._agents.get(agent_id)

    def get_skill(self, skill_name: str) -> Any | None:
        """Get a skill by name from the registry."""
        if self._skill_registry is None:
            return None
        return self._skill_registry.get(skill_name)

    async def terminate_agent(self, agent_id: str) -> bool:
        """
        Gracefully terminate an agent.

        Cancels any running tasks, persists final state, and removes
        from the in-memory pool.

        Args:
            agent_id: Agent to terminate.

        Returns:
            True if the agent was terminated.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return False

        # Cancel worker task if running
        if agent._worker_task and not agent._worker_task.done():
            agent._worker_task.cancel()
            try:
                await agent._worker_task
            except asyncio.CancelledError:
                pass

        # Persist final state as disabled for explicit termination.
        await self._persist_agent_state(agent_id, status="disabled")

        # Remove from pool
        del self._agents[agent_id]

        logger.info("Terminated agent: %s", agent_id)
        return True

    def list_agents(self) -> list[dict[str, Any]]:
        """Get summaries of all agents in the pool."""
        return [agent.get_summary() for agent in self._agents.values()]

    async def process_with_agent(
        self,
        agent_id: str,
        message: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Process a message with a specific agent, respecting concurrency limits.

        Args:
            agent_id: Agent to use.
            message: Message to process.
            **kwargs: Additional parameters for the agent.

        Returns:
            Agent response dict.

        Raises:
            EngineError: If agent not found.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise EngineError(f"Agent {agent_id!r} not found in pool")

        if agent.status == "disabled":
            raise EngineError(f"Agent {agent_id!r} is disabled")

        async with self._concurrency_semaphore:
            try:
                result = await agent.process(message, **kwargs)
                # Persist updated state
                await self._persist_agent_state(agent_id)
                return result
            except Exception:
                await self._persist_agent_state(agent_id)
                raise

    async def run_parallel(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Run multiple agent tasks in parallel using TaskGroup.

        Args:
            tasks: List of dicts with 'agent_id' and 'message' keys.

        Returns:
            List of result dicts (one per task).
        """
        results: list[dict[str, Any]] = [{}] * len(tasks)

        async with asyncio.TaskGroup() as tg:
            for i, task in enumerate(tasks):

                async def _run(
                    idx: int = i, t: dict[str, Any] = task
                ) -> None:
                    try:
                        result = await self.process_with_agent(
                            agent_id=t["agent_id"],
                            message=t["message"],
                            **{
                                k: v
                                for k, v in t.items()
                                if k not in ("agent_id", "message")
                            },
                        )
                        results[idx] = result
                    except Exception as e:
                        results[idx] = {
                            "content": f"[Error: {e}]",
                            "agent_id": t["agent_id"],
                            "error": str(e),
                        }

                tg.create_task(_run())

        return results

    async def _persist_agent_state(
        self,
        agent_id: str,
        status: str | None = None,
    ) -> None:
        """Persist agent runtime state to the database."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return

        async with self._db_engine.begin() as conn:
            await conn.execute(
                update(EngineAgentState)
                .where(EngineAgentState.agent_id == agent_id)
                .values(
                    status=status or agent.status,
                    current_task=agent.current_task,
                    consecutive_failures=agent.consecutive_failures,
                    pheromone_score=agent.pheromone_score,
                    last_active_at=agent.last_active_at,
                    updated_at=func.now(),
                )
            )

    async def update_agent_config(
        self,
        agent_id: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        focus_type: str | None = None,
        temperature: float | None = None,
        skills: list[str] | None = None,
    ) -> "EngineAgent":
        """Update config fields for an existing agent (in-memory + DB)."""
        agent = self._agents.get(agent_id)
        if agent is None:
            raise EngineError(f"Agent {agent_id!r} not found in pool")

        if model is not None:
            agent.model = model
        if system_prompt is not None:
            agent.system_prompt = system_prompt
        if focus_type is not None:
            agent.focus_type = focus_type
        if temperature is not None:
            agent.temperature = temperature
        if skills is not None:
            agent.skills = skills

        update_vals: dict[str, Any] = {"updated_at": func.now()}
        if model is not None:
            update_vals["model"] = model
        if system_prompt is not None:
            update_vals["system_prompt"] = system_prompt
        if focus_type is not None:
            update_vals["focus_type"] = focus_type
        if temperature is not None:
            update_vals["temperature"] = temperature
        if skills is not None:
            update_vals["skills"] = skills

        async with self._db_engine.begin() as conn:
            await conn.execute(
                update(EngineAgentState)
                .where(EngineAgentState.agent_id == agent_id)
                .values(**update_vals)
            )
        return agent

    def get_status(self) -> dict[str, Any]:
        """Get pool status summary."""
        statuses: dict[str, int] = {}
        for agent in self._agents.values():
            statuses[agent.status] = statuses.get(agent.status, 0) + 1

        return {
            "total_agents": len(self._agents),
            "max_concurrent": MAX_CONCURRENT_AGENTS,
            "status_counts": statuses,
            "agents": [a.get_summary() for a in self._agents.values()],
        }

    async def shutdown(self) -> None:
        """Gracefully shutdown all agents."""
        for agent_id in list(self._agents.keys()):
            agent = self._agents.get(agent_id)
            if agent is None:
                continue

            if agent._worker_task and not agent._worker_task.done():
                agent._worker_task.cancel()
                try:
                    await agent._worker_task
                except asyncio.CancelledError:
                    pass

            agent.status = "idle"
            agent.current_task = None
            await self._persist_agent_state(agent_id, status="idle")
            del self._agents[agent_id]

        logger.info("Agent pool shutdown complete")
