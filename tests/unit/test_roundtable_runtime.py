from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aria_engine.roundtable import Roundtable, RoundtableTurn


def _make_roundtable() -> Roundtable:
    roundtable = Roundtable(
        db_engine=MagicMock(),
        agent_pool=MagicMock(),
        router=MagicMock(),
    )
    roundtable._pool.get_agent.return_value = None
    return roundtable


@pytest.mark.asyncio
async def test_run_round_keeps_fast_turns_when_one_agent_times_out():
    roundtable = _make_roundtable()

    async def fake_get_agent_response(**kwargs):
        agent_id = kwargs["agent_id"]
        if agent_id == "slow":
            await asyncio.sleep(0.2)
        return RoundtableTurn(
            agent_id=agent_id,
            round_number=kwargs["round_number"],
            content=f"reply from {agent_id}",
            duration_ms=10,
        )

    roundtable._get_agent_response = AsyncMock(side_effect=fake_get_agent_response)

    turns = await roundtable._run_round(
        session_id="sess-1",
        topic="topic",
        agent_ids=["slow", "fast"],
        round_number=1,
        prior_turns=[],
        agent_timeout=1,
        round_timeout=0.05,
    )

    assert [turn.agent_id for turn in turns] == ["fast"]
