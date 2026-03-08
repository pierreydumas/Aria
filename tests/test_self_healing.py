"""
tests/test_self_healing.py — S-45 Phase 5 Chaos Tests

Tests circuit breaker behavior, retry logic, LLM fallback chain,
and activity logging resilience. Uses mocks/stubs — no production mutation.
"""
from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_api_client():
    """Create a minimal AriaAPIClient-like stub for circuit breaker tests."""
    try:
        from aria_skills.api_client import AriaAPIClient
        from aria_skills.base import SkillConfig
        cfg = SkillConfig(name="api_client", config={"api_url": "http://localhost:8000/api"})
        client = AriaAPIClient(cfg)
        # Inject a mock httpx client so no real network calls are made
        mock_http = AsyncMock()
        client._client = mock_http
        client._status = __import__("aria_skills.base", fromlist=["SkillStatus"]).SkillStatus.AVAILABLE
        return client, mock_http
    except Exception as e:
        pytest.skip(f"AriaAPIClient not importable: {e}")


def _make_llm_skill():
    """Create a minimal LLMSkill stub for fallback chain tests."""
    try:
        from aria_skills.llm import LLMSkill, LLM_FALLBACK_CHAIN
        from aria_skills.base import SkillConfig
        cfg = SkillConfig(name="llm", config={"litellm_url": "http://localhost:4000/v1"})
        skill = LLMSkill(cfg)
        mock_http = AsyncMock()
        skill._client = mock_http
        skill._status = __import__("aria_skills.base", fromlist=["SkillStatus"]).SkillStatus.AVAILABLE
        return skill, mock_http, LLM_FALLBACK_CHAIN
    except Exception as e:
        pytest.skip(f"LLMSkill not importable: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Circuit breaker opens after N failures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures():
    """
    Circuit opens after circuit_failure_threshold consecutive failures.
    Subsequent calls return immediately with circuit-open error (no HTTP call).
    """
    client, mock_http = _make_api_client()
    client._circuit_failure_threshold = 3
    client._circuit_reset_seconds = 60.0

    # Simulate the threshold being reached
    for _ in range(client._circuit_failure_threshold):
        client._record_failure()

    assert client._is_circuit_open(), "Circuit should be open after hitting threshold"

    # The next call to _request_with_retry must raise without hitting HTTP
    with pytest.raises(RuntimeError, match="circuit breaker"):
        await client._request_with_retry("GET", "/activities")

    # HTTP client should NOT have been called
    mock_http.request.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Retry with exponential backoff on 503
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_with_exponential_backoff():
    """
    503 responses trigger retries; successful response on 3rd attempt returns data.
    asyncio.sleep is patched to avoid real delays.
    """
    client, mock_http = _make_api_client()
    client._max_retries = 3
    client._base_backoff_seconds = 0.01  # fast for tests

    # First two attempts return 503, third returns 200
    resp_503 = MagicMock()
    resp_503.status_code = 503

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.raise_for_status = MagicMock()
    resp_200.json = MagicMock(return_value={"status": "ok"})

    mock_http.request = AsyncMock(side_effect=[resp_503, resp_503, resp_200])

    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def patched_sleep(delay: float):
        sleep_calls.append(delay)

    with patch("asyncio.sleep", patched_sleep):
        resp = await client._request_with_retry("GET", "/health")

    assert resp.status_code == 200
    assert mock_http.request.call_count == 3

    # Delays should be exponentially increasing (0.01*1, 0.01*2)
    assert len(sleep_calls) == 2, f"Expected 2 sleep calls, got {sleep_calls}"
    assert sleep_calls[1] > sleep_calls[0], "Delays should be increasing"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — LLM fallback chain skips open-circuit models
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_fallback_chain_skips_open_circuit():
    """
    When primary model (qwen3-mlx) circuit is open, complete_with_fallback()
    skips it and succeeds via the next available model without any error.
    """
    skill, mock_http, fallback_chain = _make_llm_skill()
    primary = fallback_chain[0]["model"]
    expected_fallback = next(entry["model"] for entry in fallback_chain if entry["model"] != primary)

    # Open circuit for primary
    skill._circuit_open_until[primary] = time.monotonic() + 999.0

    # Mock HTTP: the call should be for the next available model in the chain.
    mock_http.post = AsyncMock(return_value=MagicMock(
        status_code=200,
        raise_for_status=MagicMock(),
        json=MagicMock(return_value={
            "id": "test-123",
            "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
        })
    ))

    messages = [{"role": "user", "content": "hello"}]
    result = await skill.complete_with_fallback(messages)

    assert result.ok, f"Expected success, got: {result}"
    used_model = result.data.get("_aria_model_used")
    assert used_model == expected_fallback, (
        f"Expected fallback to {expected_fallback}, used {used_model}"
    )
    assert primary not in result.data.get("_aria_fallback_tried", []), (
        "Primary (open circuit) should not appear in tried list"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — create_activity is resilient to brief API unavailability
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activity_logging_resilient_to_transient_failure():
    """
    create_activity() uses _request_with_retry — succeeds after 1 transient failure.
    Confirms Phase 2 migration: no direct self._client calls bypass retry.
    """
    client, mock_http = _make_api_client()
    client._max_retries = 3
    client._base_backoff_seconds = 0.01

    # First call fails with network error, second succeeds
    activity_resp = MagicMock()
    activity_resp.status_code = 200
    activity_resp.raise_for_status = MagicMock()
    activity_resp.json = MagicMock(return_value={"id": "abc-123", "action": "test"})

    mock_http.request = AsyncMock(side_effect=[
        ConnectionError("simulated brief outage"),
        activity_resp,
    ])

    async def patched_sleep(delay: float):
        pass  # no real wait

    with patch("asyncio.sleep", patched_sleep):
        result = await client.create_activity(
            action="selfheal_test",
            details={"test": True}
        )

    assert result.ok, f"Expected create_activity to succeed: {result}"
    assert result.data.get("id") == "abc-123"
    assert mock_http.request.call_count == 2, "Should have retried once"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Health degradation level detection
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_degradation_level_detection():
    """
    HealthMonitorSkill.check_degradation_level() returns correct tiers:
    - 0 failures → HEALTHY
    - 1-2 failures → DEGRADED
    - 3+ failures → CRITICAL
    """
    try:
        from aria_skills.health import HealthMonitorSkill, HealthDegradationLevel
        from aria_skills.base import SkillConfig
    except ImportError as e:
        pytest.skip(f"Health skill not importable: {e}")

    cfg = SkillConfig(name="health", config={})
    skill = HealthMonitorSkill(cfg)

    # Inject fake check results
    skill._check_results = {
        "python":      {"status": "healthy"},
        "memory":      {"status": "healthy"},
        "disk":        {"status": "healthy"},
        "network":     {"status": "healthy"},
        "environment": {"status": "healthy"},
    }
    skill._last_check = __import__("datetime").datetime.now()

    result = await skill.check_degradation_level()
    assert result.ok
    assert result.data["level"] == HealthDegradationLevel.HEALTHY.value

    # Inject 1 warning → DEGRADED
    skill._check_results["disk"]["status"] = "warning"
    result = await skill.check_degradation_level()
    assert result.data["level"] == HealthDegradationLevel.DEGRADED.value

    # Inject 3 failures → CRITICAL
    skill._check_results["memory"]["status"] = "critical"
    skill._check_results["network"]["status"] = "critical"
    result = await skill.check_degradation_level()
    assert result.data["level"] == HealthDegradationLevel.CRITICAL.value
    assert "disk" in result.data["failing_subsystems"]
    assert "memory" in result.data["failing_subsystems"]
    assert "network" in result.data["failing_subsystems"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — apply_degradation_mode suspends correct jobs
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_degradation_mode_suspends_correct_jobs():
    """
    apply_degradation_mode(DEGRADED) suspends moltbook_check and social_post.
    apply_degradation_mode(CRITICAL) also suspends goal_check and agent_audit.
    heartbeat and health_check are NEVER suspended at any level.
    """
    try:
        from aria_skills.health import HealthMonitorSkill, HealthDegradationLevel
        from aria_skills.base import SkillConfig
    except ImportError as e:
        pytest.skip(f"Health skill not importable: {e}")

    cfg = SkillConfig(name="health", config={})
    skill = HealthMonitorSkill(cfg)

    # DEGRADED
    result = await skill.apply_degradation_mode(HealthDegradationLevel.DEGRADED)
    assert result.ok
    assert "moltbook_check" in result.data["suspend"]
    assert "social_post" in result.data["suspend"]
    # heartbeat must never be suspended
    assert "heartbeat" not in result.data["suspend"]
    assert "health_check" not in result.data["suspend"]

    # CRITICAL
    result = await skill.apply_degradation_mode(HealthDegradationLevel.CRITICAL)
    assert result.ok
    assert "goal_check" in result.data["suspend"]
    assert "agent_audit" in result.data["suspend"]
    assert "heartbeat" not in result.data["suspend"]
    assert "health_check" not in result.data["suspend"]
