from pathlib import Path
from typing import Protocol
from docker.types import Mount
from .config import settings


class StorageProvider(Protocol):
    def provision(self, username: str) -> None: ...
    def mounts(self, username: str) -> list[Mount]: ...
    def usage(self, username: str) -> dict[str, int]: ...


class WindowsDockerStorage:
    """Host paths are configuration, never user input; Linux venv lives in a volume."""

    def paths(self, username: str) -> dict[str, str]:
        return {
            "workspace": f"users/{username}/workspace",
            "results": f"results/{username}",
            "scratch": f"scratch/{username}",
        }

    def provision(self, username: str) -> None:
        for relative in self.paths(username).values():
            Path(settings.runtime_root, relative).mkdir(parents=True, exist_ok=True)

    def mounts(self, username: str) -> list[Mount]:
        root = settings.host_root.replace("\\", "/").rstrip("/")
        mounts = [
            Mount(f"/{target}", f"{root}/{relative}", type="bind")
            for target, relative in self.paths(username).items()
        ]
        mounts.extend(
            [
                Mount(
                    "/datasets", settings.dataset_host_path, type="bind", read_only=True
                ),
                Mount("/opt/user-env", f"lab_pyenv_{username}", type="volume"),
            ]
        )
        return mounts

    def usage(self, username: str) -> dict[str, int]:
        # Do not follow links into datasets or escape a user's storage tree.
        result = {}
        for kind, relative in self.paths(username).items():
            total = 0
            for path in Path(settings.runtime_root, relative).rglob("*"):
                try:
                    if not path.is_symlink() and path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
            result[kind] = total
        return result

    def save_log(self, resource_id: str, content: bytes) -> str:
        path = Path(settings.runtime_root, "logs/jobs", f"{resource_id}.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(content)
        temp.replace(path)
        return str(path)


storage = WindowsDockerStorage()
