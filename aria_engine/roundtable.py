"""
Engine Roundtable — multi-agent collaborative discussion using TaskGroup.

Ports roundtable logic from aria_agents/coordinator.py with:
- Structured concurrency via asyncio.TaskGroup (Python 3.11+)
- Proper agent pool integration (S4-01)
- Session isolation per roundtable (S4-02)
- All turns persisted to chat_messages
- Per-agent timeout handling with ExceptionGroup
- Pheromone score updates after each contribution
- Configurable rounds, timeout, and synthesis
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncEngine

from db.models import EngineChatSession, EngineChatMessage

from aria_engine.agent_pool import AgentPool
from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from aria_engine.routing import EngineRouter
from aria_engine.session_isolation import AgentSessionScope

logger = logging.getLogger("aria.engine.roundtable")

# Defaults
DEFAULT_ROUNDS = 3
DEFAULT_AGENT_TIMEOUT = 60  # seconds per agent per round
DEFAULT_TOTAL_TIMEOUT = 300  # seconds for entire roundtable
MAX_CONTEXT_TOKENS = 2000   # Default fallback — overridden dynamically per session
SYNTHESIS_MAX_CONTEXT_CHARS = 12_000
SYNTHESIS_CHUNK_CHARS = 8_000
MAX_CONTEXT_TURNS = 40


@dataclass
class RoundtableTurn:
    """A single turn in a roundtable discussion."""

    agent_id: str
    round_number: int
    content: str
    duration_ms: int
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class RoundtableResult:
    """Complete result of a roundtable discussion."""

    session_id: str
    topic: str
    participants: list[str]
    rounds: int
    turns: list[RoundtableTurn]
    synthesis: str
    synthesizer_id: str
    total_duration_ms: int
    chunked_mode: bool = False
    chunk_count: int = 0
    chunk_notice: str | None = None
    chunk_kind: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "participants": self.participants,
            "rounds": self.rounds,
            "turn_count": self.turn_count,
            "synthesis": self.synthesis,
            "synthesizer_id": self.synthesizer_id,
            "total_duration_ms": self.total_duration_ms,
            "chunked_mode": self.chunked_mode,
            "chunk_count": self.chunk_count,
            "chunk_notice": self.chunk_notice,
            "chunk_kind": self.chunk_kind,
            "created_at": self.created_at.isoformat(),
            "turns": [
                {
                    "agent_id": t.agent_id,
                    "round": t.round_number,
                    "content": t.content[:200] + "..."
                    if len(t.content) > 200
                    else t.content,
                    "duration_ms": t.duration_ms,
                }
                for t in self.turns
            ],
        }


class Roundtable:
    """
    Multi-agent collaborative discussion engine.

    Orchestrates a structured discussion where multiple agents
    contribute to a topic across several rounds, with each agent
    seeing prior responses for context. A synthesizer agent
    produces the final combined answer.

    Usage:
        roundtable = Roundtable(db_engine, agent_pool, router)

        result = await roundtable.discuss(
            topic="Design the new caching strategy",
            agent_ids=["aria-devops", "aria-analyst", "aria-creator"],
            rounds=3,
            synthesizer_id="main",
        )
        # result.synthesis contains the final combined answer
        # result.turns contains all individual contributions
    """

    def __init__(
        self,
        db_engine: AsyncEngine,
        agent_pool: AgentPool,
        router: EngineRouter,
    ):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self._db_engine = db_engine
        self._pool = agent_pool
        self._router = router
        self._async_session = async_sessionmaker(
            db_engine, expire_on_commit=False,
        )

    async def discuss(
        self,
        topic: str,
        agent_ids: list[str] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        synthesizer_id: str = "main",
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        on_turn: Any = None,  # Optional async callback(RoundtableTurn)
        max_agents: int = 5,     # hard cap — token economy enforcement
    ) -> RoundtableResult:
        """
        Run a multi-round collaborative discussion.

        Each round sends the topic + prior context to each agent.
        After all rounds, a synthesizer agent combines the insights.

        Args:
            topic: Discussion topic / question.
            agent_ids: List of agents to participate.
            rounds: Number of discussion rounds (default 3).
            synthesizer_id: Agent to produce the final synthesis.
            agent_timeout: Seconds per agent response (default 60).
            total_timeout: Max total seconds (default 300).
            on_turn: Optional async callback invoked after each agent turn
                     (for WebSocket streaming).

        Returns:
            RoundtableResult with all turns and final synthesis.

        Raises:
            EngineError: If fewer than 2 agents, or total timeout exceeded.
        """
        # Auto-select agents if not explicitly provided
        if agent_ids is None:
            agent_ids = self._select_agents_for_topic(topic, max_agents)
            if len(agent_ids) < 2:
                raise EngineError(
                    f"Not enough agents available for roundtable on: '{topic[:80]}'"
                )

        # Enforce agent cap even for explicit lists — prevents accidental token explosion
        if len(agent_ids) > max_agents:
            logger.warning(
                "Roundtable: truncating %d\u2192%d agents (max_agents=%d)",
                len(agent_ids), max_agents, max_agents,
            )
            agent_ids = agent_ids[:max_agents]

        if len(agent_ids) < 2:
            raise EngineError(
                "Roundtable requires at least 2 participants"
            )

        start = time.monotonic()
        session_id = str(uuid4())

        # Create a roundtable session in the DB
        await self._create_session(session_id, topic, agent_ids)

        logger.info(
            "Roundtable started: '%s' with %s (%d rounds)",
            topic[:80],
            agent_ids,
            rounds,
        )

        turns: list[RoundtableTurn] = []

        for round_num in range(1, rounds + 1):
            # Check total timeout
            elapsed = time.monotonic() - start
            if elapsed > total_timeout:
                logger.warning(
                    "Roundtable total timeout after round %d (%.0fs)",
                    round_num - 1,
                    elapsed,
                )
                break

            remaining = total_timeout - elapsed
            round_timeout = min(
                agent_timeout * len(agent_ids),
                remaining,
            )

            round_turns = await self._run_round(
                session_id=session_id,
                topic=topic,
                agent_ids=agent_ids,
                round_number=round_num,
                prior_turns=turns,
                agent_timeout=agent_timeout,
                round_timeout=round_timeout,
            )
            turns.extend(round_turns)

            # Invoke per-turn callback for WS streaming
            if on_turn is not None:
                for t in round_turns:
                    try:
                        await on_turn(t)
                    except Exception as e:
                        logger.exception("on_turn callback failed")

        # Synthesis round
        elapsed = time.monotonic() - start
        if elapsed < total_timeout:
            synthesis, synth_ms, synthesis_chunk_meta = await self._synthesize(
                session_id=session_id,
                topic=topic,
                turns=turns,
                synthesizer_id=synthesizer_id,
                timeout=min(agent_timeout * 2, total_timeout - elapsed),
            )
        else:
            synthesis = self._fallback_synthesis(turns)
            synth_ms = 0
            synthesis_chunk_meta = None

        total_ms = int((time.monotonic() - start) * 1000)

        result = RoundtableResult(
            session_id=session_id,
            topic=topic,
            participants=agent_ids,
            rounds=rounds,
            turns=turns,
            synthesis=synthesis,
            synthesizer_id=synthesizer_id,
            total_duration_ms=total_ms,
            chunked_mode=bool(synthesis_chunk_meta),
            chunk_count=(
                int(synthesis_chunk_meta.get("chunk_count", 0))
                if synthesis_chunk_meta
                else 0
            ),
            chunk_notice=(
                synthesis_chunk_meta.get("notice")
                if synthesis_chunk_meta
                else None
            ),
            chunk_kind=(
                synthesis_chunk_meta.get("kind")
                if synthesis_chunk_meta
                else None
            ),
        )

        # Persist synthesis as final message
        synthesis_meta = {"agent_id": synthesizer_id}
        if synthesis_chunk_meta:
            synthesis_meta.update(
                {
                    "chunked_mode": True,
                    "chunk_count": int(synthesis_chunk_meta.get("chunk_count", 0)),
                    "chunk_notice": synthesis_chunk_meta.get("notice"),
                    "chunk_kind": synthesis_chunk_meta.get("kind"),
                }
            )
        await self._persist_message(
            session_id,
            synthesizer_id,
            synthesis,
            "synthesis",
            metadata=synthesis_meta,
        )

        # Update pheromone scores for all participants
        for agent_id in agent_ids:
            agent_turns = [
                t for t in turns if t.agent_id == agent_id
            ]
            if agent_turns:
                avg_ms = sum(t.duration_ms for t in agent_turns) // len(
                    agent_turns
                )
                await self._router.update_scores(
                    agent_id=agent_id,
                    success=True,
                    duration_ms=avg_ms,
                )

        logger.info(
            "Roundtable complete: %d turns, %d agents, %.1fs",
            len(turns),
            len(agent_ids),
            total_ms / 1000,
        )

        return result

    def _select_agents_for_topic(
        self,
        topic: str,
        max_agents: int = 5,
    ) -> list[str]:
        """
        Auto-select agents by focus keyword match against topic.

        Selection rules:
            1. Always include >=1 L1 (orchestrator tier) agent by pheromone score
            2. Fill remaining slots with L2 agents scoring > 0.0 (sorted desc)
            3. Include L3 agents only if score > 0.4 AND slot available
            4. Hard cap at max_agents

        Returns:
            Ordered list of agent_ids (L1 first, then L2, then L3 by score).
        """
        from aria_engine.routing import compute_specialty_match

        try:
            all_agents = list(self._pool._agents.values())
        except Exception as exc:
            logger.warning("_select_agents_for_topic: could not list agents: %s", exc)
            return []

        l1_entries, l2_entries, l3_entries = [], [], []

        for agent in all_agents:
            if getattr(agent, "status", "offline") in ("offline", "disabled", "error"):
                continue
            fp = getattr(agent, "_focus_profile", None)
            delegation_level = (fp.get("delegation_level") if fp else None) or 2
            score = compute_specialty_match(topic, agent.focus_type or "")

            entry = (agent.agent_id, score, delegation_level)
            if delegation_level == 1:
                l1_entries.append(entry)
            elif delegation_level == 2:
                l2_entries.append(entry)
            else:
                l3_entries.append(entry)

        # Sort by score (higher = better match)
        l1_entries.sort(key=lambda x: x[1], reverse=True)
        l2_entries.sort(key=lambda x: x[1], reverse=True)
        l3_entries.sort(key=lambda x: x[1], reverse=True)

        selected: list[str] = []

        # Always include top L1 orchestrator if available
        if l1_entries:
            selected.append(l1_entries[0][0])

        # Fill L2 slots with scoring agents
        for agent_id, score, _ in l2_entries:
            if len(selected) >= max_agents:
                break
            if score > 0.0:
                selected.append(agent_id)

        # Include L3 only if score is high and slots remain
        for agent_id, score, _ in l3_entries:
            if len(selected) >= max_agents:
                break
            if score > 0.4:
                selected.append(agent_id)

        logger.debug(
            "_select_agents_for_topic: topic='%s' -> selected=%s",
            topic[:60], selected,
        )
        return selected

    async def _run_round(
        self,
        session_id: str,
        topic: str,
        agent_ids: list[str],
        round_number: int,
        prior_turns: list[RoundtableTurn],
        agent_timeout: int,
        round_timeout: float,
    ) -> list[RoundtableTurn]:
        """Run one round of discussion, collecting all agent responses."""
        # Compute dynamic context cap = min of all participants' token budgets
        # Ensures context never exceeds what the tightest-budget agent can receive
        participating_agents = [
            self._pool.get_agent(aid)
            for aid in agent_ids
        ]
        participant_budgets = [
            agent._focus_profile.get("token_budget_hint", MAX_CONTEXT_TOKENS)
            for agent in participating_agents
            if agent is not None and getattr(agent, "_focus_profile", None)
        ]
        context_token_cap = min(participant_budgets) if participant_budgets else MAX_CONTEXT_TOKENS
        # Approximate chars-per-agent from token cap (1 token ~ 4 chars, split across turns)
        max_per_agent_chars = max(100, context_token_cap // max(1, len(agent_ids)))

        context = self._build_context(prior_turns, max_per_agent=max_per_agent_chars)

        prompt = self._build_round_prompt(
            topic, round_number, context, len(agent_ids)
        )

        # Run all agents in parallel using TaskGroup (structured concurrency).
        # Keep partial results from completed agents, but bound the entire
        # collection task by round_timeout so persistence/callback work cannot
        # stall the round indefinitely.
        turns: list[RoundtableTurn | None] = [None] * len(agent_ids)

        async with asyncio.TaskGroup() as tg:
            for i, agent_id in enumerate(agent_ids):
                async def _collect(
                    idx: int = i, aid: str = agent_id,
                ) -> None:
                    try:
                        turn = await asyncio.wait_for(
                            self._get_agent_response(
                                session_id=session_id,
                                agent_id=aid,
                                prompt=prompt,
                                round_number=round_number,
                                timeout=min(agent_timeout, round_timeout),
                            ),
                            timeout=round_timeout,
                        )
                        turns[idx] = turn
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Agent %s timed out in round %d after %.2fs",
                            aid, round_number, round_timeout,
                        )
                    except Exception as e:
                        logger.warning(
                            "Agent %s response error in round %d: %s",
                            aid, round_number, e,
                        )

                tg.create_task(
                    _collect(),
                    name=f"round-{round_number}-{agent_id}",
                )

        turns = [t for t in turns if t is not None]  # type: ignore[assignment]

        logger.debug(
            "Round %d: %d/%d responses",
            round_number,
            len(turns),
            len(agent_ids),
        )

        return turns

    async def _get_agent_response(
        self,
        session_id: str,
        agent_id: str,
        prompt: str,
        round_number: int,
        timeout: int,
    ) -> RoundtableTurn:
        """Get a single agent's response with timeout."""
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
            content = response.get("content", "") if isinstance(response, dict) else str(response)
        except asyncio.TimeoutError:
            content = f"[{agent_id} timed out after {timeout}s]"
        except Exception as e:
            content = f"[{agent_id} error: {e}]"
            logger.warning("Agent %s failed in round %d: %s", agent_id, round_number, e)

        duration_ms = int((time.monotonic() - start) * 1000)

        turn = RoundtableTurn(
            agent_id=agent_id,
            round_number=round_number,
            content=content,
            duration_ms=duration_ms,
        )

        # Persist to DB
        await self._persist_message(
            session_id,
            agent_id,
            content,
            f"round-{round_number}",
        )

        return turn

    async def _synthesize(
        self,
        session_id: str,
        topic: str,
        turns: list[RoundtableTurn],
        synthesizer_id: str,
        timeout: float,
    ) -> tuple[str, int, dict[str, Any] | None]:
        """
        Synthesize all discussion turns into a final answer.

        Returns:
            Tuple of (synthesis text, duration_ms, chunk metadata).
        """
        context = self._build_context(turns, max_per_agent=500)
        context_for_prompt = context
        chunk_meta: dict[str, Any] | None = None

        if len(context) > SYNTHESIS_MAX_CONTEXT_CHARS:
            logger.info(
                "Roundtable synthesis context too large (%d chars) — chunking first",
                len(context),
            )
            context_for_prompt, chunk_count = await self._summarize_large_context_for_synthesis(
                session_id=session_id,
                topic=topic,
                context=context,
                synthesizer_id=synthesizer_id,
                timeout=timeout,
            )
            if chunk_count > 1:
                chunk_meta = {
                    "kind": "roundtable_synthesis",
                    "chunk_count": int(chunk_count),
                    "notice": (
                        "Chunked synthesis mode activated: "
                        f"summarized {chunk_count} context chunks before final synthesis."
                    ),
                }

        prompt = (
            f"You are the synthesizer for a roundtable discussion.\n\n"
            f"TOPIC: {topic}\n\n"
            f"DISCUSSION ({len(turns)} contributions from "
            f"{len(set(t.agent_id for t in turns))} agents):\n\n"
            f"{context_for_prompt}\n\n"
            f"TASK: Synthesize the key insights into a coherent, "
            f"actionable answer. Highlight areas of agreement and "
            f"note any important disagreements. Be concise but thorough."
        )

        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._pool.process_with_agent(
                    agent_id=synthesizer_id,
                    message=prompt,
                    session_id=session_id,
                ),
                timeout=timeout,
            )
            synthesis = response.get("content", "") if isinstance(response, dict) else str(response)
        except asyncio.TimeoutError:
            synthesis = self._fallback_synthesis(turns)
        except Exception as e:
            logger.error("Synthesis failed: %s", e)
            synthesis = self._fallback_synthesis(turns)

        duration_ms = int((time.monotonic() - start) * 1000)
        return synthesis, duration_ms, chunk_meta

    def _build_context(
        self,
        turns: list[RoundtableTurn],
        max_per_agent: int = 300,
    ) -> str:
        """Build context string from prior turns."""
        if not turns:
            return "(No prior discussion)"

        if len(turns) > MAX_CONTEXT_TURNS:
            turns = turns[-MAX_CONTEXT_TURNS:]

        lines = []
        for t in turns:
            content = t.content
            if len(content) > max_per_agent:
                content = content[:max_per_agent] + "..."
            lines.append(
                f"[Round {t.round_number}] {t.agent_id}: {content}"
            )

        return "\n\n".join(lines)

    @staticmethod
    def _chunk_text(text: str, max_chars: int) -> list[str]:
        """Split text into stable chunks without breaking every sentence."""
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for part in text.split("\n\n"):
            block = part.strip()
            if not block:
                continue
            block_len = len(block) + 2
            if current and current_len + block_len > max_chars:
                chunks.append("\n\n".join(current))
                current = [block]
                current_len = len(block)
            else:
                current.append(block)
                current_len += block_len

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    async def _summarize_large_context_for_synthesis(
        self,
        session_id: str,
        topic: str,
        context: str,
        synthesizer_id: str,
        timeout: float,
    ) -> tuple[str, int]:
        """Summarize oversized roundtable context chunk-by-chunk before final synthesis."""
        chunks = self._chunk_text(context, SYNTHESIS_CHUNK_CHARS)
        if len(chunks) <= 1:
            return context, len(chunks)

        per_chunk_timeout = max(20.0, float(timeout) / float(len(chunks) + 1))
        summaries: list[str] = []

        for idx, chunk in enumerate(chunks, start=1):
            chunk_prompt = (
                f"Roundtable context chunk {idx}/{len(chunks)} for topic: {topic}\n\n"
                "Summarize this chunk into 6-10 concise bullets preserving: "
                "key claims, agreements, disagreements, and action ideas. "
                "Keep agent identifiers and round references when present.\n\n"
                f"CHUNK:\n{chunk}"
            )
            try:
                response = await asyncio.wait_for(
                    self._pool.process_with_agent(
                        agent_id=synthesizer_id,
                        message=chunk_prompt,
                        session_id=session_id,
                    ),
                    timeout=per_chunk_timeout,
                )
                summary = (
                    response.get("content", "")
                    if isinstance(response, dict)
                    else str(response)
                )
            except Exception as exc:
                logger.warning(
                    "Roundtable chunk summary failed (%d/%d): %s",
                    idx,
                    len(chunks),
                    exc,
                )
                summary = chunk[:1200]

            summaries.append(f"[Chunk {idx}]\n{summary}")

        return "\n\n".join(summaries), len(chunks)

    def _build_round_prompt(
        self,
        topic: str,
        round_number: int,
        context: str,
        participant_count: int,
    ) -> str:
        """Build the prompt for a discussion round."""
        if round_number == 1:
            phase = "EXPLORE — Share your initial analysis"
        elif round_number == 2:
            phase = "WORK — Build on others' ideas"
        else:
            phase = "VALIDATE — Critique and refine"

        return (
            f"ROUNDTABLE DISCUSSION (Round {round_number}, Phase: {phase})\n"
            f"Participants: {participant_count} agents\n\n"
            f"TOPIC: {topic}\n\n"
            f"PRIOR DISCUSSION:\n{context}\n\n"
            f"YOUR TURN: Contribute your perspective. "
            f"{'Introduce your analysis.' if round_number == 1 else ''}"
            f"{'Build on what others said.' if round_number == 2 else ''}"
            f"{'Identify gaps and finalize.' if round_number >= 3 else ''}"
        )

    def _fallback_synthesis(self, turns: list[RoundtableTurn]) -> str:
        """Fallback synthesis when the synthesizer agent fails."""
        if not turns:
            return "(No discussion content to synthesize)"

        agents = set(t.agent_id for t in turns)
        last_round = max(t.round_number for t in turns)
        final_turns = [t for t in turns if t.round_number == last_round]

        parts = [
            f"[Auto-synthesis from {len(turns)} turns, "
            f"{len(agents)} agents, {last_round} rounds]\n"
        ]
        for t in final_turns:
            parts.append(f"- {t.agent_id}: {t.content[:300]}")

        return "\n".join(parts)

    async def _create_session(
        self,
        session_id: str,
        topic: str,
        agent_ids: list[str],
    ) -> None:
        """Create a roundtable session in the DB (ORM)."""
        title = f"Roundtable: {topic[:100]}"

        async with self._async_session() as session:
            async with session.begin():
                obj = EngineChatSession(
                    id=session_id,
                    title=title,
                    agent_id="roundtable",
                    session_type="roundtable",
                    metadata_json={"participants": agent_ids, "origin": "roundtable"},
                )
                session.add(obj)

    async def _persist_message(
        self,
        session_id: str,
        agent_id: str,
        content: str,
        role: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a roundtable message to chat_messages (ORM)."""
        async with self._async_session() as session:
            async with session.begin():
                msg_meta = {"agent_id": agent_id}
                if metadata:
                    msg_meta.update(metadata)
                msg = EngineChatMessage(
                    session_id=session_id,
                    role=role,
                    content=content,
                    metadata_json=msg_meta,
                )
                session.add(msg)

    async def list_roundtables(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent roundtable sessions (ORM)."""
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
            .where(EngineChatSession.session_type == "roundtable")
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
                "participants": (row.metadata_json or {}).get(
                    "participants", []
                ),
                "message_count": row.message_count,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
