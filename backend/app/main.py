from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
import shlex
import threading
import time
import unicodedata
from urllib.parse import unquote, urlsplit
from urllib.error import URLError
from urllib.request import urlopen
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session
from .auth import admin_user, current_user, member_user, hasher, token_hash, verify_password
from .config import settings
from .host_editor import host_workspace
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
    ApprovalDecision,
    EnvironmentCreate,
    EnvironmentPatch,
    EnvSetting,
    JobSpec,
    WorkloadPatch,
    validate_env,
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
from .gpu_telemetry import read_telemetry
from .announcements import router as announcements_router
from .schemas import TrainingExtension

app = FastAPI(
    title="GPU Lab Portal",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
scheduler = get_scheduler()
app.include_router(announcements_router)
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
            "approval_status",
            "approval_reason",
            "approval_note",
            "approved_by",
            "approved_at",
        )
    }
    result.update(
        can_manage=True,
        assigned_gpus=resource.assigned_gpus_json,
        requested_gpu_indices=resource.requested_gpu_indices_json,
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


def recommended_environment(db: Session) -> Environment | None:
    try:
        image_id = runtime.client.images.get(settings.torch_image).id
    except NotFound:
        return None
    return db.scalar(select(Environment).where(
        Environment.image == image_id, Environment.enabled.is_(True)
    ).order_by(Environment.created_at.desc()))


def deletion_lock(db: Session):
    # Wait for a whole scheduler tick, including its commits, before deletion.
    db.execute(text("SELECT pg_advisory_xact_lock(719102)"))
    db.execute(text("SELECT pg_advisory_xact_lock(719103)"))


def lock_user(db: Session, user: User) -> User:
    return db.scalar(select(User).where(User.id == user.id).with_for_update()
                     .execution_options(populate_existing=True))


def idle_user(db: Session, target: User):
    if db.scalar(select(Workload.id).where(
        Workload.user_id == target.id, Workload.status.in_(["AWAITING_APPROVAL", "PENDING", *ACTIVE])
    ).limit(1)):
        raise HTTPException(409, "请先停止调试并取消或等待训练任务结束")


def validate_resources(user: User, spec):
    if spec.requested_gpus > min(user.max_gpus, settings.gpu_count):
        raise HTTPException(422, "GPU 数量超过用户或集群上限")
    if spec.gpu_indices is not None and any(index >= settings.gpu_count for index in spec.gpu_indices):
        raise HTTPException(422, "指定的显卡编号不在本集群中")
    if (
        isinstance(spec, DebugSpec)
        and spec.time_limit_seconds > min(user.max_debug_hours, 8) * 3600
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
    if re.fullmatch(r"/host(?:/.*)?", uri):
        if user.role == "ADMIN":
            return Response(status_code=200)
        raise HTTPException(403, "仅管理员可以访问宿主机")
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


@app.get("/api/auth/host-editor")
def host_editor_auth(user: User = Depends(admin_user)):
    return Response(status_code=204)


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
    preferred = recommended_environment(db) if not spec.default_environment_id else None
    env = allowed_environment(db, user, spec.default_environment_id or (preferred.id if preferred else None))
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
                    Workload.status.in_(["AWAITING_APPROVAL", "PENDING", *ACTIVE]),
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


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    deletion_lock(db)
    target = lock_user(db, target_user(db, user, user_id))
    if target.id == user.id:
        raise HTTPException(422, "不能删除当前管理员账号")
    if target.enabled:
        raise HTTPException(409, "请先停用账号再删除")
    idle_user(db, target)
    for container in runtime.managed():
        if container.labels.get("lab.user") == target.username:
            runtime.remove(container)
    runtime.remove_python_volume(target)
    storage.delete_user_data(target.username, ("workspace", "results", "scratch"))
    for resource in db.scalars(select(Workload).where(Workload.user_id == target.id)):
        Path(settings.runtime_root, "logs/jobs", f"{resource.id}.log").unlink(missing_ok=True)
    db.execute(delete(Workload).where(Workload.user_id == target.id))
    db.execute(delete(Workspace).where(Workspace.user_id == target.id))
    db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    db.execute(delete(EnvVar).where(EnvVar.scope == target.id))
    # Preserve audit history after its former actor account is gone.
    db.execute(update(AuditEvent).where(AuditEvent.user_id == target.id).values(user_id=None))
    audit(db, user, "user.delete", "user", target.id, {"username": target.username})
    db.delete(target)
    db.commit()
    return {"ok": True}


def workspace_payload(db: Session, target: User, actor: User | None = None):
    if target.role == "ADMIN":
        return host_workspace()
    workspace = db.get(Workspace, target.id)
    container = runtime.get(runtime.name("workspace", target.username))
    workspace.state = (
        "RUNNING" if container and container.status == "running" else "STOPPED"
    )
    workspace.container_id = container.id if container else None
    db.commit()
    host_paths = storage.host_paths(target.username)
    import_destination = shlex.quote(host_paths["workspace"] + "/project/")
    result = {
        "mode": "container",
        "state": workspace.state,
        "route_path": workspace.route_path,
        "container_id": workspace.container_id,
        "environment": public_environment(
            db.get(Environment, target.default_environment_id)
        ),
        "venv": "/opt/user-env/venv",
    }
    if (actor or target).role == "ADMIN":
        result.update(host_paths=host_paths, host_uid=target.uid_hint, host_gid=target.uid_hint,
                      host_import_command=f"sudo rsync -a --chown={target.uid_hint}:{target.uid_hint} -- /path/to/project/ {import_destination}")
    return result


@app.get("/api/workspace")
def workspace(
    user_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return workspace_payload(db, target_user(db, user, user_id), user)


def workspace_action(db: Session, actor: User, target: User, action: str):
    target = lock_user(db, target)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.role == "ADMIN":
        if action != "start":
            raise HTTPException(422, "宿主机服务不通过学生工作区停止或重建")
        payload = host_workspace()
        if payload["state"] != "RUNNING":
            raise HTTPException(503, payload["error_message"])
        audit(db, actor, "host_editor.open", "host", "local")
        db.commit()
        return payload
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
    return workspace_payload(db, target, actor)


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


@app.delete("/api/workspace")
def delete_workspace(user_id: str | None = None, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    deletion_lock(db)
    target = lock_user(db, target_user(db, user, user_id))
    if target.role == "ADMIN":
        raise HTTPException(422, "不能通过工作区删除宿主机文件")
    idle_user(db, target)
    container = runtime.get(runtime.name("workspace", target.username))
    if container:
        runtime.remove(container)
    runtime.remove_python_volume(target)
    storage.delete_user_data(target.username, ("workspace", "scratch"))
    record = db.get(Workspace, target.id)
    record.state, record.container_id = "STOPPED", None
    record.last_stopped_at = now()
    runtime.provision(target)
    audit(db, user, "workspace.delete", "user", target.id, {"username": target.username})
    db.commit()
    return {"ok": True}


def list_workloads(db: Session, user: User, kind: str):
    query = select(Workload).where(Workload.kind == kind, or_(
        Workload.status.not_in(TERMINAL),
        func.coalesce(Workload.finished_at, Workload.created_at) >= now() - timedelta(days=7)))
    if user.role != "ADMIN":
        query = query.join(User, Workload.user_id == User.id).where(User.role == "MEMBER")
    records = []
    for item in db.scalars(query.order_by(Workload.created_at.desc()).limit(500)):
        if user.role == "ADMIN" or item.user_id == user.id:
            records.append(public_workload(item, db))
        else:
            summary = {key: getattr(item, key) for key in (
                "id", "kind", "user_id", "status", "requested_gpus", "time_limit_seconds",
                "created_at", "started_at", "expires_at", "finished_at")}
            summary.update(username=db.get(User, item.user_id).username, can_manage=False,
                           requested_gpu_indices=item.requested_gpu_indices_json,
                           assigned_gpus=item.assigned_gpus_json)
            records.append(summary)
    return records


@app.get("/api/jobs")
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list_workloads(db, user, "train")


@app.post("/api/jobs", status_code=201)
def add_job(
    spec: JobSpec, user: User = Depends(member_user), db: Session = Depends(get_db)
):
    user = lock_user(db, user)
    if not user or not user.enabled:
        raise HTTPException(401, "用户已停用")
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
@app.post("/api/jobs/{resource_id}/kill")
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
    resource_id: str, user: User = Depends(member_user), db: Session = Depends(get_db)
):
    old = accessible_resource(db, user, resource_id, "train")
    if old.status not in TERMINAL:
        raise HTTPException(409, "任务结束后才能重试")
    owner = lock_user(db, db.get(User, old.user_id))
    if not owner or not owner.enabled:
        raise HTTPException(422, "用户已停用")
    try:
        spec = JobSpec(
            gpu_indices=old.requested_gpu_indices_json,
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
    except ValidationError:
        raise HTTPException(422, "旧任务配置不符合当前资源限制，请新建训练任务并重新选择 GPU 和资源")
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
    spec: DebugSpec, user: User = Depends(member_user), db: Session = Depends(get_db)
):
    user = lock_user(db, user)
    if not user or not user.enabled:
        raise HTTPException(401, "用户已停用")
    validate_resources(user, spec)
    # User row lock serializes submissions, including concurrent tabs.
    if db.scalar(select(Workload.id).where(
        Workload.user_id == user.id, Workload.kind == "debug",
        Workload.status.in_(["AWAITING_APPROVAL", "PENDING", *ACTIVE])
    ).limit(1)):
        raise HTTPException(409, "每人同一时间只能有一个调试会话，请等待当前会话完全结束")
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


def decide_debug(db: Session, actor: User, resource_id: str, approved: bool, note: str):
    deletion_lock(db)
    resource = db.scalar(select(Workload).where(Workload.id == resource_id).with_for_update()
                         .execution_options(populate_existing=True))
    if not resource or resource.kind != "debug":
        raise HTTPException(404, "调试申请不存在")
    if resource.status != "AWAITING_APPROVAL" or resource.cancel_requested:
        raise HTTPException(409, "该申请已处理或已请求取消")
    owner = lock_user(db, db.get(User, resource.user_id))
    if approved:
        if not owner.enabled:
            raise HTTPException(409, "用户已停用")
        try:
            spec = DebugSpec(environment_id=resource.environment_id, requested_gpus=resource.requested_gpus,
                             gpu_indices=resource.requested_gpu_indices_json, requested_cpus=resource.requested_cpus,
                             requested_ram_mb=resource.requested_ram_mb, time_limit_seconds=resource.time_limit_seconds,
                             approval_reason=resource.approval_reason)
        except ValidationError:
            raise HTTPException(422, "旧调试申请不符合当前限制：至少一张 GPU、最多 8 小时，请先编辑申请")
        validate_resources(owner, spec)
        allowed_environment(db, owner, spec.environment_id)
        resource.status, resource.approval_status = "PENDING", "APPROVED"
    else:
        resource.status, resource.approval_status = "REJECTED", "REJECTED"
        resource.finished_at = now()
    resource.approved_by, resource.approved_at, resource.approval_note = actor.id, now(), note
    audit(db, actor, "debug.approve" if approved else "debug.reject", "debug", resource.id,
          {"hours": resource.time_limit_seconds / 3600, "note": note})
    db.commit()
    return public_workload(resource, db)


@app.post("/api/debug/{resource_id}/approve")
def approve_debug(resource_id: str, spec: ApprovalDecision, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return decide_debug(db, user, resource_id, True, spec.note)


@app.post("/api/debug/{resource_id}/reject")
def reject_debug(resource_id: str, spec: ApprovalDecision, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return decide_debug(db, user, resource_id, False, spec.note)


def delete_workload(db: Session, user: User, resource_id: str, kind: str):
    deletion_lock(db)
    resource = accessible_resource(db, user, resource_id, kind)
    if resource.status not in TERMINAL:
        raise HTTPException(409, "任务结束或停止后才能删除记录")
    container = runtime.get(runtime.name(kind, resource.id))
    if container:
        runtime.remove(container)
    Path(settings.runtime_root, "logs/jobs", f"{resource.id}.log").unlink(missing_ok=True)
    audit(db, user, f"{kind}.delete", kind, resource.id, {"username": db.get(User, resource.user_id).username})
    db.delete(resource)
    db.commit()
    return {"ok": True}


@app.delete("/api/jobs/{resource_id}")
def delete_job(resource_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return delete_workload(db, user, resource_id, "train")


@app.delete("/api/debug/{resource_id}")
def delete_debug(resource_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return delete_workload(db, user, resource_id, "debug")


@app.get("/api/resources/gpus")
def gpus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    slots = []
    telemetry = read_telemetry(Path(settings.runtime_root, "logs/gpu-telemetry.json"), settings.scheduler_backend)
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
                "metrics": telemetry["gpus"].get(str(slot.gpu_index)),
                "external_busy": slot.state == "FREE" and telemetry["gpus"].get(str(slot.gpu_index), {}).get("compute_process_count", 0) > 0,
            }
        )
    heartbeat = Path(settings.runtime_root, "logs/scheduler-heartbeat")
    online = heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 30
    return {"mode": settings.scheduler_backend, "worker_online": online, "slots": slots,
            "telemetry_status": telemetry["status"], "telemetry_sampled_at": telemetry["sampled_at"],
            "telemetry_error": telemetry["error"]}


@app.get("/api/resources/queue")
def queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = (
        select(Workload)
        .where(Workload.status.in_(["PENDING", *ACTIVE]))
        .order_by(func.coalesce(Workload.approved_at, Workload.created_at), Workload.id)
    )
    if user.role != "ADMIN":
        query = query.join(User, Workload.user_id == User.id).where(User.role == "MEMBER")
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "status": item.status,
            "requested_gpus": item.requested_gpus,
            "requested_gpu_indices": item.requested_gpu_indices_json,
            "username": db.get(User, item.user_id).username,
            "created_at": item.created_at,
            "can_manage": user.role == "ADMIN" or item.user_id == user.id,
            "cancel_requested": item.cancel_requested,
        }
        for item in db.scalars(query)
    ]


@app.get("/api/environments")
def environments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    local_images = {image.id for image in runtime.client.images.list()}
    preferred = recommended_environment(db)
    return [
        {**public_environment(item), "available": item.image in local_images,
         "recommended": item.id == (preferred.id if preferred else None)}
        for item in db.scalars(select(Environment).order_by(Environment.created_at))
        if user.role == "ADMIN" or item.enabled
    ]


@app.post("/api/environments", status_code=201)
def add_environment(
    spec: EnvironmentCreate,
    user: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    db.execute(text("SELECT pg_advisory_xact_lock(719103)"))
    image = runtime.client.images.get(spec.image)
    # Store immutable Docker content ID, so repointing a tag never silently upgrades users.
    env = Environment(**spec.model_dump(exclude={"image"}), image=image.id)
    db.add(env)
    db.flush()
    # Keep an explicit tag: Docker may discard untagged manifest indexes
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


@app.delete("/api/environments/{env_id}")
def delete_environment(env_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    deletion_lock(db)
    env = db.get(Environment, env_id)
    if not env:
        raise HTTPException(404, "环境不存在")
    if (db.scalar(select(User.id).where(User.default_environment_id == env.id).limit(1))
        or db.scalar(select(Workload.id).where(Workload.environment_id == env.id).limit(1))):
        raise HTTPException(409, "环境仍被用户或任务记录引用")
    audit(db, user, "environment.delete", "environment", env.id, {"name": env.name})
    db.delete(env)
    db.commit()
    return {"ok": True}


def image_inventory(db: Session) -> list[dict]:
    templates = list(db.scalars(select(Environment)))
    containers = runtime.client.containers.list(all=True)
    protected = set()
    for name in (settings.base_image, settings.torch_image):
        try:
            protected.add(runtime.client.images.get(name).id)
        except NotFound:
            pass
    result = []
    for image in runtime.client.images.list():
        reasons = []
        if image.id in protected:
            reasons.append("集群默认镜像")
        used_templates = [e.name for e in templates if e.image == image.id]
        if used_templates:
            reasons.append("环境模板: " + ", ".join(used_templates))
        used_containers = [c.name for c in containers if c.attrs.get("Image") == image.id]
        if used_containers:
            reasons.append("容器: " + ", ".join(used_containers))
        result.append({"id": image.id, "tags": image.tags, "size": image.attrs.get("Size", 0),
                       "blocked_reasons": reasons})
    return result


@app.get("/api/admin/images")
def docker_images(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return image_inventory(db)


@app.delete("/api/admin/images/{image_id}")
def delete_docker_image(image_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise HTTPException(422, "请使用完整的镜像 SHA256 ID")
    deletion_lock(db)
    item = next((i for i in image_inventory(db) if i["id"] == image_id), None)
    if not item:
        raise HTTPException(404, "镜像不存在")
    if item["blocked_reasons"]:
        raise HTTPException(409, "镜像仍在使用: " + "; ".join(item["blocked_reasons"]))
    # Remove the explicitly confirmed tags; never force an in-use image away.
    for reference in item["tags"] or [image_id]:
        try:
            runtime.client.images.remove(reference, force=False, noprune=True)
        except NotFound:
            pass
    audit(db, user, "image.delete", "image", image_id, {"tags": item["tags"]})
    db.commit()
    return {"ok": True}


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


@app.delete("/api/settings/env/{key}")
def delete_env(key: str, user_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "ADMIN":
        if user_id and user_id != user.id:
            raise HTTPException(403, "成员仅能删除自己的环境变量")
        user_id = user.id
    if user_id:
        target_user(db, user, user_id)
    try:
        validate_env({key: ""})
    except ValueError as error:
        raise HTTPException(422, str(error))
    scope = user_id or "global"
    item = db.get(EnvVar, (scope, key))
    if not item:
        raise HTTPException(404, "环境变量不存在")
    db.delete(item)
    audit(db, user, "env.delete", "env", f"{scope}/{key}")
    db.commit()
    return {"ok": True}


def edit_workload(db: Session, actor: User, resource_id: str, kind: str, patch: WorkloadPatch):
    deletion_lock(db)
    resource = db.scalar(select(Workload).where(Workload.id == resource_id).with_for_update()
                         .execution_options(populate_existing=True))
    if not resource or resource.kind != kind:
        raise HTTPException(404, "任务不存在")
    changes = patch.model_dump(exclude_unset=True)
    if resource.cancel_requested or resource.status not in {"PENDING", "AWAITING_APPROVAL", "RUNNING"}:
        raise HTTPException(409, "当前状态不能编辑任务")
    if resource.status == "RUNNING" and set(changes) != {"time_limit_seconds"}:
        raise HTTPException(409, "运行中的任务仅可调整时长")
    if kind == "debug" and set(changes) & {"command", "workdir", "output_name"}:
        raise HTTPException(422, "调试会话不能修改训练命令")
    owner = lock_user(db, db.get(User, resource.user_id))
    if not owner or not owner.enabled:
        raise HTTPException(409, "用户已停用")
    data = {key: getattr(resource, key) for key in (
        "environment_id", "requested_gpus", "requested_cpus", "requested_ram_mb", "time_limit_seconds")}
    data["gpu_indices"] = resource.requested_gpu_indices_json
    if kind == "train":
        data.update(command=resource.command, workdir=resource.workdir, output_name=resource.output_name, env=resource.env_json)
    else:
        data["approval_reason"] = resource.approval_reason or "管理员调整调试时长"
    data.update(changes)
    try:
        spec = JobSpec(**data) if kind == "train" else DebugSpec(**data)
    except ValidationError as error:
        raise HTTPException(422, str(error))
    validate_resources(owner, spec)
    allowed_environment(db, owner, spec.environment_id)
    if resource.status == "RUNNING":
        started = resource.started_at
        if not started:
            raise HTTPException(409, "任务启动时间不可用")
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        deadline = started + timedelta(seconds=spec.time_limit_seconds)
        if deadline <= now():
            raise HTTPException(422, "新的总时长必须大于已运行时长")
        resource.expires_at = deadline
    for key, value in changes.items():
        setattr(resource, "requested_gpu_indices_json" if key == "gpu_indices" else key, getattr(spec, key))
    audit(db, actor, f"{kind}.edit", kind, resource.id, {"fields": list(changes)})
    db.commit()
    return public_workload(resource, db)


@app.patch("/api/jobs/{resource_id}")
def patch_job(resource_id: str, spec: WorkloadPatch, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return edit_workload(db, user, resource_id, "train", spec)


@app.post("/api/jobs/{resource_id}/extend")
def extend_job(resource_id: str, spec: TrainingExtension, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    deletion_lock(db)
    resource = accessible_resource(db, user, resource_id, "train")
    try:
        patch = WorkloadPatch(time_limit_seconds=resource.time_limit_seconds + spec.extra_seconds)
    except ValidationError as error:
        raise HTTPException(422, str(error))
    return edit_workload(db, user, resource_id, "train", patch)


@app.patch("/api/debug/{resource_id}")
def patch_debug(resource_id: str, spec: WorkloadPatch, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return edit_workload(db, user, resource_id, "debug", spec)


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
def user_storage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    username = user.username
    # Filesystem scans can be slow; release the authentication connection first.
    db.close()
    return {
        "username": username,
        "bytes": storage.usage(username),
        "venv_volume": f"lab_pyenv_{username}",
        "datasets": "共享只读挂载 $HOME/dataset（$DATASET；兼容 /datasets）",
    }


@app.get("/api/admin/storage")
def admin_storage(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    users = db.execute(select(User.id, User.username, User.role)).all()
    db.close()
    return [
        {
            "user_id": item.id,
            "username": item.username,
            "role": item.role,
            "workspace_host_path": storage.host_paths(item.username)["workspace"] if item.role == "MEMBER" else None,
            "bytes": storage.usage(item.username),
        }
        for item in users
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
