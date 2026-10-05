from sqlalchemy import select, text
from docker.errors import NotFound
from .auth import hasher
from .config import settings
from .db import SessionLocal
from .models import Environment, User, Workspace, GpuSlot
from .docker_runtime import runtime


def seed():
    if len(settings.secret) < 32 or len(settings.admin_password) < 12:
        raise RuntimeError(
            "Run scripts/bootstrap.ps1 to generate session/admin credentials"
        )
    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(719101)"))
        env = db.scalar(select(Environment).order_by(Environment.created_at))
        if env is None:
            env = Environment(
                name="CUDA 12.8 · nvcc · Python 3.10",
                image=runtime.client.images.get(settings.base_image).id,
                image_version="2026.10-poc",
                description="本地 CUDA 镜像；nvcc 12.8；系统 Python + 持久化 uv venv；未预装 PyTorch",
            )
            db.add(env)
            db.flush()
        for template in db.scalars(select(Environment)):
            try:
                runtime.client.images.get(template.image).tag(f"lab-env-{template.id}", tag="pinned")
            except NotFound:
                # Existing records stay available for diagnosis and explicit reassignment.
                pass
        if (
            db.scalar(select(User).where(User.username == settings.admin_username))
            is None
        ):
            user = User(
                username=settings.admin_username,
                display_name="管理员",
                password_hash=hasher.hash(settings.admin_password),
                role="ADMIN",
                uid_hint=2000,
                default_environment_id=env.id,
                max_gpus=settings.gpu_count,
            )
            db.add(user)
            db.flush()
            db.add(
                Workspace(user_id=user.id, route_path=f"/workspace/{user.username}/")
            )
        existing = list(db.scalars(select(GpuSlot)))
        if any(
            s.gpu_index >= settings.gpu_count and s.state != "FREE" for s in existing
        ):
            raise RuntimeError(
                "Stop active GPU workloads before changing GPU count/mode"
            )
        for slot in existing:
            if slot.gpu_index >= settings.gpu_count:
                db.delete(slot)
        for index in range(settings.gpu_count):
            if db.get(GpuSlot, index) is None:
                db.add(GpuSlot(gpu_index=index))
        db.commit()


if __name__ == "__main__":
    seed()
