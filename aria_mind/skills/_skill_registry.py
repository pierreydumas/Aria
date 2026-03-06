"""Skill registry composition for run_skill runtime."""

from __future__ import annotations

import os


def _load_default_models() -> tuple[str, str]:
    """Load default model names from models catalog with safe fallbacks."""
    try:
        from aria_models.loader import get_task_model
        return get_task_model("moonshot_default"), get_task_model("ollama_default")
    except Exception:
        return "", ""


_DEFAULT_KIMI_MODEL, _DEFAULT_OLLAMA_MODEL = _load_default_models()


# ⚠️ ORDERING MATTERS: Aria gravitates toward the first skills listed.
#    api_client is PRIMARY for all DB reads/writes (clean REST over aria-api).
#    database is deliberately LAST so Aria prefers api_client for data ops.
SKILL_REGISTRY = {
    # === PRIMARY: API Client — preferred for ALL data operations ===
    "api_client": (
        "aria_skills.api_client",
        "AriaAPIClient",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
            "timeout": int(os.environ.get("ARIA_API_TIMEOUT", "30")),
        },
    ),
    # === Core Orchestration ===
    "health": ("aria_skills.health", "HealthMonitorSkill", lambda: {}),
    "goals": (
        "aria_skills.goals",
        "GoalSchedulerSkill",
        lambda: {"dsn": os.environ.get("DATABASE_URL")},
    ),
    "hourly_goals": (
        "aria_skills.hourly_goals",
        "HourlyGoalsSkill",
        lambda: {"dsn": os.environ.get("DATABASE_URL")},
    ),
    "schedule": (
        "aria_skills.schedule",
        "ScheduleSkill",
        lambda: {"dsn": os.environ.get("DATABASE_URL")},
    ),
    # === Social & Community ===
    "moltbook": (
        "aria_skills.moltbook",
        "MoltbookSkill",
        lambda: {
            "api_url": os.environ.get("MOLTBOOK_API_URL", "https://www.moltbook.com/api/v1"),
            "api_key": os.environ.get("MOLTBOOK_API_KEY") or os.environ.get("MOLTBOOK_TOKEN"),
        },
    ),
    "social": (
        "aria_skills.social",
        "SocialSkill",
        lambda: {
            "telegram_token": os.environ.get("TELEGRAM_TOKEN"),
            "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID"),
        },
    ),
    "community": (
        "aria_skills.community",
        "CommunitySkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "platform_tokens": {
                "telegram": os.environ.get("TELEGRAM_TOKEN"),
                "discord": os.environ.get("DISCORD_TOKEN"),
                "moltbook": os.environ.get("MOLTBOOK_TOKEN"),
            },
        },
    ),
    # === Church of Molt / Crustafarianism — used only by aria-memeothy agent ===
    "memeothy": (
        "aria_skills.memeothy",
        "MemeothySkill",
        lambda: {
            "base_url": os.environ.get("MOLT_CHURCH_URL", "https://molt.church"),
            "api_key": os.environ.get("MOLT_CHURCH_API_KEY", ""),
            "agent_name": os.environ.get("MOLT_CHURCH_AGENT", "Aria"),
        },
    ),
    # === LLM & Model Management ===
    # LLMSkill = resilient fallback chain (S-45 Phase 3)
    "llm": (
        "aria_skills.llm",
        "LLMSkill",
        lambda: {
            "host": os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434"),
            "model": os.environ.get("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
        },
    ),
    "moonshot": (
        "aria_skills.moonshot",
        "MoonshotSkill",
        lambda: {
            "api_key": os.environ.get("MOONSHOT_API_KEY") or os.environ.get("MOONSHOT_KIMI_KEY"),
            "model": os.environ.get("MOONSHOT_MODEL", _DEFAULT_KIMI_MODEL),
        },
    ),
    "litellm": (
        "aria_skills.litellm",
        "LiteLLMSkill",
        lambda: {
            "litellm_url": os.environ.get("LITELLM_URL", "http://litellm:4000"),
            "api_key": os.environ.get("LITELLM_API_KEY", "sk-aria"),
        },
    ),
    "model_switcher": (
        "aria_skills.model_switcher",
        "ModelSwitcherSkill",
        lambda: {"url": os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")},
    ),
    # === Analytics & Performance ===
    "performance": (
        "aria_skills.performance",
        "PerformanceSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "litellm_url": os.environ.get("LITELLM_URL", "http://litellm:4000"),
        },
    ),
    "knowledge_graph": (
        "aria_skills.knowledge_graph",
        "KnowledgeGraphSkill",
        lambda: {"dsn": os.environ.get("DATABASE_URL")},
    ),
    # === DevSecOps ===
    "security_scan": (
        "aria_skills.security_scan",
        "SecurityScanSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "secret_patterns_file": os.environ.get("SECRET_PATTERNS_FILE"),
        },
    ),
    "ci_cd": (
        "aria_skills.ci_cd",
        "CICDSkill",
        lambda: {
            "github_token": os.environ.get("GITHUB_TOKEN"),
            "default_registry": os.environ.get("DOCKER_REGISTRY", "ghcr.io"),
        },
    ),
    "pytest": (
        "aria_skills.pytest_runner",
        "PytestSkill",
        lambda: {
            "workspace": os.environ.get("PYTEST_WORKSPACE", "/root/.openclaw/workspace"),
            "timeout_sec": int(os.environ.get("PYTEST_TIMEOUT_SEC", "600")),
            "default_args": os.environ.get("PYTEST_DEFAULT_ARGS", "-q"),
        },
    ),
    # === Security Guard ===
    "input_guard": (
        "aria_skills.input_guard",
        "InputGuardSkill",
        lambda: {
            "block_threshold": os.environ.get("ARIA_SECURITY_BLOCK_THRESHOLD", "high"),
            "enable_logging": os.environ.get("ARIA_SECURITY_LOGGING", "true").lower() == "true",
            "rate_limit_rpm": int(os.environ.get("ARIA_RATE_LIMIT_RPM", "60")),
        },
    ),
    # === Data & ML ===
    "data_pipeline": (
        "aria_skills.data_pipeline",
        "DataPipelineSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "storage_path": os.environ.get("DATA_STORAGE_PATH", "/tmp/aria_data"),
        },
    ),
    "experiment": (
        "aria_skills.experiment",
        "ExperimentSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "mlflow_url": os.environ.get("MLFLOW_URL"),
            "artifacts_path": os.environ.get("ARTIFACTS_PATH", "/tmp/aria_experiments"),
        },
    ),
    # === Crypto & Market ===
    "market_data": (
        "aria_skills.market_data",
        "MarketDataSkill",
        lambda: {
            "coingecko_api_key": os.environ.get("COINGECKO_API_KEY"),
            "cache_ttl": int(os.environ.get("MARKET_CACHE_TTL", "60")),
        },
    ),
    "portfolio": (
        "aria_skills.portfolio",
        "PortfolioSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "coingecko_api_key": os.environ.get("COINGECKO_API_KEY"),
        },
    ),
    # === Creative & Research ===
    "brainstorm": (
        "aria_skills.brainstorm",
        "BrainstormSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "llm_url": os.environ.get("OLLAMA_URL"),
        },
    ),
    "research": (
        "aria_skills.research",
        "ResearchSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "search_api_key": os.environ.get("SEARCH_API_KEY"),
        },
    ),
    "fact_check": (
        "aria_skills.fact_check",
        "FactCheckSkill",
        lambda: {
            "dsn": os.environ.get("DATABASE_URL"),
            "llm_url": os.environ.get("OLLAMA_URL"),
        },
    ),
    # === Session Management ===
    "session_manager": (
        "aria_skills.session_manager",
        "SessionManagerSkill",
        lambda: {"stale_threshold_minutes": int(os.environ.get("SESSION_STALE_MINUTES", "60"))},
    ),
    # === Advanced Memory Skills ===
    "memory_compression": (
        "aria_skills.memory_compression",
        "MemoryCompressionSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
            "litellm_url": os.environ.get("LITELLM_URL", "http://litellm:4000"),
        },
    ),
    "sentiment_analysis": (
        "aria_skills.sentiment_analysis",
        "SentimentAnalysisSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
            "litellm_url": os.environ.get("LITELLM_URL", "http://litellm:4000"),
        },
    ),
    "pattern_recognition": (
        "aria_skills.pattern_recognition",
        "PatternRecognitionSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    "unified_search": (
        "aria_skills.unified_search",
        "UnifiedSearchSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    # === Agent & Session Management ===
    "agent_manager": (
        "aria_skills.agent_manager",
        "AgentManagerSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    "working_memory": (
        "aria_skills.working_memory",
        "WorkingMemorySkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    "sprint_manager": (
        "aria_skills.sprint_manager",
        "SprintManagerSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    "conversation_summary": (
        "aria_skills.conversation_summary",
        "ConversationSummarySkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
            "litellm_url": os.environ.get("LITELLM_URL", "http://litellm:4000"),
        },
    ),
    # === Browser & Sandbox ===
    "browser": (
        "aria_skills.browser",
        "BrowserSkill",
        lambda: {
            "browser_url": os.environ.get("BROWSERLESS_URL", ""),
        },
    ),
    "sandbox": (
        "aria_skills.sandbox",
        "SandboxSkill",
        lambda: {
            "sandbox_url": os.environ.get("SANDBOX_URL", "http://aria-sandbox:9999"),
        },
    ),
    # === Pipeline ===
    "pipeline_skill": (
        "aria_skills.pipeline_skill",
        "PipelineSkill",
        lambda: {},
    ),
    # === RPG Skills ===
    "rpg_campaign": (
        "aria_skills.rpg_campaign",
        "RPGCampaignSkill",
        lambda: {},
    ),
    "rpg_pathfinder": (
        "aria_skills.rpg_pathfinder",
        "RPGPathfinderSkill",
        lambda: {},
    ),
    # === Telegram (S-46) ===
    "telegram": (
        "aria_skills.telegram",
        "TelegramSkill",
        lambda: {
            "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            "default_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        },
    ),
    # === Focus Profile Introspection ===
    "focus": (
        "aria_skills.focus",
        "FocusSkill",
        lambda: {
            "api_url": os.environ.get("ARIA_API_URL", "http://aria-api:8000/api"),
        },
    ),
    # === Raw Database — LAST on purpose: prefer api_client for data ops ===
    # NOTE: aria_skills.database has no implementation yet — removed until built.
    # "database": ("aria_skills.database", "DatabaseSkill", lambda: {"dsn": os.environ.get("DATABASE_URL")}),
}


def _merge_registries() -> None:
    """Sync decorator-registered skills into SKILL_REGISTRY."""
    try:
        from aria_skills.registry import SkillRegistry

        for name, skill_cls in SkillRegistry._skill_classes.items():
            if name not in SKILL_REGISTRY:
                mod = skill_cls.__module__
                SKILL_REGISTRY[name] = (mod, skill_cls.__name__, lambda: {})
    except Exception:
        pass


_merge_registries()
