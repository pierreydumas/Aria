# aria_skills/api_client.py
"""
Aria API Client Skill.

Centralized HTTP client for all aria-api interactions.
Skills should use this instead of direct database access.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from datetime import datetime

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.latency import log_latency
from aria_skills.registry import SkillRegistry

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@SkillRegistry.register
class AriaAPIClient(BaseSkill):
    """
    HTTP client for Aria's FastAPI backend.
    
    Config:
        api_url: Base URL for aria-api (default: http://aria-api:8000/api)
        timeout: Request timeout in seconds (default: 30)
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._client: "httpx.AsyncClient" | None = None
        self._api_url: str = ""
        self._max_retries: int = int(self.config.config.get("max_retries", 3))
        self._base_backoff_seconds: float = float(self.config.config.get("base_backoff_seconds", 0.5))
        # Trip only after 10 consecutive hard failures (not 5) to avoid false-open
        # on brief error bursts during cron work cycles.
        self._circuit_failure_threshold: int = int(self.config.config.get("circuit_failure_threshold", 10))
        self._circuit_reset_seconds: float = float(self.config.config.get("circuit_reset_seconds", 60.0))
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0
    
    @property
    def name(self) -> str:
        return "api_client"
    
    async def initialize(self) -> bool:
        """Initialize HTTP client."""
        if not HAS_HTTPX:
            self.logger.error("httpx not installed")
            self._status = SkillStatus.UNAVAILABLE
            return False
        
        self._api_url = self.config.config.get(
            "api_url", 
            os.environ.get("ARIA_API_URL", "http://aria-api:8000/api")
        ).rstrip("/")
        
        timeout = self.config.config.get("timeout", 30)
        
        # S-103: Include API key header for authenticated endpoints
        _headers = {"Content-Type": "application/json"}
        _api_key = os.environ.get("ARIA_API_KEY", "")
        if _api_key:
            _headers["X-API-Key"] = _api_key

        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=timeout,
            headers=_headers,
        )
        
        self._status = SkillStatus.AVAILABLE
        self.logger.info(f"API client initialized: {self._api_url}")
        return True
    
    async def health_check(self) -> SkillStatus:
        """Check API connectivity."""
        if not self._client:
            self._status = SkillStatus.UNAVAILABLE
            return self._status
        
        try:
            if self._is_circuit_open():
                self._status = SkillStatus.ERROR
                return self._status
            resp = await self._request_with_retry("GET", "/health")
            if resp.status_code == 200:
                self._status = SkillStatus.AVAILABLE
            else:
                self._status = SkillStatus.ERROR
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            self._status = SkillStatus.ERROR
        
        return self._status
    
    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._status = SkillStatus.UNAVAILABLE
    
    # ========================================
    # Activities
    # ========================================
    async def get_activities(self, limit: int = 50, page: int = 1) -> SkillResult:
        """Get recent activities (paginated)."""
        try:
            resp = await self._request_with_retry("GET", f"/activities?limit={limit}&page={page}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get activities: {e}")
    
    async def create_activity(
        self, 
        action: str, 
        skill: str | None = None,
        details: dict | None = None,
        success: bool = True,
        error_message: str | None = None
    ) -> SkillResult:
        """Log an activity."""
        try:
            resp = await self._request_with_retry("POST", "/activities", json={
                "action": action,
                "skill": skill,
                "details": details or {},
                "success": success,
                "error_message": error_message
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create activity: {e}")
    
    # ========================================
    # Security Events
    # ========================================
    async def get_security_events(
        self, 
        limit: int = 25, 
        page: int = 1,
        threat_level: str | None = None,
        blocked_only: bool = False
    ) -> SkillResult:
        """Get security events (paginated)."""
        try:
            url = f"/security-events?limit={limit}&page={page}"
            if threat_level:
                url += f"&threat_level={threat_level}"
            if blocked_only:
                url += "&blocked_only=true"
            resp = await self._request_with_retry("GET", url)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get security events: {e}")
    
    async def create_security_event(
        self,
        threat_level: str = "LOW",
        threat_type: str = "unknown",
        threat_patterns: list[str] | None = None,
        input_preview: str | None = None,
        source: str = "api",
        user_id: str | None = None,
        blocked: bool = False,
        details: dict | None = None
    ) -> SkillResult:
        """Log a security event."""
        try:
            resp = await self._request_with_retry("POST", "/security-events", json={
                "threat_level": threat_level,
                "threat_type": threat_type,
                "threat_patterns": threat_patterns or [],
                "input_preview": input_preview,
                "source": source,
                "user_id": user_id,
                "blocked": blocked,
                "details": details or {}
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create security event: {e}")
    
    async def get_security_stats(self) -> SkillResult:
        """Get security event statistics."""
        try:
            resp = await self._request_with_retry("GET", "/security-events/stats")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get security stats: {e}")
    
    # ========================================
    # Thoughts
    # ========================================
    async def get_thoughts(self, limit: int = 25, page: int = 1) -> SkillResult:
        """Get recent thoughts (paginated)."""
        try:
            resp = await self._request_with_retry("GET", f"/thoughts?limit={limit}&page={page}")
            data = resp.json()
            return SkillResult.ok(data.get("thoughts", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get thoughts: {e}")
    
    async def create_thought(
        self, 
        content: str, 
        category: str = "general",
        metadata: dict | None = None
    ) -> SkillResult:
        """Create a thought."""
        try:
            resp = await self._request_with_retry("POST", "/thoughts", json={
                "content": content,
                "category": category,
                "metadata": metadata or {}
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create thought: {e}")
    
    # ========================================
    # Memories
    # ========================================
    async def get_memories(
        self, 
        limit: int = 25, 
        page: int = 1,
        category: str | None = None
    ) -> SkillResult:
        """Get memories (paginated)."""
        try:
            url = f"/memories?limit={limit}&page={page}"
            if category:
                url += f"&category={category}"
            resp = await self._request_with_retry("GET", url)
            data = resp.json()
            return SkillResult.ok(data.get("memories", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get memories: {e}")
    
    async def get_memory(self, key: str) -> SkillResult:
        """Get a specific memory by key."""
        try:
            resp = await self._request_with_retry("GET", f"/memories/{key}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            if hasattr(e, "response") and getattr(e.response, "status_code", None) == 404:
                return SkillResult.ok(None)
            return SkillResult.fail(f"Failed to get memory: {e}")
    
    async def set_memory(
        self, 
        key: str, 
        value: Any, 
        category: str = "general"
    ) -> SkillResult:
        """Create or update a memory."""
        try:
            resp = await self._request_with_retry("POST", "/memories", json={
                "key": key,
                "value": value,
                "category": category
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to set memory: {e}")
    
    async def delete_memory(self, key: str) -> SkillResult:
        """Delete a memory."""
        try:
            resp = await self._request_with_retry("DELETE", f"/memories/{key}")
            return SkillResult.ok({"deleted": True, "key": key})
        except Exception as e:
            return SkillResult.fail(f"Failed to delete memory: {e}")
    
    # ========================================
    # Goals
    # ========================================
    async def get_goals(
        self, 
        limit: int = 25, 
        page: int = 1,
        status: str | None = None
    ) -> SkillResult:
        """Get goals (paginated)."""
        try:
            url = f"/goals?limit={limit}&page={page}"
            if status:
                url += f"&status={status}"
            resp = await self._request_with_retry("GET", url)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get goals: {e}")
    
    async def create_goal(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        status: str = "pending",
        progress: int = 0,
        due_date: str | None = None,
        goal_id: str | None = None,
        sprint: str | None = None,
        board_column: str | None = None,
        assigned_to: str | None = None,
        tags: list | None = None,
        **kwargs,
    ) -> SkillResult:
        """Create a goal."""
        try:
            data = {
                "title": title,
                "description": description,
                "priority": priority,
                "status": status,
                "progress": progress,
            }
            if due_date:
                data["due_date"] = due_date
            if goal_id:
                data["goal_id"] = goal_id
            if sprint:
                data["sprint"] = sprint
            if board_column:
                data["board_column"] = board_column
            if assigned_to:
                data["assigned_to"] = assigned_to
            if tags:
                data["tags"] = tags
            
            resp = await self._request_with_retry("POST", "/goals", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create goal: {e}")
    
    async def update_goal(
        self,
        goal_id: str,
        status: str | None = None,
        progress: int | None = None,
        priority: int | None = None,
        board_column: str | None = None,
        due_date: str | None = None,
        sprint: str | None = None,
        assigned_to: str | None = None,
        tags: list | None = None,
        **kwargs,
    ) -> SkillResult:
        """Update a goal."""
        try:
            data = {}
            if status is not None:
                data["status"] = status
            if progress is not None:
                data["progress"] = progress
            if priority is not None:
                data["priority"] = priority
            if board_column is not None:
                data["board_column"] = board_column
            if due_date is not None:
                data["due_date"] = due_date
            if sprint is not None:
                data["sprint"] = sprint
            if assigned_to is not None:
                data["assigned_to"] = assigned_to
            if tags is not None:
                data["tags"] = tags

            for key, value in kwargs.items():
                if value is not None:
                    data[key] = value
            
            resp = await self._request_with_retry("PATCH", f"/goals/{goal_id}", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update goal: {e}")
    
    async def delete_goal(self, goal_id: str) -> SkillResult:
        """Delete a goal."""
        try:
            resp = await self._request_with_retry("DELETE", f"/goals/{goal_id}")
            return SkillResult.ok({"deleted": True})
        except Exception as e:
            return SkillResult.fail(f"Failed to delete goal: {e}")

    # ========================================
    # Sprint Board (S3-05)
    # ========================================
    async def get_goal_board(self, sprint: str = "current") -> SkillResult:
        """Get goals organized by board column."""
        try:
            resp = await self._request_with_retry("GET", f"/goals/board?sprint={sprint}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get goal board: {e}")

    async def get_goal_archive(self, page: int = 1, limit: int = 25) -> SkillResult:
        """Get completed/cancelled goals archive."""
        try:
            resp = await self._request_with_retry("GET", f"/goals/archive?page={page}&limit={limit}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get goal archive: {e}")

    async def move_goal(self, goal_id: str, board_column: str, position: int = 0) -> SkillResult:
        """Move goal to a different board column."""
        try:
            resp = await self._request_with_retry("PATCH", f"/goals/{goal_id}/move", json={
                "board_column": board_column,
                "position": position,
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to move goal: {e}")

    async def get_sprint_summary(self, sprint: str = "current") -> SkillResult:
        """Get lightweight sprint summary (token-efficient)."""
        try:
            resp = await self._request_with_retry("GET", f"/goals/sprint-summary?sprint={sprint}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get sprint summary: {e}")

    async def get_goal_history(self, days: int = 14) -> SkillResult:
        """Get goal status distribution by day for charts."""
        try:
            resp = await self._request_with_retry("GET", f"/goals/history?days={days}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get goal history: {e}")
    
    # ========================================
    # Hourly Goals
    # ========================================
    async def get_hourly_goals(self, status: str | None = None, hour: int | None = None) -> SkillResult:
        """Get hourly goals, optionally filtered by status or hour."""
        try:
            params: dict[str, Any] = {}
            if status:
                params["status"] = status
            if hour is not None:
                params["hour"] = hour
            resp = await self._request_with_retry("GET", "/hourly-goals", params=params)
            data = resp.json()
            return SkillResult.ok(data.get("goals", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get hourly goals: {e}")
    
    async def create_hourly_goal(
        self,
        hour_slot: int,
        goal_type: str,
        description: str,
        status: str = "pending"
    ) -> SkillResult:
        """Create an hourly goal."""
        try:
            resp = await self._request_with_retry("POST", "/hourly-goals", json={
                "hour_slot": hour_slot,
                "goal_type": goal_type,
                "description": description,
                "status": status
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create hourly goal: {e}")
    
    async def update_hourly_goal(
        self,
        goal_id: int,
        status: str
    ) -> SkillResult:
        """Update an hourly goal status."""
        try:
            resp = await self._request_with_retry("PATCH", f"/hourly-goals/{goal_id}", json={
                "status": status
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update hourly goal: {e}")
    
    # ========================================
    # Knowledge Graph
    # ========================================
    async def get_knowledge_graph(self) -> SkillResult:
        """Get full knowledge graph."""
        try:
            resp = await self._request_with_retry("GET", "/knowledge-graph")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get knowledge graph: {e}")
    
    async def get_entities(
        self, 
        limit: int = 100, 
        entity_type: str | None = None
    ) -> SkillResult:
        """Get knowledge entities."""
        try:
            url = f"/knowledge-graph/entities?limit={limit}"
            if entity_type:
                url += f"&type={entity_type}"
            resp = await self._request_with_retry("GET", url)
            data = resp.json()
            return SkillResult.ok(data.get("entities", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get entities: {e}")
    
    async def create_entity(
        self,
        name: str,
        entity_type: str,
        properties: dict | None = None
    ) -> SkillResult:
        """Create a knowledge entity."""
        try:
            resp = await self._request_with_retry("POST", "/knowledge-graph/entities", json={
                "name": name,
                "type": entity_type,
                "properties": properties or {}
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create entity: {e}")
    
    async def create_relation(
        self,
        from_entity: str,
        to_entity: str,
        relation_type: str,
        properties: dict | None = None
    ) -> SkillResult:
        """Create a knowledge relation."""
        try:
            resp = await self._request_with_retry("POST", "/knowledge-graph/relations", json={
                "from_entity": from_entity,
                "to_entity": to_entity,
                "relation_type": relation_type,
                "properties": properties or {}
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create relation: {e}")
    
    async def graph_traverse(
        self,
        start: str,
        relation_type: str | None = None,
        max_depth: int = 3,
        direction: str = "outgoing",
    ) -> SkillResult:
        """BFS traversal from a starting entity. Token-efficient graph exploration."""
        try:
            params = {"start": start, "max_depth": max_depth, "direction": direction}
            if relation_type:
                params["relation_type"] = relation_type
            resp = await self._request_with_retry("GET", "/knowledge-graph/traverse", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to traverse graph: {e}")

    async def graph_search(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 25,
    ) -> SkillResult:
        """ILIKE text search for entities matching a query string."""
        try:
            params: dict[str, Any] = {"q": query, "limit": limit}
            if entity_type:
                params["entity_type"] = entity_type
            resp = await self._request_with_retry("GET", "/knowledge-graph/search", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to search graph: {e}")

    async def kg_traverse(
        self,
        start: str,
        relation_type: str | None = None,
        max_depth: int = 2,
        direction: str = "both",
    ) -> SkillResult:
        """BFS traversal on the organic knowledge graph (not skill graph)."""
        try:
            params: dict[str, Any] = {"start": start, "max_depth": max_depth, "direction": direction}
            if relation_type:
                params["relation_type"] = relation_type
            resp = await self._request_with_retry("GET", "/knowledge-graph/kg-traverse", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to traverse KG: {e}")

    async def kg_search(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 25,
    ) -> SkillResult:
        """ILIKE text search on the organic knowledge graph."""
        try:
            params: dict[str, Any] = {"q": query, "limit": limit}
            if entity_type:
                params["entity_type"] = entity_type
            resp = await self._request_with_retry("GET", "/knowledge-graph/kg-search", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to search KG: {e}")

    async def find_skill_for_task(self, task: str, limit: int = 5) -> SkillResult:
        """Find the best skill for a given task description. ~100-200 tokens."""
        try:
            resp = await self._request_with_retry("GET", 
                "/knowledge-graph/skill-for-task",
                params={"task": task, "limit": limit},
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to find skill for task: {e}")

    async def delete_auto_generated_graph(self) -> SkillResult:
        """Delete all auto-generated knowledge graph entities + relations."""
        try:
            resp = await self._request_with_retry("DELETE", "/knowledge-graph/auto-generated")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to delete auto-generated graph: {e}")

    async def sync_skill_graph(self) -> SkillResult:
        """Trigger skill graph sync (idempotent regeneration)."""
        try:
            resp = await self._request_with_retry("POST", "/knowledge-graph/sync-skills")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to sync skill graph: {e}")

    async def get_query_log(self, limit: int = 50) -> SkillResult:
        """Get recent knowledge graph query log entries."""
        try:
            resp = await self._request_with_retry("GET", "/knowledge-graph/query-log", params={"limit": limit})
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get query log: {e}")
    
    # ========================================
    # Social Posts
    # ========================================
    async def get_social_posts(
        self, 
        limit: int = 25, 
        page: int = 1,
        platform: str | None = None
    ) -> SkillResult:
        """Get social posts (paginated)."""
        try:
            url = f"/social?limit={limit}&page={page}"
            if platform:
                url += f"&platform={platform}"
            resp = await self._request_with_retry("GET", url)
            data = resp.json()
            return SkillResult.ok(data.get("posts", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get social posts: {e}")
    
    async def create_social_post(
        self,
        content: str,
        platform: str = "unknown",
        visibility: str = "public",
        post_id: str | None = None,
        reply_to: str | None = None,
        url: str | None = None,
        metadata: dict | None = None
    ) -> SkillResult:
        """Create a social post."""
        try:
            data = {
                "content": content,
                "platform": platform,
                "visibility": visibility
            }
            if post_id:
                data["post_id"] = post_id
            if reply_to:
                data["reply_to"] = reply_to
            if url:
                data["url"] = url
            if metadata:
                data["metadata"] = metadata
            
            resp = await self._request_with_retry("POST", "/social", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create social post: {e}")
    
    # ========================================
    # Heartbeat
    # ========================================
    async def get_heartbeats(self, limit: int = 50) -> SkillResult:
        """Get heartbeat logs."""
        try:
            resp = await self._request_with_retry("GET", f"/heartbeat?limit={limit}")
            data = resp.json()
            return SkillResult.ok(data.get("heartbeats", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get heartbeats: {e}")
    
    async def get_latest_heartbeat(self) -> SkillResult:
        """Get latest heartbeat."""
        try:
            resp = await self._request_with_retry("GET", "/heartbeat/latest")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get latest heartbeat: {e}")
    
    async def create_heartbeat(
        self,
        beat_number: int = 0,
        status: str = "healthy",
        details: dict | None = None
    ) -> SkillResult:
        """Log a heartbeat."""
        try:
            resp = await self._request_with_retry("POST", "/heartbeat", json={
                "beat_number": beat_number,
                "status": status,
                "details": details or {}
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create heartbeat: {e}")
    
    # ========================================
    # Performance
    # ========================================
    async def get_performance_logs(self, limit: int = 50) -> SkillResult:
        """Get performance logs."""
        try:
            resp = await self._request_with_retry("GET", f"/performance?limit={limit}")
            data = resp.json()
            return SkillResult.ok(data.get("logs", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get performance logs: {e}")
    
    async def create_performance_log(
        self,
        review_period: str,
        successes: str | None = None,
        failures: str | None = None,
        improvements: str | None = None
    ) -> SkillResult:
        """Create a performance log."""
        try:
            resp = await self._request_with_retry("POST", "/performance", json={
                "review_period": review_period,
                "successes": successes,
                "failures": failures,
                "improvements": improvements
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create performance log: {e}")
    
    # ========================================
    # Tasks
    # ========================================
    async def get_tasks(self, status: str | None = None) -> SkillResult:
        """Get pending complex tasks."""
        try:
            url = "/tasks"
            if status:
                url += f"?status={status}"
            resp = await self._request_with_retry("GET", url)
            data = resp.json()
            return SkillResult.ok(data.get("tasks", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get tasks: {e}")
    
    async def create_task(
        self,
        task_type: str,
        description: str,
        agent_type: str,
        priority: str = "medium",
        task_id: str | None = None
    ) -> SkillResult:
        """Create a pending complex task."""
        try:
            data = {
                "task_type": task_type,
                "description": description,
                "agent_type": agent_type,
                "priority": priority
            }
            if task_id:
                data["task_id"] = task_id
            
            resp = await self._request_with_retry("POST", "/tasks", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create task: {e}")
    
    async def update_task(
        self,
        task_id: str,
        status: str,
        result: str | None = None
    ) -> SkillResult:
        """Update a task status."""
        try:
            resp = await self._request_with_retry("PATCH", f"/tasks/{task_id}", json={
                "status": status,
                "result": result
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update task: {e}")
    
    # ========================================
    # Schedule
    # ========================================
    async def get_schedule(self) -> SkillResult:
        """Get schedule tick status."""
        try:
            resp = await self._request_with_retry("GET", "/schedule")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get schedule: {e}")
    
    async def trigger_schedule_tick(self) -> SkillResult:
        """Trigger a manual schedule tick."""
        try:
            resp = await self._request_with_retry("POST", "/schedule/tick")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to trigger tick: {e}")
    
    async def get_jobs(self, live: bool = False) -> SkillResult:
        """Get scheduled jobs."""
        try:
            url = "/jobs/live" if live else "/jobs"
            resp = await self._request_with_retry("GET", url)
            data = resp.json()
            return SkillResult.ok(data.get("jobs", data))
        except Exception as e:
            return SkillResult.fail(f"Failed to get jobs: {e}")
    
    async def sync_jobs(self) -> SkillResult:
        """Sync jobs from scheduler."""
        try:
            resp = await self._request_with_retry("POST", "/jobs/sync")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to sync jobs: {e}")
    
    # ========================================
    # Agent Sessions
    # ========================================
    async def get_sessions(
        self,
        limit: int = 25,
        page: int = 1,
        status: str | None = None,
    ) -> SkillResult:
        """Get agent sessions (paginated)."""
        try:
            url = f"/sessions?limit={limit}&page={page}"
            if status:
                url += f"&status={status}"
            resp = await self._request_with_retry("GET", url)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get sessions: {e}")

    async def create_session(
        self,
        agent_id: str,
        session_type: str = "interactive",
        metadata: dict | None = None,
    ) -> SkillResult:
        """Start a new agent session."""
        try:
            resp = await self._request_with_retry("POST", "/sessions", json={
                "agent_id": agent_id,
                "session_type": session_type,
                "metadata": metadata or {},
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create session: {e}")

    async def update_session(
        self,
        session_id: str,
        status: str | None = None,
        messages_count: int | None = None,
        tokens_used: int | None = None,
        cost_usd: float | None = None,
    ) -> SkillResult:
        """Update agent session."""
        try:
            data = {}
            if status is not None:
                data["status"] = status
            if messages_count is not None:
                data["messages_count"] = messages_count
            if tokens_used is not None:
                data["tokens_used"] = tokens_used
            if cost_usd is not None:
                data["cost_usd"] = cost_usd
            resp = await self._request_with_retry("PATCH", f"/sessions/{session_id}", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update session: {e}")

    async def get_session_stats(self) -> SkillResult:
        """Get session statistics."""
        try:
            resp = await self._request_with_retry("GET", "/sessions/stats")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get session stats: {e}")

    # ========================================
    # Model Usage
    # ========================================
    async def get_model_usage(self, limit: int = 50, page: int = 1) -> SkillResult:
        """Get model usage records (paginated)."""
        try:
            resp = await self._request_with_retry("GET", f"/model-usage?limit={limit}&page={page}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get model usage: {e}")

    async def create_model_usage(
        self,
        model: str,
        provider: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int | None = None,
        success: bool = True,
        error_message: str | None = None,
        session_id: str | None = None,
    ) -> SkillResult:
        """Log model usage."""
        try:
            data: dict[str, Any] = {
                "model": model,
                "provider": provider,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "success": success,
            }
            if latency_ms is not None:
                data["latency_ms"] = latency_ms
            if error_message:
                data["error_message"] = error_message
            if session_id:
                data["session_id"] = session_id
            resp = await self._request_with_retry("POST", "/model-usage", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to log model usage: {e}")

    async def get_model_usage_stats(self, hours: int = 24) -> SkillResult:
        """Get model usage statistics (merged with LiteLLM data)."""
        try:
            resp = await self._request_with_retry("GET", f"/model-usage/stats?hours={hours}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get model usage stats: {e}")

    # ========================================
    # LiteLLM
    # ========================================
    async def get_litellm_models(self) -> SkillResult:
        """Get available LiteLLM models."""
        try:
            resp = await self._request_with_retry("GET", "/litellm/models")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get LiteLLM models: {e}")

    async def get_litellm_health(self) -> SkillResult:
        """Get LiteLLM health status."""
        try:
            resp = await self._request_with_retry("GET", "/litellm/health")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get LiteLLM health: {e}")

    async def get_litellm_spend(self, limit: int = 100) -> SkillResult:
        """Get LiteLLM spend logs."""
        try:
            resp = await self._request_with_retry("GET", f"/litellm/spend?limit={limit}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get LiteLLM spend: {e}")

    # ========================================
    # Provider Balances
    # ========================================
    async def get_provider_balances(self) -> SkillResult:
        """Get provider balance info (Kimi, OpenRouter, local)."""
        try:
            resp = await self._request_with_retry("GET", "/providers/balances")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get provider balances: {e}")

    # ========================================
    # Working Memory
    # ========================================
    async def remember(self, key: str, value: Any, category: str = "general",
                       importance: float = 0.5, ttl_hours: int | None = None,
                       source: str | None = None) -> SkillResult:
        """Store a working memory item."""
        try:
            resp = await self._request_with_retry("POST", "/working-memory", json={
                "key": key, "value": value, "category": category,
                "importance": importance, "ttl_hours": ttl_hours, "source": source,
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to store working memory: {e}")

    async def recall(self, key: str | None = None,
                     category: str | None = None,
                     limit: int = 25, page: int = 1) -> SkillResult:
        """Retrieve working memory items (paginated)."""
        try:
            params: dict[str, Any] = {"limit": limit, "page": page}
            if key:
                params["key"] = key
            if category:
                params["category"] = category
            resp = await self._request_with_retry("GET", "/working-memory", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to recall working memory: {e}")

    async def get_working_memory_context(self, limit: int = 20,
                                          category: str | None = None) -> SkillResult:
        """Get weighted-ranked context for LLM injection."""
        try:
            params: dict[str, Any] = {"limit": limit}
            if category:
                params["category"] = category
            resp = await self._request_with_retry("GET", "/working-memory/context", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get working memory context: {e}")

    async def working_memory_checkpoint(self) -> SkillResult:
        """Snapshot current working memory."""
        try:
            resp = await self._request_with_retry("POST", "/working-memory/checkpoint", json={})
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to checkpoint working memory: {e}")

    async def restore_working_memory_checkpoint(self) -> SkillResult:
        """Restore from latest working memory checkpoint."""
        try:
            resp = await self._request_with_retry("GET", "/working-memory/checkpoint")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to restore checkpoint: {e}")

    async def forget_working_memory(self, item_id: str) -> SkillResult:
        """Delete a working memory item."""
        try:
            resp = await self._request_with_retry("DELETE", f"/working-memory/{item_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to forget working memory item: {e}")

    async def update_working_memory(self, item_id: str, **kwargs) -> SkillResult:
        """Update a working memory item."""
        try:
            resp = await self._request_with_retry("PATCH", f"/working-memory/{item_id}", json=kwargs)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update working memory item: {e}")

    # ========================================
    # Generic / Raw
    # ========================================
    def _is_circuit_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_failure_threshold:
            self._circuit_open_until = time.monotonic() + self._circuit_reset_seconds
            self.logger.warning(
                "api_client circuit opened for %.1fs after %d failures",
                self._circuit_reset_seconds,
                self._consecutive_failures,
            )

    async def _request_with_retry(self, method: str, path: str, **kwargs):
        if not self._client:
            raise RuntimeError("API client is not initialized")

        if self._is_circuit_open():
            raise RuntimeError("API circuit breaker is open")

        attempts = max(1, self._max_retries)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if (resp.status_code >= 500 or resp.status_code == 429) and attempt < attempts - 1:
                    delay = self._base_backoff_seconds * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                self._record_success()
                return resp
            except Exception as exc:
                last_error = exc

                # Do not retry client-side request errors (except 429 throttling).
                # These are usually validation/schema issues and should not open the
                # connectivity circuit breaker.
                if HAS_HTTPX and isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code
                    if 400 <= status < 500 and status != 429:
                        raise

                self._record_failure()
                if attempt < attempts - 1:
                    delay = self._base_backoff_seconds * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                raise

        raise RuntimeError(f"request failed: {last_error}")

    @log_latency
    async def get(self, path: str, params: dict | None = None) -> SkillResult:
        """Generic GET request."""
        try:
            resp = await self._request_with_retry("GET", path, params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"GET {path} failed: {e}")
    
    @log_latency
    async def post(
        self,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> SkillResult:
        """Generic POST request."""
        try:
            resp = await self._request_with_retry(
                "POST", path, json=data, params=params
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"POST {path} failed: {e}")
    
    async def patch(self, path: str, data: dict | None = None) -> SkillResult:
        """Generic PATCH request."""
        try:
            resp = await self._request_with_retry("PATCH", path, json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"PATCH {path} failed: {e}")

    async def put(self, path: str, data: dict | None = None) -> SkillResult:
        """Generic PUT request."""
        try:
            resp = await self._request_with_retry("PUT", path, json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"PUT {path} failed: {e}")
    
    async def delete(self, path: str) -> SkillResult:
        """Generic DELETE request."""
        try:
            resp = await self._request_with_retry("DELETE", path)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"DELETE {path} failed: {e}")

    # ── Batch Operations (S-167) ────────────────────────────────────

    async def batch_get(
        self, operations: list[dict[str, Any]]
    ) -> list[SkillResult]:
        """Execute multiple GET requests concurrently.

        Args:
            operations: List of dicts with "path" and optional "params" keys.
                Example: [{"path": "/goals"}, {"path": "/activities", "params": {"limit": 5}}]

        Returns:
            List of SkillResult in the same order as the input operations.
        """
        tasks = [
            self.get(op["path"], params=op.get("params"))
            for op in operations
        ]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def batch_post(
        self, operations: list[dict[str, Any]]
    ) -> list[SkillResult]:
        """Execute multiple POST requests concurrently.

        Args:
            operations: List of dicts with "path" and optional "data" keys.
                Example: [{"path": "/activities", "data": {"action": "x"}}]

        Returns:
            List of SkillResult in the same order as the input operations.
        """
        tasks = [
            self.post(op["path"], data=op.get("data"))
            for op in operations
        ]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    # ── Performance logging (S-21) ──────────────────────────────────

    async def log_agent_performance(self, data: dict) -> SkillResult:
        """POST agent performance record to aria-api."""
        return await self.post("/performance", data=data)

    async def get_agent_performance(
        self, agent_id: str | None = None, limit: int = 100
    ) -> list:
        """GET agent performance records, optionally filtered by agent."""
        params: dict[str, Any] = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        result = await self.get("/performance", params=params)
        if result.success:
            return result.data.get("records", []) if isinstance(result.data, dict) else []
        return []

    async def get_all_pages(self, method_name: str, **kwargs) -> SkillResult:
        """Fetch all pages of a paginated endpoint."""
        all_items: list = []
        page = 1
        while True:
            result = await getattr(self, method_name)(page=page, **kwargs)
            if not result.success:
                return result
            data = result.data
            if isinstance(data, dict):
                all_items.extend(data.get("items", []))
                if page >= data.get("pages", 1):
                    break
            else:
                all_items.extend(data if isinstance(data, list) else [])
                break
            page += 1
        return SkillResult.ok({"items": all_items, "total": len(all_items)})

    # ========================================
    # Semantic Memory (S5-01)
    # ========================================
    async def store_memory_semantic(
        self, content: str, category: str = "general",
        importance: float = 0.5, source: str = "aria",
        summary: str = None, metadata: dict | None = None,
    ) -> SkillResult:
        """Store a memory with vector embedding for semantic search."""
        try:
            data = {
                "content": content, "category": category,
                "importance": importance, "source": source,
            }
            if summary:
                data["summary"] = summary
            if metadata:
                data["metadata"] = metadata
            resp = await self._request_with_retry("POST", "/memories/semantic", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to store semantic memory: {e}")

    # ========================================
    # Sentiment Events (S-47)
    # ========================================
    async def store_sentiment_event(
        self, message: str, session_id: str = None,
        external_session_id: str = None, agent_id: str = None,
        source_channel: str = None, store_semantic: bool = True,
        metadata: dict | None = None,
    ) -> SkillResult:
        """Analyze and persist sentiment for a user message via /analysis/sentiment/reply."""
        try:
            data: dict[str, Any] = {
                "message": message,
                "store_semantic": store_semantic,
            }
            if session_id:
                data["session_id"] = session_id
            if external_session_id:
                data["external_session_id"] = external_session_id
            if agent_id:
                data["agent_id"] = agent_id
            if source_channel:
                data["source_channel"] = source_channel
            if metadata:
                data["metadata"] = metadata
            resp = await self._request_with_retry("POST", "/analysis/sentiment/reply", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to store sentiment event: {e}")

    async def search_memories_semantic(
        self, query: str, limit: int = 5,
        category: str = None, min_importance: float = 0.0,
    ) -> SkillResult:
        """Search memories by semantic similarity."""
        try:
            params: dict[str, Any] = {"query": query, "limit": limit}
            if category:
                params["category"] = category
            if min_importance > 0:
                params["min_importance"] = min_importance
            resp = await self._request_with_retry("GET", "/memories/search", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to search semantic memories: {e}")

    async def list_semantic_memories(
        self, category: str = None, source: str = None,
        limit: int = 50, page: int = 1,
        min_importance: float = 0.0,
    ) -> SkillResult:
        """List semantic memories with optional category/source filter (no embedding query needed)."""
        try:
            params: dict[str, Any] = {"limit": limit, "page": page}
            if category:
                params["category"] = category
            if source:
                params["source"] = source
            if min_importance > 0:
                params["min_importance"] = min_importance
            resp = await self._request_with_retry("GET", "/memories/semantic", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to list semantic memories: {e}")

    async def summarize_session(self, hours_back: int = 24) -> SkillResult:
        """Summarize recent session into episodic memory."""
        try:
            resp = await self._request_with_retry("POST", 
                "/memories/summarize-session", json={"hours_back": hours_back}
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to summarize session: {e}")

    # ========================================
    # Memory Bridge / Seed (analysis)
    # ========================================
    async def seed_memories(
        self, limit: int = 100, skip_existing: bool = True,
    ) -> SkillResult:
        """Backfill semantic_memories from recent activities + thoughts.

        Calls POST /analysis/seed-memories which generates embeddings via
        LiteLLM and stores them in pgvector for pattern recognition,
        sentiment analysis, and semantic search.
        """
        try:
            resp = await self._request_with_retry("POST", 
                "/analysis/seed-memories",
                params={"limit": limit, "skip_existing": skip_existing},
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to seed memories: {e}")

    async def detect_patterns(
        self, category: str = None, limit: int = 50,
    ) -> SkillResult:
        """Run pattern detection on semantic memories."""
        try:
            data: dict[str, Any] = {}
            if category:
                data["category"] = category
            if limit:
                data["limit"] = limit
            resp = await self._request_with_retry("POST", "/analysis/patterns/detect", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to detect patterns: {e}")

    async def get_memory_stats(self) -> SkillResult:
        """Get statistics about semantic memories (counts, categories, sources)."""
        try:
            resp = await self._request_with_retry("GET", "/memories/semantic/stats")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get memory stats: {e}")

    # ========================================
    # Lessons Learned (S5-02)
    # ========================================
    async def record_lesson(
        self, error_pattern: str, error_type: str,
        resolution: str, skill_name: str = None,
        context: dict | None = None,
    ) -> SkillResult:
        """Record a lesson learned from an error."""
        try:
            data = {
                "error_pattern": error_pattern, "error_type": error_type,
                "resolution": resolution,
            }
            if skill_name:
                data["skill_name"] = skill_name
            if context:
                data["context"] = context
            resp = await self._request_with_retry("POST", "/lessons", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to record lesson: {e}")

    async def check_known_errors(
        self, error_type: str = None, skill_name: str = None,
    ) -> SkillResult:
        """Check if a known resolution exists for an error type."""
        try:
            params: dict[str, Any] = {}
            if error_type:
                params["error_type"] = error_type
            if skill_name:
                params["skill_name"] = skill_name
            resp = await self._request_with_retry("GET", "/lessons/check", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to check known errors: {e}")

    async def get_lessons(self, page: int = 1, per_page: int = 25) -> SkillResult:
        """List lessons learned."""
        try:
            resp = await self._request_with_retry("GET", 
                "/lessons", params={"page": page, "per_page": per_page}
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get lessons: {e}")

    # ========================================
    # Improvement Proposals (S5-06)
    # ========================================
    async def propose_improvement(
        self, title: str, description: str, category: str = "general",
        risk_level: str = "low", file_path: str = None,
        current_code: str = None, proposed_code: str = None,
        rationale: str = "",
    ) -> SkillResult:
        """Submit an improvement proposal."""
        try:
            data: dict[str, Any] = {
                "title": title, "description": description,
                "category": category, "risk_level": risk_level,
                "rationale": rationale,
            }
            if file_path:
                data["file_path"] = file_path
            if current_code is not None:
                data["current_code"] = current_code
            if proposed_code is not None:
                data["proposed_code"] = proposed_code
            resp = await self._request_with_retry("POST", "/proposals", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to propose improvement: {e}")

    async def get_proposals(self, status: str = None, page: int = 1) -> SkillResult:
        """List improvement proposals."""
        try:
            params: dict[str, Any] = {"page": page}
            if status:
                params["status"] = status
            resp = await self._request_with_retry("GET", "/proposals", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get proposals: {e}")

    async def get_proposal(self, proposal_id: str) -> SkillResult:
        """Get a single improvement proposal by ID."""
        try:
            resp = await self._request_with_retry("GET", f"/proposals/{proposal_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get proposal: {e}")

    async def review_proposal(
        self,
        proposal_id: str,
        status: str,
        reviewed_by: str = "aria",
    ) -> SkillResult:
        """Review a proposal with status approved/rejected/implemented."""
        if status not in ("approved", "rejected", "implemented"):
            return SkillResult.fail("status must be approved, rejected, or implemented")
        try:
            resp = await self._request_with_retry("PATCH", 
                f"/proposals/{proposal_id}",
                json={"status": status, "reviewed_by": reviewed_by},
            )
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to review proposal: {e}")

    async def mark_proposal_implemented(
        self,
        proposal_id: str,
        reviewed_by: str = "aria",
    ) -> SkillResult:
        """Mark an approved proposal as implemented."""
        return await self.review_proposal(
            proposal_id=proposal_id,
            status="implemented",
            reviewed_by=reviewed_by,
        )

    # ========================================
    # Skill Invocations (S5-07)
    # ========================================
    async def record_invocation(
        self, skill_name: str, tool_name: str,
        duration_ms: int = 0, success: bool = True,
        error_type: str = None, tokens_used: int = None,
        model_used: str = None,
    ) -> SkillResult:
        """Record a skill invocation for observability."""
        try:
            data: dict[str, Any] = {
                "skill_name": skill_name, "tool_name": tool_name,
                "duration_ms": duration_ms, "success": success,
            }
            if error_type:
                data["error_type"] = error_type
            if tokens_used is not None:
                data["tokens_used"] = tokens_used
            if model_used:
                data["model_used"] = model_used
            resp = await self._request_with_retry("POST", "/skills/invocations", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to record invocation: {e}")

    async def get_skill_stats(self, hours: int = 24) -> SkillResult:
        """Get skill performance stats."""
        try:
            resp = await self._request_with_retry("GET", "/skills/stats", params={"hours": hours})
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get skill stats: {e}")

    # ── File Artifacts (aria_memories) ──────────────────────────────────────

    async def write_artifact(
        self,
        content: str,
        filename: str,
        category: str = "memory",
        subfolder: str | None = None,
    ) -> SkillResult:
        """Write a file artifact (diary, plan, research, draft, etc.) to persistent storage in aria_memories/."""
        try:
            data: dict = {"content": content, "filename": filename, "category": category}
            if subfolder:
                data["subfolder"] = subfolder
            resp = await self._request_with_retry("POST", "/artifacts", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to write artifact: {e}")

    async def read_artifact(self, category: str, filename: str) -> SkillResult:
        """Read a file artifact from aria_memories/<category>/<filename>."""
        try:
            resp = await self._request_with_retry("GET", f"/artifacts/{category}/{filename}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to read artifact: {e}")

    async def read_artifact_by_path(self, path: str) -> SkillResult:
        """Read an artifact using canonical list_artifacts path, e.g. memory/logs/file.json.

        Use this when you have a full relative path returned by list_artifacts
        (e.g. ``memory/logs/work_cycle_2026-02-27_0416.json``) and want a safe
        read without manually splitting category from nested filename.
        """
        try:
            clean = path.strip("/")
            if "/" not in clean:
                return SkillResult.fail(
                    f"Path must include category and filename, got: '{path}'"
                )
            category, filename = clean.split("/", 1)
            return await self.read_artifact(category=category, filename=filename)
        except Exception as e:
            return SkillResult.fail(f"Failed to read artifact by path: {e}")

    async def list_artifacts(
        self,
        category: str | None = None,
        pattern: str | None = None,
        limit: int = 50,
    ) -> SkillResult:
        """List file artifacts in aria_memories/. Optionally filter by category and filename pattern."""
        try:
            params: dict = {"limit": limit}
            if category:
                params["category"] = category
            if pattern:
                params["pattern"] = pattern
            resp = await self._request_with_retry("GET", "/artifacts", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to list artifacts: {e}")

    async def delete_artifact(self, category: str, filename: str) -> SkillResult:
        """Delete a file artifact from aria_memories/<category>/<filename>."""
        try:
            resp = await self._request_with_retry("DELETE", f"/artifacts/{category}/{filename}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to delete artifact: {e}")

    # ========================================
    # Convenience Aliases & CRUD Shortcuts (S-112)
    # ========================================

    # -- Goals ---------------------------------------------------------------

    async def get_goal(self, goal_id: str) -> SkillResult:
        """Get a single goal by ID."""
        try:
            resp = await self._request_with_retry("GET", f"/goals/{goal_id}")
            if resp.status_code == 404:
                return SkillResult.fail(f"Goal not found: {goal_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get goal: {e}")

    async def list_goals(
        self, limit: int = 25, page: int = 1, status: str | None = None
    ) -> SkillResult:
        """List goals (alias for get_goals)."""
        return await self.get_goals(limit=limit, page=page, status=status)

    # -- Activities ----------------------------------------------------------

    async def list_activities(self, limit: int = 50, page: int = 1) -> SkillResult:
        """List activities (alias for get_activities)."""
        return await self.get_activities(limit=limit, page=page)

    # -- Agents --------------------------------------------------------------

    async def list_agents(self, limit: int = 50, page: int = 1) -> SkillResult:
        """List registered agents."""
        try:
            resp = await self._request_with_retry("GET", f"/agents?limit={limit}&page={page}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to list agents: {e}")

    async def get_agent(self, agent_id: str) -> SkillResult:
        """Get agent details by ID."""
        try:
            resp = await self._request_with_retry("GET", f"/agents/{agent_id}")
            if resp.status_code == 404:
                return SkillResult.fail(f"Agent not found: {agent_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get agent: {e}")

    async def spawn_agent(
        self,
        agent_type: str,
        config: dict | None = None,
        name: str | None = None,
    ) -> SkillResult:
        """Spawn (create) a new agent."""
        try:
            data: dict[str, Any] = {"agent_type": agent_type}
            if config:
                data["config"] = config
            if name:
                data["name"] = name
            resp = await self._request_with_retry("POST", "/agents", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to spawn agent: {e}")

    async def terminate_agent(self, agent_id: str) -> SkillResult:
        """Terminate (delete) an agent."""
        try:
            resp = await self._request_with_retry("DELETE", f"/agents/{agent_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to terminate agent: {e}")

    # -- Knowledge Graph convenience -----------------------------------------

    async def kg_add_entity(
        self,
        name: str,
        entity_type: str,
        properties: dict | None = None,
    ) -> SkillResult:
        """Add a knowledge-graph entity (alias for create_entity)."""
        return await self.create_entity(
            name=name, entity_type=entity_type, properties=properties,
        )

    async def kg_add_relation(
        self,
        from_entity: str,
        to_entity: str,
        relation_type: str,
        properties: dict | None = None,
    ) -> SkillResult:
        """Add a knowledge-graph relation (alias for create_relation)."""
        return await self.create_relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            properties=properties,
        )

    async def kg_query(
        self,
        entity_name: str | None = None,
        entity_type: str | None = None,
        relation_type: str | None = None,
        depth: int = 2,
    ) -> SkillResult:
        """Query the knowledge graph.

        When *entity_name* is provided a BFS traversal is performed.
        Otherwise entities are listed by *entity_type*.
        """
        if entity_name:
            return await self.kg_traverse(
                start=entity_name,
                relation_type=relation_type,
                max_depth=depth,
            )
        return await self.get_entities(entity_type=entity_type)

    async def kg_get_entity(
        self,
        name: str,
        entity_type: str | None = None,
    ) -> SkillResult:
        """Get a single knowledge-graph entity by name."""
        try:
            params: dict[str, Any] = {"q": name, "limit": 1}
            if entity_type:
                params["entity_type"] = entity_type
            resp = await self._request_with_retry("GET", "/knowledge-graph/kg-search", params=params)
            data = resp.json()
            results = data.get("results", [])
            if results:
                return SkillResult.ok(results[0])
            return SkillResult.fail(f"Entity not found: {name}")
        except Exception as e:
            return SkillResult.fail(f"Failed to get KG entity: {e}")

    # -- Schedule CRUD -------------------------------------------------------

    async def create_job(self, job: dict) -> SkillResult:
        """Create a scheduled job."""
        try:
            resp = await self._request_with_retry("POST", "/schedule", json=job)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to create job: {e}")

    async def get_job(self, job_id: str) -> SkillResult:
        """Get a scheduled job by ID."""
        try:
            resp = await self._request_with_retry("GET", f"/schedule/{job_id}")
            if resp.status_code == 404:
                return SkillResult.fail(f"Job not found: {job_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get job: {e}")

    async def list_jobs(
        self, enabled: bool | None = None, due: bool = False,
    ) -> SkillResult:
        """List scheduled jobs with optional filters."""
        try:
            params: dict[str, Any] = {}
            if enabled is not None:
                params["enabled"] = enabled
            if due:
                params["due"] = True
            resp = await self._request_with_retry("GET", "/schedule", params=params)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to list jobs: {e}")

    async def update_job(self, job_id: str, data: dict) -> SkillResult:
        """Update a scheduled job."""
        try:
            resp = await self._request_with_retry("PUT", f"/schedule/{job_id}", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update job: {e}")

    async def delete_job(self, job_id: str) -> SkillResult:
        """Delete a scheduled job."""
        try:
            resp = await self._request_with_retry("DELETE", f"/schedule/{job_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to delete job: {e}")

    # -- Working Memory convenience ------------------------------------------

    async def checkpoint(self) -> SkillResult:
        """Snapshot working memory (alias for working_memory_checkpoint)."""
        return await self.working_memory_checkpoint()

    async def forget(self, item_id: str) -> SkillResult:
        """Forget a working memory item (alias for forget_working_memory)."""
        return await self.forget_working_memory(item_id)

    # -- Performance convenience ---------------------------------------------

    async def log_review(
        self,
        period: str,
        successes: str | None = None,
        failures: str | None = None,
        improvements: str | None = None,
    ) -> SkillResult:
        """Log a performance review."""
        try:
            resp = await self._request_with_retry("POST", "/performance", json={
                "period": period,
                "successes": successes,
                "failures": failures,
                "improvements": improvements,
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to log review: {e}")

    async def get_reviews(self, limit: int = 25) -> SkillResult:
        """Get performance reviews."""
        try:
            resp = await self._request_with_retry("GET", "/performance", params={"limit": limit})
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to get reviews: {e}")

    # -- Sprint convenience --------------------------------------------------

    async def sprint_status(self, sprint: str = "current") -> SkillResult:
        """Get sprint status (alias for get_sprint_summary)."""
        return await self.get_sprint_summary(sprint=sprint)

    async def sprint_plan(
        self, sprint_name: str, goal_ids: list[str],
    ) -> SkillResult:
        """Assign goals to a sprint (batch update)."""
        results: list[dict] = []
        for gid in goal_ids:
            try:
                resp = await self._request_with_retry("PATCH", f"/goals/{gid}", json={
                    "sprint": sprint_name,
                    "board_column": "todo",
                })
                results.append({"goal_id": gid, "success": True})
            except Exception as e:
                results.append({"goal_id": gid, "success": False, "error": str(e)})
        return SkillResult.ok({"sprint": sprint_name, "assigned": results})

    async def update_sprint(
        self, goal_id: str, board_column: str, position: int = 0,
    ) -> SkillResult:
        """Move a goal within a sprint board (alias for move_goal)."""
        return await self.move_goal(
            goal_id=goal_id, board_column=board_column, position=position,
        )

    # -- Hourly Goals convenience --------------------------------------------

    async def set_hourly_goal(
        self,
        hour: int,
        goal: str,
        priority: str = "normal",
    ) -> SkillResult:
        """Set an hourly goal."""
        try:
            resp = await self._request_with_retry("POST", "/hourly-goals", json={
                "hour": hour,
                "goal": goal,
                "priority": priority,
                "status": "pending",
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to set hourly goal: {e}")

    async def complete_hourly_goal(self, goal_id: str) -> SkillResult:
        """Mark an hourly goal as completed."""
        try:
            resp = await self._request_with_retry("PATCH", f"/hourly-goals/{goal_id}", json={
                "status": "completed",
            })
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to complete hourly goal: {e}")

    # -- Social CRUD completions ---------------------------------------------

    async def update_social_post(
        self, post_id: str, data: dict,
    ) -> SkillResult:
        """Update a social post."""
        try:
            resp = await self._request_with_retry("PUT", f"/social/{post_id}", json=data)
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to update social post: {e}")

    async def delete_social_post(self, post_id: str) -> SkillResult:
        """Delete a social post."""
        try:
            resp = await self._request_with_retry("DELETE", f"/social/{post_id}")
            return SkillResult.ok(resp.json())
        except Exception as e:
            return SkillResult.fail(f"Failed to delete social post: {e}")


# Singleton instance for convenience
_client: AriaAPIClient | None = None


async def get_api_client() -> AriaAPIClient:
    """Get or create the API client singleton."""
    global _client
    if _client is None:
        config = SkillConfig(name="api_client", config={})
        _client = AriaAPIClient(config)
        await _client.initialize()
    return _client
