"""
Telemetry — Write LLM usage and tool invocations to aria_data schema.

The aria_engine runtime persists messages in aria_engine.chat_sessions/chat_messages.
This module mirrors key telemetry into aria_data.model_usage and aria_data.skill_invocations
so the observability dashboards (/model-usage, /skill-stats) show real data from conversations.

Fire-and-forget: failures are logged but never break the chat flow.
"""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("aria.engine.telemetry")


async def log_model_usage(
    db_factory,
    *,
    model: str,
    provider: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    """Log an LLM call to aria_data.model_usage."""
    try:
        from db.models import ModelUsage

        async with db_factory() as db:
            row = ModelUsage(
                id=uuid.uuid4(),
                model=model or "unknown",
                provider=_infer_provider(model, provider),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
                # session_id left NULL — FK targets aria_data.agent_sessions,
                # not aria_engine.chat_sessions
            )
            db.add(row)
            await db.commit()
    except ImportError as e:
        # db namespace unavailable (non-Docker / local dev) — expected, not a bug.
        logger.warning("telemetry.log_model_usage: db not available — telemetry is dark: %s", e)
    except Exception as e:
        logger.debug("telemetry.log_model_usage failed (non-fatal): %s", e)


async def log_skill_invocation(
    db_factory,
    *,
    skill_name: str,
    tool_name: str,
    agent_id: str | None = None,
    duration_ms: int | None = None,
    success: bool = True,
    error_type: str | None = None,
    tokens_used: int | None = None,
    model_used: str | None = None,
) -> None:
    """Log a tool/skill call to aria_data.skill_invocations."""
    try:
        from db.models import SkillInvocation

        async with db_factory() as db:
            row = SkillInvocation(
                id=uuid.uuid4(),
                skill_name=skill_name,
                tool_name=tool_name,
                agent_id=agent_id,
                duration_ms=duration_ms,
                success=success,
                error_type=error_type,
                tokens_used=tokens_used,
                model_used=model_used,
            )
            db.add(row)
            await db.commit()
    except ImportError as e:
        logger.warning("telemetry.log_skill_invocation: db not available — telemetry is dark: %s", e)
    except Exception as e:
        logger.debug("telemetry.log_skill_invocation failed (non-fatal): %s", e)


def _infer_provider(model: str, provider: str | None) -> str:
    """Best-effort provider inference from model name."""
    if provider:
        return provider
    # Try YAML-based lookup first (models.yaml is source of truth)
    try:
        from aria_models.loader import get_provider_label
        label = get_provider_label(model)
        if label != "unknown":
            return label
    except ImportError:
        pass
    # Generic fallback for models not in YAML (external providers)
    model_l = (model or "").lower()
    if "gpt" in model_l or "o1" in model_l or "o3" in model_l:
        return "openai"
    if "claude" in model_l:
        return "anthropic"
    if "gemini" in model_l:
        return "google"
    return "litellm"


def _parse_skill_from_tool(function_name: str) -> str:
    """Extract skill name from tool function name (e.g. 'memory__recall' -> 'memory')."""
    if "__" in function_name:
        return function_name.split("__")[0]
    return function_name
