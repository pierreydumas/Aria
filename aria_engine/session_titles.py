"""Helpers for deriving stable display titles for engine sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any


_PLACEHOLDER_TITLES = {"", "-", "untitled"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _looks_like_uuid(value: str) -> bool:
    if len(value) != 36:
        return False
    parts = value.split("-")
    if [len(part) for part in parts] != [8, 4, 4, 4, 12]:
        return False
    return all(part and all(ch in "0123456789abcdefABCDEF" for ch in part) for part in parts)


def humanize_session_label(value: Any) -> str:
    """Convert a slug-like session label into the UI format already used elsewhere."""
    text = _clean_text(value)
    if not text:
        return ""
    if _looks_like_uuid(text):
        return text
    if any(ch.isspace() for ch in text):
        return " ".join(part[:1].upper() + part[1:] for part in text.split() if part)
    if any(ch.isupper() for ch in text):
        return text
    return text.replace("_", " ").replace("-", " ").title()


def resolve_cron_job_display_name(job_name: Any, job_id: Any) -> str:
    """Resolve a safe display name for cron sessions without leaking UUID ids."""
    raw_name = _clean_text(job_name)
    if raw_name and not _looks_like_uuid(raw_name):
        return humanize_session_label(raw_name)

    raw_id = _clean_text(job_id)
    if raw_id and not _looks_like_uuid(raw_id):
        return humanize_session_label(raw_id)

    return "Cron Job"


def canonical_session_job_key(job_id: Any, job_name: Any = None) -> str:
    """Return the stable internal cron job key for branching logic."""
    raw_id = _clean_text(job_id)
    if raw_id and not _looks_like_uuid(raw_id):
        return raw_id.replace("-", "_").replace(" ", "_").lower()

    raw_name = _clean_text(job_name)
    if raw_name:
        return raw_name.replace("-", "_").replace(" ", "_").lower()

    return raw_id.lower()


def resolve_session_title(
    title: Any,
    session_type: str | None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> str:
    """Resolve a user-facing session title without changing the stored title."""
    cleaned_title = _clean_text(title)
    if cleaned_title.lower() not in _PLACEHOLDER_TITLES:
        return cleaned_title

    metadata = metadata if isinstance(metadata, dict) else {}
    stype = _clean_text(session_type).lower()
    if stype == "cron":
        raw_job_name = _clean_text(metadata.get("job_name"))
        raw_job_id = _clean_text(metadata.get("cron_job_id"))
        display_name = resolve_cron_job_display_name(raw_job_name, raw_job_id)
        if display_name:
            time_label = created_at.strftime("%H:%M") if isinstance(created_at, datetime) else ""
            return f"⏱ {display_name} · {time_label}" if time_label else f"⏱ {display_name}"

    return cleaned_title or "Untitled"