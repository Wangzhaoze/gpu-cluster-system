"""Destructive API acceptance, confined to a freshly created disposable account/image."""
import io
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import tarfile
import time

import docker
import httpx

admin = httpx.Client(base_url="http://traefik", timeout=60)
member = httpx.Client(base_url="http://traefik", timeout=60, follow_redirects=True)
anonymous = httpx.Client(base_url="http://traefik", timeout=60)
client = docker.from_env()
target = None
image = None
blocker = None
template = None
workloads = []
passed = []


def call(session, method, path, body=None, status=200):
    response = session.request(method, "/api" + path, json=body)
    assert response.status_code == status, (method, path, response.status_code, response.text[:600])
    return response.json()


def wait(check, description):
    for _ in range(90):
        result = check()
        if result:
            return result
        time.sleep(1)
    raise AssertionError("Timeout: " + description)


def done(name):
    passed.append(name)
    print("PASS " + name, flush=True)


def debug_state(identifier):
    return next(d for d in call(member, "GET", "/debug") if d["id"] == identifier)


try:
    me = call(admin, "POST", "/auth/login", {
        "username": os.environ["INITIAL_ADMIN_USERNAME"],
        "password": os.environ["INITIAL_ADMIN_PASSWORD"],
    })
    admin_id = call(admin, "GET", "/auth/me")["id"]
    password = secrets.token_urlsafe(24)
    target = call(admin, "POST", "/users", {
        "username": "deletecheck_" + secrets.token_hex(4),
        "display_name": "Disposable admin deletion check", "password": password,
        "max_gpus": 1, "max_debug_hours": 4,
    }, 201)
    env = next(e for e in call(admin, "GET", "/environments") if e["recommended"])
    assert target["default_environment_id"] == env["id"]
    call(member, "POST", "/auth/login", {"username": target["username"], "password": password})
    paths = ["/users/" + target["id"], "/workspace", "/jobs/missing", "/debug/missing",
             "/environments/" + env["id"], "/admin/images/" + env["image"]]
    for path in paths:
        call(member, "DELETE", path, status=403)
        call(anonymous, "DELETE", path, status=401)
    call(member, "GET", "/admin/images", status=403)
    call(admin, "DELETE", "/users/" + admin_id, status=422)
    call(admin, "DELETE", "/users/" + target["id"], status=409)
    call(admin, "DELETE", "/environments/" + env["id"], status=409)
    call(admin, "DELETE", "/admin/images/" + env["image"], status=409)
    done("member/anonymous deletion denied; self, enabled account and referenced image/template protected")

    workspace = call(member, "POST", "/workspace/start")
    wait(lambda: member.get(workspace["route_path"]).status_code == 200, "Python editor")
    container = client.containers.get(workspace["container_id"])
    probe = container.exec_run(["bash", "-ic", "python - <<'PY'\n"
        "import json, os, sys, torch\n"
        "assert sys.executable == '/opt/user-env/venv/bin/python'\n"
        "assert os.environ['VIRTUAL_ENV']=='/opt/user-env/venv'\n"
        "assert torch.__version__=='2.7.1+cu128'\n"
        "print('PYTHON_DEFAULT_OK', sys.executable, torch.__version__)\nPY"], user=target["username"], environment={"HOME": "/home/" + target["username"]})
    assert probe.exit_code == 0, probe.output.decode()
    print(probe.output.decode().strip(), flush=True)
    username = target["username"]
    settings_path = Path("/runtime/users", username, "workspace/.lab/code-server/workspace-" + username, "User/settings.json")
    editor_settings = json.loads(settings_path.read_text())
    assert editor_settings["python.defaultInterpreterPath"] == "/opt/user-env/venv/bin/python"
    assert editor_settings["python.terminal.activateEnvironment"]
    extensions = container.exec_run(["code-server", "--extensions-dir", "/workspace/.lab/extensions", "--list-extensions"], user=username)
    assert extensions.exit_code == 0 and b"ms-python.python" in extensions.output
    settings_path.write_text('{ // keep user preferences\n "editor.fontSize": 17, "python.defaultInterpreterPath": "/usr/bin/python", }\n')
    workspace = call(member, "POST", "/workspace/restart")
    wait(lambda: member.get(workspace["route_path"]).status_code == 200, "editor settings merge")
    preserved = json.loads(settings_path.read_text())
    assert preserved["editor.fontSize"] == 17
    assert preserved["python.defaultInterpreterPath"] == "/opt/user-env/venv/bin/python"
    container = client.containers.get(workspace["container_id"])
    root = Path("/runtime/users", username, "workspace")
    (root / "keep.py").write_text("print('keep')")
    (root / "datasets-link").symlink_to("/runtime/datasets", target_is_directory=True)
    results = Path("/runtime/results", username)
    results.joinpath("keep.txt").write_text("retained results")
    mark = container.exec_run(["bash", "-c", "echo marker > /opt/user-env/deletecheck-marker"], user=username)
    assert mark.exit_code == 0
    done("new accounts default to PyTorch; VS Code Python extension, interpreter settings and shell activation")

    debug = call(member, "POST", "/debug", {"requested_gpus": 1, "time_limit_seconds": 14400,
                 "requested_ram_mb": 4096}, 201)
    workloads.append(("debug", debug["id"]))
    current = wait(lambda: (d if (d := debug_state(debug["id"]))["status"] == "RUNNING"
                           and member.get(d["route_path"]).status_code == 200 else None), "real GPU debug")
    gpu_container = client.containers.get(current["container_id"])
    assert (datetime.fromisoformat(current['expires_at']) - datetime.fromisoformat(current['started_at'])).total_seconds() == 14400
    probe = gpu_container.exec_run(["bash", "-ic", "python -c 'import torch; assert torch.cuda.is_available(); assert torch.cuda.device_count()==1; x=torch.ones(128,128,device=\"cuda\"); assert (x@x)[0,0].item()==128; print(\"DEBUG_CUDA_DEFAULT_OK\",torch.cuda.get_device_name(0))'"], user=username, environment={"HOME": "/home/" + username})
    assert probe.exit_code == 0, probe.output.decode()
    print(probe.output.decode().strip(), flush=True)
    call(admin, "DELETE", "/debug/" + debug["id"], status=409)
    call(admin, "DELETE", "/workspace?user_id=" + target["id"], status=409)
    call(member, "DELETE", "/debug/" + debug["id"], status=403)
    call(member, "POST", "/debug/" + debug["id"] + "/stop")
    wait(lambda: debug_state(debug["id"])["status"] == "CANCELLED", "debug cancellation")
    call(admin, "DELETE", "/debug/" + debug["id"])
    assert not any(d["id"] == debug["id"] for d in call(member, "GET", "/debug"))
    assert (root / "keep.py").exists()
    done("real GPU debug uses default PyTorch; active deletion blocked and admin deletes stopped record")

    job = call(member, "POST", "/jobs", {"command": "sleep 45", "requested_gpus": 1}, 201)
    workloads.append(("jobs", job["id"]))
    wait(lambda: call(member, "GET", "/jobs/" + job["id"])["status"] == "RUNNING", "training startup")
    call(admin, "DELETE", "/jobs/" + job["id"], status=409)
    call(member, "DELETE", "/jobs/" + job["id"], status=403)
    call(member, "POST", "/jobs/" + job["id"] + "/cancel")
    wait(lambda: call(member, "GET", "/jobs/" + job["id"])["status"] == "CANCELLED", "training cancellation")
    call(admin, "DELETE", "/jobs/" + job["id"])
    call(member, "GET", "/jobs/" + job["id"], status=404)
    assert not Path("/runtime/logs/jobs", job["id"] + ".log").exists()
    assert results.joinpath("keep.txt").read_text() == "retained results"
    done("admin deletes terminal training history/logs; members can cancel; result files retained")

    call(admin, "DELETE", "/workspace?user_id=" + target["id"])
    assert not root.joinpath("keep.py").exists()
    assert not root.joinpath("datasets-link").exists()
    assert Path("/runtime/datasets/demo/hello.txt").exists()
    assert results.joinpath("keep.txt").exists()
    fresh = call(member, "POST", "/workspace/start")
    wait(lambda: member.get(fresh["route_path"]).status_code == 200, "workspace recreation")
    fresh_container = client.containers.get(fresh["container_id"])
    assert fresh_container.exec_run(["test", "!", "-e", "/opt/user-env/deletecheck-marker"]).exit_code == 0
    done("admin workspace deletion resets files/Python volume; results/shared data preserved and workspace recreates")

    tag = "lab-deletecheck:" + secrets.token_hex(8)
    recipe = ("FROM scratch\nLABEL lab.deletecheck=" + secrets.token_hex(16) + "\n").encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        info = tarfile.TarInfo("Dockerfile"); info.size = len(recipe)
        bundle.addfile(info, io.BytesIO(recipe))
    archive.seek(0)
    image, _ = client.images.build(fileobj=archive, custom_context=True, tag=tag, rm=True)
    blocker = client.containers.create(image.id, ["/unused"], labels={"lab.deletecheck": "true"})
    call(admin, "DELETE", "/admin/images/" + image.id, status=409)
    blocker.remove(); blocker = None
    template = call(admin, "POST", "/environments", {"name": "Disposable deletion check", "image": image.id,
                    "image_version": "test"}, 201)
    call(admin, "DELETE", "/admin/images/" + image.id, status=409)
    call(admin, "DELETE", "/environments/" + template["id"]); template = None
    call(member, "DELETE", "/admin/images/" + image.id, status=403)
    call(admin, "DELETE", "/admin/images/" + image.id)
    assert not any(i["id"] == image.id for i in call(admin, "GET", "/admin/images"))
    image = None
    done("admin-only Docker image deletion; container/template references protected; all confirmed tags removed")

    call(member, "PUT", "/settings/env", {"key": "DELETECHECK", "value": "temporary", "user_id": target["id"]})
    call(admin, "POST", "/users/" + target["id"] + "/disable")
    call(admin, "DELETE", "/users/" + target["id"])
    call(admin, "GET", "/users/" + target["id"], status=404)
    call(member, "GET", "/auth/me", status=401)
    assert not root.exists() and not results.exists()
    assert not client.volumes.list(filters={"name": "lab_pyenv_" + username})
    events = call(admin, "GET", "/admin/audit")
    assert any(e["action"] == "user.delete" and e["target_id"] == target["id"] for e in events)
    target = None
    done("admin account deletion removes private data/sessions/volume and retains audit trail")
    print(f"ADMIN DELETION ACCEPTANCE PASSED ({len(passed)} checks)", flush=True)
finally:
    # Only dispose resources created by this script, including on assertion failure.
    for kind, identifier in workloads:
        admin.post(f"/api/{kind}/{identifier}/" + ("stop" if kind == "debug" else "cancel"))
    if target:
        admin.post("/api/workspace/stop?user_id=" + target["id"])
        admin.post("/api/users/" + target["id"] + "/disable")
    if blocker:
        blocker.remove(force=True)
    if template:
        admin.delete("/api/environments/" + template["id"])
    if image:
        admin.delete("/api/admin/images/" + image.id)
    Path("/runtime/logs/acceptance-admin-deletion.json").write_text(json.dumps({"passed": passed, "success": target is None and len(passed) == 7}, indent=2))
    for session in (admin, member, anonymous):
        session.close()
