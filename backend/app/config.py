import os
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class Settings:
    host_root: str = os.getenv("LAB_HOST_ROOT", "/tmp/lab")
    runtime_root: str = os.getenv("LAB_RUNTIME_ROOT", "/runtime")
    dataset_host_path: str = os.getenv("DATASET_HOST_PATH", "/tmp/lab/datasets")
    network: str = "lab-net"
    project: str = "gpu-lab-poc"
    base_image: str = os.getenv("LAB_BASE_IMAGE", "lab-base-dev:2026.10-poc")
    torch_image: str = os.getenv("LAB_TORCH_IMAGE", "lab-torch-dev:2.7.1-cu128")
    shm_size: str = os.getenv("LAB_SHM_SIZE", "2g")
    scheduler_backend: str = os.getenv("SCHEDULER_BACKEND", "mock-docker")
    secret: str = os.getenv("SESSION_SECRET", "test-only-secret")
    secure_cookie: bool = os.getenv("SESSION_SECURE_COOKIE", "false").lower() == "true"
    admin_username: str = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("INITIAL_ADMIN_PASSWORD", "")

    @property
    def gpu_count(self) -> int:
        key = (
            "LOCAL_GPU_COUNT"
            if self.scheduler_backend == "local-gpu-docker"
            else "MOCK_GPU_COUNT"
        )
        return int(os.getenv(key, "1" if key == "LOCAL_GPU_COUNT" else "5"))

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL") or (
            "postgresql+psycopg://"
            + quote(os.getenv("POSTGRES_USER", "gpu_lab"), safe="")
            + ":"
            + quote(os.getenv("POSTGRES_PASSWORD", ""), safe="")
            + "@postgres/"
            + quote(os.getenv("POSTGRES_DB", "gpu_lab"), safe="")
        )


settings = Settings()
