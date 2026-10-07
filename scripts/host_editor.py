#!/usr/bin/env python3
"""Install/run a native Ubuntu editor using the existing local Linux identity."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import time

from lab_env import get_env, update_env

ROOT = Path(__file__).resolve().parent.parent
SERVICE = "gpu-cluster-host-editor.service"


def docker(*args):
    command = ["docker", *args]
    if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        command = ["sg", "docker", "-c", shlex.join(command)]
    return subprocess.check_output(command, text=True).strip()


def editor_root():
    return Path(get_env("LAB_HOST_ROOT")) / "host-editor"


def install():
    user = pwd.getpwuid(os.getuid())
    if user.pw_name != "local" or user.pw_uid == 0:
        raise RuntimeError("Install as the selected existing Linux user local, not root")
    home = Path(user.pw_dir)
    directory = editor_root()
    for name in ("", "server", "run", "user-data", "extensions"):
        path = directory / name
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    binary = directory / "server/code-server/bin/code-server"
    if not binary.exists():
        container = docker("create", "--entrypoint", "/bin/true", get_env("LAB_BASE_IMAGE"))
        try:
            docker("cp", container + ":/usr/lib/code-server", str(directory / "server"))
            extension_stage = directory / "extension-stage"
            docker("cp", container + ":/opt/lab/extensions", str(extension_stage))
            shutil.copytree(extension_stage, directory / "extensions", dirs_exist_ok=True)
            shutil.rmtree(extension_stage)
        finally:
            docker("rm", container)
    subprocess.run([str(binary), "--version"], check=True)
    python = home / "miniconda3/envs/dl/bin/python"
    if not python.exists():
        python = Path(shutil.which("python3"))
    dataset = home / "dataset"
    source = Path(get_env("DATASET_HOST_PATH")).resolve(strict=True)
    if dataset.is_symlink() and dataset.resolve() != source:
        dataset.unlink()
    if not dataset.exists():
        dataset.symlink_to(source, target_is_directory=True)
    if dataset.resolve() != source:
        raise RuntimeError("Host dataset alias conflicts with an existing directory")
    shell_init = directory / "host-bashrc"
    shell_init.write_text('if test -f "$HOME/.bashrc"; then source "$HOME/.bashrc"; fi\n')
    conda = home / "miniconda3/etc/profile.d/conda.sh"
    if conda.exists() and (python.parent.parent / "conda-meta").is_dir():
        with shell_init.open("a") as stream:
            stream.write("source " + shlex.quote(str(conda)) + "\nconda activate " + shlex.quote(str(python.parent.parent)) + "\n")
    else:
        with shell_init.open("a") as stream:
            stream.write("export PATH=" + shlex.quote(str(python.parent)) + ':"$PATH"\n')
    with shell_init.open("a") as stream:
        stream.write("export DATASET=" + shlex.quote(str(dataset)) + "\n")
    settings = directory / "user-data/User/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    if not settings.exists():
        settings.write_text(json.dumps({
            "python.defaultInterpreterPath": str(python),
            "python.terminal.activateEnvironment": True,
            "terminal.integrated.profiles.linux": {"Host bash": {"path": "/bin/bash", "args": ["--rcfile", str(shell_init)]}},
            "terminal.integrated.defaultProfile.linux": "Host bash",
        }, indent=2) + "\n")
    config = directory / "config.yaml"
    config.write_text("auth: none\nsocket: " + json.dumps(str(directory / "run/editor.sock")) + '\nsocket-mode: "0600"\ndisable-telemetry: true\ndisable-update-check: true\nabs-proxy-base-path: /host\nuser-data-dir: ' + json.dumps(str(directory / "user-data")) + "\nextensions-dir: " + json.dumps(str(directory / "extensions")) + "\n")
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"binary": str(binary), "home": str(home), "user": user.pw_name, "uid": user.pw_uid, "gid": user.pw_gid, "python": str(python)}, indent=2))
    unit = home / ".config/systemd/user" / SERVICE
    unit.parent.mkdir(parents=True, exist_ok=True)
    command = shlex.join([shutil.which("python3"), str(ROOT / "scripts/host_editor.py"), "run"])
    # sg refreshes existing Docker membership without granting sudo privileges.
    exec_args = ["/usr/bin/sg", "docker", "-c", command]
    exec_line = " ".join(json.dumps(arg) for arg in exec_args)
    unit.write_text("[Unit]\nDescription=GPU cluster native Ubuntu administrator editor\n\n[Service]\nType=simple\nWorkingDirectory=" + str(home) + "\nExecStart=" + exec_line + "\nRestart=on-failure\nRestartSec=3\nUMask=0077\n\n[Install]\nWantedBy=default.target\n")
    update_env({"LAB_HOST_EDITOR_ENABLED": "true", "LAB_HOST_EDITOR_USER": user.pw_name, "LAB_HOST_EDITOR_HOME": str(home), "LAB_HOST_EDITOR_UID": str(user.pw_uid), "LAB_HOST_EDITOR_GID": str(user.pw_gid), "LAB_HOST_EDITOR_PYTHON": str(python)})
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE], check=True)
    subprocess.run(["systemctl", "--user", "restart", SERVICE], check=True)
    for _ in range(50):
        if (directory / "run/editor.sock").is_socket():
            print("Native host editor installed for local; private Unix socket ready.")
            return
        time.sleep(0.2)
    raise RuntimeError("Native editor did not create its socket; inspect journalctl --user -u " + SERVICE)


def run():
    directory = editor_root()
    manifest = json.loads((directory / "manifest.json").read_text())
    if os.getuid() != manifest["uid"]:
        raise RuntimeError("Native host identity mismatch")
    os.environ["DATASET"] = str(Path(manifest["home"]) / "dataset")
    os.execv(manifest["binary"], [manifest["binary"], "--config", str(directory / "config.yaml"), manifest["home"]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "run", "start", "stop", "restart", "status"))
    action = parser.parse_args().action
    if action == "install":
        install()
    elif action == "run":
        run()
    else:
        subprocess.run(["systemctl", "--user", action, SERVICE], check=True)
