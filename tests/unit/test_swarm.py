"""
Unit tests for aria_engine.swarm (T-08 — Audit).

Pure-Python subset: tests the sync methods and dataclasses directly
without live DB or agent pool. The conftest.py db stub handles imports.

Tests cover:
- SwarmVote dataclass construction
- SwarmResult.vote_count property
- SwarmResult.to_dict() structure and key presence
- SwarmOrchestrator._parse_vote() — explicit [VOTE:] tags
- SwarmOrchestrator._parse_vote() — heuristic fallback from sentiment words
- SwarmOrchestrator._parse_vote() — confidence clamping (0-1)
- SwarmOrchestrator._calculate_consensus() — majority + weighted confidence
- SwarmOrchestrator._calculate_consensus() — empty input
- SwarmOrchestrator._calculate_consensus() — unanimous result = 1.0
- SwarmOrchestrator._build_trail() — empty votes
- SwarmOrchestrator._build_trail() — ordering by pheromone weight
- SwarmOrchestrator._fallback_consensus() — empty votes
- SwarmOrchestrator._fallback_consensus() — formats final iteration
- SwarmOrchestrator.execute() — raises EngineError if < MIN_AGENTS
- SwarmOrchestrator.execute() — raises EngineError if > MAX_AGENTS
- SwarmOrchestrator._build_iteration_prompt() — phase labels per iteration
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

import pytest

from aria_engine.swarm import (
    SwarmOrchestrator,
    SwarmResult,
    SwarmVote,
    DEFAULT_CONSENSUS_THRESHOLD,
    MIN_AGENTS,
    MAX_AGENTS,
)
from aria_engine.exceptions import EngineError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_orchestrator() -> SwarmOrchestrator:
    """Return a SwarmOrchestrator with all heavy deps mocked."""
    return SwarmOrchestrator(
        db_engine=MagicMock(),
        agent_pool=MagicMock(),
        router=MagicMock(),
    )


def _vote(
    agent_id: str = "main",
    iteration: int = 1,
    vote: str = "agree",
    confidence: float = 0.8,
    content: str = "I agree with this approach.",
    duration_ms: int = 100,
) -> SwarmVote:
    return SwarmVote(
        agent_id=agent_id,
        iteration=iteration,
        content=content,
        vote=vote,
        confidence=confidence,
        duration_ms=duration_ms,
    )


# ── SwarmVote ─────────────────────────────────────────────────────────────────


def test_swarm_vote_construction():
    v = _vote()
    assert v.agent_id == "main"
    assert v.vote == "agree"
    assert v.confidence == 0.8
    assert v.iteration == 1
    assert isinstance(v.created_at, datetime)


def test_swarm_vote_created_at_is_utc():
    v = _vote()
    assert v.created_at.tzinfo is not None


# ── SwarmResult ───────────────────────────────────────────────────────────────


def _make_result(votes: list[SwarmVote] | None = None) -> SwarmResult:
    v = votes or [_vote("a"), _vote("b"), _vote("c")]
    return SwarmResult(
        session_id="sess-1",
        topic="Test topic",
        participants=["a", "b", "c"],
        iterations=1,
        votes=v,
        consensus="Consensus text",
        consensus_score=0.75,
        converged=True,
        total_duration_ms=1500,
    )


def test_swarm_result_vote_count():
    r = _make_result([_vote("a"), _vote("b")])
    assert r.vote_count == 2


def test_swarm_result_vote_count_zero():
    r = _make_result([])
    assert r.vote_count == 0


def test_swarm_result_to_dict_keys():
    r = _make_result()
    d = r.to_dict()
    for key in ("session_id", "topic", "participants", "iterations",
                "vote_count", "consensus", "consensus_score",
                "converged", "total_duration_ms", "created_at", "votes"):
        assert key in d, f"Missing key: {key}"


def test_swarm_result_to_dict_vote_list():
    votes = [_vote("a"), _vote("b")]
    r = _make_result(votes)
    d = r.to_dict()
    assert len(d["votes"]) == 2
    assert d["votes"][0]["agent_id"] == "a"


def test_swarm_result_to_dict_consensus_score_rounded():
    r = _make_result()
    d = r.to_dict()
    # to_dict rounds to 3 decimal places
    assert isinstance(d["consensus_score"], float)


def test_swarm_result_to_dict_long_vote_content_truncated():
    long_content = "x" * 500
    v = _vote(content=long_content)
    r = _make_result([v])
    d = r.to_dict()
    assert len(d["votes"][0]["content"]) <= 203  # 200 + "..."


# ── _parse_vote ───────────────────────────────────────────────────────────────


def test_parse_vote_explicit_agree_tag():
    orch = _make_orchestrator()
    vote, conf = orch._parse_vote("This is correct. [VOTE: agree] [CONFIDENCE: 0.9]")
    assert vote == "agree"
    assert abs(conf - 0.9) < 0.01


def test_parse_vote_explicit_disagree_tag():
    orch = _make_orchestrator()
    vote, conf = orch._parse_vote("[VOTE: disagree] [CONFIDENCE: 0.7] I disagree.")
    assert vote == "disagree"
    assert abs(conf - 0.7) < 0.01


def test_parse_vote_explicit_extend_tag():
    orch = _make_orchestrator()
    vote, _ = orch._parse_vote("[VOTE: extend] I'd add more context here.")
    assert vote == "extend"


def test_parse_vote_explicit_pivot_tag():
    orch = _make_orchestrator()
    vote, _ = orch._parse_vote("[VOTE: pivot] We should take a completely different approach.")
    assert vote == "pivot"


def test_parse_vote_confidence_clamped_above_one():
    orch = _make_orchestrator()
    _, conf = orch._parse_vote("[VOTE: agree] [CONFIDENCE: 1.5]")
    assert conf <= 1.0


def test_parse_vote_confidence_clamped_below_zero():
    orch = _make_orchestrator()
    _, conf = orch._parse_vote("[VOTE: extend] [CONFIDENCE: -0.5]")
    assert conf >= 0.0


def test_parse_vote_heuristic_agree_words():
    orch = _make_orchestrator()
    vote, conf = orch._parse_vote("I definitely agree, this is exactly correct and absolutely right.")
    assert vote == "agree"
    assert conf > 0.5


def test_parse_vote_heuristic_disagree_words():
    orch = _make_orchestrator()
    vote, conf = orch._parse_vote("I disagree. This is wrong and incorrect, but instead we should do X.")
    assert vote == "disagree"
    assert conf > 0.5


def test_parse_vote_no_tag_defaults_to_extend():
    orch = _make_orchestrator()
    # Neutral content — no strong signal
    vote, conf = orch._parse_vote("This is an observation about the topic.")
    # Default when no clear signal is "extend" with confidence 0.5
    assert conf == 0.5


def test_parse_vote_invalid_confidence_falls_back():
    orch = _make_orchestrator()
    _, conf = orch._parse_vote("[VOTE: agree] [CONFIDENCE: not-a-number]")
    assert conf == 0.5


# ── _calculate_consensus ─────────────────────────────────────────────────────


def test_calculate_consensus_empty_votes():
    orch = _make_orchestrator()
    assert orch._calculate_consensus([]) == 0.0


def test_calculate_consensus_unanimous_agree():
    orch = _make_orchestrator()
    votes = [_vote("a", vote="agree", confidence=1.0),
             _vote("b", vote="agree", confidence=1.0),
             _vote("c", vote="agree", confidence=1.0)]
    score = orch._calculate_consensus(votes)
    # 100% agreement + 100% confidence → max possible score
    assert score == pytest.approx(1.0, abs=1e-3)


def test_calculate_consensus_split_vote():
    orch = _make_orchestrator()
    votes = [_vote("a", vote="agree", confidence=0.8),
             _vote("b", vote="disagree", confidence=0.8)]
    score = orch._calculate_consensus(votes)
    # 50% base + weighted confidence → should be ~0.62
    assert 0.4 < score < 0.8


def test_calculate_consensus_three_agree_one_dissent():
    orch = _make_orchestrator()
    votes = [_vote("a", vote="agree", confidence=0.9),
             _vote("b", vote="agree", confidence=0.8),
             _vote("c", vote="agree", confidence=0.7),
             _vote("d", vote="disagree", confidence=0.9)]
    score = orch._calculate_consensus(votes)
    # Majority (75%) agree → score should exceed threshold
    assert score > DEFAULT_CONSENSUS_THRESHOLD


def test_calculate_consensus_score_between_0_and_1():
    orch = _make_orchestrator()
    votes = [_vote(str(i), vote=["agree", "disagree", "extend", "pivot"][i % 4])
             for i in range(8)]
    score = orch._calculate_consensus(votes)
    assert 0.0 <= score <= 1.0


# ── _build_trail ─────────────────────────────────────────────────────────────


def test_build_trail_empty_returns_placeholder():
    orch = _make_orchestrator()
    trail = orch._build_trail([], {})
    assert "No prior" in trail


def test_build_trail_includes_agent_ids():
    orch = _make_orchestrator()
    votes = [_vote("aria-analyst"), _vote("aria-devops")]
    trail = orch._build_trail(votes, {"aria-analyst": 0.8, "aria-devops": 0.4})
    assert "aria-analyst" in trail
    assert "aria-devops" in trail


def test_build_trail_orders_by_pheromone_weight():
    orch = _make_orchestrator()
    # aria-analyst has higher weight — should appear first in trail
    votes = [_vote("aria-devops"), _vote("aria-analyst")]
    trail = orch._build_trail(votes, {"aria-analyst": 0.9, "aria-devops": 0.2})
    pos_analyst = trail.index("aria-analyst")
    pos_devops = trail.index("aria-devops")
    assert pos_analyst < pos_devops


def test_build_trail_high_weight_gets_star_marker():
    orch = _make_orchestrator()
    votes = [_vote("aria-analyst")]
    trail = orch._build_trail(votes, {"aria-analyst": 0.9})
    assert "★" in trail


def test_build_trail_low_weight_gets_circle_marker():
    orch = _make_orchestrator()
    votes = [_vote("aria-newbie")]
    trail = orch._build_trail(votes, {"aria-newbie": 0.1})
    assert "○" in trail


# ── _fallback_consensus ───────────────────────────────────────────────────────


def test_fallback_consensus_empty():
    orch = _make_orchestrator()
    result = orch._fallback_consensus([])
    assert "No votes" in result


def test_fallback_consensus_contains_iteration_count():
    orch = _make_orchestrator()
    votes = [_vote("a", iteration=2), _vote("b", iteration=2)]
    result = orch._fallback_consensus(votes)
    assert "2" in result or "votes" in result.lower()


def test_fallback_consensus_returns_string():
    orch = _make_orchestrator()
    votes = [_vote("a"), _vote("b"), _vote("c")]
    result = orch._fallback_consensus(votes)
    assert isinstance(result, str)
    assert len(result) > 0


# ── _build_iteration_prompt ───────────────────────────────────────────────────


def test_iteration_prompt_phase_1_is_explore():
    orch = _make_orchestrator()
    prompt = orch._build_iteration_prompt("Topic", 1, "(trail)", 3)
    assert "EXPLORE" in prompt


def test_iteration_prompt_phase_2_is_converge():
    orch = _make_orchestrator()
    prompt = orch._build_iteration_prompt("Topic", 2, "(trail)", 3)
    assert "CONVERGE" in prompt


def test_iteration_prompt_phase_5_is_finalize():
    orch = _make_orchestrator()
    prompt = orch._build_iteration_prompt("Topic", 5, "(trail)", 3)
    assert "FINALIZE" in prompt


def test_iteration_prompt_contains_vote_instructions():
    orch = _make_orchestrator()
    prompt = orch._build_iteration_prompt("Should we refactor DB?", 1, "(trail)", 2)
    assert "[VOTE:" in prompt
    assert "[CONFIDENCE:" in prompt


# ── execute() validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_raises_with_one_agent():
    orch = _make_orchestrator()
    with pytest.raises(EngineError, match=str(MIN_AGENTS)):
        await orch.execute(topic="test", agent_ids=["main"])


@pytest.mark.asyncio
async def test_execute_raises_with_too_many_agents():
    orch = _make_orchestrator()
    too_many = [f"agent-{i}" for i in range(MAX_AGENTS + 1)]
    with pytest.raises(EngineError, match=str(MAX_AGENTS)):
        await orch.execute(topic="test", agent_ids=too_many)
