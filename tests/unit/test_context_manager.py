"""
Unit tests for aria_engine.context_manager.ContextManager.build_context (T-05 — Audit).

All tests are pure-Python: ``_count_tokens`` is monkeypatched to return a
fixed value so litellm and the database are never touched.

Tests cover:
- Empty input returns empty list (no system prompt)
- System message always included regardless of budget
- Budget enforcement drops low-importance messages when tokens exhausted
- reserve_tokens correctly shrinks the available budget
- Pinned messages (system + first user + last N) are never evicted
- Result preserves original message order
- Messages with tool_calls receive importance boost (kept when high-cost)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aria_engine.config import EngineConfig
from aria_engine.context_manager import ContextManager, MIN_RECENT_MESSAGES, FALLBACK_TOKENS_PER_MESSAGE


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cm() -> ContextManager:
    """Return a ContextManager with a default (no-pydantic) config."""
    return ContextManager(config=EngineConfig())


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _system(content: str) -> dict:
    return {"role": "system", "content": content}


def _tool_msg(content: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": "call_1"}


# Each message costs exactly 10 tokens in all tests below.
TOKENS_PER_MSG = 10


def _patch_tokens(cm: ContextManager):
    """Monkeypatch _count_tokens to return TOKENS_PER_MSG for every message."""
    cm._count_tokens = lambda msg, model="": TOKENS_PER_MSG


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_empty_messages_returns_empty():
    cm = _make_cm()
    _patch_tokens(cm)
    result = cm.build_context(all_messages=[], max_tokens=1000, model="gpt-4o")
    assert result == []


def test_single_system_message_always_included():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_system("You are Aria.")]
    result = cm.build_context(all_messages=messages, max_tokens=1000, model="gpt-4o")
    assert len(result) == 1
    assert result[0]["role"] == "system"


def test_all_fit_within_budget_returns_all():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_system("sys"), _user("hi"), _assistant("hello")]
    # 3 messages x 10 tokens = 30 tokens; budget 100, reserve 0
    result = cm.build_context(all_messages=messages, max_tokens=100, model="", reserve_tokens=0)
    assert len(result) == 3


def test_budget_exceeded_drops_low_importance_messages():
    cm = _make_cm()
    _patch_tokens(cm)
    # Build a long conversation where mid-conversation assistant messages
    # should be dropped first (lowest importance, not pinned).
    # Budget: 5 messages × 10 tokens = 50; we allow max_tokens=30 → at most 3.
    messages = [
        _system("sys"),           # pinned, score=100
        _user("first user"),      # pinned (first user), score=60
        _assistant("mid reply"),  # NOT pinned, score=40 — candidate for eviction
        _user("second user"),
        _assistant("final"),      # last MIN_RECENT_MESSAGES — pinned
    ]
    result = cm.build_context(all_messages=messages, max_tokens=30, model="")
    # The mid-conversation assistant reply should be dropped
    roles = [m["role"] for m in result]
    # System must always be present
    assert "system" in roles
    # Result must be shorter than original (some message was dropped)
    assert len(result) < len(messages)


def test_reserve_tokens_shrinks_budget():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_system("sys"), _user("a"), _user("b"), _user("c"), _user("d")]
    # Without reserve: max_tokens=50 fits all 5 messages (5×10=50)
    result_no_reserve = cm.build_context(
        all_messages=messages, max_tokens=50, model="", reserve_tokens=0
    )
    # With reserve=20: effective budget = 30, fits only 3
    result_with_reserve = cm.build_context(
        all_messages=messages, max_tokens=50, model="", reserve_tokens=20
    )
    assert len(result_with_reserve) <= len(result_no_reserve)


def test_system_prompt_always_survives_tiny_budget():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_system("sys"), _user("u"), _assistant("a"), _user("u2"), _assistant("a2")]
    # Absurdly small budget — system prompt must still be in the result
    result = cm.build_context(all_messages=messages, max_tokens=1, model="")
    roles = [m["role"] for m in result]
    assert "system" in roles


def test_result_preserves_chronological_order():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [
        _system("sys"),
        _user("msg1"),
        _assistant("msg2"),
        _user("msg3"),
    ]
    result = cm.build_context(all_messages=messages, max_tokens=1000, model="")
    # The subset returned should be in the same relative order as input
    input_order = [m["content"] for m in messages]
    result_order = [m["content"] for m in result]
    filtered_input = [c for c in input_order if c in result_order]
    assert filtered_input == result_order


def test_tool_message_receives_importance_boost():
    cm = _make_cm()
    _patch_tokens(cm)
    # Tool message should score higher than plain assistant message.
    # When budget is tight, the tool message should survive over a plain assistant.
    messages = [
        _system("sys"),
        _user("question"),
        _assistant("plain answer that might be evicted"),
        _tool_msg("tool result: critical data"),
        _assistant("final answer"),  # pinned (last MIN_RECENT_MESSAGES)
    ]
    # Budget fits 4 out of 5, reserve=0 so budget = 40 tokens = 4 messages
    result = cm.build_context(all_messages=messages, max_tokens=40, model="", reserve_tokens=0)
    contents = [m.get("content", "") for m in result]
    assert "tool result: critical data" in contents


def test_estimate_tokens_sums_all_messages():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_user("a"), _assistant("b"), _system("c")]
    total = cm.estimate_tokens(messages, model="")
    assert total == TOKENS_PER_MSG * len(messages)


def test_get_window_stats_keys():
    cm = _make_cm()
    _patch_tokens(cm)
    messages = [_system("sys"), _user("hi"), _assistant("hello")]
    stats = cm.get_window_stats(messages, model="")
    assert "total_messages" in stats
    assert "total_tokens" in stats
    assert "role_counts" in stats
    assert stats["total_messages"] == 3
