"""
Tests for the goals skill (Layer 4 — orchestration).

Covers:
- Initialization and health check
- Goal CRUD (create, read, update)
- Subtask management (add, complete)
- Priority and status handling
- Goal listing with filters
- Summary statistics
- Error paths (max active, not found)
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from aria_skills.base import SkillConfig, SkillResult, SkillStatus
from aria_skills.goals import GoalSchedulerSkill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(max_active: int = 10, default_priority: int = 3) -> GoalSchedulerSkill:
    return GoalSchedulerSkill(
        SkillConfig(name="goals", config={
            "max_active_goals": max_active,
            "default_priority": default_priority,
        })
    )


@pytest.fixture
def mock_api():
    api = AsyncMock()
    api.post = AsyncMock(return_value=SkillResult.ok({}))
    api.get = AsyncMock(return_value=SkillResult.ok([]))
    api.patch = AsyncMock(return_value=SkillResult.ok({}))
    api.put = AsyncMock(return_value=SkillResult.ok({}))
    api.delete = AsyncMock(return_value=SkillResult.ok({}))
    api.health_check = AsyncMock(return_value=SkillStatus.AVAILABLE)
    return api


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize(mock_api):
    skill = _make_skill()
    with patch("aria_skills.goals.get_api_client", new_callable=AsyncMock, return_value=mock_api):
        ok = await skill.initialize()
    assert ok is True
    assert await skill.health_check() == SkillStatus.AVAILABLE


# ---------------------------------------------------------------------------
# Create Goal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_goal_success(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 10
    skill._default_priority = 3

    mock_api.post = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "title": "Test Goal"}))

    result = await skill.create_goal(title="Test Goal", description="A test", priority=2)
    assert result.success
    assert result.data["title"] == "Test Goal"
    mock_api.post.assert_called_once()


@pytest.mark.asyncio
async def test_create_goal_max_active_reached(mock_api):
    skill = _make_skill(max_active=1)
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 1
    skill._default_priority = 3
    # Pre-fill one active goal
    skill._goals["g1"] = {"status": "active"}

    result = await skill.create_goal(title="Overflow Goal")
    assert not result.success
    assert "Maximum active goals" in result.error


@pytest.mark.asyncio
async def test_create_goal_api_failure_fallback(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 10
    skill._default_priority = 3
    mock_api.post = AsyncMock(side_effect=Exception("API down"))

    result = await skill.create_goal(title="Fallback Goal")
    assert result.success
    assert result.data["title"] == "Fallback Goal"
    assert result.data["status"] == "active"


@pytest.mark.asyncio
async def test_create_goal_with_tags_and_due_date(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 10
    skill._default_priority = 3
    mock_api.post = AsyncMock(return_value=SkillResult.ok({}))

    due = datetime(2026, 3, 1, tzinfo=timezone.utc)
    result = await skill.create_goal(title="Tagged Goal", tags=["sprint7"], due_date=due)
    assert result.success


# ---------------------------------------------------------------------------
# Update Goal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_goal_status(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.patch = AsyncMock(return_value=SkillResult.ok({"status": "completed", "progress": 100}))

    result = await skill.update_goal(goal_id="goal_1", status="completed")
    assert result.success
    mock_api.patch.assert_called_once()


@pytest.mark.asyncio
async def test_update_goal_progress_100_sets_completed(mock_api):
    """Setting progress to 100 should also set status to completed."""
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.patch = AsyncMock(side_effect=Exception("API down"))
    # Provide fallback data
    skill._goals["goal_1"] = {
        "id": "goal_1", "title": "T", "status": "active", "progress": 50,
        "priority": 3, "notes": [], "subtasks": [],
    }

    result = await skill.update_goal(goal_id="goal_1", progress=100)
    assert result.success
    assert result.data["status"] == "completed"
    assert result.data["progress"] == 100


@pytest.mark.asyncio
async def test_update_goal_not_found_fallback(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.patch = AsyncMock(side_effect=Exception("API down"))

    result = await skill.update_goal(goal_id="nonexistent", status="paused")
    assert not result.success
    assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# Get Goal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_goal_success(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.get = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "title": "My Goal"}))

    result = await skill.get_goal(goal_id="goal_1")
    assert result.success
    assert result.data["id"] == "goal_1"


# ---------------------------------------------------------------------------
# Subtask Management
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_subtask(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.post = AsyncMock(return_value=SkillResult.ok({"id": "sub_1", "title": "Sub"}))

    result = await skill.add_subtask(parent_id="goal_1", title="Sub task")
    assert result.success


@pytest.mark.asyncio
async def test_complete_subtask_fallback(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.patch = AsyncMock(side_effect=Exception("API down"))
    skill._goals["goal_1"] = {
        "id": "goal_1", "subtasks": [
            {"id": "goal_1_sub_1", "title": "Do thing", "status": "pending"},
        ], "progress": 0,
    }

    result = await skill.complete_subtask(parent_id="goal_1", subtask_id="goal_1_sub_1")
    assert result.success
    assert result.data["subtask"]["status"] == "completed"
    assert result.data["parent_progress"] == 100


# ---------------------------------------------------------------------------
# List Goals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_goals_with_filters(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.get = AsyncMock(return_value=SkillResult.ok([
        {"id": "g1", "status": "active", "priority": 1},
    ]))

    result = await skill.list_goals(status="active", priority=1, limit=5)
    assert result.success


@pytest.mark.asyncio
async def test_list_goals_board_column_status(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    mock_api.get = AsyncMock(return_value=SkillResult.ok({"items": []}))
    mock_api.get_goal_board = AsyncMock(return_value=SkillResult.ok({
        "columns": {
            "backlog": [{"id": "g1", "board_column": "backlog", "priority": 2}],
            "todo": [{"id": "g2", "board_column": "todo", "priority": 1}],
            "doing": [{"id": "g3", "board_column": "doing", "priority": 3}],
            "on_hold": [],
            "done": [{"id": "g4", "board_column": "done", "priority": 4}],
        }
    }))
    mock_api.get_goal_archive = AsyncMock(return_value=SkillResult.ok({"items": [], "total": 0}))

    result = await skill.list_goals(status="doing", limit=10)
    assert result.success
    assert result.data["total"] == 1
    assert result.data["goals"][0]["id"] == "g3"
    assert result.data["board_counts"]["backlog"] == 1


@pytest.mark.asyncio
async def test_get_summary_includes_board_column_counts(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE

    mock_api.get = AsyncMock(return_value=SkillResult.ok({
        "goals": [
            {"id": "g1", "status": "active", "priority": 1},
            {"id": "g2", "status": "completed", "priority": 2},
        ]
    }))
    mock_api.get_goal_board = AsyncMock(return_value=SkillResult.ok({
        "columns": {
            "backlog": [{"id": "g1"}],
            "todo": [{"id": "g2"}],
            "doing": [],
            "on_hold": [],
            "done": [{"id": "g3"}],
        }
    }))
    mock_api.get_goal_archive = AsyncMock(return_value=SkillResult.ok({"total": 7, "items": []}))

    result = await skill.get_summary()
    assert result.success
    assert result.data["by_board_column"]["backlog"] == 1
    assert result.data["by_board_column"]["todo"] == 1
    assert result.data["by_board_column"]["done"] == 1
    assert result.data["by_board_column"]["archived"] == 7


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_summary(mock_api):
    skill = _make_skill()
    skill._api = mock_api
    skill._status = SkillStatus.AVAILABLE
    mock_api.get = AsyncMock(return_value=SkillResult.ok([
        {"status": "active", "priority": 1},
        {"status": "completed", "priority": 2},
    ]))

    result = await skill.get_summary()
    assert result.success
    assert result.data["total"] == 2
    assert result.data["by_status"]["active"] == 1
    assert result.data["by_status"]["completed"] == 1
