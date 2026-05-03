"""
Stream consumer / worker — Phase 3.1.

Reads ``invoice.uploaded`` / ``invoice.audited`` events from the bus, runs the
window detectors against each, persists any AnomalyHit, records latency in
StreamProcessingLog, and re-publishes a ``audit.anomaly_detected`` event so
Phase 3.2 alert channels can fan out.

The worker is intentionally framework-light: no Celery dependency, no
asyncio. It runs as either:

  • a long-lived management command (``manage.py run_stream_worker``)
  • a one-shot dispatch in tests (``run_once(events)``)

The Redis-backed consumer is at-least-once via XACK; failures land in the
DLQ stream where the dashboard can show them.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Iterable, Optional

from django.utils import timezone

from apps.streaming import bus
from apps.streaming import detectors as det

logger = logging.getLogger("finai.streaming")


# ─────────────────────────────────────────────────────────────────────────────
# Per-event handler
# ─────────────────────────────────────────────────────────────────────────────

def handle_event(event: bus.Event,
                 detectors: Optional[Iterable[det.BaseDetector]] = None) -> dict:
    """Run all detectors against ``event``, persist hits, log latency.

    Returns a dict with keys ``processed`` (always 1), ``hits`` (count of
    AnomalyHit rows created), ``latency_ms``, and ``ok`` for the consumer
    metrics.
    """
    started = time.monotonic()
    log_kwargs = {
        "event_type": event.type,
        "stream":     event.stream or "",
        "ok":         True,
    }
    hit_count = 0

    try:
        hits = det.evaluate_all(event, detectors)
        for hit in hits:
            _persist_hit(hit)
            hit_count += 1
            # Re-publish so Phase 3.2 alert channels (and any other downstream
            # subscribers) see the trigger immediately.
            bus.publish(
                "audit.anomaly_detected",
                payload=hit.to_dict(),
                stream=bus.STREAM_AUDIT,
                organization_id=hit.organization_id,
            )
    except Exception as exc:
        logger.exception("[worker] event handler crashed: %s", exc)
        log_kwargs["ok"] = False
        log_kwargs["error_message"] = str(exc)[:240]

    latency_ms = int((time.monotonic() - started) * 1000)
    log_kwargs["latency_ms"] = latency_ms

    try:
        from apps.streaming.models import StreamProcessingLog
        StreamProcessingLog.objects.create(**log_kwargs)
    except Exception as exc:
        logger.warning("[worker] log row write failed: %s", exc)

    return {
        "processed":  1,
        "hits":       hit_count,
        "latency_ms": latency_ms,
        "ok":         log_kwargs["ok"],
    }


def _persist_hit(hit: det.AnomalyHit) -> None:
    """Save the hit to the DB and dispatch to alert channels.

    Both steps are best-effort — failures are logged but never abort the
    worker. Alerting is a downstream concern; the canonical record is the
    AnomalyHit row, which the live-ops dashboard always reads regardless
    of whether channel delivery succeeded.
    """
    from apps.streaming.models import AnomalyHit as Hit
    saved = None
    try:
        saved = Hit.objects.create(
            organization_id=hit.organization_id,
            detector=hit.detector,
            severity=hit.severity,
            invoice_id=hit.invoice_id,
            vendor_name=hit.vendor_name,
            explanation=hit.explanation,
            details=hit.details,
            occurred_at=timezone.now(),
        )
    except Exception as exc:
        logger.warning("[worker] AnomalyHit persist failed: %s", exc)

    # Phase 3.2 — fan out to alert channels.
    if saved is not None:
        try:
            from apps.alerts.dispatcher import dispatch_for_anomaly
            dispatch_for_anomaly(saved)
        except Exception as exc:
            logger.warning("[worker] alert dispatch failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Test / dev helper — synchronous one-shot
# ─────────────────────────────────────────────────────────────────────────────

def run_once(events: Iterable[bus.Event],
             detectors: Optional[Iterable[det.BaseDetector]] = None) -> dict:
    """Run the handler against an in-memory iterable. Used by tests."""
    summary = {"processed": 0, "hits": 0, "failed": 0}
    for ev in events:
        out = handle_event(ev, detectors=detectors)
        summary["processed"] += out["processed"]
        summary["hits"]      += out["hits"]
        if not out["ok"]:
            summary["failed"] += 1
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Long-lived consumer (used by the management command)
# ─────────────────────────────────────────────────────────────────────────────

def run_consumer(*, group: str = "tadgeeg-anomaly", consumer: str = "worker-1",
                 stop_event: Optional[threading.Event] = None,
                 max_seconds: Optional[int] = None) -> dict:
    """Block in the consumer loop until ``stop_event`` is set or
    ``max_seconds`` elapses."""
    stop_event = stop_event or threading.Event()
    streams = [bus.STREAM_INVOICES, bus.STREAM_AUDIT]
    started = time.monotonic()

    if max_seconds is not None:
        # Helper thread to flip stop_event when the deadline hits.
        def _deadline():
            while not stop_event.wait(timeout=0.5):
                if time.monotonic() - started >= max_seconds:
                    stop_event.set()
                    return
        threading.Thread(target=_deadline, daemon=True).start()

    backend = bus.get_backend()
    logger.info("[worker] consumer starting (backend=%s, group=%s, streams=%s)",
                backend.name, group, streams)

    summary = backend.consume(
        streams=streams, group=group, consumer=consumer,
        callback=lambda ev: handle_event(ev),
        stop_event=stop_event,
        count=50,
    )
    summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
    summary["backend"] = backend.name
    logger.info("[worker] consumer stopped: %s", summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Metrics aggregator (used by the live-ops dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def metrics(window_minutes: int = 30) -> dict:
    """Return throughput / latency / error stats for the last window_minutes."""
    from datetime import timedelta
    from django.db.models import Avg, Count, Max
    from apps.streaming.models import StreamProcessingLog, AnomalyHit

    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    recent = StreamProcessingLog.objects.filter(processed_at__gte=cutoff)

    total = recent.count()
    failed = recent.filter(ok=False).count()
    avg_latency = recent.aggregate(a=Avg("latency_ms"))["a"] or 0
    max_latency = recent.aggregate(m=Max("latency_ms"))["m"] or 0

    # p95 — naive implementation: sort recent latencies in Python. Fine for
    # ≤ 50 k rows; if traffic is bigger, replace with PostgreSQL's
    # percentile_cont aggregate.
    latencies = sorted(recent.values_list("latency_ms", flat=True))
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0

    by_event = list(
        recent.values("event_type")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    anomaly_count = AnomalyHit.objects.filter(occurred_at__gte=cutoff).count()
    bus_stats = bus.stats()

    return {
        "window_minutes":    window_minutes,
        "events_processed":  total,
        "events_failed":     failed,
        "error_rate_pct":    round((failed / total * 100), 2) if total else 0,
        "throughput_per_min": round(total / window_minutes, 2) if window_minutes else 0,
        "avg_latency_ms":    round(avg_latency, 1),
        "p95_latency_ms":    p95,
        "max_latency_ms":    max_latency,
        "by_event_type":     by_event,
        "anomaly_count":     anomaly_count,
        "bus":               bus_stats,
    }
