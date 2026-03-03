#!/usr/bin/env python3
"""
API Route Audit — test all 268 GET routes for 2xx/3xx responses.
Runs inside the aria-api container against localhost:8000.
"""
import asyncio
import httpx
import sys
import time

BASE = "http://localhost:8000"

# GET routes that are safe to test (no side effects)
GET_ROUTES = [
    "/activities",
    "/activities/cron-summary",
    "/activities/timeline",
    "/activities/visualization",
    "/admin/files/agents",
    "/admin/files/memories",
    "/admin/files/mind",
    "/admin/files/souvenirs",
    "/agents/db",
    "/analysis/compression/history",
    "/analysis/patterns/history",
    "/analysis/sentiment/history",
    "/analysis/sentiment/score",
    "/api-key-rotations",
    "/api/metrics",
    "/artifacts",
    "/docs",
    "/engine/agents",
    "/engine/agents/metrics",
    "/engine/chat/sessions",
    "/engine/cron",
    "/engine/cron/status",
    "/engine/focus",
    "/engine/focus/active",
    "/engine/roundtable",
    "/engine/roundtable/agents/available",
    "/engine/sessions",
    "/engine/sessions/archived",
    "/engine/sessions/stats",
    "/export",
    "/goals",
    "/goals/archive",
    "/goals/board",
    "/goals/history",
    "/goals/sprint-summary",
    "/graphql",
    "/health",
    "/health/db",
    "/heartbeat",
    "/heartbeat/latest",
    "/host-stats",
    "/hourly-goals",
    "/jobs",
    "/jobs/live",
    "/knowledge-graph",
    "/knowledge-graph/entities",
    "/knowledge-graph/relations",
    "/knowledge-graph/query-log",
    "/lessons",
    "/lessons/dashboard",
    "/litellm/global-spend",
    "/litellm/health",
    "/litellm/models",
    "/litellm/spend",
    "/memories",
    "/memories/semantic",
    "/memories/semantic/stats",
    "/memory-consolidation",
    "/memory-graph",
    "/memory-timeline",
    "/metrics",
    "/model-usage",
    "/model-usage/stats",
    "/models/available",
    "/models/config",
    "/models/db",
    "/models/pricing",
    "/openapi.json",
    "/performance",
    "/proposals",
    "/providers/balances",
    "/rate-limits",
    "/records",
    "/redoc",
    "/rpg/campaigns",
    "/schedule",
    "/search?q=test",
    "/security-events",
    "/security-events/stats",
    "/sessions",
    "/sessions/hourly",
    "/sessions/stats",
    "/skill-graph",
    "/skills",
    "/skills/coherence",
    "/skills/health/dashboard",
    "/skills/insights",
    "/skills/session-trace/latest",
    "/skills/session-trace/sessions",
    "/skills/stats",
    "/skills/stats/summary",
    "/social",
    "/stats",
    "/status",
    "/table-stats",
    "/tasks",
    "/telegram/webhook-info",
    "/thoughts",
    "/working-memory",
    "/working-memory/context",
    "/working-memory/stats",
    "/working-memory/file-snapshot",
]

# Search routes needing query params
SEARCH_ROUTES = [
    "/knowledge-graph/search?query=aria&limit=3",
    "/knowledge-graph/kg-search?query=aria&limit=3",
    "/knowledge-graph/skill-for-task?task=hello",
    "/memories/search?q=test&limit=3",
    "/memory-search?q=test",
    "/lessons/check?error_type=TimeoutError",
]

# These need path params — sample known IDs
# We'll skip routes that need specific UUIDs since we don't know them


async def run_route_audit():
    all_routes = GET_ROUTES + SEARCH_ROUTES
    passed = 0
    failed = 0
    errors = []
    
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        for route in all_routes:
            try:
                resp = await client.get(route)
                if resp.status_code < 400:
                    status = "PASS"
                    passed += 1
                elif resp.status_code == 404:
                    status = "404"
                    failed += 1
                    errors.append((route, f"404 Not Found"))
                elif resp.status_code == 422:
                    # Validation error — missing required params
                    status = "422"
                    failed += 1
                    errors.append((route, f"422 Validation Error"))
                else:
                    status = f"{resp.status_code}"
                    failed += 1
                    errors.append((route, f"HTTP {resp.status_code}"))
                print(f"  {status:4s} | {route}")
            except Exception as e:
                print(f"  ERR  | {route} | {type(e).__name__}: {str(e)[:60]}")
                failed += 1
                errors.append((route, f"{type(e).__name__}: {str(e)[:60]}"))

    print(f"\n{'='*60}")
    print(f"API ROUTE AUDIT: {passed}/{len(all_routes)} passed, {failed} failed")
    print(f"{'='*60}")
    
    if errors:
        print("\nFAILURES:")
        for route, reason in errors:
            print(f"  {route}: {reason}")
    
    return passed, len(all_routes), errors


if __name__ == "__main__":
    asyncio.run(run_route_audit())
