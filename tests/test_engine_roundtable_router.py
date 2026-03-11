"""
Integration tests for the engine_roundtable router (S-155).

Tests roundtable/swarm REST endpoints using FastAPI TestClient with mocked
Roundtable engine and database. Covers: start, list, get, delete, status.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src/api is importable
_api_dir = str(Path(__file__).resolve().parent.parent / "src" / "api")
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

# Stub out DB models before import
sys.modules.setdefault("db", MagicMock())
sys.modules.setdefault("db.models", MagicMock())
sys.modules.setdefault("deps", MagicMock())
sys.modules.setdefault("aria_engine", MagicMock())
sys.modules.setdefault("aria_engine.roundtable", MagicMock())

from routers.engine_roundtable import (  # noqa: E402
    router,
    configure_roundtable,
    _running,
    _completed,
    _get_roundtable,
    RoundtableResponse,
    StartRoundtableRequest,
)


# ---------------------------------------------------------------------------
# Fake result objects
# ---------------------------------------------------------------------------

@dataclass
class FakeTurn:
    agent_id: str = "agent_a"
    round_number: int = 1
    content: str = "I think..."
    duration_ms: int = 500


@dataclass
class FakeRoundtableResult:
    session_id: str = "rt-001"
    topic: str = "Test topic"
    participants: list[str] = field(default_factory=lambda: ["agent_a", "agent_b"])
    rounds: int = 2
    turn_count: int = 4
    synthesis: str = "We agree on X."
    synthesizer_id: str = "main"
    total_duration_ms: int = 3000
    chunked_mode: bool = False
    chunk_count: int = 0
    chunk_notice: str | None = None
    chunk_kind: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime(2026, 2, 24, tzinfo=timezone.utc))
    turns: list[FakeTurn] = field(default_factory=lambda: [FakeTurn(), FakeTurn(agent_id="agent_b")])

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "participants": self.participants,
            "rounds": self.rounds,
            "turn_count": self.turn_count,
            "synthesis": self.synthesis,
            "synthesizer_id": self.synthesizer_id,
            "total_duration_ms": self.total_duration_ms,
            "chunked_mode": self.chunked_mode,
            "chunk_count": self.chunk_count,
            "chunk_notice": self.chunk_notice,
            "chunk_kind": self.chunk_kind,
            "created_at": self.created_at.isoformat(),
            "turns": [
                {"agent_id": t.agent_id, "round": t.round_number,
                 "content": t.content, "duration_ms": t.duration_ms}
                for t in self.turns
            ],
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _cleanup_state():
    """Clean up module-level state between tests."""
    _running.clear()
    _completed.clear()
    yield
    _running.clear()
    _completed.clear()


@pytest.fixture
def mock_roundtable():
    rt = AsyncMock()
    rt.discuss = AsyncMock(return_value=FakeRoundtableResult())
    rt.list_roundtables = AsyncMock(return_value=[])
    return rt


@pytest.fixture
def app(mock_roundtable):
    _app = FastAPI()
    _app.include_router(router)
    # Override the dependency that provides the Roundtable instance
    _app.dependency_overrides[_get_roundtable] = lambda: mock_roundtable
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Start Roundtable (synchronous)
# ---------------------------------------------------------------------------

def test_start_roundtable_success(client, mock_roundtable):
    with patch("routers.engine_roundtable._validate_requested_agents", new_callable=AsyncMock):
        resp = client.post("/engine/roundtable", json={
            "topic": "Test discussion",
            "agent_ids": ["agent_a", "agent_b"],
            "rounds": 2,
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["session_id"] == "rt-001"
    assert data["topic"] == "Test topic"
    assert data["turn_count"] == 4
    assert data["synthesis"] == "We agree on X."


def test_start_roundtable_chunk_metadata_passthrough(client, mock_roundtable):
    fake_result = FakeRoundtableResult(
        chunked_mode=True,
        chunk_count=3,
        chunk_notice="Chunked synthesis mode activated.",
        chunk_kind="roundtable_synthesis",
    )
    mock_roundtable.discuss = AsyncMock(return_value=fake_result)

    with patch("routers.engine_roundtable._validate_requested_agents", new_callable=AsyncMock):
        resp = client.post("/engine/roundtable", json={
            "topic": "Chunky discussion",
            "agent_ids": ["agent_a", "agent_b"],
            "rounds": 2,
        })

    assert resp.status_code == 201
    data = resp.json()
    assert data["chunked_mode"] is True
    assert data["chunk_count"] == 3
    assert data["chunk_notice"] == "Chunked synthesis mode activated."
    assert data["chunk_kind"] == "roundtable_synthesis"


def test_start_roundtable_too_few_agents(client):
    resp = client.post("/engine/roundtable", json={
        "topic": "Bad",
        "agent_ids": ["only_one"],
        "rounds": 1,
    })
    assert resp.status_code == 422  # Pydantic validation error


def test_start_roundtable_missing_topic(client):
    resp = client.post("/engine/roundtable", json={
        "topic": "",
        "agent_ids": ["a", "b"],
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List Roundtables
# ---------------------------------------------------------------------------

def test_list_roundtables(client, mock_roundtable):
    resp = client.get("/engine/roundtable")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1


# ---------------------------------------------------------------------------
# Get Roundtable by ID
# ---------------------------------------------------------------------------

def test_get_roundtable_from_cache(client):
    _completed["rt-001"] = FakeRoundtableResult()
    resp = client.get("/engine/roundtable/rt-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "rt-001"
    assert data["synthesis"] == "We agree on X."


def test_get_roundtable_not_found(client):
    with patch("routers.engine_roundtable._db_session", None):
        resp = client.get("/engine/roundtable/nonexistent")
    assert resp.status_code == 503  # DB not available


# ---------------------------------------------------------------------------
# Status (async tracking)
# ---------------------------------------------------------------------------

def test_get_status_running(client):
    _running["abc123"] = {
        "status": "running",
        "topic": "Test",
        "participants": ["a", "b"],
    }
    resp = client.get("/engine/roundtable/status/abc123")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_get_status_not_found(client):
    resp = client.get("/engine/roundtable/status/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete Roundtable
# ---------------------------------------------------------------------------

def test_delete_roundtable_no_db(client):
    with patch("routers.engine_roundtable._db_session", None):
        resp = client.delete("/engine/roundtable/rt-001")
    assert resp.status_code == 503
