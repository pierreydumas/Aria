"""Engine focus profile endpoint tests."""


class TestEngineFocus:
    """Test suite for focus profile management endpoints."""

    def test_list_focus_profiles(self, api):
        """Test listing all focus profiles."""
        r = api.get("/engine/focus")
        assert r.status_code in (200, 401)  # Success or auth required
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (list, dict))

    def test_get_focus_profile(self, api):
        """Test getting single focus profile by ID."""
        r = api.get("/engine/focus/orchestrator")
        assert r.status_code in (200, 404, 401)

    def test_get_nonexistent_focus_profile(self, api):
        """Test getting nonexistent focus profile returns 404."""
        r = api.get("/engine/focus/nonexistent-focus-12345")
        assert r.status_code in (404, 401)

    def test_create_focus_profile(self, api):
        """Test creating a new focus profile."""
        payload = {
            "focus_id": "test_focus",
            "display_name": "Test Focus",
            "delegation_level": 2,
            "token_budget_hint": 30000,
            "tone": "Test tone"
        }
        r = api.post("/engine/focus", json=payload)
        assert r.status_code in (201, 401, 422)

    def test_update_focus_profile(self, api):
        """Test updating an existing focus profile."""
        payload = {"token_budget_hint": 35000}
        r = api.put("/engine/focus/orchestrator", json=payload)
        assert r.status_code in (200, 401, 404)

    def test_delete_focus_profile(self, api):
        """Test deleting a focus profile."""
        r = api.delete("/engine/focus/test_focus")
        assert r.status_code in (204, 401, 404)

    def test_activate_focus(self, api):
        """Test setting active focus level."""
        payload = {"level": "L2"}
        r = api.post("/engine/focus/active", json=payload)
        assert r.status_code in (200, 401, 422)

    def test_get_active_focus(self, api):
        """Test getting current active focus level."""
        r = api.get("/engine/focus/active")
        assert r.status_code in (200, 401)

    def test_focus_stats(self, api):
        """Test focus seed endpoint availability."""
        r = api.post("/engine/focus/seed")
        assert r.status_code in (201, 401)


# TODO: Add integration tests for focus switching
# TODO: Test token budget enforcement
# TODO: Test delegation level validation
# TODO: Test system_prompt_addon application
# TODO: Test focus switching mid-session
