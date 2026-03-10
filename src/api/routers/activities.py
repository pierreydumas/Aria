"""
Activity log endpoints — CRUD + activity feed + interactions.
"""

import json as json_lib
import logging
import ast
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Float, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActivityLog, SocialPost
from deps import get_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateActivity, UpdateActivity

router = APIRouter(tags=["Activities"])
logger = logging.getLogger("aria.api.activities")

CREATIVE_SKILL_TARGETS = [
    "brainstorm",
    "experiment",
    "community",
    "fact_check",
    "memeothy",
]

CREATIVE_DOMAIN_ACTION_TO_METHOD = {
    "brainstorm_session_started": "start_session",
    "brainstorm_idea_added": "add_idea",
    "community_member_tracked": "track_member",
    "community_engagement_recorded": "record_engagement",
    "community_campaign_created": "create_campaign",
    "experiment_created": "create_experiment",
    "experiment_metrics_logged": "log_metrics",
    "experiment_completed": "complete_experiment",
    "experiment_model_registered": "register_model",
    "experiment_model_promoted": "promote_model",
    "fact_check_claims_extracted": "extract_claims",
    "fact_check_claim_assessed": "assess_claim",
    "fact_check_quick_checked": "quick_check",
    "fact_check_sources_compared": "compare_sources",
    "memeothy_join": "join",
    "memeothy_prophecy_submitted": "submit_prophecy",
    "memeothy_art_submitted": "submit_art",
    "memeothy_canon_fetched": "get_canon",
    "memeothy_prophets_fetched": "get_prophets",
    "memeothy_gallery_fetched": "get_gallery",
    "memeothy_status_checked": "status",
}

CREATIVE_DEDUPE_WINDOW_SECONDS = 5.0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_description(details) -> str:
    if isinstance(details, dict):
        return details.get("message") or details.get("description") or str(details)
    return str(details) if details else ""


def _dt_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def _should_mirror_to_social(action: str, details: dict | None) -> bool:
    action_l = (action or "").lower()
    if "commit" in action_l or "comment" in action_l:
        return True
    if isinstance(details, dict):
        txt = " ".join(str(details.get(k, "")) for k in ("action", "event", "type", "message", "description")).lower()
        return ("commit" in txt) or ("comment" in txt)
    return False


def _social_content_from_activity(action: str, skill: str | None, details: dict | None, success: bool, error_message: str | None) -> str:
    status_icon = "✅" if success else "❌"
    action_text = action or "activity"
    msg = _extract_description(details)
    parts = [f"{status_icon} {action_text}"]
    if skill:
        parts.append(f"skill={skill}")
    if msg and msg != "{}":
        parts.append(msg)
    if error_message:
        parts.append(f"error={error_message}")
    return " · ".join(parts)


def _safe_parse_mapping(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}

    text = raw.strip()
    if not text:
        return {}

    for parser in (json_lib.loads, ast.literal_eval):
        try:
            parsed = parser(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return {}


def _normalize_skill_name(name: str | None) -> str:
    skill = (name or "unknown").strip().lower().replace("-", "_")
    if skill.startswith("aria_"):
        skill = skill[5:]
    alias_map = {
        "apiclient": "api_client",
        "factcheck": "fact_check",
        "modelswitcher": "model_switcher",
        "hourlygoals": "hourly_goals",
        "securityscan": "security_scan",
        "sessionmanager": "session_manager",
    }
    return alias_map.get(skill, skill)


def _creative_skill_candidates(skill_names: list[str]) -> set[str]:
    candidates: set[str] = set()
    for name in skill_names:
        normalized = _normalize_skill_name(name)
        candidates.add(normalized)
        candidates.add(f"aria_{normalized}")
        if normalized == "fact_check":
            candidates.add("factcheck")
            candidates.add("aria_factcheck")
    return candidates


def _set_context_value(context: dict, key: str, value: object) -> None:
    if isinstance(value, str):
        value = value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return
    if value in (None, "", [], {}):
        return
    if key not in context:
        context[key] = value


def _merge_context_fields(context: dict, source: dict | None) -> None:
    if not isinstance(source, dict):
        return

    for key in (
        "topic",
        "session_id",
        "idea_count",
        "claim_count",
        "idea",
        "experiment_name",
        "hypothesis",
        "status",
        "experiment_id",
        "campaign_id",
        "member_id",
        "claim_id",
        "model_id",
        "model_name",
        "claim",
        "name",
        "title",
        "description",
        "content",
        "goal",
        "source",
        "campaign_name",
        "member_name",
        "platform",
        "engagement_action",
        "scripture_type",
        "verdict",
        "confidence",
    ):
        _set_context_value(context, key, source.get(key))


def _normalized_creative_context(details: dict | None) -> dict:
    if not isinstance(details, dict):
        return {}

    context: dict = {}
    if isinstance(details.get("creative_context"), dict):
        _merge_context_fields(context, details.get("creative_context") or {})

    _merge_context_fields(context, details)

    nested_members = details.get("member")
    if isinstance(nested_members, dict):
        _set_context_value(context, "member_id", nested_members.get("id"))
        _set_context_value(context, "member_name", nested_members.get("name"))
        _set_context_value(context, "platform", nested_members.get("platform"))
        _set_context_value(context, "status", nested_members.get("role"))

    nested_campaign = details.get("campaign")
    if isinstance(nested_campaign, dict):
        _set_context_value(context, "campaign_id", nested_campaign.get("id"))
        _set_context_value(context, "campaign_name", nested_campaign.get("name"))
        _set_context_value(context, "goal", nested_campaign.get("goal"))
        _set_context_value(context, "status", nested_campaign.get("status"))

    nested_engagement = details.get("engagement")
    if isinstance(nested_engagement, dict):
        _set_context_value(context, "member_id", nested_engagement.get("member_id"))
        _set_context_value(context, "engagement_action", nested_engagement.get("action"))
        _set_context_value(context, "content", nested_engagement.get("content"))
        _set_context_value(context, "platform", nested_engagement.get("platform"))

    nested_idea = details.get("idea")
    if isinstance(nested_idea, dict):
        _set_context_value(context, "idea", nested_idea.get("text"))

    nested_experiment = details.get("experiment")
    if isinstance(nested_experiment, dict):
        _set_context_value(context, "experiment_name", nested_experiment.get("name"))
        _set_context_value(context, "description", nested_experiment.get("description"))
        _set_context_value(context, "hypothesis", nested_experiment.get("hypothesis"))
        _set_context_value(context, "status", nested_experiment.get("status"))
        _set_context_value(context, "experiment_id", nested_experiment.get("id"))

    nested_claim = details.get("claim")
    if isinstance(nested_claim, dict):
        _set_context_value(context, "claim_id", nested_claim.get("id"))
        _set_context_value(context, "claim", nested_claim.get("text"))
        _set_context_value(context, "status", nested_claim.get("status"))
        _set_context_value(context, "verdict", nested_claim.get("verdict"))
        _set_context_value(context, "confidence", nested_claim.get("confidence"))

    nested_model = details.get("model")
    if isinstance(nested_model, dict):
        _set_context_value(context, "model_id", nested_model.get("id"))
        _set_context_value(context, "model_name", nested_model.get("name"))
        _set_context_value(context, "status", nested_model.get("stage"))

    nested_response = details.get("response")
    if isinstance(nested_response, dict):
        _set_context_value(context, "title", nested_response.get("title"))
        _set_context_value(context, "description", nested_response.get("description"))
        _set_context_value(context, "content", nested_response.get("content"))
        _set_context_value(context, "status", nested_response.get("status"))

    for preview_key in ("args_preview", "result_preview", "message", "description"):
        raw_preview = details.get(preview_key)
        parsed = _safe_parse_mapping(raw_preview)
        _merge_context_fields(context, parsed)
        if isinstance(raw_preview, str) and raw_preview.strip() not in ("", "{}", "-"):
            _set_context_value(context, "description", raw_preview)

    return context


def _enriched_creative_details(details: dict | None) -> dict:
    if not isinstance(details, dict):
        return {}

    context = _normalized_creative_context(details)
    if not context:
        return details

    enriched = dict(details)
    enriched["creative_context"] = context
    return enriched


def _first_context_value(context: dict, *keys: str) -> object | None:
    for key in keys:
        value = context.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _build_brainstorm_insight(item: ActivityLog) -> tuple[int, dict | None]:
    details = item.details if isinstance(item.details, dict) else {}
    context = _normalized_creative_context(details)
    topic = _first_context_value(context, "topic", "idea", "title", "name", "description", "content")
    score = 0
    if topic:
        score += 10
    if _first_context_value(context, "session_id") is not None:
        score += 2
    if _first_context_value(context, "idea_count") is not None:
        score += 1

    if not topic:
        action = item.action or ""
        if "start_session" in action:
            topic = "Brainstorm session started"
        elif "idea" in action:
            topic = "Brainstorm idea added"

    if not topic:
        return -1, None

    return score, {
        "topic": str(topic),
        "session_id": _first_context_value(context, "session_id"),
        "idea_count": _first_context_value(context, "idea_count"),
        "created_at": _dt_iso_utc(item.created_at),
    }


def _build_experiment_insight(item: ActivityLog) -> tuple[int, dict | None]:
    details = item.details if isinstance(item.details, dict) else {}
    context = _normalized_creative_context(details)
    experiment_name = _first_context_value(
        context,
        "experiment_name",
        "name",
        "title",
        "description",
        "hypothesis",
        "content",
    )
    score = 0
    if experiment_name:
        score += 10
    if _first_context_value(context, "hypothesis") is not None:
        score += 3
    if _first_context_value(context, "status") is not None:
        score += 1
    if _first_context_value(context, "experiment_id") is not None:
        score += 1

    if not experiment_name:
        action = item.action or ""
        if "create_experiment" in action:
            experiment_name = "Experiment created"
        elif "complete_experiment" in action:
            experiment_name = "Experiment completed"

    if not experiment_name:
        return -1, None

    return score, {
        "name": str(experiment_name),
        "hypothesis": _first_context_value(context, "hypothesis"),
        "status": _first_context_value(context, "status") or ("success" if item.success else "error"),
        "experiment_id": _first_context_value(context, "experiment_id"),
        "created_at": _dt_iso_utc(item.created_at),
    }


def _pick_latest_creative_insight(
    items: list[ActivityLog],
    skill_name: str,
    builder,
) -> dict | None:
    best_score = -1
    best_insight = None

    for item in items:
        if _normalize_skill_name(item.skill) != skill_name:
            continue
        score, insight = builder(item)
        if insight is None:
            continue
        if score > best_score:
            best_score = score
            best_insight = insight
        if score >= 10:
            break

    return best_insight


def _serialize_activity_item(item: ActivityLog, include_creative_context: bool = False) -> dict:
    details = item.details if isinstance(item.details, dict) else {}
    if include_creative_context:
        details = _enriched_creative_details(details)
    return {
        "id": str(item.id),
        "action": item.action,
        "skill": item.skill,
        "success": bool(item.success),
        "created_at": _dt_iso_utc(item.created_at),
        "description": _extract_description(item.details),
        "details": details,
    }


def _activity_dt_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_creative_action(item: ActivityLog, details: dict | None = None) -> str:
    skill = _normalize_skill_name(item.skill)
    action = (item.action or "unknown").strip()
    details = details if isinstance(details, dict) else (item.details if isinstance(item.details, dict) else {})

    method = None
    if "." in action:
        action_skill, action_method = action.split(".", 1)
        if _normalize_skill_name(action_skill) == skill:
            method = action_method.strip()

    if not method:
        candidate = details.get("method")
        if isinstance(candidate, str) and candidate.strip():
            method = candidate.strip()

    if not method:
        method = CREATIVE_DOMAIN_ACTION_TO_METHOD.get(action)

    if method and skill != "unknown":
        return f"{skill}.{method}"
    return action or skill or "unknown"


def _normalize_identity_fragment(value: object) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        text = " ".join(value.split())
    elif isinstance(value, (int, float, bool)):
        text = str(value)
    else:
        return None
    return text[:120] if text else None


def _creative_identity_fragments(skill: str, context: dict, details: dict) -> tuple[str, ...]:
    skill_keys = {
        "brainstorm": ("session_id", "idea", "topic"),
        "experiment": ("experiment_id", "model_id", "experiment_name", "model_name", "hypothesis"),
        "community": ("campaign_id", "campaign_name", "member_id", "member_name", "engagement_action", "content"),
        "fact_check": ("claim_id", "claim", "verdict", "source"),
        "memeothy": ("scripture_type", "title", "content", "description", "status"),
    }
    generic_keys = (
        "session_id",
        "experiment_id",
        "claim_id",
        "member_id",
        "campaign_id",
        "model_id",
        "topic",
        "idea",
        "claim",
        "title",
        "content",
        "description",
    )

    fragments: list[str] = []
    seen: set[str] = set()
    for key in (*skill_keys.get(skill, ()), *generic_keys):
        fragment = _normalize_identity_fragment(context.get(key) or details.get(key))
        if fragment and fragment not in seen:
            fragments.append(fragment)
            seen.add(fragment)
    return tuple(fragments)


def _creative_dedupe_key(item: ActivityLog, context: dict | None = None, details: dict | None = None) -> tuple[str, str]:
    details = details if isinstance(details, dict) else (item.details if isinstance(item.details, dict) else {})
    skill = _normalize_skill_name(item.skill)
    canonical_action = _canonical_creative_action(item, details)
    return skill, canonical_action


def _is_creative_wrapper_action(item: ActivityLog) -> bool:
    action = (item.action or "").strip()
    if "." not in action:
        return False
    action_skill, _ = action.split(".", 1)
    return _normalize_skill_name(action_skill) == _normalize_skill_name(item.skill)


def _creative_richness_score(item: ActivityLog, context: dict | None = None, details: dict | None = None) -> int:
    details = details if isinstance(details, dict) else (item.details if isinstance(item.details, dict) else {})
    context = context if isinstance(context, dict) else _normalized_creative_context(details)

    score = len(context)
    if not _is_creative_wrapper_action(item):
        score += 20

    for key in (
        "topic",
        "idea",
        "experiment_name",
        "hypothesis",
        "campaign_name",
        "member_name",
        "claim",
        "content",
        "title",
    ):
        if context.get(key) not in (None, ""):
            score += 2

    for key in ("duration_ms", "args_preview", "result_preview"):
        if details.get(key) not in (None, "", [], {}):
            score += 1

    for key in ("idea", "experiment", "claim", "campaign", "member", "model", "response"):
        if isinstance(details.get(key), dict):
            score += 2

    return score


def _creative_display_description(item: ActivityLog, canonical_action: str, context: dict, details: dict) -> str:
    preferred = _first_context_value(
        context,
        "description",
        "idea",
        "claim",
        "content",
        "topic",
        "experiment_name",
        "campaign_name",
        "member_name",
        "title",
        "goal",
    )
    if preferred is not None:
        return str(preferred)

    fallback_map = {
        "brainstorm.start_session": "Brainstorm session started",
        "brainstorm.add_idea": "Brainstorm idea added",
        "community.track_member": "Community member tracked",
        "community.record_engagement": "Community engagement recorded",
        "community.create_campaign": "Community campaign created",
        "experiment.create_experiment": "Experiment created",
        "experiment.log_metrics": "Experiment metrics logged",
        "experiment.complete_experiment": "Experiment completed",
        "fact_check.extract_claims": "Claims extracted for verification",
        "fact_check.assess_claim": "Claim assessed",
        "fact_check.quick_check": "Claim quick-checked",
        "fact_check.compare_sources": "Sources compared for claim",
        "memeothy.join": "Joined the Church of Molt",
        "memeothy.submit_prophecy": "Submitted prophecy",
        "memeothy.submit_art": "Submitted sacred art",
        "memeothy.get_canon": "Fetched canon",
        "memeothy.get_prophets": "Fetched prophets",
        "memeothy.get_gallery": "Fetched gallery",
        "memeothy.status": "Checked church status",
    }
    return fallback_map.get(canonical_action, _extract_description(details) or canonical_action)


def _serialize_creative_activity_item(item: ActivityLog) -> dict:
    details = _enriched_creative_details(item.details if isinstance(item.details, dict) else {})
    context = details.get("creative_context") if isinstance(details.get("creative_context"), dict) else {}
    canonical_action = _canonical_creative_action(item, details)
    return {
        "id": str(item.id),
        "action": canonical_action,
        "skill": _normalize_skill_name(item.skill),
        "success": bool(item.success),
        "created_at": _dt_iso_utc(item.created_at),
        "description": _creative_display_description(item, canonical_action, context, details),
        "details": details,
        "raw_actions": [item.action or canonical_action],
        "duplicate_count": 1,
    }


def _merge_creative_details(primary: dict, secondary: dict) -> dict:
    merged = dict(secondary)
    merged.update(primary)

    secondary_context = secondary.get("creative_context") if isinstance(secondary.get("creative_context"), dict) else {}
    primary_context = primary.get("creative_context") if isinstance(primary.get("creative_context"), dict) else {}
    merged_context = dict(secondary_context)
    merged_context.update(primary_context)
    if merged_context:
        merged["creative_context"] = merged_context

    raw_actions = sorted(set((secondary.get("raw_actions") or []) + (primary.get("raw_actions") or [])))
    if raw_actions:
        merged["raw_actions"] = raw_actions

    duplicate_count = int(secondary.get("duplicate_count", 1) or 1) + int(primary.get("duplicate_count", 1) or 1)
    merged["duplicate_count"] = duplicate_count
    return merged


def _dedupe_creative_activities(items: list[ActivityLog]) -> list[dict]:
    deduped: list[dict] = []
    latest_index_by_key: dict[tuple[str, str], int] = {}

    for item in items:
        serialized = _serialize_creative_activity_item(item)
        details = serialized["details"] if isinstance(serialized.get("details"), dict) else {}
        context = details.get("creative_context") if isinstance(details.get("creative_context"), dict) else {}
        dedupe_key = _creative_dedupe_key(item, context, details)
        identity_fragments = _creative_identity_fragments(str(serialized.get("skill") or "unknown"), context, details)
        created_at_dt = _activity_dt_utc(item.created_at)
        richness = _creative_richness_score(item, context, details)
        serialized["_created_at_dt"] = created_at_dt
        serialized["_richness"] = richness
        serialized["_identity_fragments"] = identity_fragments

        existing_idx = latest_index_by_key.get(dedupe_key)
        if existing_idx is not None:
            existing = deduped[existing_idx]
            existing_dt = existing.get("_created_at_dt")
            existing_identity = tuple(existing.get("_identity_fragments") or ())
            if isinstance(existing_dt, datetime) and isinstance(created_at_dt, datetime):
                if abs((existing_dt - created_at_dt).total_seconds()) <= CREATIVE_DEDUPE_WINDOW_SECONDS:
                    if existing_identity and identity_fragments and existing_identity != identity_fragments:
                        deduped.append(serialized)
                        latest_index_by_key[dedupe_key] = len(deduped) - 1
                        continue
                    existing_richness = int(existing.get("_richness", 0) or 0)
                    if richness > existing_richness:
                        merged = _merge_creative_details(serialized, existing)
                        merged["_created_at_dt"] = existing_dt if existing_dt > created_at_dt else created_at_dt
                        merged["created_at"] = _dt_iso_utc(merged["_created_at_dt"])
                        merged["_richness"] = max(richness, existing_richness)
                        merged["_identity_fragments"] = identity_fragments or existing_identity
                        merged_context = merged["details"].get("creative_context") if isinstance(merged.get("details"), dict) and isinstance(merged["details"].get("creative_context"), dict) else {}
                        merged["description"] = _creative_display_description(item, merged["action"], merged_context, merged["details"])
                        deduped[existing_idx] = merged
                    else:
                        merged = _merge_creative_details(existing, serialized)
                        merged["_created_at_dt"] = existing_dt if existing_dt > created_at_dt else created_at_dt
                        merged["created_at"] = _dt_iso_utc(merged["_created_at_dt"])
                        merged["_richness"] = max(richness, existing_richness)
                        merged["_identity_fragments"] = existing_identity or identity_fragments
                        merged_context = merged["details"].get("creative_context") if isinstance(merged.get("details"), dict) and isinstance(merged["details"].get("creative_context"), dict) else {}
                        merged["description"] = _creative_display_description(item, merged["action"], merged_context, merged["details"])
                        deduped[existing_idx] = merged
                    continue

        deduped.append(serialized)
        latest_index_by_key[dedupe_key] = len(deduped) - 1

    return deduped


def _public_creative_activity_items(items: list[dict], limit: int | None = None) -> list[dict]:
    sliced = items[:limit] if limit is not None else items
    return [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in sliced
    ]


def _aggregate_creative_hourly(items: list[dict]) -> list[dict]:
    hourly_counts: dict[datetime, int] = {}
    for item in items:
        created_at_dt = item.get("_created_at_dt")
        if not isinstance(created_at_dt, datetime):
            continue
        bucket = created_at_dt.replace(minute=0, second=0, microsecond=0)
        hourly_counts[bucket] = hourly_counts.get(bucket, 0) + 1
    return [
        {"hour": _dt_iso_utc(hour), "count": count}
        for hour, count in sorted(hourly_counts.items())
    ]


def _aggregate_creative_actions(items: list[dict], limit: int = 8) -> list[dict]:
    counts = Counter(str(item.get("action") or "unknown") for item in items)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"action": action, "count": count} for action, count in ranked]


def _aggregate_creative_skills(items: list[dict], skill_targets: list[str]) -> list[dict]:
    counts = Counter(str(item.get("skill") or "unknown") for item in items)
    return [
        {"skill": skill_name, "count": int(counts.get(skill_name, 0))}
        for skill_name in skill_targets
    ]


def _build_community_insight(item: ActivityLog) -> tuple[int, dict | None]:
    details = item.details if isinstance(item.details, dict) else {}
    context = _normalized_creative_context(details)
    main = _first_context_value(context, "campaign_name", "member_name", "content", "goal", "description")
    score = 0
    if context.get("campaign_name"):
        score += 12
    if context.get("member_name"):
        score += 10
    if context.get("content"):
        score += 8
    if context.get("goal"):
        score += 3
    if context.get("status"):
        score += 1

    if not main:
        fallback_map = {
            "community.track_member": "Community member tracked",
            "community.record_engagement": "Community engagement recorded",
            "community.create_campaign": "Community campaign created",
        }
        main = fallback_map.get(_canonical_creative_action(item, details))

    if not main:
        return -1, None

    meta_parts = []
    goal = _first_context_value(context, "goal")
    engagement = _first_context_value(context, "engagement_action")
    platform = _first_context_value(context, "platform")
    status = _first_context_value(context, "status")
    if goal:
        meta_parts.append(f"goal={goal}")
    if engagement:
        meta_parts.append(f"engagement={engagement}")
    if platform:
        meta_parts.append(f"platform={platform}")
    if status:
        meta_parts.append(f"status={status}")

    return score, {
        "main": str(main),
        "meta": " · ".join(part for part in meta_parts if part),
        "created_at": _dt_iso_utc(item.created_at),
    }


def _build_fact_check_insight(item: ActivityLog) -> tuple[int, dict | None]:
    details = item.details if isinstance(item.details, dict) else {}
    context = _normalized_creative_context(details)
    main = _first_context_value(context, "claim", "description", "content")
    score = 0
    if context.get("claim"):
        score += 12
    if context.get("verdict"):
        score += 3
    if context.get("confidence") not in (None, ""):
        score += 2
    if context.get("status"):
        score += 1

    if not main:
        fallback_map = {
            "fact_check.extract_claims": "Claims extracted for review",
            "fact_check.assess_claim": "Claim assessed",
            "fact_check.quick_check": "Claim quick-checked",
            "fact_check.compare_sources": "Sources compared",
        }
        main = fallback_map.get(_canonical_creative_action(item, details))

    if not main:
        return -1, None

    meta_parts = []
    verdict = _first_context_value(context, "verdict")
    confidence = _first_context_value(context, "confidence")
    status = _first_context_value(context, "status")
    source = _first_context_value(context, "source")
    if verdict:
        meta_parts.append(f"verdict={verdict}")
    if confidence not in (None, ""):
        meta_parts.append(f"confidence={confidence}")
    if status:
        meta_parts.append(f"status={status}")
    if source:
        meta_parts.append(f"source={source}")

    return score, {
        "main": str(main),
        "meta": " · ".join(part for part in meta_parts if part),
        "created_at": _dt_iso_utc(item.created_at),
    }


def _build_memeothy_insight(item: ActivityLog) -> tuple[int, dict | None]:
    details = item.details if isinstance(item.details, dict) else {}
    context = _normalized_creative_context(details)
    main = _first_context_value(context, "content", "title", "description")
    canonical_action = _canonical_creative_action(item, details)
    score = 0
    if context.get("content"):
        score += 12
    if context.get("title"):
        score += 10
    if context.get("description"):
        score += 6
    if context.get("scripture_type"):
        score += 3
    if context.get("status"):
        score += 1

    if not main:
        fallback_map = {
            "memeothy.join": "Joined the Church of Molt",
            "memeothy.submit_prophecy": "Submitted prophecy",
            "memeothy.submit_art": "Submitted sacred art",
            "memeothy.get_canon": "Fetched canon",
            "memeothy.get_prophets": "Fetched prophets",
            "memeothy.get_gallery": "Fetched gallery",
            "memeothy.status": "Checked church status",
        }
        main = fallback_map.get(canonical_action)

    if not main:
        return -1, None

    meta_parts = []
    scripture_type = _first_context_value(context, "scripture_type")
    status = _first_context_value(context, "status")
    if scripture_type:
        meta_parts.append(f"scripture={scripture_type}")
    if status:
        meta_parts.append(f"status={status}")

    return score, {
        "main": str(main),
        "meta": " · ".join(part for part in meta_parts if part),
        "created_at": _dt_iso_utc(item.created_at),
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/activities")
async def api_activities(
    page: int = 1,
    limit: int = 50,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    base = select(ActivityLog)
    if action:
        base = base.where(ActivityLog.action == action)
    base = base.order_by(ActivityLog.created_at.desc())

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "id": str(a.id),
            "type": a.action,
            "action": a.action,
            "skill": a.skill,
            "success": bool(a.success),
            "status": "ok" if a.success else "error",
            "description": _extract_description(a.details),
            "details": a.details,
            "created_at": _dt_iso_utc(a.created_at),
        }
        for a in rows
    ]
    return build_paginated_response(items, total, page, limit)


@router.post("/activities")
async def create_activity(body: CreateActivity, db: AsyncSession = Depends(get_db)):
    if body.action == "six_hour_review":
        last_stmt = (
            select(ActivityLog)
            .where(ActivityLog.action == "six_hour_review")
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
        last_activity = (await db.execute(last_stmt)).scalar_one_or_none()
        if last_activity and last_activity.created_at:
            now_utc = datetime.now(timezone.utc)
            created_at = last_activity.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (now_utc - created_at).total_seconds() < 5 * 3600:
                next_allowed = created_at + timedelta(hours=5)
                return {
                    "status": "cooldown_active",
                    "next_allowed": next_allowed.isoformat(),
                    "created": False,
                }

    activity = ActivityLog(
        id=uuid.uuid4(),
        action=body.action,
        skill=body.skill,
        details=body.details,
        success=body.success,
        error_message=body.error_message,
    )
    db.add(activity)

    # Mirror commit/comment-style events into social feed for dashboard visibility.
    action = body.action or ""
    details = body.details if isinstance(body.details, dict) else {}
    if _should_mirror_to_social(action, details):
        social_post = SocialPost(
            id=uuid.uuid4(),
            platform="activity",
            content=_social_content_from_activity(
                action=action,
                skill=body.skill,
                details=details,
                success=body.success,
                error_message=body.error_message,
            ),
            visibility="public",
            metadata_json={
                "source": "activity_log",
                "action": action,
                "skill": body.skill,
                "success": body.success,
                "details": details,
            },
        )
        db.add(social_post)

    await db.commit()
    return {"id": str(activity.id), "created": True}


@router.get("/activities/cron-summary")
async def cron_activity_summary(days: int = 7, db: AsyncSession = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            ActivityLog.action,
            func.count(ActivityLog.id).label("executions"),
            func.coalesce(func.sum(cast(ActivityLog.details["estimated_tokens"].astext, Float)), 0).label("total_estimated_tokens"),
        )
        .where(ActivityLog.action == "cron_execution")
        .where(ActivityLog.created_at >= cutoff)
        .group_by(ActivityLog.action)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "action": row.action,
            "executions": int(row.executions or 0),
            "total_estimated_tokens": float(row.total_estimated_tokens or 0),
            "days": days,
        }
        for row in rows
    ]


@router.get("/activities/timeline")
async def activity_timeline(days: int = 7, db: AsyncSession = Depends(get_db)):
    """Daily activity counts for the last N days (server-side aggregation)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date(ActivityLog.created_at).label("day"),
            func.count(ActivityLog.id).label("count"),
        )
        .where(ActivityLog.created_at >= cutoff)
        .group_by(func.date(ActivityLog.created_at))
        .order_by(func.date(ActivityLog.created_at))
    )
    return [{"day": str(r.day), "count": r.count} for r in result.all()]


@router.get("/activities/visualization")
async def activity_visualization(
    hours: int = 24,
    limit: int = 25,
    include_creative: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Aggregated activity data for UI visualizations."""
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=max(1, min(hours, 24 * 30)))
    limit = max(1, min(limit, 200))

    hour_bucket = func.date_trunc("hour", ActivityLog.created_at).label("hour")

    hourly_rows = (
        await db.execute(
            select(
                hour_bucket,
                func.count(ActivityLog.id).label("count"),
            )
            .where(ActivityLog.created_at >= cutoff)
            .group_by(hour_bucket)
            .order_by(hour_bucket)
        )
    ).all()

    actions_rows = (
        await db.execute(
            select(ActivityLog.action, func.count(ActivityLog.id).label("count"))
            .where(ActivityLog.created_at >= cutoff)
            .group_by(ActivityLog.action)
            .order_by(desc(func.count(ActivityLog.id)))
            .limit(12)
        )
    ).all()

    skill_bucket = func.coalesce(ActivityLog.skill, "unknown").label("skill")

    skills_rows = (
        await db.execute(
            select(
                skill_bucket,
                func.count(ActivityLog.id).label("count"),
            )
            .where(ActivityLog.created_at >= cutoff)
            .group_by(skill_bucket)
            .order_by(desc(func.count(ActivityLog.id)))
            .limit(12)
        )
    ).all()

    creative_skill_targets = list(CREATIVE_SKILL_TARGETS)
    deduped_creative_items: list[dict] = []
    creative_recent_public: list[dict] = []
    creative_hourly: list[dict] = []
    creative_actions: list[dict] = []
    creative_skills = [
        {"skill": skill_name, "count": 0}
        for skill_name in creative_skill_targets
    ]
    creative_history_items: list[ActivityLog] = []
    creative_total = 0
    creative_success = 0
    creative_fail = 0
    if include_creative:
        skill_expr = func.lower(func.replace(func.coalesce(ActivityLog.skill, ""), "-", "_"))
        creative_candidates = _creative_skill_candidates(creative_skill_targets)

        creative_filter = or_(*[skill_expr == value for value in sorted(creative_candidates)])

        creative_window_items = (
            await db.execute(
                select(ActivityLog)
                .where(ActivityLog.created_at >= cutoff)
                .where(creative_filter)
                .order_by(ActivityLog.created_at.desc())
            )
        ).scalars().all()

        creative_history_items = (
            await db.execute(
                select(ActivityLog)
                .where(creative_filter)
                .order_by(ActivityLog.created_at.desc())
                .limit(250)
            )
        ).scalars().all()

        deduped_creative_items = _dedupe_creative_activities(creative_window_items)
        creative_total = len(deduped_creative_items)
        creative_success = sum(1 for item in deduped_creative_items if item.get("success"))
        creative_fail = max(0, creative_total - creative_success)
        creative_hourly = _aggregate_creative_hourly(deduped_creative_items)
        creative_actions = _aggregate_creative_actions(deduped_creative_items)
        creative_skills = _aggregate_creative_skills(deduped_creative_items, creative_skill_targets)
        creative_recent_public = _public_creative_activity_items(deduped_creative_items, limit=limit)

    total_rows = (
        await db.execute(
            select(
                func.count(ActivityLog.id).label("total"),
                func.sum(case((ActivityLog.success == True, 1), else_=0)).label("success"),
                func.sum(case((ActivityLog.success == False, 1), else_=0)).label("fail"),
            ).where(ActivityLog.created_at >= cutoff)
        )
    ).one()

    recent_items = (
        await db.execute(
            select(ActivityLog)
            .where(ActivityLog.created_at >= cutoff)
            .order_by(ActivityLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    latest_brainstorm = _pick_latest_creative_insight(
        creative_history_items,
        "brainstorm",
        _build_brainstorm_insight,
    )
    latest_experiment = _pick_latest_creative_insight(
        creative_history_items,
        "experiment",
        _build_experiment_insight,
    )
    latest_community = _pick_latest_creative_insight(
        creative_history_items,
        "community",
        _build_community_insight,
    )
    latest_fact_check = _pick_latest_creative_insight(
        creative_history_items,
        "fact_check",
        _build_fact_check_insight,
    )
    latest_memeothy = _pick_latest_creative_insight(
        creative_history_items,
        "memeothy",
        _build_memeothy_insight,
    )

    return {
        "window_hours": hours,
        "generated_at": now_utc.isoformat(),
        "summary": {
            "total": int(total_rows.total or 0),
            "success": int(total_rows.success or 0),
            "fail": int(total_rows.fail or 0),
        },
        "hourly": [
            {"hour": _dt_iso_utc(row.hour), "count": int(row.count or 0)}
            for row in hourly_rows
        ],
        "actions": [
            {"action": row.action or "unknown", "count": int(row.count or 0)}
            for row in actions_rows
        ],
        "skills": [
            {"skill": row.skill or "unknown", "count": int(row.count or 0)}
            for row in skills_rows
        ],
        "creative": {
            "enabled": include_creative,
            "targets": creative_skill_targets,
            "total": creative_total,
            "success": creative_success,
            "fail": creative_fail,
            "success_rate": round((creative_success * 100 / creative_total), 2) if creative_total else 0.0,
            "skills": creative_skills,
            "hourly": creative_hourly,
            "actions": creative_actions,
            "recent": creative_recent_public,
            "insights": {
                "latest_brainstorm": latest_brainstorm,
                "latest_experiment": latest_experiment,
                "latest_community": latest_community,
                "latest_fact_check": latest_fact_check,
                "latest_memeothy": latest_memeothy,
            },
        } if include_creative else None,
        "recent": [
            _serialize_activity_item(item)
            for item in recent_items
        ],
    }


@router.delete("/activities/{activity_id}")
async def delete_activity(activity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ActivityLog).where(ActivityLog.id == activity_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Activity not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": True, "id": activity_id}


@router.patch("/activities/{activity_id}")
async def update_activity(activity_id: str, body: UpdateActivity, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ActivityLog).where(ActivityLog.id == activity_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Activity not found")
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row.to_dict()



