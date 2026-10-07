from types import SimpleNamespace

from app import docker_runtime as runtime_module, storage as storage_module


class EmptyDB:
    def scalars(self, _query):
        return []


def test_storage_mounts_persistent_user_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_module,
        "settings",
        SimpleNamespace(
            runtime_root=str(tmp_path),
            host_root="/srv/lab",
            dataset_host_path="/srv/datasets",
        ),
    )
    storage = storage_module.DockerStorage()
    mounts = {mount["Target"]: mount for mount in storage.mounts("student01")}
    assert mounts["/opt/user-env"]["Type"] == "volume"
    assert mounts["/opt/user-env"]["Source"] == "lab_pyenv_student01"
    assert mounts["/opt/user-state"]["Type"] == "volume"
    assert mounts["/opt/user-state"]["Source"] == "lab_userstate_student01"


def test_runtime_pins_persistent_config_paths(monkeypatch):
    user = SimpleNamespace(id="user-id", username="student01", uid_hint=2001)
    runtime = runtime_module.DockerRuntime()
    env = runtime.env(
        EmptyDB(),
        user,
        {
            "CODEX_HOME": "/tmp/not-persistent",
            "XDG_CONFIG_HOME": "/tmp/config",
        },
        [],
        False,
    )
    assert env["CODEX_HOME"] == "/opt/user-state/codex"
    assert env["XDG_CONFIG_HOME"] == "/opt/user-state/xdg/config"
    assert env["XDG_DATA_HOME"] == "/opt/user-state/xdg/local/share"
    assert env["XDG_STATE_HOME"] == "/opt/user-state/xdg/local/state"
    assert env["HISTFILE"] == "/opt/user-state/shell/bash_history"
    assert env["GIT_CONFIG_GLOBAL"] == "/opt/user-state/git/config"
    assert env["NPM_CONFIG_PREFIX"] == "/opt/user-state/npm"


def test_destructive_user_volume_reset_removes_python_and_user_state(monkeypatch):
    removed = []

    class Volume:
        def __init__(self, name):
            self.name = name
            self.attrs = {"Labels": {"lab.project": "test-project"}}

        def remove(self, force=False):
            assert force is False
            removed.append(self.name)

    class Volumes:
        def get(self, name):
            return Volume(name)

    runtime = runtime_module.DockerRuntime()
    runtime.__dict__["client"] = SimpleNamespace(volumes=Volumes())
    monkeypatch.setattr(runtime_module, "settings", SimpleNamespace(project="test-project"))
    runtime.remove_python_volume(SimpleNamespace(username="student01"))
    assert removed == ["lab_pyenv_student01", "lab_userstate_student01"]
