"""
Focus Skill — Aria focus profile introspection and self-activation.

Tools:
    focus__list        List all enabled profiles (id, name, level, budget, tone)
    focus__get         Full details for one focus_id  (omits addon body → saves ~1500 tokens)
    focus__activate    PATCH agent focus_type + return confirmation
    focus__status      Return current focus_type + status for agent

Token cost targets:
    focus__list     <= 80 tokens output    (compact, 8 profiles)
    focus__get      <= 250 tokens output   (no addon text)
    focus__activate <= 50 tokens output    (confirmation only)
    focus__status   <= 30 tokens output    (2-field dict)
"""
from __future__ import annotations

import os
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

ARIA_API_BASE = os.environ.get("ARIA_API_URL", "http://aria-api:8000/api")
LEVEL_NAMES = {1: "L1-Orchestrator", 2: "L2-Specialist", 3: "L3-Ephemeral"}


@SkillRegistry.register
class FocusSkill(BaseSkill):
    """
    Focus profile introspection and self-activation.
    Aria can list, inspect, and switch her own focus_type mid-session.
    """

    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._http = None

    @property
    def name(self) -> str:
        return "focus"

    async def initialize(self) -> bool:
        try:
            import httpx
            self._http = httpx.AsyncClient(
                base_url=ARIA_API_BASE,
                timeout=15.0,
            )
            self._status = SkillStatus.AVAILABLE
            return True
        except ImportError:
            self.logger.error("httpx not installed — focus skill unavailable")
            self._status = SkillStatus.UNAVAILABLE
            return False

    async def shutdown(self) -> None:
        if self._http:
            await self._http.aclose()

    async def health_check(self) -> SkillStatus:
        """Check if the API is reachable."""
        try:
            if self._http is None:
                return SkillStatus.UNAVAILABLE
            resp = await self._http.get("/engine/focus")
            if resp.status_code < 500:
                return SkillStatus.AVAILABLE
            return SkillStatus.UNAVAILABLE
        except Exception:
            return SkillStatus.UNAVAILABLE

    # ─────────────────────────── DISPATCH ────────────────────────────────────

    async def _run(self, action: str, **kwargs: Any) -> SkillResult:
        dispatch = {
            "focus__list":     self._list,
            "focus__get":      self._get,
            "focus__activate": self._activate,
            "focus__status":   self._status_check,
        }
        handler = dispatch.get(action)
        if handler is None:
            return SkillResult(
                success=False,
                data=None,
                error=f"Unknown focus action: {action}. Available: {sorted(dispatch)}",
            )
        return await handler(**kwargs)

    # ────────────────────────── focus__list ──────────────────────────────────

    async def _list(self, **_: Any) -> SkillResult:
        """
        List enabled focus profiles — compact output.
        Token cost target: <= 80 tokens.
        """
        resp = await self._http.get("/engine/focus")
        resp.raise_for_status()
        raw = resp.json()
        profiles = raw.get("profiles", raw) if isinstance(raw, dict) else raw

        compact = [
            {
                "id":     p["focus_id"],
                "name":   p.get("display_name") or p["focus_id"],
                "level":  LEVEL_NAMES.get(p.get("delegation_level", 2), "L2"),
                "budget": p.get("token_budget_hint", 0),
                "tone":   p.get("tone", ""),
            }
            for p in profiles
            if p.get("enabled", True)
        ]
        return SkillResult(success=True, data=compact)

    # ────────────────────────── focus__get ───────────────────────────────────

    async def _get(self, focus_id: str, **_: Any) -> SkillResult:
        """
        Full profile details — addon body omitted (applied invisibly by process()).
        Token cost target: <= 250 tokens.
        """
        resp = await self._http.get(f"/engine/focus/{focus_id}")
        if resp.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Focus '{focus_id}' not found. "
                                     "Use focus__list to see available profiles.")
        resp.raise_for_status()
        profile = resp.json()

        # Strip addon body — saves ~1500 tokens; agent receives it via process()
        summary = {k: v for k, v in profile.items() if k != "system_prompt_addon"}
        summary["addon_length"] = len(profile.get("system_prompt_addon") or "")
        return SkillResult(success=True, data=summary)

    # ────────────────────────── focus__activate ───────────────────────────────

    async def _activate(
        self,
        focus_id: str,
        agent_id: str | None = None,
        **_: Any,
    ) -> SkillResult:
        """
        Switch focus_type for an agent (default: ARIA_AGENT_ID env var or 'aria-main').

        1. Validates profile exists + is enabled.
        2. PATCHes the agent record via REST API.
        3. Returns confirmation.

        Cache refresh: S73's process() stale-cache guard detects the focus_type
        change on the very next LLM call and clears _focus_profile automatically.
        No explicit cache-bust endpoint needed.

        Token cost target: <= 50 tokens output.
        """
        target = agent_id or os.environ.get("ARIA_AGENT_ID", "aria-main")

        # Step 1: verify profile
        check = await self._http.get(f"/engine/focus/{focus_id}")
        if check.status_code == 404:
            return SkillResult(
                success=False, data=None,
                error=f"Focus profile '{focus_id}' not found. "
                      "Use focus__list to see available profiles.",
            )
        profile = check.json()
        if not profile.get("enabled", True):
            return SkillResult(
                success=False, data=None,
                error=f"Focus profile '{focus_id}' is disabled. Choose an active profile.",
            )

        # Step 2: PATCH agent
        patch = await self._http.patch(
            f"/engine/agents/{target}",
            json={"focus_type": focus_id},
        )
        if patch.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Agent '{target}' not found.")
        patch.raise_for_status()

        return SkillResult(
            success=True,
            data={
                "agent_id":     target,
                "focus_id":     focus_id,
                "token_budget": profile.get("token_budget_hint"),
                "level":        LEVEL_NAMES.get(profile.get("delegation_level", 2), "L2"),
                "message":      f"Focus switched to '{focus_id}'",
            },
        )

    # ────────────────────────── focus__status ─────────────────────────────────

    async def _status_check(
        self,
        agent_id: str | None = None,
        **_: Any,
    ) -> SkillResult:
        """
        Return current focus_type and status for an agent.
        Token cost target: <= 30 tokens output.
        """
        target = agent_id or os.environ.get("ARIA_AGENT_ID", "aria-main")
        resp = await self._http.get(f"/engine/agents/{target}")
        if resp.status_code == 404:
            return SkillResult(success=False, data=None,
                               error=f"Agent '{target}' not found.")
        resp.raise_for_status()
        agent = resp.json()
        return SkillResult(
            success=True,
            data={
                "agent_id":   target,
                "focus_type": agent.get("focus_type"),
                "status":     agent.get("status"),
            },
        )

    # ── Public aliases (so schema audit finds handlers by tool name) ─────────
    focus__list     = _list
    focus__get      = _get
    focus__activate = _activate
    focus__status   = _status_check
