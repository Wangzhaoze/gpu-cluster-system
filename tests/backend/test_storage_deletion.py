from types import SimpleNamespace

from app import storage as module


def test_workspace_deletion_preserves_results_and_symlink_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'settings', SimpleNamespace(runtime_root=str(tmp_path)))
    storage = module.DockerStorage()
    storage.provision('student01')
    dataset = tmp_path / 'datasets'
    dataset.mkdir()
    (dataset / 'shared.txt').write_text('shared data')
    workspace = tmp_path / 'users/student01/workspace'
    (workspace / 'data-link').symlink_to(dataset, target_is_directory=True)
    (workspace / 'code.py').write_text('print(1)')
    result = tmp_path / 'results/student01/result.txt'
    result.write_text('retained result')
    storage.delete_user_data('student01', ('workspace', 'scratch'))
    assert not workspace.exists()
    assert result.read_text() == 'retained result'
    assert (dataset / 'shared.txt').read_text() == 'shared data'
