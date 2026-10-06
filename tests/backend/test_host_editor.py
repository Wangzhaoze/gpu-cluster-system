from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from app.auth import current_user
from app.db import get_db
from app import main as module
from app.main import app


@pytest.fixture
def actor():
    db = MagicMock()
    user = SimpleNamespace(id="admin-id", role="ADMIN", enabled=True, username="admin")
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), user, db
    finally:
        app.dependency_overrides.clear()


def test_admin_workspace_uses_native_host_without_creating_container(actor, monkeypatch):
    client, user, db = actor
    host = {"mode": "host", "state": "RUNNING", "route_path": "/host/", "container_id": None, "host_user": "local", "host_home": "/home/local", "host_uid": 1000, "host_gid": 1000, "host_python": "/home/local/miniconda3/envs/dl/bin/python"}
    monkeypatch.setattr(module, "host_workspace", lambda: host, raising=False)
    get = MagicMock()
    monkeypatch.setattr(module.runtime, "get", get)
    result = client.get("/api/workspace")
    assert result.status_code == 200 and result.json() == host
    get.assert_not_called()
    db.get.assert_not_called()


@pytest.mark.parametrize("path", ["/host/", "/host/?folder=/home/local", "/host/static/file.js"])
def test_admin_can_authorize_host_route(actor, path):
    client, _, _ = actor
    assert client.get("/api/auth/traefik", headers={"X-Forwarded-Uri": path}).status_code == 200


@pytest.mark.parametrize("path", ["/host/../etc/", "/host/%2e%2e/etc/", "/hostevil/", "/host/%00"])
def test_host_auth_rejects_invalid_paths(actor, path):
    client, _, _ = actor
    assert client.get("/api/auth/traefik", headers={"X-Forwarded-Uri": path}).status_code == 403


def test_admin_proxy_auth(actor):
    client, _, _ = actor
    assert client.get("/api/auth/host-editor").status_code == 204


def test_member_cannot_authorize_host(actor):
    client, user, _ = actor
    user.role = "MEMBER"
    assert client.get("/api/auth/host-editor").status_code == 403
    assert client.get("/api/auth/traefik", headers={"X-Forwarded-Uri": "/host/"}).status_code == 403


def test_guest_cannot_authorize_host():
    assert TestClient(app).get("/api/auth/host-editor").status_code == 401


def test_host_workspace_cannot_be_deleted(actor, monkeypatch):
    client, user, _ = actor
    monkeypatch.setattr(module, "lock_user", lambda db, target: target)
    remove = MagicMock()
    monkeypatch.setattr(module.storage, "delete_user_data", remove)
    assert client.delete("/api/workspace").status_code == 422
    remove.assert_not_called()


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_host_process_not_controlled_as_student_container(actor, monkeypatch, action):
    client, _, _ = actor
    monkeypatch.setattr(module, "lock_user", lambda db, target: target)
    remove = MagicMock()
    monkeypatch.setattr(module.runtime, "remove", remove)
    assert client.post("/api/workspace/" + action).status_code == 422
    remove.assert_not_called()
