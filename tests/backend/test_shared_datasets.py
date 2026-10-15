from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import docker_runtime as runtime_module, storage as storage_module
from app.models import EnvVar
from test_role_portals import portal


@pytest.mark.parametrize("share", ["", "/mnt/elab-share/Datasets"])
def test_shared_dataset_mounts_are_optional_read_only_and_preserve_user_volumes(monkeypatch, share):
    monkeypatch.setattr(storage_module, "settings", replace(storage_module.settings,
        dataset_host_path="/media/local/NVME-Storage/dataset", dataset_elab_share_host_path=share))
    storage = storage_module.DockerStorage()
    mounts = {m["Target"]: m for m in storage.mounts("student01")}
    for target in ["/datasets", "/home/student01/dataset"]:
        assert mounts[target]["Source"] == "/media/local/NVME-Storage/dataset"
        assert mounts[target]["ReadOnly"] is True
    for target in ["/datasets_elab_share", "/home/student01/dataset_elab_share"]:
        if share:
            assert mounts[target]["Source"] == share
            assert mounts[target]["ReadOnly"] is True
        else:
            assert target not in mounts
    assert mounts["/opt/user-env"]["Source"] == "lab_pyenv_student01"
    assert mounts["/opt/user-state"]["Source"] == "lab_userstate_student01"
    assert storage.host_paths("student01").get("datasets_elab_share", "") == share


@pytest.mark.parametrize("value", ["$HOME/dataset_elab_share", "${HOME}/dataset_elab_share"])
def test_global_smb_variable_resolves_for_each_member(portal, monkeypatch, value):
    _, db, people, _ = portal
    monkeypatch.setattr(runtime_module, "settings", replace(runtime_module.settings,
        dataset_elab_share_host_path="/mnt/elab-share/Datasets"))
    db.add(EnvVar(scope="global", key="DATASET_ELAB_SHARE", value=value)); db.commit()
    for name in ["owner", "other"]:
        person = people[name]
        env = runtime_module.runtime.env(db, person, {}, [], False)
        assert env["DATASET_ELAB_SHARE"] == f"/home/{person.username}/dataset_elab_share"
        assert env["DATASET"] == f"/home/{person.username}/dataset"


def test_smb_default_present_without_database_env_record(portal, monkeypatch):
    _, db, people, _ = portal
    monkeypatch.setattr(runtime_module, "settings", replace(runtime_module.settings,
        dataset_elab_share_host_path="/mnt/elab-share/Datasets"))
    env = runtime_module.runtime.env(db, people["owner"], {}, [], False)
    assert env["DATASET_ELAB_SHARE"] == "/home/owner/dataset_elab_share"
