# aria_skills/model_switcher/__init__.py
"""
Model switcher skill — switch LLM models and toggle thinking mode.

Layer 2 orchestrator skill. Reads available models from the API
and manages the active model + thinking mode state.
"""
import os
from datetime import datetime, timezone
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry

try:
    from aria_models.loader import get_primary_model as _get_primary_model
except ImportError:
    def _get_primary_model() -> str:
        return ""


def build_thinking_params(model: str, enable: bool = True) -> dict[str, Any]:
    """Build model-specific parameters for enabling thinking mode.

    Reads thinking_params from models.yaml via get_thinking_config().
    No hardcoded model family checks — YAML is the source of truth.
    """
    if not enable:
        return {}

    try:
        from aria_models.loader import get_thinking_config
        return get_thinking_config(model)
    except ImportError:
        return {}


@SkillRegistry.register
class ModelSwitcherSkill(BaseSkill):
    """
    Switch between LLM models and toggle thinking/reasoning mode.

    Tools: list_models, switch_model, get_current_model,
           set_thinking_mode, get_thinking_mode, get_switch_history.
    """

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config or SkillConfig(name="model_switcher"))
        self._api = None
        self._current_model: str = _get_primary_model()
        self._thinking_enabled: bool = False
        self._switch_history: list[dict] = []

    @property
    def name(self) -> str:
        return "model_switcher"

    async def initialize(self) -> bool:
        try:
            from aria_skills.api_client import get_api_client
            self._api = await get_api_client()
        except Exception as e:
            self.logger.warning(f"API client not available: {e}")
            # Can still work in degraded mode without API

        # Try to load current model from models.yaml routing config
        try:
            from aria_models.loader import get_primary_model
            self._current_model = get_primary_model()
        except Exception:
            self._current_model = ""

        self._status = SkillStatus.AVAILABLE
        self.logger.info(f"Model switcher initialized (current: {self._current_model})")
        return True

    async def health_check(self) -> SkillStatus:
        return self._status

    @logged_method()
    async def list_models(self, **kwargs) -> SkillResult:
        """List available LLM models."""
        models = []

        # Try API first
        if self._api:
            try:
                result = await self._api.get_litellm_models()
                if result.success and isinstance(result.data, dict):
                    for m in result.data.get("data", []):
                        models.append({
                            "id": m.get("id", ""),
                            "name": m.get("id", ""),
                            "owned_by": m.get("owned_by", ""),
                        })
            except Exception:
                pass

        # Fallback: load from models.yaml
        if not models:
            try:
                from aria_models.loader import load_catalog
                catalog = load_catalog()
                for model_id, model_data in catalog.get("models", {}).items():
                    models.append({
                        "id": model_id,
                        "name": model_data.get("name", model_id),
                        "tier": model_data.get("tier", "unknown"),
                        "provider": model_data.get("provider", "unknown"),
                    })
            except Exception:
                pass

        return SkillResult.ok({
            "models": models,
            "total": len(models),
            "current_model": self._current_model,
        })

    @logged_method()
    async def switch_model(
        self, model: str = "", reason: str = "", **kwargs
    ) -> SkillResult:
        """Switch the active LLM model."""
        model = model or kwargs.get("model", "")
        if not model:
            return SkillResult.fail("No model specified")

        previous = self._current_model
        self._current_model = model
        entry = {
            "from": previous,
            "to": model,
            "reason": reason or kwargs.get("reason", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._switch_history.append(entry)

        return SkillResult.ok({
            "previous_model": previous,
            "current_model": model,
            "switch_count": len(self._switch_history),
            "message": f"Switched from {previous} to {model}",
        })

    @logged_method()
    async def get_current_model(self, **kwargs) -> SkillResult:
        """Get the currently active model."""
        return SkillResult.ok({
            "model": self._current_model,
            "thinking_enabled": self._thinking_enabled,
            "total_switches": len(self._switch_history),
        })

    @logged_method()
    async def set_thinking_mode(
        self, enabled: bool = True, **kwargs
    ) -> SkillResult:
        """Enable or disable thinking/reasoning mode."""
        enabled = kwargs.get("enabled", enabled)
        previous = self._thinking_enabled
        self._thinking_enabled = bool(enabled)

        # Build model-specific thinking params
        params = build_thinking_params(self._current_model, enable=self._thinking_enabled)

        return SkillResult.ok({
            "thinking_enabled": self._thinking_enabled,
            "previous": previous,
            "model": self._current_model,
            "thinking_params": params,
            "message": f"Thinking mode {'enabled' if self._thinking_enabled else 'disabled'} for {self._current_model}",
        })

    @logged_method()
    async def get_thinking_mode(self, **kwargs) -> SkillResult:
        """Get current thinking mode status."""
        params = build_thinking_params(self._current_model, enable=self._thinking_enabled)
        return SkillResult.ok({
            "thinking_enabled": self._thinking_enabled,
            "model": self._current_model,
            "thinking_params": params,
        })

    @logged_method()
    async def get_switch_history(self, limit: int = 20, **kwargs) -> SkillResult:
        """Get model switch history."""
        limit = limit or kwargs.get("limit", 20)
        return SkillResult.ok({
            "history": self._switch_history[-limit:],
            "total_switches": len(self._switch_history),
            "current_model": self._current_model,
        })
