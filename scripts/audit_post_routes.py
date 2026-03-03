#!/usr/bin/env python3
"""
API POST Route Audit — test key POST endpoints.
Runs inside the aria-api container against localhost:8000.
"""
import asyncio
import httpx
import json

BASE = "http://localhost:8000"

# (method, route, body, expected_status_range)
POST_TESTS = [
    ("POST", "/activities", {"action": "audit_route_test", "skill": "audit", "type": "audit"}, [200, 201]),
    ("POST", "/thoughts", {"content": "[route-audit] test thought", "category": "audit"}, [200, 201]),
    ("POST", "/memories", {"key": "__route_audit__", "value": "probe", "category": "audit"}, [200, 201]),
    ("POST", "/heartbeat", {"beat_number": 0, "status": "healthy", "details": {"route_audit": True}}, [200, 201]),
    ("POST", "/goals", {"title": "[route-audit] test goal", "description": "auto-test", "priority": 3, "status": "pending"}, [200, 201]),
    ("POST", "/hourly-goals", {"hour_slot": 23, "goal_type": "audit", "description": "route audit", "status": "pending"}, [200, 201]),
    ("POST", "/knowledge-graph/entities", {"name": "__route_audit__", "entity_type": "audit", "properties": {"test": True}}, [200, 201]),
    ("POST", "/lessons", {"error_pattern": "route_audit", "error_type": "AuditTest", "resolution": "n/a"}, [200, 201]),
    ("POST", "/security-events", {"threat_level": "LOW", "threat_type": "route_audit", "source": "audit", "blocked": False}, [200, 201]),
    ("POST", "/social", {"content": "[route-audit] test post", "platform": "moltbook", "visibility": "private"}, [200, 201]),
    ("POST", "/performance", {"review_period": "route_audit"}, [200, 201]),
    ("POST", "/proposals", {"title": "[route-audit] test proposal", "description": "audit test", "category": "audit", "risk_level": "low"}, [200, 201]),
    ("POST", "/working-memory", {"key": "__route_wm_audit__", "value": "probe", "category": "audit"}, [200, 201]),
    ("POST", "/skills/invocations", {"skill_name": "audit", "tool_name": "route_test", "duration_ms": 1, "success": True}, [200, 201]),
    ("POST", "/memories/semantic", {"content": "route audit probe", "category": "audit", "importance": 0.1}, [200, 201]),
    ("POST", "/model-usage", {"model": "audit-dummy", "provider": "test", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "success": True}, [200, 201]),
    ("POST", "/sessions", {"agent_id": "audit_test", "session_type": "interactive"}, [200, 201]),
    ("POST", "/tasks", {"task_type": "audit", "description": "route audit probe", "agent_type": "coordinator", "priority": "low"}, [200, 201]),
    ("POST", "/artifacts", None, [200, 201, 422]),  # Needs file upload — 422 expected
    ("POST", "/knowledge-graph/sync-skills", {}, [200, 201]),
    ("POST", "/working-memory/checkpoint", {}, [200, 201]),
    ("POST", "/analysis/patterns/detect", {}, [200, 201]),
    ("POST", "/memories/summarize-session", {}, [200, 201]),
    ("POST", "/agents/db/sync", {}, [200, 201]),
    ("POST", "/lessons/seed", {}, [200, 201]),
    ("POST", "/skills/seed", {}, [200, 201]),
    ("POST", "/models/db/sync", {}, [200, 201]),
    ("POST", "/jobs/sync", {}, [200, 201]),
]


async def run_post_audit():
    passed = 0
    failed = 0
    errors = []

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        for method, route, body, ok_statuses in POST_TESTS:
            try:
                if body is not None:
                    resp = await client.post(route, json=body)
                else:
                    resp = await client.post(route)
                
                if resp.status_code in ok_statuses or resp.status_code < 400:
                    status = "PASS"
                    passed += 1
                else:
                    status = f"{resp.status_code}"
                    failed += 1
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")[:80]
                    except:
                        detail = resp.text[:80]
                    errors.append((route, f"HTTP {resp.status_code}: {detail}"))
                print(f"  {status:4s} | {method} {route}")
            except Exception as e:
                print(f"  ERR  | {method} {route} | {type(e).__name__}: {str(e)[:60]}")
                failed += 1
                errors.append((route, f"{type(e).__name__}: {str(e)[:60]}"))

    print(f"\n{'='*60}")
    print(f"POST ROUTE AUDIT: {passed}/{len(POST_TESTS)} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print("\nFAILURES:")
        for route, reason in errors:
            print(f"  {route}: {reason}")


if __name__ == "__main__":
    asyncio.run(run_post_audit())
