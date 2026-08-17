import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.scheduler as scheduler  # noqa: E402
from backend.scheduler import JobRefreshScheduler  # noqa: E402


def test_build_default_scheduler_returns_none_when_disabled():
    scheduler.AUTO_REFRESH_JOBS = False
    assert scheduler.build_default_scheduler(lambda: None) is None


def test_build_default_scheduler_returns_instance_when_enabled():
    scheduler.AUTO_REFRESH_JOBS = True
    sched = scheduler.build_default_scheduler(lambda: None)
    assert sched is not None
    scheduler.AUTO_REFRESH_JOBS = False  # reset for other tests


def test_refresh_fn_called_on_schedule():
    calls = []
    s = JobRefreshScheduler(lambda: calls.append(time.time()), interval_hours=1)
    s._interval_seconds = 0.3  # override the safety floor for a fast test
    s.start()
    time.sleep(1.1)
    s.stop()
    assert len(calls) >= 1


def test_failing_refresh_does_not_crash_thread():
    def failing():
        raise RuntimeError("simulated network failure")

    s = JobRefreshScheduler(failing, interval_hours=1)
    s._interval_seconds = 0.3
    s.start()
    time.sleep(0.6)
    alive = s._thread.is_alive()
    s.stop()
    assert alive


def test_stop_prevents_further_calls():
    calls = []
    s = JobRefreshScheduler(lambda: calls.append(1), interval_hours=1)
    s._interval_seconds = 0.3
    s.start()
    time.sleep(0.5)
    s.stop()
    count_after_stop = len(calls)
    time.sleep(0.5)
    assert len(calls) == count_after_stop


def test_safety_floor_clamps_tiny_intervals():
    s = JobRefreshScheduler(lambda: None, interval_hours=0.0001)
    assert s._interval_seconds == 36.0  # floor is 0.01h = 36s
