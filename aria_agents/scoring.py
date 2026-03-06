# aria_agents/scoring.py
"""
Pheromone-inspired agent scoring with persistence.

Score formula: success_rate * 0.6 + speed_score * 0.3 + cost_score * 0.1
Decay factor: 0.95 per day (recent performance matters more).
Cold start: 0.5 (neutral — don't penalize untested agents).

Enhanced with:
- Performance recording (in-memory + file persistence)
- Session survival via JSON checkpointing
- Automatic score updates after each agent invocation

Architecture note (A-01 — dual scoring):
    This module provides IN-MEMORY / FILE-backed pheromone scoring used by
    ``aria_agents.coordinator`` for fast, in-process agent-selection decisions.

    ``aria_engine.routing`` maintains a SEPARATE DB-backed pheromone table
    (``engine_agent_pheromones``) used for live routing weight updates that
    survive restarts across the engine process.

    Both layers are intentional:
    - scoring.py  → fast, in-memory, coordinator-scope decisions
    - routing.py  → persistent, DB-backed, cross-restart routing memory

    Scores CAN diverge after a restart (file-backed scores reload, DB scores
    are independent). Unification is a future sprint item (requires schema
    migration + coordinator refactor to delegate to routing.py).
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria.scoring")

DECAY_FACTOR = 0.95
WEIGHTS = {"success": 0.6, "speed": 0.3, "cost": 0.1}
COLD_START_SCORE = 0.5

# Where to persist scores across restarts
_SCORES_FILE = "pheromone_scores.json"
_MEMORIES_PATH = os.environ.get("ARIA_MEMORIES_PATH", "/app/aria_memories")


def compute_pheromone(records: list[dict]) -> float:
    """Compute pheromone score from performance records.

    Args:
        records: List of dicts with keys: success (bool), speed_score (float 0-1),
                 cost_score (float 0-1), created_at (datetime).

    Returns:
        Float score between 0.0 and 1.0.
    """
    if not records:
        return COLD_START_SCORE

    score = 0.0
    weight_sum = 0.0
    now = datetime.now(timezone.utc)

    for r in records:
        created = r.get("created_at", now)
        if isinstance(created, str):
            # Handle ISO format strings
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_days = max((now - created).total_seconds() / 86400, 0)
        decay = DECAY_FACTOR ** age_days

        s = (
            float(r.get("success", False)) * WEIGHTS["success"]
            + r.get("speed_score", 0.5) * WEIGHTS["speed"]
            + r.get("cost_score", 0.5) * WEIGHTS["cost"]
        )
        score += s * decay
        weight_sum += decay

    return score / weight_sum if weight_sum > 0 else COLD_START_SCORE


def select_best_agent(
    candidates: list[str],
    scores: dict[str, float],
) -> str:
    """Select the best agent from candidates based on pheromone scores.

    Args:
        candidates: List of agent IDs to choose from.
        scores: Dict mapping agent_id -> pheromone score.

    Returns:
        Agent ID with the highest score. Falls back to first candidate.
    """
    if not candidates:
        raise ValueError("No candidate agents provided")

    return max(candidates, key=lambda a: scores.get(a, COLD_START_SCORE))


class PerformanceTracker:
    """
    Tracks agent performance across invocations and persists scores.
    
    This is what makes Aria learn which agents are best at which tasks.
    Scores survive restarts via JSON checkpointing to aria_memories/.
    """
    
    # Keep last N records per agent to bound memory
    _MAX_RECORDS_PER_AGENT = 200
    
    def __init__(self):
        self._records: dict[str, list[dict[str, Any]]] = {}
        self._scores: dict[str, float] = {}
        self._total_invocations = 0
        self._loaded = False
    
    def record(
        self,
        agent_id: str,
        success: bool,
        duration_ms: int,
        token_cost: float = 0.0,
        task_type: str = "general",
    ) -> float:
        """
        Record an agent's performance on a task.
        
        Args:
            agent_id: Which agent performed the task
            success: Did it succeed?
            duration_ms: How long it took
            token_cost: Token cost (normalized 0-1, lower is better)
            task_type: Category of task for future task-specific routing
            
        Returns:
            Updated pheromone score for this agent
        """
        # Compute normalized speed score (faster = higher, cap at 30s)
        speed_score = max(0.0, 1.0 - (duration_ms / 30000))
        
        # Compute normalized cost score (cheaper = higher)
        cost_score = max(0.0, 1.0 - min(token_cost, 1.0))
        
        record = {
            "success": success,
            "speed_score": round(speed_score, 3),
            "cost_score": round(cost_score, 3),
            "duration_ms": duration_ms,
            "task_type": task_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if agent_id not in self._records:
            self._records[agent_id] = []
        
        self._records[agent_id].append(record)
        self._total_invocations += 1
        
        # Trim old records
        if len(self._records[agent_id]) > self._MAX_RECORDS_PER_AGENT:
            self._records[agent_id] = self._records[agent_id][-self._MAX_RECORDS_PER_AGENT:]
        
        # Recompute score
        new_score = compute_pheromone(self._records[agent_id])
        self._scores[agent_id] = new_score
        
        logger.debug(
            f"Agent {agent_id}: {'✓' if success else '✗'} "
            f"({duration_ms}ms) → score={new_score:.3f}"
        )
        
        # Auto-persist every 10 invocations
        if self._total_invocations % 10 == 0:
            self.save()
        
        return new_score
    
    def get_score(self, agent_id: str) -> float:
        """Get current pheromone score for an agent."""
        return self._scores.get(agent_id, COLD_START_SCORE)
    
    def get_all_scores(self) -> dict[str, float]:
        """Get all agent scores."""
        return dict(self._scores)
    
    def get_best_agent(self, candidates: list[str]) -> str:
        """Select the best agent from candidates."""
        return select_best_agent(candidates, self._scores)
    
    def get_agent_stats(self, agent_id: str) -> dict[str, Any]:
        """Get detailed performance statistics for an agent."""
        records = self._records.get(agent_id, [])
        if not records:
            return {
                "agent_id": agent_id,
                "score": COLD_START_SCORE,
                "invocations": 0,
                "status": "untested",
            }
        
        successes = sum(1 for r in records if r["success"])
        avg_speed = sum(r["duration_ms"] for r in records) / len(records)
        
        return {
            "agent_id": agent_id,
            "score": round(self._scores.get(agent_id, COLD_START_SCORE), 3),
            "invocations": len(records),
            "successes": successes,
            "failures": len(records) - successes,
            "success_rate": round(successes / len(records), 3),
            "avg_duration_ms": round(avg_speed),
            "status": "proven" if len(records) > 10 else "learning",
        }
    
    def get_leaderboard(self) -> list[dict[str, Any]]:
        """Get all agents ranked by score."""
        all_agents = set(list(self._records.keys()) + list(self._scores.keys()))
        stats = [self.get_agent_stats(aid) for aid in all_agents]
        return sorted(stats, key=lambda x: x["score"], reverse=True)
    
    def save(self) -> bool:
        """Persist scores and recent records to disk."""
        try:
            # Try aria_memories path
            base = Path(_MEMORIES_PATH)
            if not base.exists():
                # Local dev fallback
                base = Path(__file__).parent.parent / "aria_memories"
            
            scores_dir = base / "knowledge"
            scores_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "total_invocations": self._total_invocations,
                "scores": self._scores,
                "records": {
                    # Save last 50 per agent for restart continuity
                    aid: recs[-50:] for aid, recs in self._records.items()
                },
            }
            
            filepath = scores_dir / _SCORES_FILE
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.info(f"Saved pheromone scores to {filepath}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save pheromone scores: {e}")
            return False
    
    def load(self) -> bool:
        """Load scores from disk (call during startup)."""
        if self._loaded:
            return True
        
        try:
            # Try aria_memories path first
            filepath = Path(_MEMORIES_PATH) / "knowledge" / _SCORES_FILE
            if not filepath.exists():
                filepath = Path(__file__).parent.parent / "aria_memories" / "knowledge" / _SCORES_FILE
            
            if not filepath.exists():
                logger.info("No saved pheromone scores found — starting fresh")
                self._loaded = True
                return True
            
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self._scores = data.get("scores", {})
            self._records = data.get("records", {})
            self._total_invocations = data.get("total_invocations", 0)
            self._loaded = True
            
            logger.info(
                f"Loaded pheromone scores: {len(self._scores)} agents, "
                f"{self._total_invocations} prior invocations"
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to load pheromone scores: {e}")
            self._loaded = True  # Don't retry
            return False


# Module-level singleton
_tracker: PerformanceTracker | None = None


def get_performance_tracker() -> PerformanceTracker:
    """Get or create the singleton performance tracker."""
    global _tracker
    if _tracker is None:
        _tracker = PerformanceTracker()
        _tracker.load()
    return _tracker
