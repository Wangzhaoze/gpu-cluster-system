from datetime import datetime, timezone
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Environment(Base):
    __tablename__ = "environment_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    image: Mapped[str] = mapped_column(String(300))
    image_version: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10), default="MEMBER")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    uid_hint: Mapped[int] = mapped_column(Integer, unique=True)
    default_environment_id: Mapped[str] = mapped_column(
        ForeignKey("environment_templates.id")
    )
    max_gpus: Mapped[int] = mapped_column(Integer, default=5)
    max_debug_hours: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnvVar(Base):
    __tablename__ = "environment_variables"
    # A scoped primary key prevents duplicate global/per-user keys.
    scope: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="STOPPED")
    route_path: Mapped[str] = mapped_column(String(100))
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Workload(Base):
    __tablename__ = "workloads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(
        String(10)
    )  # train / debug share one FIFO and allocation transaction
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    requested_gpus: Mapped[int] = mapped_column(Integer)
    requested_gpu_indices_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="NOT_REQUIRED")
    approval_reason: Mapped[str] = mapped_column(Text, default="")
    approval_note: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_gpus_json: Mapped[list] = mapped_column(JSON, default=list)
    requested_cpus: Mapped[int] = mapped_column(Integer)
    requested_ram_mb: Mapped[int] = mapped_column(Integer)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environment_templates.id"))
    command: Mapped[str] = mapped_column(Text)
    workdir: Mapped[str] = mapped_column(String(500), default="/workspace")
    env_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_name: Mapped[str] = mapped_column(String(100), default="run")
    route_path: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class GpuSlot(Base):
    __tablename__ = "gpu_slots"
    gpu_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(10), default="FREE")
    owner_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
