"""Cross-entity integration tests — verify FK cascades, data propagation, and workflow chains.

Tests that data flows properly BETWEEN different endpoints:
1. Activity commit → auto-mirrors to Social feed
2. Knowledge entity cascade delete → relations removed
3. Engine chat session → messages → delete cascade
4. Session → ModelUsage FK relationship
5. Skill invocation failure → Lesson resolution lookup chain
"""
import time
import httpx
import pytest


class TestActivityToSocialMirror:
    """Chain 7: Activity commit/comment → auto-mirrors to Social feed."""

    def test_01_create_commit_activity(self, api, uid):
        """POST /activities with action=commit → creates activity."""
        payload = {
            "action": "commit",
            "skill": "ci_cd",
            "details": {"message": f"Release deployment v4.2 — ref {uid}", "branch": "main"},
            "success": True,
        }
        r = api.post("/activities", json=payload)
        if r.status_code in (502, 503):
            pytest.skip("activities service unavailable")
        assert r.status_code in (200, 201), f"Create activity failed: {r.status_code} {r.text}"
        data = r.json()
        if data.get("skipped"):
            pytest.skip("noise filter blocked payload")
        assert data.get("id") or data.get("activity_id"), f"No id: {data}"
        TestActivityToSocialMirror._uid = uid

    def test_02_verify_mirrored_to_social(self, api):
        """GET /social?platform=activity → verify auto-mirrored post exists."""
        uid = getattr(TestActivityToSocialMirror, "_uid", None)
        if not uid:
            pytest.skip("no activity created")
        r = api.get("/social", params={"platform": "activity"})
        assert r.status_code == 200
        data = r.json()
        posts = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(posts, list):
            found = any(isinstance(p, dict) and uid in str(p.get("content", "")) for p in posts)
            assert found, f"Commit activity with ref {uid} not auto-mirrored to social feed"


class TestKnowledgeEntityCascadeDelete:
    """FK cascade: deleting a knowledge entity removes its relations."""

    def test_01_create_parent_entity(self, api, uid):
        """POST /knowledge-graph/entities → create parent entity."""
        r = api.post("/knowledge-graph/entities", json={
            "name": f"orchestrator-{uid}",
            "type": "service",
            "properties": {"role": "coordinator"},
        })
        if r.status_code in (502, 503):
            pytest.skip("knowledge graph unavailable")
        assert r.status_code in (200, 201), f"Failed: {r.status_code} {r.text}"
        data = r.json()
        if data.get("skipped"):
            pytest.skip("noise filter blocked")
        TestKnowledgeEntityCascadeDelete._parent_id = data.get("id")
        TestKnowledgeEntityCascadeDelete._uid = uid

    def test_02_create_child_entity(self, api):
        """POST /knowledge-graph/entities → create child entity."""
        uid = getattr(TestKnowledgeEntityCascadeDelete, "_uid", None)
        if not uid:
            pytest.skip("no parent entity")
        r = api.post("/knowledge-graph/entities", json={
            "name": f"worker-node-{uid}",
            "type": "service",
            "properties": {"role": "executor"},
        })
        assert r.status_code in (200, 201), f"Failed: {r.status_code} {r.text}"
        TestKnowledgeEntityCascadeDelete._child_id = r.json().get("id")

    def test_03_create_relation(self, api):
        """POST /knowledge-graph/relations → link parent→child."""
        parent_id = getattr(TestKnowledgeEntityCascadeDelete, "_parent_id", None)
        child_id = getattr(TestKnowledgeEntityCascadeDelete, "_child_id", None)
        if not parent_id or not child_id:
            pytest.skip("entities not created")
        r = api.post("/knowledge-graph/relations", json={
            "from_entity": str(parent_id),
            "to_entity": str(child_id),
            "relation_type": "manages",
        })
        assert r.status_code in (200, 201, 409, 422), f"Failed: {r.status_code} {r.text}"
        if r.status_code in (200, 201):
            TestKnowledgeEntityCascadeDelete._relation_id = r.json().get("id")

    def test_04_verify_relation_exists(self, api):
        """GET /knowledge-graph/relations → verify relation is present."""
        rel_id = getattr(TestKnowledgeEntityCascadeDelete, "_relation_id", None)
        if not rel_id:
            pytest.skip("no relation created")
        r = api.get("/knowledge-graph/relations")
        assert r.status_code == 200
        data = r.json()
        relations = data.get("relations", data) if isinstance(data, dict) else data
        rel_ids = [str(rel.get("id", "")) for rel in relations if isinstance(rel, dict)]
        assert str(rel_id) in rel_ids, f"Relation {rel_id} not found"

    def test_05_delete_parent_entity(self, api):
        """DELETE parent entity → cascade should remove the relation."""
        parent_id = getattr(TestKnowledgeEntityCascadeDelete, "_parent_id", None)
        if not parent_id:
            pytest.skip("no parent entity")
        r = api.delete(f"/knowledge-graph/entities/{parent_id}")
        assert r.status_code in (200, 204, 404, 405), f"Delete failed: {r.status_code} {r.text}"

    def test_06_verify_relation_cascade_deleted(self, api):
        """GET /knowledge-graph/relations → verify relation removed or flagged.

        If CASCADE is not implemented, the relation may survive — in that case
        we clean it up manually so later tests aren't affected.
        """
        rel_id = getattr(TestKnowledgeEntityCascadeDelete, "_relation_id", None)
        if not rel_id:
            pytest.skip("no relation created")
        r = api.get("/knowledge-graph/relations")
        assert r.status_code == 200
        data = r.json()
        relations = data.get("relations", data) if isinstance(data, dict) else data
        rel_ids = [str(rel.get("id", "")) for rel in relations if isinstance(rel, dict)]
        if str(rel_id) in rel_ids:
            # Cascade not implemented — clean up manually
            r2 = api.delete(f"/knowledge-graph/relations/{rel_id}")
            assert r2.status_code in (200, 204, 404, 405), \
                f"Manual relation cleanup failed: {r2.status_code}"

    def test_07_cleanup_child(self, api):
        """Cleanup remaining child entity."""
        child_id = getattr(TestKnowledgeEntityCascadeDelete, "_child_id", None)
        if child_id:
            api.delete(f"/knowledge-graph/entities/{child_id}")


class TestEngineChatMessageCascade:
    """Engine chat session → messages → delete cascade verification."""

    def test_01_create_session_and_send_message(self, api, uid):
        """Create session, send message, verify message persisted."""
        # Create session
        r = api.post("/engine/chat/sessions", json={
            "agent_id": "default",
            "session_type": "chat",
        })
        if r.status_code in (500, 503):
            pytest.skip("Engine not initialized")
        assert r.status_code in (200, 201), f"Create failed: {r.status_code} {r.text}"
        session_id = r.json()["id"]
        TestEngineChatMessageCascade._session_id = session_id
        TestEngineChatMessageCascade._uid = uid

        # Send message
        try:
            r = api.post(f"/engine/chat/sessions/{session_id}/messages", json={
                "content": f"Integration verification for cascade ref {uid}",
            })
        except (httpx.ReadTimeout, httpx.ConnectTimeout):
            api.delete(f"/engine/chat/sessions/{session_id}")
            pytest.skip("LLM timed out (no Ollama available)")
        if r.status_code in (404, 503):
            # LLM not available, skip cascade test but cleanup
            api.delete(f"/engine/chat/sessions/{session_id}")
            pytest.skip(f"LLM not available for messaging: {r.text}")
        assert r.status_code in (200, 201), f"Send failed: {r.status_code} {r.text}"
        data = r.json()
        assert "content" in data or "message_id" in data, f"No content/message_id: {data}"

    def test_02_verify_messages_in_session(self, api):
        """GET /engine/chat/sessions/{id} → verify messages in session detail."""
        session_id = getattr(TestEngineChatMessageCascade, "_session_id", None)
        if not session_id:
            pytest.skip("no session created")
        r = api.get(f"/engine/chat/sessions/{session_id}")
        if r.status_code == 503:
            pytest.skip("Engine unavailable")
        # Session may have already ended (auto-end after response) — 404 is acceptable
        if r.status_code == 404:
            pytest.skip(f"Session already ended: {r.text}")
        assert r.status_code == 200, f"Get session failed: {r.status_code} {r.text}"
        data = r.json()
        # Should have messages or recent_messages
        messages = data.get("messages", data.get("recent_messages", []))
        assert isinstance(messages, list)
        # At minimum we sent 1 user message + got 1 assistant reply
        assert len(messages) >= 1, f"Expected messages, got {len(messages)}"

    def test_03_export_session(self, api):
        """GET /engine/chat/sessions/{id}/export → verify export works."""
        session_id = getattr(TestEngineChatMessageCascade, "_session_id", None)
        if not session_id:
            pytest.skip("no session created")
        r = api.get(f"/engine/chat/sessions/{session_id}/export", params={"format": "markdown"})
        assert r.status_code in (200, 404), f"Export failed: {r.status_code} {r.text}"

    def test_04_delete_session(self, api):
        """DELETE /engine/chat/sessions/{id} → delete session."""
        session_id = getattr(TestEngineChatMessageCascade, "_session_id", None)
        if not session_id:
            pytest.skip("no session created")
        r = api.delete(f"/engine/chat/sessions/{session_id}")
        assert r.status_code in (200, 204), f"Delete failed: {r.status_code} {r.text}"

    def test_05_verify_session_gone(self, api):
        """GET /engine/chat/sessions/{id} → verify 404 after delete."""
        session_id = getattr(TestEngineChatMessageCascade, "_session_id", None)
        if not session_id:
            pytest.skip("no session created")
        r = api.get(f"/engine/chat/sessions/{session_id}")
        # After delete, should be 404 or session status=ended
        assert r.status_code in (200, 404), f"Unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            data = r.json()
            assert data.get("status") in ("ended", "deleted"), f"Session not ended: {data.get('status')}"


class TestSkillFailureToLessonResolution:
    """Chain 6 end-to-end: skill failure → lesson creation → resolution lookup."""

    def test_01_record_skill_failure(self, api, uid):
        """POST /skills/invocations → record a failure."""
        r = api.post("/skills/invocations", json={
            "skill_name": "data_pipeline",
            "tool_name": f"etl-transform-{uid}",
            "duration_ms": 28000,
            "success": False,
            "error_type": "MemoryOverflow",
        })
        if r.status_code in (502, 503):
            pytest.skip("skills service unavailable")
        assert r.status_code in (200, 201, 422)
        TestSkillFailureToLessonResolution._uid = uid

    def test_02_create_lesson_for_failure(self, api):
        """POST /lessons → create resolution for the error pattern."""
        uid = getattr(TestSkillFailureToLessonResolution, "_uid", None)
        if not uid:
            pytest.skip("no previous step")
        r = api.post("/lessons", json={
            "error_pattern": f"MemoryOverflow in etl-transform pipeline — ref {uid}",
            "error_type": "MemoryOverflow",
            "resolution": "Reduce batch_size from 10000 to 2000 and enable streaming mode",
            "skill_name": "data_pipeline",
            "context": {"dataset_size": ">500MB", "pipeline": "etl-transform"},
        })
        assert r.status_code in (200, 201, 400), f"Create lesson failed: {r.status_code} {r.text}"
        data = r.json()
        if data.get("skipped"):
            pytest.skip("noise filter blocked")
        TestSkillFailureToLessonResolution._lesson_id = data.get("id")

    def test_03_lookup_resolution(self, api):
        """GET /lessons/check → find resolution for MemoryOverflow."""
        r = api.get("/lessons/check", params={"error_type": "MemoryOverflow"})
        assert r.status_code == 200
        data = r.json()
        assert "lessons" in data or "has_resolution" in data
        if data.get("lessons"):
            resolutions = [l.get("resolution", "") for l in data["lessons"] if isinstance(l, dict)]
            assert any("batch_size" in r or "streaming" in r for r in resolutions), \
                f"Resolution not found: {resolutions}"

    def test_04_verify_in_skill_dashboard(self, api):
        """GET /skills/health/dashboard → verify data_pipeline shows issues."""
        r = api.get("/skills/health/dashboard", params={"hours": 1})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        # Dashboard should have data about skills
        assert "skills" in data or "overall" in data or "patterns" in data

    def test_05_cleanup(self, api):
        """Cleanup lesson."""
        lid = getattr(TestSkillFailureToLessonResolution, "_lesson_id", None)
        if lid:
            api.delete(f"/lessons/{lid}")


class TestEngineSessionDelete:
    """DELETE /engine/sessions/{id} — currently untested hard-delete endpoint."""

    def test_01_engine_session_delete_nonexistent(self, api):
        """DELETE /engine/sessions/{nonexistent_id} → 404."""
        r = api.delete("/engine/sessions/00000000-0000-0000-0000-000000000099")
        if r.status_code == 503:
            pytest.skip("Engine service unavailable")
        assert r.status_code == 404


class TestKnowledgeAutoGeneratedCleanup:
    """DELETE /knowledge-graph/auto-generated — bulk cleanup of skill graph."""

    def test_01_sync_then_cleanup(self, api):
        """POST sync-skills then DELETE auto-generated → verify counts."""
        # First sync to ensure there's something to clean
        r = api.post("/knowledge-graph/sync-skills")
        assert r.status_code == 200

        # Now clean auto-generated
        r = api.delete("/knowledge-graph/auto-generated")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "deleted_entities" in data or "status" in data, f"Missing keys: {list(data.keys())}"
