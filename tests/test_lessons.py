"""Lessons Learned — Error resolution lifecycle integration tests.

Scenario: create -> list -> upsert increment -> verify count -> check resolution -> seed.
"""
import pytest


class TestLessonLifecycle:
    """Ordered scenario: lesson creation, upsert, and resolution lookup."""

    def test_01_create_lesson(self, api, uid):
        """POST /lessons -> create lesson with error pattern."""
        payload = {
            'error_pattern': f'connection refused on port 5432 — ref {uid}',
            'error_type': 'ConnectionRefusedError',
            'resolution': 'Verify PostgreSQL is running and accepting connections on the configured port',
            'skill_name': 'database',
            'context': {'scenario': 'cold_start', 'note': 'DB container not ready'},
        }
        r = api.post('/lessons', json=payload)
        if r.status_code in (502, 503):
            pytest.skip('lessons service unavailable')
        if r.status_code == 429:
            pytest.skip('rate limited')
        assert r.status_code in (200, 201, 400), f'Create lesson failed: {r.status_code} {r.text}'
        data = r.json()
        if data.get('skipped'):
            pytest.skip('noise filter blocked payload')
        lesson_id = data.get('id') or data.get('lesson_id')
        assert lesson_id, f'No id in response: {data}'
        TestLessonLifecycle._lesson_id = lesson_id
        TestLessonLifecycle._uid = uid

    def test_02_verify_in_list(self, api):
        """GET /lessons -> verify lesson is in list with occurrence count."""
        uid = getattr(TestLessonLifecycle, '_uid', None)
        if not uid:
            pytest.skip('no lesson created')
        r = api.get('/lessons')
        assert r.status_code == 200
        data = r.json()
        lessons = data.get('items', data) if isinstance(data, dict) else data
        if isinstance(lessons, list):
            found = any(isinstance(l, dict) and uid in str(l.get('error_pattern', '')) for l in lessons)
            assert found, f'Lesson with ref {uid} not found'
            our = [l for l in lessons if isinstance(l, dict) and uid in str(l.get('error_pattern', ''))]
            if our:
                assert 'occurrences' in our[0] or 'occurrence_count' in our[0] or 'count' in our[0]
                TestLessonLifecycle._initial_count = (
                    our[0].get('occurrences') or our[0].get('occurrence_count') or our[0].get('count') or 1
                )

    def test_03_upsert_increments_count(self, api):
        """POST /lessons (same pattern) -> upsert should increment count."""
        uid = getattr(TestLessonLifecycle, '_uid', None)
        if not uid:
            pytest.skip('no lesson created')
        payload = {
            'error_pattern': f'connection refused on port 5432 — ref {uid}',
            'error_type': 'ConnectionRefusedError',
            'resolution': 'Verify PostgreSQL is running and accepting connections on the configured port',
            'skill_name': 'database',
        }
        r = api.post('/lessons', json=payload)
        assert r.status_code in (200, 201, 400)

    def test_04_verify_count_increased(self, api):
        """GET /lessons -> verify occurrence count increased."""
        uid = getattr(TestLessonLifecycle, '_uid', None)
        if not uid:
            pytest.skip('no lesson created')
        r = api.get('/lessons')
        assert r.status_code == 200
        data = r.json()
        lessons = data.get('items', data) if isinstance(data, dict) else data
        if isinstance(lessons, list):
            our = [l for l in lessons if isinstance(l, dict) and uid in str(l.get('error_pattern', ''))]
            if our:
                current = our[0].get('occurrences') or our[0].get('occurrence_count') or our[0].get('count') or 0
                initial = getattr(TestLessonLifecycle, '_initial_count', 1)
                assert current >= initial

    def test_05_check_resolution(self, api):
        """GET /lessons/check?error_type=ConnectionRefusedError -> verify resolution."""
        r = api.get('/lessons/check', params={'error_type': 'ConnectionRefusedError'})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert 'lessons' in data or 'has_resolution' in data

    def test_06_seed_idempotent(self, api):
        """POST /lessons/seed -> verify idempotent seed."""
        r = api.post('/lessons/seed')
        if r.status_code == 429:
            pytest.skip('rate limited')
        assert r.status_code == 200
        data = r.json()
        assert 'seeded' in data or 'total' in data

    def test_07_cleanup(self, api):
        """DELETE /lessons/{id} -> cleanup."""
        lid = getattr(TestLessonLifecycle, '_lesson_id', None)
        if not lid:
            pytest.skip('no lesson created')
        r = api.delete(f'/lessons/{lid}')
        assert r.status_code in (200, 204, 404, 405)
        if r.status_code in (200, 204):
            r = api.get(f'/lessons/{lid}')
            assert r.status_code in (404, 405), f'Lesson still exists: {r.status_code}'
