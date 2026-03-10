# aria_mind/memory.py
"""
Memory Manager - Long-term storage and recall with consolidation.

Integrates with:
- API-backed data path (api_client-first) for persistent key-value memory
- Database adapter as fallback for legacy/emergency flows
- File-based storage for artifacts (research, plans, drafts, exports)

Enhanced with:
- Memory consolidation (short-term → long-term summarization)
- Pattern recognition across memories
- Importance-weighted recall
- Session checkpointing for continuity across restarts
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque, Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# File-based storage paths (inside container)
ARIA_MEMORIES_PATH = os.environ.get("ARIA_MEMORIES_PATH", "/app/aria_memories")
ARIA_REPO_PATH = os.environ.get("ARIA_REPO_PATH", "/root/repo/aria_memories")


class MemoryManager:
    """
    Aria's memory system - her ability to remember, learn, and grow.

    Handles:
    - Short-term context (in-memory deque)
    - Long-term storage (database)
    - Memory consolidation (short → long-term with summarization)
    - Pattern recognition (what does she think about most?)
    - File-based artifact storage
    - Session checkpointing for restart continuity
    """

    def __init__(self, db_skill: "DatabaseSkill" | None = None):
        self._db = db_skill
        self._max_short_term = 200  # Increased from 100 - she deserves more context
        self._short_term: deque = deque(maxlen=self._max_short_term)
        self._connected = False
        self.logger = logging.getLogger("aria.memory")

        # Consolidation tracking
        self._consolidation_count = 0
        self._last_consolidation: str | None = None
        self._category_frequency: Counter = Counter()
        self._important_memories: list[dict[str, Any]] = []  # High-value memories flagged for review

    def set_database(self, db_skill: "DatabaseSkill"):
        """Inject database skill."""
        self._db = db_skill

    async def connect(self) -> bool:
        """Connect to memory storage."""
        if self._db:
            try:
                await self._db.initialize()
                self._connected = self._db.is_available
                return self._connected
            except Exception as e:
                self.logger.error(f"Memory connection failed: {e}")
                return False

        # No database - use in-memory only
        self._connected = True
        self.logger.warning("No database - using in-memory storage only")
        return True

    async def disconnect(self):
        """Disconnect from storage."""
        if self._db:
            await self._db.close()
        self._connected = False

    # -------------------------------------------------------------------------
    # Short-term memory (conversation context)
    # -------------------------------------------------------------------------

    def remember_short(self, content: str, category: str = "context"):
        """Add to short-term memory with pattern tracking."""
        entry = {
            "content": content,
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._short_term.append(entry)  # deque auto-trims at maxlen
        self._category_frequency[category] += 1

    def recall_short(
        self,
        limit: int = 10,
        sort_by: str = "time",  # "time" | "importance"
        min_importance: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Get short-term memories with optional importance-based retrieval.
        
        Args:
            limit: Max memories to return
            sort_by: "time" for recency, "importance" for priority
            min_importance: Filter out memories below this score
        
        Returns:
            List of memory entries
        """
        memories = list(self._short_term)
        
        # Filter by minimum importance
        if min_importance > 0:
            memories = [m for m in memories if m.get("importance_score", 0) >= min_importance]
        
        # Sort appropriately
        if sort_by == "importance":
            memories.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
            return memories[:limit]
        # Default: time-based (already in order from deque)
        return memories[-limit:]

    def clear_short(self):
        """Clear short-term memory."""
        self._short_term.clear()

    # -------------------------------------------------------------------------
    # Long-term memory (database)
    # -------------------------------------------------------------------------

    async def remember(
        self,
        key: str,
        value: Any,
        category: str = "general",
    ) -> bool:
        """Store in long-term memory."""
        if not self._db:
            self.logger.warning("No database for long-term memory")
            return False

        result = await self._db.store_memory(key, value, category)
        return result.success

    async def recall(self, key: str) -> Any | None:
        """Recall from long-term memory."""
        if not self._db:
            return None

        result = await self._db.recall_memory(key)
        if result.success and result.data:
            return result.data.get("value")
        return None

    async def search(
        self,
        pattern: str,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search long-term memories."""
        if not self._db:
            return []

        result = await self._db.search_memories(pattern, category, limit)
        return result.data if result.success else []

    # -------------------------------------------------------------------------
    # Thoughts (internal monologue)
    # -------------------------------------------------------------------------

    async def log_thought(
        self,
        content: str,
        category: str = "reflection",
    ) -> bool:
        """Log an internal thought."""
        # Add to short-term
        self.remember_short(content, category)

        # Persist if database available
        if self._db:
            result = await self._db.log_thought(content, category)
            return result.success

        return True

    async def get_recent_thoughts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent thoughts."""
        if self._db:
            result = await self._db.get_recent_thoughts(limit)
            return result.data if result.success else []

        # Fall back to short-term
        return [
            m for m in self.recall_short(limit)
            if m.get("category") in ("reflection", "thought")
        ]

    # -------------------------------------------------------------------------
    # Memory Consolidation - Transform experiences into wisdom
    # -------------------------------------------------------------------------

    async def consolidate(self, llm_skill=None, extra_entries: list[dict] | None = None) -> dict[str, Any]:
        """
        Consolidate short-term memories into long-term knowledge.

        This is Aria's ability to learn - she reviews recent experiences,
        identifies patterns, extracts lessons, and stores them as
        persistent knowledge that survives restarts.

        Args:
            llm_skill: Optional LLM skill for intelligent summarization
            extra_entries: Additional entries (e.g. from DB activities/thoughts)
                           to include beyond the in-memory deque.

        Returns:
            Dict with consolidation results
        """
        entries = list(self._short_term)
        # Merge extra entries (from DB bridge) — deduplicate by content hash
        if extra_entries:
            seen = {e.get("content", "")[:120] for e in entries}
            for ext in extra_entries:
                key = ext.get("content", "")[:120]
                if key and key not in seen:
                    entries.append(ext)
                    seen.add(key)
        if len(entries) < 5:
            return {"consolidated": False, "reason": "Not enough memories to consolidate"}

        # Group by category
        by_category: dict[str, list[Dict]] = {}
        for entry in entries:
            cat = entry.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(entry)

        summaries = {}
        lessons = []

        for category, category_entries in by_category.items():
            if len(category_entries) < 3:
                continue

            # Extract key content
            contents = [e.get("content", "")[:200] for e in category_entries]

            # Try LLM-powered summarization
            summary = None
            if llm_skill and hasattr(llm_skill, 'generate'):
                try:
                    consolidation_prompt = (
                        f"Summarize these {len(contents)} '{category}' memories into "
                        f"2-3 key insights. Be concise:\n\n"
                        + "\n".join(f"- {c}" for c in contents[:15])
                    )
                    result = await llm_skill.generate(
                        prompt=consolidation_prompt,
                        system_prompt="You are Aria Blue's memory system. Extract key insights concisely.",
                    )
                    if result.success:
                        summary = result.data.get("text", "")
                except Exception as e:
                    self.logger.debug(f"LLM consolidation failed for {category}: {e}")

            # Structured fallback — extract meaningful content, not raw telemetry
            if not summary:
                # Filter out raw JSON/method telemetry, keep human-readable content
                meaningful = []
                for c in contents:
                    # Skip entries that are mostly JSON/method telemetry
                    if c.startswith("{") or "'method':" in c or "'duration_ms':" in c:
                        continue
                    # Keep entries with real content (goals, deliverables, reflections)
                    cleaned = c.strip()[:150]
                    if len(cleaned) > 20:
                        meaningful.append(cleaned)

                if meaningful:
                    summary = (
                        f"{len(category_entries)} events in '{category}'. "
                        f"Key content: {'; '.join(meaningful[:3])}"
                    )
                else:
                    summary = (
                        f"{len(category_entries)} events in '{category}' "
                        f"(telemetry/operational data)."
                    )

            summaries[category] = summary

            # Detect meaningful patterns — skip pure telemetry categories
            _telemetry_categories = {
                "browser.navigate", "goals.get_goal", "goals.list_goals",
                "health_check", "heartbeat", "cron_execution",
            }
            if len(category_entries) > 5 and category not in _telemetry_categories:
                lessons.append(
                    f"Significant focus on '{category}' ({len(category_entries)} events) — "
                    f"worth reviewing for optimization or pattern extraction."
                )

        # Store consolidated knowledge
        consolidation_key = f"consolidation:{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}"
        consolidation_data = {
            "summaries": summaries,
            "lessons": lessons,
            "entry_count": len(entries),
            "categories": dict(self._category_frequency.most_common(10)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Persist to long-term memory
        if self._db:
            await self.remember(consolidation_key, consolidation_data, "consolidation")

        # Save as file artifact for human visibility
        # ARIA-REV-106: Verify write before clearing (atomic consolidation)
        artifact_result = self.save_json_artifact(
            consolidation_data,
            f"consolidation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json",
            "knowledge",
            "consolidations",
        )
        if not artifact_result.get("success"):
            self.logger.error("Consolidation write failed — keeping short-term intact")
            return {"consolidated": False, "reason": "Artifact write failed"}

        self._consolidation_count += 1
        self._last_consolidation = datetime.now(timezone.utc).isoformat()

        # ── ARIA-REV-008: Promote high-importance entries before clearing ─
        # Entries with importance >= 0.6 are saved to deep/ storage so they
        # survive consolidation. This prevents lossy data loss of critical
        # memories that would otherwise be discarded by _short_term.clear().
        promoted = 0
        for entry in entries:
            score = entry.get("importance_score", 0)
            if not score:
                score = self.calculate_importance_score(
                    entry.get("content", ""), entry.get("category", "general")
                )
            if score >= 0.6:
                self.save_json_artifact(
                    entry,
                    f"promoted_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{promoted}.json",
                    "deep",
                    "promoted",
                )
                promoted += 1

        # Clear processed short-term entries to avoid re-consolidating the same data
        self._short_term.clear()
        self._category_frequency.clear()

        self.logger.info(
            f"🧠 Memory consolidation #{self._consolidation_count}: "
            f"{len(entries)} entries → {len(summaries)} summaries, "
            f"{len(lessons)} lessons, {promoted} high-importance promoted"
        )

        return {
            "consolidated": True,
            "entries_processed": len(entries),
            "summaries": summaries,
            "lessons": lessons,
            "consolidation_number": self._consolidation_count,
        }

    def get_patterns(self) -> dict[str, Any]:
        """
        Analyze memory patterns - what does Aria think about most?

        Returns insight into her cognitive patterns for self-awareness.
        """
        if not self._short_term:
            return {"patterns": [], "insight": "No memories yet."}

        entries = list(self._short_term)

        # Category distribution
        top_categories = self._category_frequency.most_common(5)

        # Time distribution (if we have timestamps)
        recent_count = 0
        old_count = 0
        now = datetime.now(timezone.utc)
        for entry in entries:
            ts = entry.get("timestamp", "")
            if ts:
                try:
                    entry_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_hours = (now - entry_time).total_seconds() / 3600
                    if age_hours < 1:
                        recent_count += 1
                    else:
                        old_count += 1
                except (ValueError, TypeError):
                    pass

        # Content length analysis
        content_lengths = [len(e.get("content", "")) for e in entries]
        avg_length = sum(content_lengths) / len(content_lengths) if content_lengths else 0

        insight_parts = []
        if top_categories:
            top_cat = top_categories[0][0]
            insight_parts.append(f"Most active area: '{top_cat}' ({top_categories[0][1]} entries)")
        if recent_count > old_count:
            insight_parts.append("Activity is accelerating - more recent memories than older ones")

        return {
            "total_memories": len(entries),
            "top_categories": dict(top_categories),
            "recent_activity": recent_count,
            "average_memory_length": round(avg_length),
            "consolidation_count": self._consolidation_count,
            "insight": ". ".join(insight_parts) if insight_parts else "Building patterns...",
        }

    # -------------------------------------------------------------------------
    # Memory Importance Scoring — Automatic priority detection
    # -------------------------------------------------------------------------
    
    # Keywords that indicate high importance
    _HIGH_IMPORTANCE_KEYWORDS = {
        "critical", "urgent", "important", "priority", "deadline",
        "error", "fail", "crash", "bug", "security", "vulnerable",
        "password", "secret", "key", "token", "credential",
        "must", "need to", "required", "essential", "vital",
        "remember", "don't forget", "note", "remind",
        "goal", "objective", "milestone", "target",
        "najia", "user", "human", "preference", "like", "dislike",
        # Work output signals — ensures real deliverables score high
        "implemented", "created", "delivered", "built", "deployed",
        "fixed", "resolved", "completed", "shipped", "wrote",
        "skill", "pipeline", "schema", "router", "endpoint",
        "progress", "achieved", "finished", "merged", "released",
    }
    
    # Patterns that suggest actionable items
    _ACTION_PATTERNS = [
        "todo", "to do", "task", "action item", "follow up",
        "check", "verify", "review", "update", "fix",
    ]
    
    def calculate_importance_score(self, content: str, category: str = "general") -> float:
        """
        Calculate importance score (0.0-1.0) for a memory.
        
        Scoring factors:
        - Keyword matches (critical, urgent, error, etc.)
        - User mentions (Najia, user preferences)
        - Actionable language (todo, task, fix)
        - Content length (very short or very long = less important)
        - Category bonuses (security, goals = higher)
        
        Returns:
            Float between 0.0 (low) and 1.0 (high importance)
        """
        if not content:
            return 0.0
        
        content_lower = content.lower()
        score = 0.0
        
        # 1. Keyword matching (up to 0.4 points)
        keyword_matches = sum(1 for kw in self._HIGH_IMPORTANCE_KEYWORDS if kw in content_lower)
        score += min(0.4, keyword_matches * 0.1)
        
        # 2. Action patterns (up to 0.2 points)
        action_matches = sum(1 for pat in self._ACTION_PATTERNS if pat in content_lower)
        score += min(0.2, action_matches * 0.1)
        
        # 3. Category bonuses (up to 0.25 points)
        category_scores = {
            "security": 0.2,
            "goal": 0.2,
            "goal_work": 0.25,
            "preference": 0.15,
            "error": 0.2,
            "critical": 0.2,
            "user": 0.15,
            "deliverable": 0.25,
            "work_cycle": 0.15,
            "reflection": 0.15,
        }
        score += category_scores.get(category.lower(), 0.0)
        
        # 4. Content length factor (optimal: 30-800 chars)
        length = len(content)
        if 30 <= length <= 800:
            score += 0.1  # Sweet spot
        elif length < 15 or length > 3000:
            score -= 0.05  # Too short or too long
        
        # 5. Exclamation marks (emotional weight, up to 0.1)
        exclamation_count = content.count("!")
        score += min(0.1, exclamation_count * 0.02)
        
        # Normalize to 0.0-1.0
        return max(0.0, min(1.0, score))
    
    def remember_with_score(
        self,
        content: str,
        category: str = "general",
        auto_flag_threshold: float = 0.7,
    ) -> dict[str, Any]:
        """
        Add to short-term memory with automatic importance scoring.
        
        Args:
            content: Memory content
            category: Memory category
            auto_flag_threshold: Auto-flag if score >= this (0.0-1.0)
        
        Returns:
            Dict with memory entry and computed score
        """
        score = self.calculate_importance_score(content, category)
        
        entry = {
            "content": content,
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "importance_score": round(score, 3),
            "auto_scored": True,
        }
        
        self._short_term.append(entry)
        self._category_frequency[category] += 1
        
        # Auto-flag high-importance memories
        if score >= auto_flag_threshold:
            self.flag_important(content, reason=f"auto-scored-high:{score:.2f}")
            entry["auto_flagged"] = True
        
        return {"entry": entry, "score": score}
    
    def get_high_importance_memories(
        self,
        threshold: float = 0.6,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get memories with importance score >= threshold."""
        scored = [
            m for m in self._short_term
            if m.get("importance_score", 0) >= threshold
        ]
        # Sort by score descending
        scored.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
        return scored[:limit]
    
    def flag_important(self, content: str, reason: str = "auto") -> None:
        """
        Flag a memory as important for future review.
        These are memories Aria should pay special attention to.
        """
        self._important_memories.append({
            "content": content[:500],
            "reason": reason,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        })
        # Keep bounded
        if len(self._important_memories) > 50:
            self._important_memories = self._important_memories[-50:]

    def get_important_memories(self) -> list[dict[str, Any]]:
        """Get flagged important memories."""
        return list(self._important_memories)

    # -------------------------------------------------------------------------
    # 3-Tier Memory: surface → medium → deep
    #
    # Surface: transient heartbeat state (1-beat TTL, auto-cleared)
    # Medium:  daily context & activity summaries (24h TTL)
    # Deep:    synthesized insights & patterns (permanent)
    # -------------------------------------------------------------------------

    def write_surface(self, beat_data: dict[str, Any]) -> dict[str, Any]:
        """
        Write transient state to surface memory.

        Called every heartbeat. Overwrites previous surface state.
        Surface memory is ephemeral — it captures the *current* beat snapshot.
        """
        filename = f"beat_{beat_data.get('beat_number', 0):06d}.json"
        return self.save_json_artifact(beat_data, filename, "surface")

    def clear_stale_surface(self, max_files: int = 20) -> int:
        """Remove old surface files, keeping only the most recent ones."""
        files = self.list_artifacts("surface", pattern="beat_*.json")
        removed = 0
        if len(files) > max_files:
            # files are sorted by modified desc — remove oldest
            for f in files[max_files:]:
                try:
                    Path(f["path"]).unlink()
                    removed += 1
                except Exception:
                    pass
        return removed

    def promote_to_medium(
        self,
        summary: dict[str, Any],
        date_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Promote aggregated surface data to medium-term memory.

        Called every 6 heartbeats (6-hour consolidation). Aggregates recent
        surface snapshots into a daily activity summary.
        """
        if not date_key:
            date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subfolder = date_key
        filename = f"summary_{datetime.now(timezone.utc).strftime('%H%M')}.json"
        return self.save_json_artifact(summary, filename, "medium", subfolder)

    def promote_to_deep(
        self,
        insight: dict[str, Any],
        category: str = "patterns",
    ) -> dict[str, Any]:
        """
        Promote validated insights to deep (permanent) memory.

        Called when patterns are detected across multiple medium summaries
        or when goals complete. Deep memory is append-only and permanent.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        filename = f"{category}_{ts}.json"
        return self.save_json_artifact(insight, filename, "deep", category)

    def get_surface_state(self) -> dict[str, Any] | None:
        """Get the most recent surface memory snapshot."""
        files = self.list_artifacts("surface", pattern="beat_*.json")
        if not files:
            return None
        result = self.load_json_artifact(files[0]["name"], "surface")
        return result.get("data") if result.get("success") else None

    def get_medium_summaries(self, date_key: str | None = None) -> list[dict]:
        """Get medium-term summaries for a given date."""
        if not date_key:
            date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        files = self.list_artifacts("medium", subfolder=date_key, pattern="summary_*.json")
        summaries = []
        for f in files:
            result = self.load_json_artifact(f["name"], "medium", date_key)
            if result.get("success") and result.get("data"):
                summaries.append(result["data"])
        return summaries

    async def checkpoint_short_term(self) -> dict[str, Any]:
        """
        Save short-term memory to disk for restart survival.
        Called during graceful shutdown.
        """
        entries = list(self._short_term)
        if not entries:
            return {"success": True, "entries": 0}

        return self.save_json_artifact(
            {
                "entries": entries[-50:],  # Last 50 for quick restore
                "patterns": dict(self._category_frequency.most_common(10)),
                "important": self._important_memories[-10:],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
            "short_term_checkpoint.json",
            "memory",
        )

    async def restore_short_term(self) -> int:
        """
        Restore short-term memory from checkpoint after restart.
        Returns number of entries restored.
        """
        result = self.load_json_artifact(
            "short_term_checkpoint.json",
            "memory",
        )
        if not result.get("success") or not result.get("data"):
            return 0

        data = result["data"]
        entries = data.get("entries", [])
        for entry in entries:
            self._short_term.append(entry)

        # Restore patterns
        patterns = data.get("patterns", {})
        for cat, count in patterns.items():
            self._category_frequency[cat] += count

        # Restore important memories
        self._important_memories.extend(data.get("important", []))

        self.logger.info(f"🧠 Restored {len(entries)} short-term memories from checkpoint")
        return len(entries)

    # -------------------------------------------------------------------------
    # File-based memory (aria_memories/)
    # For artifacts: research, plans, drafts, exports, etc.
    # -------------------------------------------------------------------------

    ALLOWED_CATEGORIES = frozenset({
        "archive", "deep", "drafts", "exports", "income_ops", "knowledge",
        "logs", "medium", "memory", "moltbook", "plans", "research",
        "skills", "surface",
    })

    def _get_memories_path(self) -> Path:
        """Get the aria_memories base path."""
        # Try dedicated mount first
        if Path(ARIA_MEMORIES_PATH).exists():
            return Path(ARIA_MEMORIES_PATH)
        # Fall back to repo mount
        if Path(ARIA_REPO_PATH).exists():
            return Path(ARIA_REPO_PATH)
        # Local development
        local = Path(__file__).parent.parent / "aria_memories"
        if local.exists():
            return local
        return Path(ARIA_MEMORIES_PATH)  # Default, may not exist

    def save_artifact(
        self,
        content: str,
        filename: str,
        category: str = "general",
        subfolder: str | None = None,
    ) -> dict[str, Any]:
        """
        Save a file artifact to aria_memories.

        Args:
            content: File content to write
            filename: Name of the file (e.g., "research_report.md")
            category: Folder category (logs, research, plans, drafts, exports)
            subfolder: Optional subfolder within category

        Returns:
            Dict with success status and file path
        """
        # Validate category against whitelist
        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. "
                f"Allowed: {sorted(self.ALLOWED_CATEGORIES)}"
            )
        # Guard against path traversal
        for segment in (category, subfolder or "", filename):
            if ".." in segment or segment.startswith("/"):
                raise ValueError(f"Path traversal detected in '{segment}'")

        base = self._get_memories_path()

        # Build path: aria_memories/<category>/<subfolder>/<filename>
        folder = base / category
        if subfolder:
            folder = folder / subfolder

        try:
            folder.mkdir(parents=True, exist_ok=True)
            filepath = folder / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            self.logger.info(f"Saved artifact: {filepath}")
            return {
                "success": True,
                "path": str(filepath),
                "relative": f"aria_memories/{category}/{subfolder}/{filename}" if subfolder else f"aria_memories/{category}/{filename}",
            }
        except Exception as e:
            self.logger.error(f"Failed to save artifact: {e}")
            return {"success": False, "error": str(e)}

    def load_artifact(
        self,
        filename: str,
        category: str = "general",
        subfolder: str | None = None,
    ) -> dict[str, Any]:
        """
        Load a file artifact from aria_memories.

        Returns:
            Dict with success status and content
        """
        base = self._get_memories_path()

        folder = base / category
        if subfolder:
            folder = folder / subfolder

        filepath = folder / filename

        try:
            if not filepath.exists():
                return {"success": False, "error": f"File not found: {filepath}"}

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            return {"success": True, "content": content, "path": str(filepath)}
        except Exception as e:
            self.logger.error(f"Failed to load artifact: {e}")
            return {"success": False, "error": str(e)}

    def list_artifacts(
        self,
        category: str = "general",
        subfolder: str | None = None,
        pattern: str = "*",
    ) -> list[dict[str, Any]]:
        """
        List artifacts in a category folder.

        Returns:
            List of file info dicts
        """
        base = self._get_memories_path()

        folder = base / category
        if subfolder:
            folder = folder / subfolder

        if not folder.exists():
            return []

        files = []
        for f in folder.glob(pattern):
            if f.is_file():
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

        return sorted(files, key=lambda x: x["modified"], reverse=True)

    def save_json_artifact(
        self,
        data: Any,
        filename: str,
        category: str = "exports",
        subfolder: str | None = None,
    ) -> dict[str, Any]:
        """Save structured data as JSON."""
        content = json.dumps(data, indent=2, default=str)
        if not filename.endswith(".json"):
            filename += ".json"
        return self.save_artifact(content, filename, category, subfolder)

    def load_json_artifact(
        self,
        filename: str,
        category: str = "exports",
        subfolder: str | None = None,
    ) -> dict[str, Any]:
        """Load JSON artifact."""
        result = self.load_artifact(filename, category, subfolder)
        if result.get("success") and result.get("content"):
            try:
                result["data"] = json.loads(result["content"])
            except json.JSONDecodeError as e:
                result["success"] = False
                result["error"] = f"Invalid JSON: {e}"
        return result

    def get_status(self) -> dict[str, Any]:
        """Get memory system status with pattern awareness."""
        memories_path = self._get_memories_path()
        
        # Calculate importance score statistics
        scored_memories = [m for m in self._short_term if "importance_score" in m]
        high_importance = [m for m in scored_memories if m.get("importance_score", 0) >= 0.7]
        avg_score = (
            sum(m.get("importance_score", 0) for m in scored_memories) / len(scored_memories)
            if scored_memories else 0.0
        )
        
        return {
            "connected": self._connected,
            "has_database": self._db is not None,
            "short_term_count": len(self._short_term),
            "max_short_term": self._max_short_term,
            "file_storage": {
                "path": str(memories_path),
                "available": memories_path.exists(),
            },
            "consolidation_count": self._consolidation_count,
            "last_consolidation": self._last_consolidation,
            "important_memories_flagged": len(self._important_memories),
            "top_categories": dict(self._category_frequency.most_common(5)),
            "importance_scoring": {
                "scored_memories": len(scored_memories),
                "high_importance_count": len(high_importance),
                "average_score": round(avg_score, 3),
                "scoring_enabled": True,
            },
        }

    def __repr__(self):
        db_status = "db" if self._db else "memory-only"
        file_status = "files" if self._get_memories_path().exists() else "no-files"
        return (
            f"<MemoryManager: {db_status}, {file_status}, "
            f"{len(self._short_term)} short-term, "
            f"{self._consolidation_count} consolidations>"
        )
