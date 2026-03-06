"""
Integration test conftest — requires a running Aria API stack.

Environment variables:
    ARIA_TEST_BASE_URL   Base URL of the API under test (default: http://localhost:8000)
    ARIA_TEST_TIMEOUT    Request timeout in seconds (default: 10)

Tests are automatically skipped with a descriptive message when the server
is unreachable, so `pytest tests/integration/` is safe to run locally even
without Docker.

Usage (with running stack):
    export ARIA_TEST_BASE_URL=http://localhost:8000
    pytest tests/integration/ -v
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.getenv("ARIA_TEST_BASE_URL", "http://localhost:8000")
TIMEOUT = float(os.getenv("ARIA_TEST_TIMEOUT", "10"))


def _is_server_up() -> bool:
    """Return True if the API is reachable."""
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=3.0)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the running API stack."""
    return BASE_URL


@pytest.fixture(scope="session", autouse=True)
def require_server():
    """Skip the entire integration session if the server is not reachable."""
    if not _is_server_up():
        pytest.skip(
            f"Aria API not reachable at {BASE_URL} — "
            "start the stack with `make up` or set ARIA_TEST_BASE_URL."
        )


@pytest.fixture(scope="session")
def client(base_url: str) -> httpx.Client:
    """Synchronous HTTPX client for integration tests."""
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as c:
        yield c
