"""
Memory Cache Layer — AAA++++ cache for Aria's memory retrieval.

Three-tier LRU + TTL cache sitting in front of every DB-bound memory query:
  1. **Embedding cache** — memoizes generate_embedding() calls (biggest latency win)
  2. **Semantic search cache** — caches pgvector cosine-distance results per query hash
  3. **Memory graph cache** — caches the full /memory-graph vis-network payload

Plus: embedding latency tracking, vector health monitoring,
access-pattern analytics with per-tier time-series.

Thread-safe, process-local. Modelled after aria_skills/knowledge_graph/cache.py.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.memory_cache")


# ── Generic LRU + TTL cache (reusable building block) ────────────────────────

class LRUCache:
    """Thread-safe LRU cache with per-entry TTL expiration."""

    def __init__(self, maxsize: int = 500, ttl_seconds: int = 300):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            entry = self._cache[key]
            if entry["expires_at"] < datetime.now(timezone.utc):
                del self._cache[key]
                self._evictions += 1
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return entry["value"]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = {
                "value": value,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
            }
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def invalidate_matching(self, substring: str) -> int:
        with self._lock:
            target = substring.lower()
            to_delete = [k for k in self._cache if target in k.lower()]
            for k in to_delete:
                del self._cache[k]
            return len(to_delete)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
                "ttl_seconds": self.ttl_seconds,
            }


# ── Memory Cache Manager ─────────────────────────────────────────────────────

class MemoryCacheManager:
    """
    Three-tier cache for Aria's memory pipeline.

    Tier 1 — Embeddings:
        Key: sha256(text[:512])  →  list[float]
        TTL: 1800s (30 min) — embeddings don't change for the same text.
        Max: 2000 entries

    Tier 2 — Semantic search results:
        Key: sha256(embedding[:8])  →  list[dict] (scored memories)
        TTL: 120s (2 min) — balance freshness with latency savings.
        Max: 500 entries

    Tier 3 — Memory graph payload:
        Key: f"graph:{limit}:{types}"  →  dict (full vis-network response)
        TTL: 60s — the graph changes less frequently but users expect freshness.
        Max: 20 entries
    """

    def __init__(self):
        self._embeddings = LRUCache(maxsize=2000, ttl_seconds=1800)
        self._semantic_results = LRUCache(maxsize=500, ttl_seconds=120)
        self._graph_payloads = LRUCache(maxsize=20, ttl_seconds=60)
        self._access_log: list[dict] = []
        self._access_log_lock = threading.Lock()
        self._max_log_entries = 2000
        # ── Latency tracking ────────────────────────────────────────
        self._embedding_latencies: deque[dict] = deque(maxlen=500)
        self._semantic_latencies: deque[dict] = deque(maxlen=500)
        self._latency_lock = threading.Lock()
        # ── Time-series buckets (per-minute hit/miss counts) ────────
        self._timeseries: deque[dict] = deque(maxlen=1440)  # 24h of minutes
        self._ts_lock = threading.Lock()
        self._ts_current_minute: str = ""
        self._ts_current: dict = {}
        # ── Vector health tracking ──────────────────────────────────
        self._embedding_dims_seen: dict[int, int] = {}  # dim → count
        self._fallback_count = 0
        self._remote_count = 0
        self._started_at = datetime.now(timezone.utc)

    # ── Tier 1: Embedding cache ──────────────────────────────────

    @staticmethod
    def _embedding_key(text: str) -> str:
        normalized = text.strip().lower()[:512]
        return f"emb:{hashlib.sha256(normalized.encode()).hexdigest()[:24]}"

    def get_embedding(self, text: str) -> Optional[list[float]]:
        result = self._embeddings.get(self._embedding_key(text))
        self._log_access("embedding", "hit" if result is not None else "miss")
        return result

    def put_embedding(self, text: str, embedding: list[float]) -> None:
        self._embeddings.put(self._embedding_key(text), embedding)

    def record_embedding_latency(self, latency_ms: float, source: str = "remote") -> None:
        """Record an embedding generation latency Sample (called from generate_embedding)."""
        entry = {
            "latency_ms": round(latency_ms, 2),
            "source": source,  # "remote", "fallback", "cached"
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._latency_lock:
            self._embedding_latencies.append(entry)
            if source == "fallback":
                self._fallback_count += 1
            elif source == "remote":
                self._remote_count += 1

    def record_embedding_dims(self, dims: int) -> None:
        """Track vector dimensionality for health monitoring."""
        self._embedding_dims_seen[dims] = self._embedding_dims_seen.get(dims, 0) + 1

    def record_semantic_latency(self, latency_ms: float, result_count: int, cached: bool = False) -> None:
        """Record a semantic search operation latency."""
        entry = {
            "latency_ms": round(latency_ms, 2),
            "result_count": result_count,
            "cached": cached,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._latency_lock:
            self._semantic_latencies.append(entry)

    # ── Tier 2: Semantic search results ──────────────────────────

    @staticmethod
    def _semantic_key(embedding: list[float], limit: int = 5, min_sim: float = 0.3) -> str:
        sig = ",".join(f"{v:.6f}" for v in embedding[:8])
        raw = f"{sig}|{limit}|{min_sim}"
        return f"sem:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

    def get_semantic_results(
        self, embedding: list[float], limit: int = 5, min_sim: float = 0.3
    ) -> Optional[list[dict]]:
        result = self._semantic_results.get(self._semantic_key(embedding, limit, min_sim))
        self._log_access("semantic_search", "hit" if result is not None else "miss")
        return result

    def put_semantic_results(
        self, embedding: list[float], results: list[dict], limit: int = 5, min_sim: float = 0.3
    ) -> None:
        self._semantic_results.put(self._semantic_key(embedding, limit, min_sim), results)

    # ── Tier 3: Memory graph cache ───────────────────────────────

    @staticmethod
    def _graph_key(limit: int, include_types: str) -> str:
        return f"graph:{limit}:{include_types}"

    def get_graph(self, limit: int, include_types: str) -> Optional[dict]:
        result = self._graph_payloads.get(self._graph_key(limit, include_types))
        self._log_access("memory_graph", "hit" if result is not None else "miss")
        return result

    def put_graph(self, limit: int, include_types: str, payload: dict) -> None:
        self._graph_payloads.put(self._graph_key(limit, include_types), payload)

    # ── Invalidation ─────────────────────────────────────────────

    def invalidate_semantic(self) -> int:
        """Call after new memories are written to DB."""
        count = self._semantic_results.invalidate_matching("")
        count += self._graph_payloads.invalidate_matching("")
        if count:
            logger.info("Memory cache: invalidated %d semantic/graph entries", count)
        return count

    def invalidate_all(self) -> int:
        count = 0
        for tier in (self._embeddings, self._semantic_results, self._graph_payloads):
            count += tier.stats["size"]
            tier.clear()
        logger.info("Memory cache: full clear, %d entries evicted", count)
        return count

    # ── Access log (for analytics) ───────────────────────────────

    def _log_access(self, cache_tier: str, result: str) -> None:
        now = datetime.now(timezone.utc)
        entry = {
            "tier": cache_tier,
            "result": result,
            "timestamp": now.isoformat(),
        }
        with self._access_log_lock:
            self._access_log.append(entry)
            if len(self._access_log) > self._max_log_entries:
                self._access_log = self._access_log[-self._max_log_entries:]

        # ── Time-series bucketing (per-minute) ──────────────────────
        minute_key = now.strftime("%Y-%m-%dT%H:%M")
        with self._ts_lock:
            if minute_key != self._ts_current_minute:
                if self._ts_current:
                    self._timeseries.append(self._ts_current)
                self._ts_current_minute = minute_key
                self._ts_current = {
                    "time": minute_key,
                    "embedding_hits": 0, "embedding_misses": 0,
                    "semantic_hits": 0, "semantic_misses": 0,
                    "graph_hits": 0, "graph_misses": 0,
                }
            key = f"{cache_tier.replace('_search', '')}_{result}s"
            # normalize tier names to match bucket keys
            if cache_tier == "semantic_search":
                key = f"semantic_{result}s"
            elif cache_tier == "memory_graph":
                key = f"graph_{result}s"
            else:
                key = f"{cache_tier}_{result}s"
            self._ts_current[key] = self._ts_current.get(key, 0) + 1

    def get_access_log(self, limit: int = 100) -> list[dict]:
        with self._access_log_lock:
            return list(self._access_log[-limit:])

    # ── Latency stats helpers ────────────────────────────────────

    @staticmethod
    def _percentiles(values: list[float]) -> dict[str, float]:
        if not values:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "min": 0, "max": 0, "count": 0}
        s = sorted(values)
        n = len(s)
        return {
            "p50": round(s[n // 2], 2),
            "p95": round(s[int(n * 0.95)], 2),
            "p99": round(s[int(n * 0.99)], 2),
            "avg": round(sum(s) / n, 2),
            "min": round(s[0], 2),
            "max": round(s[-1], 2),
            "count": n,
        }

    def get_latency_stats(self) -> dict[str, Any]:
        """Return latency percentiles for embedding and semantic search."""
        with self._latency_lock:
            emb_vals = [e["latency_ms"] for e in self._embedding_latencies]
            sem_vals = [e["latency_ms"] for e in self._semantic_latencies]
            emb_remote = [e["latency_ms"] for e in self._embedding_latencies if e["source"] == "remote"]
            emb_fallback = [e["latency_ms"] for e in self._embedding_latencies if e["source"] == "fallback"]
            emb_cached = [e["latency_ms"] for e in self._embedding_latencies if e["source"] == "cached"]
            sem_uncached = [e["latency_ms"] for e in self._semantic_latencies if not e["cached"]]
            sem_cached = [e["latency_ms"] for e in self._semantic_latencies if e["cached"]]
        return {
            "embedding": {
                "all": self._percentiles(emb_vals),
                "remote": self._percentiles(emb_remote),
                "fallback": self._percentiles(emb_fallback),
                "cached": self._percentiles(emb_cached),
            },
            "semantic": {
                "all": self._percentiles(sem_vals),
                "uncached": self._percentiles(sem_uncached),
                "cached": self._percentiles(sem_cached),
            },
        }

    def get_vector_health(self) -> dict[str, Any]:
        """Return vector dimensionality and source health metrics."""
        total_source = self._fallback_count + self._remote_count
        return {
            "dimensions_seen": dict(self._embedding_dims_seen),
            "expected_dims": 768,
            "dimension_consistent": len(self._embedding_dims_seen) <= 1
                                    and 768 in self._embedding_dims_seen or not self._embedding_dims_seen,
            "remote_count": self._remote_count,
            "fallback_count": self._fallback_count,
            "remote_ratio": round(self._remote_count / total_source, 4) if total_source else 1.0,
            "fallback_ratio": round(self._fallback_count / total_source, 4) if total_source else 0.0,
        }

    def get_timeseries(self, last_n: int = 60) -> list[dict]:
        """Return last N minutes of per-tier hit/miss timeseries."""
        with self._ts_lock:
            result = list(self._timeseries)
            if self._ts_current:
                result.append(self._ts_current)
        return result[-last_n:]

    # ── Stats (combined) ─────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        emb = self._embeddings.stats
        sem = self._semantic_results.stats
        graph = self._graph_payloads.stats
        total_hits = emb["hits"] + sem["hits"] + graph["hits"]
        total_misses = emb["misses"] + sem["misses"] + graph["misses"]
        total = total_hits + total_misses
        uptime = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return {
            "embedding_cache": emb,
            "semantic_cache": sem,
            "graph_cache": graph,
            "total_items": emb["size"] + sem["size"] + graph["size"],
            "total_hits": total_hits,
            "total_misses": total_misses,
            "overall_hit_rate": round(total_hits / total, 4) if total else 0.0,
            "uptime_seconds": round(uptime, 1),
            "started_at": self._started_at.isoformat(),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_shared_cache: Optional[MemoryCacheManager] = None
_shared_lock = threading.Lock()


def get_memory_cache() -> MemoryCacheManager:
    """Return the process-wide memory cache singleton."""
    global _shared_cache
    if _shared_cache is None:
        with _shared_lock:
            if _shared_cache is None:
                _shared_cache = MemoryCacheManager()
                logger.info("Memory cache manager initialized")
    return _shared_cache


# ── Shared semantic memory retrieval (used by both REST + WS paths) ──────────

SEMANTIC_MEMORY_LIMIT = 5
SEMANTIC_MEMORY_MIN_SIMILARITY = 0.3


async def retrieve_semantic_memories(db, user_message: str) -> Optional[str]:
    """Query pgvector for memories similar to *user_message*.

    Returns a formatted system-message string, or ``None``.
    Both ``ChatEngine`` (REST / cron) and ``StreamingChatEngine`` (WS)
    call this so every path benefits from the cache.
    """
    if not user_message or len(user_message.strip()) < 10:
        return None

    try:
        from db.models import SemanticMemory
        from sqlalchemy import select
        from routers.memories import generate_embedding
        import time as _time

        _mcache = get_memory_cache()

        # Tier 1 — embedding cache
        query_embedding = await generate_embedding(user_message)

        # Tier 2 — semantic-result cache
        _sem_t0 = _time.monotonic()
        cached = _mcache.get_semantic_results(
            query_embedding, SEMANTIC_MEMORY_LIMIT, SEMANTIC_MEMORY_MIN_SIMILARITY,
        )
        if cached is not None:
            _mcache.record_semantic_latency(
                (_time.monotonic() - _sem_t0) * 1000,
                result_count=len(cached), cached=True,
            )
            if not cached:
                return None
            return _format_memory_block(cached)

        # DB query (pgvector cosine distance)
        distance_col = SemanticMemory.embedding.cosine_distance(query_embedding).label("distance")
        stmt = (
            select(SemanticMemory.content, SemanticMemory.category,
                   SemanticMemory.importance, distance_col)
            .order_by("distance")
            .limit(SEMANTIC_MEMORY_LIMIT)
        )
        rows = (await db.execute(stmt)).all()

        if not rows:
            _mcache.put_semantic_results(
                query_embedding, [], SEMANTIC_MEMORY_LIMIT, SEMANTIC_MEMORY_MIN_SIMILARITY,
            )
            return None

        relevant = [
            (content, category, importance, 1 - (distance or 1.0))
            for content, category, importance, distance in rows
            if 1 - (distance or 1.0) >= SEMANTIC_MEMORY_MIN_SIMILARITY
        ]

        if not relevant:
            _mcache.put_semantic_results(
                query_embedding, [], SEMANTIC_MEMORY_LIMIT, SEMANTIC_MEMORY_MIN_SIMILARITY,
            )
            _mcache.record_semantic_latency(
                (_time.monotonic() - _sem_t0) * 1000, result_count=0, cached=False,
            )
            return None

        cache_entries = [
            {"content": c, "category": cat, "importance": float(imp), "similarity": float(sim)}
            for c, cat, imp, sim in relevant
        ]
        _mcache.put_semantic_results(
            query_embedding, cache_entries, SEMANTIC_MEMORY_LIMIT, SEMANTIC_MEMORY_MIN_SIMILARITY,
        )
        _mcache.record_semantic_latency(
            (_time.monotonic() - _sem_t0) * 1000, result_count=len(relevant), cached=False,
        )

        logger.info(
            "Semantic memory injection: %d memories retrieved (top similarity=%.3f)",
            len(relevant), relevant[0][3] if relevant else 0,
        )
        return _format_memory_block(cache_entries)

    except Exception as exc:
        logger.debug("Semantic memory retrieval failed (non-fatal): %s", exc)
        return None


def _format_memory_block(memories: list[dict]) -> str:
    lines = ["[Recalled Memories — relevant context from past experience]"]
    for mem in memories:
        text = mem["content"]
        truncated = text[:500] + "..." if len(text) > 500 else text
        lines.append(f"- [{mem['category']}] {truncated}")
    return "\n".join(lines)
