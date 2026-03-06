"""
Agent Auto-Routing — pheromone-based message routing.

Ports scoring logic from aria_agents/scoring.py to engine with DB persistence.
Features:
- Multi-factor routing: specialty match + load + pheromone + success rate
- Pheromone score update after each interaction (boost on success, decay on failure)
- Scores persisted to engine_agent_state.pheromone_score
- Cold start handling (new agents get neutral 0.500 score)
- Time-decay weighting (recent performance matters more)
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncEngine
from db.models import EngineAgentState

from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from aria_agents.scoring import compute_pheromone as _compute_pheromone

logger = logging.getLogger("aria.engine.routing")

# Scoring parameters (ported from aria_agents/scoring.py)
DECAY_FACTOR = 0.95          # Per-day decay
COLD_START_SCORE = 0.500     # Neutral starting score
MAX_RECORDS_PER_AGENT = 200  # History cap

# Routing weight factors
WEIGHTS = {
    "pheromone": 0.35,       # Overall pheromone score
    "specialty": 0.30,       # Specialty match for the message
    "load": 0.20,            # Current load (lower = better)
    "recency": 0.15,         # Recent success rate (last 10 interactions)
}

# Fallback specialty patterns (used when DB is unavailable or table is empty)
_FALLBACK_PATTERNS: dict[str, re.Pattern] = {
    "social":       re.compile(r"(social|post|tweet|moltbook|community|engage|share|content)", re.IGNORECASE),
    "analysis":     re.compile(r"(analy|metric|data|report|review|insight|trend|stat)", re.IGNORECASE),
    "devops":       re.compile(r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug)", re.IGNORECASE),
    "devsecops":    re.compile(r"(deploy|docker|server|ci|cd|build|test|infra|monitor|debug|security|vulnerability|patch)", re.IGNORECASE),
    "creative":     re.compile(r"(creat|write|art|story|design|brand|visual|content|blog)", re.IGNORECASE),
    "research":     re.compile(r"(research|paper|study|learn|explore|investigate|knowledge)", re.IGNORECASE),
    "data":         re.compile(r"(analy|metric|data|report|insight|trend|stat|pipeline|ml|query|sql)", re.IGNORECASE),
    "orchestrator": re.compile(r"(strategy|plan|coordinate|orchestrate|decide|priority|goal|overview)", re.IGNORECASE),
    "journalist":   re.compile(r"(report|article|news|investigate|story|lead|headline|press|coverage)", re.IGNORECASE),
    "rpg_master":   re.compile(r"(rpg|campaign|quest|npc|dungeon|character|encounter|lore|world)", re.IGNORECASE),
    "trader":       re.compile(r"(trade|trader|portfolio|market|crypto|token|price|bull|bear|invest|asset|coin|defi|swap)", re.IGNORECASE),
}

# Live cache — populated by EngineRouter.initialize_patterns() from DB.
# Falls back to _FALLBACK_PATTERNS when empty or DB is unavailable.
SPECIALTY_PATTERNS: dict[str, re.Pattern] = dict(_FALLBACK_PATTERNS)

# Patterns that suggest a question benefits from multiple perspectives
ESCALATION_PATTERNS: list[tuple[re.Pattern, float]] = [
    # Direct multi-agent requests
    (re.compile(r"\b(roundtable|swarm|discuss|debate|discuss|brainstorm)\b", re.I), 0.9),
    # Comparative / evaluative questions
    (re.compile(r"\b(compare|versus|vs\.?|tradeoff|trade-off|pros and cons)\b", re.I), 0.7),
    # Strategic / architectural decisions
    (re.compile(r"\b(should we|strategy|architect|rewrite|refactor|migrate|redesign)\b", re.I), 0.6),
    # Cross-domain questions (touches multiple specialties)
    (re.compile(r"\b(also|both|and also|end-to-end|full.?stack|holistic)\b", re.I), 0.3),
    # Opinion-seeking
    (re.compile(r"\b(what do you think|your opinion|recommend|advise|suggest)\b", re.I), 0.4),
]

# Minimum escalation score to recommend multi-agent
ESCALATION_THRESHOLD = 0.6


def compute_specialty_match(
    message: str,
    focus_type: str | None,
) -> float:
    """
    Compute how well a message matches an agent's specialty.

    Args:
        message: The input message.
        focus_type: Agent's focus type (e.g., 'social', 'analysis').

    Returns:
        Float 0.0-1.0 indicating match strength.
    """
    if not focus_type or focus_type not in SPECIALTY_PATTERNS:
        return 0.3  # Generalist agents get moderate match

    pattern = SPECIALTY_PATTERNS[focus_type]
    matches = len(pattern.findall(message))
    if matches == 0:
        return 0.1  # No match
    if matches == 1:
        return 0.6
    if matches == 2:
        return 0.8
    return 1.0  # Strong match


def compute_load_score(
    status: str,
    consecutive_failures: int,
) -> float:
    """
    Compute load score (higher = less loaded = better).

    Args:
        status: Agent status ('idle', 'busy', 'error', 'disabled').
        consecutive_failures: Number of consecutive failures.

    Returns:
        Float 0.0-1.0 (1.0 = idle and healthy).
    """
    if status == "disabled":
        return 0.0
    if status == "error":
        return 0.1
    if status == "busy":
        return 0.3

    # Idle — penalize for recent failures
    failure_penalty = min(consecutive_failures * 0.1, 0.5)
    return max(1.0 - failure_penalty, 0.2)


def compute_pheromone_score(records: list[dict[str, Any]]) -> float:
    """
    Compute pheromone score from performance records.

    Thin wrapper around ``aria_agents.scoring.compute_pheromone`` so that
    both the file-backed coordinator path and the DB-backed routing path
    share a single formula (A-01 unification).  The only difference is that
    routing.py calls this with records loaded from ``aria_engine.agent_state``
    rather than from the in-memory JSON file.

    Args:
        records: List of performance records.

    Returns:
        Float score between 0.0 and 1.0.
    """
    return _compute_pheromone(records)


class EngineRouter:
    """
    Routes messages to the best available agent based on multi-factor scoring.

    Usage:
        router = EngineRouter(db_engine)
        best_agent_id = await router.route_message(
            message="Deploy the latest build",
            available_agents=["main", "aria-devops", "aria-talk"],
        )
        # -> "aria-devops" (highest combined score)

        # After interaction:
        await router.update_scores(
            agent_id="aria-devops",
            success=True,
            duration_ms=1500,
        )
    """

    def __init__(self, db_engine: AsyncEngine):
        self._db_engine = db_engine
        # In-memory record cache per agent (synced to DB periodically)
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._total_invocations = 0

    async def initialize_patterns(self) -> int:
        """
        Load focus profile expertise_keywords from DB and compile SPECIALTY_PATTERNS.
        Idempotent — safe to call multiple times for cache refresh.
        Falls back to _FALLBACK_PATTERNS if DB unavailable or table empty.

        Returns:
            Number of focus profiles loaded from DB.
        """
        global SPECIALTY_PATTERNS
        try:
            from db.models import FocusProfileEntry
            from sqlalchemy import select as _select
            async with self._db_engine.begin() as conn:
                result = await conn.execute(
                    _select(
                        FocusProfileEntry.focus_id,
                        FocusProfileEntry.expertise_keywords,
                    ).where(FocusProfileEntry.enabled.is_(True))
                )
                rows = result.all()

            if not rows:
                logger.warning("initialize_patterns: no focus profiles in DB — keeping fallback")
                return 0

            new_patterns: dict[str, re.Pattern] = {}
            for row in rows:
                keywords: list[str] = row.expertise_keywords or []
                if not keywords:
                    continue
                pattern_str = "(" + "|".join(re.escape(k) for k in keywords) + ")"
                new_patterns[row.focus_id] = re.compile(pattern_str, re.IGNORECASE)

            SPECIALTY_PATTERNS = new_patterns
            logger.info("initialize_patterns: loaded %d focus profiles", len(new_patterns))
            return len(new_patterns)

        except Exception as exc:
            logger.warning("initialize_patterns failed (%s) — using fallback patterns", exc)
            SPECIALTY_PATTERNS = dict(_FALLBACK_PATTERNS)
            return 0

    async def route_message(
        self,
        message: str,
        available_agents: list[str],
    ) -> str:
        """
        Route a message to the best available agent.

        Considers:
        1. Pheromone score (historical performance, time-decayed)
        2. Specialty match (how well message fits agent's focus)
        3. Load (current status and consecutive failures)
        4. Recency (last 10 interaction success rate)

        Args:
            message: The input message to route.
            available_agents: List of agent_ids to choose from.

        Returns:
            The agent_id of the best match.

        Raises:
            EngineError: If no agents are available.
        """
        if not available_agents:
            raise EngineError("No available agents for routing")

        if len(available_agents) == 1:
            return available_agents[0]

        # Load agent state from DB
        agent_states = await self._load_agent_states(available_agents)

        scores: dict[str, float] = {}

        for agent_id in available_agents:
            state = agent_states.get(agent_id, {})

            # Factor 1: Pheromone score
            pheromone = float(state.get("pheromone_score", COLD_START_SCORE))

            # Factor 2: Specialty match
            focus_type = state.get("focus_type")
            specialty = compute_specialty_match(message, focus_type)

            # Factor 3: Load
            status = state.get("status", "idle")
            failures = state.get("consecutive_failures", 0)
            load = compute_load_score(status, failures)

            # Factor 4: Recency (last 10 interactions)
            records = self._records.get(agent_id, [])
            recent = records[-10:] if records else []
            if recent:
                recency = sum(
                    1 for r in recent if r.get("success")
                ) / len(recent)
            else:
                recency = 0.5  # Neutral for new agents

            # Combined score
            combined = (
                pheromone * WEIGHTS["pheromone"]
                + specialty * WEIGHTS["specialty"]
                + load * WEIGHTS["load"]
                + recency * WEIGHTS["recency"]
            )
            scores[agent_id] = combined

            logger.debug(
                "Route score %s: pheromone=%.3f specialty=%.3f "
                "load=%.3f recency=%.3f -> combined=%.3f",
                agent_id, pheromone, specialty, load, recency, combined,
            )

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        logger.info(
            "Routed message to %s (score=%.3f, runners-up: %s)",
            best,
            scores[best],
            ", ".join(
                f"{k}={v:.3f}"
                for k, v in sorted(
                    scores.items(), key=lambda x: x[1], reverse=True
                )
                if k != best
            )[:100],
        )

        return best

    async def get_fallback_chain(
        self,
        agent_id: str,
    ) -> list[dict[str, str]]:
        """
        Build a fallback chain for an agent: primary → fallback_model → parent.

        Returns a list of dicts with 'agent_id' and 'model' keys, ordered
        from primary to last-resort parent. Used by ChatEngine when the
        primary model returns an error.

        Example chain:
            [
                {"agent_id": "analyst", "model": "deepseek-free"},       # primary
                {"agent_id": "analyst", "model": "qwen3-next-free"},     # fallback_model
                {"agent_id": "aria",    "model": "qwen3-mlx"},           # parent
            ]
        """
        chain: list[dict[str, str]] = []
        visited: set[str] = set()

        current_id = agent_id
        while current_id and current_id not in visited:
            visited.add(current_id)
            state = await self._load_agent_states([current_id])
            info = state.get(current_id)
            if info is None:
                break

            model = info.get("model", "")
            fallback = info.get("fallback_model")
            parent_id = info.get("parent_agent_id")

            # Step 1: Primary model
            if model:
                chain.append({"agent_id": current_id, "model": model})

            # Step 2: Fallback model on the same agent
            if fallback and fallback != model:
                chain.append({"agent_id": current_id, "model": fallback})

            # Move to parent agent for the next iteration
            current_id = parent_id

        if not chain:
            chain.append({"agent_id": agent_id, "model": ""})

        logger.debug("Fallback chain for %s: %s", agent_id, chain)
        return chain

    async def update_scores(
        self,
        agent_id: str,
        success: bool,
        duration_ms: int,
        token_cost: float = 0.0,
    ) -> float:
        """
        Update pheromone scores after an interaction.

        Records the result, recomputes the agent's pheromone score,
        and persists to engine_agent_state.

        Args:
            agent_id: The agent that handled the interaction.
            success: Whether the interaction succeeded.
            duration_ms: Duration in milliseconds.
            token_cost: Normalized token cost (0.0-1.0).

        Returns:
            Updated pheromone score.
        """
        # Compute normalized speed score (faster = higher, cap at 30s)
        speed_score = max(0.0, 1.0 - (duration_ms / 30000))
        cost_score = max(0.0, 1.0 - min(token_cost, 1.0))

        record = {
            "success": success,
            "speed_score": round(speed_score, 3),
            "cost_score": round(cost_score, 3),
            "duration_ms": duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if agent_id not in self._records:
            self._records[agent_id] = []

        self._records[agent_id].append(record)
        self._total_invocations += 1

        # Trim old records
        if len(self._records[agent_id]) > MAX_RECORDS_PER_AGENT:
            self._records[agent_id] = self._records[agent_id][
                -MAX_RECORDS_PER_AGENT:
            ]

        # Recompute pheromone score
        new_score = compute_pheromone_score(self._records[agent_id])

        # Persist to DB
        await self._persist_score(agent_id, new_score)

        logger.debug(
            "Updated %s: %s (%dms) -> score=%.3f",
            agent_id,
            "OK" if success else "FAIL",
            duration_ms,
            new_score,
        )

        return new_score

    async def _load_agent_states(
        self,
        agent_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Load agent states from DB for routing decisions."""
        if not agent_ids:
            return {}

        async with self._db_engine.begin() as conn:
            result = await conn.execute(
                select(EngineAgentState)
                .where(
                    EngineAgentState.agent_id.in_(agent_ids),
                    EngineAgentState.enabled == True,
                )
            )
            rows = result.scalars().all()

        return {
            row.agent_id: {
                "agent_id": row.agent_id,
                "agent_type": row.agent_type,
                "focus_type": row.focus_type,
                "model": row.model,
                "fallback_model": row.fallback_model,
                "parent_agent_id": row.parent_agent_id,
                "status": row.status,
                "enabled": row.enabled,
                "skills": row.skills,
                "capabilities": row.capabilities,
                "consecutive_failures": row.consecutive_failures,
                "pheromone_score": row.pheromone_score,
                "last_active_at": row.last_active_at,
            }
            for row in rows
        }

    async def _persist_score(
        self,
        agent_id: str,
        score: float,
    ) -> None:
        """Persist pheromone score to agent_state table."""
        async with self._db_engine.begin() as conn:
            await conn.execute(
                update(EngineAgentState)
                .where(EngineAgentState.agent_id == agent_id)
                .values(
                    pheromone_score=round(score, 3),
                    updated_at=func.now(),
                )
            )

    async def get_routing_table(self) -> list[dict[str, Any]]:
        """Get current routing table with all agent scores and stats."""
        async with self._db_engine.begin() as conn:
            result = await conn.execute(
                select(EngineAgentState)
                .where(
                    EngineAgentState.status != "disabled",
                    EngineAgentState.enabled == True,
                )
                .order_by(EngineAgentState.pheromone_score.desc())
            )
            rows = result.scalars().all()

        table = []
        for row in rows:
            agent_id = row.agent_id
            records = self._records.get(agent_id, [])
            recent = records[-10:] if records else []
            success_rate = (
                sum(1 for r in recent if r.get("success")) / len(recent)
                if recent
                else None
            )

            table.append({
                "agent_id": agent_id,
                "display_name": row.display_name,
                "agent_type": row.agent_type or "agent",
                "focus_type": row.focus_type,
                "status": row.status,
                "skills": row.skills or [],
                "capabilities": row.capabilities or [],
                "pheromone_score": float(row.pheromone_score or 0.5),
                "consecutive_failures": row.consecutive_failures,
                "recent_success_rate": (
                    round(success_rate, 3) if success_rate is not None else None
                ),
                "total_records": len(records),
                "last_active_at": (
                    row.last_active_at.isoformat()
                    if row.last_active_at
                    else None
                ),
            })

        return table

    # ── Auto-escalation detection ────────────────────────────────────

    def assess_escalation(self, message: str) -> dict[str, Any]:
        """
        Assess whether a message should be escalated to multi-agent
        orchestration (roundtable or swarm).

        Uses keyword pattern matching against ESCALATION_PATTERNS.
        Returns a dict with:
          - should_escalate (bool): whether escalation is recommended
          - score (float): 0.0-1.0 escalation confidence
          - mode (str): "roundtable" or "swarm" recommendation
          - reason (str): human-readable explanation
          - matching_domains (list[str]): which specialty domains matched

        The score is NOT a hard gate — the caller decides whether to act.
        """
        score = 0.0
        reasons: list[str] = []

        # Check escalation patterns
        for pattern, weight in ESCALATION_PATTERNS:
            matches = pattern.findall(message)
            if matches:
                score += weight
                reasons.append(
                    f"pattern '{matches[0]}' (+{weight:.1f})"
                )

        # Check how many specialty domains the message touches
        matching_domains: list[str] = []
        for domain, pattern in SPECIALTY_PATTERNS.items():
            if pattern.search(message):
                matching_domains.append(domain)

        # Multiple domains → more likely to benefit from multiple agents
        if len(matching_domains) >= 2:
            domain_bonus = min(len(matching_domains) * 0.15, 0.4)
            score += domain_bonus
            reasons.append(
                f"cross-domain ({', '.join(matching_domains)}) (+{domain_bonus:.1f})"
            )

        # Message length heuristic: longer questions tend to be more complex
        word_count = len(message.split())
        if word_count > 50:
            length_bonus = min((word_count - 50) * 0.005, 0.2)
            score += length_bonus

        # Cap at 1.0
        score = min(score, 1.0)

        # Recommend mode: swarm for decisions, roundtable for analysis
        decision_keywords = re.compile(
            r"\b(should|decide|choose|pick|vote|yes or no)\b", re.I
        )
        mode = (
            "swarm" if decision_keywords.search(message) else "roundtable"
        )

        should_escalate = score >= ESCALATION_THRESHOLD

        logger.debug(
            "Escalation assessment: score=%.3f escalate=%s mode=%s reasons=%s",
            score, should_escalate, mode, reasons,
        )

        return {
            "should_escalate": should_escalate,
            "score": round(score, 3),
            "mode": mode,
            "reason": "; ".join(reasons) if reasons else "no escalation signals",
            "matching_domains": matching_domains,
        }
