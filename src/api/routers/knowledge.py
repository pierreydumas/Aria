"""
Knowledge graph endpoints — entities, relations, traversal, search, query logging.
"""

import json as json_lib
import logging
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from db.models import KnowledgeEntity, KnowledgeRelation, KnowledgeQueryLog, SkillGraphEntity, SkillGraphRelation
from deps import get_db

router = APIRouter(tags=["Knowledge Graph"])
logger = logging.getLogger("aria.api.knowledge")


def _is_test_kg_payload(*values: str) -> bool:
    markers = (
        "[test]",
        "pytest",
        "goal_test",
        "skill_test",
        "test_entry",
        "live test goal",
        "test goal",
        "testing skill functionality",
        "creative pulse ingestion test",
        "creative pulse full visualization test",
        "pulse-exp-",
        "live test post",
        "moltbook test",
        "abc123",
        "post 42",
        "testentity_",
        "searchable_",
        "trav_",
        "rel_a_",
        "rel_b_",
        "pytest-entity",
        "rel-src",
        "rel-dst",
    )
    text_blob = " ".join((v or "") for v in values).lower()
    if any(marker in text_blob for marker in markers):
        return True

    if any(prefix in text_blob for prefix in ("test-", "test_", "goal-test", "goal_test", "skill-test", "skill_test")):
        return True

    # Token-aware fallback for explicit test tagging without matching unrelated words.
    return " test " in f" {text_blob} "


# ── Pydantic schemas for input validation ─────────────────────────────────────

class EntityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    type: str = Field(..., min_length=1, max_length=100)
    properties: dict = Field(default_factory=dict)

class RelationCreate(BaseModel):
    from_entity: str = Field(..., min_length=1, max_length=500)
    to_entity: str = Field(..., min_length=1, max_length=500)
    relation_type: str = Field(..., min_length=1, max_length=100)
    properties: dict = Field(default_factory=dict)


async def _resolve_entity_id(db: AsyncSession, ref: str) -> uuid.UUID:
    """Resolve an entity reference (UUID string or name) to its database UUID.

    Resolution order:
      1. Valid UUID that exists in DB → return it
      2. Exact name match → return id
      3. Case-insensitive name match → return id
      4. Auto-create entity (infer type from 'type:name' format or default to 'concept')
    """
    # 1. Try as UUID
    try:
        entity_uuid = uuid.UUID(ref)
        result = await db.execute(
            select(KnowledgeEntity.id).where(KnowledgeEntity.id == entity_uuid)
        )
        if result.scalar_one_or_none() is not None:
            return entity_uuid
    except ValueError:
        pass

    # 2. Exact name match
    result = await db.execute(
        select(KnowledgeEntity.id).where(KnowledgeEntity.name == ref).limit(1)
    )
    eid = result.scalar_one_or_none()
    if eid is not None:
        return eid

    # 3. Case-insensitive name match
    result = await db.execute(
        select(KnowledgeEntity.id).where(
            func.lower(KnowledgeEntity.name) == ref.lower()
        ).limit(1)
    )
    eid = result.scalar_one_or_none()
    if eid is not None:
        return eid

    # 4. Auto-create: infer type from "type:name" format, else "concept"
    if ":" in ref and len(ref.split(":", 1)[0]) < 30:
        parts = ref.split(":", 1)
        entity_type = parts[0].strip()
        entity_name = parts[1].strip().replace("_", " ").title()
    else:
        entity_type = "concept"
        entity_name = ref

    new_id = uuid.uuid4()
    entity = KnowledgeEntity(
        id=new_id,
        name=entity_name,
        type=entity_type,
        properties={"auto_created": True, "original_ref": ref},
    )
    db.add(entity)
    try:
        await db.flush()
    except Exception as e:
        logger.warning("Knowledge entity creation failed: %s", e)
        await db.rollback()
        raise HTTPException(
            status_code=404,
            detail=f"Entity not found and could not be auto-created: '{ref}'",
        )
    return new_id


# ── S4-05: Query logging helper ──────────────────────────────────────────────

def _extract_trace_context(request: Request | None) -> dict:
    if request is None:
        return {}

    headers = request.headers
    session_id = (headers.get("x-aria-session-id") or request.query_params.get("session_id") or "").strip()
    trace_id = (headers.get("x-aria-trace-id") or request.query_params.get("trace_id") or "").strip()
    span_id = (headers.get("x-aria-span-id") or "").strip()
    parent_span_id = (headers.get("x-aria-parent-span-id") or "").strip()
    origin = (headers.get("x-aria-trace-origin") or "").strip()

    if not span_id:
        span_id = str(uuid.uuid4())

    trace = {
        "session_id": session_id or None,
        "trace_id": trace_id or None,
        "span_id": span_id,
        "parent_span_id": parent_span_id or None,
        "origin": origin or None,
    }
    return {k: v for k, v in trace.items() if v not in (None, "")}


async def _log_query(
    db: AsyncSession,
    query_type: str,
    params: dict,
    result_count: int,
    source: str = "api",
    request: Request | None = None,
):
    """Log a knowledge graph query for analytics."""
    try:
        merged_params = dict(params or {})
        trace_context = _extract_trace_context(request)
        if trace_context:
            existing_trace = merged_params.get("__trace")
            if isinstance(existing_trace, dict):
                merged_params["__trace"] = {**existing_trace, **trace_context}
            else:
                merged_params["__trace"] = trace_context

        log = KnowledgeQueryLog(
            id=uuid.uuid4(),
            query_type=query_type,
            params=merged_params,
            result_count=result_count,
            source=source,
        )
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning("Knowledge relation creation failed: %s", e)
        await db.rollback()  # Restore session to usable state


# ── Skill Graph (dedicated tables) ───────────────────────────────────────────

@router.get("/skill-graph")
async def get_skill_graph(
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return all skill graph entities + relations (from dedicated tables)."""
    entities = (await db.execute(
        select(SkillGraphEntity).order_by(SkillGraphEntity.name)
        .limit(limit).offset(offset)
    )).scalars().all()

    from sqlalchemy.orm import aliased
    E1 = aliased(SkillGraphEntity)
    E2 = aliased(SkillGraphEntity)
    relations_result = await db.execute(
        select(
            SkillGraphRelation,
            E1.name.label("from_name"), E1.type.label("from_type"),
            E2.name.label("to_name"), E2.type.label("to_type"),
        )
        .join(E1, SkillGraphRelation.from_entity == E1.id)
        .join(E2, SkillGraphRelation.to_entity == E2.id)
        .limit(limit).offset(offset)
    )
    relation_rows = relations_result.all()

    return {
        "entities": [e.to_dict() for e in entities],
        "relations": [
            {
                **r[0].to_dict(),
                "from_name": r[1], "from_type": r[2],
                "to_name": r[3], "to_type": r[4],
            }
            for r in relation_rows
        ],
        "stats": {
            "entity_count": len(entities),
            "relation_count": len(relation_rows),
        },
    }


@router.post("/knowledge-graph/sync-skills")
async def sync_skills():
    """Trigger skill graph sync (ORM-based, idempotent)."""
    from graph_sync import sync_skill_graph
    try:
        stats = await sync_skill_graph()
    except Exception as exc:
        logger.warning("Knowledge sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}")
    return {"status": "ok", "stats": stats}


@router.get("/knowledge-graph")
async def get_knowledge_graph(
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    entities = (await db.execute(
        select(KnowledgeEntity).order_by(KnowledgeEntity.created_at.desc())
        .limit(limit).offset(offset)
    )).scalars().all()

    # Relations with entity names via subquery / manual join
    from sqlalchemy.orm import aliased
    E1 = aliased(KnowledgeEntity)
    E2 = aliased(KnowledgeEntity)
    relations_result = await db.execute(
        select(
            KnowledgeRelation,
            E1.name.label("from_name"), E1.type.label("from_type"),
            E2.name.label("to_name"), E2.type.label("to_type"),
        )
        .join(E1, KnowledgeRelation.from_entity == E1.id)
        .join(E2, KnowledgeRelation.to_entity == E2.id)
        .order_by(KnowledgeRelation.created_at.desc())
        .limit(limit).offset(offset)
    )
    relation_rows = relations_result.all()

    return {
        "entities": [e.to_dict() for e in entities],
        "relations": [
            {
                **r[0].to_dict(),
                "from_name": r[1], "from_type": r[2],
                "to_name": r[3], "to_type": r[4],
            }
            for r in relation_rows
        ],
        "stats": {
            "entity_count": len(entities),
            "relation_count": len(relation_rows),
        },
    }


@router.get("/knowledge-graph/entities")
async def get_knowledge_entities(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    type: str = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(KnowledgeEntity).order_by(KnowledgeEntity.created_at.desc()).limit(limit).offset(offset)
    if type:
        stmt = stmt.where(KnowledgeEntity.type == type)
    result = await db.execute(stmt)
    return {"entities": [e.to_dict() for e in result.scalars().all()]}


@router.get("/knowledge-graph/relations")
async def get_knowledge_relations(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import aliased
    E1 = aliased(KnowledgeEntity)
    E2 = aliased(KnowledgeEntity)
    result = await db.execute(
        select(
            KnowledgeRelation,
            E1.name.label("from_name"), E1.type.label("from_type"),
            E2.name.label("to_name"), E2.type.label("to_type"),
        )
        .join(E1, KnowledgeRelation.from_entity == E1.id)
        .join(E2, KnowledgeRelation.to_entity == E2.id)
        .order_by(KnowledgeRelation.created_at.desc())
        .limit(limit)
    )
    return {
        "relations": [
            {
                **r[0].to_dict(),
                "from_name": r[1], "from_type": r[2],
                "to_name": r[3], "to_type": r[4],
            }
            for r in result.all()
        ]
    }


@router.post("/knowledge-graph/entities")
async def create_knowledge_entity(body: EntityCreate, db: AsyncSession = Depends(get_db)):
    if _is_test_kg_payload(body.name, body.type, json_lib.dumps(body.properties or {}, default=str)):
        return {"created": False, "skipped": True, "reason": "test_or_noise_payload"}

    entity = KnowledgeEntity(
        id=uuid.uuid4(),
        name=body.name,
        type=body.type,
        properties=body.properties,
    )
    db.add(entity)
    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Entity merge conflict: %s", exc)
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Entity creation failed: {exc}")
    return {"id": str(entity.id), "created": True}


@router.post("/knowledge-graph/relations")
async def create_knowledge_relation(body: RelationCreate, db: AsyncSession = Depends(get_db)):
    if _is_test_kg_payload(body.relation_type, json_lib.dumps(body.properties or {}, default=str)):
        return {"created": False, "skipped": True, "reason": "test_or_noise_payload"}

    from_uuid = await _resolve_entity_id(db, body.from_entity)
    to_uuid = await _resolve_entity_id(db, body.to_entity)

    relation = KnowledgeRelation(
        id=uuid.uuid4(),
        from_entity=from_uuid,
        to_entity=to_uuid,
        relation_type=body.relation_type,
        properties=body.properties,
    )
    db.add(relation)
    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Relation merge conflict: %s", exc)
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Relation creation failed: {exc}")
    return {"id": str(relation.id), "created": True}


# ── S4-01: Delete auto-generated graph data ──────────────────────────────────

@router.delete("/knowledge-graph/auto-generated")
async def delete_auto_generated(db: AsyncSession = Depends(get_db)):
    """Delete all skill graph data (separate tables, safe from organic knowledge)."""
    rel_result = await db.execute(delete(SkillGraphRelation))
    ent_result = await db.execute(delete(SkillGraphEntity))
    await db.commit()
    return {"deleted_entities": ent_result.rowcount, "deleted_relations": rel_result.rowcount, "status": "ok"}


# ── S4-02: Graph traversal (BFS) ─────────────────────────────────────────────

@router.get("/knowledge-graph/traverse")
async def graph_traverse(
    request: Request,
    start: str = Query(..., description="Starting entity ID or name"),
    relation_type: str | None = Query(None, description="Filter by relation type"),
    max_depth: int = Query(3, ge=1, le=10),
    direction: str = Query("outgoing", regex="^(outgoing|incoming|both)$"),
    db: AsyncSession = Depends(get_db),
):
    """BFS traversal from a starting entity in the skill graph."""
    # Resolve start entity by ID or name
    start_entity = None
    try:
        start_uuid = uuid.UUID(start)
        result = await db.execute(select(SkillGraphEntity).where(SkillGraphEntity.id == start_uuid))
        start_entity = result.scalar_one_or_none()
    except ValueError:
        pass
    if not start_entity:
        result = await db.execute(select(SkillGraphEntity).where(SkillGraphEntity.name == start))
        start_entity = result.scalar_one_or_none()
    if not start_entity:
        return {"error": f"Entity not found: {start}", "nodes": [], "edges": []}

    # BFS – batch by level to avoid N+1 queries (S-163)
    visited: set[str] = set()
    current_level: list[uuid.UUID] = [start_entity.id]
    visited.add(str(start_entity.id))

    nodes: list[dict] = [start_entity.to_dict()]
    edges: list[dict] = []

    for _depth in range(max_depth):
        if not current_level:
            break

        # Batch-fetch all relations for every node at this BFS level
        all_relations = []
        if direction in ("outgoing", "both"):
            stmt = select(SkillGraphRelation).where(SkillGraphRelation.from_entity.in_(current_level))
            if relation_type:
                stmt = stmt.where(SkillGraphRelation.relation_type == relation_type)
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                all_relations.append(("outgoing", rel))
        if direction in ("incoming", "both"):
            stmt = select(SkillGraphRelation).where(SkillGraphRelation.to_entity.in_(current_level))
            if relation_type:
                stmt = stmt.where(SkillGraphRelation.relation_type == relation_type)
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                all_relations.append(("incoming", rel))

        # Collect unvisited neighbour IDs
        next_level_ids: list[uuid.UUID] = []
        for dir_label, rel in all_relations:
            edges.append(rel.to_dict())
            next_id = rel.to_entity if dir_label == "outgoing" else rel.from_entity
            next_id_str = str(next_id)
            if next_id_str not in visited:
                visited.add(next_id_str)
                next_level_ids.append(next_id)

        # Batch-fetch all neighbour entities in a single query
        if next_level_ids:
            result = await db.execute(
                select(SkillGraphEntity).where(SkillGraphEntity.id.in_(next_level_ids))
            )
            for entity in result.scalars().all():
                nodes.append(entity.to_dict())

        current_level = next_level_ids

    await _log_query(
        db,
        "traverse",
        {"start": start, "relation_type": relation_type, "max_depth": max_depth, "direction": direction},
        len(nodes),
        request=request,
    )
    return {"nodes": nodes, "edges": edges, "traversal_depth": max_depth, "total_nodes": len(nodes), "total_edges": len(edges)}


# ── S4-02: Graph search (ILIKE) ──────────────────────────────────────────────

@router.get("/knowledge-graph/search")
async def graph_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """ILIKE text search for entities in the skill graph."""
    pattern = f"%{q}%"
    stmt = select(SkillGraphEntity).where(
        or_(
            SkillGraphEntity.name.ilike(pattern),
            SkillGraphEntity.properties["description"].astext.ilike(pattern),
        )
    )
    if entity_type:
        stmt = stmt.where(SkillGraphEntity.type == entity_type)
    stmt = stmt.order_by(SkillGraphEntity.name).limit(limit)

    result = await db.execute(stmt)
    entities = [e.to_dict() for e in result.scalars().all()]

    await _log_query(db, "search", {"q": q, "entity_type": entity_type}, len(entities), request=request)
    return {"results": entities, "query": q, "count": len(entities)}


# ── S4-02: Skill-for-task discovery ──────────────────────────────────────────

@router.get("/knowledge-graph/skill-for-task")
async def find_skill_for_task(
    request: Request,
    task: str = Query(..., min_length=1, description="Task description"),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Find the best skill for a given task from the skill graph."""
    pattern = f"%{task}%"

    # Search skills by name/description
    skill_stmt = select(SkillGraphEntity).where(
        SkillGraphEntity.type == "skill",
        or_(
            SkillGraphEntity.name.ilike(pattern),
            SkillGraphEntity.properties["description"].astext.ilike(pattern),
        ),
    ).limit(limit)
    skill_result = await db.execute(skill_stmt)
    skill_matches = skill_result.scalars().all()

    # Search tools by name/description, then trace back to skill
    tool_stmt = select(SkillGraphEntity).where(
        SkillGraphEntity.type == "tool",
        or_(
            SkillGraphEntity.name.ilike(pattern),
            SkillGraphEntity.properties["description"].astext.ilike(pattern),
        ),
    ).limit(20)
    tool_result = await db.execute(tool_stmt)
    tool_matches = tool_result.scalars().all()

    # For each matching tool, find the parent skill via 'provides' relation
    tool_skill_ids: set[str] = set()
    for tool in tool_matches:
        rel_result = await db.execute(
            select(SkillGraphRelation).where(
                SkillGraphRelation.to_entity == tool.id,
                SkillGraphRelation.relation_type == "provides",
            )
        )
        for rel in rel_result.scalars().all():
            tool_skill_ids.add(str(rel.from_entity))

    # Fetch those parent skills
    indirect_skills = []
    if tool_skill_ids:
        indirect_result = await db.execute(
            select(SkillGraphEntity).where(
                SkillGraphEntity.id.in_([uuid.UUID(sid) for sid in tool_skill_ids])
            )
        )
        indirect_skills = indirect_result.scalars().all()

    # Merge and deduplicate
    seen: set[str] = set()
    candidates: list[dict] = []
    for skill in skill_matches:
        sid = str(skill.id)
        if sid not in seen:
            seen.add(sid)
            candidates.append({
                **skill.to_dict(),
                "match_type": "direct",
                "relevance": "high",
            })
    for skill in indirect_skills:
        sid = str(skill.id)
        if sid not in seen:
            seen.add(sid)
            candidates.append({
                **skill.to_dict(),
                "match_type": "via_tool",
                "relevance": "medium",
            })

    result_data = {
        "task": task,
        "candidates": candidates[:limit],
        "count": len(candidates[:limit]),
        "tools_searched": len(tool_matches),
    }
    await _log_query(db, "skill_for_task", {"task": task}, len(candidates[:limit]), request=request)
    return result_data


# ── S4-05: Query log endpoint ────────────────────────────────────────────────

@router.get("/knowledge-graph/query-log")
async def get_query_log(
    limit: int = Query(50, ge=1, le=200),
    query_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get recent knowledge graph query log entries."""
    stmt = select(KnowledgeQueryLog).order_by(KnowledgeQueryLog.created_at.desc()).limit(limit)
    if query_type:
        stmt = stmt.where(KnowledgeQueryLog.query_type == query_type)
    result = await db.execute(stmt)
    logs = [log.to_dict() for log in result.scalars().all()]
    return {"logs": logs, "count": len(logs)}


# ── Knowledge Graph traversal (organic knowledge) ────────────────────────────

@router.get("/knowledge-graph/kg-traverse")
async def kg_traverse(
    request: Request,
    start: str = Query(..., description="Starting entity UUID, name, or 'type:name' ref"),
    relation_type: str | None = Query(None, description="Filter by relation type"),
    max_depth: int = Query(2, ge=1, le=5),
    direction: str = Query("both", regex="^(outgoing|incoming|both)$"),
    db: AsyncSession = Depends(get_db),
):
    """BFS traversal on the organic knowledge graph (knowledge_entities / knowledge_relations)."""
    # Resolve start entity
    start_entity = None
    try:
        start_uuid = uuid.UUID(start)
        result = await db.execute(select(KnowledgeEntity).where(KnowledgeEntity.id == start_uuid))
        start_entity = result.scalar_one_or_none()
    except ValueError:
        pass
    if not start_entity:
        result = await db.execute(select(KnowledgeEntity).where(KnowledgeEntity.name == start).limit(1))
        start_entity = result.scalar_one_or_none()
    if not start_entity:
        result = await db.execute(
            select(KnowledgeEntity).where(func.lower(KnowledgeEntity.name) == start.lower()).limit(1)
        )
        start_entity = result.scalar_one_or_none()
    if not start_entity:
        return {"error": f"Entity not found: {start}", "nodes": [], "edges": []}

    # BFS – batch by level to avoid N+1 queries (S-163)
    visited: set[str] = set()
    current_level: list[uuid.UUID] = [start_entity.id]
    visited.add(str(start_entity.id))

    # Entity-name lookup used for edge annotation (avoids lazy-load N+1)
    entity_names: dict[str, str] = {str(start_entity.id): start_entity.name}

    nodes: list[dict] = [start_entity.to_dict()]
    edges: list[dict] = []

    for _depth in range(max_depth):
        if not current_level:
            break

        # Batch-fetch all relations for this BFS level
        all_relations = []
        if direction in ("outgoing", "both"):
            stmt = select(KnowledgeRelation).where(KnowledgeRelation.from_entity.in_(current_level))
            if relation_type:
                stmt = stmt.where(KnowledgeRelation.relation_type == relation_type)
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                all_relations.append(("outgoing", rel))
        if direction in ("incoming", "both"):
            stmt = select(KnowledgeRelation).where(KnowledgeRelation.to_entity.in_(current_level))
            if relation_type:
                stmt = stmt.where(KnowledgeRelation.relation_type == relation_type)
            result = await db.execute(stmt)
            for rel in result.scalars().all():
                all_relations.append(("incoming", rel))

        # Collect unvisited neighbour IDs and prepare edge data
        next_level_ids: list[uuid.UUID] = []
        pending_edges = []
        for dir_label, rel in all_relations:
            edge_data = rel.to_dict()
            pending_edges.append((edge_data, rel.from_entity, rel.to_entity))
            next_id = rel.to_entity if dir_label == "outgoing" else rel.from_entity
            next_id_str = str(next_id)
            if next_id_str not in visited:
                visited.add(next_id_str)
                next_level_ids.append(next_id)

        # Batch-fetch all neighbour entities in a single query
        if next_level_ids:
            result = await db.execute(
                select(KnowledgeEntity).where(KnowledgeEntity.id.in_(next_level_ids))
            )
            for entity in result.scalars().all():
                nodes.append(entity.to_dict())
                entity_names[str(entity.id)] = entity.name

        # Annotate edges with entity names (uses cache, no extra queries)
        for edge_data, from_id, to_id in pending_edges:
            from_name = entity_names.get(str(from_id))
            to_name = entity_names.get(str(to_id))
            if from_name:
                edge_data["from_name"] = from_name
            if to_name:
                edge_data["to_name"] = to_name
            edges.append(edge_data)

        current_level = next_level_ids

    await _log_query(
        db, "kg_traverse",
        {"start": start, "relation_type": relation_type, "max_depth": max_depth, "direction": direction},
        len(nodes),
        request=request,
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "traversal_depth": max_depth,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }


# ── Knowledge Graph entity search ────────────────────────────────────────────

@router.get("/knowledge-graph/kg-search")
async def kg_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query (name substring)"),
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """ILIKE text search for entities in the organic knowledge graph."""
    pattern = f"%{q}%"
    stmt = select(KnowledgeEntity).where(
        or_(
            KnowledgeEntity.name.ilike(pattern),
            KnowledgeEntity.properties["description"].astext.ilike(pattern),
        )
    )
    if entity_type:
        stmt = stmt.where(KnowledgeEntity.type == entity_type)
    stmt = stmt.order_by(KnowledgeEntity.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    entities = [e.to_dict() for e in result.scalars().all()]

    await _log_query(db, "kg_search", {"q": q, "entity_type": entity_type}, len(entities), request=request)
    return {"results": entities, "query": q, "count": len(entities)}

