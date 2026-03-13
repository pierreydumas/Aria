"""Tests for the KG cache layer (cache.py)."""
from __future__ import annotations

import time
import pytest
from aria_skills.knowledge_graph.cache import LRUCache, KGCacheManager


# ---------------------------------------------------------------------------
# LRUCache
# ---------------------------------------------------------------------------

class TestLRUCache:
    def test_put_get(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        c.put("a", {"val": 1})
        assert c.get("a") == {"val": 1}

    def test_miss(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        assert c.get("missing") is None
        assert c.stats["misses"] == 1

    def test_eviction_at_capacity(self):
        c = LRUCache(maxsize=2, ttl_seconds=60)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)  # should evict "a"
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3
        assert c.stats["evictions"] == 1

    def test_lru_order(self):
        c = LRUCache(maxsize=2, ttl_seconds=60)
        c.put("a", 1)
        c.put("b", 2)
        c.get("a")       # touch "a", making "b" least recent
        c.put("c", 3)    # should evict "b"
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_ttl_expiry(self):
        c = LRUCache(maxsize=10, ttl_seconds=1)
        c.put("x", "val")
        assert c.get("x") == "val"
        time.sleep(1.1)
        assert c.get("x") is None

    def test_delete(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        c.put("k", 42)
        assert c.delete("k") is True
        assert c.get("k") is None
        assert c.delete("nope") is False

    def test_delete_matching(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        c.put("entity:python", 1)
        c.put("entity:rust", 2)
        c.put("traversal:python:1", 3)
        assert c.delete_matching("python") == 2
        assert c.get("entity:python") is None
        assert c.get("entity:rust") == 2

    def test_clear(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        c.put("a", 1)
        c.put("b", 2)
        c.clear()
        assert c.stats["size"] == 0

    def test_hit_rate(self):
        c = LRUCache(maxsize=10, ttl_seconds=60)
        c.put("a", 1)
        c.get("a")   # hit
        c.get("a")   # hit
        c.get("b")   # miss
        assert c.stats["hits"] == 2
        assert c.stats["misses"] == 1
        assert c.stats["hit_rate"] == pytest.approx(2 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# KGCacheManager
# ---------------------------------------------------------------------------

class TestKGCacheManager:
    def test_entity_roundtrip(self):
        m = KGCacheManager()
        entity = {"id": "concept:python", "name": "Python", "type": "concept"}
        m.put_entity(entity)
        assert m.get_entity("concept:python") == entity
        assert m.get_entity_by_name("Python", "concept") == entity

    def test_traversal_roundtrip(self):
        m = KGCacheManager()
        result = {"entities": [{"id": "a"}], "relations": [], "total_entities": 1, "total_relations": 0}
        m.put_traversal("Python", 2, result)
        assert m.get_traversal("Python", 2) == result
        assert m.get_traversal("Python", 1) is None  # different depth = miss

    def test_traversal_with_filters(self):
        m = KGCacheManager()
        r1 = {"entities": [{"id": "a"}]}
        r2 = {"entities": [{"id": "b"}]}
        m.put_traversal("Python", 1, r1, relation="uses")
        m.put_traversal("Python", 1, r2, relation="knows")
        assert m.get_traversal("Python", 1, relation="uses") == r1
        assert m.get_traversal("Python", 1, relation="knows") == r2

    def test_invalidate(self):
        m = KGCacheManager()
        m.put_entity({"id": "concept:python", "name": "Python", "type": "concept"})
        m.put_traversal("Python", 1, {"x": 1})
        count = m.invalidate("python")
        assert count >= 1
        assert m.get_entity("concept:python") is None

    def test_clear(self):
        m = KGCacheManager()
        m.put_entity({"id": "a:b", "name": "B", "type": "a"})
        m.put_traversal("B", 1, {"x": 1})
        m.clear()
        assert m.stats["total_items"] == 0

    def test_stats(self):
        m = KGCacheManager()
        m.put_entity({"id": "a:x", "name": "X", "type": "a"})
        m.get_entity("a:x")       # hit
        m.get_entity("missing")   # miss
        s = m.stats
        assert s["entity_cache"]["hits"] == 1
        assert s["entity_cache"]["misses"] == 1
        assert s["total_items"] == 2  # two cache keys for one entity (id + name:type)
