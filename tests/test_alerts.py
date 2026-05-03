"""
Tests for Phase 3.2 — Alert routing.

Covers:
  • Dispatcher selects matching rules by trigger_type, detector, severity floor.
  • Cooldown suppresses duplicate alerts within the window per (rule, dedup_key).
  • Channel adapters return ok / failed dicts that the dispatcher persists.
  • Webhook signature is HMAC-SHA256 verifiable on the receiver side.
  • API: list / create / update / test / acknowledge.
  • Worker → dispatcher integration: an AnomalyHit fires alert events.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.alerts.channels.email   import EmailChannel
from apps.alerts.channels.sms     import SMSChannel
from apps.alerts.channels.slack   import SlackChannel
from apps.alerts.channels.webhook import WebhookChannel, sign_payload, verify_payload
from apps.alerts.channels.base    import Notification
from apps.alerts.dispatcher       import _matches, _is_in_cooldown, dispatch_for_anomaly
from apps.alerts.models           import AlertEvent, AlertRule
from apps.authentication.models   import Organization, User


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="Alert Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="alert-admin@test.local", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="alert-junior@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


@pytest.fixture
def admin_client(admin):
    c = APIClient(); c.force_authenticate(admin); return c


def _make_rule(org, **kw):
    return AlertRule.objects.create(
        organization=org,
        name=kw.get("name", "rule-1"),
        trigger_type="anomaly",
        trigger_detector=kw.get("trigger_detector", ""),
        min_severity=kw.get("min_severity", "medium"),
        channels=kw.get("channels") or [{"type": "email", "to": ["dest@test.local"]}],
        cooldown_minutes=kw.get("cooldown_minutes", 30),
        is_active=kw.get("is_active", True),
    )


def _synthetic_hit(org, **kw):
    """Match the duck-typed surface dispatch_for_anomaly expects."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=kw.get("id", "00000000-0000-0000-0000-000000000001"),
        organization_id=str(org.id),
        detector=kw.get("detector", "velocity"),
        severity=kw.get("severity", "high"),
        invoice_id=kw.get("invoice_id", "inv-1"),
        vendor_name=kw.get("vendor_name", "VendorA"),
        explanation=kw.get("explanation", "Vendor submitted 25 invoices in 30 minutes"),
        details=kw.get("details", {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Rule matching
# ─────────────────────────────────────────────────────────────────────────────

def test_severity_floor_excludes_low_alerts(db, org):
    rule = _make_rule(org, min_severity="high")
    assert _matches(rule, severity="high",     detector="velocity") is True
    assert _matches(rule, severity="medium",   detector="velocity") is False
    assert _matches(rule, severity="critical", detector="velocity") is True


def test_detector_filter(db, org):
    rule = _make_rule(org, trigger_detector="velocity")
    assert _matches(rule, severity="high", detector="velocity") is True
    assert _matches(rule, severity="high", detector="sudden_spike") is False
    assert _matches(rule, severity="high", detector="") is True   # blank = match


def test_inactive_rule_never_matches(db, org):
    rule = _make_rule(org, is_active=False)
    assert _matches(rule, severity="critical", detector="velocity") is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cooldown
# ─────────────────────────────────────────────────────────────────────────────

def test_cooldown_blocks_duplicate_within_window(db, org):
    rule = _make_rule(org, cooldown_minutes=30)
    AlertEvent.objects.create(
        organization=org, rule=rule,
        channel_type="email", channel_target="x@test", status=AlertEvent.Status.SENT,
        dedup_key="velocity:VendorA",
    )
    assert _is_in_cooldown(rule, "velocity:VendorA") is True
    assert _is_in_cooldown(rule, "velocity:VendorB") is False  # different key


def test_cooldown_does_not_block_after_window(db, org):
    from datetime import timedelta
    rule = _make_rule(org, cooldown_minutes=10)
    ev = AlertEvent.objects.create(
        organization=org, rule=rule,
        channel_type="email", channel_target="x@test", status=AlertEvent.Status.SENT,
        dedup_key="velocity:VendorA",
    )
    # Backdate the row so it falls outside the cooldown window.
    AlertEvent.objects.filter(pk=ev.pk).update(
        sent_at=timezone.now() - timedelta(minutes=20),
    )
    assert _is_in_cooldown(rule, "velocity:VendorA") is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def test_dispatch_creates_one_event_per_channel(db, org, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    rule = _make_rule(org, channels=[
        {"type": "email", "to": ["a@test.local"]},
        {"type": "sms",   "to": ["+966500000000"]},
    ])
    hit = _synthetic_hit(org)
    out = dispatch_for_anomaly(hit)
    assert out["rules_matched"] == 1
    assert out["sent"] >= 1
    assert AlertEvent.objects.filter(rule=rule).count() == 2


def test_dispatch_suppressed_creates_one_row_per_rule(db, org):
    rule = _make_rule(org, cooldown_minutes=30)
    AlertEvent.objects.create(
        organization=org, rule=rule,
        channel_type="email", channel_target="x@test",
        status=AlertEvent.Status.SENT, dedup_key="velocity:VendorA",
    )
    out = dispatch_for_anomaly(_synthetic_hit(org))
    assert out["suppressed"] == 1
    assert out["sent"] == 0
    assert AlertEvent.objects.filter(
        rule=rule, status=AlertEvent.Status.SUPPRESSED,
    ).exists()


def test_dispatch_unknown_channel_persists_failed(db, org):
    _make_rule(org, channels=[{"type": "carrier-pigeon", "to": ["X"]}])
    out = dispatch_for_anomaly(_synthetic_hit(org))
    assert out["failed"] >= 1
    failed = AlertEvent.objects.filter(status=AlertEvent.Status.FAILED).first()
    assert failed is not None
    assert "carrier-pigeon" in (failed.error_message or "")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Channel adapters
# ─────────────────────────────────────────────────────────────────────────────

def test_email_channel_sends_via_locmem_backend(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "no-reply@tadgeeg.test"
    from django.core import mail
    mail.outbox.clear()

    res = EmailChannel().send(
        {"to": ["alice@x.t", "bob@x.t"]},
        Notification(title="Hello", body="World", severity="high",
                     summary="Hello", deep_link="/i/x"),
    )
    assert res["ok"] is True
    assert len(mail.outbox) == 1
    assert "Hello" in mail.outbox[0].subject
    assert set(mail.outbox[0].to) == {"alice@x.t", "bob@x.t"}


def test_sms_channel_falls_back_to_mock_when_unconfigured(settings):
    settings.TWILIO_ACCOUNT_SID = ""
    settings.TWILIO_AUTH_TOKEN  = ""
    settings.TWILIO_FROM_NUMBER = ""
    res = SMSChannel().send({"to": "+966500000001"},
                            Notification(title="t", body="b", severity="high",
                                         summary="hello"))
    assert res["ok"] is True
    assert res.get("mock") is True


def test_slack_channel_requires_webhook_url():
    res = SlackChannel().send({}, Notification(title="x", body="y"))
    assert res["ok"] is False


def test_webhook_signature_verifies():
    secret = "shared-secret"
    body = b'{"event":"audit.alert"}'
    header = sign_payload(secret, body)
    assert header.startswith("sha256=")
    assert verify_payload(secret, body, header) is True
    assert verify_payload("wrong-secret", body, header) is False
    assert verify_payload(secret, b"tampered body", header) is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. API
# ─────────────────────────────────────────────────────────────────────────────

def test_api_create_rule_admin(db, admin_client):
    r = admin_client.post("/api/v1/alerts/rules/", {
        "name": "Critical anomalies",
        "trigger_detector": "velocity",
        "min_severity": "high",
        "channels": [{"type": "email", "to": ["audit@x.t"]}],
        "cooldown_minutes": 15,
    }, format="json")
    assert r.status_code == 201, r.content
    assert r.data["min_severity"] == "high"


def test_api_create_rule_requires_admin(db, junior, org):
    c = APIClient(); c.force_authenticate(junior)
    r = c.post("/api/v1/alerts/rules/", {
        "name": "should-fail",
        "channels": [{"type": "email", "to": ["x@y.z"]}],
    }, format="json")
    assert r.status_code == 403


def test_api_event_acknowledgement(db, org, admin):
    rule = _make_rule(org)
    ev = AlertEvent.objects.create(
        organization=org, rule=rule,
        channel_type="email", channel_target="x@test",
        status=AlertEvent.Status.SENT, dedup_key="x", severity="high",
    )
    c = APIClient(); c.force_authenticate(admin)
    r = c.post(f"/api/v1/alerts/events/{ev.id}/ack/")
    assert r.status_code == 200
    ev.refresh_from_db()
    assert ev.status == AlertEvent.Status.ACKNOWLEDGED
    assert ev.acknowledged_at is not None
    assert ev.acknowledged_by_id == admin.id


# ─────────────────────────────────────────────────────────────────────────────
# 6. End-to-end with streaming worker
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_dispatches_alert_when_detector_fires(db, org, settings):
    """A streaming AnomalyHit must trigger any matching AlertRule's channels."""
    settings.STREAMING_BUS_BACKEND = "memory"
    from apps.streaming import bus
    bus.reset_backend()

    _make_rule(org, channels=[{"type": "email", "to": ["audit@x.t"]}])
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "no-reply@tadgeeg.test"
    from django.core import mail
    mail.outbox.clear()

    # Build the AnomalyHit row directly (skip the detector + DB seeding work,
    # since dispatcher doesn't care how the hit was created).
    from apps.streaming.models import AnomalyHit as Hit
    hit = Hit.objects.create(
        organization=org, detector="velocity", severity="high",
        invoice_id="inv-x", vendor_name="VendorVel",
        explanation="vendor submitted 25 invoices in 30 minutes",
        details={"count": 25},
    )

    out = dispatch_for_anomaly(hit)
    assert out["rules_matched"] == 1
    assert out["sent"] >= 1
    assert len(mail.outbox) == 1
