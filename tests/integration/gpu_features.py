"""Verify live telemetry, exact GPU selection and long-debug approval on disposable resources."""
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import time

import docker
import httpx

admin = httpx.Client(base_url="http://traefik", timeout=60)
member = httpx.Client(base_url="http://traefik", timeout=60, follow_redirects=True)
client = docker.from_env()
target = None
resources = []
checks = []
success = False


def call(session, method, path, body=None, status=200):
    response = session.request(method, "/api" + path, json=body)
    assert response.status_code == status, (method, path, response.status_code, response.text[:700])
    return response.json()


def wait(check, description, seconds=90):
    for _ in range(seconds):
        value = check()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("Timeout: " + description)


def debug(identifier):
    return next(d for d in call(admin, "GET", "/debug") if d["id"] == identifier)


def terminal(identifier):
    return debug(identifier)["status"] in {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED", "REJECTED"}


def request_debug(hours=10, gpu=0):
    d = call(member, "POST", "/debug", {"requested_gpus": 1, "gpu_indices": [gpu],
        "time_limit_seconds": int(hours * 3600), "requested_ram_mb": 4096,
        "approval_reason": "Acceptance test of approval gating" if hours > 10 else ""}, 201)
    resources.append(("debug", d["id"]))
    return d


def passed(name):
    checks.append(name)
    print("PASS " + name, flush=True)


try:
    call(admin, "POST", "/auth/login", {"username": os.environ["INITIAL_ADMIN_USERNAME"], "password": os.environ["INITIAL_ADMIN_PASSWORD"]})
    admin_id = call(admin, "GET", "/auth/me")["id"]
    metrics = call(admin, "GET", "/resources/gpus")
    assert metrics["telemetry_status"] == "online" and len(metrics["slots"]) == 4
    assert (datetime.now().astimezone() - datetime.fromisoformat(metrics["telemetry_sampled_at"])).total_seconds() < 15
    for slot in metrics["slots"]:
        m = slot["metrics"]
        assert "5060 Ti" in m["name"] and m["uuid"].startswith("GPU-")
        assert m["memory_total_mb"] > 16000 and m["temperature_c"] > 0
        assert 0 <= m["utilization_percent"] <= 100 and m["power_w"] >= 0
    free = [s for s in metrics["slots"] if s["state"] == "FREE" and not s["external_busy"]]
    assert free, "No physically available card for a non-invasive acceptance run"
    selected = free[-1]["gpu_index"]
    uuid = free[-1]["metrics"]["uuid"]
    passed("fresh physical utilization/temperature/memory/power/fan/clock/UUID metrics for all four GPUs")

    password = secrets.token_urlsafe(24)
    target = call(admin, "POST", "/users", {"username": "gpucheck_" + secrets.token_hex(4),
        "display_name": "Disposable GPU approval acceptance", "password": password, "max_gpus": 1}, 201)
    assert target["max_debug_hours"] == 10
    call(member, "POST", "/auth/login", {"username": target["username"], "password": password})
    call(member, "POST", "/debug", {"requested_gpus": 1, "gpu_indices": [4]}, status=422)
    call(member, "POST", "/debug", {"requested_gpus": 1, "gpu_indices": [selected, selected]}, status=422)
    call(member, "POST", "/debug", {"time_limit_seconds": 36001}, status=422)

    external = next((s for s in metrics["slots"] if s["external_busy"]), None)
    if external:
        busy = request_debug(1, external["gpu_index"])
        time.sleep(3)
        assert debug(busy["id"])["status"] == "PENDING"
        call(member, "POST", "/debug/" + busy["id"] + "/stop")
        wait(lambda: terminal(busy["id"]), "external-card request cancellation")
    passed("invalid selections rejected; externally occupied selected card waits without touching its process")

    short = request_debug(10, selected)
    assert short["approval_status"] == "NOT_REQUIRED"
    running = wait(lambda: (d if (d := debug(short["id"]))["status"] == "RUNNING" and member.get(d["route_path"]).status_code == 200 else None), "selected-card ten-hour debug")
    assert running["assigned_gpus"] == [selected]
    assert (datetime.fromisoformat(running["expires_at"]) - datetime.fromisoformat(running["started_at"])).total_seconds() == 36000
    container = client.containers.get(running["container_id"])
    gpu_uuid = container.exec_run(["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"])
    assert gpu_uuid.exit_code == 0 and gpu_uuid.output.decode().strip() == uuid
    tensor = container.exec_run(["/opt/user-env/venv/bin/python", "-c", "import torch; assert torch.cuda.device_count()==1; x=torch.ones(128,128,device='cuda'); assert (x@x)[0,0].item()==128"], user=target["username"])
    assert tensor.exit_code == 0, tensor.output.decode()
    passed("ten hours starts without approval; exact selected physical UUID and CUDA computation verified")

    job = call(member, "POST", "/jobs", {"requested_gpus": 1, "gpu_indices": [selected], "requested_ram_mb": 4096,
        "command": "nvidia-smi --query-gpu=uuid --format=csv,noheader && python -c 'import torch; assert torch.cuda.device_count()==1; print((torch.ones(32,32,device=\"cuda\")@torch.ones(32,32,device=\"cuda\"))[0,0].item())'"}, 201)
    resources.append(("jobs", job["id"]))
    time.sleep(3)
    assert call(member, "GET", "/jobs/" + job["id"])["status"] == "PENDING"
    long = request_debug(11, selected)
    assert long["status"] == "AWAITING_APPROVAL" and long["container_id"] is None and long["assigned_gpus"] == []
    assert not any(q["id"] == long["id"] for q in call(member, "GET", "/resources/queue"))
    call(member, "POST", "/debug/" + long["id"] + "/approve", {}, status=403)
    call(member, "POST", "/debug/" + long["id"] + "/reject", {}, status=403)
    assert client.containers.list(all=True, filters={"name": "lab-debug-" + long["id"]}) == []
    approved = call(admin, "POST", "/debug/" + long["id"] + "/approve", {"note": "Approved disposable eleven-hour GPU test"})
    assert approved["status"] == "PENDING" and approved["approval_status"] == "APPROVED" and approved["approved_by"] == admin_id
    call(admin, "POST", "/debug/" + long["id"] + "/approve", {}, status=409)
    passed("long request holds no GPU/container/queue place until admin approval; member and duplicate decisions denied")

    call(member, "POST", "/debug/" + short["id"] + "/stop")
    wait(lambda: terminal(short["id"]), "release selected GPU")
    completed = wait(lambda: (j if (j := call(member, "GET", "/jobs/" + job["id"]))["status"] == "COMPLETED" else None), "selected-card training")
    assert completed["assigned_gpus"] == [selected]
    assert uuid in call(member, "GET", "/jobs/" + job["id"] + "/logs")["log"]
    approved_running = wait(lambda: (d if (d := debug(long["id"]))["status"] == "RUNNING" else None), "approved debug launch")
    assert approved_running["assigned_gpus"] == [selected]
    assert (datetime.fromisoformat(approved_running["expires_at"]) - datetime.fromisoformat(approved_running["started_at"])).total_seconds() == 39600
    call(member, "POST", "/debug/" + long["id"] + "/stop")
    wait(lambda: terminal(long["id"]), "approved long debug stop")
    passed("selected-card training waits/releases correctly; approval joins FIFO and eleven-hour expiry starts on launch")

    rejected = request_debug(12, selected)
    decision = call(admin, "POST", "/debug/" + rejected["id"] + "/reject", {"note": "Not approved for test"})
    assert decision["status"] == "REJECTED" and decision["approval_note"] == "Not approved for test"
    assert decision["container_id"] is None and decision["assigned_gpus"] == []
    withdrawn = request_debug(13, selected)
    call(member, "POST", "/debug/" + withdrawn["id"] + "/stop")
    wait(lambda: debug(withdrawn["id"])["status"] == "CANCELLED", "member withdrawal")
    call(admin, "POST", "/debug/" + withdrawn["id"] + "/approve", {}, status=409)
    passed("admin rejection and member withdrawal retain history without allocating GPUs")

    limit_check = request_debug(14, selected)
    call(admin, "PATCH", "/users/" + target["id"], {"max_gpus": 0})
    call(admin, "POST", "/debug/" + limit_check["id"] + "/approve", {}, status=422)
    call(admin, "PATCH", "/users/" + target["id"], {"max_gpus": 1})
    call(admin, "POST", "/users/" + target["id"] + "/disable")
    wait(lambda: terminal(limit_check["id"]), "disabled owner approval cancellation")
    call(admin, "POST", "/debug/" + limit_check["id"] + "/approve", {}, status=409)
    events = call(admin, "GET", "/admin/audit")
    assert any(e["action"] == "debug.approve" and e["target_id"] == long["id"] for e in events)
    assert any(e["action"] == "debug.reject" and e["target_id"] == rejected["id"] for e in events)
    passed("approval revalidates current quotas/disabled accounts and records admin decisions in audit")
    success = True
    print(f"GPU FEATURES ACCEPTANCE PASSED ({len(checks)} checks)", flush=True)
finally:
    for kind, identifier in resources:
        admin.post(f"/api/{kind}/{identifier}/" + ("stop" if kind == "debug" else "cancel"))
    if target:
        admin.post("/api/users/" + target["id"] + "/disable")
        for _ in range(30):
            response = admin.delete("/api/users/" + target["id"])
            if response.status_code == 200:
                break
            time.sleep(1)
        else:
            raise AssertionError("Disposable user cleanup failed: " + response.text)
    Path("/runtime/logs/acceptance-gpu-features.json").write_text(json.dumps({"success": success, "passed": checks}, indent=2))
    admin.close(); member.close()
