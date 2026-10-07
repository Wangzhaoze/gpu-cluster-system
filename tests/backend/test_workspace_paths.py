import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main as main_module, storage as storage_module
from app.auth import current_user
from app.db import get_db
from app.main import app


@pytest.fixture
def host_settings(monkeypatch):
    settings = SimpleNamespace(host_root="/srv/gpu cluster's/runtime/", dataset_host_path="/srv/shared datasets", runtime_root="/runtime")
    monkeypatch.setattr(storage_module, "settings", settings)
    return settings


def test_reported_host_paths_are_the_actual_bind_sources(host_settings):
    storage = storage_module.DockerStorage()
    paths = storage.host_paths("student01")
    assert paths == {"workspace": "/srv/gpu cluster's/runtime/users/student01/workspace", "results": "/srv/gpu cluster's/runtime/results/student01", "scratch": "/srv/gpu cluster's/runtime/scratch/student01", "datasets": "/srv/shared datasets"}
    mounts = {mount["Target"]: mount for mount in storage.mounts("student01")}
    for name, path in paths.items():
        assert mounts["/" + name]["Source"] == path
    assert mounts["/datasets"]["ReadOnly"] is True


@pytest.fixture
def member_workspace(monkeypatch, host_settings):
    user = SimpleNamespace(id="member-id", username="student01", role="MEMBER", uid_hint=2001, default_environment_id="env")
    record = SimpleNamespace(state="STOPPED", route_path="/w/member-id/", container_id=None)
    db = MagicMock()
    db.get.return_value = record
    monkeypatch.setattr(main_module.runtime, "get", lambda name: None)
    monkeypatch.setattr(main_module, "public_environment", lambda env: {})
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app), user
    finally:
        app.dependency_overrides.clear()


def test_member_workspace_omits_host_details(member_workspace):
    client, user = member_workspace
    response = client.get("/api/workspace")
    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "STOPPED"
    assert not {"host_paths", "host_uid", "host_gid", "host_import_command"} & result.keys()


def test_admin_lookup_exposes_host_paths_and_safe_import_command(member_workspace):
    client, user = member_workspace
    user.role = "ADMIN"
    target = SimpleNamespace(id="target", username="student01", role="MEMBER", uid_hint=2001, default_environment_id="env")
    from app import main as module
    from unittest.mock import patch
    with patch.object(module, "target_user", return_value=target):
        result = client.get("/api/workspace?user_id=target").json()
    assert result["host_paths"]["workspace"] == "/srv/gpu cluster's/runtime/users/student01/workspace"
    assert shlex.split(result["host_import_command"])[-1] == result["host_paths"]["workspace"] + "/project/"


def test_member_cannot_read_another_members_host_paths(member_workspace):
    client, _ = member_workspace
    assert client.get("/api/workspace?user_id=another-member").status_code == 403


def test_anonymous_cannot_read_host_paths():
    assert TestClient(app).get("/api/workspace").status_code == 401
