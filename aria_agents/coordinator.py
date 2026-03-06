# aria_agents/coordinator.py
"""
Agent coordinator.

Manages agent lifecycle and message routing.
Supports CEO pattern: Aria orchestrates, delegates maximally, and facilitates
cross-focus collaboration via roundtable discussions.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from aria_agents.base import AgentConfig, AgentMessage, AgentRole, BaseAgent
from aria_agents.context import AgentContext, AgentResult
from aria_agents.scoring import (
    compute_pheromone,
    select_best_agent,
    COLD_START_SCORE,
    get_performance_tracker,
    PerformanceTracker,
)

# Keywords that trigger cross-focus collaboration
ROUNDTABLE_TRIGGERS = re.compile(
    r"(cross-team|all perspectives|multi.?domain|collaboration|joint analysis|"
    r"security.{0,20}data|data.{0,20}security|launch.{0,20}strategy|comprehensive.{0,20}review)",
    re.IGNORECASE
)
from aria_agents.loader import AgentLoader
from aria_models.loader import get_route_skill, normalize_model_id

try:
    from aria_mind.skills._coherence import workspace_root as _skills_workspace_root
    from aria_mind.skills._kernel_router import auto_route_task_to_skills

    _HAS_SKILL_ROUTER = True
except Exception as _e:
    logger.warning("Skill router import failed (non-fatal): %s", _e)
    _HAS_SKILL_ROUTER = False

if TYPE_CHECKING:
    from aria_skills import SkillRegistry

MAX_CONCURRENT_AGENTS = 5


class LLMAgent(BaseAgent):
    """
    Agent that uses an LLM skill for processing.
    
    Uses the configured model to generate responses.
    All models route through LiteLLM for unified access.
    Supports peer consultation via coordinator reference.
    """
    
    def __init__(
        self, 
        config: AgentConfig, 
        skill_registry=None, 
        coordinator: "AgentCoordinator" = None
    ):
        super().__init__(config, skill_registry, coordinator)
    
    async def process(self, message: str, **kwargs) -> AgentMessage:
        """Process message using LLM."""
        # Add user message to context
        user_msg = AgentMessage(role="user", content=message)
        self.add_to_context(user_msg)
        
        # Get the right LLM skill based on model config
        # All models route through litellm proxy now (single gateway)
        llm_skill = None
        if self._skill_registry:
            model_id = normalize_model_id(self.config.model)
            route_skill = get_route_skill(model_id)

            if route_skill == "litellm":
                # Preferred: everything through litellm proxy
                llm_skill = self._skill_registry.get("litellm")
            elif route_skill == "moonshot":
                # Legacy: direct moonshot SDK (fallback if litellm down)
                llm_skill = self._skill_registry.get("litellm") or self._skill_registry.get("moonshot")
            elif route_skill == "ollama":
                # Legacy: direct ollama (fallback if litellm down)
                llm_skill = self._skill_registry.get("litellm") or self._skill_registry.get("ollama")
            else:
                # Default: litellm → ollama → moonshot
                llm_skill = (
                    self._skill_registry.get("litellm")
                    or self._skill_registry.get("ollama")
                    or self._skill_registry.get("moonshot")
                )

            # Final fallback chain
            if not llm_skill:
                llm_skill = (
                    self._skill_registry.get("litellm")
                    or self._skill_registry.get("moonshot")
                    or self._skill_registry.get("ollama")
                )
        
        if not llm_skill:
            self.logger.warning("No LLM skill available, returning placeholder")
            response = AgentMessage(
                role="assistant",
                content="[LLM not available]",
                agent_id=self.id,
            )
            self.add_to_context(response)
            return response
        
        # Build messages for LLM
        import os
        context_limit = int(os.getenv("AGENT_CONTEXT_LIMIT", "8"))
        messages = [{"role": "system", "content": self.get_system_prompt()}]
        skill_routing = kwargs.get("skill_routing")
        if isinstance(skill_routing, dict):
            candidates = skill_routing.get("candidates") or []
            route_source = skill_routing.get("route_source", "unknown")
            if candidates:
                top = []
                for row in candidates[:2]:
                    top_name = row.get("skill_name") or row.get("canonical_name")
                    if top_name:
                        top.append(str(top_name))
                if top:
                    messages.append(
                        {
                            "role": "system",
                            "content": f"Skill hints ({route_source}): {', '.join(top)}",
                        }
                    )

        for ctx_msg in self.get_context(limit=context_limit):
            messages.append({
                "role": ctx_msg.role,
                "content": ctx_msg.content,
            })
        
        # Call LLM with error handling
        try:
            result = await llm_skill.chat(
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            
            if result.success:
                content = result.data.get("text", "")
            else:
                content = f"[Error: {result.error}]"
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            content = f"[LLM Error: {e}]"
        
        response = AgentMessage(
            role="assistant",
            content=content,
            agent_id=self.id,
        )
        self.add_to_context(response)
        return response


class AgentCoordinator:
    """
    Coordinates multiple agents with performance-aware routing.
    
    Handles:
    - Agent lifecycle (creation, initialization)
    - Message routing with pheromone-based agent selection
    - Performance tracking and learning
    - Cross-focus collaboration via roundtable
    - Explore/Work/Validate structured task execution
    """
    
    def __init__(self, skill_registry: "SkillRegistry" | None = None):
        self._skill_registry = skill_registry
        self._agents: dict[str, BaseAgent] = {}
        self._configs: dict[str, AgentConfig] = {}
        self._hierarchy: dict[str, list[str]] = {}
        self._main_agent_id: str | None = None
        self._tracker: PerformanceTracker = get_performance_tracker()
        self._enable_skill_routing_hints = True
        self.logger = logging.getLogger("aria.coordinator")

    async def suggest_skills_for_task(
        self,
        task: str,
        limit: int = 2,
        include_info: bool = False,
    ) -> dict[str, Any]:
        """Best-effort skill routing for a free-form task."""
        if not _HAS_SKILL_ROUTER:
            return {
                "task": task,
                "route_source": "disabled",
                "route_diagnostics": [{"type": "dependency", "reason": "skill_router_unavailable"}],
                "count": 0,
                "candidates": [],
            }

        registry_names: set[str] = set()
        if self._skill_registry:
            try:
                registry_names.update(self._skill_registry.list())
            except Exception:
                pass

        if not registry_names:
            for agent in self._agents.values():
                registry_names.update(agent.config.skills or [])

        registry_map = {name: None for name in registry_names if isinstance(name, str) and name}
        if not registry_map:
            return {
                "task": task,
                "route_source": "empty_registry",
                "route_diagnostics": [{"type": "registry", "reason": "no_skills_available"}],
                "count": 0,
                "candidates": [],
            }

        route = await auto_route_task_to_skills(
            task=task,
            limit=max(1, int(limit)),
            registry=registry_map,
            validate_skill_coherence_fn=lambda _skill_name: {
                "coherent": None,
                "has_changes": None,
                "checks": {},
                "warnings": ["coherence_not_checked_in_agent_context"],
                "errors": [],
            },
            workspace_root_fn=_skills_workspace_root,
            include_info=include_info,
        )

        # Keep only skills known by this runtime unless none are known.
        if registry_map:
            filtered = [row for row in route.get("candidates", []) if row.get("skill_name") in registry_map]
            route["candidates"] = filtered
            route["count"] = len(filtered)
        return route
    
    def set_skill_registry(self, registry: "SkillRegistry") -> None:
        """Inject skill registry."""
        self._skill_registry = registry
        # Update all existing agents
        for agent in self._agents.values():
            agent.set_skill_registry(registry)
    
    async def load_from_file(self, filepath: str) -> None:
        """
        Load agent configurations from AGENTS.md.
        
        Args:
            filepath: Path to AGENTS.md file
        """
        self._configs = AgentLoader.load_from_file(filepath)
        self._hierarchy = AgentLoader.get_agent_hierarchy(self._configs)
        
        # Find main agent (no parent)
        for agent_id, config in self._configs.items():
            if config.parent is None:
                self._main_agent_id = agent_id
                break
        
        self.logger.info(f"Loaded {len(self._configs)} agent configs, main: {self._main_agent_id}")
    
    async def initialize_agents(self) -> None:
        """Create and initialize all agents with coordinator access."""
        for agent_id, config in self._configs.items():
            # Pass coordinator=self so agents can consult peers
            agent = LLMAgent(config, self._skill_registry, coordinator=self)
            self._agents[agent_id] = agent
            self.logger.debug(f"Created agent: {agent_id}")
        
        # Set up sub-agent relationships
        for parent_id, child_ids in self._hierarchy.items():
            parent = self._agents.get(parent_id)
            if parent:
                for child_id in child_ids:
                    child = self._agents.get(child_id)
                    if child:
                        parent.add_sub_agent(child)
                        self.logger.debug(f"Linked {child_id} -> {parent_id}")
    
    def get_agent(self, agent_id: str) -> BaseAgent | None:
        """Get an agent by ID."""
        return self._agents.get(agent_id)
    
    def get_main_agent(self) -> BaseAgent | None:
        """Get the main (root) agent."""
        if self._main_agent_id:
            return self._agents.get(self._main_agent_id)
        return None
    
    def list_agents(self) -> list[str]:
        """List all agent IDs."""
        return list(self._agents.keys())
    
    async def process(self, message: str, agent_id: str | None = None, **kwargs) -> AgentMessage:
        """
        Process a message through an agent with performance tracking.
        
        Enhanced with:
        - Pheromone-based agent selection when no specific agent requested
        - Performance recording after each invocation
        - Auto-detection of roundtable needs
        
        Args:
            message: Input message
            agent_id: Target agent (defaults to best available or main agent)
            **kwargs: Additional parameters
            
        Returns:
            Response from the agent
        """
        if self._enable_skill_routing_hints and "skill_routing" not in kwargs:
            try:
                kwargs["skill_routing"] = await self.suggest_skills_for_task(
                    task=message,
                    limit=2,
                    include_info=False,
                )
            except Exception as exc:
                self.logger.debug(f"Skill routing hint unavailable: {exc}")

        # Auto-detect if this needs roundtable collaboration
        if not agent_id and self.detect_roundtable_need(message):
            self.logger.info("Auto-detected roundtable need — gathering perspectives")
            perspectives = await self.roundtable(message)
            if perspectives:
                # Synthesize perspectives through main agent
                synthesis_prompt = self._build_synthesis_prompt(message, perspectives)
                agent_id = self._main_agent_id
                message = synthesis_prompt
        
        # Select target agent — use pheromone scores if no specific agent requested
        target_id = agent_id
        if not target_id:
            if len(self._agents) > 1 and self._tracker:
                # Let performance scores guide agent selection
                candidates = list(self._agents.keys())
                target_id = self._tracker.get_best_agent(candidates)
                self.logger.debug(
                    f"Pheromone selection: {target_id} "
                    f"(score={self._tracker.get_score(target_id):.3f})"
                )
            else:
                target_id = self._main_agent_id
        
        if not target_id:
            return AgentMessage(
                role="system",
                content="No agents configured",
            )
        
        agent = self._agents.get(target_id)
        if not agent:
            return AgentMessage(
                role="system",
                content=f"Agent {target_id} not found",
            )
        
        # Execute with timing for performance tracking
        start = datetime.now(timezone.utc)
        try:
            result = await agent.process(message, **kwargs)
            elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            
            # Record success
            success = bool(result.content) and not result.content.startswith("[Error")
            self._tracker.record(
                agent_id=target_id,
                success=success,
                duration_ms=elapsed_ms,
            )
            
            return result
            
        except Exception as e:
            elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            
            # Record failure
            self._tracker.record(
                agent_id=target_id,
                success=False,
                duration_ms=elapsed_ms,
            )
            
            self.logger.error(f"Agent {target_id} failed: {e}")
            return AgentMessage(
                role="system",
                content=f"[Error: {e}]",
                agent_id=target_id,
            )
    
    def _build_synthesis_prompt(
        self, original_message: str, perspectives: dict[str, AgentMessage]
    ) -> str:
        """Build a synthesis prompt from roundtable perspectives."""
        parts = [f"Original request: {original_message}\n\nPerspectives gathered:\n"]
        for agent_id, msg in perspectives.items():
            parts.append(f"**{agent_id}**: {msg.content[:500]}\n")
        parts.append(
            "\nSynthesize these perspectives into a coherent, actionable response. "
            "Highlight agreements, resolve conflicts, and provide a unified recommendation."
        )
        return "\n".join(parts)
    
    async def broadcast(self, message: str, **kwargs) -> dict[str, AgentMessage]:
        """
        Send a message to all agents in parallel.
        
        Args:
            message: Message to broadcast
            **kwargs: Additional parameters
            
        Returns:
            Dict of agent_id -> response
        """
        async def _process_single(agent_id: str, agent: BaseAgent) -> tuple:
            try:
                response = await agent.process(message, **kwargs)
                return agent_id, response
            except Exception as e:
                self.logger.error(f"Agent {agent_id} failed: {e}")
                return agent_id, AgentMessage(
                    role="system",
                    content=f"Error: {e}",
                    agent_id=agent_id,
                )
        
        # Process all agents in parallel
        results = await asyncio.gather(*[
            _process_single(aid, a) for aid, a in self._agents.items()
        ])
        
        return dict(results)
    
    def detect_roundtable_need(self, message: str) -> bool:
        """
        Auto-detect if a task needs cross-focus collaboration.
        
        Triggers on keywords indicating multi-domain work like
        "launch", "promo", "security AND data review", etc.
        
        Args:
            message: The input message to analyze
            
        Returns:
            True if roundtable discussion is recommended
        """
        return bool(ROUNDTABLE_TRIGGERS.search(message))
    
    async def roundtable(
        self, 
        question: str, 
        agent_ids: list[str] | None = None,
        exclude_main: bool = True
    ) -> dict[str, AgentMessage]:
        """
        Gather perspectives from multiple agents in parallel.
        
        CEO Pattern: Use this when a task spans multiple focus areas.
        Each agent provides their specialized perspective, then Aria
        synthesizes into a coherent decision/plan.
        
        Example:
            perspectives = await coordinator.roundtable(
                "How should we promote the AI project?",
                agent_ids=["devops", "analyst", "creator"]
            )
            # devops: security concerns
            # analyst: metrics/KPIs
            # creator: content strategy
        
        Args:
            question: The topic/question to discuss
            agent_ids: Specific agents to consult (default: all except main)
            exclude_main: Whether to exclude the main orchestrator agent
            
        Returns:
            Dict of agent_id -> response message
        """
        # Default: all agents except the main orchestrator
        if agent_ids is None:
            targets = [
                aid for aid in self._agents 
                if not exclude_main or aid != self._main_agent_id
            ]
        else:
            targets = [aid for aid in agent_ids if aid in self._agents]
        
        if not targets:
            self.logger.warning("No agents available for roundtable")
            return {}
        
        async def _get_perspective(agent_id: str) -> tuple:
            agent = self._agents.get(agent_id)
            if not agent:
                return agent_id, None
            
            # Frame the question for focused perspective
            prompt = (
                f"[Roundtable Discussion]\n"
                f"{question}\n\n"
                f"Provide your perspective from your focus area ({agent.config.role.value}). "
                f"Be concise and actionable."
            )
            
            try:
                response = await agent.process(prompt)
                return agent_id, response
            except Exception as e:
                self.logger.error(f"Roundtable: {agent_id} failed: {e}")
                return agent_id, AgentMessage(
                    role="system",
                    content=f"[Error from {agent_id}: {e}]",
                    agent_id=agent_id,
                )
        
        # Gather all perspectives in parallel
        results = await asyncio.gather(*[_get_perspective(aid) for aid in targets])
        
        self.logger.info(f"Roundtable complete: {len(results)} perspectives gathered")
        return {aid: resp for aid, resp in results if resp}
    
    def get_status(self) -> dict[str, Any]:
        """Get coordinator status with performance leaderboard."""
        return {
            "agents": len(self._agents),
            "main_agent": self._main_agent_id,
            "hierarchy": self._hierarchy,
            "skill_registry": self._skill_registry is not None,
            "performance": {
                "total_invocations": self._tracker._total_invocations,
                "leaderboard": self._tracker.get_leaderboard(),
            },
        }

    # ── Explorer / Worker / Validator cycle ──────────────────────────────

    async def explore(self, ctx: AgentContext) -> list[str]:
        """Generate candidate approaches for a task.

        Returns a list of approach strings (ideally 3). Falls back to the
        full LLM response as a single approach if parsing fails.
        """
        agent = self._agents.get(ctx.agent_id) or self.get_main_agent()
        if not agent:
            return [ctx.task]

        prompt = (
            f"List 3 distinct approaches to accomplish this task. "
            f"Return each approach on its own numbered line (1. 2. 3.).\n\n"
            f"Task: {ctx.task}"
        )
        response = await agent.process(prompt)
        text = response.content

        # Try to parse numbered lines
        approaches = re.findall(r"^\s*\d+[\.)\-]\s*(.+)", text, re.MULTILINE)
        if approaches:
            return [a.strip() for a in approaches if a.strip()]
        # Fallback: return full response as single approach
        return [text.strip()] if text.strip() else [ctx.task]

    async def work(self, ctx: AgentContext, approach: str) -> AgentResult:
        """Implement a selected approach."""
        agent = self._agents.get(ctx.agent_id) or self.get_main_agent()
        agent_id = agent.id if agent else ctx.agent_id or "unknown"

        if not agent:
            return AgentResult(agent_id=agent_id, success=False, output="No agent available")

        start = datetime.now(timezone.utc)
        prompt = (
            f"Implement the following approach for the task.\n\n"
            f"Task: {ctx.task}\nApproach: {approach}"
        )
        response = await agent.process(prompt)
        elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

        content = response.content
        has_error = any(marker in content for marker in [
            "[LLM Error:", "[Error:", "Failed:", "[LLM not available]"
        ])
        return AgentResult(
            agent_id=agent_id,
            success=not has_error,
            output=content,
            duration_ms=elapsed,
        )

    async def validate(self, ctx: AgentContext, result: AgentResult) -> AgentResult:
        """Validate a work result against task constraints."""
        agent = self._agents.get(ctx.agent_id) or self.get_main_agent()
        agent_id = agent.id if agent else ctx.agent_id or "unknown"

        if not agent:
            return AgentResult(agent_id=agent_id, success=False, output="No agent available")

        constraint_text = ", ".join(ctx.constraints) if ctx.constraints else "none"
        prompt = (
            f"Validate this output against the constraints.\n\n"
            f"Task: {ctx.task}\nConstraints: {constraint_text}\n"
            f"Output to validate:\n{result.output}"
        )
        response = await agent.process(prompt)

        content = response.content.upper()
        passed = "PASS" in content and "FAIL" not in content
        return AgentResult(
            agent_id=agent_id,
            success=passed,
            output=response.content,
        )

    async def solve(self, ctx: AgentContext, max_attempts: int = 3) -> AgentResult:
        """Full explore -> work -> validate cycle with retry."""
        approaches = await self.explore(ctx)

        for attempt in range(max_attempts):
            approach = approaches[attempt % len(approaches)]
            result = await self.work(ctx, approach)

            if not result.success:
                self.logger.warning(f"Attempt {attempt+1} work failed: {result.output[:100]}")
                continue

            validation = await self.validate(ctx, result)
            if validation.success:
                return result

            self.logger.warning(f"Attempt {attempt+1} validation failed: {validation.output[:100]}")

        return AgentResult(
            agent_id=ctx.agent_id or "unknown",
            success=False,
            output=f"Max {max_attempts} attempts exceeded",
        )

    async def spawn_parallel(self, tasks: list[AgentContext]) -> list[AgentResult]:
        """Run multiple tasks concurrently with a semaphore."""
        if not tasks:
            return []

        sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

        async def _limited(t: AgentContext) -> AgentResult:
            async with sem:
                return await self._process_task(t)

        return list(await asyncio.gather(*[_limited(t) for t in tasks]))

    async def _process_task(self, ctx: AgentContext) -> AgentResult:
        """Internal: run a single task, record timing, and track performance."""
        agent = self._agents.get(ctx.agent_id) or self.get_main_agent()
        agent_id = agent.id if agent else ctx.agent_id or "unknown"

        if not agent:
            return AgentResult(agent_id=agent_id, success=False, output="No agent available")

        start = datetime.now(timezone.utc)
        try:
            response = await agent.process(ctx.task)
            elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            
            # Record performance
            success = bool(response.content) and not response.content.startswith("[Error")
            self._tracker.record(
                agent_id=agent_id,
                success=success,
                duration_ms=elapsed,
                task_type="parallel_task",
            )
            
            return AgentResult(
                agent_id=agent_id,
                success=success,
                output=response.content,
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            
            self._tracker.record(
                agent_id=agent_id,
                success=False,
                duration_ms=elapsed,
                task_type="parallel_task",
            )
            
            return AgentResult(
                agent_id=agent_id,
                success=False,
                output=str(exc),
                duration_ms=elapsed,
            )
