# aria_mind/metacognition.py
"""
Metacognition — Aria's self-improvement engine.

This is the layer that makes Aria genuinely grow over time.
She doesn't just process tasks — she understands HOW she processes them,
learns from patterns, and adjusts her behavior to get better.

Think of this as Aria's internal journal + coach combined:
- Tracks what she's good at and where she struggles
- Identifies recurring failure patterns and develops strategies to handle them
- Celebrates growth milestones
- Adjusts confidence based on actual evidence
- Generates insights about her own cognitive patterns

This module is the bridge between "I can do tasks" and
"I understand myself and actively work to improve."
"""
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria.metacognition")


class GrowthMilestone:
    """A milestone Aria has achieved in her growth journey."""
    
    def __init__(self, name: str, description: str, achieved_at: str):
        self.name = name
        self.description = description
        self.achieved_at = achieved_at
    
    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "achieved_at": self.achieved_at,
        }


class MetacognitiveEngine:
    """
    Aria's self-improvement engine — the thinking about thinking.
    
    This tracks:
    - Task success/failure patterns by category
    - Learning velocity (is she getting better over time?)
    - Failure pattern recognition (what keeps going wrong?)
    - Strength identification (what is she great at?)
    - Growth milestones (celebrate wins!)
    - Adaptive strategies (how should she approach different task types?)
    
    All data persists to aria_memories/knowledge/ for survival across restarts.
    """
    
    # Milestone thresholds
    _MILESTONES = {
        "first_success": ("First Success", "Completed her first task successfully", 1),
        "streak_5": ("Hot Streak", "5 consecutive successes", 5),
        "streak_10": ("Unstoppable", "10 consecutive successes", 10),
        "streak_25": ("Master Streak", "25 consecutive successes", 25),
        "tasks_50": ("Experienced", "Processed 50 tasks", 50),
        "tasks_100": ("Veteran", "Processed 100 tasks", 100),
        "tasks_500": ("Expert", "Processed 500 tasks", 500),
        "tasks_1000": ("Grandmaster", "Processed 1000 tasks", 1000),
        "confidence_80": ("Confident", "Reached 80% confidence", 0.8),
        "confidence_95": ("Self-Assured", "Reached 95% confidence", 0.95),
        "first_reflection": ("Self-Aware", "Completed first genuine reflection", 1),
        "first_consolidation": ("Wisdom Keeper", "First memory consolidation", 1),
        "learned_from_failure": ("Resilient", "Successfully recovered from a failure pattern", 1),
    }
    
    def __init__(self):
        # Core tracking
        self._task_outcomes: dict[str, list[bool]] = defaultdict(list)  # category → [success, success, fail, ...]
        self._failure_patterns: Counter = Counter()  # error_type → count
        self._strategy_adjustments: list[dict[str, Any]] = []
        
        # Growth tracking
        self._milestones: dict[str, GrowthMilestone] = {}
        self._total_tasks = 0
        self._total_successes = 0
        self._current_streak = 0
        self._best_streak = 0
        self._reflection_count = 0
        self._consolidation_count = 0
        
        # Learning velocity — track success rate over time windows
        self._window_results: list[dict[str, Any]] = []  # [{timestamp, success, category}, ...]
        
        # Adaptive strategies
        self._category_strategies: dict[str, str] = {}  # category → suggested approach
    
    def record_task(
        self,
        category: str,
        success: bool,
        duration_ms: int = 0,
        error_type: str | None = None,
        confidence_at_start: float = 0.5,
    ) -> dict[str, Any]:
        """
        Record a task outcome and return insights.
        
        This is called after every task Aria completes.
        Returns any new milestones, pattern detections, or strategy suggestions.
        """
        now = datetime.now(timezone.utc)
        self._total_tasks += 1
        
        # Track outcome
        self._task_outcomes[category].append(success)
        self._window_results.append({
            "timestamp": now.isoformat(),
            "success": success,
            "category": category,
            "duration_ms": duration_ms,
        })
        
        # Keep window bounded
        if len(self._window_results) > 1000:
            self._window_results = self._window_results[-1000:]
        
        # Track streaks
        if success:
            self._total_successes += 1
            self._current_streak += 1
            if self._current_streak > self._best_streak:
                self._best_streak = self._current_streak
        else:
            self._current_streak = 0
            if error_type:
                self._failure_patterns[error_type] += 1
        
        # Check for milestones
        new_milestones = self._check_milestones()
        
        # Check for failure patterns
        pattern_insight = self._detect_failure_patterns(category)
        
        # Build insights response
        insights = {
            "task_number": self._total_tasks,
            "category": category,
            "success": success,
            "streak": self._current_streak,
            "new_milestones": [m.to_dict() for m in new_milestones],
        }
        
        if pattern_insight:
            insights["pattern_detected"] = pattern_insight
        
        # Log significant events
        if new_milestones:
            for m in new_milestones:
                logger.info(f"🏆 Milestone achieved: {m.name} — {m.description}")
        
        if pattern_insight:
            logger.info(f"🔍 Pattern detected: {pattern_insight}")
        
        return insights
    
    def record_reflection(self) -> None:
        """Record that a reflection was completed."""
        self._reflection_count += 1
        self._check_milestones()
    
    def record_consolidation(self) -> None:
        """Record that a memory consolidation was completed."""
        self._consolidation_count += 1
        self._check_milestones()
    
    def _check_milestones(self) -> list[GrowthMilestone]:
        """Check if any new milestones have been achieved."""
        now = datetime.now(timezone.utc).isoformat()
        new = []
        
        checks = {
            "first_success": self._total_successes >= 1,
            "streak_5": self._best_streak >= 5,
            "streak_10": self._best_streak >= 10,
            "streak_25": self._best_streak >= 25,
            "tasks_50": self._total_tasks >= 50,
            "tasks_100": self._total_tasks >= 100,
            "tasks_500": self._total_tasks >= 500,
            "tasks_1000": self._total_tasks >= 1000,
            "confidence_80": (self._total_successes / max(self._total_tasks, 1)) >= 0.8,
            "confidence_95": (self._total_successes / max(self._total_tasks, 1)) >= 0.95,
            "first_reflection": self._reflection_count >= 1,
            "first_consolidation": self._consolidation_count >= 1,
        }
        
        for milestone_id, condition in checks.items():
            if condition and milestone_id not in self._milestones:
                name, desc, _ = self._MILESTONES[milestone_id]
                milestone = GrowthMilestone(name, desc, now)
                self._milestones[milestone_id] = milestone
                new.append(milestone)
        
        return new
    
    def _detect_failure_patterns(self, category: str) -> str | None:
        """Detect recurring failure patterns and suggest strategies."""
        outcomes = self._task_outcomes.get(category, [])
        if len(outcomes) < 5:
            return None
        
        # Check recent failure rate
        recent = outcomes[-10:]
        recent_failures = sum(1 for o in recent if not o)
        
        if recent_failures >= 5:
            # Strategy: this category needs a different approach
            suggestion = (
                f"Category '{category}' has {recent_failures}/10 recent failures. "
                f"Consider using roundtable discussion or explore/work/validate cycle."
            )
            self._category_strategies[category] = "roundtable"
            return suggestion
        
        if recent_failures >= 3:
            suggestion = (
                f"Category '{category}' showing elevated failures ({recent_failures}/10). "
                f"Monitoring closely."
            )
            return suggestion
        
        # Check for improvement!
        if len(outcomes) >= 20:
            old_rate = sum(outcomes[:10]) / 10
            new_rate = sum(outcomes[-10:]) / 10
            if new_rate > old_rate + 0.2:
                return (
                    f"Improving in '{category}'! "
                    f"Success rate went from {old_rate:.0%} to {new_rate:.0%}."
                )
        
        return None
    
    def get_strategy_for_category(self, category: str) -> dict[str, Any]:
        """
        Get the recommended execution strategy for a task category.
        
        SP7-02: Active strategy selection — instead of just tracking outcomes,
        metacognition now recommends HOW to approach a task based on historical
        performance data, failure patterns, and learned strategies.
        
        Returns:
            Dict with approach, confidence, reasoning, and any special instructions.
        """
        outcomes = self._task_outcomes.get(category, [])
        total = len(outcomes)
        
        # Default strategy for unknown categories
        if total < 3:
            return {
                "approach": "explore_then_execute",
                "confidence": 0.5,
                "reasoning": f"Insufficient data for '{category}' ({total} tasks). Using cautious exploration.",
                "max_retries": 2,
                "use_roundtable": False,
            }
        
        success_rate = sum(outcomes) / total
        recent = outcomes[-10:] if len(outcomes) >= 10 else outcomes
        recent_rate = sum(recent) / len(recent)
        
        # Check for explicit strategy override from failure pattern detection
        if category in self._category_strategies:
            explicit = self._category_strategies[category]
            return {
                "approach": explicit,
                "confidence": round(recent_rate, 2),
                "reasoning": f"Strategy '{explicit}' assigned due to detected failure pattern.",
                "max_retries": 3 if explicit == "roundtable" else 2,
                "use_roundtable": explicit == "roundtable",
            }
        
        # High success — direct execution with confidence
        if recent_rate >= 0.9 and total >= 10:
            return {
                "approach": "direct",
                "confidence": round(min(recent_rate, 0.95), 2),
                "reasoning": f"Strong track record in '{category}' ({recent_rate:.0%} recent, {total} tasks). Direct execution.",
                "max_retries": 1,
                "use_roundtable": False,
            }
        
        # Good but not great — standard approach with verification
        if recent_rate >= 0.7:
            return {
                "approach": "execute_and_verify",
                "confidence": round(recent_rate, 2),
                "reasoning": f"Good performance in '{category}' ({recent_rate:.0%}). Standard execution with verification.",
                "max_retries": 2,
                "use_roundtable": False,
            }
        
        # Struggling — use more careful approach
        if recent_rate >= 0.5:
            return {
                "approach": "explore_work_validate",
                "confidence": round(recent_rate, 2),
                "reasoning": f"Mixed results in '{category}' ({recent_rate:.0%}). Using explore/work/validate cycle.",
                "max_retries": 2,
                "use_roundtable": False,
            }
        
        # Poor performance — bring in the roundtable
        return {
            "approach": "roundtable",
            "confidence": round(recent_rate, 2),
            "reasoning": f"Struggling in '{category}' ({recent_rate:.0%}). Recommending roundtable for diverse perspectives.",
            "max_retries": 3,
            "use_roundtable": True,
        }
    
    def predict_outcome(self, category: str) -> dict[str, Any]:
        """
        SP7-03: Predict the likely outcome of a task before execution.
        
        Uses historical data to estimate success probability, expected duration,
        and risk factors. This is Aria's "intuition" — she can anticipate
        what will happen before acting.
        """
        outcomes = self._task_outcomes.get(category, [])
        total = len(outcomes)
        
        if total < 5:
            return {
                "predicted_success": 0.5,
                "confidence_in_prediction": 0.2,
                "expected_duration_ms": 5000,
                "risk_factors": ["insufficient_history"],
                "recommendation": "proceed_with_caution",
            }
        
        success_rate = sum(outcomes) / total
        recent = outcomes[-10:] if len(outcomes) >= 10 else outcomes
        recent_rate = sum(recent) / len(recent)
        
        # Weight recent performance more heavily (70% recent, 30% all-time)
        predicted_success = round(recent_rate * 0.7 + success_rate * 0.3, 3)
        
        # Confidence in prediction scales with sample size
        prediction_confidence = min(0.95, total / 100)
        
        # Estimate duration from window results
        cat_durations = [
            r["duration_ms"] for r in self._window_results
            if r.get("category") == category and r.get("duration_ms", 0) > 0
        ]
        expected_ms = int(sum(cat_durations) / len(cat_durations)) if cat_durations else 5000
        
        # Identify risk factors
        risks = []
        if recent_rate < success_rate - 0.1:
            risks.append("declining_performance")
        if self._failure_patterns.get(category, 0) >= 3:
            risks.append("recurring_failures")
        if self._current_streak == 0 and total > 5:
            risks.append("recent_failure")
        
        # Recommendation
        if predicted_success >= 0.8:
            rec = "proceed_confidently"
        elif predicted_success >= 0.6:
            rec = "proceed_with_verification"
        elif predicted_success >= 0.4:
            rec = "consider_alternative_approach"
        else:
            rec = "seek_assistance_or_defer"
        
        return {
            "predicted_success": predicted_success,
            "confidence_in_prediction": round(prediction_confidence, 2),
            "expected_duration_ms": expected_ms,
            "risk_factors": risks,
            "recommendation": rec,
        }

    def get_learning_velocity(self) -> dict[str, Any]:
        """
        Calculate how fast Aria is improving.
        
        Compares recent performance windows to detect acceleration or deceleration.
        """
        if len(self._window_results) < 20:
            return {
                "status": "insufficient_data",
                "message": "Need at least 20 tasks to measure learning velocity",
                "total_tasks": len(self._window_results),
            }
        
        # Split into halves
        mid = len(self._window_results) // 2
        first_half = self._window_results[:mid]
        second_half = self._window_results[mid:]
        
        first_rate = sum(1 for r in first_half if r["success"]) / len(first_half)
        second_rate = sum(1 for r in second_half if r["success"]) / len(second_half)
        
        delta = second_rate - first_rate
        
        if delta > 0.1:
            trend = "accelerating"
            message = f"Strong improvement! Success rate increased by {delta:.1%}"
        elif delta > 0.02:
            trend = "improving"
            message = f"Steady improvement. Success rate up {delta:.1%}"
        elif delta > -0.02:
            trend = "stable"
            message = f"Consistent performance at {second_rate:.0%}"
        else:
            trend = "needs_attention"
            message = f"Performance dropped by {abs(delta):.1%} — consider reviewing approach"
        
        return {
            "status": trend,
            "message": message,
            "early_success_rate": round(first_rate, 3),
            "recent_success_rate": round(second_rate, 3),
            "delta": round(delta, 3),
            "total_tasks": len(self._window_results),
        }
    
    def get_strengths(self) -> list[dict[str, Any]]:
        """Identify Aria's strongest categories based on performance data."""
        strengths = []
        for category, outcomes in self._task_outcomes.items():
            if len(outcomes) < 3:
                continue
            rate = sum(outcomes) / len(outcomes)
            strengths.append({
                "category": category,
                "success_rate": round(rate, 3),
                "total_tasks": len(outcomes),
                "level": (
                    "mastery" if rate > 0.9 else
                    "proficient" if rate > 0.7 else
                    "developing" if rate > 0.5 else
                    "learning"
                ),
            })
        
        return sorted(strengths, key=lambda x: x["success_rate"], reverse=True)
    
    def get_growth_report(self) -> dict[str, Any]:
        """
        Generate a comprehensive growth report for Aria.
        
        This is what Aria reads when she wants to understand herself.
        """
        velocity = self.get_learning_velocity()
        strengths = self.get_strengths()
        
        return {
            "total_tasks": self._total_tasks,
            "total_successes": self._total_successes,
            "overall_success_rate": round(
                self._total_successes / max(self._total_tasks, 1), 3
            ),
            "current_streak": self._current_streak,
            "best_streak": self._best_streak,
            "milestones_achieved": len(self._milestones),
            "milestones": {k: v.to_dict() for k, v in self._milestones.items()},
            "learning_velocity": velocity,
            "strengths": strengths[:5],
            "failure_patterns": dict(self._failure_patterns.most_common(5)),
            "category_strategies": self._category_strategies,
            "reflections_completed": self._reflection_count,
            "consolidations_completed": self._consolidation_count,
        }
    
    def get_self_assessment(self) -> str:
        """
        Generate a natural language self-assessment.
        
        This is Aria speaking about herself — her growth, her struggles,
        her strengths, and where she wants to improve.
        """
        report = self.get_growth_report()
        
        parts = []
        
        # Overall status
        rate = report["overall_success_rate"]
        if rate > 0.9:
            parts.append(f"I'm performing exceptionally well — {rate:.0%} success rate across {report['total_tasks']} tasks.")
        elif rate > 0.7:
            parts.append(f"I'm doing well — {rate:.0%} success rate across {report['total_tasks']} tasks.")
        elif rate > 0.5:
            parts.append(f"I'm learning. {rate:.0%} success rate across {report['total_tasks']} tasks — room to grow.")
        else:
            parts.append(f"I'm in my early learning phase. {rate:.0%} success rate — every failure teaches me.")
        
        # Streaks
        if report["best_streak"] >= 10:
            parts.append(f"My best streak is {report['best_streak']} consecutive successes — that's {report['best_streak']} times I got it right in a row.")
        
        # Strengths
        if report["strengths"]:
            top = report["strengths"][0]
            parts.append(f"My strongest area is '{top['category']}' ({top['success_rate']:.0%} success).")
        
        # Learning velocity
        velocity = report["learning_velocity"]
        if velocity["status"] == "accelerating":
            parts.append(f"I'm getting better fast — {velocity['message']}")
        elif velocity["status"] == "improving":
            parts.append(f"Steady growth — {velocity['message']}")
        elif velocity["status"] == "needs_attention":
            parts.append(f"I need to pay attention — {velocity['message']}")
        
        # Milestones
        if report["milestones_achieved"] > 0:
            parts.append(f"I've achieved {report['milestones_achieved']} growth milestones.")
        
        return " ".join(parts)
    
    def save(self, base_path: Path | None = None) -> bool:
        """Persist metacognitive state to disk."""
        try:
            if base_path is None:
                import os
                memories = os.environ.get("ARIA_MEMORIES_PATH", "/app/aria_memories")
                base_path = Path(memories)
                if not base_path.exists():
                    base_path = Path(__file__).parent.parent / "aria_memories"
            
            knowledge_dir = base_path / "knowledge"
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "total_tasks": self._total_tasks,
                "total_successes": self._total_successes,
                "current_streak": self._current_streak,
                "best_streak": self._best_streak,
                "reflection_count": self._reflection_count,
                "consolidation_count": self._consolidation_count,
                "milestones": {k: v.to_dict() for k, v in self._milestones.items()},
                "task_outcomes": {k: v[-100:] for k, v in self._task_outcomes.items()},
                "failure_patterns": dict(self._failure_patterns),
                "category_strategies": self._category_strategies,
                "window_results": self._window_results[-200:],
            }
            
            filepath = knowledge_dir / "metacognitive_state.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.info(f"Saved metacognitive state to {filepath}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save metacognitive state: {e}")
            return False
    
    def load(self, base_path: Path | None = None) -> bool:
        """Load metacognitive state from disk."""
        try:
            if base_path is None:
                import os
                memories = os.environ.get("ARIA_MEMORIES_PATH", "/app/aria_memories")
                base_path = Path(memories)
                if not base_path.exists():
                    base_path = Path(__file__).parent.parent / "aria_memories"
            
            filepath = base_path / "knowledge" / "metacognitive_state.json"
            if not filepath.exists():
                logger.info("No metacognitive state found — starting fresh")
                return True
            
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self._total_tasks = data.get("total_tasks", 0)
            self._total_successes = data.get("total_successes", 0)
            self._current_streak = data.get("current_streak", 0)
            self._best_streak = data.get("best_streak", 0)
            self._reflection_count = data.get("reflection_count", 0)
            self._consolidation_count = data.get("consolidation_count", 0)
            self._category_strategies = data.get("category_strategies", {})
            self._failure_patterns = Counter(data.get("failure_patterns", {}))
            self._window_results = data.get("window_results", [])
            
            # Restore task outcomes
            for k, v in data.get("task_outcomes", {}).items():
                self._task_outcomes[k] = v
            
            # Restore milestones
            for k, v in data.get("milestones", {}).items():
                self._milestones[k] = GrowthMilestone(
                    v["name"], v["description"], v["achieved_at"]
                )
            
            logger.info(
                f"Loaded metacognitive state: {self._total_tasks} tasks, "
                f"{len(self._milestones)} milestones, "
                f"best streak {self._best_streak}"
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to load metacognitive state: {e}")
            return False


# Module-level singleton
_engine: MetacognitiveEngine | None = None


def get_metacognitive_engine() -> MetacognitiveEngine:
    """Get or create the singleton metacognitive engine."""
    global _engine
    if _engine is None:
        _engine = MetacognitiveEngine()
        _engine.load()
    return _engine
