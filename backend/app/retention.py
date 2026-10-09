"""Remove seven-day-old terminal task history, never student data."""
from datetime import timedelta
import logging
from pathlib import Path

from sqlalchemy import func, select

from .config import settings
from .docker_runtime import runtime
from .models import Workload, now
from .scheduler.base import TERMINAL

logger = logging.getLogger(__name__)


def prune_workload_history(db, cutoff=None):
    cutoff = cutoff or now() - timedelta(days=7)
    expired = list(db.scalars(select(Workload).where(
        Workload.status.in_(TERMINAL),
        func.coalesce(Workload.finished_at, Workload.created_at) < cutoff)))
    removed = 0
    for item in expired:
        try:
            container = runtime.get(runtime.name(item.kind, item.id))
            if container:
                if container.status not in {"exited", "dead", "created"}:
                    continue
                if container.labels.get("lab.job_id") != item.id or container.labels.get("lab.project") != settings.project:
                    logger.warning("Skip mismatched terminal container for %s", item.id)
                    continue
                runtime.remove(container)
            # Do not use log_path: it can contain a historical host path.
            if Path(item.id).name != item.id:
                raise ValueError("Invalid task ID in retention")
            Path(settings.runtime_root, "logs/jobs", f"{item.id}.log").unlink(missing_ok=True)
            db.delete(item)
            db.commit()
            removed += 1
        except Exception:
            db.rollback()
            logger.exception("History cleanup failed for %s; record retained", item.id)
    if removed:
        logger.info("Removed %s terminal task records older than seven days", removed)
    return removed
