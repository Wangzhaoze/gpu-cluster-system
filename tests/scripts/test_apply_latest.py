"""Exercise the real shell script with fake Docker, never the host daemon."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

FAKE_DOCKER = r'''#!/usr/bin/env python3
import datetime, hashlib, json, os, pathlib, sys
args = sys.argv[1:]
state_path = pathlib.Path(os.environ['FAKE_DOCKER_STATE'])
state = json.loads(state_path.read_text())
with open(os.environ['FAKE_DOCKER_LOG'], 'a') as log: log.write(json.dumps(args)+'\n')
def persist(): state_path.write_text(json.dumps(state))
def image(ref):
    identifier=state['tags'].get(ref,ref)
    return identifier if identifier in state['images'] else None
if args[0]=='info':
    if '--format' in args: print('linux')
    sys.exit(0)
if args[:2]==['image','inspect']:
    ref=args[-1]; identifier=image(ref)
    if not identifier: sys.exit(1)
    print(state['labels'].get(identifier,'') if 'fingerprint' in args[3] else identifier)
elif args[:2]==['image','tag']:
    state['tags'][args[3]]=args[2]; persist()
elif args[0]=='pull':
    identifier='sha256:'+hashlib.sha256(args[1].encode()).hexdigest()
    state['tags'][args[1]]=identifier;state['images'].append(identifier);persist()
elif args[0]=='inspect':
    name=args[-1].removeprefix('container-'); service=state['services'][name]
    print('true' if service['running'] else 'false') if 'Running' in args[2] else print(service['image'] if 'Image' in args[2] else '2026-10-08T00:00:00Z')
elif args[0]=='logs':
    if not state.get('unregistered_tunnel'): print('Registered tunnel connection\nhttps://synthetic-test.trycloudflare.com')
elif args[0]=='compose':
    rest=args[1:];files=[]
    while rest and rest[0] in ['--profile','-f']:
        if rest[0]=='-f':files.append(rest[1])
        rest=rest[2:]
    action=rest[0];services=[s for s in rest[1:] if s in ['backend','frontend','scheduler-worker','postgres','traefik','gpu-monitor','host-editor-proxy','cloudflared']]
    if action=='config': pass
    elif action=='ps':
        if services:
            for service in services:
                if service in state['services']: print('container-'+service)
    elif action=='build':
        for service in services:
            if state.get('fail_build')==service: sys.exit(1)
            label=os.environ['LAB_'+service.upper()+'_BUILD_FINGERPRINT']
            identifier='sha256:'+hashlib.sha256((service+label).encode()).hexdigest()
            state['tags']['lab-'+service+':2026.10-poc']=identifier
            state['labels'][identifier]=label
            if identifier not in state['images']:state['images'].append(identifier)
        persist()
    elif action=='stop':
        for service in services:state['services'][service]['running']=False
        persist()
    elif action in ['up','start']:
        if state.get('fail_up') and 'backend' in services and not files:
            state['fail_up']=False;persist();sys.exit(1)
        if files:state['rollback_command']=pathlib.Path(files[-1]).read_text()
        for service in services:
            target=state['tags'].get('lab-'+('backend' if service=='scheduler-worker' else service)+':2026.10-poc','sha256:'+'9'*64)
            previous=state['services'].get(service)
            if action=='start' and previous:target=previous['image']
            count=(previous or {}).get('generation',0)
            if not previous or previous['image']!=target or '--force-recreate' in rest:count+=1
            state['services'][service]={'image':target,'running':True,'generation':count}
            if service=='scheduler-worker' and not state.get('missing_heartbeat'):
                heartbeat=pathlib.Path(os.environ['FAKE_RUNTIME'])/'logs/scheduler-heartbeat'
                heartbeat.parent.mkdir(parents=True,exist_ok=True)
                heartbeat.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())
        persist()
    elif action=='exec':
        if 'app.update_images' in rest:
            ledger=pathlib.Path(os.environ['FAKE_RUNTIME'])/'logs/apply-latest-images.json'
            refs={s['image'] for s in state['services'].values()}|set(state['tags'].values())
            for candidate in json.loads(ledger.read_text()):
                if candidate not in refs and candidate in state['images']:state['images'].remove(candidate)
            builder_ledger=pathlib.Path(os.environ['FAKE_RUNTIME'])/'logs/apply-latest-builders.json'
            builders=json.loads(builder_ledger.read_text()) if builder_ledger.exists() else []
            if '--builder-tag' in rest:builders.append(rest[rest.index('--builder-tag')+1])
            for tag in set(builders):
                identifier=state['tags'].pop(tag,None)
                if identifier and identifier not in set(state['tags'].values()):state['images'].remove(identifier)
            builder_ledger.write_text('[]')
            ledger.write_text('[]');persist()
        else: print('{"status":"ok"}')
else: raise SystemExit('Unexpected fake Docker call: '+repr(args))
'''


@pytest.fixture
def checkout(tmp_path):
    for relative in ['apply-latest.sh', 'scripts/lab_env.py', 'scripts/image_fingerprint.py', 'scripts/lab.sh']:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, path)
    (tmp_path / 'compose.yaml').write_text('services: {}\n')
    for folder in ['backend', 'frontend', 'tests/backend', 'tests/integration']:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        (tmp_path / folder / 'input.txt').write_text(folder)
    runtime = tmp_path / 'runtime'
    (runtime / 'logs').mkdir(parents=True)
    (tmp_path / '.env').write_text(f'LAB_HOST_ROOT={runtime}\nLAB_BASE_IMAGE=lab-base:current\nLOCAL_NODE_IMAGE=node:test\nSCHEDULER_BACKEND=local-gpu-docker\nLAB_HOST_EDITOR_ENABLED=false\n')
    backend, frontend, base = ['sha256:' + digit * 64 for digit in '123']
    state = {'tags': {'lab-backend:2026.10-poc': backend, 'lab-frontend:2026.10-poc': frontend, 'lab-base:current': base},
             'images': [backend, frontend, base], 'labels': {},
             'services': {name: {'image': backend if name in ['backend', 'scheduler-worker'] else frontend if name == 'frontend' else base, 'running': True, 'generation': 1}
                          for name in ['backend', 'frontend', 'scheduler-worker', 'postgres', 'traefik', 'gpu-monitor', 'cloudflared']}}
    state_path, log_path = tmp_path / 'docker.json', tmp_path / 'calls.jsonl'
    state_path.write_text(json.dumps(state))
    tools = tmp_path / 'bin'
    tools.mkdir()
    docker = tools / 'docker'
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    git = tools / 'git'
    git.write_text('#!/bin/sh\nif [ "$1" = status ]; then echo " M TODO.md"; else exit 1; fi\n')
    git.chmod(0o755)
    environment = {**os.environ, 'PATH': str(tools) + ':' + os.environ['PATH'], 'FAKE_DOCKER_STATE': str(state_path), 'FAKE_DOCKER_LOG': str(log_path), 'FAKE_RUNTIME': str(runtime)}
    def run(*args):
        result = subprocess.run(['bash', str(tmp_path / 'apply-latest.sh'), *args], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=25)
        return result, json.loads(state_path.read_text()), [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
    return tmp_path, state_path, run


def actions(calls, action):
    return [c for c in calls if c[0] == 'compose' and action in c]


def test_build_before_pause_and_idempotent_second_run(checkout):
    root, _, run = checkout
    result, first, calls = run()
    assert result.returncode == 0, result.stdout + result.stderr
    builds = actions(calls, 'build')
    assert [c[-1] for c in builds] == ['backend', 'frontend']
    assert max(calls.index(c) for c in builds) < calls.index(actions(calls, 'stop')[0])
    assert not any('app.apply_update' in c or 'prune' in c or 'down' in c or 'rm' in c for c in calls)
    assert all(first['services'][s]['generation'] == 1 for s in ['postgres', 'traefik', 'gpu-monitor', 'cloudflared'])
    result, second, all_calls = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions(all_calls, 'build') == builds
    assert second['images'] == first['images'] and second['services'] == first['services']
    assert 'Current checkout applied' in result.stdout


def test_stopped_and_missing_infrastructure_can_start(checkout):
    _, state_path, run = checkout
    state = json.loads(state_path.read_text())
    for service in state['services'].values(): service['running'] = False
    del state['services']['traefik']
    state_path.write_text(json.dumps(state))
    result, updated, calls = run('--no-build')
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(service['running'] for service in updated['services'].values())
    assert not actions(calls, 'build')
    assert updated['services']['cloudflared']['generation'] == 1
    assert any(c[-1] == 'traefik' for c in actions(calls, 'up'))


def test_first_start_and_explicit_remote(checkout):
    _, state_path, run = checkout
    state = json.loads(state_path.read_text()); state['services'] = {}
    state_path.write_text(json.dumps(state))
    result, updated, _ = run('--remote')
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(s['running'] for s in updated['services'].values())
    assert 'cloudflared' in updated['services']


def test_build_failure_restores_tags_without_stopping_services(checkout):
    _, state_path, run = checkout
    state = json.loads(state_path.read_text()); before_tags = dict(state['tags'])
    state['fail_build'] = 'frontend'; state_path.write_text(json.dumps(state))
    result, after, calls = run()
    assert result.returncode != 0
    assert after['tags']['lab-backend:2026.10-poc'] == before_tags['lab-backend:2026.10-poc']
    assert all(s['running'] for s in after['services'].values())
    assert not actions(calls, 'stop')


def test_update_failure_restores_apps_and_worker_with_additive_migrations(checkout):
    _, state_path, run = checkout
    state = json.loads(state_path.read_text()); state['fail_up'] = True
    state_path.write_text(json.dumps(state))
    result, restored, calls = run()
    assert result.returncode != 0
    assert all(restored['services'][s]['running'] for s in ['backend', 'frontend', 'scheduler-worker'])
    assert restored['services']['backend']['image'] == 'sha256:' + '1' * 64
    assert 'uvicorn' in restored['rollback_command'] and 'alembic' not in restored['rollback_command']
    assert not any('prune' in c or 'down' in c for c in calls)


def test_local_changes_supported_but_explicit_pull_requires_clean_checkout(checkout):
    _, _, run = checkout
    result, _, calls = run('--pull')
    assert result.returncode != 0 and 'clean tracked files' in result.stderr
    assert not calls


def test_help_and_process_lock_do_not_touch_docker(checkout):
    root, _, run = checkout
    result, _, calls = run('--help')
    assert result.returncode == 0 and not calls
    with (root / '.apply-latest.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, _, calls = run()
        assert result.returncode != 0 and 'already running' in result.stderr and not calls


def test_explicit_restart_recreates_only_application_containers(checkout):
    _, _, run = checkout
    result, updated, calls = run('--no-build', '--restart')
    assert result.returncode == 0, result.stdout + result.stderr
    forced = [c for c in actions(calls, 'up') if '--force-recreate' in c]
    assert len(forced) == 1 and forced[0][-2:] == ['backend', 'frontend']
    assert updated['services']['cloudflared']['generation'] == 1


def test_stale_scheduler_heartbeat_cannot_report_success(checkout):
    root, state_path, run = checkout
    script = root / 'apply-latest.sh'
    script.write_text(script.read_text().replace('range(60)', 'range(1)'))
    state = json.loads(state_path.read_text()); state['missing_heartbeat'] = True
    state_path.write_text(json.dumps(state))
    result, restored, _ = run('--no-build')
    assert result.returncode != 0 and 'fresh heartbeat' in result.stderr
    assert 'Current checkout applied' not in result.stdout
    assert restored['services']['backend']['image'] == 'sha256:' + '1' * 64


def test_failed_frontend_builder_is_cleaned_on_successful_retry(checkout):
    root, state_path, run = checkout
    state = json.loads(state_path.read_text()); state['fail_build'] = 'frontend'
    state_path.write_text(json.dumps(state))
    result, failed, _ = run()
    assert result.returncode != 0 and 'node:test' in failed['tags']
    assert json.loads((root / 'runtime/logs/apply-latest-builders.json').read_text()) == ['node:test']
    failed.pop('fail_build'); state_path.write_text(json.dumps(failed))
    result, recovered, _ = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'node:test' not in recovered['tags']
    assert json.loads((root / 'runtime/logs/apply-latest-builders.json').read_text()) == []


def test_native_host_editor_profile_starts_under_its_configured_user(checkout):
    root, _, run = checkout
    with (root / '.env').open('a') as env:
        env.write(f'LAB_HOST_EDITOR_ENABLED=true\nLAB_HOST_EDITOR_UID={os.getuid()}\nLAB_HOST_EDITOR_USER=local\n')
    script = root / 'scripts/host-editor.sh'
    script.write_text('#!/bin/sh\ntest "$1" = start\n')
    script.chmod(0o755)
    result, started, calls = run('--no-build')
    assert result.returncode == 0, result.stdout + result.stderr
    assert started['services']['host-editor-proxy']['running']
    assert any('--profile' in call and 'host' in call for call in calls)


def test_unregistered_public_tunnel_cannot_report_success(checkout):
    root, state_path, run = checkout
    script = root / 'apply-latest.sh'
    script.write_text(script.read_text().replace('{1..15}', '{1..1}'))
    state = json.loads(state_path.read_text()); state['unregistered_tunnel'] = True
    state_path.write_text(json.dumps(state))
    result, restored, _ = run('--no-build')
    assert result.returncode != 0 and 'Public tunnel did not register' in result.stderr
    assert 'Current checkout applied' not in result.stdout
    assert restored['services']['backend']['image'] == 'sha256:' + '1' * 64
