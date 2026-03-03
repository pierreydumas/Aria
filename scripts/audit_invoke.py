#!/usr/bin/env python3
"""Audit invocation script — test all tools for a given skill."""
import asyncio
import json
import sys
import importlib
import inspect
import traceback
import os

sys.path.insert(0, "/")

# Force imports from bind-mounted /aria_skills/ over baked /app/aria_skills/
# Remove /app from sys.path so Python picks up the bind-mount first
sys.path = [p for p in sys.path if not p.startswith("/app")]
sys.path.insert(0, "/")

# Clear cached modules to pick up bind-mounted code
for k in list(sys.modules):
    if "aria_skills" in k:
        del sys.modules[k]

from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ─────────────────────────────────────────────────────────────────────────
# Test definitions per skill
# ─────────────────────────────────────────────────────────────────────────
TESTS = {
    "api_client": [
        # GET-only (read-safe)
        ("get_activities", {"limit": 3}),
        ("get_security_events", {"limit": 3}),
        ("get_security_stats", {}),
        ("get_thoughts", {"limit": 3}),
        ("get_memories", {"limit": 3}),
        ("get_memory", {"key": "__audit_nonexistent__"}),
        ("get_goals", {"limit": 3}),
        ("get_goal_board", {"sprint": "current"}),
        ("get_goal_archive", {"limit": 3}),
        ("get_sprint_summary", {"sprint": "current"}),
        ("get_goal_history", {"days": 1}),
        ("get_hourly_goals", {}),
        ("get_knowledge_graph", {}),
        ("get_entities", {"limit": 3}),
        ("graph_search", {"query": "aria", "limit": 3}),
        ("kg_search", {"query": "aria", "limit": 3}),
        ("find_skill_for_task", {"task": "send a message", "limit": 3}),
        ("get_query_log", {"limit": 3}),
        ("get_social_posts", {"limit": 3}),
        ("get_heartbeats", {"limit": 3}),
        ("get_latest_heartbeat", {}),
        ("get_performance_logs", {"limit": 3}),
        ("get_tasks", {}),
        ("get_schedule", {}),
        ("get_jobs", {}),
        ("get_sessions", {"limit": 3}),
        ("get_session_stats", {}),
        ("get_model_usage", {"limit": 3}),
        ("get_model_usage_stats", {"hours": 1}),
        ("get_litellm_models", {}),
        ("get_litellm_health", {}),
        ("get_litellm_spend", {"limit": 3}),
        ("get_provider_balances", {}),
        ("recall", {"limit": 3}),
        ("get_working_memory_context", {"limit": 3}),
        ("search_memories_semantic", {"query": "test", "limit": 3}),
        ("list_semantic_memories", {"limit": 3}),
        ("get_memory_stats", {}),
        ("check_known_errors", {"error_type": "TimeoutError"}),
        ("get_lessons", {}),
        ("get_proposals", {}),
        ("get_skill_stats", {"hours": 1}),
        ("list_artifacts", {"limit": 3}),
        ("list_agents", {}),
        ("list_jobs", {}),
        ("get_reviews", {"limit": 3}),
        ("sprint_status", {}),
        ("kg_query", {"entity_type": "skill"}),
        # Harmless writes
        ("create_activity", {"action": "audit_test", "skill": "api_client", "details": {"audit": True}, "success": True}),
        ("create_security_event", {"threat_level": "LOW", "threat_type": "audit_test", "source": "audit", "blocked": False}),
        ("create_thought", {"content": "[audit] connectivity test", "category": "audit"}),
        ("set_memory", {"key": "__audit_test__", "value": "audit_probe", "category": "audit"}),
        ("create_heartbeat", {"beat_number": 0, "status": "healthy", "details": {"audit": True}}),
        ("create_performance_log", {"review_period": "audit_test"}),
        ("create_entity", {"name": "__audit_entity__", "entity_type": "audit", "properties": {"test": True}}),
        ("create_social_post", {"content": "[audit] connectivity test", "platform": "moltbook", "visibility": "private"}),
        ("record_invocation", {"skill_name": "api_client", "tool_name": "audit_test", "duration_ms": 1, "success": True}),
        ("record_lesson", {"error_pattern": "audit_test", "error_type": "AuditTest", "resolution": "n/a"}),
        ("remember", {"key": "__audit_wm__", "value": "probe", "category": "audit", "importance": 0.1}),
        ("store_memory_semantic", {"content": "audit connectivity probe", "category": "audit", "importance": 0.1}),
        ("write_artifact", {"content": "audit probe", "filename": "__audit_test__.txt", "category": "logs"}),
        ("read_artifact", {"category": "logs", "filename": "__audit_test__.txt"}),
        # Idempotent POST
        ("sync_skill_graph", {}),
        ("working_memory_checkpoint", {}),
        ("detect_patterns", {"limit": 5}),
    ],
    "input_guard": [
        ("analyze_input", {"text": "hello world", "source": "user"}),
        ("sanitize_for_html", {"text": "<script>alert(1)</script>"}),
        ("check_sql_safety", {"text": "1; DROP TABLE users;--"}),
        ("check_path_safety", {"path": "../../etc/passwd"}),
        ("filter_output", {"text": "key=sk-abc123secret", "strict": False}),
        ("build_safe_query", {"operation": "select", "table": "goals", "columns": ["id", "title"], "limit": 5}),
        ("get_security_summary", {"hours": 1}),
        ("validate_api_params", {"params": {"name": "test"}, "schema": {"name": "str"}}),
    ],
    # Phase 2 — Infrastructure
    "health": [
        ("check_system", {}),
        ("get_last_check", {}),
        ("check_degradation_level", {}),
        ("apply_degradation_mode", {"level": "healthy"}),
    ],
    "litellm": [
        ("list_models", {}),
    ],
    "llm": [
        ("get_fallback_chain", {}),
        ("get_circuit_status", {}),
        ("reset_circuit_breakers", {}),
    ],
    "model_switcher": [
        ("list_models", {}),
        ("get_current_model", {}),
        ("get_thinking_mode", {}),
        ("get_switch_history", {}),
    ],
    "session_manager": [
        ("list_sessions", {}),
        ("get_session_stats", {}),
    ],
    "browser": [
        ("navigate", {"url": "https://example.com"}),
        ("screenshot", {"url": "https://example.com"}),
    ],
    "moonshot": [
        ("chat", {"messages": [{"role": "user", "content": "Say hello in one word."}], "temperature": 0.1, "max_tokens": 16}),
    ],
    "ollama": [
        ("list_models", {}),
        ("set_model", {"model": "qwen2.5:3b"}),
    ],
    "sandbox": [
        ("run_code", {"code": "print('hello from sandbox')", "timeout": 10}),
        ("write_file", {"path": "/tmp/audit_test.txt", "content": "audit ok"}),
        ("read_file", {"path": "/tmp/audit_test.txt"}),
        ("run_tests", {"test_path": "tests/"}),
    ],
    # Phase 3 — Core Business
    "goals": [
        ("list_goals", {}),
        ("get_next_actions", {}),
    ],
    "working_memory": [
        ("recall", {}),
        ("get_context", {}),
        ("reflect", {}),
    ],
    "unified_search": [
        ("search", {"query": "test", "limit": 3}),
    ],
    "knowledge_graph": [
        ("get_entity", {"query": "aria"}),
        ("query", {}),
    ],
    "social": [
        ("get_posts", {}),
    ],
    "sentiment_analysis": [
        ("analyze_message", {"text": "I love this project!"}),
        ("get_sentiment_history", {}),
    ],
    "conversation_summary": [
        ("summarize_session", {}),
        ("summarize_topic", {"topic": "test"}),
    ],
    "memory_compression": [
        ("get_compression_stats", {}),
    ],
    "pattern_recognition": [
        ("get_pattern_stats", {}),
        ("get_recurring", {}),
        ("get_emerging", {}),
    ],
    "agent_manager": [
        ("list_agents", {}),
        ("get_performance_report", {}),
        ("get_agent_health", {}),
    ],
    "sprint_manager": [
        ("sprint_status", {}),
        ("sprint_report", {}),
    ],
    "fact_check": [
        ("quick_check", {"statement": "Water boils at 100C at sea level"}),
        ("get_verdict_summary", {}),
    ],
    # Phase 4 — Extended
    "brainstorm": [
        ("start_session", {"topic": "test ideas"}),
        ("get_random_prompt", {}),
    ],
    "research": [
        ("list_projects", {}),
    ],
    "ci_cd": [
        ("generate_workflow", {"workflow_type": "test", "language": "python"}),
    ],
    "data_pipeline": [
        ("infer_schema", {"data": [{"a": 1, "b": "hello"}]}),
    ],
    "experiment": [
        ("create_experiment", {"name": "audit_test", "description": "Audit smoke test"}),
    ],
    "security_scan": [
        ("scan_code", {"code": "import os; os.system('rm -rf /')", "language": "python"}),
        ("get_scan_history", {}),
    ],
    "market_data": [
        ("get_market_overview", {}),
        ("search_coins", {"query": "bitcoin"}),
    ],
    "portfolio": [
        ("get_portfolio", {}),
        ("get_transactions", {}),
    ],
    "community": [
        ("get_community_health", {}),
        ("get_growth_strategies", {}),
    ],
    "moltbook": [
        ("get_feed", {}),
    ],
    "memeothy": [
        ("status", {}),
        ("get_prophets", {}),
    ],
    "telegram": [
        ("get_me", {}),
    ],
    "rpg_campaign": [
        ("list_campaigns", {}),
    ],
    "rpg_pathfinder": [
        ("list_characters", {}),
        ("lookup_condition", {"condition": "frightened"}),
    ],
    "pytest_runner": [
        ("get_last_result", {}),
    ],
    # Phase 5 — Orchestration
    "focus": [
        ("focus__list", {}),
        ("focus__status", {}),
    ],
    "hourly_goals": [
        ("get_current_goals", {}),
        ("get_day_summary", {}),
    ],
    "performance": [
        ("get_reviews", {}),
        ("get_improvement_summary", {}),
        ("get_metrics", {}),
    ],
    "schedule": [
        ("list_jobs", {}),
        ("get_due_jobs", {}),
    ],
    "pipeline_skill": [
        ("list_pipelines", {}),
    ],
}


async def get_api_client_singleton():
    """Initialize the shared API client singleton (required by most skills)."""
    try:
        from aria_skills.api_client import get_api_client
        client = await get_api_client()
        return client
    except Exception as e:
        print(f"WARN: api_client init failed: {e}")
        return None


async def test_skill(skill_name: str, tests: list):
    """Test a single skill's tools."""
    # Import the module
    try:
        mod = importlib.import_module(f"aria_skills.{skill_name}")
    except Exception as e:
        print(f"  IMPORT_ERROR: {e}")
        return 0, len(tests), []

    # Find the skill class
    from aria_skills.base import BaseSkill
    skill_cls = None
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, BaseSkill) and obj is not BaseSkill:
            skill_cls = obj
            break

    if not skill_cls:
        print(f"  NO_CLASS found")
        return 0, len(tests), []

    # Instantiate and initialize
    try:
        skill = skill_cls(SkillConfig(name=skill_name))
        ok = await skill.initialize()
        if not ok:
            print(f"  INIT_FAILED")
            # Try running tools anyway
    except Exception as e:
        print(f"  INIT_ERROR: {type(e).__name__}: {e}")
        return 0, len(tests), []

    passed = 0
    failures = []

    for tool_name, args in tests:
        try:
            handler = getattr(skill, tool_name, None)
            if handler is None:
                print(f"  {tool_name}: MISSING_HANDLER")
                failures.append((tool_name, "MISSING_HANDLER"))
                continue

            result = handler(**args)
            if inspect.isawaitable(result):
                result = await result

            if hasattr(result, "success"):
                ok_flag = result.success
                data_preview = str(result.data)[:100] if result.data else str(result.error)[:100]
            else:
                ok_flag = True
                data_preview = str(result)[:100]

            status = "PASS" if ok_flag else "SOFT_FAIL"
            print(f"  {tool_name}: {status} | {data_preview}")
            if ok_flag:
                passed += 1
            else:
                failures.append((tool_name, f"SOFT_FAIL: {data_preview}"))
        except Exception as e:
            print(f"  {tool_name}: EXCEPTION | {type(e).__name__}: {str(e)[:80]}")
            failures.append((tool_name, f"{type(e).__name__}: {str(e)[:80]}"))

    return passed, len(tests), failures


async def run_audit(skills_to_test):
    """Run audit for a list of skills."""
    # Initialize shared API client
    await get_api_client_singleton()

    grand_total = 0
    grand_pass = 0
    grand_fail = 0
    all_failures = []

    for skill_name in skills_to_test:
        tests = TESTS.get(skill_name, [])
        if not tests:
            print(f"\n[{skill_name}] NO TESTS DEFINED — skipped")
            continue

        print(f"\n[{skill_name}] Testing {len(tests)} tools...")
        passed, total, failures = await test_skill(skill_name, tests)
        grand_total += total
        grand_pass += passed
        grand_fail += total - passed
        for tool, reason in failures:
            all_failures.append((skill_name, tool, reason))

    print("\n" + "=" * 60)
    print(f"AUDIT RESULTS: {grand_pass}/{grand_total} passed, {grand_fail} failed")
    print("=" * 60)

    if all_failures:
        print("\nFAILURES:")
        for skill, tool, reason in all_failures:
            print(f"  {skill}.{tool}: {reason}")

    return grand_pass, grand_total, all_failures


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "all":
            skills = list(TESTS.keys())
        elif sys.argv[1] == "phase1":
            skills = ["input_guard"]
        elif sys.argv[1] == "phase2":
            skills = ["health", "litellm", "llm", "model_switcher", "browser",
                      "session_manager", "moonshot", "ollama", "sandbox"]
        elif sys.argv[1] == "phase3":
            skills = ["goals", "working_memory", "unified_search", "knowledge_graph",
                      "social", "sentiment_analysis", "conversation_summary",
                      "memory_compression", "pattern_recognition", "agent_manager",
                      "sprint_manager", "fact_check"]
        elif sys.argv[1] == "phase4":
            skills = ["brainstorm", "research", "ci_cd", "data_pipeline", "experiment",
                      "security_scan", "market_data", "portfolio", "community",
                      "moltbook", "memeothy", "telegram", "rpg_campaign", "rpg_pathfinder",
                      "pytest_runner"]
        elif sys.argv[1] == "phase5":
            skills = ["focus", "hourly_goals", "performance", "schedule", "pipeline_skill"]
        else:
            skills = sys.argv[1:]
    else:
        skills = list(TESTS.keys())

    asyncio.run(run_audit(skills))
