"""Native host editor status; OS lifecycle is owned by systemd, not the scheduler."""
import json
from urllib.error import URLError
from urllib.request import urlopen
from .config import settings


def host_workspace() -> dict:
    ready = False
    error = "宿主机编辑器尚未启用"
    if settings.host_editor_enabled:
        try:
            with urlopen("http://host-editor-proxy:8080/healthz", timeout=1) as response:
                ready = response.status == 200 and json.load(response).get("status") == "ok"
            error = "" if ready else "宿主机编辑器暂不可用"
        except (OSError, URLError, ValueError):
            error = "宿主机编辑器暂不可用，请检查 systemd 服务"
    return {
        "mode": "host", "state": "RUNNING" if ready else "STOPPED",
        "route_path": "/host/", "container_id": None,
        "host_user": settings.host_editor_user, "host_home": settings.host_editor_home,
        "host_uid": settings.host_editor_uid, "host_gid": settings.host_editor_gid,
        "host_python": settings.host_editor_python, "error_message": error,
    }
