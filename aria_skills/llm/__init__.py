# aria_skills/llm/__init__.py
"""
LLM Fallback Chain Skill (S-45 Phase 3).

Provides resilient LLM completions with per-model circuit breakers
and automatic fallback through the model priority chain.
Model names sourced from aria_models/models.yaml — do NOT hardcode here.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

# ─────────────────────────────────────────────────────────────────────────────
# Fallback chain — loaded dynamically from aria_models/models.yaml at runtime.
# ─────────────────────────────────────────────────────────────────────────────
_STATIC_FALLBACK_CHAIN: list[dict] = []


def _build_fallback_chain() -> list[dict]:
    """Load fallback chain from aria_models/models.yaml routing.fallbacks.

    Falls back to _STATIC_FALLBACK_CHAIN on any loading error.
    """
    try:
        from aria_models.loader import load_catalog as _load_catalog

        catalog = _load_catalog()
        routing = catalog.get("routing", {})
        fallbacks: list[str] = routing.get("fallbacks", [])

        # Build a tier map keyed by the routed alias used throughout the skill.
        models_map: dict[str, str] = {}
        local_chat_models: list[str] = []
        for model_key, mval in catalog.get("models", {}).items():
            alias = f"litellm/{model_key}"
            tier = mval.get("tier", "paid")
            models_map[alias] = tier

            if tier != "local":
                continue
            if mval.get("type") == "embedding":
                continue
            if mval.get("maxTokens", 0) <= 0:
                continue

            local_chat_models.append(alias)

        chain = []
        for i, model_id in enumerate(fallbacks):
            # Infer tier: check models_map, then fallback name heuristics
            tier = models_map.get(model_id, "")
            if not tier:
                if "local" in model_id or "mlx" in model_id or "ollama" in model_id:
                    tier = "local"
                elif "free" in model_id:
                    tier = "free"
                else:
                    tier = "paid"
            chain.append({"model": model_id, "tier": tier, "priority": i + 1})

        # Ensure chat-capable local models from models.yaml are prepended if not in fallbacks.
        for local_id in reversed(local_chat_models):
            if not any(entry["model"] == local_id for entry in chain):
                chain.insert(0, {"model": local_id, "tier": "local", "priority": 0})

        return chain
    except Exception:
        return _STATIC_FALLBACK_CHAIN


LLM_FALLBACK_CHAIN: list[dict] = _build_fallback_chain()


@SkillRegistry.register
class LLMSkill(BaseSkill):
    """
    LLM completion skill with circuit-breaker-aware fallback chain.

    Routes completion requests through LLM_FALLBACK_CHAIN, skipping
    models whose circuit-breakers are open, and retrying with the next
    available model on transient failures.

    Config:
        litellm_url: LiteLLM proxy base URL (default: http://litellm:4000/v1)
        timeout:     Per-request timeout in seconds (default: 120)
        circuit_failure_threshold: failures before opening circuit (default: 3)
        circuit_reset_seconds:     seconds before retrying (default: 60)
    """

    def __init__(self, config: SkillConfig) -> None:
        super().__init__(config)
        self._litellm_url: str = ""
        self._timeout: float = 0
        self._api_key: str = ""
        self._client: "httpx.AsyncClient | None" = None

        # Per-model circuit breaker state
        self._failure_counts: dict[str, int] = {}
        self._circuit_open_until: dict[str, float] = {}
        self._circuit_failure_threshold: int = int(
            self.config.config.get("circuit_failure_threshold", 3)
        )
        self._circuit_reset_seconds: float = float(
            self.config.config.get("circuit_reset_seconds", 60.0)
        )

    @property
    def name(self) -> str:
        return "llm"

    async def initialize(self) -> bool:
        if not HAS_HTTPX:
            self.logger.error("httpx not installed — LLMSkill unavailable")
            self._status = SkillStatus.UNAVAILABLE
            return False

        self._litellm_url = self.config.config.get(
            "litellm_url",
            os.environ.get("LITELLM_URL", "http://litellm:4000/v1"),
        ).rstrip("/")
        self._timeout = float(self.config.config.get("timeout", 120))
        self._api_key = os.environ.get("LITELLM_MASTER_KEY", "sk-aria")

        self._client = httpx.AsyncClient(
            base_url=self._litellm_url,
            timeout=self._timeout,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        self._status = SkillStatus.AVAILABLE
        self.logger.info("LLMSkill initialized — %s", self._litellm_url)
        return True

    async def health_check(self) -> SkillStatus:
        if not self._client:
            return SkillStatus.UNAVAILABLE
        try:
            resp = await self._client.get("/models")
            self._status = SkillStatus.AVAILABLE if resp.status_code == 200 else SkillStatus.ERROR
        except Exception as e:
            self.logger.warning("LLM health check failed: %s", e)
            self._status = SkillStatus.ERROR
        return self._status

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
            self._status = SkillStatus.UNAVAILABLE

    # ─────────────────────────────────────────────────────────────────────────
    # Circuit breaker helpers (per-model)
    # ─────────────────────────────────────────────────────────────────────────

    def _is_circuit_open(self, model: str) -> bool:
        """Return True if this model's circuit is open (cooling down)."""
        return time.monotonic() < self._circuit_open_until.get(model, 0.0)

    def _record_success(self, model: str) -> None:
        self._failure_counts[model] = 0
        self._circuit_open_until[model] = 0.0

    def _record_failure(self, model: str) -> None:
        count = self._failure_counts.get(model, 0) + 1
        self._failure_counts[model] = count
        if count >= self._circuit_failure_threshold:
            open_until = time.monotonic() + self._circuit_reset_seconds
            self._circuit_open_until[model] = open_until
            self.logger.warning(
                "LLM circuit opened for model=%s (%.0fs cooldown after %d failures)",
                model, self._circuit_reset_seconds, count,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Core completion method
    # ─────────────────────────────────────────────────────────────────────────

    async def _complete_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a single completion request to LiteLLM for a specific model."""
        if not self._client:
            raise RuntimeError("LLMSkill is not initialized")

        payload = {"model": model, "messages": messages, **kwargs}
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def complete_with_fallback(
        self,
        messages: list[dict[str, str]],
        chain: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SkillResult:
        """
        Try each model in the fallback chain until one succeeds.

        Skips models whose circuit-breakers are currently open.
        Records success/failure per model for adaptive routing.

        Args:
            messages: OpenAI-style message list.
            chain:    Override fallback chain (defaults to LLM_FALLBACK_CHAIN).
            **kwargs: Extra params forwarded to the completion API (e.g. temperature).

        Returns:
            SkillResult.ok(response_dict) or SkillResult.fail(reason).
        """
        chain = chain or LLM_FALLBACK_CHAIN
        tried: list[str] = []
        last_error: Exception | None = None

        for model_cfg in sorted(chain, key=lambda m: m.get("priority", 99)):
            model = model_cfg["model"]
            if self._is_circuit_open(model):
                self.logger.debug("Skipping %s — circuit open", model)
                continue
            tried.append(model)
            try:
                result = await self._complete_with_model(model, messages, **kwargs)
                self._record_success(model)
                result["_aria_model_used"] = model
                result["_aria_fallback_tried"] = tried
                return SkillResult.ok(result)
            except Exception as exc:
                last_error = exc
                self._record_failure(model)
                self.logger.warning(
                    "LLM model %s failed (trying next): %s", model, exc
                )

        reason = (
            f"All LLM models in fallback chain unavailable. "
            f"Tried: {tried}. Last error: {last_error}"
        )
        self.logger.error(reason)
        return SkillResult.fail(reason)

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> SkillResult:
        """
        Complete a conversation, optionally pinning to a specific model.

        If model is not specified or its circuit is open, delegates to
        complete_with_fallback() for automatic failover.
        """
        if model and not self._is_circuit_open(model):
            # Try the requested model first; fall back if it errors
            try:
                result = await self._complete_with_model(model, messages, **kwargs)
                self._record_success(model)
                result["_aria_model_used"] = model
                return SkillResult.ok(result)
            except Exception as exc:
                self._record_failure(model)
                self.logger.warning(
                    "Requested model %s failed, falling back: %s", model, exc
                )
        return await self.complete_with_fallback(messages, **kwargs)

    async def get_circuit_status(self) -> SkillResult:
        """Return circuit breaker state for all models."""
        now = time.monotonic()
        status = {}
        for model_cfg in LLM_FALLBACK_CHAIN:
            model = model_cfg["model"]
            open_until = self._circuit_open_until.get(model, 0.0)
            status[model] = {
                "tier": model_cfg["tier"],
                "priority": model_cfg["priority"],
                "circuit_open": open_until > now,
                "failures": self._failure_counts.get(model, 0),
                "resets_in_seconds": max(0.0, round(open_until - now, 1)),
            }
        return SkillResult.ok(status)

    async def complete_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> SkillResult:
        """Get a completion from a specific model, bypassing the fallback chain."""
        try:
            result = await self._complete_with_model(model, messages, **kwargs)
            self._record_success(model)
            result["_aria_model_used"] = model
            return SkillResult.ok(result)
        except Exception as exc:
            self._record_failure(model)
            return SkillResult.fail(f"Model {model} failed: {exc}")

    async def get_fallback_chain(self) -> SkillResult:
        """Get the current fallback chain with tier and priority info."""
        return SkillResult.ok({"chain": LLM_FALLBACK_CHAIN})

    async def reset_circuit_breakers(self) -> SkillResult:
        """Reset all circuit breakers to closed state."""
        self._failure_counts.clear()
        self._circuit_open_until.clear()
        return SkillResult.ok({
            "reset": True,
            "models_cleared": len(LLM_FALLBACK_CHAIN),
        })
