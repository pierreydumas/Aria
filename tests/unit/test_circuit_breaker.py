"""
Unit tests for aria_engine.circuit_breaker (T-01 / T-04 — Audit).

Tests cover:
- Initial state is CLOSED
- is_open() returns False when closed
- record_failure() increments counter; breaker opens at threshold
- state property returns correct string values
- record_success() resets failures and closes the breaker
- reset() force-closes regardless of failure count
- Half-open detection after reset_after elapsed (via monkerpatching time.monotonic)
- spawn_gate() raises when breaker is open
- __repr__ includes name and state
"""
from __future__ import annotations

import time
import pytest

from aria_engine.circuit_breaker import CircuitBreaker


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def cb():
    """Circuit breaker with threshold=3 and a very long reset_after."""
    return CircuitBreaker(name="test", threshold=3, reset_after=9999.0)


@pytest.fixture
def fast_cb():
    """Circuit breaker with threshold=2 and instant reset (reset_after=0.0)."""
    return CircuitBreaker(name="fast", threshold=2, reset_after=0.0)


# ── Initial state ─────────────────────────────────────────────────────────────


def test_initial_state_closed(cb):
    assert cb.state == "closed"


def test_initial_is_open_false(cb):
    assert cb.is_open() is False


def test_initial_failures_zero(cb):
    assert cb._failures == 0


# ── Failure counting ──────────────────────────────────────────────────────────


def test_single_failure_stays_closed(cb):
    cb.record_failure()
    assert cb.is_open() is False
    assert cb.state == "closed"


def test_failure_below_threshold_stays_closed(cb):
    for _ in range(cb.threshold - 1):
        cb.record_failure()
    assert cb.is_open() is False


def test_failure_at_threshold_opens(cb):
    for _ in range(cb.threshold):
        cb.record_failure()
    assert cb.is_open() is True
    assert cb.state == "open"


def test_failure_beyond_threshold_stays_open(cb):
    for _ in range(cb.threshold + 5):
        cb.record_failure()
    assert cb.is_open() is True


# ── record_success ────────────────────────────────────────────────────────────


def test_success_resets_failures(cb):
    for _ in range(cb.threshold):
        cb.record_failure()
    assert cb.is_open() is True
    cb.record_success()
    assert cb.is_open() is False
    assert cb._failures == 0


def test_success_closes_breaker(cb):
    for _ in range(cb.threshold):
        cb.record_failure()
    cb.record_success()
    assert cb.state == "closed"


# ── reset ─────────────────────────────────────────────────────────────────────


def test_reset_force_closes(cb):
    for _ in range(cb.threshold):
        cb.record_failure()
    assert cb.is_open() is True
    cb.reset()
    assert cb.is_open() is False
    assert cb._failures == 0


def test_reset_on_closed_is_noop(cb):
    cb.reset()
    assert cb.state == "closed"
    assert cb._failures == 0


# ── Half-open detection ───────────────────────────────────────────────────────


def test_half_open_after_reset_after_elapsed(monkeypatch):
    """After reset_after seconds the breaker transitions to half-open."""
    cb = CircuitBreaker(name="hopen", threshold=2, reset_after=10.0)
    t0 = time.monotonic()

    for _ in range(2):
        cb.record_failure()
    assert cb.state == "open"

    # Simulate 11 seconds passing
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 11.0)
    assert cb.state == "half-open"
    # is_open() should return False in half-open (probe allowed)
    assert cb.is_open() is False


def test_open_before_reset_after(monkeypatch):
    cb = CircuitBreaker(name="still-open", threshold=1, reset_after=30.0)
    t0 = time.monotonic()
    cb.record_failure()

    # Only 5 seconds have elapsed
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 5.0)
    assert cb.state == "open"
    assert cb.is_open() is True


# ── spawn_gate ────────────────────────────────────────────────────────────────


def test_spawn_gate_raises_when_open(cb):
    for _ in range(cb.threshold):
        cb.record_failure()
    with pytest.raises(Exception):
        cb.spawn_gate()


def test_spawn_gate_passes_when_closed(cb):
    # Should not raise
    cb.spawn_gate()


# ── __repr__ ──────────────────────────────────────────────────────────────────


def test_repr_contains_name(cb):
    assert "test" in repr(cb)


def test_repr_contains_state(cb):
    r = repr(cb)
    assert "closed" in r or "open" in r or "half-open" in r
