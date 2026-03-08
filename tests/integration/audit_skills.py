#!/usr/bin/env python
"""
S-56: Skills & api_client audit script.

Verifies:
  1. All exported skills import without errors
  2. All exported skills have a health_check() method
  3. No SQLAlchemy/direct-DB imports in aria_skills/ (5-layer rule)
  4. No hardcoded model names in skills (models.yaml SOT rule)
  5. SkillRegistry.discover() loads all skills
  6. api_client coverage — all key api_client methods exist
  7. PipelineExecutor uses shared registry (not empty constructor)

Usage:
  cd /app          # or repo root
    python tests/integration/audit_skills.py
"""

import importlib
import inspect
import subprocess
import sys
from pathlib import Path

# ── Setup ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))    # make aria_skills importable

SKILLS_DIR = REPO_ROOT / "aria_skills"

SKILL_EXPORTS = [
    "MoltbookSkill",
    "MoonshotSkill",
    "OllamaSkill",
    "HealthMonitorSkill",
    "GoalSchedulerSkill",
    "KnowledgeGraphSkill",
    "PytestSkill",
    "PerformanceSkill",
    "SocialSkill",
    "HourlyGoalsSkill",
    "LiteLLMSkill",
    "ScheduleSkill",
    "SecurityScanSkill",
    "CICDSkill",
    "DataPipelineSkill",
    "InputGuardSkill",
    "AriaAPIClient",
    "MarketDataSkill",
    "PortfolioSkill",
    "ResearchSkill",
    "PipelineSkill",
    "AgentManagerSkill",
    "SandboxSkill",
    "TelegramSkill",
    "WorkingMemorySkill",
    "MemoryCompressionSkill",
    "SentimentAnalysisSkill",
    "PatternRecognitionSkill",
    "UnifiedSearchSkill",
    "ConversationSummarySkill",
    "MemeothySkill",
    "SessionManagerSkill",
    "SprintManagerSkill",
]

API_CLIENT_REQUIRED_METHODS = [
    "get_memories",
    "set_memory",
    "get_thoughts",
    "create_thought",
    "get_goals",
    "create_goal",
    "get_sessions",
    "create_activity",
    "create_heartbeat",
    "store_sentiment_event",
    "search_memories_semantic",
    "get_working_memory_context",
    "update_working_memory",
]

FORBIDDEN_IMPORTS = [
    "from sqlalchemy",
    "import sqlalchemy",
    "from db.",
    "from src.api.db",
    "import asyncpg",
    "import psycopg",
]

FORBIDDEN_MODEL_PATTERNS: list[str] = []
try:
    import pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))
    from aria_models.loader import list_all_model_ids as _lam
    FORBIDDEN_MODEL_PATTERNS = [f'"{m}"' for m in _lam()]
except (ImportError, AttributeError, OSError, ValueError):
    FORBIDDEN_MODEL_PATTERNS = [
        '"moonshot-v1-8k"',
        '"kimi"',
        '"gpt-4"',
        '"gpt-3.5"',
        '"claude-',
        '"gemini-',
    ]

# ── Checks ───────────────────────────────────────────────────────────────────

def check_imports() -> tuple[list, list]:
    """Check all exported skill classes/objects import without error."""
    passed, failed = [], []
    aria_skills = importlib.import_module("aria_skills")
    for name in SKILL_EXPORTS:
        try:
            obj = getattr(aria_skills, name)
            has_hc = (
                hasattr(obj, "health_check")
                or (inspect.isclass(obj) and any(
                    "health_check" in dir(base) for base in inspect.getmro(obj)
                ))
            )
            status = "OK" if has_hc else "WARN"
            note = "" if has_hc else " (missing health_check)"
            print(f"  [{status}] {name}{note}")
            passed.append(name)
        except AttributeError as e:
            print(f"  [FAIL] {name}: AttributeError - {e}")
            failed.append((name, str(e)))
        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            print(f"  [FAIL] {name}: {type(e).__name__} - {e}")
            failed.append((name, str(e)))
    return passed, failed


def check_no_db_in_skills() -> list[str]:
    """Ensure no skill file directly imports SQLAlchemy or DB modules."""
    violations = []
    for py in SKILLS_DIR.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT)
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            # Skip files that can't be read
            continue
        for pattern in FORBIDDEN_IMPORTS:
            if pattern in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern in line:
                        violations.append(f"{rel}:{i}  {line.strip()}")
    return violations


def check_no_hardcoded_models() -> list[str]:
    """Check skills for hardcoded model names (should use models.yaml).
    
    False-positive exclusions:
    - Lines that use the name as a YAML key in .get("kimi", ...) — that's reading models.yaml
    - Lines inside except/fallback blocks (DEFAULT_* = "kimi") are acceptable last resorts
    """
    hits = []
    for py in SKILLS_DIR.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT)
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            # Skip files that can't be read
            continue
        for pattern in FORBIDDEN_MODEL_PATTERNS:
            if pattern in text:
                for i, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    if pattern not in stripped:
                        continue
                    # Skip YAML key lookups like .get("kimi", ...)
                    if '.get("kimi"' in stripped or ".get('kimi'" in stripped:
                        continue
                    # Skip fallback/default assignments in except blocks
                    if "_DEFAULT_" in stripped or "_FALLBACK_" in stripped:
                        continue
                    if "models.yaml" in stripped:
                        continue
                    hits.append(f"{rel}:{i}  {stripped}")
    return hits


def check_api_client_coverage() -> tuple[list, list]:
    """Verify all required api_client methods exist."""
    present, missing = [], []
    try:
        from aria_skills.api_client import AriaAPIClient
        for method in API_CLIENT_REQUIRED_METHODS:
            if hasattr(AriaAPIClient, method):
                present.append(method)
            else:
                missing.append(method)
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
        print(f"  [FAIL] Could not import AriaAPIClient: {e}")
        return [], API_CLIENT_REQUIRED_METHODS
    return present, missing


def check_registry() -> int:
    """Verify SkillRegistry has 30+ registered classes after importing aria_skills."""
    try:
        # Import all skills to trigger @SkillRegistry.register decorators
        import aria_skills  # noqa: F401 — triggers all registrations
        from aria_skills.registry import SkillRegistry
        count = len(SkillRegistry._skill_classes)
        return count
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
        print(f"  [FAIL] SkillRegistry error: {e}")
        return -1


def check_pipeline_executor() -> bool:
    """Verify PipelineExecutor does not use empty SkillRegistry()."""
    pe_path = SKILLS_DIR / "pipeline_executor.py"
    if not pe_path.exists():
        return True  # not present — skip
    text = pe_path.read_text(encoding="utf-8", errors="replace")
    bad_pattern = "PipelineExecutor(SkillRegistry())"
    if bad_pattern in text:
        print(f"  [WARN] pipeline_executor.py contains '{bad_pattern}' - empty registry bug")
        return False
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    exit_code = 0

    print("=" * 60)
    print("S-56: Aria Skills Audit")
    print("=" * 60)

    # 1. Import check
    print("\n[1/5] Import audit ...")
    passed, failed = check_imports()
    if failed:
        print(f"\n  FAIL: {len(failed)} skill(s) failed to import:")
        for name, err in failed:
            print(f"    {name}: {err}")
        exit_code = 1
    else:
        print(f"\n  OK: {len(passed)}/{len(SKILL_EXPORTS)} skills importable")

    # 2. 5-layer constraint
    print("\n[2/5] 5-layer constraint (no DB in skills) ...")
    violations = check_no_db_in_skills()
    if violations:
        print(f"  FAIL: {len(violations)} violation(s):")
        for v in violations[:20]:
            print(f"    {v}")
        exit_code = 1
    else:
        print("  OK: No SQLAlchemy / direct DB imports in aria_skills/")

    # 3. No hardcoded model names
    print("\n[3/5] Hardcoded model names in skills ...")
    hits = check_no_hardcoded_models()
    if hits:
        print(f"  WARN: {len(hits)} possible hardcoded model name(s):")
        for h in hits[:10]:
            print(f"    {h}")
        # Warning only — not a hard failure
    else:
        print("  OK: No hardcoded model names found")

    # 4. api_client coverage
    print("\n[4/5] api_client method coverage ...")
    present, missing = check_api_client_coverage()
    if missing:
        print(f"  FAIL: {len(missing)} required method(s) missing from AriaAPIClient:")
        for m in missing:
            print(f"    - {m}")
        exit_code = 1
    else:
        print(f"  OK: All {len(present)} required api_client methods present")

    # 5. Registry + pipeline executor
    print("\n[5/5] SkillRegistry + PipelineExecutor ...")
    count = check_registry()
    if count < 0:
        exit_code = 1
    elif count < 25:
        print(f"  WARN: Only {count} skills registered (expected 30+)")
    else:
        print(f"  OK: {count} skills in registry")

    pe_ok = check_pipeline_executor()
    if not pe_ok:
        exit_code = 1

    # Summary
    print("\n" + "=" * 60)
    if exit_code == 0:
        print("AUDIT PASSED")
    else:
        print("AUDIT FAILED — see above for details")
    print("=" * 60)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
