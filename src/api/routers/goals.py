"""
Goals + hourly goals endpoints.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Goal, HourlyGoal
from deps import get_db
from pagination import paginate_query, build_paginated_response
from schemas.requests import CreateGoal, UpdateGoal, MoveGoal, CreateHourlyGoal, UpdateHourlyGoal

router = APIRouter(tags=["Goals"])
logger = logging.getLogger("aria.api.goals")


def _is_noisy_goal_payload(goal_id: str | None, title: str | None, description: str | None) -> bool:
    text = " ".join([goal_id or "", title or "", description or ""]).lower().strip()
    noisy_markers = [
        "live test goal",
        "test goal",
        "testing skill functionality",
        "creative pulse ingestion test",
        "fetch test",
        "update test",
        "goal_test",
        "skill_test",
        "test_entry",
        "creative pulse full visualization test",
        "pulse-exp-",
        "live test post",
        "moltbook test",
        "abc123",
        "post 42",
        "patchable",
        "dry run",
    ]
    if any(marker in text for marker in noisy_markers):
        return True

    goal_id_s = (goal_id or "").lower().strip()
    if (
        goal_id_s.startswith("test-")
        or goal_id_s.startswith("test_")
        or goal_id_s.startswith("goal-test")
        or goal_id_s.startswith("goal_test")
        or goal_id_s.startswith("skill-test")
        or goal_id_s.startswith("skill_test")
    ):
        return True

    return False


# ── Goals ────────────────────────────────────────────────────────────────────

@router.get("/goals")
async def list_goals(
    page: int = 1,
    limit: int = 25,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    base = select(Goal).order_by(Goal.priority.desc(), Goal.created_at.desc())
    if status:
        normalized = status.strip().lower()
        status_aliases: dict[str, tuple[str, ...]] = {
            "active": ("active", "in_progress"),
            "in_progress": ("active", "in_progress"),
            "on_hold": ("on_hold", "paused"),
            "paused": ("on_hold", "paused"),
        }
        allowed_statuses = status_aliases.get(normalized, (normalized,))
        base = base.where(Goal.status.in_(allowed_statuses))

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    result = await db.execute(stmt)
    items = [g.to_dict() for g in result.scalars().all()]

    return build_paginated_response(items, total, page, limit)


@router.post("/goals")
async def create_goal(body: CreateGoal, db: AsyncSession = Depends(get_db)):
    new_id = uuid.uuid4()
    goal_id = body.goal_id or f"goal-{str(new_id)[:8]}"
    title = body.title
    description = body.description

    if _is_noisy_goal_payload(goal_id, title, description):
        return {"created": False, "skipped": True, "reason": "test_or_patch_noise"}

    goal = Goal(
        id=new_id,
        goal_id=goal_id,
        title=title,
        description=description,
        status=body.status,
        progress=body.progress,
        priority=body.priority,
        due_date=body.due_date or body.target_date,
        sprint=body.sprint,
        board_column=body.board_column,
        position=body.position,
        assigned_to=body.assigned_to,
        tags=body.tags,
    )
    db.add(goal)
    await db.commit()
    return {"id": str(goal.id), "goal_id": goal.goal_id, "created": True}


# ── Sprint Board (S3-02) ────────────────────────────────────────────────────

@router.get("/goals/board")
async def goal_board(
    sprint: str = "current",
    db: AsyncSession = Depends(get_db),
):
    """Get goals organized by board column for Kanban view."""
    from datetime import timedelta, timezone as tz

    # If "current" sprint, get the latest sprint name or default to "sprint-1"
    if sprint == "current":
        latest = await db.execute(
            select(Goal.sprint).where(Goal.sprint != "backlog")
            .order_by(Goal.created_at.desc()).limit(1)
        )
        sprint = latest.scalar() or "sprint-1"

    from sqlalchemy import or_

    # ── Auto-reconcile status → board_column ─────────────────────────
    # Goals created by cron/agents set status but never update board_column.
    status_to_column = {
        # NOTE: 'in_progress' is intentionally NOT here — users/agents place
        # in_progress goals across columns manually (backlog/todo/doing).
        "completed": "done",
        "paused": "on_hold",
        "cancelled": "done",
    }
    for status_val, col_val in status_to_column.items():
        await db.execute(
            update(Goal)
            .where(Goal.status == status_val, Goal.board_column != col_val)
            .values(board_column=col_val)
        )
    # pending goals stuck in backlog are fine; pending+backlog = correct

    # ── Auto-archive: completed/cancelled > 24h → clear from board ───
    archive_cutoff = datetime.utcnow() - timedelta(hours=24)
    await db.execute(
        update(Goal)
        .where(
            Goal.status.in_(["completed", "cancelled"]),
            Goal.completed_at.isnot(None),
            Goal.completed_at < archive_cutoff,
            Goal.board_column != "archived",
        )
        .values(board_column="archived")
    )

    await db.commit()

    # Fetch all goals for this sprint + backlog + NULL sprint (exclude archived)
    stmt = select(Goal).where(
        or_(
            Goal.sprint.in_([sprint, "backlog"]),
            Goal.sprint.is_(None),
        ),
        Goal.board_column != "archived",
    ).order_by(Goal.position.asc(), Goal.priority.asc())
    result = await db.execute(stmt)
    goals = result.scalars().all()

    columns = {
        "backlog": [],
        "todo": [],
        "doing": [],
        "on_hold": [],
        "done": [],
    }

    for g in goals:
        d = g.to_dict()
        col = g.board_column or "backlog"
        if col in columns:
            columns[col].append(d)

    return {
        "sprint": sprint,
        "columns": columns,
        "counts": {k: len(v) for k, v in columns.items()},
        "total": sum(len(v) for v in columns.values()),
    }


@router.get("/goals/archive")
async def goal_archive(
    page: int = 1,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """Get completed and cancelled goals for archive view."""
    from sqlalchemy import or_
    base = select(Goal).where(
        or_(
            Goal.status.in_(["completed", "cancelled"]),
            Goal.board_column == "archived",
        )
    ).order_by(Goal.completed_at.desc().nulls_last())

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt, _ = paginate_query(base, page, limit)
    result = await db.execute(stmt)
    items = [g.to_dict() for g in result.scalars().all()]

    return build_paginated_response(items, total, page, limit)


@router.get("/goals/sprint-summary")
async def goal_sprint_summary(
    sprint: str = "current",
    db: AsyncSession = Depends(get_db),
):
    """Lightweight sprint summary — optimized for Aria's token budget (~200 tokens)."""
    stmt = select(
        Goal.status,
        func.count(Goal.id).label("count"),
    ).group_by(Goal.status)

    result = await db.execute(stmt)
    status_counts = {row.status: row.count for row in result.all()}

    active = await db.execute(
        select(Goal.goal_id, Goal.title, Goal.priority, Goal.progress)
        .where(Goal.status == "active")
        .order_by(Goal.priority.asc(), Goal.progress.desc())
        .limit(3)
    )
    top_goals = [
        {"id": r.goal_id, "title": r.title, "priority": r.priority, "progress": float(r.progress or 0)}
        for r in active.all()
    ]

    return {
        "sprint": sprint,
        "status_counts": status_counts,
        "total": sum(status_counts.values()),
        "top_active": top_goals,
        "summary": f"{status_counts.get('active', 0)} active, {status_counts.get('pending', 0)} pending, {status_counts.get('completed', 0)} done",
    }


@router.get("/goals/history")
async def goal_history(
    days: int = 14,
    db: AsyncSession = Depends(get_db),
):
    """Get goal status distribution by day for stacked chart."""
    from sqlalchemy import cast, Date
    from datetime import timedelta, timezone as tz

    since = datetime.now(tz.utc) - timedelta(days=days)

    stmt = select(
        cast(Goal.created_at, Date).label("day"),
        Goal.status,
        func.count(Goal.id).label("count"),
    ).where(
        Goal.created_at >= since
    ).group_by("day", Goal.status).order_by("day")

    result = await db.execute(stmt)
    rows = result.all()

    data = {}
    for row in rows:
        day = str(row.day)
        if day not in data:
            data[day] = {"pending": 0, "active": 0, "completed": 0, "paused": 0, "cancelled": 0}
        data[day][row.status] = row.count

    return {
        "days": days,
        "data": data,
        "labels": sorted(data.keys()),
    }


# ── Parameterized goal routes (catch-all MUST come after named routes) ───────

@router.get("/goals/{goal_id}")
async def get_goal(goal_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch a single goal by UUID or goal_id string."""
    try:
        uid = uuid.UUID(goal_id)
        result = await db.execute(select(Goal).where(Goal.id == uid))
    except ValueError:
        result = await db.execute(select(Goal).where(Goal.goal_id == goal_id))
    goal = result.scalars().first()
    if not goal:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id!r} not found")
    return goal.to_dict()


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(goal_id)
        result = await db.execute(delete(Goal).where(Goal.id == uid))
    except ValueError:
        result = await db.execute(delete(Goal).where(Goal.goal_id == goal_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    await db.commit()
    return {"deleted": True}


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str, body: UpdateGoal, db: AsyncSession = Depends(get_db)
):
    data = body.model_dump(exclude_none=True)
    next_title = data.get("title")
    next_description = data.get("description")
    if _is_noisy_goal_payload(goal_id, next_title, next_description):
        return {"updated": False, "skipped": True, "reason": "test_or_patch_noise"}

    values: dict = {}
    if body.status is not None:
        values["status"] = body.status
        if body.status == "completed":
            from sqlalchemy import text
            values["completed_at"] = text("NOW()")
        # Auto-sync board_column when status changes (unless explicitly set)
        if "board_column" not in data:
            status_col_map = {"active": "doing", "completed": "done", "paused": "on_hold", "cancelled": "done", "pending": "todo"}
            if body.status in status_col_map:
                values["board_column"] = status_col_map[body.status]
    if body.progress is not None:
        values["progress"] = body.progress
    if body.priority is not None:
        values["priority"] = body.priority
    # Sprint board fields (S3-01)
    for field in ("sprint", "board_column", "position", "assigned_to", "tags", "title", "description", "due_date"):
        if field in data:
            values[field] = data[field]

    if values:
        try:
            uid = uuid.UUID(goal_id)
            result = await db.execute(update(Goal).where(Goal.id == uid).values(**values))
        except ValueError:
            result = await db.execute(update(Goal).where(Goal.goal_id == goal_id).values(**values))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
        await db.commit()
    return {"updated": True}


@router.patch("/goals/{goal_id}/move")
async def move_goal(
    goal_id: str,
    body: MoveGoal,
    db: AsyncSession = Depends(get_db),
):
    """Move goal to new board column (for drag-and-drop)."""
    new_column = body.board_column
    new_position = body.position

    column_to_status = {
        "backlog": "pending",
        "todo": "pending",
        "doing": "active",
        "on_hold": "paused",
        "done": "completed",
    }

    # Validate board_column
    if not new_column or new_column not in column_to_status:
        raise HTTPException(
            status_code=400,
            detail=f"board_column is required and must be one of: {list(column_to_status.keys())}",
        )

    values = {
        "board_column": new_column,
        "position": new_position,
    }

    new_status = column_to_status[new_column]
    values["status"] = new_status
    if new_status == "completed":
        values["completed_at"] = datetime.now()
    elif new_column != "done":
        # Clear completed_at when moving away from done
        values["completed_at"] = None

    try:
        uid = uuid.UUID(goal_id)
        result = await db.execute(update(Goal).where(Goal.id == uid).values(**values))
    except ValueError:
        result = await db.execute(update(Goal).where(Goal.goal_id == goal_id).values(**values))

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")

    await db.commit()
    return {"moved": True, "board_column": new_column, "position": new_position}


# ── Hourly goals ─────────────────────────────────────────────────────────────

@router.get("/hourly-goals")
async def get_hourly_goals(
    status: str | None = None, db: AsyncSession = Depends(get_db)
):
    stmt = select(HourlyGoal).order_by(HourlyGoal.hour_slot, HourlyGoal.created_at.desc())
    if status:
        stmt = stmt.where(HourlyGoal.status == status)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"goals": [g.to_dict() for g in rows], "count": len(rows)}


@router.post("/hourly-goals")
async def create_hourly_goal(body: CreateHourlyGoal, db: AsyncSession = Depends(get_db)):
    if _is_noisy_goal_payload(
        None,
        body.goal_type,
        body.description,
    ):
        return {"created": False, "skipped": True, "reason": "test_or_patch_noise"}

    goal = HourlyGoal(
        hour_slot=body.hour_slot,
        goal_type=body.goal_type,
        description=body.description,
        status=body.status,
    )
    db.add(goal)
    await db.commit()
    return {"created": True}


@router.patch("/hourly-goals/{goal_id}")
async def update_hourly_goal(
    goal_id: int, body: UpdateHourlyGoal, db: AsyncSession = Depends(get_db)
):
    status = body.status
    values: dict = {"status": status}
    if status == "completed":
        from sqlalchemy import text
        values["completed_at"] = text("NOW()")
    await db.execute(update(HourlyGoal).where(HourlyGoal.id == goal_id).values(**values))
    await db.commit()
    return {"updated": True}
