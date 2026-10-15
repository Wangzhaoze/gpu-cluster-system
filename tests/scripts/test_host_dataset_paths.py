import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_host_editor_uses_physical_dataset_paths_and_optional_share(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("host_dataset_test", ROOT / "scripts/host_editor.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    data, share = tmp_path / "NVMe" / "dataset", tmp_path / "share" / "Datasets"
    data.mkdir(parents=True); share.mkdir(parents=True)
    alias = tmp_path / "dataset"; alias.symlink_to(data)
    values = {"DATASET_HOST_PATH": str(alias)}
    monkeypatch.setattr(module, "get_env", lambda key: values[key])
    assert module.dataset_sources() == {"DATASET": data}
    values["DATASET_ELAB_SHARE_HOST_PATH"] = str(share)
    assert module.dataset_sources() == {"DATASET": data, "DATASET_ELAB_SHARE": share}


def test_host_console_environment_does_not_require_online_smb(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("host_dataset_offline_test", ROOT / "scripts/host_editor.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    values = {"DATASET_HOST_PATH": str(tmp_path), "DATASET_ELAB_SHARE_HOST_PATH": "/mnt/offline/Datasets"}
    monkeypatch.setattr(module, "get_env", lambda key: values[key])
    assert module.dataset_sources()["DATASET_ELAB_SHARE"] == Path("/mnt/offline/Datasets")
