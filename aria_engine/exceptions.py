"""Engine-specific exceptions and fire-and-forget task utilities."""

import asyncio
import logging

_ff_logger = logging.getLogger("aria.engine.fire_forget")


def safe_fire_and_forget(coro, *, name: str = "") -> asyncio.Task:
    """Schedule a coroutine as a fire-and-forget task with error logging.

    Unlike bare ``asyncio.create_task`` / ``ensure_future``, exceptions are
    caught and logged at WARNING level so they never vanish silently.
    """
    task = asyncio.ensure_future(coro)
    if name:
        try:
            task.set_name(name)
        except AttributeError:
            pass  # Python < 3.8 compat (shouldn't happen on 3.13+)

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _ff_logger.warning(
                "Fire-and-forget task %s failed: %s",
                name or t.get_name(),
                exc,
                exc_info=exc,
            )

    task.add_done_callback(_on_done)
    return task


class EngineError(Exception):
    """Base exception for aria_engine."""
    pass


class LLMError(EngineError):
    """LLM gateway errors (model unavailable, timeout, etc.)."""
    pass


class SessionError(EngineError):
    """Session management errors."""
    pass


class SchedulerError(EngineError):
    """Scheduler errors (job execution, scheduling)."""
    pass


class AgentError(EngineError):
    """Agent pool errors (spawn, terminate, routing)."""
    pass


class ContextError(EngineError):
    """Context assembly errors."""
    pass


class ToolError(EngineError):
    """Tool calling errors."""
    pass
