"""
Aria Engine — Standalone Python runtime for Aria Blue.

Native runtime providing:
- LLM gateway (direct litellm SDK)
- Chat engine (session lifecycle + streaming)
- Scheduler (APScheduler + PostgreSQL)
- Agent pool (async task management)
- Context manager (sliding window + importance)
"""

__version__ = "3.0.0"

from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError, LLMError, SessionError, SchedulerError

__all__ = ["EngineConfig", "EngineError", "LLMError", "SessionError", "SchedulerError",
           "get_engine", "set_engine"]

# Global engine instance (set by AriaEngine.start())
_engine_instance = None


def get_engine():
    """Get the global AriaEngine instance."""
    return _engine_instance


def set_engine(engine):
    """Set the global AriaEngine instance."""
    global _engine_instance
    _engine_instance = engine
