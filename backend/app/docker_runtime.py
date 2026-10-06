from functools import cached_property
import docker
from docker.errors import NotFound
from docker.types import DeviceRequest
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .models import EnvVar, Environment, User, Workload
from .storage import storage


class DockerRuntime:
    @cached_property
    def client(self):
        return docker.from_env(timeout=45)

    def provision(self, user: User):
        storage.provision(user.username)
        self.client.volumes.create(
            f"lab_pyenv_{user.username}",
            labels={
                "lab.managed": "true",
                "lab.project": settings.project,
                "lab.user": user.username,
            },
        )

    def name(self, kind: str, resource_id: str) -> str:
        return f"lab-{kind}-{resource_id}"

    def remove_python_volume(self, user: User):
        try:
            volume = self.client.volumes.get(f"lab_pyenv_{user.username}")
        except NotFound:
            return
        if (volume.attrs.get("Labels") or {}).get("lab.project") != settings.project:
            raise RuntimeError("Python volume belongs to another project")
        volume.remove(force=False)

    def get(self, name: str):
        try:
            container = self.client.containers.get(name)
            if container.labels.get("lab.project") != settings.project:
                raise RuntimeError(
                    f"Container name occupied by another project: {name}"
                )
            return container
        except NotFound:
            return None

    def managed(self):
        return self.client.containers.list(
            all=True,
            filters={"label": ["lab.managed=true", f"lab.project={settings.project}"]},
        )

    def env(
        self,
        db: Session,
        user: User,
        overrides: dict[str, str],
        gpus: list[int],
        real_gpu: bool,
    ) -> dict[str, str]:
        result = {
            "HF_HOME": "/scratch/hf",
            "TORCH_HOME": "/scratch/torch",
            "PIP_CACHE_DIR": "/scratch/pip",
            "PYTHONUNBUFFERED": "1",
        }
        for scope in ("global", user.id):
            for variable in db.scalars(
                select(EnvVar).where(EnvVar.scope == scope, EnvVar.enabled.is_(True))
            ):
                result[variable.key] = variable.value
        result.update(overrides)
        result.update(
            {
                "LAB_USERNAME": user.username,
                "LAB_UID": str(user.uid_hint),
                "LAB_GID": str(user.uid_hint),
                "VIRTUAL_ENV": "/opt/user-env/venv",
                "LAB_ASSIGNED_GPUS": ",".join(map(str, gpus)),
                "CUDA_VISIBLE_DEVICES": ",".join(
                    map(str, range(len(gpus)) if real_gpu else gpus)
                ),
                "NVIDIA_VISIBLE_DEVICES": ",".join(map(str, gpus))
                if real_gpu and gpus
                else "void",
            }
        )
        return result

    def routing(self, name: str, path: str) -> dict[str, str]:
        prefix = path.rstrip("/")
        return {
            "traefik.enable": "true",
            "traefik.docker.network": settings.network,
            f"traefik.http.routers.{name}.rule": f"PathPrefix(`{path}`)",
            f"traefik.http.routers.{name}.priority": "200",
            f"traefik.http.routers.{name}.entrypoints": "web",
            f"traefik.http.routers.{name}.middlewares": f"lab-auth@file,{name}-strip",
            f"traefik.http.middlewares.{name}-strip.stripprefix.prefixes": prefix,
            f"traefik.http.services.{name}.loadbalancer.server.port": "8080",
        }

    def create(
        self,
        db: Session,
        user: User,
        env: Environment,
        kind: str,
        resource_id: str,
        gpus: list[int],
        cpus: int,
        ram_mb: int,
        workdir: str = "/workspace",
        command: str = "",
        overrides: dict | None = None,
        route: str | None = None,
        output_name: str = "run",
        real_gpu: bool = False,
    ):
        name = self.name(kind, resource_id)
        existing = self.get(name)
        if existing:
            return existing  # deterministic name closes crash-after-create window
        self.provision(user)
        self.client.images.get(env.image)  # fail clearly; never implicitly pull
        labels = {
            "lab.managed": "true",
            "lab.project": settings.project,
            "lab.kind": kind,
            "lab.user": user.username,
            "lab.job_id": resource_id,
            "lab.assigned_gpus": ",".join(map(str, gpus)),
        }
        environment = self.env(db, user, overrides or {}, gpus, real_gpu)
        if route:
            labels.update(self.routing(name, route))
            process = [
                "code-server",
                "--auth",
                "none",
                "--bind-addr",
                "0.0.0.0:8080",
                "--disable-telemetry",
                "--abs-proxy-base-path",
                route.rstrip("/"),
                "--user-data-dir",
                f"/workspace/.lab/code-server/{kind}-{resource_id}",
                "--extensions-dir",
                "/workspace/.lab/extensions",
                "/workspace",
            ]
        else:
            environment["LAB_RESULT_DIR"] = f"/results/{output_name}/{resource_id}"
            process = ["bash", "-c", 'mkdir -p "$LAB_RESULT_DIR"; ' + command]
        kwargs = {}
        if real_gpu and gpus:
            kwargs["device_requests"] = [
                DeviceRequest(device_ids=list(map(str, gpus)), capabilities=[["gpu"]])
            ]
        return self.client.containers.create(
            env.image,
            process,
            name=name,
            environment=environment,
            labels=labels,
            network=settings.network,
            mounts=storage.mounts(user.username),
            working_dir=workdir,
            nano_cpus=cpus * 1_000_000_000,
            mem_limit=f"{ram_mb}m",
            shm_size=settings.shm_size,
            pids_limit=1024,
            privileged=False,
            restart_policy={"Name": "no"},
            **kwargs,
        )

    def capture_log(self, workload: Workload, container):
        workload.log_path = storage.save_log(
            workload.id, container.logs(stdout=True, stderr=True, timestamps=True)
        )

    def remove(self, container):
        container.reload()
        if container.status == "running":
            container.stop(timeout=3)
        container.remove(force=True)


runtime = DockerRuntime()
