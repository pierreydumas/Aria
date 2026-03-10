"""Unit tests for Creative Pulse activity aggregation helpers."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "api"))

from src.api.routers.activities import (  # noqa: E402
    _build_brainstorm_insight,
    _build_community_insight,
    _build_experiment_insight,
    _dedupe_creative_activities,
    _enriched_creative_details,
    _normalized_creative_context,
    _pick_latest_creative_insight,
)


def _item(**kwargs):
    base = {
        "id": "activity-test",
        "skill": "brainstorm",
        "action": "brainstorm.start_session",
        "details": {},
        "success": True,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_normalized_creative_context_extracts_nested_fields():
    context = _normalized_creative_context({
        "idea": {"text": "Launch a creative operations dashboard"},
        "campaign": {"name": "Spring Launch", "goal": "200 signups", "status": "active"},
        "scripture_type": "verse",
    })

    assert context["idea"] == "Launch a creative operations dashboard"
    assert context["campaign_name"] == "Spring Launch"
    assert context["goal"] == "200 signups"
    assert context["status"] == "active"
    assert context["scripture_type"] == "verse"


def test_enriched_creative_details_adds_creative_context():
    details = {
        "experiment": {
            "id": "exp-123",
            "name": "LLM sentiment comparison",
            "hypothesis": "LLM scoring beats lexicon scoring",
            "status": "running",
        }
    }

    enriched = _enriched_creative_details(details)

    assert enriched["creative_context"]["experiment_name"] == "LLM sentiment comparison"
    assert enriched["creative_context"]["hypothesis"] == "LLM scoring beats lexicon scoring"
    assert enriched["creative_context"]["experiment_id"] == "exp-123"


def test_pick_latest_brainstorm_prefers_rich_domain_event_over_wrapper():
    wrapper = _item(
        action="brainstorm.start_session",
        details={"method": "start_session", "duration_ms": 8},
        created_at=datetime(2026, 3, 10, 7, 38, 26, tzinfo=timezone.utc),
    )
    rich = _item(
        action="brainstorm_session_started",
        details={"topic": "Creative content ideas for March", "session_id": "42dd4717"},
        created_at=datetime(2026, 3, 10, 7, 38, 25, tzinfo=timezone.utc),
    )

    insight = _pick_latest_creative_insight(
        [wrapper, rich],
        "brainstorm",
        _build_brainstorm_insight,
    )

    assert insight is not None
    assert insight["topic"] == "Creative content ideas for March"
    assert insight["session_id"] == "42dd4717"


def test_experiment_insight_uses_description_when_name_missing():
    score, insight = _build_experiment_insight(
        _item(
            skill="experiment",
            action="experiment_created",
            details={
                "description": "Comparing lexicon-based vs LLM-based sentiment scoring approaches",
                "status": "completed",
            },
        )
    )

    assert score >= 10
    assert insight is not None
    assert insight["name"] == "Comparing lexicon-based vs LLM-based sentiment scoring approaches"
    assert insight["status"] == "completed"


def test_dedupe_creative_activities_merges_wrapper_with_domain_event():
    wrapper = _item(
        id="activity-1",
        action="brainstorm.start_session",
        details={"method": "start_session", "duration_ms": 8},
        created_at=datetime(2026, 3, 10, 7, 38, 26, tzinfo=timezone.utc),
    )
    rich = _item(
        id="activity-2",
        action="brainstorm_session_started",
        details={"topic": "Creative content ideas for March", "session_id": "42dd4717"},
        created_at=datetime(2026, 3, 10, 7, 38, 25, tzinfo=timezone.utc),
    )

    deduped = _dedupe_creative_activities([wrapper, rich])

    assert len(deduped) == 1
    assert deduped[0]["action"] == "brainstorm.start_session"
    assert deduped[0]["duplicate_count"] == 2
    assert sorted(deduped[0]["raw_actions"]) == ["brainstorm.start_session", "brainstorm_session_started"]
    assert deduped[0]["details"]["creative_context"]["topic"] == "Creative content ideas for March"
    assert deduped[0]["description"] == "Creative content ideas for March"


def test_pick_latest_community_focus_prefers_campaign_context():
    engagement = _item(
        skill="community",
        action="community.record_engagement",
        details={"method": "record_engagement", "duration_ms": 6},
        created_at=datetime(2026, 3, 10, 10, 0, 0, tzinfo=timezone.utc),
    )
    campaign = _item(
        skill="community",
        action="community_campaign_created",
        details={
            "campaign": {"id": "cmp-1", "name": "Creator Sprint", "goal": "50 new contributors", "status": "active"},
        },
        created_at=datetime(2026, 3, 10, 9, 59, 58, tzinfo=timezone.utc),
    )

    insight = _pick_latest_creative_insight(
        [engagement, campaign],
        "community",
        _build_community_insight,
    )

    assert insight is not None
    assert insight["main"] == "Creator Sprint"
    assert "goal=50 new contributors" in insight["meta"]