from types import SimpleNamespace
from unittest.mock import MagicMock

from docker.errors import NotFound
from app import update_images


def test_cleanup_protects_all_container_and_template_references_and_tags(monkeypatch):
    images = {name: SimpleNamespace(id=name, tags=[]) for name in ['obsolete', 'stopped-container', 'template', 'other-tag', 'builder']}
    images['other-tag'].tags = ['keep:tag']
    images['builder'].tags = ['node:temporary']
    client = MagicMock()
    client.containers.list.return_value = [SimpleNamespace(attrs={'Image': 'stopped-container'})]
    def get(reference):
        reference = {'custom:template': 'template', 'node:temporary': 'builder'}.get(reference, reference)
        if reference not in images: raise NotFound('gone')
        return images[reference]
    client.images.get.side_effect = get
    monkeypatch.setitem(update_images.runtime.__dict__, 'client', client)
    session = MagicMock()
    session.__enter__.return_value.scalars.return_value = [SimpleNamespace(image='custom:template')]
    monkeypatch.setattr(update_images, 'SessionLocal', lambda: session)
    assert update_images.cleanup_images(['obsolete', 'stopped-container', 'template', 'other-tag', 'missing'], 'node:temporary') == ['obsolete']
    assert [(c.args, c.kwargs) for c in client.images.remove.call_args_list] == [(('obsolete',), {'force': False}), (('node:temporary',), {'force': False})]


def test_cleanup_fails_closed_if_reference_inventory_fails(monkeypatch):
    client = MagicMock()
    client.containers.list.side_effect = RuntimeError('Docker unavailable')
    monkeypatch.setitem(update_images.runtime.__dict__, 'client', client)
    import pytest
    with pytest.raises(RuntimeError): update_images.cleanup_images(['obsolete'])
    client.images.remove.assert_not_called()


def test_atomic_ledger_replacement_preserves_host_ownership(monkeypatch, tmp_path):
    import json
    path = tmp_path / 'image-ledger.json'
    path.write_text('[]')
    before = path.stat()
    chown = MagicMock()
    monkeypatch.setattr(update_images.os, 'chown', chown)
    update_images.write_ledger(path, ['old', 'old'])
    assert json.loads(path.read_text()) == ['old']
    assert path.stat().st_mode & 0o777 == 0o600
    chown.assert_called_once_with(path.with_suffix('.tmp'), before.st_uid, before.st_gid)
    chown.reset_mock()
    builder = tmp_path / 'builder-ledger.json'
    update_images.write_ledger(builder, [], before)
    chown.assert_called_once_with(builder.with_suffix('.tmp'), before.st_uid, before.st_gid)
