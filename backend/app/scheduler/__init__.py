from .mock_docker import MockDockerScheduler
from .local_gpu_docker import LocalGpuDockerScheduler
from .slurm import SlurmScheduler
from ..config import settings


def get_scheduler():
    if settings.scheduler_backend == "mock-docker":
        return MockDockerScheduler()
    if settings.scheduler_backend == "local-gpu-docker":
        return LocalGpuDockerScheduler()
    if settings.scheduler_backend == "slurm":
        return SlurmScheduler()
    raise RuntimeError(f"Unknown scheduler: {settings.scheduler_backend}")
