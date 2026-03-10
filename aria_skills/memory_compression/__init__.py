# aria_skills/memory_compression/__init__.py
"""
Hierarchical Memory Compression — Full Production Implementation.

Three-tier compression system:
  raw     → Last 20 messages (verbatim, high-value)
  recent  → Last 100 messages (compressed to ~30%)
  archive → Everything older (compressed to ~10%)

Reduces token usage by 70%+ while preserving key facts, decisions,
and user preferences. Uses api_client for LLM summaries and semantic
storage — fully integrated with existing pgvector infrastructure.
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry

# Load default compression model from models.yaml (single source of truth)
try:
    from aria_models.loader import (
        get_primary_model as _get_primary,
        get_task_model as _get_task_model,
        normalize_temperature as _normalize_temperature,
    )
    _DEFAULT_COMPRESSION_MODEL = _get_primary()
except Exception:
    _DEFAULT_COMPRESSION_MODEL = ""
    def _get_task_model(task: str) -> str:
        return ""
    def _normalize_temperature(model_id: str, temperature: float | None) -> float | None:
        return temperature


# ═══════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """Raw memory entry for compression."""
    id: str
    content: str
    category: str
    timestamp: datetime
    importance_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryEntry":
        ts = d.get("timestamp") or d.get("created_at") or datetime.now(timezone.utc).isoformat()
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return cls(
            id=str(d.get("id", "")),
            content=d.get("content", ""),
            category=d.get("category", "general"),
            timestamp=ts,
            importance_score=float(d.get("importance_score", d.get("importance", 0.5))),
            metadata=d.get("metadata", {}),
        )


def _extract_message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts).strip()
    return ""


@dataclass
class CompressedMemory:
    """Compressed memory summary."""
    tier: str  # "raw", "recent", "archive"
    summary: str
    original_count: int
    compressed_count: int
    key_entities: list[str]
    timestamp: datetime
    key_facts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    original_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class CompressionResult:
    """Result of compression operation."""
    success: bool
    memories_processed: int
    compressed_count: int
    compression_ratio: float
    tiers_updated: dict[str, int]
    tokens_saved_estimate: int = 0
    errors: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Importance Scoring
# ═══════════════════════════════════════════════════════════════════

class ImportanceScorer:
    """Score memories by importance to decide what to keep/compress."""

    RECENCY_WEIGHT = 0.4
    SIGNIFICANCE_WEIGHT = 0.3
    CATEGORY_WEIGHT = 0.2
    LENGTH_WEIGHT = 0.1

    CATEGORY_IMPORTANCE = {
        "user_command": 1.0, "goal": 1.0, "decision": 0.9, "preference": 0.9,
        "error": 0.8, "reflection": 0.7, "episodic": 0.6, "sentiment": 0.6,
        "social": 0.5, "context": 0.4, "general": 0.5, "system": 0.3,
    }

    def score(self, memory: MemoryEntry, now: datetime | None = None) -> float:
        """Calculate importance score (0.0-1.0)."""
        if now is None:
            now = datetime.now(timezone.utc)

        age_hours = max(0, (now - memory.timestamp).total_seconds() / 3600)
        recency = max(0.1, min(1.0, 2.0 ** (-age_hours / 4)))
        significance = memory.importance_score
        category_mult = self.CATEGORY_IMPORTANCE.get(memory.category, 0.5)

        content_len = len(memory.content)
        if content_len < 20:
            length_score = 0.3
        elif content_len <= 500:
            length_score = 1.0
        else:
            length_score = 0.7

        total = (
            recency * self.RECENCY_WEIGHT
            + significance * self.SIGNIFICANCE_WEIGHT
            + category_mult * self.CATEGORY_WEIGHT
            + length_score * self.LENGTH_WEIGHT
        )
        return max(0.0, min(1.0, total))


# ═══════════════════════════════════════════════════════════════════
# Compression Engine
# ═══════════════════════════════════════════════════════════════════

class MemoryCompressor:
    """
    Hierarchical memory compression system.
    """

    def __init__(
        self,
        raw_limit: int = 20,
        recent_limit: int = 100,
        compression_ratios: dict[str, float] | None = None,
        api_client=None,
    ):
        self.raw_limit = raw_limit
        self.recent_limit = recent_limit
        self.compression_ratios = compression_ratios or {"recent": 0.3, "archive": 0.1}
        self._api = api_client
        self.scorer = ImportanceScorer()

    async def compress_tier(
        self, memories: list[MemoryEntry], target_tier: str, target_count: int,
    ) -> list[CompressedMemory]:
        if not memories:
            return []

        now = datetime.now(timezone.utc)
        scored = [(m, self.scorer.score(m, now)) for m in memories]
        scored.sort(key=lambda x: x[1], reverse=True)

        ratio = self.compression_ratios.get(target_tier, 0.3)
        keep_count = max(1, int(target_count / ratio))
        to_compress = scored[:keep_count]

        compressed: list[CompressedMemory] = []
        batch_size = 20

        for i in range(0, len(to_compress), batch_size):
            batch = to_compress[i: i + batch_size]
            batch_memories = [m for m, _ in batch]
            summary = await self._summarize_batch(batch_memories, target_tier)

            compressed.append(CompressedMemory(
                tier=target_tier,
                summary=summary["text"],
                original_count=len(batch_memories),
                compressed_count=1,
                key_entities=summary["entities"],
                timestamp=now,
                key_facts=summary["facts"],
                original_ids=[m.id for m in batch_memories],
            ))

        return compressed

    async def _summarize_batch(self, memories: list[MemoryEntry], tier: str) -> dict[str, Any]:
        contents = [m.content for m in memories]
        categories = [m.category for m in memories]

        if self._api:
            try:
                return await self._llm_summarize(contents, tier)
            except Exception:
                pass
        return self._rule_based_summary(contents, categories)

    async def _llm_summarize(self, contents: list[str], tier: str) -> dict[str, Any]:
        import httpx

        litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000")
        litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")

        instruction = (
            "Summarize these conversation excerpts into a concise paragraph. "
            "Preserve key facts, decisions, and user preferences. "
            'Return JSON: {"summary": "...", "entities": [...], "facts": [...]}'
        ) if tier == "recent" else (
            "Extract the most important persistent knowledge from these memories. "
            "Focus on long-term facts, preferences, and recurring patterns. "
            "Be extremely concise. Return JSON."
        )

        prompt = instruction + "\n\nMemories:\n" + "\n".join(f"- {c}" for c in contents[:20])
        fallback_model = _get_task_model("local_fast") or _get_primary()
        candidate_models = [_DEFAULT_COMPRESSION_MODEL or fallback_model]
        if fallback_model not in candidate_models:
            candidate_models.append(fallback_model)

        async with httpx.AsyncClient(timeout=60) as client:
            raw = ""
            last_error: Exception | None = None
            for candidate_model in candidate_models:
                try:
                    resp = await client.post(
                        f"{litellm_url}/v1/chat/completions",
                        json={
                            "model": candidate_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 1500,
                            "temperature": _normalize_temperature(candidate_model, 0.3),
                        },
                        headers={"Authorization": f"Bearer {litellm_key}"},
                    )
                    resp.raise_for_status()
                    message = resp.json().get("choices", [{}])[0].get("message", {})
                    raw = _extract_message_text(message)
                    if raw:
                        break
                    last_error = ValueError(
                        f"{candidate_model} returned empty content"
                    )
                except Exception as exc:
                    last_error = exc

            if not raw:
                raise last_error or ValueError("empty compression summary response")

            json_match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                return {
                    "text": parsed.get("summary", raw.strip()),
                    "entities": parsed.get("entities", []),
                    "facts": parsed.get("facts", []),
                }

        return self._rule_based_summary(contents, [])

    def _rule_based_summary(self, contents: list[str], categories: list[str]) -> dict[str, Any]:
        first_sentences: list[str] = []
        entities: set = set()

        for c in contents:
            first = c.split(".")[0][:100]
            if first and first not in first_sentences:
                first_sentences.append(first)
            for word in c.split():
                if word.istitle() and len(word) > 2:
                    entities.add(word.strip(".,!?;:"))

        cat_label = categories[0] if categories else "general"
        summary = f"{len(contents)} {cat_label} events. " + " ".join(first_sentences[:3])

        return {
            "text": summary[:300],
            "entities": list(entities)[:10],
            "facts": first_sentences[:5],
        }


# ═══════════════════════════════════════════════════════════════════
# Compression Manager
# ═══════════════════════════════════════════════════════════════════

class CompressionManager:

    def __init__(self, compressor: MemoryCompressor):
        self.compressor = compressor
        self.compressed_store: list[CompressedMemory] = []

    async def process_all(self, memories: list[MemoryEntry]) -> CompressionResult:
        if len(memories) < 10:
            return CompressionResult(
                success=True, memories_processed=len(memories),
                compressed_count=len(memories), compression_ratio=1.0, tiers_updated={},
            )

        memories.sort(key=lambda m: m.timestamp, reverse=True)

        raw_memories = memories[:self.compressor.raw_limit]
        recent_memories = memories[self.compressor.raw_limit:][:self.compressor.recent_limit]
        archive_memories = memories[self.compressor.raw_limit + self.compressor.recent_limit:]

        result = CompressionResult(
            success=True, memories_processed=len(memories),
            compressed_count=0, compression_ratio=0, tiers_updated={},
        )

        if recent_memories:
            recent_compressed = await self.compressor.compress_tier(
                recent_memories, "recent", self.compressor.recent_limit)
            self.compressed_store.extend(recent_compressed)
            result.tiers_updated["recent"] = len(recent_compressed)
            result.compressed_count += len(recent_compressed)

        if archive_memories:
            archive_compressed = await self.compressor.compress_tier(
                archive_memories, "archive", max(1, len(archive_memories) // 10))
            self.compressed_store.extend(archive_compressed)
            result.tiers_updated["archive"] = len(archive_compressed)
            result.compressed_count += len(archive_compressed)

        if memories:
            result.compression_ratio = (result.compressed_count + len(raw_memories)) / len(memories)

        original_tokens = sum(len(m.content) // 4 for m in memories)
        compressed_tokens = sum(len(c.summary) // 4 for c in self.compressed_store)
        raw_tokens = sum(len(m.content) // 4 for m in raw_memories)
        result.tokens_saved_estimate = max(0, original_tokens - compressed_tokens - raw_tokens)

        return result

    def get_active_context(self, raw_memories: list[MemoryEntry]) -> dict[str, Any]:
        raw_memories.sort(key=lambda m: m.timestamp, reverse=True)
        active_raw = raw_memories[:self.compressor.raw_limit]

        recent_compressed = [c for c in self.compressed_store if c.tier == "recent"]
        archive_compressed = [c for c in self.compressed_store if c.tier == "archive"]

        parts: list[str] = []
        if archive_compressed:
            parts.append("LONG-TERM KNOWLEDGE:\n" + "\n".join(f"- {c.summary}" for c in archive_compressed[-3:]))
        if recent_compressed:
            parts.append("RECENT OVERVIEW:\n" + "\n".join(f"- {c.summary}" for c in recent_compressed[-5:]))
        if active_raw:
            parts.append("RECENT MESSAGES:\n" + "\n".join(
                f"[{m.timestamp.strftime('%H:%M')}] {m.content[:200]}" for m in active_raw[:10]))

        full_context = "\n\n".join(parts)
        return {
            "context": full_context,
            "tokens_estimate": len(full_context) // 4,
            "tiers": {"raw": len(active_raw), "recent": len(recent_compressed), "archive": len(archive_compressed)},
        }


# ═══════════════════════════════════════════════════════════════════
# Skill Class
# ═══════════════════════════════════════════════════════════════════

@SkillRegistry.register
class MemoryCompressionSkill(BaseSkill):
    """
    Hierarchical memory compression with 3-tier pipeline.

    Tools:
      compress_memories   — Compress a list of memories into tiered summaries
      compress_session    — Compress recent session activity via api_client
      get_context_budget  — Retrieve weighted context within token budget
      get_compression_stats — Stats from last compression run
    """

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config or SkillConfig(name="memory_compression"))
        self._api = None
        self._compressor: MemoryCompressor | None = None
        self._manager: CompressionManager | None = None
        self._last_result: CompressionResult | None = None

    @property
    def name(self) -> str:
        return "memory_compression"

    async def initialize(self) -> bool:
        try:
            from aria_skills.api_client import get_api_client
            self._api = await get_api_client()
        except Exception as e:
            self.logger.warning(f"API client init failed (compression works standalone): {e}")
            self._api = None

        raw_limit = int(self.config.config.get("raw_limit", 20))
        recent_limit = int(self.config.config.get("recent_limit", 100))

        self._compressor = MemoryCompressor(
            raw_limit=raw_limit, recent_limit=recent_limit, api_client=self._api)
        self._manager = CompressionManager(self._compressor)

        self._status = SkillStatus.AVAILABLE
        self.logger.info("Memory compression initialized (raw=%d, recent=%d, api=%s)",
                         raw_limit, recent_limit, self._api is not None)
        return True

    async def health_check(self) -> SkillStatus:
        if self._compressor is None:
            self._status = SkillStatus.UNAVAILABLE
        return self._status

    @logged_method()
    async def compress_memories(self, memories: list[dict[str, Any]] | None = None,
                                 store_semantic: bool = True, **kwargs) -> SkillResult:
        """Compress a list of memories through the 3-tier pipeline."""
        memories = memories or kwargs.get("memories", [])
        if not memories or len(memories) < 5:
            return SkillResult.ok({"compressed": False, "reason": "Need >= 5 memories",
                                    "memories_processed": len(memories) if memories else 0})

        mem_objects = [MemoryEntry.from_dict(m) for m in memories]
        self._manager.compressed_store.clear()
        result = await self._manager.process_all(mem_objects)
        self._last_result = result

        stored_ids: list[str] = []
        if store_semantic and self._api and result.success:
            for cm in self._manager.compressed_store:
                try:
                    r = await self._api.store_memory_semantic(
                        content=cm.summary,
                        category=f"compressed_{cm.tier}",
                        importance=0.7 if cm.tier == "archive" else 0.5,
                        source="memory_compression",
                        metadata={"tier": cm.tier, "original_count": cm.original_count,
                                  "key_entities": cm.key_entities, "key_facts": cm.key_facts,
                                  "original_ids": cm.original_ids[:10]},
                    )
                    if r.success and isinstance(r.data, dict):
                        stored_ids.append(r.data.get("id", ""))
                except Exception:
                    pass

        active_context = self._manager.get_active_context(mem_objects)
        return SkillResult.ok({
            "compressed": True,
            "memories_processed": result.memories_processed,
            "compression_ratio": round(result.compression_ratio, 3),
            "tokens_saved_estimate": result.tokens_saved_estimate,
            "tiers_updated": result.tiers_updated,
            "summaries": [cm.to_dict() for cm in self._manager.compressed_store],
            "active_context": active_context,
            "semantic_ids_stored": stored_ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @logged_method()
    async def compress_session(self, hours_back: int = 6, **kwargs) -> SkillResult:
        """Compress recent session via api_client.summarize_session()."""
        hours_back = max(1, min(48, int(kwargs.get("hours_back", hours_back))))
        if self._api is None:
            return SkillResult.fail("api_client not available")
        try:
            result = await self._api.summarize_session(hours_back=hours_back)
            if not result.success:
                return SkillResult.fail(f"Session compression failed: {result.error}")
            data = result.data or {}
            return SkillResult.ok({
                "compressed": True, "hours_back": hours_back,
                "summary": data.get("summary", ""), "decisions": data.get("decisions", []),
                "stored": data.get("stored", False), "ids": data.get("ids", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return SkillResult.fail(f"Session compression failed: {e}")

    @logged_method()
    async def get_context_budget(self, max_tokens: int = 2000, **kwargs) -> SkillResult:
        """Retrieve working memory context within a token budget."""
        max_tokens = int(kwargs.get("max_tokens", max_tokens))
        if self._api is None:
            return SkillResult.fail("api_client not available")

        try:
            result = await self._api.get_working_memory_context(limit=20)
            if not result.success:
                return SkillResult.fail(f"Context retrieval failed: {result.error}")

            items: list[dict[str, Any]] = []
            raw = result.data
            if isinstance(raw, dict):
                items = raw.get("items", raw.get("context", []))
            elif isinstance(raw, list):
                items = raw

            total_chars = 0
            selected: list[dict[str, Any]] = []
            for item in items:
                val = str(item.get("value", "")) if isinstance(item, dict) else str(item)
                chars = len(val)
                if total_chars + chars > max_tokens * 4:
                    break
                total_chars += chars
                selected.append(item)

            compressed_context = ""
            if self._manager and self._manager.compressed_store:
                summaries = [c.summary for c in self._manager.compressed_store[-5:]]
                compressed_context = "\n".join(f"- {s}" for s in summaries)
                if total_chars + len(compressed_context) <= max_tokens * 4:
                    total_chars += len(compressed_context)

            return SkillResult.ok({
                "items_count": len(selected), "total_available": len(items),
                "estimated_tokens": total_chars // 4, "budget": max_tokens,
                "items": selected, "compressed_summaries": compressed_context or None,
            })
        except Exception as e:
            return SkillResult.fail(f"Context retrieval failed: {e}")

    @logged_method()
    async def get_compression_stats(self, **kwargs) -> SkillResult:
        """Get statistics from the last compression run."""
        if self._last_result is None:
            return SkillResult.ok({"has_data": False, "message": "No compression run yet."})
        r = self._last_result
        return SkillResult.ok({
            "has_data": True, "memories_processed": r.memories_processed,
            "compressed_count": r.compressed_count,
            "compression_ratio": round(r.compression_ratio, 3),
            "tokens_saved_estimate": r.tokens_saved_estimate,
            "tiers_updated": r.tiers_updated,
            "summaries_in_store": len(self._manager.compressed_store) if self._manager else 0,
        })

    async def close(self) -> None:
        self._api = None
        self._compressor = None
        self._manager = None
        self._status = SkillStatus.UNAVAILABLE
