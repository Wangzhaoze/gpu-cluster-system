from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import main as module, retention, server
from app.models import AnnouncementRead, Workload, now
from app.schemas import DebugSpec, JobSpec, UserCreate
from test_role_portals import portal


@pytest.mark.parametrize('spec,values', [(JobSpec, {'command': 'true'}), (DebugSpec, {})])
def test_default_resources_and_gpu_requirement(spec, values):
    request = spec(**values)
    assert (request.requested_cpus, request.requested_ram_mb, request.requested_gpus) == (4, 4096, 1)
    with pytest.raises(ValidationError):
        spec(requested_gpus=0, **values)


def test_debug_eight_hour_hard_limit():
    assert UserCreate(username='student', display_name='Student', password='long-password').max_debug_hours == 8
    assert DebugSpec(time_limit_seconds=28800).time_limit_seconds == 28800
    with pytest.raises(ValidationError):
        DebugSpec(time_limit_seconds=28801, approval_reason='Cannot bypass the cap')


@pytest.mark.parametrize('state', ['PENDING', 'AWAITING_APPROVAL', 'STARTING', 'RUNNING'])
@pytest.mark.parametrize('cancelling', [False, True])
def test_one_debug_including_pending_and_cancelling(portal, state, cancelling):
    client, db, _, _ = portal
    existing = db.get(Workload, 'owner-debug')
    existing.status, existing.cancel_requested = state, cancelling
    db.commit()
    response = client.post('/api/debug', json={})
    assert response.status_code == 409, response.text


def test_completed_debug_allows_one_new_multi_gpu_session(portal):
    client, db, people, _ = portal
    db.get(Workload, 'owner-debug').status = 'CANCELLED'
    people['owner'].max_gpus = 3
    db.commit()
    response = client.post('/api/debug', json={'requested_gpus': 2, 'gpu_indices': [0, 1], 'time_limit_seconds': 28800})
    assert response.status_code == 201, response.text
    assert response.json()['requested_gpu_indices'] == [0, 1]
    assert client.post('/api/debug', json={}).status_code == 409


def test_training_kill_scope_and_queue_permissions(portal):
    client, db, people, actor = portal
    rows = {r['id']: r for r in client.get('/api/resources/queue').json()}
    assert rows['owner-train']['can_manage'] and not rows['other-train']['can_manage']
    assert client.post('/api/jobs/other-train/kill').status_code == 403
    assert not db.get(Workload, 'other-train').cancel_requested
    assert client.post('/api/jobs/owner-train/kill').status_code == 200
    assert db.get(Workload, 'owner-train').cancel_requested
    actor[0] = people['admin']
    assert client.post('/api/jobs/other-train/kill').status_code == 200
    assert db.get(Workload, 'other-train').cancel_requested


def test_admin_extends_training_without_container_restart(portal):
    client, db, people, actor = portal
    resource = db.get(Workload, 'owner-train')
    resource.status, resource.started_at = 'RUNNING', now() - timedelta(minutes=30)
    resource.expires_at = resource.started_at + timedelta(hours=1)
    resource.container_id = 'preserved-container'
    db.commit()
    assert client.post('/api/jobs/owner-train/extend', json={'extra_seconds': 3600}).status_code == 403
    actor[0] = people['admin']
    response = client.post('/api/jobs/owner-train/extend', json={'extra_seconds': 3600})
    assert response.status_code == 200, response.text
    assert resource.time_limit_seconds == 7200 and resource.container_id == 'preserved-container'
    assert (resource.expires_at.replace(tzinfo=timezone.utc) - resource.started_at.replace(tzinfo=timezone.utc)).total_seconds() == 7200
    assert client.post('/api/jobs/owner-train/extend', json={'extra_seconds': 604800}).status_code == 422
    assert client.post('/api/jobs/owner-train/extend', json={'extra_seconds': 0}).status_code == 422


def test_logs_download_is_private(portal):
    client, _, people, actor = portal
    assert client.get('/api/jobs/other-train/logs/download').status_code == 403
    assert client.get('/api/jobs/owner-train/logs/download').status_code == 200
    actor[0] = people['admin']
    assert client.get('/api/jobs/other-train/logs/download').status_code == 200


def test_announcement_draft_publication_and_durable_per_user_read(portal):
    client, db, people, actor = portal
    payload = {'title': 'Notice', 'body': 'Line one\nLine two <script>plain text</script>'}
    assert client.post('/api/announcements', json=payload).status_code == 403
    actor[0] = people['admin']
    draft = client.post('/api/announcements', json=payload)
    assert draft.status_code == 201, draft.text
    identifier = draft.json()['id']
    actor[0] = people['owner']
    assert client.get('/api/announcements').json() == []
    assert client.post(f'/api/announcements/{identifier}/read').status_code == 404
    assert client.post(f'/api/announcements/{identifier}/publish').status_code == 403
    actor[0] = people['admin']
    edited = client.patch(f'/api/announcements/{identifier}', json={**payload, 'title': 'Updated notice'})
    assert edited.status_code == 200
    published = client.post(f'/api/announcements/{identifier}/publish')
    assert published.status_code == 200 and published.json()['published_at']
    repeated = client.post(f'/api/announcements/{identifier}/publish').json()['published_at']
    assert datetime.fromisoformat(repeated).replace(tzinfo=timezone.utc) == datetime.fromisoformat(published.json()['published_at']).replace(tzinfo=timezone.utc)
    assert client.patch(f'/api/announcements/{identifier}', json=payload).status_code == 409
    actor[0] = people['owner']
    assert client.get('/api/announcements').json()[0]['title'] == 'Updated notice'
    assert client.post(f'/api/announcements/{identifier}/read').status_code == 200
    assert client.post(f'/api/announcements/{identifier}/read').status_code == 200
    assert client.get('/api/announcements').json() == []
    assert len(list(db.scalars(select(AnnouncementRead)))) == 1
    actor[0] = people['other']
    assert client.get('/api/announcements').json()[0]['id'] == identifier
    actor[0] = people['owner']
    assert client.get('/api/announcements').json() == []  # A new login/session remains read.


@pytest.mark.parametrize('title,body', [(' ', 'text'), ('title', '\n'), ('title', 'bad\0text')])
def test_announcement_rejects_blank_and_invalid_content(portal, title, body):
    client, _, people, actor = portal
    actor[0] = people['admin']
    assert client.post('/api/announcements', json={'title': title, 'body': body}).status_code == 422


def history(db, identifier, status, created, finished=None):
    item = Workload(id=identifier, kind='train', user_id='owner', environment_id='env', command='true',
                    status=status, requested_gpus=1, requested_cpus=4, requested_ram_mb=4096,
                    time_limit_seconds=3600, created_at=created, finished_at=finished)
    db.add(item)
    db.commit()
    return item


def test_seven_day_retention_preserves_active_and_student_files(portal, monkeypatch, tmp_path):
    _, db, _, _ = portal
    instant = now()
    old = instant - timedelta(days=8)
    cutoff = instant - timedelta(days=7)
    cases = [('old-completed', 'COMPLETED', old), ('old-debug', 'CANCELLED', old),
             ('legacy-terminal', 'FAILED', None), ('boundary', 'COMPLETED', cutoff),
             ('recent-completed', 'COMPLETED', instant), ('old-running', 'RUNNING', None),
             ('old-pending', 'PENDING', None), ('old-approval', 'AWAITING_APPROVAL', None)]
    log_dir = tmp_path / 'logs/jobs'
    log_dir.mkdir(parents=True)
    for identifier, status, finished in cases:
        item = history(db, identifier, status, old, finished)
        if identifier == 'old-debug':
            item.kind = 'debug'
            db.commit()
        (log_dir / f'{identifier}.log').write_text('task log')
    markers = [tmp_path / 'users/owner/workspace/code.py', tmp_path / 'results/owner/model.pt']
    for path in markers:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('preserved')
    monkeypatch.setattr(retention, 'settings', SimpleNamespace(runtime_root=str(tmp_path), project='gpu-lab-poc'))
    assert retention.prune_workload_history(db, cutoff) == 3
    for identifier in ('old-completed', 'old-debug', 'legacy-terminal'):
        assert db.get(Workload, identifier) is None and not (log_dir / f'{identifier}.log').exists()
    for identifier, _, _ in cases[3:]:
        assert db.get(Workload, identifier) is not None and (log_dir / f'{identifier}.log').exists()
    assert all(path.read_text() == 'preserved' for path in markers)


def test_retention_does_not_delete_live_container_or_record_after_log_failure(portal, monkeypatch, tmp_path):
    _, db, _, _ = portal
    old = now() - timedelta(days=8)
    history(db, 'still-running', 'COMPLETED', old, old)
    container = MagicMock(status='running')
    monkeypatch.setattr(retention.runtime, 'get', lambda name: container)
    assert retention.prune_workload_history(db) == 0
    assert db.get(Workload, 'still-running') is not None
    monkeypatch.setattr(retention.runtime, 'get', lambda name: None)
    monkeypatch.setattr(retention, 'settings', SimpleNamespace(runtime_root=str(tmp_path), project='gpu-lab-poc'))
    monkeypatch.setattr(retention.Path, 'unlink', lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError('denied')))
    assert retention.prune_workload_history(db) == 0
    assert db.get(Workload, 'still-running') is not None


def test_lists_hide_expired_history_before_hourly_cleanup_but_keep_active(portal):
    client, db, _, _ = portal
    old = now() - timedelta(days=8)
    history(db, 'expired-hidden', 'COMPLETED', old, old)
    history(db, 'old-still-active', 'RUNNING', old)
    ids = {row['id'] for row in client.get('/api/jobs').json()}
    assert 'expired-hidden' not in ids and 'old-still-active' in ids


def test_announcement_migration_creates_tables_and_clamps_existing_limits(portal, monkeypatch):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from app.models import Announcement, AnnouncementRead
    _, db, people, _ = portal
    people['owner'].max_debug_hours = 10
    people['other'].max_debug_hours = 4
    db.commit()
    engine = db.get_bind()
    AnnouncementRead.__table__.drop(engine)
    Announcement.__table__.drop(engine)
    spec = spec_from_file_location('portal_migration', Path(__file__).resolve().parents[2] / 'backend/alembic/versions/0003_portal_announcements.py')
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
    db.expire_all()
    assert people['owner'].max_debug_hours == 8 and people['other'].max_debug_hours == 4
    assert {'announcements', 'announcement_reads'} <= set(inspect(engine).get_table_names())


def test_legacy_long_debug_must_be_edited_before_approval(portal):
    client, db, people, actor = portal
    actor[0] = people['admin']
    old = db.get(Workload, 'owner-debug')
    old.status, old.approval_status, old.time_limit_seconds = 'AWAITING_APPROVAL', 'PENDING', 43200
    db.commit()
    assert client.post('/api/debug/owner-debug/approve', json={}).status_code == 422
    assert old.status == 'AWAITING_APPROVAL'
    assert client.patch('/api/debug/owner-debug', json={'time_limit_seconds': 28800}).status_code == 200
    assert client.post('/api/debug/owner-debug/approve', json={}).status_code == 200
    assert old.status == 'PENDING'


def test_legacy_cpu_only_training_retry_requires_new_gpu_task(portal):
    client, db, _, _ = portal
    item = db.get(Workload, 'owner-train')
    item.status, item.requested_gpus = 'COMPLETED', 0
    item.requested_gpu_indices_json = None
    db.commit()
    response = client.post('/api/jobs/owner-train/retry')
    assert response.status_code == 422 and 'GPU' in response.json()['detail']
    assert item.requested_gpus == 0
