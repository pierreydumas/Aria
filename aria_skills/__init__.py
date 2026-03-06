# aria_skills/__init__.py
"""
Aria Skills - API-safe skill interfaces

Skills are modular capabilities that Aria can use to interact
with external systems (APIs, databases, services).

Each skill:
- Has a clear interface
- Handles its own authentication
- Implements rate limiting
- Provides health checks
- Logs all operations

NEW STRUCTURE (v2.0):
Each skill is now a subdirectory containing:
- __init__.py  - Python implementation
- skill.json   - Aria manifest
- SKILL.md     - Documentation (optional)

Usage:
    from aria_skills import SkillRegistry
    
    registry = SkillRegistry()
    await registry.load_from_config("aria_mind/TOOLS.md")
    
    moltbook = registry.get("moltbook")
    await moltbook.post_status("Hello world!")
"""

__version__ = "3.0.0"

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

# Import skill implementations from subdirectories
from aria_skills.moltbook import MoltbookSkill
from aria_skills.moonshot import MoonshotSkill          # v2 canonical
from aria_skills.ollama import OllamaSkill              # v2 canonical
from aria_skills.health import HealthMonitorSkill
from aria_skills.goals import GoalSchedulerSkill
from aria_skills.knowledge_graph import KnowledgeGraphSkill
from aria_skills.pytest_runner import PytestSkill

# Communication skills (v1.1.0)
from aria_skills.performance import PerformanceSkill
from aria_skills.social import SocialSkill
from aria_skills.hourly_goals import HourlyGoalsSkill
from aria_skills.litellm import LiteLLMSkill
from aria_skills.schedule import ScheduleSkill

# Focus-specific skills (v1.2.0)
from aria_skills.security_scan import SecurityScanSkill
from aria_skills.ci_cd import CICDSkill
from aria_skills.data_pipeline import DataPipelineSkill

# Security skill (v1.3.0) - Runtime input protection
from aria_skills.input_guard import InputGuardSkill

# API Client (v1.3.0) - Centralized HTTP client
from aria_skills.api_client import AriaAPIClient, get_api_client
from aria_skills.market_data import MarketDataSkill
from aria_skills.portfolio import PortfolioSkill
from aria_skills.research import ResearchSkill

# Pipeline Engine (v1.4.0) — Cognitive multi-step workflows
from aria_skills.pipeline_skill import PipelineSkill

# Agent & Runtime Skills (v1.1)
from aria_skills.agent_manager import AgentManagerSkill
from aria_skills.sandbox import SandboxSkill
from aria_skills.telegram import TelegramSkill
from aria_skills.working_memory import WorkingMemorySkill

# Advanced Memory Skills (v2.0)
from aria_skills.memory_compression import MemoryCompressionSkill
from aria_skills.sentiment_analysis import SentimentAnalysisSkill
from aria_skills.pattern_recognition import PatternRecognitionSkill
from aria_skills.unified_search import UnifiedSearchSkill

# Additional registered skills (v3.0 audit)
from aria_skills.conversation_summary import ConversationSummarySkill
from aria_skills.memeothy import MemeothySkill
from aria_skills.session_manager import SessionManagerSkill
from aria_skills.sprint_manager import SprintManagerSkill

# Model management (v3.1)
from aria_skills.model_switcher import ModelSwitcherSkill

# RPG Skills (v3.1 — Pathfinder 2e)
from aria_skills.rpg_pathfinder import RPGPathfinderSkill
from aria_skills.rpg_campaign import RPGCampaignSkill

__all__ = [
    # Base classes
    "BaseSkill",
    "SkillConfig",
    "SkillResult",
    "SkillStatus",
    "SkillRegistry",
    # Core Skills
    "MoltbookSkill",
    "OllamaSkill",  # Default LLM (local)
    "MoonshotSkill",
    "KnowledgeGraphSkill",
    "HealthMonitorSkill",
    "GoalSchedulerSkill",
    "PytestSkill",
    # Communication Skills (v1.1.0)
    "PerformanceSkill",
    "SocialSkill",
    "HourlyGoalsSkill",
    "LiteLLMSkill",
    "ScheduleSkill",
    # Security (v1.3.0)
    "InputGuardSkill",
    # Focus-Specific Skills (v1.2.0)
    "SecurityScanSkill",      # DevSecOps
    "CICDSkill",              # DevSecOps
    "DataPipelineSkill",      # Data Architect
    "MarketDataSkill",        # Crypto Trader
    "PortfolioSkill",         # Crypto Trader
    "ResearchSkill",          # Journalist
    # API Client
    "AriaAPIClient",
    "get_api_client",
    # Pipeline Engine (v1.4.0)
    "PipelineSkill",
    # Agent & Runtime Skills (v1.1)
    "AgentManagerSkill",
    "SandboxSkill",
    "TelegramSkill",
    "WorkingMemorySkill",
    # Advanced Memory Skills (v2.0)
    "MemoryCompressionSkill",
    "SentimentAnalysisSkill",
    "PatternRecognitionSkill",
    "UnifiedSearchSkill",
    # Additional Skills (v3.0 audit)
    "ConversationSummarySkill",
    "MemeothySkill",
    "SessionManagerSkill",
    "SprintManagerSkill",
    # RPG Skills (v3.1 — Pathfinder 2e)
    "RPGPathfinderSkill",
    "RPGCampaignSkill",
    # Model management (v3.1)
    "ModelSwitcherSkill",
]
