from datetime import timedelta
import logging
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..models import Environment, GpuSlot, User, Workload, now, new_id
from ..schemas import JobSpec, DebugSpec
from ..docker_runtime import runtime
from ..config import settings
from ..storage import storage
from ..gpu_telemetry import read_telemetry
from pathlib import Path
from .base import ACTIVE, TERMINAL

logger = logging.getLogger(__name__)


def first_fit(free: list[int], count: int, selected: list[int] | None = None) -> list[int] | None:
    if selected is not None:
        return list(selected) if len(selected) == count and set(selected).issubset(free) else None
    return sorted(free)[:count] if len(free) >= count else None


class MockDockerScheduler:
    real_gpu = False

    def submit_train(self, db: Session, user: User, spec: JobSpec) -> Workload:
        data = spec.model_dump()
        env = data.pop("env")
        selected = data.pop("gpu_indices")
        resource = Workload(kind="train", user_id=user.id, env_json=env,
                            requested_gpu_indices_json=selected, **data)
        db.add(resource)
        db.flush()
        return resource

    def start_debug(self, db: Session, user: User, spec: DebugSpec) -> Workload:
        resource_id = new_id()
        data = spec.model_dump()
        selected = data.pop("gpu_indices")
        resource = Workload(
            id=resource_id,
            kind="debug",
            user_id=user.id,
            route_path=f"/debug/{resource_id}/",
            command="code-server",
            status="PENDING",
            approval_status="NOT_REQUIRED",
            requested_gpu_indices_json=selected,
            **data,
        )
        db.add(resource)
        db.flush()
        return resource

    def cancel(self, db: Session, resource: Workload) -> None:
        if resource.status not in TERMINAL:
            resource.cancel_requested = True

    def get_status(self, db: Session, resource_id: str) -> Workload | None:
        return db.get(Workload, resource_id)

    def list_resources(self, db: Session) -> list[GpuSlot]:
        return list(db.scalars(select(GpuSlot).order_by(GpuSlot.gpu_index)))

    def finish(
        self,
        db: Session,
        resource: Workload,
        container,
        status: str,
        error: str | None = None,
    ):
        if container:
            if container.status == "running":
                container.stop(timeout=3)
                container.reload()
            # Commit terminal state only after logs have been durably saved.
            runtime.capture_log(resource, container)
            resource.exit_code = container.attrs["State"].get("ExitCode")
        resource.status = status
        if resource.approval_status == "PENDING":
            resource.approval_status = "CANCELLED"
        resource.finished_at = now()
        resource.error_message = error
        for slot in db.scalars(select(GpuSlot).where(GpuSlot.owner_id == resource.id)):
            slot.state, slot.owner_type, slot.owner_id = "FREE", None, None
        db.commit()
        if container:
            runtime.remove(container)

    def reconcile(self, db: Session):
        # Terminal containers remaining after a crash are cleaned only after recapturing logs.
        for container in runtime.managed():
            if container.labels.get("lab.kind") == "workspace":
                continue
            resource = db.get(Workload, container.labels.get("lab.job_id", ""))
            if resource is None:
                # Unknown managed workload cannot continue consuming GPUs.
                if container.status == "running":
                    container.stop(timeout=3)
                storage.save_log(
                    f"orphan-{container.id}",
                    container.logs(stdout=True, stderr=True, timestamps=True),
                )
                runtime.remove(container)
            elif resource.status in TERMINAL:
                runtime.capture_log(resource, container)
                db.commit()
                runtime.remove(container)
        for slot in self.list_resources(db):
            owner = db.get(Workload, slot.owner_id) if slot.owner_id else None
            if not owner or owner.status not in ACTIVE:
                slot.state, slot.owner_id, slot.owner_type = "FREE", None, None
        # Restore allocations from the durable assignment if a slot row was stale.
        for resource in db.scalars(select(Workload).where(Workload.status.in_(ACTIVE))):
            for index in resource.assigned_gpus_json:
                slot = db.get(GpuSlot, index)
                if not slot or (slot.owner_id and slot.owner_id != resource.id):
                    raise RuntimeError("GPU allocation conflict during recovery")
                slot.state, slot.owner_id, slot.owner_type = (
                    "RUNNING",
                    resource.id,
                    resource.kind,
                )
        db.commit()

    def launch(self, db: Session, resource: Workload):
        if resource.kind == "debug" and resource.time_limit_seconds > 28800 and resource.started_at is None:
            self.finish(db, resource, None, "FAILED", "Debug sessions are limited to eight hours")
            return
        if resource.requested_gpus < 1:
            self.finish(db, resource, None, "FAILED", "Training and debugging require at least one GPU")
            return
        user = db.get(User, resource.user_id)
        env = db.get(Environment, resource.environment_id)
        # Disabled users/images must not start queued work.
        if not user.enabled or not env.enabled:
            self.finish(db, resource, None, "CANCELLED", "User or environment disabled")
            return
        container = runtime.create(
            db,
            user,
            env,
            resource.kind,
            resource.id,
            resource.assigned_gpus_json,
            resource.requested_cpus,
            resource.requested_ram_mb,
            resource.workdir,
            resource.command,
            resource.env_json,
            resource.route_path,
            resource.output_name,
            self.real_gpu,
        )
        resource.container_id = container.id
        if container.status == "created":
            container.start()
        container.reload()
        # A crash after Docker start but before this commit is recovered from STARTING.
        state = container.attrs.get("State", {})
        started = state.get("StartedAt", "")
        if resource.started_at is None:
            from datetime import datetime

            resource.started_at = (
                datetime.fromisoformat(started[:26] + "+00:00")
                if started and not started.startswith("0001")
                else now()
            )
        resource.expires_at = resource.started_at + timedelta(
            seconds=resource.time_limit_seconds
        )
        resource.status = "RUNNING"
        db.commit()

    def tick(self, db: Session):
        self.reconcile(db)
        for resource in list(
            db.scalars(
                select(Workload)
                .where(Workload.status.in_(["AWAITING_APPROVAL", "PENDING", *ACTIVE]))
                .order_by(func.coalesce(Workload.approved_at, Workload.created_at), Workload.id)
            )
        ):
            container = runtime.get(runtime.name(resource.kind, resource.id))
            user = db.get(User, resource.user_id)
            if resource.cancel_requested or not user.enabled:
                self.finish(db, resource, container, "CANCELLED")
                continue
            if resource.status == "STARTING":
                try:
                    self.launch(db, resource)
                except Exception as exc:
                    logger.exception("Workload start failed: %s", resource.id)
                    self.finish(
                        db,
                        resource,
                        runtime.get(runtime.name(resource.kind, resource.id)),
                        "FAILED",
                        str(exc)[:2000],
                    )
                continue
            if resource.status == "RUNNING":
                if container is None:
                    self.finish(
                        db,
                        resource,
                        None,
                        "FAILED",
                        "Container missing during recovery",
                    )
                elif container.status in {"exited", "dead"}:
                    code = container.attrs["State"].get("ExitCode", 1)
                    self.finish(
                        db, resource, container, "COMPLETED" if code == 0 else "FAILED"
                    )
                elif now() >= resource.expires_at:
                    self.finish(db, resource, container, "TIMED_OUT")
                else:
                    runtime.capture_log(resource, container)
                    db.commit()
        # One global FIFO for debug and training; no preemption/backfilling.
        pending = list(
            db.scalars(
                select(Workload)
                .where(Workload.status == "PENDING")
                .order_by(func.coalesce(Workload.approved_at, Workload.created_at), Workload.id)
            )
        )
        for resource in pending:
            if resource.kind == "debug" and db.scalar(select(Workload.id).where(
                Workload.user_id == resource.user_id, Workload.kind == "debug",
                Workload.status.in_(ACTIVE), Workload.id != resource.id
            ).limit(1)):
                break  # Also serialize legacy queued debug sessions after an upgrade.
            free = [
                slot.gpu_index
                for slot in self.list_resources(db)
                if slot.state == "FREE"
            ]
            if self.real_gpu and resource.requested_gpus:
                telemetry = read_telemetry(Path(settings.runtime_root, "logs/gpu-telemetry.json"), settings.scheduler_backend)
                if telemetry["status"] != "online":
                    break  # Never guess physical availability from a stale sample.
                free = [i for i in free if str(i) in telemetry["gpus"]
                        and telemetry["gpus"][str(i)].get("compute_process_count", 0) == 0]
            assigned = first_fit(free, resource.requested_gpus, resource.requested_gpu_indices_json)
            user = db.get(User, resource.user_id)
            used = sum(
                len(other.assigned_gpus_json)
                for other in db.scalars(
                    select(Workload).where(
                        Workload.user_id == user.id, Workload.status.in_(ACTIVE)
                    )
                )
            )
            if resource.requested_gpus > min(user.max_gpus, settings.gpu_count):
                self.finish(
                    db,
                    resource,
                    None,
                    "FAILED",
                    "GPU request exceeds current user limit",
                )
                continue
            if assigned is None or used + resource.requested_gpus > user.max_gpus:
                break
            resource.assigned_gpus_json = assigned
            resource.status = "STARTING"
            for index in assigned:
                slot = db.get(GpuSlot, index)
                slot.state, slot.owner_type, slot.owner_id = (
                    "RUNNING",
                    resource.kind,
                    resource.id,
                )
            db.commit()  # reserve durably BEFORE calling Docker
            try:
                self.launch(db, resource)
            except Exception as exc:
                logger.exception("Workload start failed: %s", resource.id)
                self.finish(
                    db,
                    resource,
                    runtime.get(runtime.name(resource.kind, resource.id)),
                    "FAILED",
                    str(exc)[:2000],
                )
