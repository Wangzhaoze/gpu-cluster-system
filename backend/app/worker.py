import logging
from pathlib import Path
import signal
import threading
import time
from sqlalchemy import text
from sqlalchemy.orm import Session
from .config import settings
from .db import engine
from .models import now
from .scheduler import get_scheduler
from .retention import prune_workload_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
stop = threading.Event()


def run():
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    scheduler = get_scheduler()
    next_cleanup = 0.0
    while not stop.is_set():
        try:
            with engine.connect() as connection:
                # Session lock survives commits in a tick; extra workers cannot double allocate.
                locked = connection.execute(
                    text("SELECT pg_try_advisory_lock(719102)")
                ).scalar()
                connection.commit()
                if locked:
                    try:
                        with Session(bind=connection, expire_on_commit=False) as db:
                            scheduler.tick(db)
                            if time.monotonic() >= next_cleanup:
                                prune_workload_history(db)
                                next_cleanup = time.monotonic() + 3600
                        path = Path(settings.runtime_root, "logs/scheduler-heartbeat")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(now().isoformat())
                    finally:
                        connection.rollback()
                        connection.execute(text("SELECT pg_advisory_unlock(719102)"))
                        connection.commit()
        except Exception:
            logging.exception("Scheduler tick failed; retrying")
        stop.wait(1)


if __name__ == "__main__":
    run()
