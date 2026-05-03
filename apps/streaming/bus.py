"""
Event bus — Phase 3.1 of the Enterprise Roadmap.

Backed by Redis Streams when REDIS_URL is reachable, falling back to a
process-local in-memory queue otherwise. The fallback is for unit tests and
single-process dev runs — it gives the same `publish(event) → consume()`
contract so call-sites don't change between environments.

Streams:
  invoices       — invoice.uploaded, invoice.processed, invoice.audited
  audit          — audit.completed, audit.failed
  cases          — case.created, case.resolved
  dlq            — dead-letter for events the consumer rejected

Consumer groups: each subscriber declares a group name so Redis tracks
acknowledgement per group, giving us at-least-once delivery semantics.

The Continuous-Auditing detectors (velocity, sudden-spike, vendor-
concentration) run as ``StreamConsumer`` instances bound to the
``invoices`` and ``audit`` streams.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from django.conf import settings

logger = logging.getLogger("finai.streaming")

# Stream + DLQ names
STREAM_INVOICES = "tadgeeg:stream:invoices"
STREAM_AUDIT    = "tadgeeg:stream:audit"
STREAM_CASES    = "tadgeeg:stream:cases"
STREAM_DLQ      = "tadgeeg:stream:dlq"

# Maximum stream length the bus retains. Older entries are trimmed lazily —
# this keeps Redis memory bounded even when the consumer falls behind.
STREAM_MAXLEN = 50_000

# Block ms when reading. Short enough that a Ctrl-C from the worker is
# responsive, long enough to avoid a busy loop.
READ_BLOCK_MS = 2_000


# ─────────────────────────────────────────────────────────────────────────────
# Event dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    type: str
    payload: dict
    organization_id: Optional[str] = None
    occurred_at: Optional[str] = None
    event_id: str = ""
    stream: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = str(uuid.uuid4())
        if not self.occurred_at:
            self.occurred_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "type":            self.type,
            "payload":         self.payload,
            "organization_id": self.organization_id,
            "occurred_at":     self.occurred_at,
            "event_id":        self.event_id,
            "stream":          self.stream,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Backend interface
# ─────────────────────────────────────────────────────────────────────────────

class _BusBackend:
    """Two implementations: RedisBackend + InMemoryBackend. Both expose the
    same publish/consume/stats surface the rest of the app calls."""
    name = "base"

    def publish(self, stream: str, event: Event) -> str:
        raise NotImplementedError

    def consume(self, streams: list[str], group: str, consumer: str,
                callback: Callable[[Event], None], *,
                stop_event: threading.Event,
                count: int = 50) -> dict:
        raise NotImplementedError

    def stats(self) -> dict:
        raise NotImplementedError

    def trim(self, stream: str, maxlen: int = STREAM_MAXLEN) -> int:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Redis Streams backend
# ─────────────────────────────────────────────────────────────────────────────

class RedisBackend(_BusBackend):
    name = "redis"

    def __init__(self, url: Optional[str] = None):
        import redis
        self.url    = url or getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        self.client = redis.Redis.from_url(self.url, decode_responses=True)

    def _ensure_group(self, stream: str, group: str) -> None:
        try:
            self.client.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:
            # BUSYGROUP — already exists, fine.
            if "BUSYGROUP" in str(exc):
                return
            raise

    def publish(self, stream: str, event: Event) -> str:
        event.stream = stream
        record = {"data": json.dumps(event.to_dict(), default=str)}
        try:
            entry_id = self.client.xadd(stream, record, maxlen=STREAM_MAXLEN, approximate=True)
            return entry_id
        except Exception as exc:
            logger.warning("[bus.redis] publish failed (%s): %s", stream, exc)
            raise

    def consume(self, streams: list[str], group: str, consumer: str,
                callback: Callable[[Event], None], *,
                stop_event: threading.Event,
                count: int = 50) -> dict:
        for s in streams:
            self._ensure_group(s, group)

        processed = 0
        failed = 0
        # Read from each stream's group queue. ">" means only new (unacked).
        while not stop_event.is_set():
            try:
                resp = self.client.xreadgroup(
                    group, consumer,
                    {s: ">" for s in streams},
                    count=count, block=READ_BLOCK_MS,
                )
            except Exception as exc:
                logger.warning("[bus.redis] xreadgroup failed: %s", exc)
                time.sleep(1)
                continue

            if not resp:
                continue

            for stream_name, entries in resp:
                for entry_id, fields in entries:
                    try:
                        ev = _event_from_record(fields, stream=stream_name)
                        callback(ev)
                        self.client.xack(stream_name, group, entry_id)
                        processed += 1
                    except Exception as exc:
                        failed += 1
                        logger.error("[bus.redis] consumer failed for %s: %s",
                                     entry_id, exc)
                        # Push to DLQ.
                        try:
                            self.client.xadd(
                                STREAM_DLQ,
                                {"data": json.dumps({
                                    "stream":    stream_name,
                                    "entry_id":  entry_id,
                                    "fields":    fields,
                                    "error":     str(exc),
                                    "group":     group,
                                    "consumer":  consumer,
                                    "failed_at": datetime.utcnow().isoformat(),
                                }, default=str)},
                                maxlen=STREAM_MAXLEN, approximate=True,
                            )
                            self.client.xack(stream_name, group, entry_id)
                        except Exception:
                            logger.exception("[bus.redis] DLQ write failed")

        return {"processed": processed, "failed": failed}

    def stats(self) -> dict:
        out = {"backend": "redis"}
        for s in (STREAM_INVOICES, STREAM_AUDIT, STREAM_CASES, STREAM_DLQ):
            try:
                info = self.client.xinfo_stream(s)
                out[s] = {"length": info.get("length", 0),
                          "groups": info.get("groups", 0)}
            except Exception:
                out[s] = {"length": 0, "groups": 0, "missing": True}
        return out

    def trim(self, stream: str, maxlen: int = STREAM_MAXLEN) -> int:
        try:
            return self.client.xtrim(stream, maxlen=maxlen, approximate=True)
        except Exception as exc:
            logger.warning("[bus.redis] trim failed: %s", exc)
            return 0


# ─────────────────────────────────────────────────────────────────────────────
# In-memory backend (tests + single-process dev)
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryBackend(_BusBackend):
    name = "memory"

    def __init__(self):
        self._streams: dict[str, deque] = defaultdict(lambda: deque(maxlen=STREAM_MAXLEN))
        self._cursors: dict[tuple[str, str], int] = defaultdict(int)
        self._lock = threading.Lock()

    def publish(self, stream: str, event: Event) -> str:
        event.stream = stream
        with self._lock:
            self._streams[stream].append(event)
        return f"mem-{event.event_id}"

    def consume(self, streams: list[str], group: str, consumer: str,
                callback: Callable[[Event], None], *,
                stop_event: threading.Event,
                count: int = 50) -> dict:
        processed = 0
        failed = 0
        while not stop_event.is_set():
            had_work = False
            for s in streams:
                with self._lock:
                    cursor_key = (s, group)
                    cursor = self._cursors[cursor_key]
                    pending = list(self._streams[s])[cursor:cursor + count]
                    if pending:
                        self._cursors[cursor_key] = cursor + len(pending)
                        had_work = True
                for ev in pending:
                    try:
                        callback(ev)
                        processed += 1
                    except Exception as exc:
                        failed += 1
                        logger.error("[bus.memory] consumer failed: %s", exc)
            if not had_work:
                # No work — yield briefly so a stop-event check can run.
                if stop_event.wait(timeout=0.05):
                    break
        return {"processed": processed, "failed": failed}

    def stats(self) -> dict:
        with self._lock:
            return {
                "backend": "memory",
                **{s: {"length": len(self._streams[s])}
                   for s in (STREAM_INVOICES, STREAM_AUDIT, STREAM_CASES, STREAM_DLQ)},
            }

    def trim(self, stream: str, maxlen: int = STREAM_MAXLEN) -> int:
        with self._lock:
            d = self._streams[stream]
            removed = max(0, len(d) - maxlen)
            for _ in range(removed):
                d.popleft()
        return removed

    # Test helper — drain the stream synchronously so unit tests don't need threads.
    def drain(self, streams: list[str], group: str,
              callback: Callable[[Event], None]) -> dict:
        stop = threading.Event()
        stop.set()  # one pass, then exit
        return self.consume(streams, group, "test", callback,
                            stop_event=threading.Event(), count=10000) \
            if False else self._drain_once(streams, group, callback)

    def _drain_once(self, streams, group, callback) -> dict:
        processed = 0
        failed = 0
        for s in streams:
            cursor_key = (s, group)
            with self._lock:
                cursor = self._cursors[cursor_key]
                pending = list(self._streams[s])[cursor:]
                self._cursors[cursor_key] = cursor + len(pending)
            for ev in pending:
                try:
                    callback(ev)
                    processed += 1
                except Exception as exc:
                    failed += 1
                    logger.error("[bus.memory] consumer failed: %s", exc)
        return {"processed": processed, "failed": failed}


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

_backend: Optional[_BusBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> _BusBackend:
    """Return the active backend, choosing Redis when reachable."""
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        # Honour an explicit settings override first (used by tests).
        forced = getattr(settings, "STREAMING_BUS_BACKEND", "")
        if forced == "memory":
            _backend = InMemoryBackend()
            return _backend
        try:
            backend = RedisBackend()
            backend.client.ping()
            _backend = backend
        except Exception as exc:
            logger.info(
                "[bus] Redis unreachable (%s) — falling back to in-memory bus", exc,
            )
            _backend = InMemoryBackend()
        return _backend


def reset_backend() -> None:
    """Test helper — drop the singleton so a new backend is picked next time."""
    global _backend
    with _backend_lock:
        _backend = None


def _event_from_record(fields: dict, stream: str = "") -> Event:
    raw = fields.get("data") or "{}"
    data = json.loads(raw) if isinstance(raw, str) else raw
    ev = Event(
        type=data.get("type", ""),
        payload=data.get("payload") or {},
        organization_id=data.get("organization_id"),
        occurred_at=data.get("occurred_at"),
        event_id=data.get("event_id") or "",
        stream=data.get("stream") or stream,
    )
    return ev


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def publish(event_type: str, payload: dict, *,
            stream: str = STREAM_INVOICES,
            organization_id: Optional[str] = None) -> str:
    """Convenience wrapper: build an Event and write it to ``stream``.

    Returns the backend's entry id (a Redis "1234567890-0" string when
    backed by Redis, or "mem-<uuid>" in-memory)."""
    ev = Event(
        type=event_type,
        payload=payload or {},
        organization_id=str(organization_id) if organization_id is not None else None,
    )
    try:
        return get_backend().publish(stream, ev)
    except Exception as exc:
        logger.warning("[bus.publish] %s on %s failed: %s", event_type, stream, exc)
        return ""


def stats() -> dict:
    try:
        return get_backend().stats()
    except Exception as exc:
        return {"backend": "error", "error": str(exc)}
