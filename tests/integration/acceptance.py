"""Real HTTP + PostgreSQL + Docker acceptance. Only touches accounts it creates."""

import argparse
import json
import os
from pathlib import Path
import secrets
import time
import sys
import httpx
import docker

parser = argparse.ArgumentParser()
parser.add_argument("--gpu", action="store_true")
args = parser.parse_args()
base = "http://traefik"
docker_client = docker.from_env()
report = []
created = []
workloads = []
admin = httpx.Client(base_url=base, timeout=60, follow_redirects=True)
password = secrets.token_urlsafe(20)


def call(client, method, path, body=None):
    response = client.request(method, "/api" + path, json=body)
    if response.status_code >= 400:
        raise AssertionError(
            f"{method} {path}: {response.status_code} {response.text[:800]}"
        )
    return response.json()


def passed(name):
    report.append(name)
    print(f"PASS {name}", flush=True)


def wait(condition, description, timeout=90):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = condition()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("Timeout: " + description)


def get_job(client, job_id):
    return call(client, "GET", f"/jobs/{job_id}")


def wait_state(client, job_id, expected):
    def poll():
        job = get_job(client, job_id)
        if job["status"] in {"FAILED", "TIMED_OUT"} and job["status"] != expected:
            logs = call(client, "GET", f"/jobs/{job_id}/logs")
            raise AssertionError(str(job) + str(logs))
        return job if job["status"] == expected else None

    return wait(poll, f"job {job_id} {expected}")


def submit(client, command, gpus=0, limit=120, env=None):
    job = call(
        client,
        "POST",
        "/jobs",
        {
            "command": command,
            "requested_gpus": gpus,
            "time_limit_seconds": limit,
            "requested_ram_mb": 512,
            "env": env or {},
            "output_name": "acceptance",
        },
    )
    workloads.append((client, "jobs", job["id"]))
    return job


def exec_ok(container, argv):
    result = container.exec_run(argv)
    if result.exit_code:
        raise AssertionError(result.output.decode(errors="replace"))
    return result.output.decode(errors="replace")


try:
    call(
        admin,
        "POST",
        "/auth/login",
        {
            "username": os.environ["INITIAL_ADMIN_USERNAME"],
            "password": os.environ["INITIAL_ADMIN_PASSWORD"],
        },
    )
    mode = call(admin, "GET", "/resources/gpus")["mode"]
    if args.gpu and mode != "local-gpu-docker":
        raise AssertionError(
            "Switch with ./scripts/lab.sh set-scheduler local-gpu-docker first"
        )
    if not args.gpu and mode != "mock-docker":
        raise AssertionError("Full acceptance needs mock-docker with five GPU slots")
    if call(admin, "GET", "/resources/queue"):
        raise AssertionError(
            "Finish/cancel existing workloads before running acceptance"
        )
    for prefix in ("test_a_", "test_b_"):
        name = prefix + secrets.token_hex(4)
        user = call(
            admin,
            "POST",
            "/users",
            {
                "username": name,
                "display_name": "Acceptance " + name,
                "password": password,
                "max_gpus": 1 if args.gpu else 5,
            },
        )
        created.append(user)
    clients = [
        httpx.Client(base_url=base, timeout=60, follow_redirects=True) for _ in created
    ]
    for client, user in zip(clients, created):
        call(
            client,
            "POST",
            "/auth/login",
            {"username": user["username"], "password": password},
        )
        assert docker_client.volumes.get("lab_pyenv_" + user["username"])
    a, b = clients
    ua, ub = created
    passed("admin/member login and user provisioning")
    if args.gpu:
        # A CUDA allocation proves computation API access without downloading PyTorch.
        root = Path("/runtime/users", ua["username"], "workspace")
        root.mkdir(parents=True, exist_ok=True)
        root.joinpath("gpu_check.py").write_text(
            'import ctypes\nc=ctypes.CDLL("libcudart.so.12")\nn=ctypes.c_int()\nassert c.cudaGetDeviceCount(ctypes.byref(n))==0 and n.value==1\np=ctypes.c_void_p()\nassert c.cudaMalloc(ctypes.byref(p),1048576)==0\nassert c.cudaFree(p)==0\nprint("REAL_GPU_OK")\n'
        )
        gpu = submit(
            a,
            "nvidia-smi --query-gpu=name --format=csv,noheader && python /workspace/gpu_check.py",
            1,
        )
        wait_state(a, gpu["id"], "COMPLETED")
        assert "REAL_GPU_OK" in call(a, "GET", f"/jobs/{gpu['id']}/logs")["log"]
        passed("real GPU DeviceRequest, nvidia-smi and CUDA allocation")
    else:
        workspace = call(a, "POST", "/workspace/start")
        ca = docker_client.containers.get(workspace["container_id"])
        # The Python symlink appears before uv finishes seeding pip. The editor
        # starts only after the entrypoint finishes environment initialization.
        route = workspace["route_path"]
        wait(lambda: a.get(route).status_code == 200, "code-server and venv initialization")
        exec_ok(ca, ["/opt/user-env/venv/bin/pip", "install", "rich==13.9.4"])
        exec_ok(ca, ["bash", "-c", "echo WORKSPACE_OK > /workspace/persist.txt"])
        assert httpx.get(base + route).status_code == 401
        assert b.get(route).status_code == 403
        assert admin.get(route).status_code == 200
        assert b.get("/api/users").status_code == 403
        passed("code-server route and ForwardAuth owner/admin isolation")
        assert not ca.attrs["HostConfig"].get("DeviceRequests")
        assert not ca.attrs["HostConfig"]["Privileged"]
        assert not ca.attrs["HostConfig"]["PortBindings"]
        assert not any(
            m["Destination"] == "/var/run/docker.sock" for m in ca.attrs["Mounts"]
        )
        assert (
            next(m for m in ca.attrs["Mounts"] if m["Destination"] == "/datasets")["RW"]
            is False
        )
        exec_ok(ca, ["ls", "/datasets"])
        assert ca.exec_run(["touch", "/datasets/should-fail.txt"]).exit_code != 0
        passed("CPU workspace, read-only real dataset and Docker boundaries")
        old_id = ca.id
        call(a, "POST", "/workspace/stop")
        workspace = call(a, "POST", "/workspace/start")
        assert workspace["container_id"] != old_id
        ca = docker_client.containers.get(workspace["container_id"])
        wait(
            lambda: ca.exec_run(
                ["/opt/user-env/venv/bin/python", "-c", "import rich"]
            ).exit_code
            == 0,
            "persistent rich",
        )
        assert "WORKSPACE_OK" in exec_ok(ca, ["cat", "/workspace/persist.txt"])
        wb = call(b, "POST", "/workspace/start")
        cb = docker_client.containers.get(wb["container_id"])
        wait(
            lambda: cb.exec_run(
                ["test", "-f", "/opt/user-env/venv/bin/python"]
            ).exit_code
            == 0,
            "second venv",
        )
        assert (
            cb.exec_run(
                ["/opt/user-env/venv/bin/python", "-c", "import rich"]
            ).exit_code
            != 0
        )
        passed("files and pip package survive replacement; separate user venvs")
        call(
            admin,
            "PUT",
            "/settings/env",
            {"key": "POC_PRECEDENCE", "value": "global", "is_secret": False},
        )
        call(
            a,
            "PUT",
            "/settings/env",
            {"user_id": ua["id"], "key": "POC_PRECEDENCE", "value": "user"},
        )
        call(
            a,
            "PUT",
            "/settings/env",
            {
                "user_id": ua["id"],
                "key": "POC_SECRET",
                "value": "secret-value",
                "is_secret": True,
            },
        )
        settings_response = call(a, "GET", "/settings/env")
        assert (
            next(v for v in settings_response if v["key"] == "POC_SECRET")["value"]
            == "********"
        )
        job = submit(
            a,
            "python -c \"import rich,os,pathlib; assert os.environ['POC_PRECEDENCE']=='job'; p=pathlib.Path(os.environ['LAB_RESULT_DIR']); (p/'result.txt').write_text('RESULT_OK'); print('TRAIN_OK')\"",
            env={"POC_PRECEDENCE": "job"},
        )
        wait_state(a, job["id"], "COMPLETED")
        assert "TRAIN_OK" in call(a, "GET", f"/jobs/{job['id']}/logs")["log"]
        assert (
            Path(
                "/runtime/results",
                ua["username"],
                "acceptance",
                job["id"],
                "result.txt",
            ).read_text()
            == "RESULT_OK"
        )
        assert b.get(f"/api/jobs/{job['id']}/logs").status_code == 403
        assert (
            a.post(
                "/api/jobs", json={"command": "true", "workdir": "/workspace/../etc"}
            ).status_code
            == 422
        )
        assert (
            a.post(
                "/api/jobs", json={"command": "true", "requested_gpus": 6}
            ).status_code
            == 422
        )
        passed(
            "training uses persistent venv; durable logs/results; env precedence/secrets"
        )
        retry = call(a, "POST", f"/jobs/{job['id']}/retry")
        workloads.append((a, "jobs", retry["id"]))
        wait_state(a, retry["id"], "COMPLETED")
        passed("job retry creates independent persisted result")
        j1 = submit(
            a,
            "python -c 'import time; print(\"A_RUNNING\", flush=True); time.sleep(120)'",
            2,
            180,
        )
        j2 = submit(b, "python -c 'import time; time.sleep(120)'", 2, 180)
        r1, r2 = wait_state(a, j1["id"], "RUNNING"), wait_state(b, j2["id"], "RUNNING")
        assert r1["assigned_gpus"] == [0, 1] and r2["assigned_gpus"] == [2, 3]
        debug = call(
            a, "POST", "/debug", {"requested_gpus": 1, "time_limit_seconds": 120}
        )
        workloads.append((a, "debug", debug["id"]))

        def running_debug():
            current = next(
                d for d in call(a, "GET", "/debug") if d["id"] == debug["id"]
            )
            return current if current["status"] == "RUNNING" else None

        debug = wait(running_debug, "debug RUNNING")
        assert debug["assigned_gpus"] == [4]
        dc = docker_client.containers.get(debug["container_id"])
        wait(
            lambda: dc.exec_run(
                ["/opt/user-env/venv/bin/python", "-c", "import rich"]
            ).exit_code
            == 0,
            "debug rich",
        )
        wait(lambda: a.get(debug["route_path"]).status_code == 200, "debug ForwardAuth")
        assert b.get(debug["route_path"]).status_code == 403
        assert dc.exec_run(["touch", "/datasets/should-fail.txt"]).exit_code != 0
        pending = submit(b, "python -c 'print(\"QUEUE_OK\")'", 1)
        time.sleep(3)
        assert get_job(b, pending["id"])["status"] == "PENDING"
        passed(
            "5-GPU first-fit: 2+2+1, shared debug/train FIFO and persistent debug venv"
        )
        # Restart backend and worker without touching running dynamic containers.
        for service in ("backend", "scheduler-worker"):
            containers = docker_client.containers.list(
                filters={
                    "label": [
                        "com.docker.compose.project=gpu-lab-poc",
                        "com.docker.compose.service=" + service,
                    ]
                }
            )
            container = next(
                c
                for c in containers
                if c.labels.get("com.docker.compose.oneoff", "False").lower() == "false"
            )
            container.restart(timeout=5)
        wait(lambda: admin.get("/api/health").status_code == 200, "backend restart")
        time.sleep(3)
        assert get_job(a, j1["id"])["container_id"] == r1["container_id"]
        assert get_job(b, j2["id"])["container_id"] == r2["container_id"]
        for current in (r1, r2):
            assert (
                len(
                    docker_client.containers.list(
                        all=True, filters={"label": "lab.job_id=" + current["id"]}
                    )
                )
                == 1
            )
        assert get_job(b, pending["id"])["status"] == "PENDING"
        passed(
            "backend/worker restart recovers sessions, running/pending state without duplicates"
        )
        call(a, "POST", f"/debug/{debug['id']}/stop")
        wait_state(b, pending["id"], "COMPLETED")
        assert "QUEUE_OK" in call(b, "GET", f"/jobs/{pending['id']}/logs")["log"]
        passed("debug stop releases GPU and queued training starts automatically")
        for client, job in ((a, j1), (b, j2)):
            call(client, "POST", f"/jobs/{job['id']}/cancel")
            wait_state(client, job["id"], "CANCELLED")
        ttl = call(a, "POST", "/debug", {"requested_gpus": 1, "time_limit_seconds": 5})
        workloads.append((a, "debug", ttl["id"]))
        wait(
            lambda: next(d for d in call(a, "GET", "/debug") if d["id"] == ttl["id"])[
                "status"
            ]
            == "TIMED_OUT",
            "debug TTL",
        )
        timed = submit(a, "sleep 60", 1, 5)
        wait_state(a, timed["id"], "TIMED_OUT")
        failed = submit(a, "echo EXPECTED_FAILURE; exit 7")
        failure = wait_state(a, failed["id"], "FAILED")
        assert failure["exit_code"] == 7
        passed("job cancellation/failure/time limits and debug TTL release allocations")
        wait(
            lambda: all(
                s["state"] == "FREE" for s in call(a, "GET", "/resources/gpus")["slots"]
            ),
            "all GPUs free",
        )
        assert "A_RUNNING" in call(a, "GET", f"/jobs/{j1['id']}/logs")["log"]
        assert call(admin, "GET", "/admin/storage") and call(
            admin, "GET", "/admin/audit"
        )
        passed("final GPU release, saved logs, storage and audit")
    print(f"ACCEPTANCE PASSED ({len(report)} checks)", flush=True)
finally:
    for client, kind, identifier in workloads:
        try:
            call(
                admin,
                "POST",
                f"/{kind}/{identifier}/" + ("stop" if kind == "debug" else "cancel"),
            )
        except Exception:
            pass
    for user in created:
        try:
            call(admin, "POST", f"/workspace/stop?user_id={user['id']}")
            call(admin, "POST", f"/users/{user['id']}/disable")
        except Exception:
            pass
    path = Path(
        "/runtime/logs/acceptance-gpu.json"
        if args.gpu
        else "/runtime/logs/acceptance.json"
    )
    path.write_text(
        json.dumps(
            {
                "success": sys.exc_info()[0] is None,
                "passed": report,
                "test_users": [u["username"] for u in created],
            },
            indent=2,
        )
    )
