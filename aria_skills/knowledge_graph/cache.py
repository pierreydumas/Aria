"""
Knowledge Graph Cache Layer

LRU cache with TTL for entity lookups and traversal queries.
Designed by Aria (kg_cache_design.md), integrated into the KG skill.

Benchmarked: 73% avg speedup, 85% hit rate (kg_cache_experiment_report.md).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LRUCache:
    """Thread-safe LRU cache with TTL-based expiration."""

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 600):
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
            now = datetime.now(timezone.utc)
            self._cache[key] = {
                "value": value,
                "expires_at": now + timedelta(seconds=self.ttl_seconds),
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

    def delete_matching(self, substring: str) -> int:
        """Delete all entries whose key contains *substring* (case-insensitive)."""
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


class KGCacheManager:
    """
    Coordinates entity and traversal caches for the KnowledgeGraphSkill.

    Usage:
        cache = KGCacheManager()

        # entity lookup
        cached = cache.get_entity("person:najia")
        if cached is None:
            entity = await api_call(...)
            cache.put_entity(entity)

        # traversal
        cached = cache.get_traversal("najia", depth=2)
        if cached is None:
            result = await api_traverse(...)
            cache.put_traversal("najia", 2, result)

        # invalidation on write
        cache.invalidate("najia")
    """

    def __init__(
        self,
        entity_maxsize: int = 1000,
        entity_ttl: int = 600,
        traversal_maxsize: int = 500,
        traversal_ttl: int = 300,
    ):
        self._entities = LRUCache(maxsize=entity_maxsize, ttl_seconds=entity_ttl)
        self._traversals = LRUCache(maxsize=traversal_maxsize, ttl_seconds=traversal_ttl)

    # ── Entity cache ────────────────────────────────────────────

    @staticmethod
    def _entity_key(entity_id: str) -> str:
        return f"ent:id:{entity_id}"

    @staticmethod
    def _entity_name_key(name: str, entity_type: str) -> str:
        return f"ent:{entity_type}:{name}".lower()

    def get_entity(self, entity_id: str) -> Optional[dict]:
        return self._entities.get(self._entity_key(entity_id))

    def get_entity_by_name(self, name: str, entity_type: str) -> Optional[dict]:
        return self._entities.get(self._entity_name_key(name, entity_type))

    def put_entity(self, entity: dict) -> None:
        eid = entity.get("id", "")
        name = entity.get("name", "")
        etype = entity.get("type", "")
        if eid:
            self._entities.put(self._entity_key(eid), entity)
        if name and etype:
            self._entities.put(self._entity_name_key(name, etype), entity)

    # ── Traversal cache ─────────────────────────────────────────

    @staticmethod
    def _traversal_key(
        entity_name: str,
        depth: int,
        relation: str | None = None,
        entity_type: str | None = None,
    ) -> str:
        raw = f"{entity_name}|{depth}|{relation or ''}|{entity_type or ''}"
        return f"trav:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    def get_traversal(
        self,
        entity_name: str,
        depth: int,
        relation: str | None = None,
        entity_type: str | None = None,
    ) -> Optional[dict]:
        key = self._traversal_key(entity_name, depth, relation, entity_type)
        return self._traversals.get(key)

    def put_traversal(
        self,
        entity_name: str,
        depth: int,
        result: dict,
        relation: str | None = None,
        entity_type: str | None = None,
    ) -> None:
        key = self._traversal_key(entity_name, depth, relation, entity_type)
        self._traversals.put(key, result)

    # ── Invalidation ────────────────────────────────────────────

    def invalidate(self, entity_name: str) -> int:
        """Invalidate all cache entries related to *entity_name*."""
        count = self._entities.delete_matching(entity_name)
        count += self._traversals.delete_matching(entity_name)
        if count:
            logger.debug("KG cache: invalidated %d entries for %s", count, entity_name)
        return count

    def clear(self) -> None:
        self._entities.clear()
        self._traversals.clear()
        logger.info("KG cache: all entries cleared")

    # ── Stats ───────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        e = self._entities.stats
        t = self._traversals.stats
        return {
            "entity_cache": e,
            "traversal_cache": t,
            "total_items": e["size"] + t["size"],
        }


# ── Module-level singleton ──────────────────────────────────────
# All code paths (api_client, kernel_router, KG skill) share one cache.

_shared_cache: KGCacheManager | None = None
_shared_lock = threading.Lock()


def get_shared_cache() -> KGCacheManager:
    """Return the process-wide KGCacheManager singleton."""
    global _shared_cache
    if _shared_cache is None:
        with _shared_lock:
            if _shared_cache is None:
                _shared_cache = KGCacheManager()
                logger.info("KG cache: shared singleton created")
    return _shared_cache
