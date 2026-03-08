#!/usr/bin/env python3
"""Runtime smoke checks for live Aria stack (health, auth, swarm, Aria loop)."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BRAIN_STACK_DIR = REPO_ROOT / "stacks" / "brain"
OUT_PATH = REPO_ROOT / "aria_souvenirs" / "docs" / "runtime_smoke_2026-02-26.json"


def _sh(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True, cwd=str(BRAIN_STACK_DIR), text=True).strip()


def resolve_api_base() -> str:
    host_port = _sh("docker compose port aria-api 8000 | awk -F: '{print $2}'")
    return f"http://127.0.0.1:{host_port}"


def resolve_api_key() -> str:
    return _sh("docker compose exec -T aria-api /bin/sh -lc 'printf %s \"$ARIA_API_KEY\"'")


def request(api_base: str, api_key: str, method: str, path: str, body: dict[str, Any] | None = None, use_key: bool = False) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if use_key and api_key:
        headers["X-API-Key"] = api_key

    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(api_base + path, method=method, headers=headers, data=payload)

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except Exception:
                parsed = raw[:500]
            return {"status": resp.status, "body": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw[:500]
        return {"status": exc.code, "body": parsed}


def main() -> int:
    api_base = resolve_api_base()
    api_key = resolve_api_key()

    report: dict[str, Any] = {
        "api_base": api_base,
        "api_key_configured": bool(api_key),
        "checks": {},
    }

    checks = report["checks"]

    checks["health"] = request(api_base, api_key, "GET", "/api/health")
    checks["status"] = request(api_base, api_key, "GET", "/api/status")
    checks["host_stats"] = request(api_base, api_key, "GET", "/api/host-stats")

    create_body = {"agent_id": "aria", "session_type": "interactive"}
    checks["chat_create_without_key"] = request(
        api_base, api_key, "POST", "/api/engine/chat/sessions", create_body, use_key=False
    )
    checks["chat_create_with_key"] = request(
        api_base, api_key, "POST", "/api/engine/chat/sessions", create_body, use_key=True
    )

    swarm_probe = {
        "topic": "runtime smoke swarm probe",
        "agent_ids": ["aria", "analyst"],
        "rounds": 1,
        "synthesizer_id": "aria",
    }
    checks["swarm_sync"] = request(
        api_base, api_key, "POST", "/api/engine/roundtable/swarm", swarm_probe, use_key=True
    )
    checks["swarm_async"] = request(
        api_base, api_key, "POST", "/api/engine/roundtable/swarm/async", swarm_probe, use_key=True
    )
    swarm_async_body = checks["swarm_async"].get("body") if isinstance(checks["swarm_async"], dict) else None
    swarm_key = None
    if isinstance(swarm_async_body, dict):
        swarm_key = swarm_async_body.get("key") or swarm_async_body.get("session_id")
    if swarm_key:
        checks["swarm_async_status"] = request(
            api_base, api_key, "GET", f"/api/engine/roundtable/swarm/status/{swarm_key}", use_key=True
        )

    session_resp = request(
        api_base,
        api_key,
        "POST",
        "/api/engine/chat/sessions",
        {
            "agent_id": "aria",
            "session_type": "interactive",
            "metadata": {
                "source": "runtime_smoke_2026-02-26",
                "trace": str(uuid.uuid4()),
            },
        },
        use_key=True,
    )
    checks["aria_session_create"] = session_resp

    sid = session_resp.get("body", {}).get("id") if isinstance(session_resp.get("body"), dict) else None
    if sid:
        checks["aria_message"] = request(
            api_base,
            api_key,
            "POST",
            f"/api/engine/chat/sessions/{sid}/messages",
            {
                "content": "Runtime smoke check: reply in one short sentence confirming Aria loop is active.",
                "enable_thinking": False,
                "enable_tools": False,
            },
            use_key=True,
        )
        checks["aria_session_id"] = {"status": 200, "body": {"id": sid}}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    summary = {
        "api_base": report["api_base"],
        "api_key_configured": report["api_key_configured"],
        "health": checks.get("health", {}).get("status"),
        "status": checks.get("status", {}).get("status"),
        "chat_without_key": checks.get("chat_create_without_key", {}).get("status"),
        "chat_with_key": checks.get("chat_create_with_key", {}).get("status"),
        "swarm_sync": checks.get("swarm_sync", {}).get("status"),
        "swarm_async": checks.get("swarm_async", {}).get("status"),
        "aria_session_create": checks.get("aria_session_create", {}).get("status"),
        "aria_message": checks.get("aria_message", {}).get("status"),
        "output": str(OUT_PATH),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
