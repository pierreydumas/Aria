"""
Tests for the api_client skill (Layer 1).

Covers:
- Initialization with env vars and config
- Generic HTTP verb methods (get/post/patch/put/delete)
- Domain methods (goals, memories, activities, etc.)
- Error handling (connection errors, timeouts, HTTP 4xx/5xx)
- Auth header propagation
- Circuit breaker behaviour
"""
from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aria_skills.api_client import AriaAPIClient
from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int = 200, json_data: dict | None = None):
    """Build a fake httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code}", request=MagicMock(), response=resp,
        )
    return resp


@pytest.fixture
def api_client():
    """Return an AriaAPIClient with a mocked httpx.AsyncClient."""
    cfg = SkillConfig(name="api_client", config={
        "api_url": "http://test-api:8000/api",
        "timeout": 5,
        "max_retries": 1,
        "base_backoff_seconds": 0.0,
        "circuit_failure_threshold": 3,
        "circuit_reset_seconds": 0.1,
    })
    client = AriaAPIClient(cfg)
    # Inject a mock httpx client directly
    mock_httpx = AsyncMock(spec=httpx.AsyncClient)
    client._client = mock_httpx
    client._api_url = "http://test-api:8000/api"
    client._status = SkillStatus.AVAILABLE
    return client


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_default_url():
    """Without env var, uses default api_url from config."""
    cfg = SkillConfig(name="api_client", config={"api_url": "http://my-api:9000/api"})
    client = AriaAPIClient(cfg)
    with patch("aria_skills.api_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = AsyncMock()
        result = await client.initialize()
        assert result is True
        assert client._api_url == "http://my-api:9000/api"
        assert client._status == SkillStatus.AVAILABLE
        await client.close()


@pytest.mark.asyncio
async def test_initialize_from_env():
    """ARIA_API_URL env var overrides the default."""
    cfg = SkillConfig(name="api_client", config={})
    client = AriaAPIClient(cfg)
    with (
        patch.dict(os.environ, {"ARIA_API_URL": "http://env-api:8080/api"}),
        patch("aria_skills.api_client.httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value = AsyncMock()
        await client.initialize()
        assert client._api_url == "http://env-api:8080/api"
        await client.close()


@pytest.mark.asyncio
async def test_initialize_with_api_key():
    """ARIA_API_KEY should be propagated as X-API-Key header."""
    cfg = SkillConfig(name="api_client", config={})
    client = AriaAPIClient(cfg)
    with (
        patch.dict(os.environ, {"ARIA_API_KEY": "test-key-42"}),
        patch("aria_skills.api_client.httpx.AsyncClient") as mock_cls,
    ):
        mock_cls.return_value = AsyncMock()
        await client.initialize()
        # The AsyncClient constructor should have been called with headers including X-API-Key
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["headers"]["X-API-Key"] == "test-key-42"
        await client.close()


# ---------------------------------------------------------------------------
# Generic HTTP verbs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_success(api_client):
    """Generic GET returns SkillResult.ok on 200."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"items": [1, 2, 3]})
    )
    result = await api_client.get("/some-path")
    assert result.success is True
    assert result.data == {"items": [1, 2, 3]}


@pytest.mark.asyncio
async def test_post_success(api_client):
    """Generic POST returns SkillResult.ok on 200."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"id": 42})
    )
    result = await api_client.post("/some-path", data={"key": "val"})
    assert result.success is True
    assert result.data["id"] == 42


@pytest.mark.asyncio
async def test_patch_success(api_client):
    """Generic PATCH returns SkillResult.ok on 200."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"updated": True})
    )
    result = await api_client.patch("/items/1", data={"name": "new"})
    assert result.success is True


@pytest.mark.asyncio
async def test_delete_success(api_client):
    """Generic DELETE returns SkillResult.ok on 200."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"deleted": True})
    )
    result = await api_client.delete("/items/1")
    assert result.success is True


# ---------------------------------------------------------------------------
# Domain methods
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_activities(api_client):
    """get_activities delegates to GET /activities."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"activities": []})
    )
    result = await api_client.get_activities(limit=10)
    assert result.success is True
    api_client._client.request.assert_called_once()
    method, path = api_client._client.request.call_args[0][:2]
    assert method == "GET"
    assert "/activities" in path


@pytest.mark.asyncio
async def test_create_goal(api_client):
    """create_goal delegates to POST /goals."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"id": "goal-1"})
    )
    result = await api_client.create_goal(title="Ship v2")
    assert result.success is True
    api_client._client.request.assert_called_once()
    method, path = api_client._client.request.call_args[0][:2]
    assert method == "POST"
    assert "/goals" in path


@pytest.mark.asyncio
async def test_set_memory(api_client):
    """set_memory delegates to POST /memories."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"key": "foo"})
    )
    result = await api_client.set_memory("foo", "bar")
    assert result.success is True
    api_client._client.request.assert_called_once()
    method, path = api_client._client.request.call_args[0][:2]
    assert method == "POST"
    assert "/memories" in path


@pytest.mark.asyncio
async def test_delete_goal(api_client):
    """delete_goal delegates to DELETE /goals/{id}."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {})
    )
    result = await api_client.delete_goal("goal-99")
    assert result.success is True
    api_client._client.request.assert_called_once()
    method, path = api_client._client.request.call_args[0][:2]
    assert method == "DELETE"
    assert "/goals/goal-99" in path


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_connection_error(api_client):
    """Connection error returns SkillResult.fail."""
    api_client._client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
    result = await api_client.get("/health")
    assert result.success is False
    assert "failed" in result.error.lower()


@pytest.mark.asyncio
async def test_get_timeout_error(api_client):
    """Timeout returns SkillResult.fail."""
    api_client._client.request = AsyncMock(
        side_effect=httpx.ReadTimeout("read timed out")
    )
    result = await api_client.get("/slow-endpoint")
    assert result.success is False


@pytest.mark.asyncio
async def test_post_http_4xx(api_client):
    """4xx response is propagated as failure."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(422, {"detail": "Validation error"})
    )
    result = await api_client.create_activity(action="test")
    assert result.success is False


@pytest.mark.asyncio
async def test_health_check_available(api_client):
    """health_check returns AVAILABLE on 200."""
    api_client._client.request = AsyncMock(
        return_value=_make_response(200, {"status": "ok"})
    )
    status = await api_client.health_check()
    assert status == SkillStatus.AVAILABLE


@pytest.mark.asyncio
async def test_health_check_error(api_client):
    """health_check returns ERROR on failure."""
    api_client._client.request = AsyncMock(side_effect=httpx.ConnectError("down"))
    status = await api_client.health_check()
    assert status == SkillStatus.ERROR


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures(api_client):
    """Circuit opens after consecutive failures exceed threshold."""
    api_client._client.request = AsyncMock(side_effect=httpx.ConnectError("down"))
    # Trigger failures to open the circuit (threshold=3)
    for _ in range(3):
        await api_client.get("/fail")
    assert api_client._is_circuit_open() is True


@pytest.mark.asyncio
async def test_close_releases_client(api_client):
    """close() sets status to UNAVAILABLE and clears client."""
    await api_client.close()
    assert api_client._status == SkillStatus.UNAVAILABLE
    assert api_client._client is None
