from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from aria_engine.scheduler import EngineScheduler
from aria_engine.session_titles import (
    canonical_session_job_key,
    humanize_session_label,
    resolve_cron_job_display_name,
    resolve_session_title,
)


def test_humanize_session_label_from_slug():
    assert humanize_session_label("work_cycle") == "Work Cycle"


def test_canonical_session_job_key_prefers_job_id():
    assert canonical_session_job_key("work_cycle", "Work Cycle") == "work_cycle"


def test_resolve_cron_job_display_name_hides_uuid_ids():
    assert resolve_cron_job_display_name("", "2afe56fb-4e1d-46e8-9769-977eb3564a52") == "Cron Job"


def test_resolve_session_title_uses_cron_metadata_for_placeholder_titles():
    created_at = datetime(2026, 3, 10, 22, 19, tzinfo=timezone.utc)
    title = resolve_session_title(
        "Untitled",
        "cron",
        {"cron_job_id": "work_cycle", "job_name": ""},
        created_at,
    )
    assert title == "⏱ Work Cycle · 22:19"


def test_resolve_session_title_preserves_explicit_title():
    created_at = datetime(2026, 3, 10, 22, 19, tzinfo=timezone.utc)
    title = resolve_session_title(
        "Agent: memory — summarize session",
        "scoped",
        {"cron_job_id": "work_cycle"},
        created_at,
    )
    assert title == "Agent: memory — summarize session"


@pytest.mark.asyncio
async def test_trigger_job_passes_job_name_to_execute_job():
    scheduler = EngineScheduler(config=MagicMock(), db_engine=MagicMock())
    captured: dict[str, object] = {}
    finished = asyncio.Event()

    async def fake_get_job(job_id: str):
        return {
            "id": job_id,
            "name": "Work Cycle",
            "agent_id": "aria",
            "payload_type": "prompt",
            "payload": "run the next cycle",
            "session_mode": "isolated",
            "max_duration_seconds": 300,
        }

    async def fake_execute_job(**kwargs):
        captured.update(kwargs)
        finished.set()

    scheduler.get_job = fake_get_job  # type: ignore[method-assign]
    scheduler._execute_job = fake_execute_job  # type: ignore[method-assign]

    assert await scheduler.trigger_job("work_cycle") is True
    await asyncio.wait_for(finished.wait(), timeout=1)
    assert captured["job_name"] == "Work Cycle"