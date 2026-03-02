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
from typing import Any, AsyncIterator

import litellm
from litellm import acompletion, token_counter

from aria_engine.config import EngineConfig
from aria_engine.circuit_breaker import CircuitBreaker
from aria_engine.exceptions import LLMError
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
        response = await gateway.complete(messages, model="step-35-flash-free")

        # Streaming:
        async for chunk in gateway.stream(messages, model="qwen3-mlx"):
            print(chunk.content, end="")
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._models_config: dict[str, Any] | None = None
        self._cb = CircuitBreaker(name="llm", threshold=5, reset_after=30.0)
        self._latency_samples: list[float] = []
        # Manual circuit-breaker state used by stream()
        self._circuit_failures: int = 0
        self._circuit_threshold: int = 5
        self._circuit_opened_at: float = 0.0

        # Configure litellm
        # Note: Do NOT set litellm.api_base globally — each model specifies
        # its own api_base/api_key in models.yaml.  The global api_base would
        # override per-call kwargs for providers that use a different base URL.
        litellm.api_key = config.litellm_master_key
        litellm.drop_params = True  # Don't fail on unsupported params

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
        """Get fallback model chain from models.yaml."""
        routing = get_routing_config()
        fallbacks = routing.get("fallbacks", [])
        return [self._resolve_model(m)[0] for m in fallbacks]

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self._cb.is_open()

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

        resolved_model, model_extra = self._resolve_model(model or self.config.default_model)

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature or self.config.default_temperature,
            "max_tokens": max_tokens or self.config.default_max_tokens,
            "drop_params": True,  # let litellm drop unsupported params per provider
        }
        # Per-model api_key / api_base from models.yaml
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
            self._latency_samples.append(elapsed_ms)

            choice = response.choices[0]
            content = choice.message.content or ""
            thinking = getattr(choice.message, "reasoning_content", None)

            # Also check for thinking tag extraction
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

        except asyncio.TimeoutError:
            self._cb.record_failure()
            logger.error("LLM call timed out after %.0fs (failures=%d)", self.LLM_TIMEOUT, self._cb.failure_count)
            raise LLMError(f"LLM completion timed out after {self.LLM_TIMEOUT}s")
        except Exception as e:
            self._cb.record_failure()
            logger.error("LLM call failed (failures=%d): %s", self._cb.failure_count, e)
            raise LLMError(f"LLM completion failed: {e}") from e

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

        resolved_model, model_extra = self._resolve_model(model or self.config.default_model)

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature or self.config.default_temperature,
            "max_tokens": max_tokens or self.config.default_max_tokens,
            "stream": True,
            "drop_params": True,  # let litellm drop unsupported params per provider
        }
        # Per-model api_key / api_base from models.yaml
        kwargs.update(model_extra)

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if enable_thinking:
            from aria_engine.thinking import build_thinking_params
            thinking_params = build_thinking_params(resolved_model, enable=True)
            kwargs.update(thinking_params)

        try:
            response = await asyncio.wait_for(
                acompletion(**kwargs),
                timeout=self.LLM_TIMEOUT,
            )

            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                yield StreamChunk(
                    content=getattr(delta, "content", "") or "",
                    thinking=getattr(delta, "reasoning_content", "") or "",
                    tool_call_delta=None,  # TODO: streaming tool calls
                    finish_reason=chunk.choices[0].finish_reason,
                    is_thinking=bool(getattr(delta, "reasoning_content", "")),
                )

            self._circuit_failures = 0

        except asyncio.TimeoutError:
            self._circuit_failures += 1
            if self._circuit_failures >= self._circuit_threshold:
                self._circuit_opened_at = time.monotonic()
            raise LLMError(f"LLM streaming timed out after {self.LLM_TIMEOUT}s")
        except Exception as e:
            self._circuit_failures += 1
            if self._circuit_failures >= self._circuit_threshold:
                self._circuit_opened_at = time.monotonic()
            raise LLMError(f"LLM streaming failed: {e}") from e

    def get_stats(self) -> dict[str, Any]:
        """Return gateway statistics."""
        return {
            "circuit_failures": self._circuit_failures,
            "circuit_open": self._is_circuit_open(),
            "latency_samples": len(self._latency_samples),
        }
