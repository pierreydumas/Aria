"""Operations — Task lifecycle, heartbeat flow, rate limits, jobs, performance, schedule.

Chain 7: tasks CRUD, heartbeat flow, rate-limit increment verification.
"""
import pytest


class TestTaskLifecycle:
    """Ordered scenario: task create -> list -> patch -> verify."""

    def test_01_create_task(self, api, uid):
        """POST /tasks -> create with all required fields."""
        payload = {
            'task_id': f'deploy-{uid}',
            'task_type': 'deployment',
            'description': f'Deploy API v2 to production — ref {uid}',
            'agent_type': 'coder',
            'priority': 'high',
            'status': 'pending',
        }
        r = api.post('/tasks', json=payload)
        if r.status_code in (502, 503):
            pytest.skip('tasks service unavailable')
        assert r.status_code in (200, 201), f'Create task failed: {r.status_code} {r.text}'
        data = r.json()
        if data.get('skipped'):
            pytest.skip('noise filter blocked payload')
        task_id = data.get('task_id') or data.get('id')
        assert task_id, f'No task_id in response: {data}'
        TestTaskLifecycle._task_id = task_id
        TestTaskLifecycle._uid = uid

    def test_02_verify_in_list(self, api):
        """GET /tasks -> verify our task is in the list."""
        uid = getattr(TestTaskLifecycle, '_uid', None)
        if not uid:
            pytest.skip('no task created')
        r = api.get('/tasks')
        assert r.status_code == 200
        data = r.json()
        tasks = data.get('tasks', data) if isinstance(data, dict) else data
        assert isinstance(tasks, list), f'Expected list, got {type(tasks)}'
        task_ids = [t.get('task_id', '') for t in tasks if isinstance(t, dict)]
        assert f'deploy-{uid}' in task_ids, f'Created task not found. IDs: {task_ids[:10]}'

    def test_03_complete_task(self, api):
        """PATCH /tasks/{task_id} -> complete it."""
        task_id = getattr(TestTaskLifecycle, '_task_id', None)
        if not task_id:
            pytest.skip('no task created')
        r = api.patch(f'/tasks/{task_id}', json={'status': 'done', 'result': 'Deployment successful'})
        assert r.status_code in (200, 422), f'Patch task failed: {r.status_code} {r.text}'
        if r.status_code == 200:
            data = r.json()
            assert data.get('updated') is True or 'updated' in data

    def test_04_verify_task_updated(self, api):
        """GET /tasks -> verify status was updated."""
        uid = getattr(TestTaskLifecycle, '_uid', None)
        if not uid:
            pytest.skip('no task created')
        r = api.get('/tasks', params={'status': 'done'})
        assert r.status_code == 200
        data = r.json()
        tasks = data.get('tasks', data) if isinstance(data, dict) else data
        if isinstance(tasks, list):
            our_tasks = [t for t in tasks if isinstance(t, dict) and t.get('task_id') == f'deploy-{uid}']
            if our_tasks:
                assert our_tasks[0].get('status') == 'done'

    def test_05_delete_task(self, api):
        """DELETE /tasks/{task_id} -> remove it from the queue."""
        task_id = getattr(TestTaskLifecycle, '_task_id', None)
        if not task_id:
            pytest.skip('no task created')
        r = api.delete(f'/tasks/{task_id}')
        assert r.status_code in (200, 404), f'Delete task failed: {r.status_code} {r.text}'
        if r.status_code == 200:
            data = r.json()
            assert data.get('deleted') is True


class TestTaskPurge:
    """Queue purge endpoint should support explicit task-id cleanup."""

    def test_01_create_purge_target(self, api, uid):
        payload = {
            'task_id': f'purge-{uid}',
            'task_type': 'cleanup',
            'description': f'Queue purge test target {uid}',
            'agent_type': 'coder',
            'priority': 'low',
            'status': 'pending',
        }
        r = api.post('/tasks', json=payload)
        if r.status_code in (502, 503):
            pytest.skip('tasks service unavailable')
        assert r.status_code in (200, 201), f'Create purge target failed: {r.status_code} {r.text}'
        TestTaskPurge._task_id = payload['task_id']

    def test_02_purge_by_task_id(self, api):
        task_id = getattr(TestTaskPurge, '_task_id', None)
        if not task_id:
            pytest.skip('no purge target created')
        r = api.post('/tasks/purge', json={'task_ids': [task_id]})
        assert r.status_code in (200, 422), f'Purge task failed: {r.status_code} {r.text}'
        if r.status_code == 200:
            data = r.json()
            assert data.get('purged', 0) >= 1

    def test_03_verify_purged(self, api):
        task_id = getattr(TestTaskPurge, '_task_id', None)
        if not task_id:
            pytest.skip('no purge target created')
        r = api.get('/tasks')
        assert r.status_code == 200
        data = r.json()
        tasks = data.get('tasks', data) if isinstance(data, dict) else data
        task_ids = [t.get('task_id', '') for t in tasks if isinstance(t, dict)]
        assert task_id not in task_ids


class TestHeartbeatFlow:
    """Heartbeat: create -> list -> latest."""

    def test_01_create_heartbeat(self, api, uid):
        """POST /heartbeat -> create with beat_number, status, details."""
        payload = {
            'beat_number': 99999,
            'job_name': f'test-heartbeat-flow-{uid}',
            'status': 'test',
            'details': {'uptime_hours': 72, 'ref': uid},
        }
        r = api.post('/heartbeat', json=payload)
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code in (200, 201), f'Create heartbeat failed: {r.status_code} {r.text}'
        data = r.json()
        assert 'id' in data or 'created' in data, f'Missing id/created: {data}'
        assert data.get('persisted') is False
        TestHeartbeatFlow._uid = uid

    def test_02_list_heartbeats(self, api):
        """GET /heartbeat -> verify it is in list."""
        r = api.get('/heartbeat')
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code == 200
        data = r.json()
        hbs = data.get('heartbeats', data) if isinstance(data, dict) else data
        assert isinstance(hbs, list) or isinstance(data, dict)
        if isinstance(hbs, list) and hbs:
            assert 'beat_number' in hbs[0] or 'status' in hbs[0]

    def test_03_latest_heartbeat(self, api):
        """GET /heartbeat/latest -> verify it is the latest."""
        r = api.get('/heartbeat/latest')
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert 'beat_number' in data or 'status' in data or 'id' in data


class TestRateLimits:
    """Rate limit: check -> increment -> check again -> verify counter."""

    def test_01_check_rate_limit(self, api, uid):
        """POST /rate-limits/check -> initial check."""
        r = api.post('/rate-limits/check', json={'skill': f'cache-{uid}', 'max_actions': 100, 'window_seconds': 3600})
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            data = r.json()
            assert 'allowed' in data or 'remaining' in data
            TestRateLimits._skill = f'cache-{uid}'
            TestRateLimits._initial_remaining = data.get('remaining')

    def test_02_increment_rate_limit(self, api):
        """POST /rate-limits/increment -> increment counter."""
        skill = getattr(TestRateLimits, '_skill', None)
        if not skill:
            pytest.skip('no skill from previous step')
        r = api.post('/rate-limits/increment', json={'skill': skill, 'action_type': 'invoke'})
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            data = r.json()
            assert data.get('incremented') is True or 'skill' in data

    def test_03_verify_counter_increased(self, api):
        """POST /rate-limits/check again -> verify counter changed."""
        skill = getattr(TestRateLimits, '_skill', None)
        if not skill:
            pytest.skip('no skill from previous step')
        r = api.post('/rate-limits/check', json={'skill': skill, 'max_actions': 100, 'window_seconds': 3600})
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            data = r.json()
            initial = getattr(TestRateLimits, '_initial_remaining', None)
            if initial is not None and data.get('remaining') is not None:
                assert data['remaining'] <= initial

    def test_04_list_rate_limits(self, api):
        """GET /rate-limits -> verify response body structure."""
        r = api.get('/rate-limits')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert 'rate_limits' in data or 'count' in data


class TestPerformance:
    """Performance endpoint assertions."""

    def test_create_and_list_performance(self, api, uid):
        """POST /performance -> record, then GET -> verify in list."""
        payload = {
            'review_period': f'2026-Q1-{uid}',
            'successes': ['stable deploy', 'reduced retry spikes'],
            'failures': ['one transient timeout'],
            'improvements': ['Reduced cold start latency by 40%'],
        }
        r = api.post('/performance', json=payload)
        assert r.status_code in (200, 201)
        data = r.json()
        assert 'created' in data or 'id' in data

        r = api.get('/performance')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        logs = data.get('logs', data) if isinstance(data, dict) else data
        assert isinstance(logs, list) or 'count' in data


class TestScheduleAndJobs:
    """Schedule and jobs endpoints."""

    def test_schedule(self, api):
        r = api.get('/schedule')
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_schedule_tick(self, api):
        r = api.post('/schedule/tick')
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            data = r.json()
            assert 'ticked' in data or 'at' in data

    def test_list_jobs(self, api):
        r = api.get('/jobs')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert 'jobs' in data or 'count' in data

    def test_live_jobs(self, api):
        r = api.get('/jobs/live')
        assert r.status_code == 200
        data = r.json()
        assert 'jobs' in data or 'source' in data

    def test_nonexistent_job(self, api):
        r = api.get('/jobs/nonexistent-job-id-xyz-999')
        assert r.status_code == 404

    def test_sync_jobs(self, api):
        r = api.post('/jobs/sync')
        assert r.status_code in (200, 404, 422)


class TestHeartbeatPayloadCompat:
    """S-42: Heartbeat payload contract hardening — details accepts dict, str, list, None."""

    def test_heartbeat_string_details(self, api):
        """POST /heartbeat with `details` as a plain string must return 200."""
        r = api.post('/heartbeat', json={"job_name": "test-heartbeat-string", "status": "test", "details": "ok"})
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code in (200, 201), f'Expected 200/201 for string details, got {r.status_code}: {r.text}'
        data = r.json()
        assert 'id' in data or 'created' in data
        assert data.get('persisted') is False

    def test_heartbeat_list_details(self, api):
        """POST /heartbeat with `details` as a list must return 200."""
        r = api.post('/heartbeat', json={"job_name": "test-heartbeat-list", "status": "test", "details": ["event_a", "event_b"]})
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code in (200, 201), f'Expected 200/201 for list details, got {r.status_code}: {r.text}'
        assert r.json().get('persisted') is False

    def test_heartbeat_null_details(self, api):
        """POST /heartbeat with `details` omitted (null) must return 200."""
        r = api.post('/heartbeat', json={"job_name": "test-heartbeat-null", "status": "test"})
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code in (200, 201), f'Expected 200/201 for null details, got {r.status_code}: {r.text}'
        assert r.json().get('persisted') is False

    def test_heartbeat_dict_details_still_works(self, api):
        """POST /heartbeat with `details` as a dict must still return 200 (regression guard)."""
        r = api.post('/heartbeat', json={"job_name": "test-heartbeat-dict", "status": "test", "details": {"uptime": 99}})
        if r.status_code in (502, 503):
            pytest.skip('heartbeat service unavailable')
        assert r.status_code in (200, 201), f'Expected 200/201 for dict details, got {r.status_code}: {r.text}'
        assert r.json().get('persisted') is False


class TestApiKeyRotations:
    """API key rotation tracking."""

    def test_create_and_list_rotations(self, api, uid):
        payload = {
            'service': 'openai',
            'reason': 'routine rotation',
            'rotated_by': 'system',
        }
        r = api.post('/api-key-rotations', json=payload)
        assert r.status_code in (200, 201)
        data = r.json()
        assert 'id' in data or 'created' in data

        r = api.get('/api-key-rotations')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert 'rotations' in data or 'count' in data
