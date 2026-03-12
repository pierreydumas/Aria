"""
Skill Registry endpoints — read skill health status from the skill_status table.
Skill Invocation stats (S5-07) — observability dashboard data.
"""

import logging
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, case, text, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    SkillStatusRecord,
    SkillInvocation,
    KnowledgeQueryLog,
    KnowledgeEntity,
    ModelUsage,
    EngineChatSession,
    EngineChatSessionArchive,
    EngineChatMessage,
    EngineChatMessageArchive,
    SkillGraphEntity,
    SkillGraphRelation,
    EngineAgentState,
)
from deps import get_db
from schemas.requests import CreateSkillInvocation

router = APIRouter(tags=["Skills"])
logger = logging.getLogger("aria.api.skills")

_SKILL_SUPPORT_DIRS = {"_template", "__pycache__", "pipelines"}


def _skills_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "aria_skills"
        if candidate.exists() and candidate.is_dir():
            return candidate
    return Path.cwd() / "aria_skills"


def _coherence_scan(include_support: bool = False) -> dict:
    root = _skills_root()
    rows: list[dict] = []
    if not root.exists():
        return {
            "root": str(root),
            "skills": [],
            "count": 0,
            "coherent_count": 0,
            "incoherent_count": 0,
            "coherent": True,
        }

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if not include_support and entry.name in _SKILL_SUPPORT_DIRS:
            continue

        canonical = f"aria-{entry.name.replace('_', '-')}"
        init_path = entry / "__init__.py"
        json_path = entry / "skill.json"
        md_path = entry / "SKILL.md"

        row = {
            "skill": entry.name,
            "canonical": canonical,
            "is_support_dir": entry.name in _SKILL_SUPPORT_DIRS,
            "has_init": init_path.exists(),
            "has_skill_json": json_path.exists(),
            "has_skill_md": md_path.exists(),
            "name_matches": None,
            "errors": [],
            "warnings": [],
            "coherent": True,
        }

        if not row["has_init"]:
            row["errors"].append("Missing __init__.py")
        if not row["has_skill_json"]:
            row["errors"].append("Missing skill.json")
        if not row["has_skill_md"]:
            row["errors"].append("Missing SKILL.md")

        if row["has_skill_json"]:
            try:
                import json as _json

                manifest = _json.loads(json_path.read_text(encoding="utf-8"))
                actual_name = manifest.get("name")
                row["manifest_name"] = actual_name
                row["name_matches"] = actual_name == canonical
                if actual_name != canonical:
                    row["errors"].append(
                        f"skill.json name mismatch: expected '{canonical}', got '{actual_name}'"
                    )
            except Exception as exc:
                logger.warning("skill.json parse error: %s", exc)
                row["name_matches"] = False
                row["errors"].append(f"skill.json parse error: {exc}")

        row["coherent"] = len(row["errors"]) == 0
        rows.append(row)

    coherent_count = sum(1 for row in rows if row["coherent"])
    return {
        "root": str(root),
        "skills": rows,
        "count": len(rows),
        "coherent_count": coherent_count,
        "incoherent_count": len(rows) - coherent_count,
        "coherent": coherent_count == len(rows),
    }

# Layer int → display label
_LAYER_LABELS = {0: "L0", 1: "L1", 2: "L2", 3: "L3", 4: "L4"}


def _discover_known_skills() -> list[tuple[str, str]]:
    """Build known-skills list dynamically from skill.json manifests."""
    import json as _json

    root = _skills_root()
    skills: list[tuple[str, str]] = []
    if not root.exists():
        return skills
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.name in _SKILL_SUPPORT_DIRS:
            continue
        json_path = entry / "skill.json"
        if not json_path.exists():
            continue
        try:
            manifest = _json.loads(json_path.read_text(encoding="utf-8"))
            layer_int = manifest.get("layer", 3)
            label = _LAYER_LABELS.get(int(layer_int), "L3")
            skills.append((entry.name, label))
        except Exception:
            skills.append((entry.name, "L3"))
    return skills


# Lazy-evaluated; refreshed on each seed/list call
_KNOWN_SKILLS: list[tuple[str, str]] = []


def _get_known_skills() -> list[tuple[str, str]]:
    global _KNOWN_SKILLS
    _KNOWN_SKILLS = _discover_known_skills()
    return _KNOWN_SKILLS


# ── List / Filter ────────────────────────────────────────────────────────────

@router.get("/skills")
async def list_skills(
    status: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all registered skills with optional status filter. Auto-seeds if empty."""
    stmt = select(SkillStatusRecord).order_by(SkillStatusRecord.skill_name)
    if status:
        stmt = stmt.where(SkillStatusRecord.status == status)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Auto-seed if table is empty (first access)
    if not rows and not status:
        for name, layer in _get_known_skills():
            seed_stmt = pg_insert(SkillStatusRecord).values(
                skill_name=name,
                canonical_name=name.replace("_", "-"),
                status="healthy",
                layer=layer,
            ).on_conflict_do_nothing(index_elements=["skill_name"])
            await db.execute(seed_stmt)
        await db.commit()
        result = await db.execute(
            select(SkillStatusRecord).order_by(SkillStatusRecord.skill_name)
        )
        rows = result.scalars().all()

    invocation_rows = (
        await db.execute(
            select(
                SkillInvocation.skill_name,
                func.count().label("total"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
                func.max(SkillInvocation.created_at).label("last_execution"),
            )
            .group_by(SkillInvocation.skill_name)
        )
    ).all()

    usage_by_skill = {
        row.skill_name: {
            "total": int(row.total or 0),
            "failures": int(row.failures or 0),
            "last_execution": row.last_execution,
        }
        for row in invocation_rows
    }

    # ── Enrich with focus_affinity (from graph) and assigned_agents (from agent_state) ──
    # Build skill→affinity map from graph relations (graph uses canonical names, map via directory property)
    affinity_rows = (
        await db.execute(
            select(SkillGraphEntity.properties, SkillGraphRelation.to_entity)
            .join(SkillGraphRelation, SkillGraphEntity.id == SkillGraphRelation.from_entity)
            .where(SkillGraphEntity.type == "skill")
            .where(SkillGraphRelation.relation_type == "affinity")
        )
    ).all()
    # Get focus_mode names by entity id
    fm_entities = (
        await db.execute(
            select(SkillGraphEntity.id, SkillGraphEntity.name)
            .where(SkillGraphEntity.type == "focus_mode")
        )
    ).all()
    fm_names = {row.id: row.name for row in fm_entities}
    affinity_map: dict[str, list[str]] = {}
    for row in affinity_rows:
        fm = fm_names.get(row.to_entity)
        dir_name = (row.properties or {}).get("directory", "")
        if fm and dir_name:
            affinity_map.setdefault(dir_name, []).append(fm)

    # Build skill→agents map from agent_state
    agent_rows = (
        await db.execute(
            select(EngineAgentState.agent_id, EngineAgentState.skills)
            .where(EngineAgentState.enabled == True)
        )
    ).all()
    agents_map: dict[str, list[str]] = {}
    for ag in agent_rows:
        for sk in (ag.skills or []):
            agents_map.setdefault(sk, []).append(ag.agent_id)

    items = []
    for row in rows:
        item = row.to_dict()
        agg = usage_by_skill.get(row.skill_name)
        if agg:
            item["use_count"] = max(int(item.get("use_count") or 0), agg["total"])
            item["error_count"] = max(int(item.get("error_count") or 0), agg["failures"])
            if agg["last_execution"]:
                item["last_execution"] = agg["last_execution"].isoformat()

        if not item.get("last_health_check"):
            item["last_health_check"] = item.get("updated_at")

        item["focus_affinity"] = affinity_map.get(row.skill_name, [])
        item["assigned_agents"] = agents_map.get(row.skill_name, [])

        items.append(item)

    # Layer distribution
    layer_dist: dict[str, int] = {}
    for row in rows:
        layer_dist[row.layer or "?"] = layer_dist.get(row.layer or "?", 0) + 1

    return {
        "skills": items,
        "count": len(rows),
        "healthy": sum(1 for r in rows if r.status == "healthy"),
        "degraded": sum(1 for r in rows if r.status == "degraded"),
        "unavailable": sum(1 for r in rows if r.status == "unavailable"),
        "layer_distribution": layer_dist,
    }


# ── Single Skill Health ─────────────────────────────────────────────────────

@router.get("/skills/{name}/health")
async def get_skill_health(name: str, db: AsyncSession = Depends(get_db)):
    """Return health details for a single skill by name."""
    result = await db.execute(
        select(SkillStatusRecord).where(SkillStatusRecord.skill_name == name)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return row.to_dict()


# ── Seed Skills ──────────────────────────────────────────────────────────────

@router.post("/skills/seed")
async def seed_skills(db: AsyncSession = Depends(get_db)):
    """Seed skill_status from manifests, update stale layers, remove ghost entries."""
    known = _get_known_skills()
    known_names = {name for name, _ in known}
    created = 0
    updated = 0

    for name, layer in known:
        stmt = pg_insert(SkillStatusRecord).values(
            skill_name=name,
            canonical_name=name.replace("_", "-"),
            status="healthy",
            layer=layer,
        ).on_conflict_do_nothing(index_elements=["skill_name"])
        result = await db.execute(stmt)
        created += max(0, result.rowcount)

    # Update layer labels for existing rows that diverge from manifests
    layer_map = dict(known)
    existing = (await db.execute(select(SkillStatusRecord))).scalars().all()
    for row in existing:
        expected_layer = layer_map.get(row.skill_name)
        if expected_layer and row.layer != expected_layer:
            row.layer = expected_layer
            updated += 1

    # Remove ghost entries (in DB but no manifest on disk)
    removed = []
    for row in existing:
        if row.skill_name not in known_names:
            removed.append(row.skill_name)
            await db.delete(row)

    await db.commit()
    return {
        "seeded": created,
        "updated_layers": updated,
        "removed_ghosts": removed,
        "total": len(known),
    }


@router.get("/skills/coherence")
async def get_skills_coherence(include_support: bool = False):
    """Report skill-system coherence (init + manifest + docs) for adaptation tooling."""
    data = _coherence_scan(include_support=include_support)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return data


# ── Skill Invocation Recording (S5-07) ──────────────────────────────────────

@router.post("/skills/invocations")
async def record_invocation(body: CreateSkillInvocation, db: AsyncSession = Depends(get_db)):
    """Record a skill invocation for observability."""
    inv = SkillInvocation(
        skill_name=body.skill_name,
        tool_name=body.tool_name,
        agent_id=body.agent_id,
        duration_ms=body.duration_ms,
        success=body.success,
        error_type=body.error_type,
        tokens_used=body.tokens_used,
        model_used=body.model_used,
    )
    db.add(inv)
    await db.commit()
    return {"recorded": True}


@router.delete("/skills/invocations/purge-test-data")
async def purge_test_invocations(db: AsyncSession = Depends(get_db)):
    """
    Remove synthetic test invocations that pollute health scores.

    Deletes invocations whose tool_name matches known test patterns
    (e.g. embedding-lookup-*, etl-transform-*).
    """
    from sqlalchemy import delete as sa_delete, or_

    patterns = [
        SkillInvocation.tool_name.like("embedding-lookup-%"),
        SkillInvocation.tool_name.like("etl-transform-%"),
    ]
    stmt = sa_delete(SkillInvocation).where(or_(*patterns))
    result = await db.execute(stmt)
    await db.commit()
    return {"purged": result.rowcount, "patterns": ["embedding-lookup-%", "etl-transform-%"]}


@router.get("/skills/stats")
async def skill_stats(hours: int = 24, db: AsyncSession = Depends(get_db)):
    """Skill performance stats for the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    skill_expr = func.split_part(ModelUsage.model, ":", 2)
    usage_token_rows = (
        await db.execute(
            select(
                skill_expr.label("skill_name"),
                func.coalesce(func.sum(func.coalesce(ModelUsage.input_tokens, 0) + func.coalesce(ModelUsage.output_tokens, 0)), 0).label("total_tokens"),
            )
            .where(ModelUsage.created_at >= cutoff)
            .where(ModelUsage.model.like("skill:%:%"))
            .group_by(text("1"))
        )
    ).all()
    usage_tokens_by_skill = {
        str(row.skill_name or ""): int(row.total_tokens or 0)
        for row in usage_token_rows
        if row.skill_name
    }

    stmt = (
        select(
            SkillInvocation.skill_name,
            func.count().label("total"),
            func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
            func.sum(case((SkillInvocation.success == True, 1), else_=0)).label("successes"),
            func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
            func.sum(SkillInvocation.tokens_used).label("total_tokens"),
        )
        .where(SkillInvocation.created_at >= cutoff)
        .group_by(SkillInvocation.skill_name)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    stats = []
    for row in result.all():
        total = row.total or 1
        invocation_tokens = int(row.total_tokens or 0)
        usage_tokens = usage_tokens_by_skill.get(str(row.skill_name or ""), 0)
        total_tokens = invocation_tokens if invocation_tokens > 0 else usage_tokens
        stats.append({
            "skill_name": row.skill_name,
            "total": row.total,
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "successes": row.successes or 0,
            "failures": row.failures or 0,
            "error_rate": round((row.failures or 0) / total, 3),
            "total_tokens": total_tokens,
        })
    return {"stats": stats, "hours": hours}


@router.get("/skills/stats/summary")
async def skill_stats_summary(hours: int = 24, db: AsyncSession = Depends(get_db)):
    """Compact aggregate summary for skills telemetry widgets."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    summary_row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
                func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
            ).where(SkillInvocation.created_at >= cutoff)
        )
    ).one()

    recent = (
        await db.execute(
            select(SkillInvocation.skill_name, func.count().label("count"))
            .where(SkillInvocation.created_at >= cutoff)
            .group_by(SkillInvocation.skill_name)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    total = int(summary_row.total or 0)
    failures = int(summary_row.failures or 0)
    return {
        "hours": hours,
        "total": total,
        "failures": failures,
        "error_rate": round((failures / max(total, 1)), 3),
        "avg_duration_ms": round(float(summary_row.avg_duration_ms or 0), 1),
        "invocations": [
            {"skill_name": row.skill_name, "count": int(row.count or 0)}
            for row in recent
        ],
    }


@router.get("/skills/stats/{skill_name}")
async def skill_detail_stats(
    skill_name: str,
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
):
    """Detailed stats for one skill with recent invocations."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(SkillInvocation)
        .where(SkillInvocation.skill_name == skill_name)
        .where(SkillInvocation.created_at >= cutoff)
        .order_by(SkillInvocation.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    invocations = [i.to_dict() for i in result.scalars().all()]

    total = len(invocations)
    failures = sum(1 for i in invocations if not i.get("success", True))
    avg_duration = (
        sum(i.get("duration_ms", 0) or 0 for i in invocations) / max(total, 1)
    )
    return {
        "skill_name": skill_name,
        "total": total,
        "failures": failures,
        "error_rate": round(failures / max(total, 1), 3),
        "avg_duration_ms": round(avg_duration, 1),
        "invocations": invocations[:25],
    }


@router.get("/skills/insights")
async def skills_insights(
    hours: int = 24,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Rich skill observability payload for the dashboard (stats + timeline + graph activity)."""
    safe_hours = max(1, min(hours, 24 * 30))
    safe_limit = max(10, min(limit, 500))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)

    # Headline metrics
    totals_row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(case((SkillInvocation.success == True, 1), else_=0)).label("successes"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
                func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
                func.coalesce(func.sum(SkillInvocation.tokens_used), 0).label("total_tokens"),
                func.count(func.distinct(SkillInvocation.skill_name)).label("unique_skills"),
                func.count(func.distinct(SkillInvocation.tool_name)).label("unique_tools"),
            ).where(SkillInvocation.created_at >= cutoff)
        )
    ).one()

    total_invocations = int(totals_row.total or 0)
    failures = int(totals_row.failures or 0)
    successes = int(totals_row.successes or 0)
    success_rate = round((successes / max(total_invocations, 1)) * 100, 1)

    skill_expr = func.split_part(ModelUsage.model, ":", 2)
    usage_token_rows = (
        await db.execute(
            select(
                skill_expr.label("skill_name"),
                func.coalesce(func.sum(func.coalesce(ModelUsage.input_tokens, 0) + func.coalesce(ModelUsage.output_tokens, 0)), 0).label("total_tokens"),
            )
            .where(ModelUsage.created_at >= cutoff)
            .where(ModelUsage.model.like("skill:%:%"))
            .group_by(text("1"))
        )
    ).all()
    usage_tokens_by_skill = {
        str(row.skill_name or ""): int(row.total_tokens or 0)
        for row in usage_token_rows
        if row.skill_name
    }

    # Skill-level breakdown
    skill_rows = (
        await db.execute(
            select(
                SkillInvocation.skill_name,
                func.count().label("invocations"),
                func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
                func.sum(case((SkillInvocation.success == True, 1), else_=0)).label("successes"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
                func.coalesce(func.sum(SkillInvocation.tokens_used), 0).label("tokens"),
            )
            .where(SkillInvocation.created_at >= cutoff)
            .group_by(SkillInvocation.skill_name)
            .order_by(func.count().desc())
        )
    ).all()

    by_skill = []
    for row in skill_rows:
        invocations = int(row.invocations or 0)
        row_failures = int(row.failures or 0)
        invocation_tokens = int(row.tokens or 0)
        usage_tokens = usage_tokens_by_skill.get(str(row.skill_name or ""), 0)
        total_tokens = invocation_tokens if invocation_tokens > 0 else usage_tokens
        by_skill.append({
            "skill_name": row.skill_name,
            "invocations": invocations,
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "successes": int(row.successes or 0),
            "failures": row_failures,
            "error_rate": round((row_failures / max(invocations, 1)) * 100, 1),
            "total_tokens": total_tokens,
        })

    summary_total_tokens = sum(int(item.get("total_tokens") or 0) for item in by_skill)

    # Tool-level breakdown
    tool_rows = (
        await db.execute(
            select(
                SkillInvocation.tool_name,
                func.count().label("invocations"),
                func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
            )
            .where(SkillInvocation.created_at >= cutoff)
            .group_by(SkillInvocation.tool_name)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()

    by_tool = [
        {
            "tool_name": row.tool_name,
            "invocations": int(row.invocations or 0),
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "error_rate": round((int(row.failures or 0) / max(int(row.invocations or 0), 1)) * 100, 1),
        }
        for row in tool_rows
    ]

    # Timeline (hourly)
    timeline_bucket = func.date_trunc("hour", SkillInvocation.created_at)
    timeline_rows = (
        await db.execute(
            select(
                timeline_bucket.label("bucket"),
                func.count().label("invocations"),
                func.avg(SkillInvocation.duration_ms).label("avg_duration_ms"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
            )
            .where(SkillInvocation.created_at >= cutoff)
            .group_by(timeline_bucket)
            .order_by(text("1"))
        )
    ).all()

    timeline = [
        {
            "hour": row.bucket.isoformat() if row.bucket else None,
            "invocations": int(row.invocations or 0),
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "error_rate": round((int(row.failures or 0) / max(int(row.invocations or 0), 1)) * 100, 1),
        }
        for row in timeline_rows
    ]

    # Recent skill executions
    recent_rows = (
        await db.execute(
            select(SkillInvocation)
            .where(SkillInvocation.created_at >= cutoff)
            .order_by(SkillInvocation.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()

    recent_invocations = [
        {
            "id": str(item.id),
            "skill_name": item.skill_name,
            "tool_name": item.tool_name,
            "duration_ms": item.duration_ms,
            "success": item.success,
            "error_type": item.error_type,
            "tokens_used": item.tokens_used,
            "model_used": item.model_used,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in recent_rows
    ]

    # GraphQL / graph interrogation activity from knowledge query log
    query_rows = (
        await db.execute(
            select(KnowledgeQueryLog)
            .where(KnowledgeQueryLog.created_at >= cutoff)
            .order_by(KnowledgeQueryLog.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()

    graph_start_ids: set[str] = set()
    for log in query_rows:
        params = log.params or {}
        start = params.get("start") if isinstance(params, dict) else None
        if isinstance(start, str) and start.strip():
            graph_start_ids.add(start.strip())

    start_name_by_id: dict[str, str] = {}
    start_uuid_ids: list[uuid_lib.UUID] = []
    for raw in graph_start_ids:
        try:
            start_uuid_ids.append(uuid_lib.UUID(raw))
        except ValueError:
            continue

    if start_uuid_ids:
        entities = (
            await db.execute(
                select(SkillGraphEntity.id, SkillGraphEntity.name)
                .where(SkillGraphEntity.id.in_(start_uuid_ids))
            )
        ).all()
        for row in entities:
            start_name_by_id[str(row.id)] = row.name

        missing_ids = [entity_id for entity_id in start_uuid_ids if str(entity_id) not in start_name_by_id]
        if missing_ids:
            knowledge_entities = (
                await db.execute(
                    select(KnowledgeEntity.id, KnowledgeEntity.name)
                    .where(KnowledgeEntity.id.in_(missing_ids))
                )
            ).all()
            for row in knowledge_entities:
                start_name_by_id[str(row.id)] = row.name

    recent_graph_queries = [
        {
            "id": str(log.id),
            "query_type": log.query_type,
            "source": log.source,
            "params": log.params or {},
            "start_name": start_name_by_id.get(str((log.params or {}).get("start") or "")),
            "result_count": log.result_count,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in query_rows
    ]

    return {
        "hours": safe_hours,
        "summary": {
            "total_invocations": total_invocations,
            "success_rate": success_rate,
            "avg_duration_ms": round(float(totals_row.avg_duration_ms or 0), 1),
            "total_tokens": summary_total_tokens,
            "unique_skills": int(totals_row.unique_skills or 0),
            "unique_tools": int(totals_row.unique_tools or 0),
            "failures": failures,
        },
        "by_skill": by_skill,
        "by_tool": by_tool,
        "timeline": timeline,
        "recent_invocations": recent_invocations,
        "recent_graph_queries": recent_graph_queries,
    }


@router.get("/skills/session-trace/latest")
async def latest_session_trace(
    hours: int = 24,
    session_id: str | None = Query(default=None, description="Optional explicit session id from active or archive tables"),
    db: AsyncSession = Depends(get_db),
):
    """Return latest inferred graph-query trace across active + archived engine sessions."""
    safe_hours = max(1, min(hours, 24 * 30))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)

    active_rows = (
        await db.execute(
            select(
                EngineChatSession.id,
                EngineChatSession.agent_id,
                EngineChatSession.session_type,
                EngineChatSession.title,
                EngineChatSession.status,
                EngineChatSession.created_at,
                EngineChatSession.updated_at,
                EngineChatSession.ended_at,
            )
            .where(
                or_(
                    EngineChatSession.created_at >= cutoff,
                    EngineChatSession.updated_at >= cutoff,
                    EngineChatSession.ended_at.is_(None),
                )
            )
            .order_by(func.coalesce(EngineChatSession.updated_at, EngineChatSession.created_at).desc())
            .limit(200)
        )
    ).all()

    archived_rows = (
        await db.execute(
            select(
                EngineChatSessionArchive.id,
                EngineChatSessionArchive.agent_id,
                EngineChatSessionArchive.session_type,
                EngineChatSessionArchive.title,
                EngineChatSessionArchive.status,
                EngineChatSessionArchive.created_at,
                EngineChatSessionArchive.updated_at,
                EngineChatSessionArchive.ended_at,
                EngineChatSessionArchive.archived_at,
            )
            .where(
                or_(
                    EngineChatSessionArchive.created_at >= cutoff,
                    EngineChatSessionArchive.updated_at >= cutoff,
                    EngineChatSessionArchive.archived_at >= cutoff,
                )
            )
            .order_by(
                func.coalesce(
                    EngineChatSessionArchive.updated_at,
                    EngineChatSessionArchive.archived_at,
                    EngineChatSessionArchive.created_at,
                ).desc()
            )
            .limit(200)
        )
    ).all()

    sessions: list[dict] = []
    for row in active_rows:
        sort_at = row.updated_at or row.ended_at or row.created_at
        sessions.append({
            "session_id": str(row.id),
            "agent_id": row.agent_id,
            "source_table": "active",
            "session_type": row.session_type,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "ended_at": row.ended_at,
            "archived_at": None,
            "sort_at": sort_at,
        })

    for row in archived_rows:
        sort_at = row.updated_at or row.ended_at or row.created_at
        sessions.append({
            "session_id": str(row.id),
            "agent_id": row.agent_id,
            "source_table": "archive",
            "session_type": row.session_type,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "ended_at": row.ended_at,
            "archived_at": row.archived_at,
            "sort_at": sort_at,
        })

    if not sessions:
        return {
            "hours": safe_hours,
            "session": None,
            "query_count": 0,
            "trace_nodes": [],
            "trace_edges": [],
            "queries": [],
            "notes": "No sessions found in selected window.",
        }

    sessions.sort(key=lambda item: item.get("sort_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    def _prefer_non_ui_inferred_logs(rows: list[KnowledgeQueryLog]) -> tuple[list[KnowledgeQueryLog], int]:
        if not rows:
            return rows, 0

        preferred: list[KnowledgeQueryLog] = []
        ui_rows: list[KnowledgeQueryLog] = []
        for row in rows:
            params = row.params if isinstance(row.params, dict) else {}
            trace = params.get("__trace") if isinstance(params.get("__trace"), dict) else {}
            origin = str(trace.get("origin") or "").strip().lower()
            trace_session_id = str(trace.get("session_id") or "").strip().lower()
            is_skill_stats_ui_trace = origin == "skill-stats" or trace_session_id.startswith("web-skill-stats-")
            if is_skill_stats_ui_trace:
                ui_rows.append(row)
            else:
                preferred.append(row)

        if preferred:
            return preferred, len(ui_rows)
        return rows, 0

    async def _collect_logs_for_session(
        candidate: dict,
        *,
        allow_broad_fallback: bool,
    ) -> tuple[list[KnowledgeQueryLog], bool, datetime, datetime, int]:
        now_utc = datetime.now(timezone.utc)
        candidate_window_start = candidate.get("created_at") or cutoff
        if candidate_window_start < cutoff:
            candidate_window_start = cutoff

        status_text = str(candidate.get("status") or "").strip().lower()
        is_active_like = status_text not in {"ended", "closed", "archived", "completed"}
        candidate_window_end_anchor = (
            now_utc
            if is_active_like and not candidate.get("ended_at")
            else (
                candidate.get("ended_at")
                or candidate.get("updated_at")
                or candidate.get("sort_at")
            )
        )
        candidate_window_end = (candidate_window_end_anchor or datetime.now(timezone.utc)) + timedelta(minutes=5)
        if candidate_window_end < candidate_window_start:
            candidate_window_end = candidate_window_start + timedelta(minutes=5)

        candidate_logs = (
            await db.execute(
                select(KnowledgeQueryLog)
                .where(KnowledgeQueryLog.created_at >= candidate_window_start)
                .where(KnowledgeQueryLog.created_at <= candidate_window_end)
                .where(KnowledgeQueryLog.params["__trace"]["session_id"].astext == candidate["session_id"])
                .order_by(KnowledgeQueryLog.created_at.asc())
                .limit(400)
            )
        ).scalars().all()

        matched = bool(candidate_logs)

        if not candidate_logs:
            candidate_logs = (
                await db.execute(
                    select(KnowledgeQueryLog)
                    .where(KnowledgeQueryLog.created_at >= candidate_window_start)
                    .where(KnowledgeQueryLog.created_at <= candidate_window_end)
                    .order_by(KnowledgeQueryLog.created_at.asc())
                    .limit(400)
                )
            ).scalars().all()

        if not candidate_logs and allow_broad_fallback:
            anchor = candidate.get("sort_at") or datetime.now(timezone.utc)
            candidate_logs = (
                await db.execute(
                    select(KnowledgeQueryLog)
                    .where(KnowledgeQueryLog.created_at >= anchor - timedelta(minutes=30))
                    .where(KnowledgeQueryLog.created_at <= anchor + timedelta(minutes=30))
                    .order_by(KnowledgeQueryLog.created_at.asc())
                    .limit(200)
                )
            ).scalars().all()

        filtered_ui_noise_count = 0
        if candidate_logs and not matched:
            candidate_logs, filtered_ui_noise_count = _prefer_non_ui_inferred_logs(candidate_logs)

        return candidate_logs, matched, candidate_window_start, candidate_window_end, filtered_ui_noise_count

    selected_session_id = (session_id or "").strip()

    if selected_session_id:
        latest = next((item for item in sessions if item["session_id"] == selected_session_id), None)
        if latest is None:
            return {
                "hours": safe_hours,
                "session": None,
                "query_count": 0,
                "trace_nodes": [],
                "trace_edges": [],
                "queries": [],
                "notes": f"Requested session not found in selected window: {selected_session_id}",
                "matched_by_session": False,
            }
        logs, matched_by_session, window_start, window_end, filtered_ui_noise_count = await _collect_logs_for_session(
            latest,
            allow_broad_fallback=False,
        )
    else:
        non_terminal_status = {"ended", "closed", "archived", "completed"}
        active_live_candidates = [
            item for item in sessions
            if item.get("source_table") == "active"
            and str(item.get("status") or "").strip().lower() not in non_terminal_status
        ]
        non_terminal_candidates = [
            item for item in sessions
            if str(item.get("status") or "").strip().lower() not in non_terminal_status
        ]
        active_any_candidates = [item for item in sessions if item.get("source_table") == "active"]
        ranked_candidates = (
            active_live_candidates
            or non_terminal_candidates
            or active_any_candidates
            or sessions
        )

        latest = ranked_candidates[0]
        logs, matched_by_session, window_start, window_end, filtered_ui_noise_count = await _collect_logs_for_session(
            latest,
            allow_broad_fallback=False,
        )

        # Prefer the newest session that actually has query activity in trace metadata
        # or inferred time window, so the default dashboard action is actionable.
        if not logs:
            scan_budget = min(len(ranked_candidates), 50)
            for candidate in ranked_candidates[1:scan_budget]:
                candidate_logs, candidate_matched, candidate_window_start, candidate_window_end, candidate_filtered = await _collect_logs_for_session(
                    candidate,
                    allow_broad_fallback=False,
                )
                if candidate_logs:
                    latest = candidate
                    logs = candidate_logs
                    matched_by_session = candidate_matched
                    window_start = candidate_window_start
                    window_end = candidate_window_end
                    filtered_ui_noise_count = candidate_filtered
                    break

    def _signature(query_type: str, params: dict) -> str:
        start = str((params or {}).get("start") or "")
        task = str((params or {}).get("task") or "")
        depth = str((params or {}).get("max_depth") or "")
        relation = str((params or {}).get("relation_type") or "")
        direction = str((params or {}).get("direction") or "")
        return "|".join([query_type or "", start, task, depth, relation, direction])

    trace_start_ids: set[str] = set()
    for log in logs:
        params = log.params or {}
        start = params.get("start") if isinstance(params, dict) else None
        if isinstance(start, str) and start.strip():
            trace_start_ids.add(start.strip())

    trace_start_name_by_id: dict[str, str] = {}
    trace_uuid_ids: list[uuid_lib.UUID] = []
    for raw in trace_start_ids:
        try:
            trace_uuid_ids.append(uuid_lib.UUID(raw))
        except ValueError:
            continue

    if trace_uuid_ids:
        trace_entities = (
            await db.execute(
                select(SkillGraphEntity.id, SkillGraphEntity.name)
                .where(SkillGraphEntity.id.in_(trace_uuid_ids))
            )
        ).all()
        for row in trace_entities:
            trace_start_name_by_id[str(row.id)] = row.name

        trace_missing_ids = [entity_id for entity_id in trace_uuid_ids if str(entity_id) not in trace_start_name_by_id]
        if trace_missing_ids:
            knowledge_trace_entities = (
                await db.execute(
                    select(KnowledgeEntity.id, KnowledgeEntity.name)
                    .where(KnowledgeEntity.id.in_(trace_missing_ids))
                )
            ).all()
            for row in knowledge_trace_entities:
                trace_start_name_by_id[str(row.id)] = row.name

    trace_nodes: list[dict] = []
    trace_edges: list[dict] = []
    queries: list[dict] = []
    trace_nodes.append({"id": "session", "label": "Session Start", "kind": "session"})

    prev_node_id = "session"
    seen_signature_to_node: dict[str, str] = {}
    span_to_node: dict[str, str] = {}
    for index, log in enumerate(logs):
        params = log.params or {}
        trace_ctx = params.get("__trace") if isinstance(params.get("__trace"), dict) else {}
        query_type = str(log.query_type or "query")
        span_id = str(trace_ctx.get("span_id") or "").strip()
        parent_span_id = str(trace_ctx.get("parent_span_id") or "").strip()
        node_id = span_id if span_id else f"q-{index}"
        if node_id in span_to_node.values() and not span_id:
            node_id = f"q-{index}-dup"
        start_id = str(params.get("start") or "")
        start_name = trace_start_name_by_id.get(start_id, "")
        primary = str(params.get("task") or start_name or start_id or params.get("q") or "")
        label_suffix = primary if primary else str(log.result_count or 0)
        trace_nodes.append({
            "id": node_id,
            "label": f"{query_type}\\n{label_suffix}",
            "kind": "query",
            "query_type": query_type,
            "query_target": label_suffix,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
        parent_node_id = span_to_node.get(parent_span_id) if parent_span_id else None
        trace_edges.append({
            "from": parent_node_id or prev_node_id,
            "to": node_id,
            "kind": "parent" if parent_node_id else "sequence",
        })

        sig = _signature(query_type, params)
        if sig in seen_signature_to_node:
            trace_edges.append({
                "from": seen_signature_to_node[sig],
                "to": node_id,
                "kind": "loop",
            })
        seen_signature_to_node[sig] = node_id
        if span_id:
            span_to_node[span_id] = node_id
        prev_node_id = node_id

        queries.append({
            "id": str(log.id),
            "query_type": query_type,
            "params": params,
            "query_target": label_suffix,
            "start_name": start_name or None,
            "result_count": int(log.result_count or 0),
            "source": log.source,
            "trace": trace_ctx,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    # ── Session execution events (chat loop / tools / sub-agents) ───────────
    execution_events: list[dict] = []
    if latest.get("source_table") == "archive":
        msg_stmt = (
            select(EngineChatMessageArchive)
            .where(EngineChatMessageArchive.session_id == uuid_lib.UUID(latest["session_id"]))
            .order_by(EngineChatMessageArchive.created_at.asc())
            .limit(800)
        )
    else:
        msg_stmt = (
            select(EngineChatMessage)
            .where(EngineChatMessage.session_id == uuid_lib.UUID(latest["session_id"]))
            .order_by(EngineChatMessage.created_at.asc())
            .limit(800)
        )

    session_messages = (await db.execute(msg_stmt)).scalars().all()
    root_agent = str(latest.get("agent_id") or "aria").strip() or "aria"
    previous_speaker_agent = root_agent

    for msg in session_messages:
        created_at_iso = msg.created_at.isoformat() if msg.created_at else None
        role = str(msg.role or "")
        msg_agent = str(msg.agent_id or "").strip()
        content_text = str(msg.content or "").strip()

        if role == "user":
            execution_events.append({
                "kind": "ask",
                "created_at": created_at_iso,
                "label": content_text[:160] if content_text else "User ask",
                "message_id": str(msg.id),
            })
            continue

        if role == "assistant":
            speaker_agent = msg_agent or previous_speaker_agent or root_agent
            if speaker_agent and previous_speaker_agent and speaker_agent != previous_speaker_agent:
                execution_events.append({
                    "kind": "agent_handoff",
                    "created_at": created_at_iso,
                    "label": f"Handoff: {previous_speaker_agent} → {speaker_agent}",
                    "from_agent": previous_speaker_agent,
                    "to_agent": speaker_agent,
                    "message_id": str(msg.id),
                })

            meta = msg.metadata_json if isinstance(msg.metadata_json, dict) else {}
            exec_trace = meta.get("exec_trace") if isinstance(meta, dict) else None
            if isinstance(exec_trace, dict):
                tools = exec_trace.get("tools") or []
                execution_events.append({
                    "kind": "llm_loop",
                    "created_at": created_at_iso,
                    "label": f"LLM loop: {int(exec_trace.get('iterations') or 0)} iterations · {len(tools)} tools",
                    "iterations": int(exec_trace.get("iterations") or 0),
                    "tool_count": len(tools),
                    "latency_ms": int(exec_trace.get("latency_ms") or 0),
                    "message_id": str(msg.id),
                })
                for tool_idx, tool in enumerate(tools):
                    if not isinstance(tool, dict):
                        continue
                    t_name = str(tool.get("name") or "tool")
                    t_ok = bool(tool.get("success", False))
                    t_dur = int(tool.get("duration_ms") or 0)
                    execution_events.append({
                        "kind": "tool_call",
                        "created_at": created_at_iso,
                        "label": f"{t_name} · {'ok' if t_ok else 'fail'} · {t_dur}ms",
                        "success": t_ok,
                        "duration_ms": t_dur,
                        "message_id": str(msg.id),
                        "order": tool_idx,
                    })

            if msg_agent and msg_agent not in {"", "main", "aria"}:
                execution_events.append({
                    "kind": "sub_agent",
                    "created_at": created_at_iso,
                    "label": f"Sub-agent response: {msg_agent}",
                    "agent_id": msg_agent,
                    "message_id": str(msg.id),
                })

            if content_text:
                execution_events.append({
                    "kind": "assistant",
                    "created_at": created_at_iso,
                    "label": f"{speaker_agent}: {content_text[:160]}",
                    "agent_id": speaker_agent,
                    "message_id": str(msg.id),
                })
            previous_speaker_agent = speaker_agent
            continue

        if role == "tool":
            tool_name = "tool"
            if isinstance(msg.tool_results, dict):
                tool_name = str(msg.tool_results.get("name") or tool_name)
            execution_events.append({
                "kind": "tool_result",
                "created_at": created_at_iso,
                "label": f"Tool result: {tool_name}",
                "message_id": str(msg.id),
            })

    execution_events.sort(key=lambda item: item.get("created_at") or "")
    sub_agents = sorted(
        {
            str(item.get("agent_id"))
            for item in execution_events
            if item.get("kind") == "sub_agent" and item.get("agent_id")
        }
    )
    execution_summary = {
        "events": len(execution_events),
        "llm_loops": sum(1 for item in execution_events if item.get("kind") == "llm_loop"),
        "tool_calls": sum(1 for item in execution_events if item.get("kind") == "tool_call"),
        "handoffs": sum(1 for item in execution_events if item.get("kind") == "agent_handoff"),
        "sub_agents": sub_agents,
    }

    return {
        "hours": safe_hours,
        "session": {
            "session_id": latest["session_id"],
            "agent_id": latest.get("agent_id"),
            "source_table": latest["source_table"],
            "session_type": latest.get("session_type"),
            "title": latest.get("title"),
            "status": latest.get("status"),
            "created_at": latest.get("created_at").isoformat() if latest.get("created_at") else None,
            "updated_at": latest.get("updated_at").isoformat() if latest.get("updated_at") else None,
            "ended_at": latest.get("ended_at").isoformat() if latest.get("ended_at") else None,
            "archived_at": latest.get("archived_at").isoformat() if latest.get("archived_at") else None,
        },
        "window": {
            "start": window_start.isoformat() if window_start else None,
            "end": window_end.isoformat() if window_end else None,
        },
        "query_count": len(queries),
        "trace_nodes": trace_nodes,
        "trace_edges": trace_edges,
        "queries": queries,
        "execution_events": execution_events,
        "execution_summary": execution_summary,
        "notes": "Trace uses exact session_id matching when trace metadata exists, otherwise falls back to inferred session time window with UI-origin noise de-prioritized.",
        "matched_by_session": matched_by_session,
        "filtered_ui_noise_count": int(filtered_ui_noise_count),
    }


@router.get("/skills/session-trace/sessions")
async def list_session_trace_candidates(
    hours: int = 24,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List latest active+archived engine sessions for Session Trace picker."""
    safe_hours = max(1, min(hours, 24 * 30))
    safe_limit = max(1, min(limit, 100))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)

    active_rows = (
        await db.execute(
            select(
                EngineChatSession.id,
                EngineChatSession.session_type,
                EngineChatSession.title,
                EngineChatSession.status,
                EngineChatSession.created_at,
                EngineChatSession.updated_at,
                EngineChatSession.ended_at,
            )
            .where(
                or_(
                    EngineChatSession.created_at >= cutoff,
                    EngineChatSession.updated_at >= cutoff,
                    EngineChatSession.ended_at.is_(None),
                )
            )
            .order_by(func.coalesce(EngineChatSession.updated_at, EngineChatSession.created_at).desc())
            .limit(300)
        )
    ).all()

    archived_rows = (
        await db.execute(
            select(
                EngineChatSessionArchive.id,
                EngineChatSessionArchive.session_type,
                EngineChatSessionArchive.title,
                EngineChatSessionArchive.status,
                EngineChatSessionArchive.created_at,
                EngineChatSessionArchive.updated_at,
                EngineChatSessionArchive.ended_at,
                EngineChatSessionArchive.archived_at,
            )
            .where(
                or_(
                    EngineChatSessionArchive.created_at >= cutoff,
                    EngineChatSessionArchive.updated_at >= cutoff,
                    EngineChatSessionArchive.archived_at >= cutoff,
                )
            )
            .order_by(
                func.coalesce(
                    EngineChatSessionArchive.updated_at,
                    EngineChatSessionArchive.archived_at,
                    EngineChatSessionArchive.created_at,
                ).desc()
            )
            .limit(300)
        )
    ).all()

    sessions: list[dict] = []
    for row in active_rows:
        sort_at = row.updated_at or row.ended_at or row.created_at
        sessions.append({
            "session_id": str(row.id),
            "source_table": "active",
            "session_type": row.session_type,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "archived_at": None,
            "sort_at": sort_at,
        })

    for row in archived_rows:
        sort_at = row.updated_at or row.ended_at or row.created_at
        sessions.append({
            "session_id": str(row.id),
            "source_table": "archive",
            "session_type": row.session_type,
            "title": row.title,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "sort_at": sort_at,
        })

    non_terminal_status = {"ended", "closed", "archived", "completed"}
    sessions.sort(
        key=lambda item: (
            item.get("source_table") == "active",
            str(item.get("status") or "").strip().lower() not in non_terminal_status,
            item.get("sort_at") or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    top = sessions[:safe_limit]

    return {
        "hours": safe_hours,
        "sessions": [
            {
                "session_id": row["session_id"],
                "source_table": row["source_table"],
                "session_type": row.get("session_type"),
                "title": row.get("title"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "ended_at": row.get("ended_at"),
                "archived_at": row.get("archived_at"),
            }
            for row in top
        ],
        "count": len(top),
        "total_candidates": len(sessions),
    }


# ── Skill Health Dashboard (DB-backed health scoring + pattern detection) ────


def _health_score(total: int, failures: int, avg_duration_ms: float) -> float:
    """
    Compute a 0-100 health score from invocation data.
    Factors: error rate (50 pts), latency (30 pts), activity (20 pts).
    """
    if total == 0:
        return 100.0  # No data = assume healthy

    error_rate = failures / total
    error_penalty = min(error_rate * 100, 50.0)  # Up to 50 pts lost

    # Latency penalty: 0 pts under 2s, scales to 30 pts at 30s+
    latency_penalty = min(max(avg_duration_ms - 2000, 0) / 28000 * 30, 30.0)

    # Activity bonus: skills with more usage get benefit of the doubt
    activity_bonus = min(total / 50, 1.0) * 20  # Full 20 pts at 50+ calls

    return round(min(100.0, max(0.0, 100.0 - error_penalty - latency_penalty + activity_bonus)), 1)


def _health_status(score: float) -> str:
    if score >= 80:
        return "healthy"
    elif score >= 50:
        return "degraded"
    return "unhealthy"


# Prevention suggestion heuristics for recurring error types
_PREVENTION_HINTS: dict[str, str] = {
    "ConnectionError": "Check network/DNS. Consider connection pooling or retry backoff.",
    "TimeoutError": "Increase timeout or add circuit breaker. Check if upstream service is overloaded.",
    "HTTPStatusError": "Review API credentials and rate limits. Add response-code-specific retry logic.",
    "JSONDecodeError": "Upstream returned non-JSON. Add response content-type validation.",
    "OperationalError": "Database connection issue. Verify connection pool health and max connections.",
    "RateLimitError": "Back off on this skill. Consider request throttling or queue-based execution.",
    "AuthenticationError": "API key expired or invalid. Rotate credentials.",
    "ValueError": "Input validation gap. Add stricter param checking before execution.",
}


@router.get("/skills/health/dashboard")
async def skill_health_dashboard(
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
):
    """
    Skill Health Dashboard — health scores, recurring failure patterns,
    and prevention suggestions.  DB-backed, no in-memory dependency.
    """
    safe_hours = max(1, min(hours, 24 * 30))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)

    # ── Per-skill health scoring ─────────────────────────────────────────
    skill_rows = (
        await db.execute(
            select(
                SkillInvocation.skill_name,
                func.count().label("total"),
                func.sum(case((SkillInvocation.success == True, 1), else_=0)).label("successes"),
                func.sum(case((SkillInvocation.success == False, 1), else_=0)).label("failures"),
                func.avg(SkillInvocation.duration_ms).label("avg_ms"),
                func.max(SkillInvocation.duration_ms).label("max_ms"),
                func.min(SkillInvocation.duration_ms).label("min_ms"),
                func.coalesce(func.sum(SkillInvocation.tokens_used), 0).label("tokens"),
                func.max(SkillInvocation.created_at).label("last_seen"),
            )
            .where(SkillInvocation.created_at >= cutoff)
            .group_by(SkillInvocation.skill_name)
            .order_by(func.count().desc())
        )
    ).all()

    skills = []
    total_invocations = 0
    total_failures = 0

    # Lookup layer from skill_status table for enrichment
    status_rows = (await db.execute(select(SkillStatusRecord))).scalars().all()
    layer_by_skill = {r.skill_name: r.layer for r in status_rows}

    for row in skill_rows:
        total = int(row.total or 0)
        failures = int(row.failures or 0)
        avg_ms = float(row.avg_ms or 0)
        score = _health_score(total, failures, avg_ms)
        total_invocations += total
        total_failures += failures
        skills.append({
            "skill_name": row.skill_name,
            "layer": layer_by_skill.get(row.skill_name),
            "health_score": score,
            "status": _health_status(score),
            "total_calls": total,
            "successes": int(row.successes or 0),
            "failures": failures,
            "error_rate": round((failures / max(total, 1)) * 100, 1),
            "avg_duration_ms": round(avg_ms, 1),
            "max_duration_ms": int(row.max_ms or 0),
            "min_duration_ms": int(row.min_ms or 0),
            "total_tokens": int(row.tokens or 0),
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        })

    overall_score = (
        round(sum(s["health_score"] for s in skills) / len(skills), 1)
        if skills else 100.0
    )

    # ── Recurring failure patterns (GROUP BY error_type) ─────────────────
    pattern_rows = (
        await db.execute(
            select(
                SkillInvocation.skill_name,
                SkillInvocation.error_type,
                func.count().label("count"),
                func.min(SkillInvocation.created_at).label("first_seen"),
                func.max(SkillInvocation.created_at).label("last_seen"),
            )
            .where(SkillInvocation.created_at >= cutoff)
            .where(SkillInvocation.success == False)
            .where(SkillInvocation.error_type.isnot(None))
            .group_by(SkillInvocation.skill_name, SkillInvocation.error_type)
            .having(func.count() >= 2)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()

    patterns = []
    for row in pattern_rows:
        error_type = row.error_type or "unknown"
        suggestion = _PREVENTION_HINTS.get(
            error_type,
            f"Recurring {error_type} in {row.skill_name} ({row.count}x). "
            "Investigate logs and consider adding targeted error handling.",
        )
        patterns.append({
            "skill_name": row.skill_name,
            "error_type": error_type,
            "count": int(row.count),
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "suggestion": suggestion,
        })

    # ── Unhealthy + slow skill shortlists ────────────────────────────────
    unhealthy = [s for s in skills if s["status"] == "unhealthy"]
    degraded = [s for s in skills if s["status"] == "degraded"]
    slow = [s for s in skills if s["avg_duration_ms"] >= 5000]

    # ── Per-layer health aggregates ──────────────────────────────────────
    layer_stats: dict[str, dict] = {}
    for s in skills:
        lyr = s.get("layer") or "unknown"
        if lyr not in layer_stats:
            layer_stats[lyr] = {"count": 0, "total_calls": 0, "total_failures": 0, "score_sum": 0.0}
        layer_stats[lyr]["count"] += 1
        layer_stats[lyr]["total_calls"] += s["total_calls"]
        layer_stats[lyr]["total_failures"] += s["failures"]
        layer_stats[lyr]["score_sum"] += s["health_score"]
    for lyr, v in layer_stats.items():
        v["avg_health"] = round(v["score_sum"] / max(v["count"], 1), 1)
        del v["score_sum"]

    return {
        "hours": safe_hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "health_score": overall_score,
            "status": _health_status(overall_score),
            "total_invocations": total_invocations,
            "total_failures": total_failures,
            "skills_monitored": len(skills),
            "unhealthy_count": len(unhealthy),
            "degraded_count": len(degraded),
            "slow_count": len(slow),
        },
        "layer_stats": layer_stats,
        "skills": skills,
        "patterns": patterns,
        "unhealthy_skills": unhealthy,
        "degraded_skills": degraded,
        "slow_skills": slow,
    }
