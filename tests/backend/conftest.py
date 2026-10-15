import pytest
from unittest.mock import MagicMock
from app import resources


@pytest.fixture(autouse=True)
def isolated_host_capacity(monkeypatch):
    """Unit tests never contact the live Docker Engine for host capacity."""
    monkeypatch.setattr(resources, '_docker_info', lambda: {'NCPU': 32, 'MemTotal': 64 * 1024**3})
    monkeypatch.setitem(resources.runtime.__dict__, 'client', MagicMock())
    resources.runtime.client.containers.list.return_value = []
