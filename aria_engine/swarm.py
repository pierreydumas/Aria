"""
Swarm Orchestrator — Emergent collective intelligence engine.

Unlike Roundtable (structured rounds + central synthesizer), Swarm uses:
- Pheromone-weighted voting instead of a single synthesizer
- Stigmergy: agents share state via a "trail" — each agent reads all
  prior contributions and reinforces or diverges
- Iterative convergence: rounds continue until consensus threshold is met
  or max iterations reached
- No fixed roles — any agent can lead, follow, or dissent

Topology: fully-connected mesh (every agent sees every other agent's output).
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from db.models import EngineChatSession, EngineChatMessage, EngineAgentState

from aria_engine.agent_pool import AgentPool
from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from aria_engine.routing import EngineRouter

logger = logging.getLogger("aria.engine.swarm")

# Defaults
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_CONSENSUS_THRESHOLD = 0.7  # 70% agreement → converged
DEFAULT_AGENT_TIMEOUT = 60
DEFAULT_TOTAL_TIMEOUT = 600
MIN_AGENTS = 2
MAX_AGENTS = 12


@dataclass
class SwarmVote:
    """A single agent's contribution + vote in a swarm iteration."""
    agent_id: str
    iteration: int
    content: str
    vote: str          # "agree" | "disagree" | "extend" | "pivot"
    confidence: float  # 0.0 – 1.0
    duration_ms: int
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class SwarmResult:
    """Complete result of a swarm decision."""
    session_id: str
    topic: str
    participants: list[str]
    iterations: int
    votes: list[SwarmVote]
    consensus: str          # Final merged output
    consensus_score: float  # 0.0 – 1.0 (how converged)
    converged: bool         # True if consensus_threshold was met
    total_duration_ms: int
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def vote_count(self) -> int:
        return len(self.votes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "participants": self.participants,
            "iterations": self.iterations,
            "vote_count": self.vote_count,
            "consensus": self.consensus,
            "consensus_score": round(self.consensus_score, 3),
            "converged": self.converged,
            "total_duration_ms": self.total_duration_ms,
            "created_at": self.created_at.isoformat(),
            "votes": [
                {
                    "agent_id": v.agent_id,
                    "iteration": v.iteration,
                    "content": (
                        v.content[:200] + "..."
                        if len(v.content) > 200
                        else v.content
                    ),
                    "vote": v.vote,
                    "confidence": round(v.confidence, 3),
                    "duration_ms": v.duration_ms,
                }
                for v in self.votes
            ],
        }


class SwarmOrchestrator:
    """
    Emergent collective intelligence via pheromone-weighted voting.

    Unlike Roundtable's structured rounds, Swarm iterates until
    agents converge on a consensus or max_iterations is reached.

    Usage:
        swarm = SwarmOrchestrator(db_engine, agent_pool, router)
        result = await swarm.execute(
            topic="Should we refactor the auth module?",
            agent_ids=["analyst", "devops", "main"],
        )
        print(result.consensus, result.consensus_score)
    """

    def __init__(
        self,
        db_engine: AsyncEngine,
        agent_pool: AgentPool,
        router: EngineRouter,
    ):
        self._db_engine = db_engine
        self._pool = agent_pool
        self._router = router
        self._async_session = async_sessionmaker(
            db_engine, expire_on_commit=False,
        )

    async def execute(
        self,
        topic: str,
        agent_ids: list[str],
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        consensus_threshold: float = DEFAULT_CONSENSUS_THRESHOLD,
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        on_vote: Any = None,  # Optional async callback(SwarmVote)
    ) -> SwarmResult:
        """
        Execute a swarm decision process.

        Args:
            topic: The question/decision to process.
            agent_ids: Agent IDs to participate (min 2).
            max_iterations: Maximum voting rounds.
            consensus_threshold: Agreement level to stop early (0.0 – 1.0).
            agent_timeout: Seconds per agent per iteration.
            total_timeout: Max total seconds.
            on_vote: Optional async callback for each vote (for streaming).

        Returns:
            SwarmResult with consensus and convergence info.
        """
        if len(agent_ids) < MIN_AGENTS:
            raise EngineError(
                f"Swarm requires at least {MIN_AGENTS} participants"
            )
        if len(agent_ids) > MAX_AGENTS:
            raise EngineError(
                f"Swarm limited to {MAX_AGENTS} participants"
            )

        start = time.monotonic()
        session_id = str(uuid4())

        await self._create_session(session_id, topic, agent_ids)

        logger.info(
            "Swarm started: '%s' with %s (max %d iterations, threshold=%.2f)",
            topic[:80], agent_ids, max_iterations, consensus_threshold,
        )

        all_votes: list[SwarmVote] = []
        consensus_score = 0.0
        converged = False

        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - start
            if elapsed > total_timeout:
                logger.warning(
                    "Swarm total timeout after iteration %d (%.0fs)",
                    iteration - 1, elapsed,
                )
                break

            remaining = total_timeout - elapsed
            round_timeout = min(
                agent_timeout * len(agent_ids), remaining,
            )

            # Get pheromone scores for weighted influence
            pheromone_weights = await self._get_pheromone_weights(agent_ids)

            iteration_votes = await self._run_iteration(
                session_id=session_id,
                topic=topic,
                agent_ids=agent_ids,
                iteration=iteration,
                prior_votes=all_votes,
                pheromone_weights=pheromone_weights,
                agent_timeout=agent_timeout,
                round_timeout=round_timeout,
                on_vote=on_vote,
            )
            all_votes.extend(iteration_votes)

            # Calculate consensus from this iteration
            consensus_score = self._calculate_consensus(iteration_votes)

            logger.info(
                "Swarm iteration %d: %d votes, consensus=%.3f",
                iteration, len(iteration_votes), consensus_score,
            )

            if consensus_score >= consensus_threshold:
                converged = True
                logger.info(
                    "Swarm converged at iteration %d (score=%.3f >= %.3f)",
                    iteration, consensus_score, consensus_threshold,
                )
                break

        # Build consensus from pheromone-weighted votes
        elapsed_before_consensus = time.monotonic() - start
        if elapsed_before_consensus < total_timeout:
            consensus = await self._build_consensus(
                session_id=session_id,
                topic=topic,
                votes=all_votes,
                pheromone_weights=await self._get_pheromone_weights(agent_ids),
                timeout=min(agent_timeout * 2, total_timeout - elapsed_before_consensus),
            )
        else:
            consensus = self._fallback_consensus(all_votes)

        total_ms = int((time.monotonic() - start) * 1000)
        iterations_completed = max(
            (v.iteration for v in all_votes), default=0
        )

        result = SwarmResult(
            session_id=session_id,
            topic=topic,
            participants=agent_ids,
            iterations=iterations_completed,
            votes=all_votes,
            consensus=consensus,
            consensus_score=consensus_score,
            converged=converged,
            total_duration_ms=total_ms,
        )

        # Persist consensus
        await self._persist_message(
            session_id, "swarm", consensus, "consensus"
        )

        # Update pheromone scores — boost agents who voted with consensus
        for agent_id in agent_ids:
            agent_votes = [v for v in all_votes if v.agent_id == agent_id]
            if agent_votes:
                avg_confidence = sum(v.confidence for v in agent_votes) / len(agent_votes)
                avg_ms = sum(v.duration_ms for v in agent_votes) // len(agent_votes)
                await self._router.update_scores(
                    agent_id=agent_id,
                    success=avg_confidence > 0.5,
                    duration_ms=avg_ms,
                )

        logger.info(
            "Swarm complete: %d votes, %d iterations, consensus=%.3f, converged=%s, %.1fs",
            len(all_votes), iterations_completed, consensus_score,
            converged, total_ms / 1000,
        )

        return result

    async def _run_iteration(
        self,
        session_id: str,
        topic: str,
        agent_ids: list[str],
        iteration: int,
        prior_votes: list[SwarmVote],
        pheromone_weights: dict[str, float],
        agent_timeout: int,
        round_timeout: float,
        on_vote: Any = None,
    ) -> list[SwarmVote]:
        """Run one swarm iteration — all agents vote in parallel."""
        trail = self._build_trail(prior_votes, pheromone_weights)
        prompt = self._build_iteration_prompt(
            topic, iteration, trail, len(agent_ids)
        )

        # Collect results INSIDE each task so a single agent failure never
        # discards votes from agents that already completed, while keeping a
        # hard cap around the full task (model call + persistence).
        votes: list[SwarmVote | None] = [None] * len(agent_ids)

        async with asyncio.TaskGroup() as tg:
            for i, agent_id in enumerate(agent_ids):
                async def _collect(
                    idx: int = i, aid: str = agent_id,
                ) -> None:
                    try:
                        vote = await asyncio.wait_for(
                            self._get_agent_vote(
                                session_id=session_id,
                                agent_id=aid,
                                prompt=prompt,
                                iteration=iteration,
                                timeout=min(agent_timeout, round_timeout),
                            ),
                            timeout=round_timeout,
                        )
                        votes[idx] = vote
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Agent %s timed out in swarm iteration %d after %.2fs",
                            aid, iteration, round_timeout,
                        )
                    except Exception as e:
                        logger.warning(
                            "Agent %s vote error in iteration %d: %s",
                            aid, iteration, e,
                        )

                tg.create_task(
                    _collect(),
                    name=f"swarm-{iteration}-{agent_id}",
                )

        ordered_votes = [v for v in votes if v is not None]
        if on_vote is not None:
            for vote in ordered_votes:
                try:
                    await on_vote(vote)
                except Exception:
                    logger.exception("on_vote callback failed for agent")

        return ordered_votes

    async def _get_agent_vote(
        self,
        session_id: str,
        agent_id: str,
        prompt: str,
        iteration: int,
        timeout: int,
    ) -> SwarmVote:
        """Get a single agent's vote for this iteration."""
        start = time.monotonic()

        try:
            response = await asyncio.wait_for(
                self._pool.process_with_agent(
                    agent_id=agent_id,
                    message=prompt,
                    session_id=session_id,
                ),
                timeout=timeout,
            )
            content = (
                response.get("content", "")
                if isinstance(response, dict)
                else str(response)
            )
        except asyncio.TimeoutError:
            content = f"[{agent_id} timed out after {timeout}s]"
        except Exception as e:
            content = f"[{agent_id} error: {e}]"
            logger.warning(
                "Agent %s failed in swarm iteration %d: %s",
                agent_id, iteration, e,
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        # Parse vote signal from content
        vote_type, confidence = self._parse_vote(content)

        vote = SwarmVote(
            agent_id=agent_id,
            iteration=iteration,
            content=content,
            vote=vote_type,
            confidence=confidence,
            duration_ms=duration_ms,
        )

        await self._persist_message(
            session_id, agent_id, content, f"swarm-{iteration}",
        )

        return vote

    def _parse_vote(self, content: str) -> tuple[str, float]:
        """
        Parse vote direction and confidence from agent response.

        Agents are prompted to include [VOTE: agree|disagree|extend|pivot]
        and [CONFIDENCE: 0.0-1.0] in their response. Falls back to
        heuristic analysis if not found.
        """
        import re

        content_lower = content.lower()

        # Try explicit vote tag
        vote_match = re.search(
            r"\[vote:\s*(agree|disagree|extend|pivot)\]",
            content_lower,
        )
        vote_type = vote_match.group(1) if vote_match else "extend"

        # Try explicit confidence tag
        conf_match = re.search(
            r"\[confidence:\s*([\d.]+)\]",
            content_lower,
        )
        if conf_match:
            try:
                confidence = float(conf_match.group(1))
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                confidence = 0.5
        else:
            # Heuristic: estimate confidence from language
            confidence = 0.5
            strong_agree = len(re.findall(
                r"\b(agree|correct|exactly|definitely|absolutely|yes)\b",
                content_lower,
            ))
            strong_disagree = len(re.findall(
                r"\b(disagree|wrong|incorrect|no|however|but|instead)\b",
                content_lower,
            ))
            if strong_agree > strong_disagree:
                vote_type = "agree" if not vote_match else vote_type
                confidence = min(0.5 + strong_agree * 0.1, 0.9)
            elif strong_disagree > strong_agree:
                vote_type = "disagree" if not vote_match else vote_type
                confidence = min(0.5 + strong_disagree * 0.1, 0.9)

        return vote_type, round(confidence, 3)

    def _calculate_consensus(self, votes: list[SwarmVote]) -> float:
        """
        Calculate consensus score from an iteration's votes.

        Uses weighted agreement: agents who agree with the majority
        and have high confidence contribute more to the score.
        """
        if not votes:
            return 0.0

        # Count vote types
        vote_counts: dict[str, int] = {}
        for v in votes:
            vote_counts[v.vote] = vote_counts.get(v.vote, 0) + 1

        # Majority vote type
        majority_type = max(vote_counts, key=vote_counts.get)
        majority_count = vote_counts[majority_type]

        # Base consensus: fraction of agents in majority
        base = majority_count / len(votes)

        # Weight by confidence of majority voters
        majority_confidences = [
            v.confidence for v in votes if v.vote == majority_type
        ]
        avg_confidence = (
            sum(majority_confidences) / len(majority_confidences)
            if majority_confidences
            else 0.5
        )

        # Combined score: 60% agreement ratio + 40% confidence
        return base * 0.6 + avg_confidence * 0.4

    def _build_trail(
        self,
        votes: list[SwarmVote],
        pheromone_weights: dict[str, float],
    ) -> str:
        """
        Build the stigmergy trail — prior contributions weighted by
        pheromone scores. Higher-scored agents' contributions appear
        more prominently.
        """
        if not votes:
            return "(No prior swarm activity)"

        # Sort by pheromone weight (strongest trail first)
        weighted_votes = sorted(
            votes,
            key=lambda v: pheromone_weights.get(v.agent_id, 0.5),
            reverse=True,
        )

        lines = []
        for v in weighted_votes:
            weight = pheromone_weights.get(v.agent_id, 0.5)
            marker = "★" if weight > 0.7 else "●" if weight > 0.4 else "○"
            truncated = v.content[:300] if len(v.content) > 300 else v.content
            lines.append(
                f"{marker} [{v.agent_id} iter-{v.iteration} "
                f"vote={v.vote} conf={v.confidence:.2f}]: {truncated}"
            )

        return "\n\n".join(lines)

    def _build_iteration_prompt(
        self,
        topic: str,
        iteration: int,
        trail: str,
        participant_count: int,
    ) -> str:
        """Build the prompt for a swarm iteration."""
        if iteration == 1:
            phase = "EXPLORE — Share your initial position"
        elif iteration <= 3:
            phase = "CONVERGE — Read the trail. Reinforce what works, challenge what doesn't"
        else:
            phase = "FINALIZE — Build final consensus. Minimize dissent"

        return (
            f"SWARM DECISION (Iteration {iteration}, Phase: {phase})\n"
            f"Participants: {participant_count} agents\n\n"
            f"TOPIC: {topic}\n\n"
            f"PHEROMONE TRAIL (prior contributions, strongest first):\n"
            f"{trail}\n\n"
            f"YOUR TURN: Contribute your perspective.\n"
            f"You MUST include these tags in your response:\n"
            f"  [VOTE: agree|disagree|extend|pivot]\n"
            f"  [CONFIDENCE: 0.0-1.0]\n\n"
            f"Where:\n"
            f"  agree = concur with emerging consensus\n"
            f"  disagree = oppose the current direction\n"
            f"  extend = agree but add significant new information\n"
            f"  pivot = propose an entirely different approach\n"
        )

    async def _build_consensus(
        self,
        session_id: str,
        topic: str,
        votes: list[SwarmVote],
        pheromone_weights: dict[str, float],
        timeout: float,
    ) -> str:
        """
        Build consensus from all votes, weighted by pheromone scores.

        Uses the highest-scoring agent to synthesize, weighted by
        both pheromone score and vote confidence.
        """
        trail = self._build_trail(votes, pheromone_weights)

        # Pick the agent with highest combined score to do synthesis
        agent_scores: dict[str, float] = {}
        for v in votes:
            weight = pheromone_weights.get(v.agent_id, 0.5)
            combined = weight * 0.6 + v.confidence * 0.4
            if v.agent_id not in agent_scores or combined > agent_scores[v.agent_id]:
                agent_scores[v.agent_id] = combined

        synthesizer = max(agent_scores, key=agent_scores.get) if agent_scores else "main"

        prompt = (
            f"You are synthesizing a SWARM DECISION.\n\n"
            f"TOPIC: {topic}\n\n"
            f"FULL TRAIL ({len(votes)} votes from "
            f"{len(set(v.agent_id for v in votes))} agents):\n\n"
            f"{trail}\n\n"
            f"TASK: Merge the swarm's collective intelligence into a coherent "
            f"decision. Weight contributions by their pheromone markers "
            f"(★ = high authority, ● = medium, ○ = low). "
            f"Highlight the consensus position and note any significant "
            f"dissent. Be actionable and decisive."
        )

        try:
            response = await asyncio.wait_for(
                self._pool.process_with_agent(
                    agent_id=synthesizer,
                    message=prompt,
                    session_id=session_id,
                ),
                timeout=timeout,
            )
            return (
                response.get("content", "")
                if isinstance(response, dict)
                else str(response)
            )
        except Exception as e:
            logger.error("Swarm consensus synthesis failed: %s", e)
            return self._fallback_consensus(votes)

    def _fallback_consensus(self, votes: list[SwarmVote]) -> str:
        """Generate a simple consensus when LLM synthesis fails."""
        if not votes:
            return "(No votes to synthesize)"

        # Count final iteration votes
        last_iter = max(v.iteration for v in votes)
        final_votes = [v for v in votes if v.iteration == last_iter]

        vote_counts: dict[str, int] = {}
        for v in final_votes:
            vote_counts[v.vote] = vote_counts.get(v.vote, 0) + 1

        parts = [
            f"[Auto-consensus from {len(votes)} votes, "
            f"{len(set(v.agent_id for v in votes))} agents, "
            f"{last_iter} iterations]\n",
            f"Vote distribution: {vote_counts}\n",
        ]
        for v in final_votes:
            parts.append(
                f"- {v.agent_id} ({v.vote}, conf={v.confidence:.2f}): "
                f"{v.content[:300]}"
            )

        return "\n".join(parts)

    async def _get_pheromone_weights(
        self, agent_ids: list[str]
    ) -> dict[str, float]:
        """Load pheromone scores for agents from the routing table (ORM)."""
        weights: dict[str, float] = {}
        try:
            stmt = (
                select(
                    EngineAgentState.agent_id,
                    EngineAgentState.pheromone_score,
                )
                .where(EngineAgentState.agent_id.in_(agent_ids))
            )

            async with self._async_session() as session:
                result = await session.execute(stmt)
                for row in result:
                    weights[row.agent_id] = float(
                        row.pheromone_score or 0.5
                    )
        except Exception as e:
            logger.warning("Failed to load pheromone weights: %s", e)

        # Fill missing with cold-start score
        for aid in agent_ids:
            if aid not in weights:
                weights[aid] = 0.5

        return weights

    async def _create_session(
        self,
        session_id: str,
        topic: str,
        agent_ids: list[str],
    ) -> None:
        """Create a swarm session in the database (ORM)."""
        title = f"Swarm: {topic[:100]}"

        async with self._async_session() as session:
            async with session.begin():
                obj = EngineChatSession(
                    id=session_id,
                    title=title,
                    agent_id="swarm",
                    session_type="swarm",
                    metadata_json={"participants": agent_ids, "mode": "swarm", "origin": "swarm"},
                )
                session.add(obj)

    async def _persist_message(
        self,
        session_id: str,
        agent_id: str,
        content: str,
        role: str,
    ) -> None:
        """Persist a swarm message to the database (ORM)."""
        async with self._async_session() as session:
            async with session.begin():
                msg = EngineChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    metadata_json={"agent_id": agent_id},
                )
                session.add(msg)

    async def list_swarms(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List past swarm sessions (ORM)."""
        stmt = (
            select(
                EngineChatSession.id,
                EngineChatSession.title,
                EngineChatSession.metadata_json,
                EngineChatSession.created_at,
                func.count(EngineChatMessage.id).label("message_count"),
            )
            .outerjoin(
                EngineChatMessage,
                EngineChatMessage.session_id == EngineChatSession.id,
            )
            .where(EngineChatSession.session_type == "swarm")
            .group_by(
                EngineChatSession.id,
                EngineChatSession.title,
                EngineChatSession.metadata_json,
                EngineChatSession.created_at,
            )
            .order_by(EngineChatSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        async with self._async_session() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "session_id": str(row.id),
                "title": row.title,
                "participants": (
                    (row.metadata_json or {}).get("participants", [])
                    if isinstance(row.metadata_json, dict)
                    else []
                ),
                "message_count": row.message_count,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
