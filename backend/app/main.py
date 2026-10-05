from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
import re
import secrets
import threading
import time
import unicodedata
from urllib.parse import unquote, urlsplit
from urllib.error import URLError
from urllib.request import urlopen
from docker.errors import DockerException
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from .auth import admin_user, current_user, hasher, token_hash, verify_password
from .config import settings
from .db import get_db
from .docker_runtime import runtime
from .models import (
    AuditEvent,
    AuthSession,
    Environment,
    EnvVar,
    User,
    Workload,
    Workspace,
    now,
)
from .schemas import (
    DebugSpec,
    EnvironmentCreate,
    EnvironmentPatch,
    EnvSetting,
    JobSpec,
    Login,
    PasswordChange,
    PasswordReset,
    UserCreate,
    UserPatch,
    clean_credential,
)
from .scheduler import get_scheduler
from .scheduler.base import ACTIVE, TERMINAL
from .storage import storage

app = FastAPI(
    title="GPU Lab Portal",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
scheduler = get_scheduler()
attempts: dict[str, deque] = defaultdict(deque)
attempt_lock = threading.Lock()
dummy_hash = hasher.hash("invalid-account-dummy-password")
remote_urls: dict[tuple[str, str], str] = {}


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if (
            origin and urlsplit(origin).netloc != request.headers.get("host")
        ) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DockerException)
def docker_error(request, exc):
    return JSONResponse(
        {"detail": f"Docker 操作失败: {str(exc)[:800]}"}, status_code=503
    )


def audit(
    db: Session,
    user: User | None,
    action: str,
    target: str,
    identifier: str,
    metadata: dict | None = None,
):
    db.add(
        AuditEvent(
            user_id=user.id if user else None,
            action=action,
            target_type=target,
            target_id=identifier,
            metadata_json=metadata or {},
        )
    )


def public_user(user: User) -> dict:
    return {
        key: getattr(user, key)
        for key in (
            "id",
            "username",
            "display_name",
            "role",
            "enabled",
            "default_environment_id",
            "max_gpus",
            "max_debug_hours",
            "created_at",
        )
    }


def public_environment(env: Environment) -> dict:
    return {
        key: getattr(env, key)
        for key in ("id", "name", "image", "image_version", "description", "enabled")
    }


def public_workload(resource: Workload, db: Session) -> dict:
    result = {
        key: getattr(resource, key)
        for key in (
            "id",
            "kind",
            "user_id",
            "status",
            "requested_gpus",
            "requested_cpus",
            "requested_ram_mb",
            "time_limit_seconds",
            "environment_id",
            "command",
            "workdir",
            "output_name",
            "route_path",
            "created_at",
            "started_at",
            "expires_at",
            "finished_at",
            "exit_code",
            "container_id",
            "error_message",
            "cancel_requested",
        )
    }
    result.update(
        assigned_gpus=resource.assigned_gpus_json,
        env_keys=list(resource.env_json),
        username=db.get(User, resource.user_id).username,
    )
    return result


def target_user(db: Session, user: User, user_id: str | None) -> User:
    if not user_id or user_id == user.id:
        return user
    if user.role != "ADMIN":
        raise HTTPException(403, "不能操作其他用户")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    return target


def accessible_resource(
    db: Session, user: User, resource_id: str, kind: str | None = None
) -> Workload:
    resource = scheduler.get_status(db, resource_id)
    if not resource or (kind and resource.kind != kind):
        raise HTTPException(404, "任务不存在")
    if user.role != "ADMIN" and resource.user_id != user.id:
        raise HTTPException(403, "无权访问此任务")
    return resource


def allowed_environment(db: Session, user: User, env_id: str | None) -> Environment:
    env = db.get(Environment, env_id or user.default_environment_id)
    if not env or not env.enabled:
        raise HTTPException(422, "环境不存在或已停用")
    # The Python ABI of one persistent venv must stay bound to the user's pinned template.
    if user.role != "ADMIN" and env.id != user.default_environment_id:
        raise HTTPException(403, "请使用管理员为你固定的环境")
    return env


def validate_resources(user: User, spec):
    if spec.requested_gpus > min(user.max_gpus, settings.gpu_count):
        raise HTTPException(422, "GPU 数量超过用户或集群上限")
    if (
        isinstance(spec, DebugSpec)
        and spec.time_limit_seconds > user.max_debug_hours * 3600
    ):
        raise HTTPException(422, "Debug 时间超过用户上限")


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def client_address(request: Request) -> str:
    # Behind the tunnel every visitor shares the cloudflared container as peer;
    # Cloudflare's own header names the device. The local port is 127.0.0.1 only.
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def password_notes(password: str) -> list[str]:
    notes = []
    if password != password.strip():
        notes.append("首尾有空白")
    if any(unicodedata.category(c) == "Cf" for c in password):
        notes.append("含不可见字符")
    if not password.isascii():
        notes.append("含非 ASCII 字符")
    return notes


@app.post("/api/auth/login")
def login(
    spec: Login, request: Request, response: Response, db: Session = Depends(get_db)
):
    address = client_address(request)
    with attempt_lock:
        cutoff = time.monotonic() - 60
        for key in [k for k, h in attempts.items() if not h or h[-1] < cutoff]:
            del attempts[key]
        history = attempts[address]
        while history and history[0] < cutoff:
            history.popleft()
        if len(history) >= 20:
            raise HTTPException(429, "登录过于频繁，请一分钟后重试")
        history.append(time.monotonic())
    user = db.scalar(select(User).where(User.username == spec.username))
    stored = user.password_hash if user else dummy_hash
    valid = verify_password(spec.password, stored)
    cleaned = clean_credential(spec.password)
    # The exact password always wins; otherwise retry without what a keyboard
    # or paste on another device may have added invisibly.
    normalized = (
        not valid and cleaned != spec.password and verify_password(cleaned, stored)
    )
    source = {
        "client": address,
        "user_agent": request.headers.get("user-agent", "")[:200],
    }
    if not user or not user.enabled or not (valid or normalized):
        # The browser shows one message for every cause. Record which cause it
        # was and the shape of the input, never the password itself.
        audit(
            db,
            user,
            "login.failed",
            "user",
            user.id if user else spec.username,
            {
                "reason": "unknown_user"
                if not user
                else "disabled"
                if not user.enabled
                else "bad_password",
                "username": spec.username,
                "password_length": len(spec.password),
                "password_notes": password_notes(spec.password),
                **source,
            },
        )
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=now() + timedelta(days=7),
        )
    )
    audit(
        db,
        user,
        "login",
        "user",
        user.id,
        {**source, "password_normalized": normalized},
    )
    db.commit()
    secure = (
        settings.secure_cookie
        or request.headers.get("x-forwarded-proto") == "https"
        # Quick Tunnel terminates TLS before the local Traefik HTTP entrypoint.
        # The browser's same-origin POST still reports its original HTTPS origin.
        or urlsplit(request.headers.get("origin", "")).scheme == "https"
    )
    response.set_cookie(
        "lab_session",
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=7 * 86400,
        path="/",
    )
    return public_user(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.execute(
        delete(AuthSession).where(
            AuthSession.token_hash == token_hash(request.cookies.get("lab_session", ""))
        )
    )
    db.commit()
    response.delete_cookie("lab_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


@app.post("/api/auth/change-password")
def change_password(
    spec: PasswordChange,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(spec.current_password, user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    if spec.current_password == spec.new_password:
        raise HTTPException(422, "新密码必须与当前密码不同")
    user.password_hash = hasher.hash(spec.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, user, "user.change_password", "user", user.id)
    db.commit()
    response.delete_cookie("lab_session", path="/")
    return {"ok": True, "message": "密码已修改，请使用新密码重新登录"}


@app.get("/api/auth/traefik")
def forward_auth(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    uri = unquote(urlsplit(request.headers.get("x-forwarded-uri", "")).path)
    if ".." in uri.split("/") or "\\" in uri or "\x00" in uri:
        raise HTTPException(403, "无效路由")
    workspace_match = re.fullmatch(r"/workspace/([a-z][a-z0-9_]{2,31})/.*", uri)
    debug_match = re.fullmatch(r"/debug/([a-f0-9-]{36})/.*", uri)
    if workspace_match:
        owner = db.scalar(select(User).where(User.username == workspace_match[1]))
        if owner and owner.enabled and (user.role == "ADMIN" or owner.id == user.id):
            return Response(status_code=200)
    if debug_match:
        resource = db.get(Workload, debug_match[1])
        if (
            resource
            and resource.kind == "debug"
            and resource.status == "RUNNING"
            and (user.role == "ADMIN" or resource.user_id == user.id)
        ):
            return Response(status_code=200)
    raise HTTPException(403, "无权访问此工作区或调试会话")


@app.get("/api/users")
def users(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [
        public_user(item) for item in db.scalars(select(User).order_by(User.created_at))
    ]


@app.post("/api/users", status_code=201)
def add_user(
    spec: UserCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)
):
    db.execute(text("SELECT pg_advisory_xact_lock(719103)"))
    if db.scalar(select(User).where(User.username == spec.username)):
        raise HTTPException(409, "用户名已存在")
    env = allowed_environment(db, user, spec.default_environment_id)
    if spec.max_gpus > settings.gpu_count:
        raise HTTPException(422, "max_gpus 超过集群 GPU 数量")
    target = User(
        **spec.model_dump(exclude={"password", "default_environment_id"}),
        password_hash=hasher.hash(spec.password),
        default_environment_id=env.id,
        uid_hint=(db.scalar(select(func.max(User.uid_hint))) or 1999) + 1,
    )
    db.add(target)
    db.flush()
    runtime.provision(target)
    db.add(Workspace(user_id=target.id, route_path=f"/workspace/{target.username}/"))
    audit(db, user, "user.create", "user", target.id)
    db.commit()
    return public_user(target)


@app.get("/api/users/{user_id}")
def read_user(
    user_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)
):
    return public_user(target_user(db, user, user_id))


def update_user(db: Session, actor: User, user_id: str, changes: dict):
    db.execute(text("SELECT pg_advisory_xact_lock(719103)"))
    target = target_user(db, actor, user_id)
    if target.id == actor.id and (
        changes.get("enabled") is False or changes.get("role", "ADMIN") != "ADMIN"
    ):
        raise HTTPException(422, "不能停用或降级当前管理员账号")
    if changes.get("max_gpus", 0) > settings.gpu_count:
        raise HTTPException(422, "max_gpus 超过集群 GPU 数量")
    if changes.get("default_environment_id"):
        allowed_environment(db, actor, changes["default_environment_id"])
        if changes["default_environment_id"] != target.default_environment_id:
            if db.scalar(
                select(Workload.id).where(
                    Workload.user_id == target.id,
                    Workload.status.in_(["PENDING", *ACTIVE]),
                )
            ) or runtime.get(runtime.name("workspace", target.username)):
                raise HTTPException(
                    409, "更换环境前请停止工作区及所有任务；确认新镜像 Python ABI 兼容"
                )
    for key, value in changes.items():
        setattr(target, key, value)
    if changes.get("enabled") is False:
        db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
        container = runtime.get(runtime.name("workspace", target.username))
        if container:
            runtime.remove(container)
        workspace = db.get(Workspace, target.id)
        workspace.state, workspace.container_id = "STOPPED", None
    audit(db, actor, "user.update", "user", target.id, {"fields": list(changes)})
    db.commit()
    return public_user(target)


@app.patch("/api/users/{user_id}")
def patch_user(
    user_id: str,
    spec: UserPatch,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    return update_user(db, user, user_id, spec.model_dump(exclude_none=True))


@app.post("/api/users/{user_id}/enable")
def enable_user(
    user_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)
):
    return update_user(db, user, user_id, {"enabled": True})


@app.post("/api/users/{user_id}/disable")
def disable_user(
    user_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)
):
    return update_user(db, user, user_id, {"enabled": False})


@app.post("/api/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    spec: PasswordReset,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    target = target_user(db, user, user_id)
    target.password_hash = hasher.hash(spec.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    audit(db, user, "user.reset_password", "user", target.id)
    db.commit()
    return {"ok": True}


def workspace_payload(db: Session, target: User):
    workspace = db.get(Workspace, target.id)
    container = runtime.get(runtime.name("workspace", target.username))
    workspace.state = (
        "RUNNING" if container and container.status == "running" else "STOPPED"
    )
    workspace.container_id = container.id if container else None
    db.commit()
    return {
        "state": workspace.state,
        "route_path": workspace.route_path,
        "container_id": workspace.container_id,
        "environment": public_environment(
            db.get(Environment, target.default_environment_id)
        ),
        "venv": "/opt/user-env/venv",
    }


@app.get("/api/workspace")
def workspace(
    user_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return workspace_payload(db, target_user(db, user, user_id))


def workspace_action(db: Session, actor: User, target: User, action: str):
    db.scalar(select(User).where(User.id == target.id).with_for_update())
    container = runtime.get(runtime.name("workspace", target.username))
    record = db.get(Workspace, target.id)
    if action in {"stop", "restart"}:
        if container:
            runtime.remove(container)
        container = None
        record.last_stopped_at = now()
    if action in {"start", "restart"}:
        if not target.enabled:
            raise HTTPException(422, "用户已停用")
        env = allowed_environment(db, target, None)
        if container and container.status != "running":
            runtime.remove(container)
            container = None
        if not container:
            container = runtime.create(
                db,
                target,
                env,
                "workspace",
                target.username,
                [],
                2,
                2048,
                route=record.route_path,
            )
            container.start()
        record.last_started_at = now()
    audit(db, actor, f"workspace.{action}", "user", target.id)
    db.commit()
    return workspace_payload(db, target)


@app.post("/api/workspace/{action}")
def manage_workspace(
    action: str,
    user_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(404)
    return workspace_action(db, user, target_user(db, user, user_id), action)


def list_workloads(db: Session, user: User, kind: str):
    query = select(Workload).where(Workload.kind == kind)
    if user.role != "ADMIN":
        query = query.where(Workload.user_id == user.id)
    return [
        public_workload(item, db)
        for item in db.scalars(query.order_by(Workload.created_at.desc()).limit(500))
    ]


@app.get("/api/jobs")
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list_workloads(db, user, "train")


@app.post("/api/jobs", status_code=201)
def add_job(
    spec: JobSpec, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    validate_resources(user, spec)
    spec.environment_id = allowed_environment(db, user, spec.environment_id).id
    resource = scheduler.submit_train(db, user, spec)
    audit(db, user, "job.submit", "job", resource.id)
    db.commit()
    return public_workload(resource, db)


@app.get("/api/jobs/{resource_id}")
def job(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return public_workload(accessible_resource(db, user, resource_id, "train"), db)


@app.post("/api/jobs/{resource_id}/cancel")
def cancel_job(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    resource = accessible_resource(db, user, resource_id, "train")
    scheduler.cancel(db, resource)
    audit(db, user, "job.cancel", "job", resource.id)
    db.commit()
    return public_workload(resource, db)


@app.post("/api/jobs/{resource_id}/retry", status_code=201)
def retry_job(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    old = accessible_resource(db, user, resource_id, "train")
    if old.status not in TERMINAL:
        raise HTTPException(409, "任务结束后才能重试")
    owner = db.get(User, old.user_id)
    if not owner.enabled:
        raise HTTPException(422, "用户已停用")
    spec = JobSpec(
        **{
            key: getattr(old, key)
            for key in (
                "environment_id",
                "requested_gpus",
                "requested_cpus",
                "requested_ram_mb",
                "time_limit_seconds",
                "command",
                "workdir",
                "output_name",
            )
        },
        env=old.env_json,
    )
    validate_resources(owner, spec)
    allowed_environment(db, owner, spec.environment_id)
    resource = scheduler.submit_train(db, owner, spec)
    audit(db, user, "job.retry", "job", resource.id, {"previous_id": old.id})
    db.commit()
    return public_workload(resource, db)


def log_payload(resource: Workload):
    path = Path(settings.runtime_root, "logs/jobs", f"{resource.id}.log")
    if path.exists():
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 262144))
            content = stream.read().decode("utf-8", errors="replace")
    else:
        content = "等待容器启动…"
    return {"id": resource.id, "status": resource.status, "log": content}


@app.get("/api/jobs/{resource_id}/logs")
def job_logs(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return log_payload(accessible_resource(db, user, resource_id, "train"))


@app.get("/api/debug")
def debug_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list_workloads(db, user, "debug")


@app.post("/api/debug", status_code=201)
def add_debug(
    spec: DebugSpec, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    validate_resources(user, spec)
    spec.environment_id = allowed_environment(db, user, spec.environment_id).id
    resource = scheduler.start_debug(db, user, spec)
    audit(db, user, "debug.start", "debug", resource.id)
    db.commit()
    return public_workload(resource, db)


@app.post("/api/debug/{resource_id}/stop")
def stop_debug(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    resource = accessible_resource(db, user, resource_id, "debug")
    scheduler.cancel(db, resource)
    audit(db, user, "debug.stop", "debug", resource.id)
    db.commit()
    return public_workload(resource, db)


@app.get("/api/debug/{resource_id}/logs")
def debug_logs(
    resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return log_payload(accessible_resource(db, user, resource_id, "debug"))


@app.get("/api/resources/gpus")
def gpus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    slots = []
    for slot in scheduler.list_resources(db):
        owner = db.get(Workload, slot.owner_id) if slot.owner_id else None
        slots.append(
            {
                "gpu_index": slot.gpu_index,
                "state": slot.state,
                "owner_type": slot.owner_type,
                "owner_id": slot.owner_id,
                "username": db.get(User, owner.user_id).username if owner else None,
                "started_at": owner.started_at if owner else None,
            }
        )
    heartbeat = Path(settings.runtime_root, "logs/scheduler-heartbeat")
    online = heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 30
    return {"mode": settings.scheduler_backend, "worker_online": online, "slots": slots}


@app.get("/api/resources/queue")
def queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = (
        select(Workload)
        .where(Workload.status.in_(["PENDING", *ACTIVE]))
        .order_by(Workload.created_at, Workload.id)
    )
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "status": item.status,
            "requested_gpus": item.requested_gpus,
            "username": db.get(User, item.user_id).username,
            "created_at": item.created_at,
        }
        for item in db.scalars(query)
    ]


@app.get("/api/environments")
def environments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    local_images = {image.id for image in runtime.client.images.list()}
    return [
        {**public_environment(item), "available": item.image in local_images}
        for item in db.scalars(select(Environment).order_by(Environment.created_at))
        if user.role == "ADMIN" or item.enabled
    ]


@app.post("/api/environments", status_code=201)
def add_environment(
    spec: EnvironmentCreate,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    image = runtime.client.images.get(spec.image)
    # Store immutable Docker content ID, so repointing a tag never silently upgrades users.
    env = Environment(**spec.model_dump(exclude={"image"}), image=image.id)
    db.add(env)
    db.flush()
    # Keep an explicit tag: Docker Desktop may discard untagged manifest indexes
    # when the mutable development build tag is replaced.
    image.tag(f"lab-env-{env.id}", tag="pinned")
    audit(db, user, "environment.create", "environment", env.id)
    db.commit()
    return public_environment(env)


@app.patch("/api/environments/{env_id}")
def patch_environment(
    env_id: str,
    spec: EnvironmentPatch,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    env = db.get(Environment, env_id)
    if not env:
        raise HTTPException(404)
    env.enabled = spec.enabled
    audit(db, user, "environment.update", "environment", env.id)
    db.commit()
    return public_environment(env)


@app.get("/api/settings/env")
def env_settings(
    user_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    scope = user_id or "global"
    if user.role != "ADMIN":
        if user_id and user_id != user.id:
            raise HTTPException(403)
        scopes = ["global", user.id]
    else:
        if user_id:
            target_user(db, user, user_id)
        scopes = [scope]
    return [
        {
            "scope": item.scope,
            "key": item.key,
            "value": "********" if item.is_secret else item.value,
            "is_secret": item.is_secret,
            "enabled": item.enabled,
        }
        for item in db.scalars(
            select(EnvVar)
            .where(EnvVar.scope.in_(scopes))
            .order_by(EnvVar.scope, EnvVar.key)
        )
    ]


@app.put("/api/settings/env")
def set_env(
    spec: EnvSetting, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if user.role != "ADMIN" and spec.user_id != user.id:
        raise HTTPException(403, "成员仅能修改自己的环境变量")
    if spec.user_id:
        target_user(db, user, spec.user_id)
    scope = spec.user_id or "global"
    item = db.get(EnvVar, (scope, spec.key))
    if not item:
        item = EnvVar(scope=scope, key=spec.key, value=spec.value)
        db.add(item)
    item.value, item.is_secret, item.enabled = spec.value, spec.is_secret, spec.enabled
    audit(db, user, "env.update", "env", f"{scope}/{spec.key}")
    db.commit()
    return {"ok": True, "message": "仅对新建容器生效"}


@app.get("/api/system/remote-access")
@app.get("/api/settings/remote")
def remote_access(user: User = Depends(current_user)):
    containers = runtime.client.containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={settings.project}",
                "com.docker.compose.service=cloudflared",
            ]
        },
    )
    result = {"mode": "cloudflare-quick", "status": "offline", "url": None}
    if not containers or containers[0].status != "running":
        remote_urls.clear()
        return result
    container = containers[0]
    started = container.attrs["State"]["StartedAt"]
    key = (container.id, started)
    url = remote_urls.get(key)
    if not url:
        # Docker keeps logs across restarts. Only advertise this process's URL.
        # Docker emits UTC nanoseconds; Python 3.10 accepts up to microseconds.
        since = int(datetime.fromisoformat(started[:19] + "+00:00").timestamp())
        content = container.logs(since=since).decode(errors="replace")
        matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", content)
        if matches:
            url = matches[-1]
            remote_urls.clear()
            remote_urls[key] = url
    result.update(status="connecting", url=url)
    try:
        # A running process alone does not prove an active Cloudflare connection.
        with urlopen("http://cloudflared:20241/ready", timeout=1) as ready:
            if ready.status == 200 and url:
                result["status"] = "online"
    except (URLError, OSError):
        pass
    return result


@app.get("/api/storage")
def user_storage(user: User = Depends(current_user)):
    return {
        "username": user.username,
        "bytes": storage.usage(user.username),
        "venv_volume": f"lab_pyenv_{user.username}",
        "datasets": "共享只读挂载 /datasets",
    }


@app.get("/api/admin/storage")
def admin_storage(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [
        {
            "user_id": item.id,
            "username": item.username,
            "bytes": storage.usage(item.username),
        }
        for item in db.scalars(select(User))
    ]


@app.get("/api/admin/overview")
def overview(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    containers = runtime.managed()
    return {
        "users": db.scalar(select(func.count(User.id))),
        "workspaces": sum(
            c.labels.get("lab.kind") == "workspace" and c.status == "running"
            for c in containers
        ),
        "running": db.scalar(
            select(func.count(Workload.id)).where(Workload.status.in_(ACTIVE))
        ),
        "pending": db.scalar(
            select(func.count(Workload.id)).where(Workload.status == "PENDING")
        ),
        "scheduler_backend": settings.scheduler_backend,
    }


@app.get("/api/admin/audit")
def audit_events(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "user_id": item.user_id,
            "created_at": item.created_at,
            "metadata": item.metadata_json,
        }
        for item in db.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)
        )
    ]
