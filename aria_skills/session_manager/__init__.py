# aria_skills/session_manager/__init__.py
"""
Session management skill.

List, prune, and delete Aria engine sessions via the aria-api REST layer.
All session data lives in PostgreSQL (aria_engine.chat_sessions / chat_messages).

Tools:
  - list_sessions        — list active sessions (from DB via API)
  - delete_session       — delete a session + its messages
  - prune_sessions       — archive stale sessions (hidden from chat, kept for Aria)
  - get_session_stats    — summary statistics
  - list_archived_sessions — browse archived sessions (pruned from chat)
  - cleanup_after_delegation — delete a sub-agent session after completion
  - cleanup_orphans      — purge ghost sessions (0 messages, stale)
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class SessionManagerSkill(BaseSkill):
    """
    Manage Aria sessions — list, prune stale ones, delete by ID.

    All operations go through aria-api REST endpoints which read/write
    the PostgreSQL aria_engine schema (chat_sessions + chat_messages).
    """

    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._stale_threshold_minutes: int = int(
            config.config.get("stale_threshold_minutes", 60)
        )
        self._api = None

    @property
    def name(self) -> str:
        return "session_manager"

    async def initialize(self) -> bool:
        self._api = await get_api_client()
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Session manager initialized (DB-backed via aria-api)")
        return True

    async def health_check(self) -> SkillStatus:
        return self._status

    # ── Internal helpers ───────────────────────────────────────────

    async def _fetch_sessions(
        self,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch sessions from the engine sessions API (max 200 per API constraint)."""
        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "sort": "updated_at",
            "order": "desc",
        }
        result = await self._api.get("/engine/sessions", params=params)
        if not result.success:
            return []
        data = result.data if isinstance(result.data, dict) else {}
        return data.get("sessions", data.get("items", []))

    # ── Public tool functions ──────────────────────────────────────────

    @logged_method()
    async def list_sessions(self, agent: str = "", **kwargs) -> SkillResult:
        """
        List all active sessions from the database.

        Args:
            agent: Filter by agent_id (default: all agents).
        """
        agent = agent or kwargs.get("agent", "")
        try:
            sessions = await self._fetch_sessions()

            if agent:
                sessions = [s for s in sessions if s.get("agent_id") == agent]

            normalized = []
            for s in sessions:
                normalized.append({
                    "id": s.get("session_id") or s.get("id", ""),
                    "agent_id": s.get("agent_id", ""),
                    "session_type": s.get("session_type", "interactive"),
                    "status": s.get("status", "active"),
                    "title": s.get("title", ""),
                    "model": s.get("model", ""),
                    "message_count": s.get("message_count", 0),
                    "updated_at": s.get("updated_at") or s.get("last_message_at", ""),
                    "created_at": s.get("created_at", ""),
                })

            return SkillResult.ok({
                "session_count": len(normalized),
                "sessions": normalized,
            })
        except Exception as e:
            return SkillResult.fail(f"Error listing sessions: {e}")

    @logged_method()
    async def delete_session(self, session_id: str = "", agent: str = "", **kwargs) -> SkillResult:
        """
        Delete a session and all its messages from the database.

        Args:
            session_id: The session UUID to delete.
            agent: Unused (kept for backward compat).
        """
        if not session_id:
            session_id = kwargs.get("session_id", "")
        if not session_id:
            return SkillResult.fail("session_id is required")

        current_sid = os.environ.get("ARIA_SESSION_ID", "")
        if current_sid and session_id == current_sid:
            return SkillResult.fail(
                f"Cannot delete current session {session_id}: "
                "this would destroy the active conversation context."
            )

        try:
            result = await self._api.delete(f"/engine/sessions/{session_id}")
            if result.success:
                return SkillResult.ok({
                    "deleted": session_id,
                    "message": f"Session {session_id} deleted from database",
                })
            else:
                return SkillResult.fail(
                    f"Failed to delete session {session_id}: {result.error}"
                )
        except Exception as e:
            return SkillResult.fail(f"Error deleting session {session_id}: {e}")

    @logged_method()
    async def prune_sessions(
        self,
        max_age_minutes: int = 0,
        dry_run: bool = False,
        **kwargs,
    ) -> SkillResult:
        """
        Archive stale sessions older than threshold.

        Calls the bulk ``POST /engine/sessions/cleanup`` endpoint which archives
        all matching sessions + messages in a single DB transaction (atomic —
        no partial states, no per-session loop).
        Sessions are moved to archive tables — hidden from chat UI but
        still accessible to Aria via list_archived_sessions.

        Args:
            max_age_minutes: Archive sessions older than this (default: config value or 60).
            dry_run: If true, count candidates without archiving.
        """
        if not max_age_minutes:
            max_age_minutes = kwargs.get("max_age_minutes", self._stale_threshold_minutes)
            if isinstance(max_age_minutes, str):
                max_age_minutes = int(max_age_minutes) if max_age_minutes else self._stale_threshold_minutes

        dry_run = kwargs.get("dry_run", dry_run)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        max_age_minutes = int(max_age_minutes)
        # Convert minutes to hours for the bulk endpoint (keeps sub-hour precision via
        # the max_age_hours param which uses make_interval at hour granularity).
        # Round up so we never archive sessions younger than requested.
        import math
        max_age_hours = math.ceil(max_age_minutes / 60) if max_age_minutes >= 60 else None

        try:
            params: dict[str, Any] = {"dry_run": dry_run}
            if max_age_hours is not None:
                params["max_age_hours"] = max_age_hours
            else:
                # Sub-60-min threshold: fall back to days=1 with dry_run guard
                params["days"] = 1

            r = await self._api.post("/engine/sessions/cleanup", params=params)
            if not r.success:
                return SkillResult.fail(f"Cleanup endpoint error: {r.error}")

            data = r.data if isinstance(r.data, dict) else {}
            return SkillResult.ok({
                "pruned_count": data.get("pruned_count", 0),
                "archived_count": data.get("archived_count", 0),
                "message_count": data.get("message_count", 0),
                "zombies_closed": data.get("zombies_closed", 0),
                "dry_run": dry_run,
                "threshold_minutes": max_age_minutes,
            })
        except Exception as e:
            return SkillResult.fail(f"prune_sessions error: {e}")

    @logged_method()
    async def get_session_stats(self, **kwargs) -> SkillResult:
        """Get summary statistics about current sessions."""
        try:
            stats_resp = await self._api.get(
                "/sessions/stats",
                params={"include_runtime_events": True, "include_cron_events": True},
            )
            if not stats_resp.success:
                return SkillResult.fail(f"Error getting session stats: {stats_resp.error}")

            data = stats_resp.data if isinstance(stats_resp.data, dict) else {}
            return SkillResult.ok({
                "total_sessions": data.get("total_sessions", 0),
                "active_sessions": data.get("active_sessions", 0),
                "by_agent": data.get("by_agent", []),
                "by_type": data.get("by_type", []),
                "source": "engine_sessions_status",
            })
        except Exception as e:
            return SkillResult.fail(f"Error getting session stats: {e}")

    @logged_method()
    async def list_archived_sessions(self, agent: str = "", limit: int = 50, **kwargs) -> SkillResult:
        """
        List sessions that have been archived (pruned from chat but preserved).

        Archived sessions are no longer visible in the chat UI but Aria can
        browse them here for historical context, past conversations, and auditing.

        Args:
            agent: Filter by agent_id (default: all agents).
            limit: Max sessions to return (default 50, max 200).
        """
        agent = agent or kwargs.get("agent", "")
        if isinstance(limit, str):
            limit = int(limit) if limit else 50
        limit = min(limit, 200)

        try:
            params: dict[str, Any] = {"limit": limit}
            if agent:
                params["agent_id"] = agent

            result = await self._api.get("/engine/sessions/archived", params=params)
            if not result.success:
                return SkillResult.fail(f"Failed to fetch archived sessions: {result.error}")

            data = result.data if isinstance(result.data, dict) else {}
            sessions = data.get("sessions", [])

            return SkillResult.ok({
                "archived_count": len(sessions),
                "total": data.get("total", len(sessions)),
                "sessions": sessions,
            })
        except Exception as e:
            return SkillResult.fail(f"Error listing archived sessions: {e}")

    @logged_method()
    async def cleanup_after_delegation(self, session_id: str = "", **kwargs) -> SkillResult:
        """Clean up a session after a sub-agent delegation completes."""
        if not session_id:
            session_id = kwargs.get("session_id", "")
        if not session_id:
            return SkillResult.fail(
                "session_id is required — pass the ID of the completed delegation session"
            )
        return await self.delete_session(session_id=session_id)

    @logged_method()
    async def cleanup_orphans(self, dry_run: bool = False, **kwargs) -> SkillResult:
        """
        Clean up ghost sessions (0 messages, stale) from the database.

        Args:
            dry_run: If true, report what would be cleaned without doing it.
        """
        dry_run = kwargs.get("dry_run", dry_run)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        try:
            if dry_run:
                sessions = await self._fetch_sessions(limit=200)
                ghosts = [s for s in sessions if s.get("message_count", 0) == 0]
                return SkillResult.ok({
                    "dry_run": True,
                    "ghost_count": len(ghosts),
                    "ghosts": [
                        {
                            "id": s.get("session_id") or s.get("id", ""),
                            "agent_id": s.get("agent_id", ""),
                            "session_type": s.get("session_type", ""),
                            "created_at": s.get("created_at", ""),
                        }
                        for s in ghosts
                    ],
                })
            else:
                result = await self._api.delete(
                    "/engine/sessions/ghosts?older_than_minutes=15",
                )
                if result.success:
                    return SkillResult.ok({
                        "dry_run": False,
                        "deleted": result.data.get("deleted", 0) if isinstance(result.data, dict) else 0,
                        "message": "Ghost sessions purged",
                    })
                else:
                    return SkillResult.fail(f"Ghost cleanup failed: {result.error}")
        except Exception as e:
            return SkillResult.fail(f"Error cleaning up orphans: {e}")

    async def close(self):
        self._api = None
