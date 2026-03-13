"""
Native LLM Gateway — Direct litellm SDK integration.

Zero-hop Python calls to litellm.
Features:
- Direct litellm.acompletion() with async streaming
- Model routing from models.yaml
- Fallback chain with automatic failover
- Token counting and cost tracking
- Thinking token support (Qwen3, Claude)
- Tool calling (function calling) support
- Circuit breaker for resilience
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

import litellm
from litellm import acompletion, token_counter

from aria_engine.config import EngineConfig
from aria_engine.circuit_breaker import CircuitBreaker
from aria_engine.exceptions import LLMError, safe_fire_and_forget
from aria_models.loader import load_catalog, get_routing_config, normalize_model_id

logger = logging.getLogger("aria.engine.llm")


@dataclass
class LLMResponse:
    """Response from LLM gateway."""
    content: str
    thinking: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = ""


@dataclass
class StreamChunk:
    """Single chunk from streaming response."""
    content: str = ""
    thinking: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: str | None = None
    is_thinking: bool = False


class LLMGateway:
    """
    Native LLM gateway using litellm SDK directly.

    Usage:
        gateway = LLMGateway(config)
        response = await gateway.complete(messages, model="trinity")

        # Streaming:
        async for chunk in gateway.stream(messages, model="qwen3.5_mlx"):
            print(chunk.content, end="")
    """

    def __init__(self, config: EngineConfig, db_engine: "AsyncEngine | None" = None):
        self.config = config
        self._db_engine = db_engine          # set via initialize() at boot
        self._models_config: dict[str, Any] | None = None
        self._cb = CircuitBreaker(name="llm", threshold=5, reset_after=30.0)
        self._latency_samples: list[float] = []

        # Configure litellm
        # Note: Do NOT set litellm.api_base globally — each model specifies
        # its own api_base/api_key in models.yaml.  The global api_base would
        # override per-call kwargs for providers that use a different base URL.
        litellm.api_key = config.litellm_master_key
        litellm.drop_params = True  # Don't fail on unsupported params

    async def initialize(self, db_engine: "AsyncEngine") -> None:
        """Restore persisted circuit-breaker state from DB.

        Call once after construction to hydrate ``self._cb`` from
        ``aria_engine.circuit_breaker_state``.  Non-fatal — failures are
        logged and the gateway continues with a fresh (closed) CB.
        """
        self._db_engine = db_engine
        try:
            self._cb = await CircuitBreaker.restore(
                "llm", db_engine, threshold=5, reset_after=30.0
            )
            logger.info("LLM circuit breaker restored from DB: %s", self._cb)
        except Exception as exc:
            logger.warning("CB restore failed (non-fatal), using fresh CB: %s", exc)

    async def _cb_persist(self) -> None:
        """Fire-and-forget helper — persist circuit-breaker state to DB."""
        if self._db_engine is None:
            return
        try:
            await self._cb.persist(self._db_engine)
        except Exception as exc:
            logger.debug("CB persist failed (non-fatal): %s", exc)

    def _load_models(self) -> dict[str, Any]:
        """Lazy-load models.yaml configuration."""
        if self._models_config is None:
            self._models_config = load_catalog()
        return self._models_config

    def _resolve_model(self, model: str) -> tuple[str, dict[str, Any]]:
        """Resolve model alias to (litellm_model_string, extra_kwargs).

        Returns the litellm model identifier and any per-model overrides
        (``api_key``, ``api_base``, ``temperature``, etc.) from models.yaml
        so that calls go directly to the provider rather than requiring a
        litellm proxy.
        """
        import os

        models = self._load_models()
        model_id = normalize_model_id(model)
        model_entries = models.get("models", {})
        model_def = model_entries.get(model_id, {})
        litellm_block = model_def.get("litellm", {})
        litellm_model = litellm_block.get("model", model)

        extra: dict[str, Any] = {}

        # Per-model api_key (supports "os.environ/VAR" syntax)
        raw_key = litellm_block.get("api_key", "")
        if raw_key:
            if raw_key.startswith("os.environ/"):
                env_var = raw_key.split("/", 1)[1]
                resolved_key = os.environ.get(env_var, "")
                if resolved_key:
                    extra["api_key"] = resolved_key
            else:
                extra["api_key"] = raw_key

        # Per-model api_base
        raw_base = litellm_block.get("api_base", "")
        if raw_base:
            extra["api_base"] = raw_base

        # Forward any other litellm params (temperature, max_tokens, etc.)
        _reserved = {"model", "api_key", "api_base"}
        for k, v in litellm_block.items():
            if k not in _reserved and v is not None:
                extra[k] = v

        return litellm_model, extra

    def _get_fallback_chain(self) -> list[str]:
        """Get fallback model chain from models.yaml (alias IDs)."""
        routing = get_routing_config()
        fallbacks = routing.get("fallbacks", [])
        return [normalize_model_id(str(m)) for m in fallbacks]

    def _build_model_candidates(self, primary_model: str | None) -> list[str]:
        """Build ordered unique candidate list: primary + configured fallbacks."""
        primary = normalize_model_id(primary_model or self.config.default_model)
        candidates: list[str] = [primary]
        for fallback in self._get_fallback_chain():
            if fallback and fallback not in candidates:
                candidates.append(fallback)
        return candidates

    @staticmethod
    def _is_retriable_error(exc: Exception) -> bool:
        """Best-effort retriable classification for provider/network/transient failures."""
        msg = str(exc).lower()
        retriable_markers = (
            "timeout",
            "timed out",
            "rate limit",
            "429",
            "503",
            "502",
            "connection",
            "temporar",
            "overloaded",
            "service unavailable",
        )
        return any(marker in msg for marker in retriable_markers)

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self._cb.is_open()

    @staticmethod
    def _normalize_messages_for_provider(
        messages: list[dict[str, Any]],
        *,
        enable_thinking: bool,
    ) -> list[dict[str, Any]]:
        """Normalize outbound messages for provider compatibility.

        Moonshot/Kimi rejects assistant tool-call messages when thinking mode is
        enabled and ``reasoning_content`` is absent. We defensively ensure that
        field exists for every assistant tool-call message.
        """
        normalized: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                normalized.append(message)
                continue

            entry: dict[str, Any] = dict(message)
            if entry.get("role") == "assistant" and entry.get("tool_calls"):
                entry.setdefault("content", "")
                if enable_thinking and "reasoning_content" not in entry:
                    entry["reasoning_content"] = entry.get("thinking") or "[reasoning_unavailable]"

            normalized.append(entry)

        return normalized

    def estimate_tokens_for_messages(
        self,
        *,
        model: str | None,
        messages: list[dict[str, Any]],
    ) -> int:
        """Estimate prompt tokens for telemetry/accounting when provider usage is missing."""
        resolved_model, _ = self._resolve_model(model or self.config.default_model)
        try:
            estimated = token_counter(model=resolved_model, messages=messages)
            return int(estimated or 0)
        except Exception:
            text = " ".join(str(m.get("content", "")) for m in messages)
            return max(1, int(len(text.split()) * 1.35)) if text.strip() else 0

    def estimate_tokens_for_text(
        self,
        *,
        model: str | None,
        text: str,
    ) -> int:
        """Estimate completion tokens for plain generated text."""
        if not text or not text.strip():
            return 0
        resolved_model, _ = self._resolve_model(model or self.config.default_model)
        try:
            estimated = token_counter(
                model=resolved_model,
                messages=[{"role": "assistant", "content": text}],
            )
            return int(estimated or 0)
        except Exception:
            return max(1, int(len(text.split()) * 1.35))

    # Default timeout for LLM calls (seconds). Override via config.
    LLM_TIMEOUT: float = 120.0

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> LLMResponse:
        """
        Send a completion request to the LLM.

        Args:
            messages: Chat messages [{role, content}]
            model: Model to use (resolved via models.yaml)
            temperature: Override temperature
            max_tokens: Override max tokens
            tools: Tool definitions for function calling
            enable_thinking: Request thinking/reasoning tokens

        Returns:
            LLMResponse with content, thinking, tool_calls, usage stats
        """
        if self._is_circuit_open():
            raise LLMError("Circuit breaker open — too many consecutive failures")

        candidates = self._build_model_candidates(model)
        last_error: Exception | None = None

        for idx, candidate in enumerate(candidates):
            resolved_model, model_extra = self._resolve_model(candidate)

            provider_messages = self._normalize_messages_for_provider(
                messages,
                enable_thinking=enable_thinking,
            )

            kwargs: dict[str, Any] = {
                "model": resolved_model,
                "messages": provider_messages,
                "temperature": temperature or self.config.default_temperature,
                "max_tokens": max_tokens or self.config.default_max_tokens,
                "drop_params": True,  # let litellm drop unsupported params per provider
            }
            kwargs.update(model_extra)

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            if enable_thinking:
                from aria_engine.thinking import build_thinking_params
                thinking_params = build_thinking_params(resolved_model, enable=True)
                kwargs.update(thinking_params)

            start = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    acompletion(**kwargs),
                    timeout=self.LLM_TIMEOUT,
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)
                self._cb.record_success()
                safe_fire_and_forget(self._cb_persist(), name="cb-persist-success")
                self._latency_samples.append(elapsed_ms)

                choice = response.choices[0]
                content = choice.message.content or ""
                thinking = getattr(choice.message, "reasoning_content", None)

                if not thinking:
                    from aria_engine.thinking import extract_thinking_from_response
                    thinking = extract_thinking_from_response(response)
                    if thinking:
                        from aria_engine.thinking import strip_thinking_from_content
                        content = strip_thinking_from_content(content)

                tool_calls_raw = getattr(choice.message, "tool_calls", None)
                tool_calls = None
                if tool_calls_raw:
                    tool_calls = [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls_raw
                    ]

                usage = response.usage or {}

                if idx > 0:
                    logger.warning(
                        "LLM completion fallback succeeded on candidate %s (attempt %d/%d)",
                        candidate,
                        idx + 1,
                        len(candidates),
                    )
                    # ARIA-REV-117: Record fallback metric
                    try:
                        from aria_engine.metrics import METRICS
                        METRICS.llm_fallback_total.labels(
                            primary_model=candidates[0],
                            fallback_model=candidate,
                        ).inc()
                    except Exception:
                        pass

                return LLMResponse(
                    content=content,
                    thinking=thinking,
                    tool_calls=tool_calls,
                    model=resolved_model,
                    input_tokens=getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "completion_tokens", 0),
                    cost_usd=(getattr(response, "_hidden_params", {}).get("response_cost") or 0.0),
                    latency_ms=elapsed_ms,
                    finish_reason=choice.finish_reason or "",
                )

            except Exception as e:
                self._cb.record_failure()
                safe_fire_and_forget(self._cb_persist(), name="cb-persist-failure")
                last_error = e
                retriable = isinstance(e, asyncio.TimeoutError) or self._is_retriable_error(e)
                has_next = idx < len(candidates) - 1
                logger.error(
                    "LLM completion failed on candidate %s (attempt %d/%d, retriable=%s): %s",
                    candidate,
                    idx + 1,
                    len(candidates),
                    retriable,
                    e,
                )
                if has_next and retriable:
                    continue
                if isinstance(e, asyncio.TimeoutError):
                    raise LLMError(f"LLM completion timed out after {self.LLM_TIMEOUT}s")
                raise LLMError(f"LLM completion failed: {e}") from e

        if isinstance(last_error, asyncio.TimeoutError):
            raise LLMError(f"LLM completion timed out after {self.LLM_TIMEOUT}s")
        raise LLMError(f"LLM completion failed: {last_error}")

    async def stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        enable_thinking: bool = False,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream a completion response chunk by chunk.

        Yields StreamChunk objects with content/thinking deltas.
        """
        if self._is_circuit_open():
            raise LLMError("Circuit breaker open — too many consecutive failures")

        candidates = self._build_model_candidates(model)
        last_error: Exception | None = None

        for idx, candidate in enumerate(candidates):
            resolved_model, model_extra = self._resolve_model(candidate)

            provider_messages = self._normalize_messages_for_provider(
                messages,
                enable_thinking=enable_thinking,
            )

            kwargs: dict[str, Any] = {
                "model": resolved_model,
                "messages": provider_messages,
                "temperature": temperature or self.config.default_temperature,
                "max_tokens": max_tokens or self.config.default_max_tokens,
                "stream": True,
                "drop_params": True,  # let litellm drop unsupported params per provider
            }
            kwargs.update(model_extra)

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            if enable_thinking:
                from aria_engine.thinking import build_thinking_params
                thinking_params = build_thinking_params(resolved_model, enable=True)
                kwargs.update(thinking_params)

            streamed_any_chunk = False
            try:
                response = await asyncio.wait_for(
                    acompletion(**kwargs),
                    timeout=self.LLM_TIMEOUT,
                )

                async for chunk in response:
                    streamed_any_chunk = True
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    tool_call_delta = None
                    delta_tool_calls = getattr(delta, "tool_calls", None)
                    if delta_tool_calls:
                        first_tc = delta_tool_calls[0]
                        tool_call_delta = {
                            "index": getattr(first_tc, "index", None),
                            "id": getattr(first_tc, "id", None),
                            "function": {
                                "name": getattr(getattr(first_tc, "function", None), "name", None),
                                "arguments": getattr(getattr(first_tc, "function", None), "arguments", None),
                            },
                        }

                    yield StreamChunk(
                        content=getattr(delta, "content", "") or "",
                        thinking=getattr(delta, "reasoning_content", "") or "",
                        tool_call_delta=tool_call_delta,
                        finish_reason=chunk.choices[0].finish_reason,
                        is_thinking=bool(getattr(delta, "reasoning_content", "")),
                    )

                self._cb.record_success()
                safe_fire_and_forget(self._cb_persist(), name="cb-persist-stream-ok")
                if idx > 0:
                    logger.warning(
                        "LLM streaming fallback succeeded on candidate %s (attempt %d/%d)",
                        candidate,
                        idx + 1,
                        len(candidates),
                    )
                    # ARIA-REV-117: Record fallback metric
                    try:
                        from aria_engine.metrics import METRICS
                        METRICS.llm_fallback_total.labels(
                            primary_model=candidates[0],
                            fallback_model=candidate,
                        ).inc()
                    except Exception:
                        pass
                return

            except Exception as e:
                self._cb.record_failure()
                safe_fire_and_forget(self._cb_persist(), name="cb-persist-stream-fail")
                last_error = e

                retriable = isinstance(e, asyncio.TimeoutError) or self._is_retriable_error(e)
                has_next = idx < len(candidates) - 1

                # If we've already emitted any chunk, we cannot safely switch
                # providers mid-stream without breaking turn semantics.
                if streamed_any_chunk:
                    if isinstance(e, asyncio.TimeoutError):
                        raise LLMError(f"LLM streaming timed out after {self.LLM_TIMEOUT}s")
                    raise LLMError(f"LLM streaming failed: {e}") from e

                logger.error(
                    "LLM streaming failed on candidate %s (attempt %d/%d, retriable=%s): %s",
                    candidate,
                    idx + 1,
                    len(candidates),
                    retriable,
                    e,
                )
                if has_next and retriable:
                    continue
                if isinstance(e, asyncio.TimeoutError):
                    raise LLMError(f"LLM streaming timed out after {self.LLM_TIMEOUT}s")
                raise LLMError(f"LLM streaming failed: {e}") from e

        if isinstance(last_error, asyncio.TimeoutError):
            raise LLMError(f"LLM streaming timed out after {self.LLM_TIMEOUT}s")
        raise LLMError(f"LLM streaming failed: {last_error}")

    def get_stats(self) -> dict[str, Any]:
        """Return gateway statistics."""
        return {
            "circuit_breaker": str(self._cb),
            "circuit_open": self._is_circuit_open(),
            "latency_samples": len(self._latency_samples),
        }
