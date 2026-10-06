"""Read-only public native-host acceptance using temporary existing-user sessions."""
import argparse
import base64
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import struct
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from app.auth import token_hash
from app.db import SessionLocal
from app.models import AuthSession, User, now


def websocket(url, cookie, expected):
    target = urlsplit(url)
    path = "/host/?reconnectionToken=" + secrets.token_hex(16) + "&reconnection=false&skipWebSocketFrames=false"
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    headers = [f"GET {path} HTTP/1.1", f"Host: {target.hostname}", "Upgrade: websocket", "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13", f"Origin: {url}"]
    if cookie:
        headers.append("Cookie: lab_session=" + cookie)
    connection = ssl.create_default_context().wrap_socket(socket.create_connection((target.hostname, 443), timeout=25), server_hostname=target.hostname)
    with connection:
        connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
        stream = connection.makefile("rb")
        status = int(stream.readline().decode().split()[1])
        response_headers = {}
        while True:
            line = stream.readline()
            if line == b"\r\n":
                break
            assert line, "Incomplete WebSocket headers"
            name, value = line.decode().split(":", 1)
            response_headers[name.lower()] = value.strip()
        assert status == expected, (status, expected)
        if status != 101:
            return
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        assert response_headers.get("sec-websocket-accept") == accept
        payload, mask = b"HOST_WS_OK", secrets.token_bytes(4)
        connection.sendall(bytes([0x89, 0x80 | len(payload)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        for _ in range(12):
            frame = stream.read(2)
            assert len(frame) == 2, "WebSocket closed before pong"
            opcode, length = frame[0] & 15, frame[1] & 127
            if length == 126:
                length = struct.unpack("!H", stream.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", stream.read(8))[0]
            assert length < 1048576
            data = stream.read(length)
            if opcode == 10:
                assert data == payload
                return
            assert opcode != 8, "WebSocket closed before pong"
        raise AssertionError("No WebSocket pong")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    url = parser.parse_args().url.rstrip("/")
    target = urlsplit(url)
    assert target.scheme == "https" and (target.hostname or "").endswith(".trycloudflare.com") and target.port in (None, 443) and not (target.path or target.query or target.username)
    tokens = {role: secrets.token_urlsafe(32) for role in ("ADMIN", "MEMBER")}
    checks, clients, success = [], [], False
    probe = Path("/runtime/host-editor/acceptance-" + secrets.token_hex(8) + ".txt")

    def passed(name):
        checks.append(name)
        print("PASS " + name, flush=True)

    def client(base, token=None):
        c = httpx.Client(base_url=base, headers={"Origin": base}, timeout=40, follow_redirects=True)
        if token:
            c.cookies.set("lab_session", token)
        clients.append(c)
        return c

    try:
        with SessionLocal() as db:
            for role, token in tokens.items():
                actor = db.scalar(select(User).where(User.role == role, User.enabled.is_(True)).order_by(User.username))
                assert actor is not None
                db.add(AuthSession(token_hash=token_hash(token), user_id=actor.id, expires_at=now() + timedelta(minutes=10)))
            db.commit()
        admin, member, guest = client(url, tokens["ADMIN"]), client(url, tokens["MEMBER"]), client(url)
        assert guest.get("/api/health").status_code == 200
        remote = admin.get("/api/system/remote-access").json()
        assert remote["status"] == "online" and remote["url"] == url
        host_response = admin.get("/api/workspace")
        assert host_response.status_code == 200
        host = host_response.json()
        assert host["mode"] == "host" and host["state"] == "RUNNING" and host["container_id"] is None
        assert host["host_user"] == "local" and host["host_uid"] == 1000 and host["host_home"] == "/home/local"
        assert host["host_python"] == "/home/local/miniconda3/envs/dl/bin/python"
        student = member.get("/api/workspace").json()
        assert student["mode"] == "container" and "host_paths" in student and "host_home" not in student
        assert guest.get("/api/workspace").status_code == 401
        passed("unchanged public tunnel; admin native metadata and member container contract")
        assert admin.get("/api/auth/host-editor").status_code == 204
        assert member.get("/api/auth/host-editor").status_code == 403
        assert guest.get("/api/auth/host-editor").status_code == 401
        editor = admin.get("/host/")
        assert editor.status_code == 200 and "vscode-workbench-web-configuration" in editor.text
        assert admin.get("/host/?folder=%2Fhome%2Flocal%2Fgpu-cluster-system").status_code == 200
        assert member.get("/host/").status_code == 403
        assert guest.get("/host/").status_code == 401
        assert admin.get("/host/", headers={"Origin": "https://attacker.invalid"}).status_code == 403
        passed("public native VS Code HTML and project folder; admin-only HTTP and origin guard")
        probe.write_text("NATIVE_HOST_FILES_OK\n")
        probe.chmod(0o644)
        host_path = os.environ["LAB_HOST_ROOT"] + "/host-editor/" + probe.name
        resource = "/host/vscode-remote-resource"
        response = admin.get(resource, params={"path": host_path})
        assert response.status_code == 200 and response.text == probe.read_text()
        assert member.get(resource, params={"path": host_path}).status_code == 403
        assert guest.get(resource, params={"path": host_path}).status_code == 401
        os_release = admin.get(resource, params={"path": "/etc/os-release"})
        assert os_release.status_code == 200 and 'VERSION_ID="24.04"' in os_release.text
        passed("native host absolute file access and Ubuntu 24.04 identity; student/guest file denial")
        websocket(url, tokens["ADMIN"], 101)
        websocket(url, tokens["MEMBER"], 403)
        websocket(url, None, 401)
        passed("native editor WSS upgrade and ping/pong through Cloudflare; member/guest denied")
        for token, status in [(None, 401), (tokens["MEMBER"], 403)]:
            direct = client("http://host-editor-proxy:8080", token)
            assert direct.get("/").status_code == status
            assert direct.get("/", headers={"X-Forwarded-Host": "example.invalid", "Origin": "http://example.invalid"}).status_code == status
        direct_admin = client("http://host-editor-proxy:8080", tokens["ADMIN"])
        assert direct_admin.get("/", headers={"Origin": "https://attacker.invalid"}).status_code == 403
        passed("direct internal proxy rejects anonymous, member and forged forwarding headers")
        for action in ("stop", "restart"):
            assert admin.post("/api/workspace/" + action).status_code == 422
        assert admin.delete("/api/workspace").status_code == 422
        assert admin.get("/api/workspace").json()["state"] == "RUNNING"
        passed("student workspace stop/restart/delete cannot control the host service or files")
        success = True
    finally:
        probe.unlink(missing_ok=True)
        for c in clients:
            c.close()
        with SessionLocal() as db:
            for token in tokens.values():
                session = db.get(AuthSession, token_hash(token))
                if session:
                    db.delete(session)
            db.commit()
        Path("/runtime/logs/acceptance-host-editor.json").write_text(json.dumps({"success": success, "url": url, "passed": checks}, indent=2))
    print("HOST EDITOR ACCEPTANCE PASSED (" + str(len(checks)) + " checks)", flush=True)


if __name__ == "__main__":
    main()
