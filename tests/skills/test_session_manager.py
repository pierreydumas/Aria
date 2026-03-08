"""
Tests for the session_manager skill (DB-backed, v3).

Covers:
- Session listing (via api_client → /engine/sessions)
- Session deletion (via api_client → DELETE /engine/sessions/{id})
- Active-session protection
- Prune / archive stale sessions
- Session stats
- Archived session listing
- Cleanup-after-delegation (alias for delete)
- Orphan cleanup (dry-run and live)

NOTE: All file-based helpers (_flatten_sessions, _is_cron_or_subagent_session,
_epoch_ms_to_iso) were removed when the skill migrated to DB-backed storage
in v3.  Tests below reflect the current DB-backed implementation.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from aria_skills.session_manager import SessionManagerSkill
from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sessions_payload(*sessions):
    """Build a SkillResult wrapping the /engine/sessions response body."""
    return SkillResult.ok({"sessions": list(sessions)})


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def session_skill(mock_api_client):
    """Return a SessionManagerSkill wired to the mock API client."""
    cfg = SkillConfig(name="session_manager", config={"stale_threshold_minutes": 30})
    skill = SessionManagerSkill(cfg)
    skill._api = mock_api_client
    skill._status = SkillStatus.AVAILABLE
    return skill


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_sessions_empty(session_skill, mock_api_client):
    """Returns empty list when no sessions exist in DB."""
    mock_api_client.get = AsyncMock(return_value=_sessions_payload())
    result = await session_skill.list_sessions()
    assert result.success is True
    assert result.data["session_count"] == 0
    assert result.data["sessions"] == []


@pytest.mark.asyncio
async def test_list_sessions_returns_entries(session_skill, mock_api_client):
    """Returns normalized sessions from the DB."""
    raw = [
        {"id": "s-1", "agent_id": "aria", "session_type": "interactive",
         "status": "active", "title": "Morning", "model": "qwen3", "message_count": 5},
        {"id": "s-2", "agent_id": "aria-talk", "session_type": "cron",
         "status": "active", "title": "", "model": "kimi", "message_count": 1},
    ]
    mock_api_client.get = AsyncMock(return_value=_sessions_payload(*raw))
    result = await session_skill.list_sessions()
    assert result.success is True
    assert result.data["session_count"] == 2


@pytest.mark.asyncio
async def test_list_sessions_agent_filter(session_skill, mock_api_client):
    """Agent filter restricts results to the matching agent_id."""
    raw = [
        {"id": "s-1", "agent_id": "aria", "session_type": "interactive",
         "status": "active", "title": "", "model": "qwen3", "message_count": 2},
        {"id": "s-2", "agent_id": "aria-talk", "session_type": "interactive",
         "status": "active", "title": "", "model": "kimi", "message_count": 0},
    ]
    mock_api_client.get = AsyncMock(return_value=_sessions_payload(*raw))
    result = await session_skill.list_sessions(agent="aria")
    assert result.success is True
    assert result.data["session_count"] == 1
    assert result.data["sessions"][0]["agent_id"] == "aria"


@pytest.mark.asyncio
async def test_list_sessions_api_failure(session_skill, mock_api_client):
    """API failure is handled gracefully — returns empty list."""
    mock_api_client.get = AsyncMock(return_value=SkillResult.fail("DB error"))
    result = await session_skill.list_sessions()
    assert result.success is True
    assert result.data["session_count"] == 0


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_session_missing_id(session_skill):
    """Deleting without session_id returns failure."""
    result = await session_skill.delete_session()
    assert result.success is False
    assert "required" in result.error.lower()


@pytest.mark.asyncio
async def test_delete_session_active_protection(session_skill):
    """Cannot delete the currently active session."""
    with patch.dict(os.environ, {"ARIA_SESSION_ID": "active-sid"}):
        result = await session_skill.delete_session(session_id="active-sid")
    assert result.success is False
    assert "active" in result.error.lower() or "current" in result.error.lower()


@pytest.mark.asyncio
async def test_delete_session_success(session_skill, mock_api_client):
    """Successful delete returns the session ID."""
    mock_api_client.delete = AsyncMock(return_value=SkillResult.ok({"deleted": "sid-abc"}))
    os.environ.pop("ARIA_SESSION_ID", None)
    result = await session_skill.delete_session(session_id="sid-abc")
    assert result.success is True
    assert result.data["deleted"] == "sid-abc"


@pytest.mark.asyncio
async def test_delete_session_api_failure(session_skill, mock_api_client):
    """API error on delete is surfaced as failure."""
    mock_api_client.delete = AsyncMock(return_value=SkillResult.fail("Not found"))
    os.environ.pop("ARIA_SESSION_ID", None)
    result = await session_skill.delete_session(session_id="sid-xyz")
    assert result.success is False


# ---------------------------------------------------------------------------
# prune_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prune_sessions_dry_run(session_skill, mock_api_client):
    """Dry-run calls cleanup endpoint with dry_run=True."""
    mock_api_client.get = AsyncMock(return_value=_sessions_payload())
    mock_api_client.post = AsyncMock(return_value=SkillResult.ok({
        "pruned_count": 3, "archived_count": 3, "dry_run": True,
    }))
    result = await session_skill.prune_sessions(max_age_minutes=60, dry_run=True)
    assert result.success is True
    assert result.data["dry_run"] is True
    assert result.data["pruned_count"] >= 0


@pytest.mark.asyncio
async def test_prune_sessions_live(session_skill, mock_api_client):
    """Live prune calls cleanup endpoint and returns counts."""
    mock_api_client.get = AsyncMock(return_value=_sessions_payload())
    mock_api_client.post = AsyncMock(return_value=SkillResult.ok({
        "pruned_count": 2, "archived_count": 2, "message_count": 10, "zombies_closed": 0,
    }))
    result = await session_skill.prune_sessions(max_age_minutes=120, dry_run=False)
    assert result.success is True
    assert result.data["pruned_count"] == 2


# ---------------------------------------------------------------------------
# get_session_stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_stats(session_skill, mock_api_client):
    """Returns DB-backed stats with totals and per-agent breakdown."""
    mock_api_client.get = AsyncMock(return_value=SkillResult.ok({
        "total_sessions": 7,
        "active_sessions": 4,
        "by_agent": [],
        "by_type": [],
    }))
    result = await session_skill.get_session_stats()
    assert result.success is True
    assert result.data["total_sessions"] == 7
    assert result.data["active_sessions"] == 4


@pytest.mark.asyncio
async def test_get_session_stats_api_failure(session_skill, mock_api_client):
    """Stats API failure surfaces as failure."""
    mock_api_client.get = AsyncMock(return_value=SkillResult.fail("timeout"))
    result = await session_skill.get_session_stats()
    assert result.success is False


# ---------------------------------------------------------------------------
# list_archived_sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_archived_sessions(session_skill, mock_api_client):
    """Returns archived sessions from DB."""
    mock_api_client.get = AsyncMock(return_value=SkillResult.ok({
        "sessions": [{"id": "arc-1", "agent_id": "aria"}],
        "total": 1,
    }))
    result = await session_skill.list_archived_sessions()
    assert result.success is True
    assert result.data["archived_count"] == 1


# ---------------------------------------------------------------------------
# cleanup_after_delegation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_after_delegation_missing_id(session_skill):
    """cleanup_after_delegation without session_id fails."""
    result = await session_skill.cleanup_after_delegation()
    assert result.success is False
    assert "required" in result.error.lower()


@pytest.mark.asyncio
async def test_cleanup_after_delegation_delegates_to_delete(session_skill, mock_api_client):
    """cleanup_after_delegation is a thin wrapper on delete_session."""
    mock_api_client.delete = AsyncMock(return_value=SkillResult.ok({"deleted": "sub-sid-1"}))
    os.environ.pop("ARIA_SESSION_ID", None)
    result = await session_skill.cleanup_after_delegation(session_id="sub-sid-1")
    assert result.success is True
    mock_api_client.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# cleanup_orphans
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_orphans_dry_run(session_skill, mock_api_client):
    """Dry-run orphan cleanup lists zero-message sessions without deleting."""
    raw = [
        {"id": "ghost-1", "agent_id": "aria", "session_type": "interactive",
         "message_count": 0, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "active-1", "agent_id": "aria", "session_type": "interactive",
         "message_count": 3, "created_at": "2026-01-02T00:00:00Z"},
    ]
    mock_api_client.get = AsyncMock(return_value=_sessions_payload(*raw))
    result = await session_skill.cleanup_orphans(dry_run=True)
    assert result.success is True
    assert result.data["dry_run"] is True
    assert result.data["ghost_count"] == 1


@pytest.mark.asyncio
async def test_cleanup_orphans_live(session_skill, mock_api_client):
    """Live orphan cleanup calls the ghosts DELETE endpoint."""
    mock_api_client.delete = AsyncMock(return_value=SkillResult.ok({"deleted": 4}))
    result = await session_skill.cleanup_orphans(dry_run=False)
    assert result.success is True
    assert result.data["dry_run"] is False
    mock_api_client.delete.assert_awaited_once()
