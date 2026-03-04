# aria_skills/goals.py
"""
Goal and task management skill.

Handles goal creation, scheduling, and tracking.
Persists via REST API (TICKET-12: eliminate in-memory stubs).
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class GoalSchedulerSkill(BaseSkill):
    """
    Goal and task scheduling.
    
    Config:
        max_active_goals: Maximum concurrent active goals
        default_priority: Default priority level (1-5)
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._goals: dict[str, dict] = {}  # fallback cache
        self._goal_counter = 0
        self._api = None
    
    @property
    def name(self) -> str:
        return "goals"
    
    async def initialize(self) -> bool:
        """Initialize goal scheduler."""
        self._max_active = self.config.config.get("max_active_goals", 10)
        self._default_priority = self.config.config.get("default_priority", 3)
        self._api = await get_api_client()
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Goal scheduler initialized (API-backed)")
        return True
    
    async def close(self):
        """Cleanup (shared API client is managed by api_client module)."""
        self._api = None
    
    async def health_check(self) -> SkillStatus:
        """Check scheduler availability."""
        return self._status
    
    @logged_method()
    async def create_goal(
        self,
        title: str,
        description: str = "",
        priority: int | None = None,
        due_date: datetime | None = None,
        parent_id: str | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ) -> SkillResult:
        """
        Create a new goal.
        
        Args:
            title: Goal title
            description: Detailed description
            priority: 1-5 (1 is highest)
            due_date: Optional deadline
            parent_id: Optional parent goal for subtasks
            tags: Optional categorization tags
            
        Returns:
            SkillResult with goal data
        """
        # Check active goal limit
        active_count = sum(1 for g in self._goals.values() if g["status"] == "active")
        if active_count >= self._max_active:
            return SkillResult.fail(f"Maximum active goals ({self._max_active}) reached")
        
        self._goal_counter += 1
        goal_id = f"goal_{self._goal_counter}"
        
        goal = {
            "id": goal_id,
            "title": title,
            "description": description,
            "priority": priority or self._default_priority,
            "status": "active",
            "progress": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "due_date": due_date.isoformat() if due_date else None,
            "parent_id": parent_id,
            "tags": tags or [],
            "subtasks": [],
            "notes": [],
        }
        
        # Always cache locally for fallback lookups
        self._goals[goal_id] = goal
        try:
            result = await self._api.post("/goals", data=goal)
            if not result:
                raise Exception(result.error)
            api_data = result.data
            # Merge API response with local goal data
            if isinstance(api_data, dict):
                self._goals[goal_id].update(api_data)
            self._log_usage("create_goal", True)
            return SkillResult.ok(self._goals[goal_id])
        except Exception as e:
            self.logger.warning(f"API create_goal failed, using fallback: {e}")
            self._log_usage("create_goal", True)
            return SkillResult.ok(goal)
    
    @logged_method()
    async def update_goal(
        self,
        goal_id: str,
        status: str | None = None,
        progress: int | None = None,
        priority: int | None = None,
        notes: str | None = None,
    ) -> SkillResult:
        """
        Update a goal.
        
        Args:
            goal_id: Goal to update
            status: New status (active, completed, paused, cancelled)
            progress: Progress percentage (0-100)
            priority: New priority
            notes: Add a note
            
        Returns:
            SkillResult with updated goal
        """
        update_data: dict[str, Any] = {}
        if status:
            update_data["status"] = status
            if status == "completed":
                update_data["progress"] = 100
                update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        if progress is not None:
            update_data["progress"] = min(max(progress, 0), 100)
            if update_data["progress"] == 100:
                update_data["status"] = "completed"
                update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        if priority is not None:
            update_data["priority"] = min(max(priority, 1), 5)
        if notes:
            update_data["notes"] = notes
        
        try:
            resp = await self._api.patch(f"/goals/{goal_id}", data=update_data)
            if not resp:
                raise Exception(resp.error)
            api_data = resp.data
            self._log_usage("update_goal", True)
            return SkillResult.ok(api_data if api_data else update_data)
        except Exception as e:
            self.logger.warning(f"API update_goal failed, using fallback: {e}")
            # Look up by dict key first, then by "id" field (API may use UUIDs)
            goal = self._goals.get(goal_id)
            if goal is None:
                for g in self._goals.values():
                    if g.get("id") == goal_id:
                        goal = g
                        break
            if goal is None:
                return SkillResult.fail(f"Goal not found: {goal_id}")

            if status:
                goal["status"] = status
                if status == "completed":
                    goal["progress"] = 100
                    goal["completed_at"] = datetime.now(timezone.utc).isoformat()
            if progress is not None:
                goal["progress"] = min(max(progress, 0), 100)
                if goal["progress"] == 100:
                    goal["status"] = "completed"
                    goal["completed_at"] = datetime.now(timezone.utc).isoformat()
            if priority is not None:
                goal["priority"] = min(max(priority, 1), 5)
            if notes:
                goal["notes"].append({
                    "text": notes,
                    "added_at": datetime.now(timezone.utc).isoformat()
                })
            self._log_usage("update_goal", True)
            return SkillResult.ok(goal)
    
    @logged_method()
    async def get_goal(self, goal_id: str) -> SkillResult:
        """Get a specific goal."""
        try:
            result = await self._api.get(f"/goals/{goal_id}")
            if not result:
                raise Exception(result.error)
            return SkillResult.ok(result.data)
        except Exception as e:
            self.logger.warning(f"API get_goal failed, using fallback: {e}")
            if goal_id not in self._goals:
                return SkillResult.fail(f"Goal not found: {goal_id}")
            return SkillResult.ok(self._goals[goal_id])
    
    @logged_method()
    async def list_goals(
        self,
        status: str | None = None,
        priority: int | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> SkillResult:
        """
        List goals with filters.
        
        Args:
            status: Filter by status
            priority: Filter by priority
            tag: Filter by tag
            limit: Maximum results
            
        Returns:
            SkillResult with goal list
        """
        normalized_status = (status or "").strip().lower() or None
        board_column_statuses = {"backlog", "todo", "doing", "on_hold", "done"}

        def _normalize_goal_list(payload: Any) -> list[dict[str, Any]]:
            if isinstance(payload, list):
                return [g for g in payload if isinstance(g, dict)]
            if isinstance(payload, dict):
                if isinstance(payload.get("goals"), list):
                    return [g for g in payload["goals"] if isinstance(g, dict)]
                if isinstance(payload.get("items"), list):
                    return [g for g in payload["items"] if isinstance(g, dict)]
            return []

        def _priority_value(goal: dict[str, Any]) -> int:
            try:
                return int(goal.get("priority", 3) or 3)
            except Exception:
                return 3

        def _date_value(goal: dict[str, Any]) -> str:
            return str(goal.get("updated_at") or goal.get("created_at") or "")

        try:
            params: dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            if priority:
                params["priority"] = priority
            if tag:
                params["tag"] = tag

            resp = await self._api.get("/goals", params=params)
            if not resp:
                raise Exception(resp.error)

            api_goals = _normalize_goal_list(resp.data)

            board_columns: dict[str, list[dict[str, Any]]] = {}
            archive_goals: list[dict[str, Any]] = []

            board_resp = await self._api.get_goal_board("current")
            if board_resp and board_resp.success and isinstance(board_resp.data, dict):
                raw_columns = board_resp.data.get("columns") or {}
                if isinstance(raw_columns, dict):
                    for col in ("backlog", "todo", "doing", "on_hold", "done"):
                        board_columns[col] = _normalize_goal_list(raw_columns.get(col))

            archive_resp = await self._api.get_goal_archive(page=1, limit=max(limit, 100))
            if archive_resp and archive_resp.success:
                archive_goals = _normalize_goal_list(archive_resp.data)

            goals: list[dict[str, Any]]
            if normalized_status in board_column_statuses and board_columns:
                goals = list(board_columns.get(normalized_status or "", []))
            elif normalized_status in {"archived", "archive"}:
                goals = list(archive_goals)
            elif normalized_status in {"active", "in_progress"} and board_columns:
                goals = [
                    *board_columns.get("backlog", []),
                    *board_columns.get("todo", []),
                    *board_columns.get("doing", []),
                    *board_columns.get("on_hold", []),
                ]
            elif normalized_status == "all" and board_columns:
                goals = [
                    *board_columns.get("backlog", []),
                    *board_columns.get("todo", []),
                    *board_columns.get("doing", []),
                    *board_columns.get("on_hold", []),
                    *board_columns.get("done", []),
                    *archive_goals,
                ]
            else:
                goals = list(api_goals)

            if priority is not None:
                goals = [g for g in goals if _priority_value(g) == int(priority)]

            if tag:
                goals = [g for g in goals if tag in (g.get("tags") or [])]

            goals.sort(key=lambda g: (_priority_value(g), _date_value(g)), reverse=False)
            goals = goals[:limit]

            board_counts = {
                "backlog": len(board_columns.get("backlog", [])),
                "todo": len(board_columns.get("todo", [])),
                "doing": len(board_columns.get("doing", [])),
                "on_hold": len(board_columns.get("on_hold", [])),
                "done": len(board_columns.get("done", [])),
                "archived": len(archive_goals),
            }

            return SkillResult.ok({
                "goals": goals,
                "total": len(goals),
                "filters_applied": {"status": status, "priority": priority, "tag": tag, "limit": limit},
                "board_counts": board_counts,
            })
        except Exception as e:
            self.logger.warning(f"API list_goals failed, using fallback: {e}")
            goals = list(self._goals.values())
            if status:
                goals = [g for g in goals if g["status"] == status]
            if priority:
                goals = [g for g in goals if g["priority"] == priority]
            if tag:
                goals = [g for g in goals if tag in g.get("tags", [])]
            goals.sort(key=lambda g: (g["priority"], g.get("due_date") or "9999"))
            return SkillResult.ok({
                "goals": goals[:limit],
                "total": len(goals),
                "filters_applied": {"status": status, "priority": priority, "tag": tag},
            })

    @logged_method()
    async def get_next_actions(self, limit: int = 5) -> SkillResult:
        """
        Get prioritized next actions.
        
        Returns highest priority active goals that are due soonest.
        """
        try:
            result = await self._api.get("/goals", params={"status": "active", "limit": limit})
            if not result:
                raise Exception(result.error)
            api_data = result.data
            goals = api_data if isinstance(api_data, list) else api_data.get("goals", [])
            return SkillResult.ok({"next_actions": goals[:limit], "total_active": len(goals)})
        except Exception as e:
            self.logger.warning(f"API get_next_actions failed, using fallback: {e}")
            active = [g for g in self._goals.values() if g["status"] == "active"]
            now = datetime.now(timezone.utc)
            def score(goal):
                priority_score = goal["priority"] * 100
                if goal.get("due_date"):
                    due = datetime.fromisoformat(goal["due_date"])
                    days = (due - now).days
                    if days < 0:
                        return priority_score + days * 10
                    return priority_score + days
                return priority_score + 50
            active.sort(key=score)
            return SkillResult.ok({"next_actions": active[:limit], "total_active": len(active)})
    
    @logged_method()
    async def add_subtask(
        self,
        parent_id: str,
        title: str,
        description: str = "",
    ) -> SkillResult:
        """Add a subtask to a goal."""
        subtask = {
            "title": title,
            "description": description,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = await self._api.post(f"/goals/{parent_id}/subtasks", data=subtask)
            if not result:
                raise Exception(result.error)
            return SkillResult.ok(result.data)
        except Exception as e:
            self.logger.warning(f"API add_subtask failed, using fallback: {e}")
            if parent_id not in self._goals:
                return SkillResult.fail(f"Parent goal not found: {parent_id}")
            subtask_id = f"{parent_id}_sub_{len(self._goals[parent_id]['subtasks']) + 1}"
            subtask["id"] = subtask_id
            self._goals[parent_id]["subtasks"].append(subtask)
            return SkillResult.ok({"subtask": subtask, "parent_id": parent_id})
    
    @logged_method()
    async def complete_subtask(self, parent_id: str, subtask_id: str) -> SkillResult:
        """Mark a subtask as complete."""
        try:
            result = await self._api.patch(
                f"/goals/{parent_id}/subtasks/{subtask_id}",
                data={"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()},
            )
            if not result:
                raise Exception(result.error)
            return SkillResult.ok(result.data)
        except Exception as e:
            self.logger.warning(f"API complete_subtask failed, using fallback: {e}")
            if parent_id not in self._goals:
                return SkillResult.fail(f"Parent goal not found: {parent_id}")
            goal = self._goals[parent_id]
            for subtask in goal["subtasks"]:
                if subtask["id"] == subtask_id:
                    subtask["status"] = "completed"
                    subtask["completed_at"] = datetime.now(timezone.utc).isoformat()
                    total = len(goal["subtasks"])
                    completed = sum(1 for s in goal["subtasks"] if s["status"] == "completed")
                    goal["progress"] = int((completed / total) * 100)
                    return SkillResult.ok({"subtask": subtask, "parent_progress": goal["progress"]})
            return SkillResult.fail(f"Subtask not found: {subtask_id}")
    
    @logged_method()
    async def get_summary(self) -> SkillResult:
        """Get goal summary statistics."""
        try:
            result = await self._api.get("/goals")
            if not result:
                raise Exception(result.error)
            api_data = result.data
            goals = api_data if isinstance(api_data, list) else api_data.get("goals", [])

            board_counts = {
                "backlog": 0,
                "todo": 0,
                "doing": 0,
                "on_hold": 0,
                "done": 0,
                "archived": 0,
            }
            board_resp = await self._api.get_goal_board("current")
            if board_resp and board_resp.success and isinstance(board_resp.data, dict):
                cols = board_resp.data.get("columns") or {}
                if isinstance(cols, dict):
                    for col in ("backlog", "todo", "doing", "on_hold", "done"):
                        values = cols.get(col)
                        board_counts[col] = len(values) if isinstance(values, list) else 0
            archive_resp = await self._api.get_goal_archive(page=1, limit=1)
            if archive_resp and archive_resp.success and isinstance(archive_resp.data, dict):
                board_counts["archived"] = int(archive_resp.data.get("total") or 0)

            return SkillResult.ok({
                "total": len(goals),
                "by_status": {
                    "active": sum(1 for g in goals if g.get("status") == "active"),
                    "completed": sum(1 for g in goals if g.get("status") == "completed"),
                    "paused": sum(1 for g in goals if g.get("status") == "paused"),
                    "cancelled": sum(1 for g in goals if g.get("status") == "cancelled"),
                },
                "by_board_column": board_counts,
                "by_priority": {
                    p: sum(1 for g in goals if g.get("priority") == p) for p in range(1, 6)
                },
            })
        except Exception as e:
            self.logger.warning(f"API get_summary failed, using fallback: {e}")
            goals = list(self._goals.values())
            return SkillResult.ok({
                "total": len(goals),
                "by_status": {
                    "active": sum(1 for g in goals if g["status"] == "active"),
                    "completed": sum(1 for g in goals if g["status"] == "completed"),
                    "paused": sum(1 for g in goals if g["status"] == "paused"),
                    "cancelled": sum(1 for g in goals if g["status"] == "cancelled"),
                },
                "by_priority": {
                    p: sum(1 for g in goals if g["priority"] == p) for p in range(1, 6)
                },
                "overdue": sum(
                    1 for g in goals
                    if g["status"] == "active"
                    and g.get("due_date")
                    and datetime.fromisoformat(g["due_date"]) < datetime.now(timezone.utc)
                ),
            })
