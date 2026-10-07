"""One-shot runtime migration used by apply-latest.sh.

The scheduler worker must be stopped before this module runs. Active training
containers are intentionally left untouched. Running member workspaces and
debug containers are recreated so new mounts, environment variables and
code-server state paths take effect immediately without changing user data,
GPU allocations or debug deadlines.
"""

from __future__ import annotations

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .docker_runtime import runtime
from .models import Environment, User, Workload, Workspace
from .scheduler import get_scheduler


SYSTEM_TEMPLATES = {
    ("CUDA 12.8 · nvcc · Python 3.10", "2026.10-poc"): "base",
    ("CUDA 12.8 · nvcc · PyTorch 2.7.1", "2.7.1-cu128-editor"): "torch",
}


def refresh_system_template_images(db) -> None:
    """Move only built-in templates to the freshly rebuilt image IDs."""
    image_ids = {
        "base": runtime.client.images.get(settings.base_image).id,
        "torch": runtime.client.images.get(settings.torch_image).id,
    }
    changed = 0
    for env in db.scalars(select(Environment)):
        kind = SYSTEM_TEMPLATES.get((env.name, env.image_version))
        if kind and env.image != image_ids[kind]:
            env.image = image_ids[kind]
            changed += 1
    if changed:
        db.commit()
    print(f"Updated {changed} built-in environment template image reference(s).")


def recreate_runtime_sessions() -> None:
    scheduler = get_scheduler()
    recreated_workspaces = 0
    recreated_debug = 0

    with SessionLocal() as db:
        refresh_system_template_images(db)

        members = list(
            db.scalars(select(User).where(User.role == "MEMBER", User.enabled.is_(True)))
        )
        running_workspaces: list[tuple[User, Workspace]] = []
        for user in members:
            record = db.get(Workspace, user.id)
            container = runtime.get(runtime.name("workspace", user.username))
            if record and container and container.status == "running":
                running_workspaces.append((user, record))

        running_debug = list(
            db.scalars(
                select(Workload).where(
                    Workload.kind == "debug",
                    Workload.status == "RUNNING",
                    Workload.cancel_requested.is_(False),
                )
            )
        )

        # Recreate CPU workspaces first. Persistent workspace, Python and user-state
        # volumes remain in place; only the disposable container changes.
        for user, record in running_workspaces:
            old = runtime.get(runtime.name("workspace", user.username))
            if old:
                runtime.remove(old)
            env = db.get(Environment, user.default_environment_id)
            container = runtime.create(
                db,
                user,
                env,
                "workspace",
                user.username,
                [],
                2,
                2048,
                route=record.route_path,
            )
            container.start()
            record.state = "RUNNING"
            record.container_id = container.id
            recreated_workspaces += 1
            db.commit()

        # Recreate active debug containers with the same DB record, GPU assignment,
        # start time and expiry. Training containers are deliberately not touched.
        for resource in running_debug:
            user = db.get(User, resource.user_id)
            env = db.get(Environment, resource.environment_id)
            old = runtime.get(runtime.name("debug", resource.id))
            if old:
                runtime.remove(old)
            container = runtime.create(
                db,
                user,
                env,
                "debug",
                resource.id,
                resource.assigned_gpus_json,
                resource.requested_cpus,
                resource.requested_ram_mb,
                resource.workdir,
                resource.command,
                resource.env_json,
                resource.route_path,
                resource.output_name,
                scheduler.real_gpu,
            )
            container.start()
            resource.container_id = container.id
            recreated_debug += 1
            db.commit()

    print(
        "Runtime refresh complete: "
        f"{recreated_workspaces} workspace(s), {recreated_debug} debug session(s)."
    )
    print("Active training containers were left running and will use the new runtime on the next job.")


if __name__ == "__main__":
    recreate_runtime_sessions()
