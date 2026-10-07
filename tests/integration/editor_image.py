"""Real image acceptance for unprivileged extension seeding and persistent state.

Run from the backend with --keep when recovery fixtures must remain for review.
Existing users, project files and volumes are never modified.
"""
import argparse
import json
from pathlib import Path
import secrets
import time
from types import SimpleNamespace

import httpx
from docker.types import Mount
from app.config import settings
from app.docker_runtime import runtime


class EmptyDB:
    def scalars(self, _):
        return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', action='store_true')
    args = parser.parse_args()
    run = secrets.token_hex(5)
    username = 'editorprobe_' + run
    user = SimpleNamespace(username=username, uid_hint=28001, id=run)
    volumes, containers, checks = [], [], []
    success = False
    names = {kind: 'lab_recovery_' + kind + '_' + run for kind in ['workspace', 'python', 'state']}
    labels = {'lab.recovery.fixture': run, 'traefik.enable': 'false'}
    home = '/home/' + username
    marker = 'SYNTHETIC_RECOVERY_STATE_' + run

    def execute(container, code):
        result = container.exec_run(['/opt/user-env/venv/bin/python', '-c', code], user=username, environment={'HOME': home})
        assert result.exit_code == 0, result.output.decode(errors='replace')[-500:]

    def launch(index):
        container = runtime.client.containers.create(
            settings.torch_image,
            ['code-server', '--auth', 'none', '--bind-addr', '0.0.0.0:8080', '--disable-telemetry',
             '--user-data-dir', '/opt/user-state/code-server/user-data', '--extensions-dir', '/opt/user-state/code-server/extensions',
             '--session-socket', '/tmp/editor-recovery.sock', '/workspace'],
            name='lab-recovery-editor-' + run + '-' + str(index), labels=labels,
            environment=runtime.env(EmptyDB(), user, {}, [], False),
            mounts=[Mount('/workspace', names['workspace'], type='volume'), Mount('/opt/user-env', names['python'], type='volume'),
                    Mount('/opt/user-state', names['state'], type='volume'),
                    Mount(home + '/dataset', settings.dataset_host_path, type='bind', read_only=True)],
            network=settings.network, mem_limit='2048m', pids_limit=512,
        )
        containers.append(container)
        runtime.prepare_home(container, user)
        container.start()
        for _ in range(90):
            container.reload()
            assert container.status in {'created', 'running'}, container.logs(tail=20).decode(errors='replace')[-1000:]
            address = container.attrs['NetworkSettings']['Networks'][settings.network]['IPAddress']
            try:
                response = httpx.get('http://' + address + ':8080/', timeout=2, follow_redirects=True)
                if response.status_code == 200 and 'vscode-workbench-web-configuration' in response.text:
                    return container
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise AssertionError('New editor did not become ready')

    try:
        for image in [settings.base_image, settings.torch_image]:
            probe = runtime.client.containers.create(image, ['-c', 'test -r /opt/lab/extensions && test -x /opt/lab && test -r /usr/local/bin/configure-lab-editor && test -x /usr/local/bin/configure-lab-editor'], entrypoint='/bin/bash', user='65534:65534', network_mode='none', labels=labels)
            containers.append(probe)
            probe.start()
            assert probe.wait(timeout=30)['StatusCode'] == 0, image + ' member read permissions failed'
        checks.append('base and PyTorch images expose public extensions and readable editor helpers to an unprivileged UID')
        print('PASS ' + checks[-1], flush=True)
        for name in names.values():
            volumes.append(runtime.client.volumes.create(name, labels=labels))
        first = launch(1)
        execute(first, 'import os,torch; from pathlib import Path; assert torch.__version__=="2.7.1+cu128"; assert torch.version.cuda=="12.8"; assert os.environ["DATASET"]==str(Path.home()/"dataset"); assert Path(os.environ["DATASET"]).is_dir(); assert os.statvfs(os.environ["DATASET"]).f_flag & os.ST_RDONLY; assert os.access(Path.home()/".bashrc",os.W_OK)')
        execute(first, 'from pathlib import Path; import json; Path("/opt/user-state/codex/recovery-smoke.txt").write_text(' + repr(marker) + '); p=Path("/opt/user-state/code-server/user-data/User/settings.json"); v=json.loads(p.read_text()); v["editor.fontSize"]=19; p.write_text(json.dumps(v))')
        checks.append('fresh member editor initializes and serves its workbench with PyTorch, writable home and read-only HOME/dataset')
        print('PASS ' + checks[-1], flush=True)
        first.stop(timeout=5)
        second = launch(2)
        execute(second, 'from pathlib import Path; import json,os; assert Path("/opt/user-state/codex/recovery-smoke.txt").read_text()==' + repr(marker) + '; v=json.loads(Path("/opt/user-state/code-server/user-data/User/settings.json").read_text()); assert v["editor.fontSize"]==19; assert v["python.defaultInterpreterPath"]=="/opt/user-env/venv/bin/python"; assert Path("/opt/user-state/codex/recovery-smoke.txt").stat().st_uid==os.getuid()')
        checks.append('recreated editor starts against an initialized state volume and retains member settings and synthetic Codex state')
        print('PASS ' + checks[-1], flush=True)
        success = True
    finally:
        for container in containers:
            container.reload()
            if container.status == 'running':
                container.stop(timeout=5)
            if not args.keep:
                container.remove()
        if not args.keep:
            for volume in volumes:
                volume.remove()
        report = Path('/runtime/logs/workspace-recovery-20261007/image-acceptance.json')
        report.write_text(json.dumps({'success': success, 'passed': checks, 'fixtures_retained': args.keep,
                                     'containers': [c.name for c in containers], 'volumes': list(names.values())}, indent=2))
        report.chmod(0o600)
    assert success


if __name__ == '__main__':
    main()
