"""Verify host bind paths and bidirectional development with disposable members."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import time

import docker
import httpx

from sqlalchemy import select
from app.auth import token_hash
from app.db import SessionLocal
from app.models import AuthSession, User, now

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://traefik")
args = parser.parse_args()
admin = httpx.Client(base_url="http://traefik", timeout=45)
member = httpx.Client(base_url=args.url, headers={"Origin": args.url}, timeout=45, follow_redirects=True)
anonymous = httpx.Client(base_url=args.url, timeout=45, follow_redirects=True)
maintenance_token = secrets.token_urlsafe(32)
client = docker.from_env()
users = []
checks = []
success = False


def call(session, method, path, body=None, expected=200):
    r = session.request(method, "/api" + path, json=body)
    assert r.status_code == expected, (method, path, r.status_code, r.text[:500])
    return r.json()


def passed(name):
    checks.append(name)
    print("PASS " + name, flush=True)


try:
    # This local maintenance test already has backend DB and Docker access.
    # Use a short-lived session rather than replacing an admin's changed password.
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.role == "ADMIN", User.enabled.is_(True)))
        assert actor is not None
        db.add(AuthSession(token_hash=token_hash(maintenance_token), user_id=actor.id, expires_at=now() + timedelta(minutes=15)))
        db.commit()
    admin.cookies.set("lab_session", maintenance_token)
    envs = call(admin, "GET", "/environments")
    image = os.environ.get("LAB_TORCH_IMAGE", "lab-torch-dev:2.7.1-cu128")
    image_id = client.images.get(image).id
    template = next(e for e in envs if e["enabled"] and e["image"] == image_id)
    password = secrets.token_urlsafe(24)
    for _ in range(2):
        users.append(call(admin, "POST", "/users", {"username": "path_" + secrets.token_hex(4), "display_name": "Host path acceptance", "password": password, "max_gpus": 1, "default_environment_id": template["id"]}, 201))
    owner, other = users
    call(member, "POST", "/auth/login", {"username": owner["username"], "password": password})
    member_stopped = call(member, "GET", "/workspace")
    assert "host_paths" not in member_stopped
    stopped = call(admin, "GET", "/workspace?user_id=" + owner["id"])
    assert stopped["state"] == "STOPPED"
    host = stopped["host_paths"]["workspace"]
    assert host == os.environ["LAB_HOST_ROOT"] + "/users/" + owner["username"] + "/workspace"
    assert anonymous.get("/api/workspace").status_code == 401
    assert member.get("/api/workspace?user_id=" + other["id"]).status_code == 403
    assert call(admin, "GET", "/workspace?user_id=" + owner["id"])["host_paths"] == stopped["host_paths"]
    passed("own host paths before startup, admin lookup and cross-user/anonymous denial")

    call(member, "POST", "/workspace/start")
    workspace = call(admin, "GET", "/workspace?user_id=" + owner["id"])
    for _ in range(75):
        if member.get(workspace["route_path"]).status_code == 200:
            break
        time.sleep(1)
    assert member.get(workspace["route_path"]).status_code == 200
    assert anonymous.get(workspace["route_path"]).status_code == 401
    passed("portal and authenticated Web VS Code access through the chosen URL")
    container = client.containers.get(workspace["container_id"])
    actual = {m["Destination"]: m for m in container.attrs["Mounts"]}
    for kind, source in workspace["host_paths"].items():
        assert actual["/" + kind]["Source"] == source
    assert not actual["/datasets"]["RW"]
    passed("reported paths match real Docker bind mounts; shared datasets remain read-only")

    project = Path("/runtime/users", owner["username"], "workspace/project")
    project.mkdir()
    script = project / "host_import.py"
    script.write_text("from pathlib import Path\nPath('web_output.txt').write_text('WEB_TO_HOST_OK')\nprint('HOST_IMPORT_OK')\n")
    for path in (project, script):
        os.chown(path, workspace["host_uid"], workspace["host_gid"])
    for _ in range(75):
        result = container.exec_run(["/opt/user-env/venv/bin/python", "-c", "import torch; print(torch.__version__)"], user=str(workspace["host_uid"]))
        if result.exit_code == 0:
            break
        time.sleep(1)
    assert result.exit_code == 0, result.output.decode()[-400:]
    result = container.exec_run(["/opt/user-env/venv/bin/python", "/workspace/project/host_import.py"], workdir="/workspace/project", user=str(workspace["host_uid"]))
    assert result.exit_code == 0 and b"HOST_IMPORT_OK" in result.output, result.output
    assert (project / "web_output.txt").read_text() == "WEB_TO_HOST_OK"
    result = container.exec_run(["/opt/user-env/venv/bin/python", "-c", "from pathlib import Path; p=Path('/workspace/project/host_import.py'); p.write_text(p.read_text()+'# edited in workspace\\n')"], user=str(workspace["host_uid"]))
    assert result.exit_code == 0 and "edited in workspace" in script.read_text()
    passed("host import, editable ownership, persistent PyTorch interpreter and workspace-to-host writes")

    job = call(member, "POST", "/jobs", {"command": "python host_import.py", "workdir": "/workspace/project", "requested_gpus": 0, "requested_ram_mb": 1024, "time_limit_seconds": 120}, 201)
    for _ in range(120):
        state = call(member, "GET", "/jobs/" + job["id"])
        assert state["status"] not in {"FAILED", "TIMED_OUT", "CANCELLED"}, state
        if state["status"] == "COMPLETED":
            break
        time.sleep(1)
    assert state["status"] == "COMPLETED", state
    assert "HOST_IMPORT_OK" in call(member, "GET", "/jobs/" + job["id"] + "/logs")["log"]
    passed("training continues inside imported project folder with persistent Python environment")
    call(member, "POST", "/workspace/stop")
    assert script.exists()
    call(member, "POST", "/workspace/start")
    restarted = call(admin, "GET", "/workspace?user_id=" + owner["id"])
    assert restarted["host_paths"] == workspace["host_paths"]
    assert script.exists()
    passed("workspace stop/start retains project files and reports stable host paths")
    success = True
finally:
    for user in users:
        for job in call(admin, "GET", "/jobs"):
            if job["user_id"] == user["id"] and job["status"] in {"PENDING", "STARTING", "RUNNING"}:
                call(admin, "POST", "/jobs/" + job["id"] + "/cancel")
        call(admin, "POST", "/workspace/stop?user_id=" + user["id"])
        call(admin, "POST", "/users/" + user["id"] + "/disable")
        call(admin, "DELETE", "/users/" + user["id"])
    with SessionLocal() as db:
        session = db.get(AuthSession, token_hash(maintenance_token))
        if session:
            db.delete(session)
            db.commit()
    Path("/runtime/logs/acceptance-workspace-paths.json").write_text(json.dumps({"success": success, "url": args.url, "passed": checks}, indent=2))
print("WORKSPACE HOST PATH ACCEPTANCE PASSED (" + str(len(checks)) + " checks)", flush=True)
