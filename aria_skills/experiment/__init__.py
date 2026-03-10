# aria_skills/experiment/__init__.py
"""
ML experiment tracking and model management.

In-memory experiment store with JSONL persistence to aria_memories/.
For Aria's Data Architect persona.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry

EXPERIMENTS_DIR = Path(os.environ.get("ARIA_MEMORIES", "/aria_memories")) / "experiments"


@SkillRegistry.register
class ExperimentSkill(BaseSkill):
    """ML experiment tracking and model management."""

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config or SkillConfig(name="experiment"))
        self._experiments: dict[str, dict] = {}
        self._models: dict[str, dict] = {}
        self._api = None

    @property
    def name(self) -> str:
        return "experiment"

    async def initialize(self) -> bool:
        # Load persisted experiments if available
        try:
            EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
            log_path = EXPERIMENTS_DIR / "experiments.jsonl"
            if log_path.exists():
                for line in log_path.read_text().splitlines():
                    if line.strip():
                        exp = json.loads(line)
                        self._experiments[exp["id"]] = exp
                self.logger.info(f"Loaded {len(self._experiments)} persisted experiments")
        except Exception as e:
            self.logger.warning(f"Could not load persisted experiments: {e}")

        try:
            self._api = await get_api_client()
        except Exception as e:
            self.logger.info(f"API unavailable, experiment activity logging disabled: {e}")
            self._api = None

        self._status = SkillStatus.AVAILABLE
        self.logger.info("Experiment tracking skill initialized")
        return True

    async def health_check(self) -> SkillStatus:
        return self._status

    def _persist(self, experiment: dict) -> None:
        """Append experiment to JSONL log."""
        try:
            EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
            with open(EXPERIMENTS_DIR / "experiments.jsonl", "a") as f:
                f.write(json.dumps(experiment, default=str) + "\n")
        except Exception:
            pass

    @logged_method()
    async def create_experiment(
        self, name: str = "", description: str = "",
        hypothesis: str = "", tags: list[str] | None = None, **kwargs
    ) -> SkillResult:
        """Create a new experiment."""
        name = name or kwargs.get("name", "unnamed")
        exp_id = str(uuid.uuid4())[:8]
        experiment = {
            "id": exp_id,
            "name": name,
            "description": description or kwargs.get("description", ""),
            "hypothesis": hypothesis or kwargs.get("hypothesis", ""),
            "tags": tags or kwargs.get("tags", []),
            "status": "running",
            "metrics": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        self._experiments[exp_id] = experiment
        self._persist(experiment)
        await self._persist_activity("experiment_created", {
            "experiment": experiment,
            "experiment_id": exp_id,
            "experiment_name": experiment["name"],
            "hypothesis": experiment["hypothesis"],
            "status": experiment["status"],
            "description": experiment["description"],
        })
        return SkillResult.ok({
            "experiment": experiment,
            "message": f"Experiment '{name}' created with ID {exp_id}",
        })

    @logged_method()
    async def log_metrics(
        self, experiment_id: str = "", metrics: dict | None = None,
        step: int | None = None, **kwargs
    ) -> SkillResult:
        """Log metrics for an experiment."""
        experiment_id = experiment_id or kwargs.get("experiment_id", "")
        if experiment_id not in self._experiments:
            return SkillResult.fail(f"Experiment '{experiment_id}' not found")
        metrics = metrics or kwargs.get("metrics", {})
        if not metrics:
            return SkillResult.fail("No metrics provided")

        exp = self._experiments[experiment_id]
        for key, value in metrics.items():
            if key not in exp["metrics"]:
                exp["metrics"][key] = []
            exp["metrics"][key].append({
                "value": value,
                "step": step,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        self._persist(exp)
        await self._persist_activity("experiment_metrics_logged", {
            "experiment_id": experiment_id,
            "experiment_name": exp["name"],
            "status": exp["status"],
            "metrics": metrics,
            "step": step,
        })
        return SkillResult.ok({
            "experiment_id": experiment_id,
            "metrics_logged": list(metrics.keys()),
            "total_metrics": {k: len(v) for k, v in exp["metrics"].items()},
        })

    @logged_method()
    async def complete_experiment(
        self, experiment_id: str = "", conclusion: str = "", **kwargs
    ) -> SkillResult:
        """Mark an experiment as completed."""
        experiment_id = experiment_id or kwargs.get("experiment_id", "")
        if experiment_id not in self._experiments:
            return SkillResult.fail(f"Experiment '{experiment_id}' not found")

        exp = self._experiments[experiment_id]
        exp["status"] = "completed"
        exp["completed_at"] = datetime.now(timezone.utc).isoformat()
        exp["conclusion"] = conclusion or kwargs.get("conclusion", "")
        self._persist(exp)
        await self._persist_activity("experiment_completed", {
            "experiment": exp,
            "experiment_id": experiment_id,
            "experiment_name": exp["name"],
            "status": exp["status"],
            "conclusion": exp.get("conclusion", ""),
        })
        return SkillResult.ok({
            "experiment": exp,
            "message": f"Experiment '{exp['name']}' completed",
        })

    @logged_method()
    async def compare_experiments(
        self, experiment_ids: list[str] | None = None, metric: str = "", **kwargs
    ) -> SkillResult:
        """Compare metrics across experiments."""
        experiment_ids = experiment_ids or kwargs.get("experiment_ids", [])
        metric = metric or kwargs.get("metric", "")
        if not experiment_ids:
            return SkillResult.fail("No experiment IDs provided")

        comparisons = []
        for eid in experiment_ids:
            exp = self._experiments.get(eid)
            if not exp:
                continue
            metric_data = exp["metrics"].get(metric, [])
            latest = metric_data[-1]["value"] if metric_data else None
            comparisons.append({
                "experiment_id": eid,
                "name": exp["name"],
                "status": exp["status"],
                "metric": metric,
                "latest_value": latest,
                "data_points": len(metric_data),
            })

        if not comparisons:
            return SkillResult.fail("No valid experiments found")

        # Sort by latest value
        comparisons.sort(key=lambda x: x["latest_value"] or 0, reverse=True)
        return SkillResult.ok({
            "metric": metric,
            "comparisons": comparisons,
            "best": comparisons[0]["experiment_id"] if comparisons else None,
        })

    @logged_method()
    async def register_model(
        self, name: str = "", experiment_id: str = "",
        version: str = "1.0.0", metadata: dict | None = None, **kwargs
    ) -> SkillResult:
        """Register a model from an experiment."""
        name = name or kwargs.get("name", "")
        if not name:
            return SkillResult.fail("No model name provided")
        model_id = str(uuid.uuid4())[:8]
        self._models[model_id] = {
            "id": model_id,
            "name": name,
            "experiment_id": experiment_id or kwargs.get("experiment_id", ""),
            "version": version,
            "stage": "staging",
            "metadata": metadata or kwargs.get("metadata", {}),
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._persist_activity("experiment_model_registered", {
            "model": self._models[model_id],
            "experiment_id": self._models[model_id]["experiment_id"],
            "experiment_name": self._experiments.get(self._models[model_id]["experiment_id"], {}).get("name"),
            "status": self._models[model_id]["stage"],
        })
        return SkillResult.ok({
            "model": self._models[model_id],
            "message": f"Model '{name}' registered (staging)",
        })

    @logged_method()
    async def promote_model(
        self, model_id: str = "", stage: str = "production", **kwargs
    ) -> SkillResult:
        """Promote a model to a given stage."""
        model_id = model_id or kwargs.get("model_id", "")
        if model_id not in self._models:
            return SkillResult.fail(f"Model '{model_id}' not found")
        self._models[model_id]["stage"] = stage
        self._models[model_id]["promoted_at"] = datetime.now(timezone.utc).isoformat()
        await self._persist_activity("experiment_model_promoted", {
            "model": self._models[model_id],
            "experiment_id": self._models[model_id].get("experiment_id"),
            "experiment_name": self._experiments.get(self._models[model_id].get("experiment_id", ""), {}).get("name"),
            "status": self._models[model_id]["stage"],
        })
        return SkillResult.ok({
            "model": self._models[model_id],
            "message": f"Model promoted to {stage}",
        })

    async def _persist_activity(self, action: str, details: dict, success: bool = True) -> None:
        """Best-effort API persistence. Never blocks experiment execution."""
        if not self._api:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._api.create_activity(
                        action=action,
                        skill=self.name,
                        details=details,
                        success=success,
                    )
                )
        except Exception:
            self.logger.debug("Experiment activity persistence skipped")
