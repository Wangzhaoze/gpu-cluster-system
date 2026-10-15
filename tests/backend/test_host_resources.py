from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import resources
from app.db import Base
from app.models import Environment, GpuSlot, User, Workload
from app.scheduler.mock_docker import MockDockerScheduler
from test_role_portals import portal


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(resources, '_docker_info', lambda: {'NCPU': 30, 'MemTotal': 58820 * 1024**2})
    monkeypatch.setitem(resources.runtime.__dict__, 'client', MagicMock())
    resources.runtime.client.containers.list.return_value = []


def test_upgraded_host_and_reserve_are_dynamic(host):
    limits = resources.host_limits()
    assert limits == {'total_cpus': 30, 'total_ram_mb': 58820, 'reserved_ram_mb': 8192, 'schedulable_ram_mb': 50628}
    assert resources.request_error(30, 50628, limits) is None
    assert 'CPU' in resources.request_error(31, 4096, limits)
    assert '内存' in resources.request_error(4, 50629, limits)


@pytest.mark.parametrize('info', [{'NCPU': 0, 'MemTotal': 64*1024**3}, {'NCPU': True, 'MemTotal': 64*1024**3}, {'NCPU': 30, 'MemTotal': 0}, {}])
def test_invalid_host_capacity_fails_closed(monkeypatch, info):
    monkeypatch.setattr(resources, '_docker_info', lambda: info)
    with pytest.raises(DockerException):
        resources.host_limits()


def test_capacity_accounts_active_jobs_and_running_workspaces_once(portal, host, monkeypatch):
    _, db, _, _ = portal
    item = db.get(Workload, 'owner-train')
    item.status, item.requested_cpus, item.requested_ram_mb = 'RUNNING', 8, 16384
    db.commit()
    workspace = SimpleNamespace(id='workspace', attrs={'HostConfig': {'NanoCpus': 2_000_000_000, 'Memory': 2*1024**3}})
    resources.runtime.client.containers.list.return_value = [workspace]
    limits = resources.capacity(db)
    assert (limits['allocated_cpus'], limits['allocated_ram_mb']) == (10, 18432)
    assert (limits['available_cpus'], limits['available_ram_mb']) == (20, 32196)
    assert resources.capacity(db, exclude_workspace='workspace')['allocated_cpus'] == 8
    with pytest.raises(HTTPException) as error:
        resources.require_available(db, 21, 4096)
    assert error.value.status_code == 409


@pytest.mark.parametrize('path,payload', [('/jobs', {'command': 'true', 'requested_cpus': 31}), ('/jobs', {'command': 'true', 'requested_ram_mb': 65536}), ('/debug', {'requested_cpus': 31}), ('/debug', {'requested_ram_mb': 65536})])
def test_api_rejects_resources_beyond_real_host(portal, host, path, payload):
    client, db, _, _ = portal
    db.get(Workload, 'owner-debug').status = 'CANCELLED'
    db.commit()
    response = client.post('/api'+path, json=payload)
    assert response.status_code == 422, response.text


def test_capacity_visible_to_member_and_admin(portal, host):
    client, _, people, actor = portal
    for name in ['owner', 'admin']:
        actor[0] = people[name]
        payload = client.get('/api/resources/gpus').json()
        assert payload['capacity']['total_cpus'] == 30
        assert payload['capacity']['total_ram_mb'] == 58820
        assert payload['capacity']['schedulable_ram_mb'] == 50628


def test_running_legacy_job_duration_edit_preserves_resources(portal, host):
    from app.models import now
    client, db, people, actor = portal
    actor[0] = people['admin']
    item = db.get(Workload, 'owner-train')
    item.status, item.requested_ram_mb, item.started_at = 'RUNNING', 65536, now()
    db.commit()
    response = client.patch('/api/jobs/owner-train', json={'time_limit_seconds': 7200})
    assert response.status_code == 200, response.text
    assert item.requested_ram_mb == 65536


def test_workspace_admission_failure_keeps_existing_container(portal, host, monkeypatch):
    client, db, _, _ = portal
    db.get(Workload, 'other-train').status = 'RUNNING'
    db.get(Workload, 'other-train').requested_ram_mb = 50000
    db.commit()
    old = SimpleNamespace(id='stopped-workspace', status='exited')
    monkeypatch.setattr(resources.runtime, 'get', lambda name: old)
    remove = MagicMock()
    monkeypatch.setattr(resources.runtime, 'remove', remove)
    response = client.post('/api/workspace/start')
    assert response.status_code == 409, response.text
    remove.assert_not_called()


@pytest.mark.parametrize('first_ram,first_cpus,second_ram,second_cpus', [(30000,10,25000,1),(4096,20,4096,12)])
def test_scheduler_waits_for_cpu_ram_and_releases_fifo(host, monkeypatch, first_ram, first_cpus, second_ram, second_cpus):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(Environment(id='env', name='test', image='image', image_version='test', enabled=True))
        db.add(User(id='member', username='member', display_name='member', password_hash='test', uid_hint=3000, max_gpus=5, max_debug_hours=8, default_environment_id='env'))
        db.add_all([GpuSlot(gpu_index=i) for i in range(5)])
        def job(identifier, ram, cpus=1):
            return Workload(id=identifier, user_id='member', kind='train', environment_id='env', requested_gpus=1, requested_cpus=cpus, requested_ram_mb=ram, command='true', time_limit_seconds=3600)
        first, second = job('first', first_ram, first_cpus), job('second', second_ram, second_cpus)
        db.add_all([first, second]); db.commit()
        scheduler = MockDockerScheduler()
        monkeypatch.setattr(scheduler, 'reconcile', lambda db: None)
        monkeypatch.setattr(resources.runtime, 'get', lambda name: None)
        launched = []
        def launch(db, item):
            launched.append(item.id)
            item.status = 'RUNNING';db.commit()
        monkeypatch.setattr(scheduler, 'launch', launch)
        scheduler.tick(db)
        assert launched == ['first'] and second.status == 'PENDING'
        first.status = 'COMPLETED'
        for slot in db.scalars(select(GpuSlot)):
            slot.state, slot.owner_id, slot.owner_type = 'FREE', None, None
        db.commit();scheduler.tick(db)
        assert launched == ['first', 'second']



@pytest.mark.parametrize('cpus,ram', [(31,4096),(4,65536)])
def test_legacy_impossible_queued_job_fails_before_container_creation(portal, host, monkeypatch, cpus, ram):
    _, db, _, _ = portal
    for item in db.scalars(select(Workload)):
        item.status = 'COMPLETED'
    item = db.get(Workload, 'owner-train')
    item.status, item.requested_cpus, item.requested_ram_mb = 'PENDING', cpus, ram
    db.commit()
    scheduler = MockDockerScheduler()
    monkeypatch.setattr(scheduler, 'reconcile', lambda db: None)
    launch = MagicMock()
    monkeypatch.setattr(scheduler, 'launch', launch)
    scheduler.tick(db)
    assert item.status == 'FAILED' and item.error_message
    launch.assert_not_called()


def test_legacy_unlimited_workspace_cannot_be_counted_as_free(portal, host):
    _, db, _, _ = portal
    resources.runtime.client.containers.list.return_value = [SimpleNamespace(id='legacy', attrs={'HostConfig': {'Memory':0,'NanoCpus':0}})]
    result = resources.capacity(db)
    assert result['available_cpus'] == 0 and result['available_ram_mb'] == 0
