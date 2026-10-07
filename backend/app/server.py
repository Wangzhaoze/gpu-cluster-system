from pathlib import Path

from fastapi import Depends
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from .auth import current_user
from .config import settings
from .db import get_db
from .main import app, accessible_resource
from .models import User


@app.get("/api/jobs/{resource_id}/logs/download")
def download_job_log(
    resource_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    resource = accessible_resource(db, user, resource_id, "train")
    path = Path(settings.runtime_root, "logs/jobs", f"{resource.id}.log")
    if not path.exists():
        return PlainTextResponse(
            "等待容器启动…\n",
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="training-{resource.id}.txt"'
            },
        )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"training-{resource.id}.txt",
        content_disposition_type="attachment",
    )
