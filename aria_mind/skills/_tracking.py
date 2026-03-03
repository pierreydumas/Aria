"""Best-effort tracking helpers for run_skill."""


import json
import logging
import os

_API_BASE = (os.environ.get("ARIA_API_URL") or "").rstrip("/")
_API_PATH = (os.environ.get("ARIA_API_PATH") or "").strip()

try:
    import httpx  # type: ignore[import-not-found]

    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

_tracker_log = logging.getLogger("aria.skill_tracker")

# Load primary model from models.yaml (single source of truth)
try:
    from aria_models.loader import get_primary_model_full as _get_pf
    _PRIMARY_MODEL_FULL = _get_pf()
except Exception:
    _PRIMARY_MODEL_FULL = ""


def _is_noise_invocation(skill_name: str, function_name: str, success: bool) -> bool:
    """Filter high-frequency low-value noise from activity stream."""
    if not success:
        return False

    skill = (skill_name or "").strip().lower()
    fn = (function_name or "").strip().lower()

    # Routine health probes are useful for status but noisy for activity/memory views.
    if fn == "health_check" and skill in {"health", "api_client", "agent_manager"}:
        return True

    # Successful test runs can be frequent and should not pollute memory/KG summaries.
    if skill in {"pytest", "pytest_runner"} and fn in {"run_tests", "health_check", "get_last_result"}:
        return True

    return False


def _api_base_candidates() -> list[str]:
    seen = set()
    candidates = []

    def _add(base: str):
        b = (base or "").rstrip("/")
        if b and b not in seen:
            seen.add(b)
            candidates.append(b)

    if not _API_BASE:
        return []

    _add(_API_BASE)
    if _API_PATH:
        _add(f"{_API_BASE}/{_API_PATH.strip('/')}")
    if _API_BASE.endswith("/api"):
        _add(_API_BASE[:-4])
    else:
        _add(f"{_API_BASE}/api")

    return candidates


async def _api_post(endpoint: str, payload: dict) -> bool:
    """Fire-and-forget POST to aria-api. Returns True on success."""
    if not _HAS_HTTPX:
        _tracker_log.debug("httpx not installed — skipping tracking POST")
        return False
    bases = _api_base_candidates()
    if not bases:
        _tracker_log.debug("ARIA_API_URL is not set — skipping tracking POST %s", endpoint)
        return False

    last_exc = None
    async with httpx.AsyncClient(timeout=5) as client:
        for base in bases:
            try:
                resp = await client.post(f"{base}{endpoint}", json=payload)
                resp.raise_for_status()
                return True
            except Exception as exc:
                last_exc = exc
                continue
    _tracker_log.debug("Tracking POST %s failed: %s", endpoint, last_exc)
    return False


def _log_locally(event_type: str, data: dict) -> None:
    """Fallback: log tracking data locally when the API is unreachable."""
    _tracker_log.warning(
        "API unreachable — logging %s locally: %s",
        event_type,
        json.dumps(data, default=str),
    )


async def _log_session(
    skill_name: str,
    function_name: str,
    duration_ms: float,
    success: bool,
    error_msg: str | None = None,
) -> None:
    """P2.1 — Log skill invocation to agent_sessions via aria-api."""
    payload = {
        "agent_id": os.environ.get("ARIA_AGENT_ID", "main"),
        "session_type": "skill_exec",
        "status": "completed" if success else "error",
        "metadata": {
            "skill": skill_name,
            "function": function_name,
            "duration_ms": round(duration_ms, 2),
            "success": success,
            "error": error_msg,
        },
    }
    ok = await _api_post("/sessions", payload)
    if not ok:
        _log_locally("session", payload)


async def _log_model_usage(skill_name: str, function_name: str, duration_ms: float) -> None:
    """P2.2 — Log approximate model usage via aria-api."""
    payload = {
        "model": f"skill:{skill_name}:{function_name}",
        "provider": "skill-exec",
        "latency_ms": int(duration_ms),
        "success": True,
    }
    ok = await _api_post("/model-usage", payload)
    if not ok:
        _log_locally("model_usage", payload)


async def _log_skill_invocation(
    skill_name: str,
    function_name: str,
    duration_ms: float,
    success: bool,
    error_msg: str | None = None,
    args_preview: str | None = None,
    result_preview: str | None = None,
    creative_context: dict | None = None,
) -> None:
    """Log invocation to /skills/invocations for Skill Stats dashboard."""
    if _is_noise_invocation(skill_name, function_name, success):
        return

    payload = {
        "skill_name": skill_name,
        "tool_name": function_name,
        "duration_ms": int(duration_ms),
        "success": success,
        "error_type": error_msg,
        "tokens_used": 0,
        "model_used": os.environ.get("ARIA_MODEL", _PRIMARY_MODEL_FULL),
    }
    ok = await _api_post("/skills/invocations", payload)
    if not ok:
        _log_locally("skill_invocation", payload)

    activity_payload = {
        "action": f"skill.{function_name}",
        "skill": skill_name,
        "success": success,
        "error_message": error_msg,
        "details": {
            "function": function_name,
            "duration_ms": round(duration_ms, 2),
            "source": "run_skill",
            "args_preview": args_preview or "",
            "result_preview": result_preview or "",
            "creative_context": creative_context or {},
        },
    }
    activity_ok = await _api_post("/activities", activity_payload)
    if not activity_ok:
        _log_locally("activity", activity_payload)
