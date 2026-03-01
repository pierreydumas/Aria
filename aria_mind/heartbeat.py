# aria_mind/heartbeat.py
"""
Heartbeat - Lifecycle, health monitoring, and autonomous action.

More than just a health check — this is Aria's pulse of autonomous behavior.
Every beat is an opportunity to:
- Monitor health and self-heal failing subsystems
- Work on active goals
- Trigger memory consolidation
- Reflect on recent experiences
- Grow confidence through consistent operation
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aria_mind import AriaMind


class Heartbeat:
    """
    Aria's heartbeat — keeps her alive, healthy, AND productive.
    
    Responsibilities:
    - Periodic health checks with self-healing
    - Goal progress on every beat
    - Memory consolidation triggers
    - Periodic reflection scheduling
    - Subsystem reconnection on failure
    """
    
    def __init__(self, mind: "AriaMind"):
        self._mind = mind
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_beat: datetime | None = None
        self._beat_count = 0
        self._interval = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "3600"))
        self._health_status: dict[str, Any] = {}
        self.logger = logging.getLogger("aria.heartbeat")
        
        # Self-healing state
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5
        self._subsystem_health: dict[str, bool] = {
            "soul": False,
            "memory": False,
            "cognition": False,
        }
        
        # Autonomous action scheduling (1 beat = 1 hour)
        self._beats_since_reflection = 0
        self._beats_since_consolidation = 0
        self._beats_since_goal_check = 0
        self._beats_since_maintenance = 0
        self._reflection_interval = 6      # every 6 beats = 6hr (matches six_hour_review cron)
        self._consolidation_interval = 6   # every 6 beats = 6hr (surface→medium promotion)
        self._goal_check_interval = 1      # every beat = 1hr (matches hourly_goal_check cron)
        self._maintenance_interval = 24    # every 24 beats = 24hr (daily autonomous maintenance)
    
    async def _get_focus_level(self) -> str:
        """
        Read active_focus_level from memory store.
        Returns 'L1', 'L2', or 'L3'. Defaults to 'L2' on error or missing key.

        L1 = shallow (local model, no sub-agents, 1 goal)
        L2 = standard (free cloud, max 2 sub-agents, 3 goals)  <- default
        L3 = deep (free cloud, roundtable eligible, 5 goals)
        """
        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                return "L2"
            result = await api.get_memory(key="active_focus_level")
            level = (result or {}).get("value", "L2")
            if level not in ("L1", "L2", "L3"):
                return "L2"
            return level
        except Exception:
            return "L2"  # safe default on any failure

    # Focus routing config — defines limits per level
    FOCUS_ROUTING: dict = {
        "L1": {"max_goals": 1, "sub_agents": False, "roundtable": False},
        "L2": {"max_goals": 3, "sub_agents": True,  "roundtable": False},
        "L3": {"max_goals": 5, "sub_agents": True,  "roundtable": True},
    }

    @property
    def is_healthy(self) -> bool:
        """Check if heartbeat is functioning."""
        if not self._running:
            return False
        
        if self._last_beat is None:
            return False
        
        # Unhealthy if no beat in 2x interval
        elapsed = (datetime.now(timezone.utc) - self._last_beat).total_seconds()
        return elapsed < (self._interval * 2)
    
    async def start(self):
        """Start the heartbeat loop."""
        if self._running:
            return
        
        self._running = True
        self.logger.info("💓 Heartbeat started — Aria is alive")
        
        # Start background task with reference
        self._task = asyncio.create_task(self._beat_loop())
    
    async def stop(self):
        """Stop the heartbeat."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("💔 Heartbeat stopped")
    
    async def _beat_loop(self):
        """Main heartbeat loop with error recovery."""
        while self._running:
            try:
                await self._beat()
                self._consecutive_failures = 0
            except Exception as e:
                self._consecutive_failures += 1
                self.logger.error(
                    f"Beat failed ({self._consecutive_failures}/"
                    f"{self._max_consecutive_failures}): {e}"
                )
                
                # Self-healing: if too many failures, try to recover
                if self._consecutive_failures >= self._max_consecutive_failures:
                    self.logger.warning("⚠️ Too many consecutive failures — attempting self-heal")
                    await self._self_heal()
                    self._consecutive_failures = 0
            
            await asyncio.sleep(self._interval)
    
    async def _beat(self):
        """
        Single heartbeat cycle — monitor + act.
        
        Every beat Aria:
        1. Checks all subsystem health
        2. Attempts self-healing for failed subsystems
        3. Works on goals (every 5 beats)
        4. Triggers reflection (every 30 beats)
        5. Triggers memory consolidation (every 60 beats)
        """
        from aria_mind.logging_config import correlation_id_var, new_correlation_id
        correlation_id_var.set(new_correlation_id())

        self._last_beat = datetime.now(timezone.utc)
        self._beat_count += 1
        
        # 1. Collect health status
        self._subsystem_health = {
            "soul": self._mind.soul is not None and getattr(self._mind.soul, '_loaded', False),
            "memory": self._mind.memory is not None and self._mind.memory._connected,
            "cognition": self._mind.cognition is not None,
        }
        
        self._health_status = {
            "timestamp": self._last_beat.isoformat(),
            "beat_number": self._beat_count,
            "subsystems": dict(self._subsystem_health),
            "all_healthy": all(self._subsystem_health.values()),
        }
        
        # Log to DB via api_client (replaces startup.py raw SQL)
        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if api:
                await api.create_activity(
                    action="heartbeat",
                    skill="system",
                    details=self._health_status,
                    success=True,
                )
                # Also record to heartbeat_log table
                try:
                    await api.create_heartbeat(
                        beat_number=self._beat_count,
                        status="healthy" if self._health_status.get("all_healthy") else "unhealthy",
                        details=self._health_status,
                    )
                except Exception:
                    pass  # heartbeat_log is supplementary, don't fail the main loop
        except Exception as e:
            self.logger.debug(f"Heartbeat DB log failed: {e}")

        # 2. Write surface memory (transient heartbeat state)
        await self._write_surface_memory()

        # 3. Self-heal any failed subsystems
        for subsystem, healthy in self._subsystem_health.items():
            if not healthy:
                self.logger.warning(f"⚠️ Subsystem '{subsystem}' unhealthy — attempting recovery")
                await self._heal_subsystem(subsystem)
        
        # 4. Goal work (every beat = per GOALS.md cycle)
        self._beats_since_goal_check += 1
        if self._beats_since_goal_check >= self._goal_check_interval:
            self._beats_since_goal_check = 0
            await self._check_goals()
        
        # 5. Periodic reflection (every 6 beats)
        self._beats_since_reflection += 1
        if self._beats_since_reflection >= self._reflection_interval:
            self._beats_since_reflection = 0
            await self._trigger_reflection()
        
        # 6. Memory consolidation: surface → medium (every 6 beats)
        #    Also triggers medium → deep when patterns emerge
        self._beats_since_consolidation += 1
        if self._beats_since_consolidation >= self._consolidation_interval:
            self._beats_since_consolidation = 0
            await self._trigger_consolidation()
        
        # 7. Clean stale surface files (keep last 20)
        if self._mind.memory and self._beat_count % 10 == 0:
            try:
                removed = self._mind.memory.clear_stale_surface(max_files=20)
                if removed:
                    self.logger.debug(f"🧹 Cleared {removed} stale surface files")
            except Exception:
                pass

        # 8. Autonomous maintenance (every 24 beats = daily)
        #    Non-destructive only: archive, compress, vacuum — never hard-delete
        self._beats_since_maintenance += 1
        if self._beats_since_maintenance >= self._maintenance_interval:
            self._beats_since_maintenance = 0
            await self._autonomous_maintenance()
        
        self.logger.debug(f"💓 Beat #{self._beat_count} — all systems nominal")
    
    async def _heal_subsystem(self, subsystem: str) -> bool:
        """Attempt to reconnect/reload a failed subsystem."""
        try:
            if subsystem == "memory" and self._mind.memory:
                success = await self._mind.memory.connect()
                if success:
                    self.logger.info(f"✅ Memory reconnected")
                return success
                
            elif subsystem == "soul" and self._mind.soul:
                if not getattr(self._mind.soul, '_loaded', False):
                    await self._mind.soul.load()
                    self.logger.info(f"✅ Soul reloaded")
                    return True
                
            elif subsystem == "cognition":
                if self._mind.cognition is None and self._mind.soul and self._mind.memory:
                    from aria_mind.cognition import Cognition
                    self._mind.cognition = Cognition(
                        soul=self._mind.soul,
                        memory=self._mind.memory,
                    )
                    self.logger.info(f"✅ Cognition reconstructed")
                    return True
                    
        except Exception as e:
            self.logger.error(f"Failed to heal {subsystem}: {e}")
        
        return False
    
    async def _self_heal(self) -> None:
        """Emergency self-healing — try to recover all subsystems."""
        self.logger.warning("🔧 Running emergency self-heal cycle...")
        for subsystem in ["memory", "soul", "cognition"]:
            if not self._subsystem_health.get(subsystem, False):
                await self._heal_subsystem(subsystem)

    async def _autonomous_maintenance(self) -> None:
        """
        Autonomous non-destructive maintenance — runs daily.

        Policy: Non-destructive = Autonomous. Destructive = Consent.
        All operations here archive/compress/vacuum — never hard-delete.
        """
        self.logger.info("🔧 Starting autonomous maintenance cycle...")
        results: dict[str, Any] = {"beat": self._beat_count, "actions": []}

        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                self.logger.debug("Autonomous maintenance skipped: api_client unavailable")
                self._write_degraded_log("autonomous_maintenance", "api_client_unavailable")
                return
        except Exception as e:
            self.logger.debug(f"Autonomous maintenance skipped: {e}")
            return

        # 1. Session archiving — archive stale sessions (>24h idle)
        try:
            session_result = await api.post(
                "/api/agent-manager/prune-stale-sessions",
                json={"max_age_hours": 24},
            )
            pruned = session_result.get("pruned", 0) if isinstance(session_result, dict) else 0
            results["actions"].append({"op": "session_archive", "pruned": pruned})
            if pruned:
                self.logger.info(f"🗂️ Archived {pruned} stale sessions (>24h)")
        except Exception as e:
            self.logger.debug(f"Session archiving skipped: {e}")

        # 2. Activity compression — archive activities >7 days old
        try:
            compress_result = await api.post(
                "/api/admin/maintenance",
                json={"operation": "vacuum", "tables": ["activity_log"]},
            )
            results["actions"].append({"op": "activity_vacuum", "result": "ok"})
            self.logger.info("📊 Activity table vacuumed")
        except Exception as e:
            self.logger.debug(f"Activity vacuum skipped: {e}")

        # 3. Semantic memory dedup (non-destructive — marks dupes, keeps originals)
        try:
            dedup_result = await api.post(
                "/api/admin/maintenance",
                json={"operation": "vacuum", "tables": ["semantic_memories"]},
            )
            results["actions"].append({"op": "semantic_vacuum", "result": "ok"})
            self.logger.info("🧠 Semantic memories vacuumed")
        except Exception as e:
            self.logger.debug(f"Semantic vacuum skipped: {e}")

        # 4. Log the maintenance activity
        try:
            await api.create_activity(
                action="autonomous_maintenance",
                skill="heartbeat",
                details=results,
                success=True,
            )
        except Exception:
            pass

        self.logger.info(
            f"🔧 Autonomous maintenance complete: {len(results['actions'])} actions"
        )

    async def _emergency_maintenance(self) -> None:
        """
        Emergency maintenance triggered by resource thresholds.
        Called from _beat() when thresholds are exceeded.
        Non-destructive only — archive/compress/evict caches.
        """
        self.logger.warning("⚡ Emergency maintenance triggered by resource pressure")

        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                return
        except Exception:
            return

        # Emergency session pruning (>6h idle when >50 sessions)
        try:
            stats = await api.get("/api/agent-manager/session-stats")
            active = (stats or {}).get("active_sessions", 0) if isinstance(stats, dict) else 0
            if active > 50:
                await api.post(
                    "/api/agent-manager/prune-stale-sessions",
                    json={"max_age_hours": 6},
                )
                self.logger.warning(f"⚡ Emergency pruned sessions (had {active} active, >50 threshold)")
        except Exception as e:
            self.logger.debug(f"Emergency session prune failed: {e}")

        # Force memory consolidation
        await self._trigger_consolidation()

    async def _check_goals(self) -> None:
        """Execute one concrete goal-work step per cycle, scaled by focus level."""
        if not self._mind.cognition or not self._mind.cognition._skills:
            return

        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if not api:
                self.logger.debug("Goal check skipped: api_client unavailable (CB open?)")
                self._write_degraded_log("_check_goals", "api_client_unavailable")
                return
        except Exception as e:
            self.logger.debug(f"Goal check skipped: api_client error {e}")
            return

        focus_level = await self._get_focus_level()
        focus_cfg = self.FOCUS_ROUTING.get(focus_level, self.FOCUS_ROUTING["L2"])
        max_goals = focus_cfg["max_goals"]
        progress_step = {"L1": 5, "L2": 10, "L3": 15}.get(focus_level, 10)
        memory_seed_limit = {"L1": 20, "L2": 50, "L3": 100}.get(focus_level, 50)

        self.logger.debug(f"\U0001f493 Goal cycle — focus={focus_level}, candidates={max_goals}")

        def _normalize_goal_list(payload: Any) -> list[dict[str, Any]]:
            if isinstance(payload, list):
                return [g for g in payload if isinstance(g, dict)]
            if isinstance(payload, dict):
                if isinstance(payload.get("next_actions"), list):
                    return [g for g in payload["next_actions"] if isinstance(g, dict)]
                if isinstance(payload.get("items"), list):
                    return [g for g in payload["items"] if isinstance(g, dict)]
                if isinstance(payload.get("goals"), list):
                    return [g for g in payload["goals"] if isinstance(g, dict)]
            return []

        def _parse_due(goal: dict[str, Any]) -> datetime:
            raw_due = goal.get("due_date") or goal.get("target_date")
            if not raw_due or not isinstance(raw_due, str):
                return datetime.max.replace(tzinfo=timezone.utc)
            try:
                parsed = datetime.fromisoformat(raw_due.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                return datetime.max.replace(tzinfo=timezone.utc)

        try:
            goals_result = await api.get_goals(status="in_progress", limit=max_goals)
            if not goals_result.success:
                goals_result = await api.get_goals(status="active", limit=max_goals)

            goals = _normalize_goal_list(goals_result.data)
            if not goals:
                self.logger.debug("Goal cycle: no in-progress goals found")
                return

            prioritized = sorted(
                goals,
                key=lambda g: (
                    _parse_due(g),
                    int(g.get("priority", 3) or 3),
                    -float(g.get("progress", 0) or 0),
                ),
            )
            goal = prioritized[0]

            goal_ref = str(goal.get("goal_id") or goal.get("id") or "").strip()
            if not goal_ref:
                self.logger.debug("Goal cycle skipped: selected goal has no id")
                return

            current_progress = int(float(goal.get("progress", 0) or 0))
            next_progress = min(100, current_progress + progress_step)

            await api.move_goal(goal_id=goal_ref, board_column="doing", position=0)
            await api.update_goal(goal_id=goal_ref, progress=next_progress)

            if next_progress >= 100:
                await api.update_goal(goal_id=goal_ref, status="completed", progress=100)
                await api.move_goal(goal_id=goal_ref, board_column="done", position=0)

            activity_details = {
                "goal_id": goal_ref,
                "title": goal.get("title"),
                "focus_level": focus_level,
                "progress_before": current_progress,
                "progress_after": next_progress,
                "action": "heartbeat_goal_step",
                "completed": next_progress >= 100,
            }
            await api.create_activity(
                action="goal_work",
                skill="heartbeat",
                details=activity_details,
                success=True,
            )

            seed_result = await api.seed_memories(limit=memory_seed_limit, skip_existing=True)
            if not seed_result.success:
                self.logger.debug(f"Goal cycle memory seed skipped: {seed_result.error}")

            self.logger.info(
                f"\U0001f3af Goal work [{focus_level}] {goal_ref}: "
                f"{current_progress}% → {next_progress}%"
            )
        except Exception as e:
            self.logger.debug(f"Goal check skipped: {e}")

    def _write_degraded_log(self, cycle: str, reason: str) -> None:
        """Write a degraded-mode log to aria_memories/logs/ when API is unavailable."""
        import json
        from pathlib import Path
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        log_dir = Path("aria_memories/logs")
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{cycle}_{ts}.json"
            log_file.write_text(json.dumps({
                "status": "degraded",
                "reason": reason,
                "cycle": cycle,
                "action": "halted",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception:
            pass  # File write failure shouldn't crash the heartbeat
    
    async def _trigger_reflection(self) -> None:
        """
        Trigger reflection cycle — six_hour_review equivalent.
        At L3: trigger roundtable (analyst + creator + devops) via engine API.
        At L2/L1: standard single-agent cognition.reflect() (existing behaviour).
        """
        if not self._mind.cognition:
            return

        focus_level = await self._get_focus_level()

        if focus_level == "L3":
            # L3: roundtable for comprehensive six_hour_review
            try:
                from aria_skills.api_client import get_api_client
                api = await get_api_client()
                if api:
                    result = await api.post(
                        "/engine/roundtable",
                        json={
                            "topic": "6-hour system review: goals, content, health, errors",
                            "agent_ids": ["analyst", "creator", "devops"],
                            "rounds": 1,
                            "timeout": 240,
                        },
                    )
                    self.logger.info(
                        f"\U0001f3af Roundtable six_hour_review dispatched "
                        f"(focus=L3): session_id={result.get('session_id', '?')}"
                    )
                    return
            except Exception as e:
                self.logger.warning(f"Roundtable dispatch failed, falling back to reflect(): {e}")

        # L1/L2 (or L3 fallback): standard reflection
        try:
            reflection = await self._mind.cognition.reflect()
            self.logger.info(f"\U0001fa9e Reflection complete [focus={focus_level}] ({len(reflection)} chars)")
        except Exception as e:
            self.logger.debug(f"Reflection skipped: {e}")
    
    async def _write_surface_memory(self) -> None:
        """Write transient heartbeat state to surface memory tier."""
        if not self._mind.memory:
            return

        try:
            surface_data = {
                "timestamp": self._last_beat.isoformat() if self._last_beat else None,
                "beat_number": self._beat_count,
                "subsystems": dict(self._subsystem_health),
                "all_healthy": all(self._subsystem_health.values()),
                "short_term_count": len(self._mind.memory._short_term),
                "important_memories": len(self._mind.memory._important_memories),
                "top_categories": dict(self._mind.memory._category_frequency.most_common(5)),
                "autonomous_actions": {
                    "next_goal_check_in": self._goal_check_interval - self._beats_since_goal_check,
                    "next_reflection_in": self._reflection_interval - self._beats_since_reflection,
                    "next_consolidation_in": self._consolidation_interval - self._beats_since_consolidation,
                    "next_maintenance_in": self._maintenance_interval - self._beats_since_maintenance,
                },
            }
            self._mind.memory.write_surface(surface_data)
        except Exception as e:
            self.logger.debug(f"Surface memory write skipped: {e}")

    async def _trigger_consolidation(self) -> None:
        """
        Trigger memory consolidation across all tiers.

        1. Short-term → summaries (existing consolidation)
        2. Surface → medium (aggregate heartbeat snapshots into 6h summary)
        3. Medium → deep (when patterns detected across multiple summaries)
        """
        if not self._mind.memory:
            return
        
        try:
            # Get LLM skill for intelligent consolidation
            llm_skill = None
            if self._mind.cognition and self._mind.cognition._skills:
                llm_skill = (
                    self._mind.cognition._skills.get("litellm")
                    or self._mind.cognition._skills.get("llm")
                )
            
            # 1. Standard short-term → long-term consolidation
            result = await self._mind.memory.consolidate(llm_skill=llm_skill)
            if result.get("consolidated"):
                self.logger.info(
                    f"🧠 Memory consolidated: {result['entries_processed']} entries, "
                    f"{len(result.get('lessons', []))} lessons learned"
                )

            # 2. Surface → medium promotion
            await self._promote_surface_to_medium(result)

            # 3. Medium → deep promotion (check for patterns)
            await self._promote_medium_to_deep(result)

        except Exception as e:
            self.logger.debug(f"Consolidation skipped: {e}")

    async def _promote_surface_to_medium(self, consolidation_result: dict) -> None:
        """Aggregate recent surface snapshots into a medium-term summary."""
        if not self._mind.memory:
            return

        try:
            surface_files = self._mind.memory.list_artifacts("surface", pattern="beat_*.json")
            if not surface_files:
                return

            # Aggregate surface data
            beats_healthy = 0
            beats_total = len(surface_files)
            all_categories: dict[str, int] = {}

            for sf in surface_files[:20]:  # Last 20 beats max
                data = self._mind.memory.load_json_artifact(sf["name"], "surface")
                if data.get("success") and data.get("data"):
                    snap = data["data"]
                    if snap.get("all_healthy"):
                        beats_healthy += 1
                    for cat, count in snap.get("top_categories", {}).items():
                        all_categories[cat] = all_categories.get(cat, 0) + count

            medium_summary = {
                "period_beats": beats_total,
                "beats_healthy": beats_healthy,
                "health_rate": round(beats_healthy / max(beats_total, 1), 2),
                "top_categories": dict(sorted(
                    all_categories.items(), key=lambda x: x[1], reverse=True
                )[:10]),
                "consolidation": {
                    "entries_processed": consolidation_result.get("entries_processed", 0),
                    "lessons": consolidation_result.get("lessons", []),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self._mind.memory.promote_to_medium(medium_summary)
            self.logger.info(
                f"📊 Surface→Medium: {beats_total} beats, "
                f"{beats_healthy}/{beats_total} healthy"
            )
        except Exception as e:
            self.logger.debug(f"Surface→Medium promotion skipped: {e}")

    async def _promote_medium_to_deep(self, consolidation_result: dict) -> None:
        """Promote patterns from medium to deep memory when insights emerge."""
        if not self._mind.memory:
            return

        lessons = consolidation_result.get("lessons", [])
        if not lessons:
            return

        try:
            self._mind.memory.promote_to_deep(
                {
                    "lessons": lessons,
                    "source": "heartbeat_consolidation",
                    "beat_number": self._beat_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                category="patterns",
            )
            self.logger.info(f"🧬 Medium→Deep: {len(lessons)} patterns promoted")
        except Exception as e:
            self.logger.debug(f"Medium→Deep promotion skipped: {e}")
    
    def get_status(self) -> dict[str, Any]:
        """Get current health status with detailed telemetry."""
        return {
            "running": self._running,
            "healthy": self.is_healthy,
            "last_beat": self._last_beat.isoformat() if self._last_beat else None,
            "beat_count": self._beat_count,
            "consecutive_failures": self._consecutive_failures,
            "subsystems": self._subsystem_health,
            "autonomous_actions": {
                "next_goal_check_in": self._goal_check_interval - self._beats_since_goal_check,
                "next_reflection_in": self._reflection_interval - self._beats_since_reflection,
                "next_consolidation_in": self._consolidation_interval - self._beats_since_consolidation,
                "next_maintenance_in": self._maintenance_interval - self._beats_since_maintenance,
            },
            "details": self._health_status,
        }
    
    def __repr__(self):
        status = "healthy" if self.is_healthy else "unhealthy"
        return f"<Heartbeat: {status}, beats={self._beat_count}, failures={self._consecutive_failures}>"
