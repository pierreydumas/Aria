"""
Focus System - Aria's specialized persona overlays.

Focuses are ADDITIVE personality layers that enhance Aria's core identity
without replacing it. Each focus emphasizes specific skills, communication
styles, and model preferences for different types of tasks.

The focus system allows Aria to:
1. Adapt her approach to match task domains
2. Prioritize relevant skills for efficiency
3. Delegate focused work to appropriate sub-agents
4. Maintain core identity while specializing

CRITICAL: Focuses NEVER override Values or Boundaries.

Model hints are loaded from aria_models/models.yaml (criteria.focus_defaults).
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging

_focus_log = logging.getLogger("aria.focus")

# Import model catalog loader - models.yaml is the source of truth
try:
    from aria_models.loader import get_focus_default, load_catalog
    _HAS_CATALOG = True
except ImportError:
    _HAS_CATALOG = False
    def get_focus_default(focus_type: str) -> str | None:
        return None
    def load_catalog():
        return {}


class FocusType(Enum):
    """Available focus personas."""
    ORCHESTRATOR = "orchestrator"    # Coordinator/Exec Manager (DEFAULT)
    DEVSECOPS = "devsecops"          # Security-first engineering
    DATA = "data"                    # Data Science/MLOps/Architect
    TRADER = "trader"                # Crypto/Market analysis
    CREATIVE = "creative"            # Creative/Adventurer
    SOCIAL = "social"                # Social Media/Startuper
    JOURNALIST = "journalist"        # Reporter/Investigator


# Focus defaults loaded from models.yaml (single source of truth)
_FALLBACK_MODEL_HINTS: dict[str, str] = {}
try:
    _cat = load_catalog()
    _FALLBACK_MODEL_HINTS = _cat.get("criteria", {}).get("focus_defaults", {})
except Exception:
    pass


def _get_model_hint(focus_type: str) -> str:
    """
    Get model hint from models.yaml, falling back to loaded defaults.
    
    Source of truth: aria_models/models.yaml -> criteria.focus_defaults
    """
    if _HAS_CATALOG:
        hint = get_focus_default(focus_type)
        if hint:
            return hint
    _focus_log.warning(
        "Catalog lookup failed for focus '%s'; using loaded fallback", focus_type
    )
    return _FALLBACK_MODEL_HINTS.get(focus_type, "")


def get_focus_default_with_profile(focus_type: str) -> tuple[str, float, int]:
    """Return (model, temperature, max_tokens) for a focus type.

    Looks up the profiles section in models.yaml first (keyed by focus_type).
    Falls back to (model_hint, 0.7, 4096) when no profile matches.
    """
    model_hint = _get_model_hint(focus_type)
    default_temp = 0.7
    default_max_tokens = 4096

    if _HAS_CATALOG:
        try:
            catalog = load_catalog()
            profiles = catalog.get("profiles", {}) if catalog else {}
            profile = profiles.get(focus_type)
            if profile and isinstance(profile, dict):
                return (
                    profile.get("model", model_hint),
                    profile.get("temperature", default_temp),
                    profile.get("max_tokens", default_max_tokens),
                )
        except Exception:
            pass  # graceful fallback

    return (model_hint, default_temp, default_max_tokens)


@dataclass
class Focus:
    """
    A specialized persona overlay for Aria.
    
    Each focus defines:
    - Vibe modifier: How to adjust communication tone
    - Skills: Which tools to prioritize
    - Model hint: Preferred LLM for this focus (from models.yaml)
    - Context: Background knowledge to inject
    """
    type: FocusType
    name: str
    emoji: str
    vibe: str
    skills: list[str]
    model_hint: str  # Loaded from models.yaml at init, see _get_model_hint()
    context: str
    delegation_hint: str = ""  # How this focus delegates work
    
    def get_model_hint_live(self) -> str:
        """Get current model hint from models.yaml (refreshes on each call)."""
        return _get_model_hint(self.type.value)

    def get_model_profile(self) -> tuple[str, float, int]:
        """Return (model, temperature, max_tokens) from profiles section."""
        return get_focus_default_with_profile(self.type.value)
    
    def get_system_prompt_overlay(self) -> str:
        """Generate system prompt addition for this focus."""
        return f"""
Current Focus: {self.name} {self.emoji}
Approach: {self.vibe}
{self.context}
{self.delegation_hint}
"""

    def __repr__(self) -> str:
        return f"<Focus:{self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

FOCUSES: dict[FocusType, Focus] = {
    
    FocusType.ORCHESTRATOR: Focus(
        type=FocusType.ORCHESTRATOR,
        name="Orchestrator",
        emoji="🎯",
        vibe="Meta-cognitive, delegation-focused, strategic",
        skills=["api_client", "goals", "schedule", "health"],
        model_hint=_get_model_hint("orchestrator"),
        context="""
You are in executive mode. Your role is to:
- Analyze incoming requests and break them into delegatable tasks
- Route work to the most appropriate specialized focus
- Track progress and synthesize results
- Maintain the big picture while sub-agents handle details
- Prioritize ruthlessly: urgent > important > nice-to-have
""",
        delegation_hint="Delegate technical work to DevSecOps, analysis to Data, creative to Creative."
    ),
    
    FocusType.DEVSECOPS: Focus(
        type=FocusType.DEVSECOPS,
        name="DevSecOps",
        emoji="🔒",
        vibe="Security-paranoid, infrastructure-aware, systematic",
        skills=["pytest", "security_scan", "ci_cd", "database", "health", "llm"],
        model_hint=_get_model_hint("devsecops"),
        context="""
You are in DevSecOps mode. Your priorities:
- Security FIRST: Never trust input, validate everything
- Infrastructure as Code: Version all configs
- CI/CD mindset: Every change must be testable
- Shift left: Catch issues early, automate everything
- Least privilege: Minimal permissions always

Key patterns:
- Review code for security vulnerabilities before functionality
- Check for secrets exposure, injection risks, auth bypasses
- Prefer defensive coding with explicit error handling
""",
        delegation_hint="Escalate business logic decisions to Orchestrator, data analysis to Data focus."
    ),
    
    FocusType.DATA: Focus(
        type=FocusType.DATA,
        name="Data Architect",
        emoji="📊",
        vibe="Analytical, pattern-seeking, metrics-driven",
        skills=["api_client", "knowledge_graph", "performance", "data_pipeline", "experiment", "llm"],
        model_hint=_get_model_hint("data"),
        context="""
You are in Data Science/MLOps mode. Your approach:
- Data-driven decisions: Back claims with evidence
- Statistical thinking: Consider distributions, not just averages
- Pipeline mindset: Data quality > model complexity
- Experiment tracking: Document hypotheses and results
- Feature engineering: Transform data to reveal insights

Key patterns:
- Start with data exploration before modeling
- Validate assumptions with queries
- Build reproducible pipelines
- Track model performance over time
""",
        delegation_hint="Route code implementation to DevSecOps, communication to Social focus."
    ),
    
    FocusType.TRADER: Focus(
        type=FocusType.TRADER,
        name="Crypto Trader",
        emoji="📈",
        vibe="Risk-aware, market-analytical, disciplined",
        skills=["api_client", "market_data", "portfolio", "knowledge_graph", "schedule", "llm"],
        model_hint=_get_model_hint("trader"),
        context="""
You are in Crypto/Trading analysis mode. Your principles:
- Risk management FIRST: Never risk more than you can lose
- Market structure: Understand liquidity, orderflow, sentiment
- Technical + Fundamental: Both matter, neither is complete
- Execution discipline: Stick to the plan, no emotional trades
- Position sizing: Kelly criterion, never all-in

Key patterns:
- Identify support/resistance levels
- Track on-chain metrics and whale movements
- Note market correlations (BTC dominance, DXY, etc.)
- Set clear entry/exit criteria before any trade idea
""",
        delegation_hint="Route technical implementation to DevSecOps, news analysis to Journalist focus."
    ),
    
    FocusType.CREATIVE: Focus(
        type=FocusType.CREATIVE,
        name="Creative",
        emoji="🎨",
        vibe="Exploratory, unconventional, playful",
        skills=["brainstorm", "llm", "moltbook", "social", "knowledge_graph"],
        model_hint=_get_model_hint("creative"),
        context="""
You are in Creative/Adventure mode. Your approach:
- Divergent thinking: Generate many ideas before converging
- Yes-and: Build on ideas rather than dismissing them
- Constraints breed creativity: Limitations are features
- Prototype fast: Show don't tell
- Embrace weird: The unusual is often valuable

Key patterns:
- Brainstorm without judgment first
- Mix unexpected domains for novel solutions
- Tell stories to make ideas memorable
- Iterate quickly, fail fast, learn faster
""",
        delegation_hint="Route technical validation to DevSecOps, publishing to Social focus."
    ),
    
    FocusType.SOCIAL: Focus(
        type=FocusType.SOCIAL,
        name="Social Architect",
        emoji="🌐",
        vibe="Community-building, engaging, authentic",
        skills=["moltbook", "social", "community", "schedule", "api_client"],
        model_hint=_get_model_hint("social"),
        context="""
You are in Social Media/Startuper mode. Your principles:
- Authenticity > perfection: Real beats polished
- Community first: Build relationships, not just followers
- Value-driven content: Every post should help someone
- Consistency: Regular presence builds trust
- Engagement: Respond, interact, participate

Key patterns for Moltbook:
- Share learnings, not just achievements
- Ask questions to spark discussion
- Support other agents' content
- Rate limits: 1 post/30min, 50 comments/day - quality over quantity
""",
        delegation_hint="Route technical content to DevSecOps, research to Data focus."
    ),
    
    FocusType.JOURNALIST: Focus(
        type=FocusType.JOURNALIST,
        name="Journalist",
        emoji="📰",
        vibe="Investigative, fact-checking, narrative-building",
        skills=["research", "fact_check", "knowledge_graph", "moltbook", "social", "llm"],
        model_hint=_get_model_hint("journalist"),
        context="""
You are in Journalist/Reporter mode. Your standards:
- Facts first: Verify before reporting
- Multiple sources: Never rely on single source
- Attribution: Credit sources, link to evidence
- Narrative structure: Lead with the important, support with details
- Objectivity: Present multiple perspectives fairly

Key patterns:
- Who, what, when, where, why, how
- Distinguish fact from opinion explicitly
- Update when new information emerges
- Protect sources when appropriate
""",
        delegation_hint="Route data analysis to Data focus, publishing to Social focus."
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# FOCUS MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class FocusManager:
    """
    Manages Aria's active focus and focus transitions.
    
    The FocusManager ensures:
    1. Only one focus is active at a time
    2. Default focus is ORCHESTRATOR
    3. Focus changes are logged
    4. Core identity is never compromised
    """
    
    def __init__(self):
        self._active: Focus = FOCUSES[FocusType.ORCHESTRATOR]
        self._history: list[FocusType] = []
    
    @property
    def active(self) -> Focus:
        """Get current active focus."""
        return self._active
    
    @property
    def all_focuses(self) -> dict[FocusType, Focus]:
        """Get all available focuses."""
        return FOCUSES
    
    def set_focus(self, focus_type: FocusType) -> Focus:
        """
        Set the active focus.
        
        Args:
            focus_type: The focus to activate
            
        Returns:
            The newly active Focus
        """
        if focus_type not in FOCUSES:
            raise ValueError(f"Unknown focus type: {focus_type}")
        
        old_focus = self._active.type
        self._active = FOCUSES[focus_type]
        self._history.append(old_focus)
        
        # Keep history manageable
        if len(self._history) > 50:
            self._history = self._history[-25:]
        
        return self._active
    
    def reset(self) -> Focus:
        """Reset to default ORCHESTRATOR focus."""
        return self.set_focus(FocusType.ORCHESTRATOR)
    
    def get_focus_for_task(self, task_keywords: list[str]) -> FocusType:
        """
        Suggest best focus for a task based on keywords.
        
        Uses keyword matching (fast, free, always available).
        See also: classify_focus_llm() for LLM-powered classification.
        
        Args:
            task_keywords: Words describing the task
            
        Returns:
            Recommended FocusType
        """
        keywords_lower = [k.lower() for k in task_keywords]
        
        # Keyword mapping to focus types
        mappings = {
            FocusType.DEVSECOPS: ["code", "security", "test", "deploy", "ci", "cd", "docker", 
                                  "kubernetes", "infrastructure", "vulnerability", "audit"],
            FocusType.DATA: ["data", "analysis", "model", "ml", "ai", "statistics", "pipeline",
                           "query", "database", "metrics", "visualization", "experiment"],
            FocusType.TRADER: ["crypto", "trading", "market", "price", "bitcoin", "defi",
                              "investment", "portfolio", "risk", "chart", "technical"],
            FocusType.CREATIVE: ["creative", "brainstorm", "idea", "story", "design", 
                                "innovate", "explore", "experiment", "art", "novel"],
            FocusType.SOCIAL: ["post", "moltbook", "social", "community", "engage", "share",
                              "network", "startup", "pitch", "audience", "content"],
            FocusType.JOURNALIST: ["news", "report", "investigate", "article", "fact",
                                   "source", "story", "headline", "research", "verify"],
        }
        
        # Score each focus
        scores = {ft: 0 for ft in FocusType}
        for focus_type, focus_keywords in mappings.items():
            for kw in keywords_lower:
                if any(fk in kw or kw in fk for fk in focus_keywords):
                    scores[focus_type] += 1
        
        # Return highest scoring focus, default to ORCHESTRATOR
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else FocusType.ORCHESTRATOR

    async def classify_focus_llm(
        self,
        task_text: str,
        llm_skill=None,
    ) -> FocusType:
        """
        SP7-07: LLM-powered focus classification.

        Uses a single cheap LLM call (local model, ~50 input tokens,
        max_tokens=64) to classify the task into a focus type.
        Cost: $0 when using local qwen3.5_mlx or free-tier OpenRouter.

        Falls back to keyword matching if LLM is unavailable or fails.

        Args:
            task_text: The user prompt or task description
            llm_skill: Optional LLM skill instance (litellm or ollama).
                        If None, falls back to keyword matching.

        Returns:
            Recommended FocusType
        """
        # Build the valid focus names for the prompt
        valid_names = [ft.value for ft in FocusType]

        if llm_skill and hasattr(llm_skill, "complete"):
            try:
                classification_prompt = (
                    f"Classify this task into exactly ONE focus type.\n"
                    f"Options: {', '.join(valid_names)}\n"
                    f"Task: {task_text[:200]}\n"
                    f"Reply with ONLY the focus type name, nothing else."
                )
                messages = [
                    {"role": "system", "content": "You are a task classifier. Reply with a single word."},
                    {"role": "user", "content": classification_prompt},
                ]
                result = await llm_skill.complete(
                    messages=messages,
                    max_tokens=32,
                    temperature=0.1,  # profile: focus_classify
                )
                if result.success:
                    data = result.data or {}
                    choices = data.get("choices", [])
                    if choices:
                        raw = choices[0].get("message", {}).get("content", "").strip().lower()
                    else:
                        raw = (data.get("text") or "").strip().lower()
                    # Parse — accept the focus name anywhere in the response
                    for ft in FocusType:
                        if ft.value in raw:
                            return ft
            except Exception:
                pass  # Fall through to keyword matching

        # Fallback: keyword matching (always available, free)
        keywords = task_text.lower().split()[:20]
        return self.get_focus_for_task(keywords)
    
    def get_awareness_text(self) -> str:
        """
        Generate text describing all focuses for self-awareness.
        
        This is injected into Aria's context so she knows her capabilities.
        """
        lines = ["I can adopt specialized focuses for different tasks:\n"]
        for ft, focus in FOCUSES.items():
            skills_str = ", ".join(focus.skills[:3])  # First 3 skills
            model = focus.get_model_hint_live()  # Get live model from models.yaml
            lines.append(f"- {focus.emoji} **{focus.name}**: {focus.vibe} (model: {model})")
        lines.append(f"\nCurrent focus: {self._active.emoji} {self._active.name}")
        return "\n".join(lines)
    
    def status(self) -> dict:
        """Return current focus status."""
        model, temperature, max_tokens = self._active.get_model_profile()
        return {
            "active_focus": self._active.name,
            "focus_type": self._active.type.value,
            "skills": self._active.skills,
            "model_hint": self._active.get_model_hint_live(),  # Live from models.yaml
            "model_hint_static": self._active.model_hint,  # Static at init time
            "temperature": temperature,
            "max_tokens": max_tokens,
            "recent_history": [f.value for f in self._history[-5:]],
            "catalog_available": _HAS_CATALOG,
        }
    
    def get_all_model_hints(self) -> dict[str, str]:
        """Get all focus -> model mappings (live from models.yaml)."""
        return {ft.value: _get_model_hint(ft.value) for ft in FocusType}


# Module-level instance for convenience
_focus_manager = FocusManager()

def get_focus_manager() -> FocusManager:
    """Get the global FocusManager instance."""
    return _focus_manager
