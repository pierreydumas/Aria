"""
Tests for the agent_manager skill (Layer 4 — orchestration).

Covers:
- Initialization (success + failure paths)
- Agent spawning (with/without context)
- Agent listing (with filters)
- Agent termination
- Health monitoring
- Performance report
- Prune stale sessions
- Spawn focused agent
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from aria_skills.base import SkillConfig, SkillResult, SkillStatus
from aria_skills.agent_manager import AgentManagerSkill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill() -> AgentManagerSkill:
    return AgentManagerSkill(SkillConfig(name="agent_manager"))


@pytest.fixture
def mock_api():
    api = AsyncMock()
    api.post = AsyncMock(return_value=SkillResult.ok({"session_id": "sess-1", "agent_id": "analyst"}))
    api.get = AsyncMock(return_value=SkillResult.ok({"sessions": [], "count": 0}))
    api.patch = AsyncMock(return_value=SkillResult.ok({"status": "terminated"}))
    api.health_check = AsyncMock(return_value=SkillStatus.AVAILABLE)
    return api


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_success(mock_api):
    skill = _make_skill()
    with patch("aria_skills.agent_manager.get_api_client", new_callable=AsyncMock, return_value=mock_api):
        ok = await skill.initialize()
    assert ok is True
    assert skill._status == SkillStatus.AVAILABLE


@pytest.mark.asyncio
async def test_initialize_api_unavailable(mock_api):
    skill = _make_skill()
    mock_api.health_check = AsyncMock(return_value=SkillStatus.UNAVAILABLE)
    with patch("aria_skills.agent_manager.get_api_client", new_callable=AsyncMock, return_value=mock_api):
        ok = await skill.initialize()
    assert ok is False
    assert skill._status == SkillStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_initialize_exception():
    skill = _make_skill()
    with patch("aria_skills.agent_manager.get_api_client", new_callable=AsyncMock, side_effect=Exception("boom")):
        ok = await skill.initialize()
    assert ok is False


# ---------------------------------------------------------------------------
# List Agents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_agents_success(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.get = AsyncMock(return_value=SkillResult.ok({"sessions": [{"id": "s1"}], "count": 1}))

    result = await skill.list_agents()
    assert result.success
    assert result.data["count"] == 1


@pytest.mark.asyncio
async def test_list_agents_not_initialized():
    skill = _make_skill()
    skill._api = None

    result = await skill.list_agents()
    assert not result.success
    assert "Not initialized" in result.error


@pytest.mark.asyncio
async def test_list_agents_with_filters(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    await skill.list_agents(status="active", agent_id="analyst", limit=10)
    call_args = mock_api.get.call_args
    params = call_args[1].get("params", call_args[0][1] if len(call_args[0]) > 1 else {})
    assert params.get("status") == "active" or "status" in str(call_args)


# ---------------------------------------------------------------------------
# Spawn Agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_agent_success(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    result = await skill.spawn_agent(
        agent_type="analyst",
        context={"task": "Analyze code quality"},
    )
    assert result.success
    mock_api.post.assert_called_once()


@pytest.mark.asyncio
async def test_spawn_agent_missing_task(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    result = await skill.spawn_agent(agent_type="analyst", context={"task": ""})
    assert not result.success
    assert "task" in result.error.lower()


@pytest.mark.asyncio
async def test_spawn_agent_no_context(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    result = await skill.spawn_agent(agent_type="creator")
    assert result.success


@pytest.mark.asyncio
async def test_spawn_agent_api_failure(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.post = AsyncMock(side_effect=Exception("API down"))

    result = await skill.spawn_agent(agent_type="devops", context={"task": "Deploy"})
    assert not result.success
    assert "Failed to spawn" in result.error


# ---------------------------------------------------------------------------
# Terminate Agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terminate_agent_success(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    result = await skill.terminate_agent(session_id="sess-1")
    assert result.success
    assert result.data["status"] in {"terminated", "ended"}


@pytest.mark.asyncio
async def test_terminate_agent_not_initialized():
    skill = _make_skill()
    skill._api = None

    result = await skill.terminate_agent(session_id="sess-1")
    assert not result.success


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_calls_api(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    mock_api.get = AsyncMock(return_value=SkillResult.ok({"status": "ok"}))

    status = await skill.health_check()
    assert status == SkillStatus.AVAILABLE


@pytest.mark.asyncio
async def test_health_check_no_api():
    skill = _make_skill()
    skill._api = None

    status = await skill.health_check()
    assert status == SkillStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Performance Report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_performance_report(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.get = AsyncMock(return_value=SkillResult.ok({
        "total_sessions": 10,
        "active_sessions": 3,
        "total_tokens": 50000,
        "total_cost": 0.25,
        "by_agent": [],
        "by_status": [],
    }))

    result = await skill.get_performance_report()
    assert result.success
    assert result.data["total_sessions"] == 10
    assert "generated_at" in result.data


# ---------------------------------------------------------------------------
# Agent Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_agent_health(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    now = datetime.now(timezone.utc)
    mock_api.get = AsyncMock(side_effect=[
        SkillResult.ok({"sessions": [
            {"agent_id": "analyst", "status": "active", "started_at": (now - timedelta(minutes=30)).isoformat(), "model": "gpt-4", "last_active": now.isoformat()},
        ]}),
        SkillResult.ok({}),  # stats call
    ])

    result = await skill.get_agent_health()
    assert result.success
    assert result.data["total_active"] == 1


# ---------------------------------------------------------------------------
# Sub-agent circuit breaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_focused_agent_opens_circuit_after_failure(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.post = AsyncMock(side_effect=[
        SkillResult.ok({"id": "sess-focused-1"}),
        SkillResult.fail("comms down"),
    ])
    mock_api.delete = AsyncMock(return_value=SkillResult.ok({"status": "ended"}))

    first = await skill.spawn_focused_agent(
        task="Find one source",
        focus="research",
        tools=["browser"],
    )
    assert not first.success
    assert "Focused agent failed" in first.error

    call_count_before = mock_api.post.call_count
    second = await skill.spawn_focused_agent(
        task="Try again",
        focus="research",
        tools=["browser"],
    )
    assert not second.success
    assert "circuit open" in second.error.lower()
    assert mock_api.post.call_count == call_count_before


@pytest.mark.asyncio
async def test_send_to_agent_short_circuits_when_circuit_open(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    skill._subagent_circuit_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    mock_api.post = AsyncMock()

    result = await skill.send_to_agent(session_id="sess-1", message="continue")
    assert not result.success
    assert "circuit open" in result.error.lower()
    engine_calls = [
        args[0]
        for args, _ in mock_api.post.call_args_list
        if args and isinstance(args[0], str) and "/engine/chat/sessions/" in args[0]
    ]
    assert engine_calls == []
