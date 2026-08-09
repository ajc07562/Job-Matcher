"""
Optional background thread that periodically re-runs ingestion so the job corpus
stays current without you remembering to re-run ingest.py by hand. Off by default
(AUTO_REFRESH_JOBS=false) since it's an outbound-network side effect on a timer —
turn it on explicitly in .env if you want it.

Kept deliberately simple: a daemon thread with a sleep loop, not a task queue or
cron library. This is a single-process app; a heavier scheduler (Celery, APScheduler)
would be the right call if this ever needs to run across multiple worker processes.
"""
import threading
import time
import traceback
from typing import Callable, Optional

from backend.config import AUTO_REFRESH_JOBS, REFRESH_INTERVAL_HOURS


class JobRefreshScheduler:
    def __init__(self, refresh_fn: Callable[[], None], interval_hours: float):
        self._refresh_fn = refresh_fn
        self._interval_seconds = max(interval_hours, 0.01) * 3600
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return  # already running
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="job-refresh-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            # Wait first: the app already loads jobs (fresh or sample) on startup,
            # so the first refresh should happen a full interval later, not immediately.
            if self._stop_event.wait(timeout=self._interval_seconds):
                break
            try:
                print(f"[scheduler] Running scheduled job refresh...")
                self._refresh_fn()
                print(f"[scheduler] Refresh complete.")
            except Exception:
                # A failed refresh should never crash the running app — log and retry next cycle.
                print(f"[scheduler] Refresh failed:")
                traceback.print_exc()


def build_default_scheduler(refresh_fn: Callable[[], None]) -> Optional[JobRefreshScheduler]:
    """Returns a configured-but-not-started scheduler, or None if auto-refresh is disabled."""
    if not AUTO_REFRESH_JOBS:
        return None
    return JobRefreshScheduler(refresh_fn, REFRESH_INTERVAL_HOURS)