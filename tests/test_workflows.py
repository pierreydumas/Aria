"""
End-to-end workflow tests (S-157).

Tests complete multi-layer flows with all layers mocked:
- Skill invocation flow (registry → skill → api_client)
- Goal CRUD lifecycle: create → read → update → complete → verify
- Session lifecycle: create → use → close
- Memory checkpoint → recall cycle

All tests use async support with full mocking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ===========================================================================
# Goal CRUD Lifecycle
# ===========================================================================

@pytest.mark.asyncio
async def test_goal_crud_lifecycle():
    """Create → read → update → complete → verify full lifecycle."""
    from aria_skills.goals import GoalSchedulerSkill

    api = AsyncMock()
    skill = GoalSchedulerSkill(SkillConfig(name="goals", config={"max_active_goals": 10, "default_priority": 3}))
    skill._api = api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 10
    skill._default_priority = 3

    # 1. Create
    api.post = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "title": "Ship v3", "status": "active"}))
    create_result = await skill.create_goal(title="Ship v3", priority=1)
    assert create_result.success
    assert create_result.data["title"] == "Ship v3"

    # 2. Read
    api.get = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "title": "Ship v3", "status": "active", "progress": 0}))
    read_result = await skill.get_goal(goal_id="goal_1")
    assert read_result.success
    assert read_result.data["status"] == "active"

    # 3. Update progress
    api.patch = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "progress": 60, "status": "active"}))
    update_result = await skill.update_goal(goal_id="goal_1", progress=60)
    assert update_result.success

    # 4. Complete
    api.patch = AsyncMock(return_value=SkillResult.ok({"id": "goal_1", "status": "completed", "progress": 100}))
    complete_result = await skill.update_goal(goal_id="goal_1", status="completed")
    assert complete_result.success

    # 5. Verify in listing
    api.get = AsyncMock(return_value=SkillResult.ok([
        {"id": "goal_1", "status": "completed", "progress": 100},
    ]))
    list_result = await skill.list_goals(status="completed")
    assert list_result.success
    goals = list_result.data if isinstance(list_result.data, list) else list_result.data.get("goals", [])
    assert any(g["id"] == "goal_1" and g["status"] == "completed" for g in goals)


# ===========================================================================
# Goal + Subtask Lifecycle
# ===========================================================================

@pytest.mark.asyncio
async def test_goal_subtask_lifecycle():
    """Create goal → add subtasks → complete subtasks → check parent progress."""
    from aria_skills.goals import GoalSchedulerSkill

    api = AsyncMock()
    skill = GoalSchedulerSkill(SkillConfig(name="goals", config={"max_active_goals": 10, "default_priority": 3}))
    skill._api = api
    skill._status = SkillStatus.AVAILABLE
    skill._max_active = 10
    skill._default_priority = 3

    # Use API-failure fallback path so we can test local state management
    api.post = AsyncMock(side_effect=Exception("API down"))
    api.patch = AsyncMock(side_effect=Exception("API down"))

    # 1. Create parent goal (fallback)
    create_result = await skill.create_goal(title="Write Tests")
    assert create_result.success
    goal_id = create_result.data["id"]

    # 2. Add subtasks
    sub1 = await skill.add_subtask(parent_id=goal_id, title="Unit tests")
    assert sub1.success
    sub2 = await skill.add_subtask(parent_id=goal_id, title="Integration tests")
    assert sub2.success

    # 3. Complete first subtask
    sub1_id = sub1.data["subtask"]["id"]
    result = await skill.complete_subtask(parent_id=goal_id, subtask_id=sub1_id)
    assert result.success
    # 1 of 2 subtasks complete = 50%
    assert result.data["parent_progress"] == 50


# ===========================================================================
# Session Lifecycle
# ===========================================================================

@pytest.mark.asyncio
async def test_session_lifecycle():
    """Create session → use it (spawn agent) → close session."""
    from aria_skills.agent_manager import AgentManagerSkill

    api = AsyncMock()
    api.health_check = AsyncMock(return_value=SkillStatus.AVAILABLE)
    api.get = AsyncMock(return_value=SkillResult.ok({"status": "ok"}))

    skill = AgentManagerSkill(SkillConfig(name="agent_manager"))
    with patch("aria_skills.agent_manager.get_api_client", new_callable=AsyncMock, return_value=api):
        ok = await skill.initialize()
    assert ok is True

    # 1. Spawn (create session)
    api.post = AsyncMock(return_value=SkillResult.ok({
        "session_id": "sess-abc",
        "agent_id": "analyst",
        "status": "active",
    }))
    spawn_result = await skill.spawn_agent(agent_type="analyst", context={"task": "Analyze data"})
    assert spawn_result.success
    session_id = spawn_result.data["session_id"]

    # 2. Check health (use session)
    api.get = AsyncMock(side_effect=[
        SkillResult.ok({"sessions": [
            {"agent_id": "analyst", "status": "active",
             "started_at": datetime.now(timezone.utc).isoformat(),
             "model": "gpt-4", "last_active": datetime.now(timezone.utc).isoformat()},
        ]}),
        SkillResult.ok({}),  # stats
    ])
    health_result = await skill.get_agent_health()
    assert health_result.success
    assert health_result.data["total_active"] == 1

    # 3. Terminate (close session)
    api.patch = AsyncMock(return_value=SkillResult.ok({"status": "terminated"}))
    term_result = await skill.terminate_agent(session_id=session_id)
    assert term_result.success
    assert term_result.data["status"] in ("terminated", "ended")


# ===========================================================================
# Memory Checkpoint → Recall Cycle
# ===========================================================================

@pytest.mark.asyncio
async def test_memory_checkpoint_recall_cycle():
    """Checkpoint working memory → recall from checkpoint.

    Uses the hourly_goals skill as a proxy for checkpoint (set → get = recall).
    """
    from aria_skills.hourly_goals import HourlyGoalsSkill

    api = AsyncMock()
    skill = HourlyGoalsSkill(SkillConfig(name="hourly_goals"))
    skill._api = api
    skill._status = SkillStatus.AVAILABLE

    # 1. Store (checkpoint) — set hourly goal
    api.post = AsyncMock(return_value=SkillResult.ok({
        "id": "hg_10_0", "hour": 10, "goal": "Complete sprint review", "status": "pending",
    }))
    set_result = await skill.set_goal(hour=10, goal="Complete sprint review", priority="high")
    assert set_result.success

    # 2. Recall — get current goals
    api.get = AsyncMock(return_value=SkillResult.ok([
        {"id": "hg_10_0", "hour": 10, "goal": "Complete sprint review", "status": "pending"},
    ]))
    get_result = await skill.get_current_goals()
    assert get_result.success
    assert get_result.data["pending"] == 1

    # 3. Complete and verify summary
    api.patch = AsyncMock(return_value=SkillResult.ok({"status": "completed"}))
    complete_result = await skill.complete_goal(goal_id="hg_10_0")
    assert complete_result.success

    api.get = AsyncMock(return_value=SkillResult.ok([
        {"id": "hg_10_0", "hour": 10, "goal": "Complete sprint review", "status": "completed"},
    ]))
    summary = await skill.get_day_summary()
    assert summary.success
    assert summary.data["completed"] == 1
    assert summary.data["completion_rate"] == 100.0


# ===========================================================================
# Skill Invocation Flow
# ===========================================================================

@pytest.mark.asyncio
async def test_skill_invocation_flow():
    """Test complete skill invocation: construct → init → invoke → result."""
    from aria_skills.performance import PerformanceSkill

    api = AsyncMock()
    skill = PerformanceSkill(SkillConfig(name="performance"))

    # 1. Initialize
    with patch("aria_skills.performance.get_api_client", new_callable=AsyncMock, return_value=api):
        ok = await skill.initialize()
    assert ok is True
    assert skill._status == SkillStatus.AVAILABLE

    # 2. Invoke: log a review
    api.post = AsyncMock(return_value=SkillResult.ok({
        "id": "perf_1", "period": "2026-02-24",
    }))
    result = await skill.log_review(
        period="2026-02-24",
        successes=["Shipped S-154 tests"],
        failures=[],
        improvements=["Cover more edge cases"],
    )
    assert result.success
    assert result.data["period"] == "2026-02-24"

    # 3. Invoke: get reviews
    api.get = AsyncMock(return_value=SkillResult.ok([
        {"period": "2026-02-24", "improvements": ["Cover more edge cases"]},
    ]))
    reviews = await skill.get_reviews(limit=5)
    assert reviews.success

    # 4. Invoke: improvement summary
    summary = await skill.get_improvement_summary()
    assert summary.success
    assert summary.data["total_reviews"] >= 1


# ===========================================================================
# Sprint Workflow
# ===========================================================================

@pytest.mark.asyncio
async def test_sprint_workflow():
    """Plan sprint → update board → report."""
    from aria_skills.sprint_manager import SprintManagerSkill

    api = AsyncMock()
    skill = SprintManagerSkill(SkillConfig(name="sprint_manager"))
    skill._api = api
    skill._status = SkillStatus.AVAILABLE

    # 1. Plan sprint
    api.patch = AsyncMock(return_value=SkillResult.ok({}))
    plan = await skill.sprint_plan(sprint_name="Sprint 8", goal_ids=["g1", "g2"])
    assert plan.success
    assert plan.data["sprint"] == "Sprint 8"

    # 2. Move goal to doing
    api.patch = AsyncMock(return_value=SkillResult.ok({"board_column": "doing"}))
    move = await skill.sprint_move_goal(goal_id="g1", column="doing")
    assert move.success

    # 3. Report
    api.get = AsyncMock(return_value=SkillResult.ok({
        "columns": {"todo": ["g2"], "doing": ["g1"], "done": [], "on_hold": []},
    }))
    report = await skill.sprint_report()
    assert report.success
    assert report.data["total_goals"] == 2
    assert report.data["in_progress"] == 1


# ===========================================================================
# Schedule + Job Execution Workflow
# ===========================================================================

@pytest.mark.asyncio
async def test_schedule_job_execution_flow():
    """Create job → check due → mark run → verify."""
    from aria_skills.schedule import ScheduleSkill

    api = AsyncMock()
    skill = ScheduleSkill(SkillConfig(name="schedule"))
    skill._api = api
    skill._status = SkillStatus.AVAILABLE

    # Use fallback path for stateful testing
    api.post = AsyncMock(side_effect=Exception("API down"))
    api.get = AsyncMock(side_effect=Exception("API down"))
    api.put = AsyncMock(side_effect=Exception("API down"))

    # 1. Create job
    job_result = await skill.create_job(
        name="hourly_health",
        schedule="every 1 hours",
        action="health_check",
    )
    assert job_result.success
    job_id = job_result.data["id"]

    # 2. Force next_run to past
    skill._jobs[job_id]["next_run"] = "2020-01-01T00:00:00+00:00"

    # 3. Check due jobs
    due = await skill.get_due_jobs()
    assert due.success
    assert due.data["count"] == 1

    # 4. Mark as run
    mark = await skill.mark_job_run(job_id=job_id, success=True)
    assert mark.success
    assert mark.data["run_count"] == 1
