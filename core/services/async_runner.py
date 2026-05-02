"""
Lightweight background-thread runner — used when Celery/Redis are unavailable.

This is *not* a Celery replacement. It's a pragmatic fallback so multi-record
uploads don't block the HTTP request for 30+ seconds when the worker is down.
The thread runs the work after the response is sent. If the process restarts
mid-job the work is lost — that's the explicit trade-off.

Usage:
    from core.services.async_runner import run_in_background
    run_in_background(process_records, records, base_doc, ...)

Decision tree (chosen by the upload pipeline):
    1. Celery broker reachable          → use Celery (`task.delay(...)`).
    2. Process count of records ≤ N     → run inline (synchronous, fast).
    3. Records > N AND broker down     → background thread (this module).
    4. Records > N AND broker reachable → Celery wins.
"""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Callable

logger = logging.getLogger("finai")


def run_in_background(target: Callable, *args, **kwargs) -> threading.Thread:
    """Spawn a daemon thread to run `target(*args, **kwargs)`.

    - daemon=True so the thread doesn't block process shutdown.
    - All exceptions are caught and logged; the caller's request flow is
      never affected by failures inside the background thread.
    """
    def _wrapper():
        try:
            target(*args, **kwargs)
        except Exception:
            logger.error(
                "[async_runner] background task %s failed:\n%s",
                getattr(target, "__name__", repr(target)),
                traceback.format_exc(),
            )

    t = threading.Thread(target=_wrapper, daemon=True, name=f"bg-{getattr(target, '__name__', 'task')}")
    t.start()
    logger.info("[async_runner] spawned background thread for %s", getattr(target, "__name__", "task"))
    return t


def should_use_background(record_count: int, sync_threshold: int = 50) -> bool:
    """Decide whether a multi-record job should go to a background thread.

    True when records exceed the inline threshold AND the Celery broker is
    NOT reachable (so the broker decision tree's option #3 applies).
    """
    if record_count <= sync_threshold:
        return False
    try:
        from apps.documents.signals import _broker_reachable
        return not _broker_reachable()
    except Exception:
        return True  # broker probe failed → assume not reachable
