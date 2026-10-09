"""Exercise the current public Quick Tunnel with disposable MEMBER accounts."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time
from urllib.parse import urlsplit

import httpx
import docker

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
args = parser.parse_args()
url = args.url.rstrip("/")
target = urlsplit(url)
if (
    target.scheme != "https"
    or not (target.hostname or "").endswith(".trycloudflare.com")
    or target.port not in (None, 443)
    or target.path
    or target.query
    or target.username
):
    raise SystemExit("Only the current HTTPS trycloudflare.com URL is accepted")

admin = httpx.Client(base_url="http://traefik", timeout=30)
member = httpx.Client(base_url=url, headers={"Origin": url}, timeout=30, follow_redirects=True)
other_session = httpx.Client(base_url=url, headers={"Origin": url}, timeout=30, follow_redirects=True)
anonymous = httpx.Client(base_url=url, timeout=30, follow_redirects=True)
users = []
report = []
cleanup_errors = []
job_id = None
success = False
password = secrets.token_urlsafe(24)
new_password = secrets.token_urlsafe(24)


def call(client, method, path, body=None):
    response = client.request(method, "/api" + path, json=body)
    if response.status_code >= 400:
        raise AssertionError(f"{method} {path}: HTTP {response.status_code} {response.text[:300]}")
    return response.json()


def passed(name):
    report.append(name)
    print("PASS " + name, flush=True)


def wait(check, description, timeout=75):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(2)
    raise AssertionError("Timeout: " + description)


def websocket(path, cookie=None, expected=101):
    """Verify a real WSS upgrade and RFC 6455 ping/pong through Cloudflare."""
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    headers = [
        f"GET {path} HTTP/1.1",
        f"Host: {target.hostname}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        f"Origin: {url}",
    ]
    if cookie:
        headers.append("Cookie: lab_session=" + cookie)
    connection = ssl.create_default_context().wrap_socket(
        socket.create_connection((target.hostname, 443), timeout=20),
        server_hostname=target.hostname,
    )
    with connection:
        connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
        stream = connection.makefile("rb")
        status = int(stream.readline().decode().split()[1])
        response_headers = {}
        while True:
            line = stream.readline()
            if line == b"\r\n":
                break
            if not line:
                raise AssertionError("Incomplete WebSocket headers")
            name, value = line.decode().split(":", 1)
            response_headers[name.lower()] = value.strip()
        assert status == expected, f"WSS returned {status}, expected {expected}"
        if expected != 101:
            return
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        assert response_headers.get("sec-websocket-accept") == accept
        payload = b"REMOTE_WS_OK"
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        connection.sendall(bytes([0x89, 0x80 | len(payload)]) + mask + masked)
        for _ in range(12):
            frame = stream.read(2)
            assert len(frame) == 2, "WebSocket closed before pong"
            opcode = frame[0] & 0x0F
            length = frame[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", stream.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", stream.read(8))[0]
            assert length < 1048576, "Unexpectedly large WebSocket frame"
            data = stream.read(length)
            if opcode == 10:
                assert data == payload
                return
            assert opcode != 8, "WebSocket closed before pong"
        raise AssertionError("No WebSocket pong received")


try:
    call(admin, "POST", "/auth/login", {
        "username": os.environ["INITIAL_ADMIN_USERNAME"],
        "password": os.environ["INITIAL_ADMIN_PASSWORD"],
    })
    remote = call(admin, "GET", "/system/remote-access")
    assert remote["status"] == "online" and remote["url"] == url
    assert anonymous.get("/").status_code == 200
    assert call(anonymous, "GET", "/health")["status"] == "ok"
    passed("current tunnel readiness and public HTTPS portal")
    # Use an available template without changing the administrator's environment.
    local_images = {image.id for image in docker.from_env().images.list()}
    templates = call(admin, "GET", "/environments")
    template = next(e for e in reversed(templates) if e["enabled"] and e["image"] in local_images)
    for _ in range(2):
        name = "remote_" + secrets.token_hex(4)
        users.append(call(admin, "POST", "/users", {
            "username": name, "display_name": "Remote acceptance " + name,
            "password": password, "role": "MEMBER", "max_gpus": 1,
            "default_environment_id": template["id"],
        }))
    ua, ub = users
    response = member.post("/api/auth/login", json={"username": ua["username"], "password": password})
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"].lower()
    assert "secure" in cookie_header and "httponly" in cookie_header and "samesite=lax" in cookie_header
    call(other_session, "POST", "/auth/login", {"username": ua["username"], "password": password})
    assert call(member, "GET", "/auth/me")["role"] == "MEMBER"
    assert member.get("/api/users").status_code == 403
    assert anonymous.get("/api/workspace").status_code == 401
    assert member.post("/api/workspace/start", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    passed("HTTPS member login, secure cookie, role permissions and CSRF rejection")
    workspace = call(member, "POST", "/workspace/start")
    route = workspace["route_path"]
    wait(lambda: member.get(route).status_code == 200, "public VS Code startup")
    assert anonymous.get(route).status_code == 401
    outsider = httpx.Client(base_url=url, headers={"Origin": url}, timeout=30)
    call(outsider, "POST", "/auth/login", {"username": ub["username"], "password": password})
    assert outsider.get(route).status_code == 403
    passed("public workspace HTTP, anonymous denial and cross-user isolation")
    ws_path = route + "?reconnectionToken=" + secrets.token_hex(16) + "&reconnection=false&skipWebSocketFrames=false"
    websocket(ws_path, member.cookies.get("lab_session"))
    websocket(ws_path, expected=401)
    passed("authenticated WSS upgrade and ping/pong through Cloudflare; anonymous WSS denied")
    assert member.post("/api/auth/change-password", json={"current_password": "wrong-current", "new_password": new_password}).status_code == 400
    assert member.post("/api/auth/change-password", json={"current_password": password, "new_password": "short"}).status_code == 422
    assert member.post("/api/auth/change-password", json={"current_password": password, "new_password": password}).status_code == 422
    assert call(member, "GET", "/auth/me")["id"] == ua["id"]
    call(member, "POST", "/auth/change-password", {"current_password": password, "new_password": new_password})
    assert member.get("/api/auth/me").status_code == 401
    assert other_session.get("/api/auth/me").status_code == 401
    assert other_session.get(route).status_code == 401
    assert member.post("/api/auth/login", json={"username": ua["username"], "password": password}).status_code == 401
    # Another device's keyboard may capitalise, widen or pad what the member typed.
    wide = str.maketrans({chr(code): chr(code + 0xFEE0) for code in range(0x21, 0x7F)})
    call(other_session, "POST", "/auth/login", {"username": " " + ua["username"].upper(), "password": new_password.translate(wide) + "​ "})
    assert member.post("/api/auth/login", json={"username": ua["username"], "password": new_password.swapcase()}).status_code == 401
    call(member, "POST", "/auth/login", {"username": ua["username"], "password": new_password})
    assert member.get(route).status_code == 200
    passed("password validation, change, all previous sessions revoked and new login")
    job = call(member, "POST", "/jobs", {
        "command": 'python -c "import os,pathlib; p=pathlib.Path(os.environ[\'LAB_RESULT_DIR\']); (p/\'remote.txt\').write_text(\'REMOTE_TRAIN_OK\'); print(\'REMOTE_TRAIN_OK\')"',
        "requested_gpus": 1, "requested_ram_mb": 512, "time_limit_seconds": 60,
        "output_name": "remote_acceptance",
    })
    job_id = job["id"]
    def finished():
        state = call(member, "GET", f"/jobs/{job_id}")
        assert state["status"] not in {"FAILED", "TIMED_OUT"}, str(state)
        return state["status"] == "COMPLETED"
    wait(finished, "remote GPU-required training")
    assert "REMOTE_TRAIN_OK" in call(member, "GET", f"/jobs/{job_id}/logs")["log"]
    result = Path("/runtime/results", ua["username"], "remote_acceptance", job_id, "remote.txt")
    assert result.read_text() == "REMOTE_TRAIN_OK"
    passed("public training submission, completion, logs and persistent results")
    audit = call(admin, "GET", "/admin/audit")
    assert any(e["action"] == "user.change_password" and e["target_id"] == ua["id"] for e in audit)
    assert "password" not in call(admin, "GET", f"/users/{ua['id']}")
    failures = [e["metadata"] for e in audit if e["action"] == "login.failed" and e["target_id"] == ua["id"]]
    assert failures and all(f["reason"] == "bad_password" and f["client"] for f in failures)
    assert not any(secret in json.dumps(audit) for secret in (password, new_password))
    assert any(e["action"] == "login" and e["target_id"] == ua["id"] and e["metadata"]["password_normalized"] for e in audit)
    passed("password-change and failed-login audit; credentials excluded from responses")
    success = True
finally:
    if job_id:
        try:
            call(admin, "POST", f"/jobs/{job_id}/cancel")
        except Exception as error:
            cleanup_errors.append(str(error))
    for user in users:
        try:
            call(admin, "POST", f"/users/{user['id']}/disable")
        except Exception as error:
            cleanup_errors.append(str(error))
    path = Path("/runtime/logs/acceptance-remote.json")
    path.write_text(json.dumps({
        "success": success and not cleanup_errors,
        "url": url,
        "passed": report,
        "test_users": [user["username"] for user in users],
        "cleanup_errors": cleanup_errors,
    }, indent=2))
    if cleanup_errors:
        print("Cleanup failures: " + str(cleanup_errors), file=sys.stderr)
if cleanup_errors:
    raise SystemExit(1)
print(f"REMOTE ACCEPTANCE PASSED ({len(report)} checks)", flush=True)
