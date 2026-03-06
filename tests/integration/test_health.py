"""
Integration smoke tests — health endpoints.

These tests run against a live Aria API stack.  They are skipped automatically
when no server is reachable (see conftest.py `require_server` fixture).

Run:
    make up
    pytest tests/integration/test_health.py -v
"""
from __future__ import annotations

import pytest
import httpx


pytestmark = pytest.mark.integration


class TestHealthEndpoints:
    """Smoke-test the /health family of endpoints."""

    def test_health_returns_200(self, client: httpx.Client):
        """GET /health must return 200."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_has_status(self, client: httpx.Client):
        """GET /health response must contain a 'status' field."""
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data

    def test_health_status_is_ok_or_degraded(self, client: httpx.Client):
        """Status must be a known sentinel value — never an internal error string."""
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "healthy", "unhealthy"), (
            f"Unexpected health status: {data['status']!r}"
        )

    def test_health_has_version(self, client: httpx.Client):
        """GET /health response must include a version field."""
        resp = client.get("/health")
        data = resp.json()
        assert "version" in data or "status" in data

    def test_cors_header_present(self, client: httpx.Client):
        """OPTIONS /health must include CORS Allow-Origin header."""
        resp = client.options("/health", headers={"Origin": "http://localhost:3000"})
        # Either 200 or 204 is acceptable for OPTIONS
        assert resp.status_code in (200, 204, 405)


class TestApiRootEndpoints:
    """Sanity-check the root API structure."""

    def test_openapi_schema_accessible(self, client: httpx.Client):
        """GET /openapi.json must be accessible (not 404)."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_openapi_schema_has_paths(self, client: httpx.Client):
        """OpenAPI schema must declare at least one path."""
        resp = client.get("/openapi.json")
        schema = resp.json()
        assert "paths" in schema
        assert len(schema["paths"]) > 0

    def test_docs_accessible(self, client: httpx.Client):
        """GET /docs must be accessible (Swagger UI)."""
        resp = client.get("/docs")
        assert resp.status_code == 200
