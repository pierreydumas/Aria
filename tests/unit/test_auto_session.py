"""
Unit tests for aria_engine.auto_session (T-09 — Audit).

Pure-Python subset: tests ``generate_auto_title`` (module-level, no deps)
and ``AutoSessionManager._needs_rotation`` (logic-only, dict-in / bool-out).
No DB or live services are used.

Tests cover:
- generate_auto_title: normal string
- generate_auto_title: truncates at AUTO_TITLE_MAX_LENGTH with ellipsis
- generate_auto_title: empty string falls back to timestamp
- generate_auto_title: multi-line — uses first line only
- generate_auto_title: exactly at limit — no ellipsis
- generate_auto_title: whitespace-only — falls back to timestamp
- _needs_rotation: already-ended session returns True
- _needs_rotation: message count at limit returns True
- _needs_rotation: message count below limit returns False
- _needs_rotation: session beyond duration limit returns True
- _needs_rotation: fresh session returns False
- _needs_rotation: no created_at field returns False (safe default)
- AUTO_TITLE_MAX_LENGTH constant is 100
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from aria_engine.auto_session import (
    AutoSessionManager,
    generate_auto_title,
    AUTO_TITLE_MAX_LENGTH,
    MAX_MESSAGES_PER_SESSION,
    MAX_SESSION_DURATION_HOURS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_manager(
    idle_minutes: int = 30,
    max_messages: int = MAX_MESSAGES_PER_SESSION,
    max_hours: int = MAX_SESSION_DURATION_HOURS,
) -> AutoSessionManager:
    return AutoSessionManager(
        db_engine=MagicMock(),
        session_manager=MagicMock(),
        idle_timeout_minutes=idle_minutes,
        max_messages=max_messages,
        max_duration_hours=max_hours,
    )


def _iso_ago(**kwargs) -> str:
    """Return an ISO 8601 timestamp N time units in the past."""
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


def _iso_future(**kwargs) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).isoformat()


# ── generate_auto_title ───────────────────────────────────────────────────────


def test_auto_title_normal_string():
    title = generate_auto_title("Hello, what is the weather?")
    assert title == "Hello, what is the weather?"


def test_auto_title_truncates_long_string():
    long = "A" * (AUTO_TITLE_MAX_LENGTH + 10)
    title = generate_auto_title(long)
    assert len(title) <= AUTO_TITLE_MAX_LENGTH
    assert title.endswith("...")


def test_auto_title_exactly_at_limit_no_ellipsis():
    exact = "B" * AUTO_TITLE_MAX_LENGTH
    title = generate_auto_title(exact)
    assert title == exact
    assert not title.endswith("...")


def test_auto_title_empty_string_fallback():
    title = generate_auto_title("")
    assert title.startswith("Session ")


def test_auto_title_whitespace_only_fallback():
    title = generate_auto_title("   \t\n  ")
    assert title.startswith("Session ")


def test_auto_title_multiline_uses_first_line():
    title = generate_auto_title("First line\nSecond line\nThird line")
    assert title == "First line"


def test_auto_title_multiline_first_line_empty_falls_through():
    # First line is blank, should use full text up to limit
    title = generate_auto_title("\nSecond line")
    # After strip() the text starts with \n, first_line becomes empty
    # falls through to use text[:MAX_LENGTH]
    assert isinstance(title, str)
    assert len(title) > 0


def test_auto_title_strips_leading_trailing_spaces():
    title = generate_auto_title("  Hello there  ")
    assert title == "Hello there"


def test_auto_title_constant_is_100():
    assert AUTO_TITLE_MAX_LENGTH == 100


# ── _needs_rotation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_needs_rotation_ended_session():
    mgr = _make_manager()
    session = {"metadata": {"ended": True}, "message_count": 0, "created_at": _iso_ago(hours=1)}
    assert await mgr._needs_rotation(session) is True


@pytest.mark.asyncio
async def test_needs_rotation_ended_false_not_rotated():
    mgr = _make_manager()
    session = {"metadata": {"ended": False}, "message_count": 0, "created_at": _iso_ago(hours=1)}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_message_count_at_limit():
    mgr = _make_manager(max_messages=50)
    session = {"metadata": {}, "message_count": 50, "created_at": _iso_ago(hours=1)}
    assert await mgr._needs_rotation(session) is True


@pytest.mark.asyncio
async def test_needs_rotation_message_count_below_limit():
    mgr = _make_manager(max_messages=50)
    session = {"metadata": {}, "message_count": 49, "created_at": _iso_ago(hours=1)}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_message_count_zero():
    mgr = _make_manager()
    session = {"metadata": {}, "message_count": 0, "created_at": _iso_ago(minutes=1)}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_duration_exceeded():
    mgr = _make_manager(max_hours=8)
    # Session created 9 hours ago → exceeds 8h limit
    session = {"metadata": {}, "message_count": 0, "created_at": _iso_ago(hours=9)}
    assert await mgr._needs_rotation(session) is True


@pytest.mark.asyncio
async def test_needs_rotation_duration_under_limit():
    mgr = _make_manager(max_hours=8)
    # Session created 7 hours ago → within 8h limit
    session = {"metadata": {}, "message_count": 0, "created_at": _iso_ago(hours=7)}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_no_created_at():
    """Missing created_at should not raise and should return False."""
    mgr = _make_manager()
    session = {"metadata": {}, "message_count": 0}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_no_metadata():
    """Missing metadata key should be treated as empty — not rotated."""
    mgr = _make_manager()
    session = {"message_count": 0, "created_at": _iso_ago(minutes=5)}
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_fresh_session():
    """Brand new session: no rotation needed."""
    mgr = _make_manager()
    session = {
        "metadata": {},
        "message_count": 1,
        "created_at": _iso_ago(seconds=5),
    }
    assert await mgr._needs_rotation(session) is False


@pytest.mark.asyncio
async def test_needs_rotation_naive_datetime_handled():
    """created_at without timezone info should not raise."""
    mgr = _make_manager(max_hours=1)
    naive = (datetime.utcnow() - timedelta(hours=2)).isoformat()  # no tz
    session = {"metadata": {}, "message_count": 0, "created_at": naive}
    # Should return True (2h > 1h limit) without raising
    result = await mgr._needs_rotation(session)
    assert result is True
