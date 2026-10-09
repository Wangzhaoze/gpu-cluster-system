from datetime import timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import main as module
from app.auth import current_user
from app.db import Base, get_db
from app.models import Environment, EnvVar, User, Workload, Workspace, now


@pytest.fixture
def portal(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(Environment(id='env', name='Python', image='image', image_version='test', enabled=True))
    people = {}
    for index, (name, role) in enumerate([('owner', 'MEMBER'), ('other', 'MEMBER'), ('admin', 'ADMIN')]):
        people[name] = User(id=name, username=name, display_name=name, role=role, enabled=True, uid_hint=3000+index, default_environment_id='env', password_hash='test', max_gpus=1, max_debug_hours=8)
        db.add(people[name])
        db.add(Workspace(user_id=name, route_path='/workspace/'+name+'/', state='STOPPED'))
    for name in people:
        for kind in ['train', 'debug']:
            db.add(Workload(id=name+'-'+kind, kind=kind, user_id=name, status='PENDING', environment_id='env', command='private_command_'+name, workdir='/workspace/private', output_name='private_output', env_json={'PRIVATE_TOKEN':'hidden'}, requested_gpus=1, requested_gpu_indices_json=[0], assigned_gpus_json=[], requested_cpus=1, requested_ram_mb=1024, time_limit_seconds=3600, route_path='/debug/private/', error_message='private_error', approval_reason='private_reason'))
    db.commit()
    actor = [people['owner']]
    module.app.dependency_overrides[current_user] = lambda: actor[0]
    module.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(module, 'deletion_lock', lambda db: None)
    monkeypatch.setattr(module.runtime, 'get', lambda name: None)
    monkeypatch.setattr(module.storage, 'usage', lambda name: {})
    try:
        yield TestClient(module.app), db, people, actor
    finally:
        module.app.dependency_overrides.clear()
        db.close()
        engine.dispose()


@pytest.mark.parametrize('path,body', [('/jobs', {'command':'true'}), ('/debug', {}), ('/jobs/owner-train/retry', None)])
def test_admin_cannot_create_or_retry_workloads(portal, path, body):
    client, db, people, actor = portal
    actor[0] = people['admin']
    assert client.post('/api'+path, json=body).status_code == 403


@pytest.mark.parametrize('kind,path', [('train','jobs'), ('debug','debug')])
def test_members_receive_other_members_summary_without_private_fields(portal, kind, path):
    client, db, people, actor = portal
    response=client.get('/api/'+path)
    assert response.status_code == 200
    records={r['user_id']: r for r in response.json()}
    assert set(records)=={'owner','other'}
    assert records['owner']['can_manage'] is True and records['owner']['command']=='private_command_owner'
    assert records['other']['can_manage'] is False and records['other']['username']=='other'
    assert set(records['other'])=={'id','kind','user_id','username','status','requested_gpus','requested_gpu_indices','assigned_gpus','time_limit_seconds','created_at','started_at','expires_at','finished_at','can_manage'}
    actor[0]=people['admin']
    all_records=client.get('/api/'+path).json()
    assert len(all_records)==3 and all(r['can_manage'] and 'command' in r for r in all_records)


@pytest.mark.parametrize('method,path', [('GET','/jobs/other-train'),('GET','/jobs/other-train/logs'),('GET','/debug/other-debug/logs'),('POST','/jobs/other-train/cancel'),('POST','/debug/other-debug/stop'),('POST','/jobs/other-train/retry'),('PATCH','/jobs/other-train'),('PATCH','/debug/other-debug')])
def test_summary_visibility_does_not_allow_details_or_control(portal, method, path):
    client, db, _, _=portal
    before=db.get(Workload,'other-train').command
    assert client.request(method,'/api'+path,json={'time_limit_seconds':7200} if method=='PATCH' else None).status_code==403
    assert db.get(Workload,'other-train').command==before


def test_member_queue_excludes_admin_records(portal):
    client, _, _, _=portal
    assert {r['username'] for r in client.get('/api/resources/queue').json()}=={'owner','other'}


def test_host_paths_visible_only_to_admin_storage(portal):
    client, _, people, actor=portal
    payload=client.get('/api/workspace').json()
    assert not {'host_paths','host_uid','host_gid','host_import_command'} & payload.keys()
    assert client.get('/api/admin/storage').status_code==403
    actor[0]=people['admin']
    rows=client.get('/api/admin/storage').json()
    members=[r for r in rows if r['role']=='MEMBER']
    assert len(members)==2 and all(r['workspace_host_path'].endswith('/users/'+r['username']+'/workspace') for r in members)
    assert 'host_paths' in client.get('/api/workspace?user_id=owner').json()


def test_environment_crud_scopes_and_admin_sync(portal):
    client, db, people, actor=portal
    assert client.put('/api/settings/env',json={'user_id':'owner','key':'MODEL_NAME','value':'first'}).status_code==200
    assert client.put('/api/settings/env',json={'user_id':'owner','key':'MODEL_NAME','value':'updated'}).status_code==200
    for user_id in (None,'other'):
        assert client.put('/api/settings/env',json={'user_id':user_id,'key':'MODEL_NAME','value':'bad'}).status_code==403
    assert client.delete('/api/settings/env/MODEL_NAME?user_id=other').status_code==403
    actor[0]=people['admin']
    assert client.get('/api/settings/env?user_id=owner').json()[0]['value']=='updated'
    assert client.put('/api/settings/env',json={'key':'GLOBAL_MODEL','value':'shared'}).status_code==200
    actor[0]=people['owner']
    assert {r['scope'] for r in client.get('/api/settings/env').json()}=={'global','owner'}
    assert client.delete('/api/settings/env/GLOBAL_MODEL?user_id=global').status_code==403
    assert client.delete('/api/settings/env/MODEL_NAME?user_id=owner').status_code==200
    assert db.get(EnvVar,('owner','MODEL_NAME')) is None
    assert client.delete('/api/settings/env/MODEL_NAME').status_code==404
    actor[0]=people['admin']
    assert client.delete('/api/settings/env/GLOBAL_MODEL').status_code==200


@pytest.mark.parametrize('key', ['PATH','CUDA_VISIBLE_DEVICES','LAB_TEST','BAD-NAME'])
def test_variable_protected_keys(portal,key):
    client, _, _, _=portal
    assert client.put('/api/settings/env',json={'user_id':'owner','key':key,'value':'bad'}).status_code==422


def test_variable_merge_priority(portal):
    client, db, people, actor=portal
    db.add_all([EnvVar(scope='global',key='MODEL_NAME',value='global'),EnvVar(scope='owner',key='MODEL_NAME',value='personal')]);db.commit()
    merged=module.runtime.env(db,people['owner'],{},[],False)
    assert merged['MODEL_NAME']=='personal'
    assert module.runtime.env(db,people['owner'],{'MODEL_NAME':'task'},[],False)['MODEL_NAME']=='task'


@pytest.mark.parametrize('path,kind', [('jobs','train'),('debug','debug')])
def test_admin_edits_queued_resources_without_new_record(portal,path,kind):
    client,db,people,actor=portal;actor[0]=people['admin']
    payload={'requested_cpus':2,'requested_ram_mb':2048,'time_limit_seconds':7200,'gpu_indices':[0]}
    if kind=='train': payload.update(command='python train.py',workdir='/workspace/project')
    result=client.patch('/api/'+path+'/owner-'+kind,json=payload)
    assert result.status_code==200,result.text
    resource=db.get(Workload,'owner-'+kind)
    assert resource.requested_cpus==2 and resource.requested_ram_mb==2048 and resource.time_limit_seconds==7200
    assert resource.status=='PENDING'
    assert client.patch('/api/'+path+'/owner-'+kind,json={'requested_gpus':2,'gpu_indices':[0,1]}).status_code==422


def test_running_edit_updates_deadline_without_restart(portal):
    client,db,people,actor=portal;actor[0]=people['admin']
    resource=db.get(Workload,'owner-debug');resource.status='RUNNING';resource.started_at=now()-timedelta(seconds=30);resource.expires_at=now()+timedelta(hours=1);resource.container_id='unchanged';db.commit()
    assert client.patch('/api/debug/owner-debug',json={'time_limit_seconds':7200}).status_code==200
    assert resource.container_id=='unchanged' and (resource.expires_at.replace(tzinfo=timezone.utc)-resource.started_at.replace(tzinfo=timezone.utc)).total_seconds()==7200
    assert client.patch('/api/debug/owner-debug',json={'requested_ram_mb':4096}).status_code==409
    assert client.patch('/api/debug/owner-debug',json={'time_limit_seconds':5}).status_code==422


@pytest.mark.parametrize('state', ['STARTING','COMPLETED','CANCELLED'])
def test_admin_cannot_edit_transition_or_finished_workload(portal,state):
    client,db,people,actor=portal;actor[0]=people['admin'];resource=db.get(Workload,'owner-debug');resource.status=state;db.commit()
    assert client.patch('/api/debug/owner-debug',json={'time_limit_seconds':7200}).status_code==409


def test_waiting_long_debug_edit_keeps_approval_pending(portal):
    client,db,people,actor=portal;actor[0]=people['admin'];r=db.get(Workload,'owner-debug');r.status='AWAITING_APPROVAL';r.approval_status='PENDING';r.time_limit_seconds=43200;db.commit()
    assert client.patch('/api/debug/owner-debug',json={'time_limit_seconds':7200}).status_code==200
    assert r.status=='AWAITING_APPROVAL' and r.approval_status=='PENDING'


def test_admin_cannot_extend_debug_past_eight_hours(portal):
    client,db,people,actor=portal;actor[0]=people['admin']
    assert client.patch('/api/debug/owner-debug',json={'time_limit_seconds':43200}).status_code==422
    r=db.get(Workload,'owner-debug');assert r.time_limit_seconds==3600 and r.approval_status=='NOT_REQUIRED'


@pytest.mark.parametrize('path', ['jobs', 'debug'])
def test_members_submit_multiple_gpus_and_admin_edits_with_owner_quota(portal, path):
    client, db, people, actor = portal
    people['owner'].max_gpus = 3
    if path == 'debug':
        db.get(Workload, 'owner-debug').status = 'CANCELLED'
    db.commit()
    payload = {'requested_gpus': 2, 'gpu_indices': [1, 2]}
    if path == 'jobs':
        payload['command'] = 'true'
    response = client.post('/api/' + path, json=payload)
    assert response.status_code == 201, response.text
    resource = response.json()
    assert resource['requested_gpus'] == 2 and resource['requested_gpu_indices'] == [1, 2]
    actor[0] = people['admin']
    updated = client.patch('/api/' + path + '/' + resource['id'], json={'requested_gpus': 3, 'gpu_indices': [0, 1, 2]})
    assert updated.status_code == 200, updated.text
    assert updated.json()['requested_gpus'] == 3
    actor[0] = people['owner']
    assert client.post('/api/' + path, json={**payload, 'requested_gpus': 4, 'gpu_indices': [0, 1, 2, 3]}).status_code == 422



def test_dataset_default_available_to_all_roles_and_obeys_scoped_priority(portal):
    _, db, people, _ = portal
    for person in people.values():
        assert module.runtime.env(db, person, {}, [], False)['DATASET'] == '/home/' + person.username + '/dataset'
    db.add(EnvVar(scope='global', key='DATASET', value='/datasets/shared'))
    db.add(EnvVar(scope='owner', key='DATASET', value='/datasets/personal'))
    db.commit()
    assert module.runtime.env(db, people['other'], {}, [], False)['DATASET'] == '/datasets/shared'
    assert module.runtime.env(db, people['owner'], {}, [], False)['DATASET'] == '/datasets/personal'
    assert module.runtime.env(db, people['owner'], {'DATASET': '/datasets/task'}, [], False)['DATASET'] == '/datasets/task'


@pytest.mark.parametrize('value', ['$HOME/dataset', '${HOME}/dataset'])
def test_dataset_home_expression_expands_for_each_user(portal, value):
    _, db, people, _ = portal
    db.add(EnvVar(scope='global', key='DATASET', value=value))
    db.commit()
    for person in people.values():
        assert module.runtime.env(db, person, {}, [], False)['DATASET'] == '/home/' + person.username + '/dataset'


@pytest.mark.parametrize('role,path', [('owner', '/storage'), ('admin', '/admin/storage')])
def test_slow_storage_scans_do_not_hold_database_connections(portal, monkeypatch, role, path):
    client, db, people, actor = portal
    actor[0] = people[role]
    db.scalar(select(User).where(User.id == role))
    assert db.in_transaction()
    scanned = []

    def usage(username):
        assert not db.in_transaction(), 'Filesystem scans must release the DB pool connection'
        scanned.append(username)
        return {'workspace': 123, 'results': 0, 'scratch': 0}

    monkeypatch.setattr(module.storage, 'usage', usage)
    response = client.get('/api' + path)
    assert response.status_code == 200
    assert set(scanned) == ({role} if role == 'owner' else set(people))
    if role == 'owner':
        assert response.json()['username'] == role
    else:
        assert {row['user_id'] for row in response.json()} == set(people)
