#!/usr/bin/env python3
"""Fail-fast guardrail for Mac/Web -> Docker API path regressions.

Validates:
1) Direct API protected route rejects missing key (401).
2) Flask web proxy /api path accepts POST without CSRF token (201).
3) Traefik HTTP /api path injects API key server-side (201).
4) Traefik HTTPS /api path injects API key server-side (201).

Exit code is non-zero on any failed assertion.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_DIR = REPO_ROOT / "stacks" / "brain"


@dataclass
class CheckResult:
    name: str
    url: str
    expected: int
    actual: int
    ok: bool
    body_preview: str


def _compose_port(service: str, container_port: int) -> int:
    out = subprocess.check_output(
        ["docker", "compose", "port", service, str(container_port)],
        cwd=STACK_DIR,
        text=True,
    ).strip()
    return int(out.rsplit(":", 1)[1])


def _request(method: str, url: str, payload: dict | None = None, insecure_tls: bool = False) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})

    context = ssl._create_unverified_context() if insecure_tls else None

    try:
        with urllib.request.urlopen(req, timeout=45, context=context) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return exc.code, body


def _run_check(name: str, url: str, expected: int, insecure_tls: bool = False) -> CheckResult:
    status, body = _request(
        "POST",
        url,
        payload={"agent_id": "aria", "session_type": "interactive"},
        insecure_tls=insecure_tls,
    )
    return CheckResult(
        name=name,
        url=url,
        expected=expected,
        actual=status,
        ok=(status == expected),
        body_preview=body[:220].replace("\n", " "),
    )


def main() -> int:
    api_port = _compose_port("aria-api", 8000)
    web_port = _compose_port("aria-web", 5000)
    traefik_http_port = _compose_port("traefik", 80)
    traefik_https_port = _compose_port("traefik", 443)

    checks = [
        _run_check(
            name="direct_api_requires_key",
            url=f"http://127.0.0.1:{api_port}/api/engine/chat/sessions",
            expected=401,
        ),
        _run_check(
            name="web_proxy_csrf_exempt_and_key_injected",
            url=f"http://127.0.0.1:{web_port}/api/engine/chat/sessions",
            expected=201,
        ),
        _run_check(
            name="traefik_http_key_injected",
            url=f"http://127.0.0.1:{traefik_http_port}/api/engine/chat/sessions",
            expected=201,
        ),
        _run_check(
            name="traefik_https_key_injected",
            url=f"https://127.0.0.1:{traefik_https_port}/api/engine/chat/sessions",
            expected=201,
            insecure_tls=True,
        ),
    ]

    print("\nGuardrail results:\n")
    has_failures = False
    for result in checks:
        mark = "PASS" if result.ok else "FAIL"
        print(f"- {mark:4} {result.name}: expected={result.expected} got={result.actual} url={result.url}")
        if not result.ok:
            has_failures = True
            print(f"  body: {result.body_preview}")

    if has_failures:
        print("\nGuardrail FAILED: Mac/Web -> Docker API path regression detected.")
        return 1

    print("\nGuardrail PASSED: CSRF exemption and Traefik API key injection are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
