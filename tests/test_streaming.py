"""
Tests for Phase 3.1 — Continuous Auditing.

Covers:
  • In-memory bus: publish + drain returns the same events.
  • VelocityDetector fires when vendor exceeds threshold in window.
  • SuddenSpikeDetector fires when amount > μ + kσ of vendor history.
  • VendorConcentrationDetector fires when vendor crosses % threshold.
  • Worker.handle_event persists AnomalyHit and StreamProcessingLog rows.
  • Detectors silently skip events with missing fields.
  • metrics() aggregates throughput / latency / errors correctly.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.authentication.models import Organization, User


@pytest.fixture(autouse=True)
def _force_memory_bus(settings):
    """Tests run against the in-memory bus to avoid a Redis dependency."""
    settings.STREAMING_BUS_BACKEND = "memory"
    from apps.streaming import bus
    bus.reset_backend()


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Streaming Test Org")


@pytest.fixture
def user(db, org):
    return User.objects.create_user(
        email="stream@test.local", full_name="Stream Tester",
        password="x", organization=org, role=User.Role.SENIOR_AUDITOR,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Bus
# ─────────────────────────────────────────────────────────────────────────────

def test_in_memory_bus_publish_and_drain(db, org):
    from apps.streaming import bus

    bus.publish("invoice.uploaded", payload={"invoice_id": "x"},
                stream=bus.STREAM_INVOICES, organization_id=str(org.id))
    bus.publish("invoice.uploaded", payload={"invoice_id": "y"},
                stream=bus.STREAM_INVOICES, organization_id=str(org.id))

    backend = bus.get_backend()
    assert backend.name == "memory"

    seen = []
    backend.drain([bus.STREAM_INVOICES], "test-group", lambda ev: seen.append(ev))
    assert len(seen) == 2
    ids = {ev.payload["invoice_id"] for ev in seen}
    assert ids == {"x", "y"}


def test_bus_stats_reports_lengths(db):
    from apps.streaming import bus
    bus.publish("invoice.uploaded", payload={"k": 1})
    s = bus.stats()
    assert s["backend"] == "memory"
    assert s[bus.STREAM_INVOICES]["length"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Detectors
# ─────────────────────────────────────────────────────────────────────────────

def _seed_invoices(org, user, *, vendor: str, count: int,
                   amount: float = 1000, seconds_apart: int = 60):
    """Create N invoices for a vendor — used to set up window-detector inputs."""
    from apps.invoices.models import Invoice
    now = timezone.now()
    out = []
    for i in range(count):
        inv = Invoice.objects.create(
            organization=org, uploaded_by=user,
            invoice_number=f"VEL-{vendor}-{i}",
            vendor_name=vendor, total_amount=Decimal(str(amount)),
            currency="SAR",
            original_filename=f"v{i}.pdf",
        )
        # Bypass auto_now_add so we can simulate a tight window.
        Invoice.objects.filter(pk=inv.pk).update(
            created_at=now - timedelta(seconds=(count - i) * seconds_apart),
        )
        inv.refresh_from_db()
        out.append(inv)
    return out


def test_velocity_detector_fires_above_threshold(db, org, user):
    from apps.streaming import bus
    from apps.streaming.detectors import VelocityDetector

    _seed_invoices(org, user, vendor="FastVendor", count=12,
                   seconds_apart=30)  # 12 invoices in 6 minutes

    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "x", "vendor_name": "FastVendor",
                 "total_amount": 1000},
        organization_id=str(org.id),
    )

    hit = VelocityDetector(threshold=10, window_minutes=60).evaluate(ev)
    assert hit is not None
    assert hit.detector == "velocity"
    assert hit.vendor_name == "FastVendor"
    assert "12" in hit.explanation or "11" in hit.explanation


def test_velocity_detector_silent_below_threshold(db, org, user):
    from apps.streaming import bus
    from apps.streaming.detectors import VelocityDetector

    _seed_invoices(org, user, vendor="SlowVendor", count=3, seconds_apart=300)
    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "x", "vendor_name": "SlowVendor"},
        organization_id=str(org.id),
    )
    hit = VelocityDetector(threshold=10, window_minutes=60).evaluate(ev)
    assert hit is None


def test_sudden_spike_detector_fires_on_outlier(db, org, user):
    from apps.streaming import bus
    from apps.streaming.detectors import SuddenSpikeDetector
    from apps.invoices.models import Invoice
    from decimal import Decimal

    # Vendor "SpikeCo" historical: 10 invoices with mean ≈ 1000 and low std.
    # We need *some* variance for the z-score to be defined — a perfectly
    # constant history produces std=0 and no detector can fire on it.
    now = timezone.now()
    for i, amount in enumerate([900, 950, 1000, 1050, 1100, 980, 1020, 990, 1010, 1005]):
        inv = Invoice.objects.create(
            organization=org, uploaded_by=user,
            invoice_number=f"SPIKE-{i}",
            vendor_name="SpikeCo",
            total_amount=Decimal(str(amount)),
            currency="SAR",
            original_filename=f"s{i}.pdf",
        )
        Invoice.objects.filter(pk=inv.pk).update(
            created_at=now - timedelta(days=15 - i),
        )

    # New invoice 100x the historical mean → far beyond 3σ.
    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "spike-1", "vendor_name": "SpikeCo",
                 "total_amount": 100000},
        organization_id=str(org.id),
    )
    hit = SuddenSpikeDetector(sigma=3.0, lookback_days=30, min_history=5).evaluate(ev)
    assert hit is not None
    assert "σ" in hit.explanation
    assert hit.details["zscore"] > 3.0


def test_sudden_spike_skips_when_history_is_thin(db, org, user):
    from apps.streaming import bus
    from apps.streaming.detectors import SuddenSpikeDetector
    _seed_invoices(org, user, vendor="ThinVendor", count=2, amount=1000)
    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "x", "vendor_name": "ThinVendor",
                 "total_amount": 100000},
        organization_id=str(org.id),
    )
    assert SuddenSpikeDetector(min_history=5).evaluate(ev) is None


def test_vendor_concentration_detector_fires_when_dominant(db, org, user):
    from apps.streaming import bus
    from apps.streaming.detectors import VendorConcentrationDetector

    _seed_invoices(org, user, vendor="DominantCo", count=15, amount=10000)
    _seed_invoices(org, user, vendor="OtherCo",   count=5,  amount=500)

    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "d-1", "vendor_name": "DominantCo"},
        organization_id=str(org.id),
    )
    hit = VendorConcentrationDetector(threshold_pct=30.0).evaluate(ev)
    assert hit is not None
    assert hit.details["vendor_share_pct"] > 30


# ─────────────────────────────────────────────────────────────────────────────
# 3. Worker
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_handle_event_persists_hits_and_log(db, org, user):
    from apps.streaming import bus, worker
    from apps.streaming.models import AnomalyHit, StreamProcessingLog

    _seed_invoices(org, user, vendor="VelocityCo", count=15, seconds_apart=30)
    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "v-1", "vendor_name": "VelocityCo",
                 "total_amount": 1000},
        organization_id=str(org.id),
    )
    out = worker.handle_event(ev)

    assert out["processed"] == 1
    assert out["ok"] is True
    assert out["hits"] >= 1   # velocity will fire
    assert AnomalyHit.objects.filter(organization=org, detector="velocity").exists()
    assert StreamProcessingLog.objects.filter(event_type="invoice.uploaded").exists()


def test_worker_skips_events_without_org_id(db):
    from apps.streaming import bus, worker
    ev = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "x", "vendor_name": "X"},
        organization_id=None,
    )
    out = worker.handle_event(ev)
    assert out["processed"] == 1
    assert out["hits"] == 0
    assert out["ok"] is True


def test_worker_run_once_aggregates(db, org, user):
    from apps.streaming import bus, worker
    _seed_invoices(org, user, vendor="BatchCo", count=15, seconds_apart=30)

    events = [
        bus.Event(type="invoice.uploaded",
                  payload={"invoice_id": f"i-{i}", "vendor_name": "BatchCo",
                           "total_amount": 1000},
                  organization_id=str(org.id))
        for i in range(3)
    ]
    out = worker.run_once(events)
    assert out["processed"] == 3
    assert out["hits"] >= 3
    assert out["failed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Metrics
# ─────────────────────────────────────────────────────────────────────────────

def test_metrics_aggregates_throughput_and_errors(db):
    from apps.streaming.models import StreamProcessingLog
    from apps.streaming.worker import metrics
    from datetime import timedelta

    now = timezone.now()
    # 8 ok rows, 2 failures.
    for i in range(8):
        StreamProcessingLog.objects.create(
            event_type="invoice.uploaded", latency_ms=50 + i, ok=True,
            processed_at=now - timedelta(minutes=1),
        )
    for i in range(2):
        StreamProcessingLog.objects.create(
            event_type="invoice.uploaded", latency_ms=200, ok=False,
            error_message="boom", processed_at=now - timedelta(minutes=2),
        )

    m = metrics(window_minutes=10)
    assert m["events_processed"] == 10
    assert m["events_failed"] == 2
    assert 19 <= m["error_rate_pct"] <= 21   # 20% with rounding
    assert m["avg_latency_ms"] > 0
    assert m["p95_latency_ms"] > 0


def test_worker_raises_when_anomaly_persistence_fails(db, org):
    """A persistence failure must reach the bus so it can retry or DLQ."""
    from unittest.mock import patch
    from apps.streaming import bus, worker
    from apps.streaming.detectors import AnomalyHit

    event = bus.Event(
        type="invoice.uploaded",
        payload={"invoice_id": "failed-hit", "vendor_name": "FailureCo"},
        organization_id=str(org.id),
    )
    hit = AnomalyHit(
        organization_id=str(org.id), detector="test", severity="high",
        invoice_id="failed-hit", vendor_name="FailureCo", explanation="test", details={},
    )
    with patch("apps.streaming.worker.det.evaluate_all", return_value=[hit]), patch(
        "apps.streaming.worker._persist_hit", side_effect=RuntimeError("database unavailable")
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            worker.handle_event(event)
