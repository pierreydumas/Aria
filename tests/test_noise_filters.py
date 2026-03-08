"""Noise filter behavior tests — verify that noise/test payloads are properly rejected.

The API has silent noise filters that return {skipped: true} instead of errors.
These tests verify the filters work correctly for each domain.
"""
import pytest


class TestGoalsNoiseFilter:
    """Goals noise filter blocks test-like payloads."""

    def test_test_goal_title_blocked(self, api):
        """POST /goals with 'test goal' title → skipped."""
        r = api.post("/goals", json={"title": "test goal for verification"})
        assert r.status_code in (200, 201)
        data = r.json()
        assert data.get("skipped") is True, f"Expected skipped=true, got: {data}"

    def test_test_prefix_goal_id_blocked(self, api):
        """POST /goals with 'test-*' goal_id → skipped."""
        r = api.post("/goals", json={"title": "Valid title", "goal_id": "test-goal-123"})
        assert r.status_code in (200, 201)
        data = r.json()
        assert data.get("skipped") is True, f"Expected skipped=true, got: {data}"


class TestMemoriesNoiseFilter:
    """Memories noise filter blocks test-like payloads."""

    def test_test_prefix_key_blocked(self, api):
        """POST /memories with key starting with 'test-' → skipped."""
        r = api.post("/memories", json={"key": "test-memory-xyz", "value": "{\"data\":1}"})
        assert r.status_code in (200, 201)
        data = r.json()
        assert data.get("skipped") is True or data.get("stored") is False, \
            f"Expected noise filter to block: {data}"


class TestSocialNoiseFilter:
    """Social noise filter blocks test-like payloads."""

    def test_test_post_content_blocked(self, api):
        """POST /social with 'test post' content → skipped."""
        r = api.post("/social", json={"content": "test post for verification"})
        if r.status_code in (502, 503):
            pytest.skip("social service unavailable")
        assert r.status_code in (200, 201)
        data = r.json()
        assert data.get("skipped") is True, f"Expected skipped=true, got: {data}"

    def test_metadata_test_flag_blocked(self, api):
        """POST /social with metadata.test=true → skipped."""
        r = api.post("/social", json={
            "content": "Legitimate looking content",
            "metadata": {"test": True},
        })
        if r.status_code in (502, 503):
            pytest.skip("social service unavailable")
        assert r.status_code in (200, 201)
        data = r.json()
        assert data.get("skipped") is True, f"Expected skipped=true, got: {data}"
