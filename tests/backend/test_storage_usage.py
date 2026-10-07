from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

from app import storage as module


def test_usage_caches_large_scans_and_refreshes_without_following_dataset_links(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'settings', SimpleNamespace(runtime_root=str(tmp_path)))
    clock = [100.0]
    monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    storage = module.DockerStorage()
    storage.provision('student01')
    workspace = tmp_path / 'users/student01/workspace'
    project = workspace / 'project.txt'
    project.write_text('123')
    shared = tmp_path / 'datasets'
    shared.mkdir()
    (shared / 'large.bin').write_bytes(b'x' * 1000)
    (workspace / 'dataset').symlink_to(shared, target_is_directory=True)
    first = storage.usage('student01')
    assert first == {'workspace': 3, 'results': 0, 'scratch': 0}
    first['workspace'] = 99  # Callers cannot mutate the cached result.
    project.write_text('1234567')
    clock[0] += 59
    assert storage.usage('student01')['workspace'] == 3
    clock[0] += 1
    assert storage.usage('student01')['workspace'] == 7
    storage.delete_user_data('student01', ('workspace', 'scratch'))
    assert storage.usage('student01')['workspace'] == 0


def test_concurrent_storage_polling_scans_a_user_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'settings', SimpleNamespace(runtime_root=str(tmp_path)))
    storage = module.DockerStorage()
    entered, release, counter_lock = Event(), Event(), Lock()
    calls = []

    def scan(username):
        with counter_lock:
            calls.append(username)
        entered.set()
        assert release.wait(5)
        return {'workspace': 777, 'results': 0, 'scratch': 0}

    monkeypatch.setattr(storage, '_scan_usage', scan)
    with ThreadPoolExecutor(max_workers=20) as executor:
        requests = [executor.submit(storage.usage, 'student01') for _ in range(20)]
        assert entered.wait(5)
        release.set()
        assert all(request.result(timeout=5)['workspace'] == 777 for request in requests)
    assert calls == ['student01']
