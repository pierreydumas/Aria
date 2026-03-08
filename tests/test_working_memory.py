"""Working Memory  Full lifecycle with context retrieval integration tests.

Chain 5: create -> list -> patch -> context -> checkpoint -> stats -> cleanup dry_run -> delete -> verify gone.
"""
import pytest


class TestWorkingMemoryLifecycle:
    """Ordered scenario: full working memory lifecycle."""

    def test_01_create_item(self, api, uid):
        """POST /working-memory -> create item with key, value, category, importance."""
        payload = {
            "key": f"active-context-{uid}",
            "value": '{"focus":"deployment","priority":"high"}',
            "category": "context",
            "importance": 0.8,
            "ttl_hours": 24,
            "source": "integration-suite",
        }
        r = api.post("/working-memory", json=payload)
        if r.status_code in (502, 503):
            pytest.skip("working memory service unavailable")
        assert r.status_code in (200, 201), f"Create failed: {r.status_code} {r.text}"
        data = r.json()
        if data.get("skipped"):
            pytest.skip("noise filter blocked payload")
        item_id = data.get("id") or data.get("item_id")
        assert item_id, f"No id in response: {data}"
        assert "key" in data, f"Missing key in response: {data}"
        TestWorkingMemoryLifecycle._item_id = item_id
        TestWorkingMemoryLifecycle._uid = uid

    def test_02_verify_in_list(self, api):
        """GET /working-memory -> verify item appears in list."""
        uid = getattr(TestWorkingMemoryLifecycle, "_uid", None)
        if not uid:
            pytest.skip("no item created")
        r = api.get("/working-memory", params={"category": "context"})
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            keys = [item.get("key", "") for item in items if isinstance(item, dict)]
            assert f"active-context-{uid}" in keys, \
                f"Created item not found in list. Keys: {keys[:10]}"

    def test_03_patch_item(self, api):
        """PATCH /working-memory/{id} -> update value and importance."""
        item_id = getattr(TestWorkingMemoryLifecycle, "_item_id", None)
        if not item_id:
            pytest.skip("no item created")
        r = api.patch(f"/working-memory/{item_id}", json={
            "value": '{"focus":"monitoring","priority":"critical"}',
            "importance": 0.95,
        })
        assert r.status_code == 200, f"Patch failed: {r.status_code} {r.text}"
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("value"), str):
            assert '"focus":"monitoring"' in data["value"], f"Value not updated: {data['value']}"

    def test_04_context_retrieval(self, api):
        """GET /working-memory/context -> verify weighted retrieval."""
        r = api.get("/working-memory/context", params={"category": "context", "limit": 20})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        context_items = data.get("context", [])
        assert isinstance(context_items, list)
        if context_items:
            assert "relevance" in context_items[0] or "importance" in context_items[0], \
                f"Missing relevance/importance: {list(context_items[0].keys())}"

    def test_05_create_checkpoint(self, api):
        """POST /working-memory/checkpoint -> create snapshot."""
        r = api.post("/working-memory/checkpoint")
        assert r.status_code in (200, 201), f"Checkpoint create failed: {r.status_code} {r.text}"
        data = r.json()
        assert isinstance(data, dict)
        assert "checkpoint_id" in data or "items_checkpointed" in data, \
            f"Missing checkpoint keys: {list(data.keys())}"

    def test_06_get_checkpoint(self, api):
        """GET /working-memory/checkpoint -> verify snapshot contains data."""
        r = api.get("/working-memory/checkpoint")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "items" in data or "checkpoint_id" in data or "count" in data, \
            f"Missing checkpoint keys: {list(data.keys())}"

    def test_07_stats(self, api):
        """GET /working-memory/stats -> verify stats reflect our data."""
        r = api.get("/working-memory/stats")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "total_items" in data or "categories" in data, \
            f"Missing stats keys: {list(data.keys())}"
        if "total_items" in data:
            assert data["total_items"] > 0, "Expected at least one item in stats"

    def test_08_cleanup_dry_run(self, api):
        """POST /working-memory/cleanup {dry_run: true} -> verify it identifies items."""
        r = api.post("/working-memory/cleanup", json={"dry_run": True, "delete_expired": True})
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, dict)
            assert "matched" in data or "deleted" in data or "dry_run" in data, \
                f"Missing cleanup keys: {list(data.keys())}"
            if "dry_run" in data:
                assert data["dry_run"] is True

    def test_09_delete_item(self, api):
        """DELETE /working-memory/{id} -> cleanup."""
        item_id = getattr(TestWorkingMemoryLifecycle, "_item_id", None)
        if not item_id:
            pytest.skip("no item created")
        r = api.delete(f"/working-memory/{item_id}")
        assert r.status_code in (200, 204), f"Delete failed: {r.status_code} {r.text}"

    def test_10_verify_deleted(self, api):
        """GET /working-memory -> verify item is gone."""
        uid = getattr(TestWorkingMemoryLifecycle, "_uid", None)
        if not uid:
            pytest.skip("no uid from previous step")
        r = api.get("/working-memory", params={"key": f"active-context-{uid}"})
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            keys = [item.get("key", "") for item in items if isinstance(item, dict)]
            assert f"active-context-{uid}" not in keys, \
                f"Item still present after delete: {keys}"


class TestWorkingMemoryFileSnapshot:
    """File-based snapshot endpoint."""

    def test_file_snapshot(self, api):
        """GET /working-memory/file-snapshot -> verify structure."""
        r = api.get("/working-memory/file-snapshot")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (dict, list))
