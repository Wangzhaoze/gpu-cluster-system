from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import current_user
from app.main import app


@pytest.mark.parametrize('path', [
    '/api/users/unknown', '/api/workspace', '/api/jobs/unknown',
    '/api/debug/unknown', '/api/environments/unknown', '/api/admin/images/unknown',
])
def test_members_cannot_delete_even_their_own_resources(path):
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='unknown', role='MEMBER')
    try:
        response = TestClient(app).delete(path)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('path', [
    '/api/users/unknown', '/api/workspace', '/api/jobs/unknown',
    '/api/debug/unknown', '/api/environments/unknown', '/api/admin/images/unknown',
])
def test_anonymous_cannot_delete(path):
    assert TestClient(app).delete(path).status_code == 401
