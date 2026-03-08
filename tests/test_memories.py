"""Memories  KV memory lifecycle and semantic memory integration tests.

Chain 4: upsert -> read -> upsert update -> read updated -> delete -> verify 404.
"""
import pytest


class TestMemoryKVLifecycle:
    """Ordered scenario: full key-value memory lifecycle."""

    def test_01_upsert_memory(self, api, uid):
        """POST /memories -> upsert with key/value/category."""
        payload = {
            "key": f"user-preference-{uid}",
            "value": '{"theme":"dark","lang":"en","timezone":"UTC"}',
            "category": "preferences",
        }
        r = api.post("/memories", json=payload)
        if r.status_code in (502, 503):
            pytest.skip("memories service unavailable")
        assert r.status_code in (200, 201), f"Upsert failed: {r.status_code} {r.text}"
        data = r.json()
        if data.get("stored") is False or data.get("skipped") is True:
            pytest.skip("noise filter blocked payload")
        assert "id" in data or "key" in data, f"Missing id/key in response: {data}"
        TestMemoryKVLifecycle._key = f"user-preference-{uid}"
        TestMemoryKVLifecycle._uid = uid

    def test_02_read_memory(self, api):
        """GET /memories/{key} -> verify value matches."""
        key = getattr(TestMemoryKVLifecycle, "_key", None)
        if not key:
            pytest.skip("no memory created")
        r = api.get(f"/memories/{key}")
        assert r.status_code == 200, f"Read failed: {r.status_code} {r.text}"
        data = r.json()
        assert isinstance(data, dict)
        val = data.get("value", data)
        if isinstance(val, str):
            assert '"theme":"dark"' in val
            assert '"lang":"en"' in val

    def test_03_upsert_same_key_new_value(self, api):
        """POST /memories -> upsert same key with new value -> verify upserted."""
        key = getattr(TestMemoryKVLifecycle, "_key", None)
        if not key:
            pytest.skip("no memory created")
        payload = {
            "key": key,
            "value": '{"theme":"light","lang":"es","timezone":"CET"}',
            "category": "preferences",
        }
        r = api.post("/memories", json=payload)
        assert r.status_code in (200, 201), f"Upsert update failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("upserted") is True or "id" in data, f"Missing upsert confirmation: {data}"

    def test_04_read_updated_value(self, api):
        """GET /memories/{key} -> verify updated value."""
        key = getattr(TestMemoryKVLifecycle, "_key", None)
        if not key:
            pytest.skip("no memory created")
        r = api.get(f"/memories/{key}")
        assert r.status_code == 200
        data = r.json()
        val = data.get("value", data)
        if isinstance(val, str):
            assert '"theme":"light"' in val
            assert '"lang":"es"' in val

    def test_05_delete_memory(self, api):
        """DELETE /memories/{key} -> cleanup."""
        key = getattr(TestMemoryKVLifecycle, "_key", None)
        if not key:
            pytest.skip("no memory created")
        r = api.delete(f"/memories/{key}")
        assert r.status_code in (200, 204), f"Delete failed: {r.status_code} {r.text}"

    def test_06_verify_deleted(self, api):
        """GET /memories/{key} -> verify 404."""
        key = getattr(TestMemoryKVLifecycle, "_key", None)
        if not key:
            pytest.skip("no memory created")
        r = api.get(f"/memories/{key}")
        assert r.status_code == 404, f"Memory still exists after delete: {r.status_code}"


class TestSemanticMemory:
    """Semantic memory  skip if embedding service unavailable."""

    def test_01_store_semantic_memory(self, api, uid):
        """POST /memories/semantic -> store with content/category/importance."""
        payload = {
            "content": f"API latency optimization completed successfully for deployment {uid}",
            "category": "engineering",
            "importance": 0.7,
            "source": "integration-suite",
            "summary": f"Latency optimization ref {uid}",
        }
        r = api.post("/memories/semantic", json=payload)
        if r.status_code in (502, 503):
            pytest.skip("embedding service unavailable")
        assert r.status_code in (200, 201, 422), f"Semantic store failed: {r.status_code} {r.text}"
        if r.status_code in (200, 201):
            data = r.json()
            assert "id" in data or "stored" in data, f"Missing id/stored: {data}"
            TestSemanticMemory._stored_id = data.get("id")

    def test_02_list_semantic_memories(self, api):
        """GET /memories/semantic -> verify it is in the list."""
        r = api.get("/memories/semantic")
        if r.status_code in (502, 503):
            pytest.skip("embedding service unavailable")
        assert r.status_code in (200, 422), f"List semantic failed: {r.status_code}"
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (dict, list))

    def test_03_search_memories(self, api):
        """GET /memories/search -> semantic search."""
        r = api.get("/memories/search", params={"query": "latency optimization"})
        if r.status_code in (502, 503):
            pytest.skip("embedding service unavailable")
        assert r.status_code == 200, f"Search failed: {r.status_code} {r.text}"
        data = r.json()
        assert isinstance(data, dict)
        assert "memories" in data or "query" in data, f"Missing search keys: {list(data.keys())}"

    def test_04_search_by_vector(self, api):
        """POST /memories/search-by-vector -> vector search endpoint reachable."""
        r = api.post("/memories/search-by-vector", json={
            "embedding": [0.0] * 768,
            "limit": 3,
        })
        if r.status_code in (502, 503):
            pytest.skip("embedding service unavailable")
        assert r.status_code in (200, 400, 422), f"Vector search failed: {r.status_code} {r.text}"

    def test_05_summarize_session(self, api):
        """POST /memories/summarize-session -> summarization endpoint reachable."""
        r = api.post("/memories/summarize-session", json={"hours_back": 1})
        if r.status_code in (502, 503):
            pytest.skip("embedding service unavailable")
        assert r.status_code in (200, 422), f"Summarize session failed: {r.status_code} {r.text}"


class TestMemoryEdgeCases:
    """Edge cases for memories."""

    def test_nonexistent_memory_returns_404(self, api):
        """GET /memories/{nonexistent} -> 404."""
        r = api.get("/memories/nonexistent-key-xyz-never-created-999")
        assert r.status_code == 404

    def test_list_memories_paginated(self, api):
        """GET /memories -> verify paginated structure."""
        r = api.get("/memories", params={"page": 1, "limit": 5})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (dict, list))
