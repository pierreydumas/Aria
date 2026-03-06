"""
Integration tests for the artifacts router (S-155).

Tests artifact CRUD endpoints using FastAPI TestClient with mocked filesystem.
Covers: write, read, list, delete, validation, error handling.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src/api is importable
_api_dir = str(Path(__file__).resolve().parent.parent / "src" / "api")
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

from routers.artifacts import router, ALLOWED_CATEGORIES
from security_middleware import SecurityMiddleware, RateLimiter


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def secure_client():
    _app = FastAPI()
    _app.add_middleware(
        SecurityMiddleware,
        rate_limiter=RateLimiter(
            requests_per_minute=1_000,
            requests_per_hour=10_000,
            burst_limit=100,
        ),
        max_body_size=2_000_000,
    )
    _app.include_router(router)
    return TestClient(_app)


# ---------------------------------------------------------------------------
# Write Artifact
# ---------------------------------------------------------------------------

def test_write_artifact_success(client, tmp_path):
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": "Hello Aria",
            "filename": "test.md",
            "category": "memory",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["filename"] == "test.md"
    assert data["category"] == "memory"
    assert (tmp_path / "memory" / "test.md").read_text() == "Hello Aria"


def test_write_artifact_with_subfolder(client, tmp_path):
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": "Deep thought",
            "filename": "note.txt",
            "category": "research",
            "subfolder": "sprint7",
        })
    assert resp.status_code == 200
    assert (tmp_path / "research" / "sprint7" / "note.txt").exists()


def test_write_artifact_invalid_category(client, tmp_path):
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": "nope",
            "filename": "test.md",
            "category": "INVALID_CAT",
        })
    assert resp.status_code == 400
    assert "Invalid category" in resp.json()["detail"]


def test_write_artifact_path_traversal(client, tmp_path):
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": "hack",
            "filename": "../../../etc/passwd",
            "category": "memory",
        })
    assert resp.status_code == 400
    assert "Invalid path segment" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Read Artifact
# ---------------------------------------------------------------------------

def test_read_artifact_success(client, tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "test.log").write_text("line1\nline2")
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts/logs/test.log")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["content"] == "line1\nline2"
    assert data["category"] == "logs"


def test_read_artifact_not_found(client, tmp_path):
    (tmp_path / "logs").mkdir()
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts/logs/missing.txt")
    assert resp.status_code == 404


def test_read_artifact_nested_path_success(client, tmp_path):
    """S-40: Nested artifact paths must be readable with category + subfolder/filename."""
    (tmp_path / "memory" / "logs").mkdir(parents=True)
    (tmp_path / "memory" / "logs" / "work_cycle_2026-02-27_0416.json").write_text('{"ok": true}')
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts/memory/logs/work_cycle_2026-02-27_0416.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["path"] == "memory/logs/work_cycle_2026-02-27_0416.json"


def test_write_artifact_json_content_validation(client, tmp_path):
    """S-39: Writing Markdown content to a .json file must be rejected with HTTP 400."""
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": "# Work Cycle\n\nThis is markdown, not JSON.",
            "filename": "work_cycle_2026-02-27.json",
            "category": "logs",
        })
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.json()["detail"]


def test_write_artifact_valid_json_content(client, tmp_path):
    """S-39: Writing valid JSON to a .json file must succeed."""
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.post("/artifacts", json={
            "content": '{"timestamp": "2026-02-27T14:01:00Z", "job": "work_cycle"}',
            "filename": "work_cycle_2026-02-27.json",
            "category": "logs",
        })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_security_middleware_allows_artifact_markdown_and_sql_content(secure_client, tmp_path):
    """Artifact content should allow stored Markdown and SQL examples."""
    content = (
        "---\n"
        "title: GPT-4o Mini Analysis\n"
        "---\n\n"
        "```sql\n"
        "SELECT * FROM goals;\n"
        "```\n"
    )
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = secure_client.post("/artifacts", json={
            "content": content,
            "filename": "analysis.md",
            "category": "research",
        })
    assert resp.status_code == 200
    assert (tmp_path / "research" / "analysis.md").read_text() == content


def test_security_middleware_still_scans_artifact_metadata(secure_client, tmp_path):
    """Artifact metadata should still be scanned for obviously malicious input."""
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = secure_client.post("/artifacts", json={
            "content": "safe body",
            "filename": "DROP TABLE.md",
            "category": "research",
        })
    assert resp.status_code == 400
    data = resp.json()
    assert data["detail"] == "Request blocked for security reasons"
    assert data["threat_type"] == "sql_injection"


# ---------------------------------------------------------------------------
# List Artifacts
# ---------------------------------------------------------------------------

def test_list_artifacts_all_categories(client, tmp_path):
    for cat in ["logs", "memory", "plans"]:
        d = tmp_path / cat
        d.mkdir()
        (d / "file.md").write_text("x")
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    names = [c["name"] for c in data["categories"]]
    assert "logs" in names
    assert "memory" in names


def test_list_artifacts_by_category(client, tmp_path):
    d = tmp_path / "research"
    d.mkdir()
    (d / "paper1.md").write_text("content1")
    (d / "paper2.md").write_text("content2")
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts", params={"category": "research"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_list_artifacts_empty_category(client, tmp_path):
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.get("/artifacts", params={"category": "research"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Delete Artifact
# ---------------------------------------------------------------------------

def test_delete_artifact_success(client, tmp_path):
    d = tmp_path / "drafts"
    d.mkdir()
    (d / "draft.md").write_text("delete me")
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.delete("/artifacts/drafts/draft.md")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert not (d / "draft.md").exists()


def test_delete_artifact_not_found(client, tmp_path):
    (tmp_path / "drafts").mkdir()
    with patch("routers.artifacts.ARIA_MEMORIES_PATH", tmp_path):
        resp = client.delete("/artifacts/drafts/nope.md")
    assert resp.status_code == 404
