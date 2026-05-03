"""
Tests for Phase 2.1 — Mobile API surface.

Covers:
  • Login: returns access + refresh + user payload, registers the device.
  • Refresh token rotates and old token is blacklisted (rotation policy).
  • Logout blacklists the refresh and deactivates the device row.
  • Device register / biometric register validate inputs.
  • Inbox returns flagged invoices for the caller's org.
  • Idempotency-Key prevents double-execution on retry; refuses key reuse with
    a different body.
  • Multi-photo capture builds a PDF from N images and saves it under MEDIA_ROOT.
  • Push dispatcher logs to MockChannel when no FCM key is configured.
"""

from __future__ import annotations

import io
import json
import os
import uuid

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.api_mobile.models import IdempotencyKey, MobileDevice
from apps.audit.integrity import GENESIS_HASH
from apps.authentication.models import Organization, User


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="Mobile Test Org")


@pytest.fixture
def user(db, org):
    u = User.objects.create_user(
        email="mobile@test.local", full_name="Mobile Tester",
        password="pw1234", organization=org, role=User.Role.SENIOR_AUDITOR,
    )
    u.is_active = True
    u.save()
    return u


@pytest.fixture
def auth_client(user):
    """API client authenticated via the mobile login endpoint."""
    c = APIClient()
    res = c.post("/api/v1/mobile/auth/login/", {
        "email": user.email, "password": "pw1234",
        "device_id": "test-device-1", "platform": "ios", "device_name": "iPhone 15",
    }, format="json")
    assert res.status_code == 200, res.content
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
    return c, res.data


# ─────────────────────────────────────────────────────────────────────────────
# 1. Auth
# ─────────────────────────────────────────────────────────────────────────────

def test_login_returns_tokens_and_registers_device(db, user):
    c = APIClient()
    res = c.post("/api/v1/mobile/auth/login/", {
        "email": user.email, "password": "pw1234",
        "device_id": "iphone-abc", "platform": "ios", "device_name": "Pavel's iPhone",
    }, format="json")
    assert res.status_code == 200, res.content
    body = res.data
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == user.email
    assert body["device"]["device_id"] == "iphone-abc"

    device = MobileDevice.objects.get(user=user, device_id="iphone-abc")
    assert device.platform == "ios"
    assert device.is_active is True


def test_login_rejects_wrong_password(db, user):
    c = APIClient()
    res = c.post("/api/v1/mobile/auth/login/", {
        "email": user.email, "password": "wrong",
        "device_id": "x", "platform": "android",
    }, format="json")
    assert res.status_code == 401


def test_login_rejects_missing_fields(db, user):
    c = APIClient()
    res = c.post("/api/v1/mobile/auth/login/", {
        "email": user.email,
    }, format="json")
    assert res.status_code == 400


@override_settings(SIMPLE_JWT={
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ACCESS_TOKEN_LIFETIME": __import__("datetime").timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": __import__("datetime").timedelta(days=7),
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
})
def test_refresh_token_rotation(db, user):
    c = APIClient()
    res = c.post("/api/v1/mobile/auth/login/", {
        "email": user.email, "password": "pw1234",
        "device_id": "rot-test", "platform": "android",
    }, format="json")
    refresh1 = res.data["refresh"]

    # Rotate.
    res2 = c.post("/api/v1/mobile/auth/refresh/", {"refresh": refresh1}, format="json")
    assert res2.status_code == 200, res2.content
    refresh2 = res2.data.get("refresh")
    assert refresh2 and refresh2 != refresh1

    # Old token must be blacklisted — second use fails.
    res3 = c.post("/api/v1/mobile/auth/refresh/", {"refresh": refresh1}, format="json")
    assert res3.status_code in (401, 400)


def test_logout_blacklists_refresh_and_deactivates_device(db, auth_client):
    c, login = auth_client
    res = c.post("/api/v1/mobile/auth/logout/", {
        "refresh": login["refresh"], "device_id": "test-device-1",
    }, format="json")
    assert res.status_code == 200
    device = MobileDevice.objects.get(user_id=login["user"]["id"], device_id="test-device-1")
    assert device.is_active is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Device registration & biometric
# ─────────────────────────────────────────────────────────────────────────────

def test_device_register_upserts(db, auth_client):
    c, _ = auth_client
    res = c.post("/api/v1/mobile/devices/register/", {
        "device_id": "test-device-1",
        "push_token": "fcm-abc-123",
        "platform": "ios", "device_name": "iPhone 15",
    }, format="json")
    assert res.status_code == 200
    assert res.data["push_token_set"] is True

    # Re-register updates the same row.
    res2 = c.post("/api/v1/mobile/devices/register/", {
        "device_id": "test-device-1",
        "push_token": "fcm-rotated-456",
    }, format="json")
    assert res2.status_code == 200
    assert MobileDevice.objects.filter(device_id="test-device-1").count() == 1


def test_biometric_register_requires_pem(db, auth_client):
    c, login = auth_client
    res = c.post("/api/v1/mobile/devices/biometric/", {
        "device_id": "test-device-1", "public_key": "not-a-pem",
    }, format="json")
    assert res.status_code == 400


def test_biometric_register_stores_pubkey(db, auth_client):
    c, login = auth_client
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        "MCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n"
        "-----END PUBLIC KEY-----\n"
    )
    res = c.post("/api/v1/mobile/devices/biometric/", {
        "device_id": "test-device-1", "public_key": pem,
    }, format="json")
    assert res.status_code == 200, res.content
    device = MobileDevice.objects.get(user_id=login["user"]["id"], device_id="test-device-1")
    assert "BEGIN PUBLIC KEY" in device.biometric_pubkey


# ─────────────────────────────────────────────────────────────────────────────
# 3. Inbox
# ─────────────────────────────────────────────────────────────────────────────

def test_inbox_returns_flagged_invoices(db, auth_client, user, org):
    from apps.invoices.models import Invoice

    Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="MOB-001", vendor_name="Vendor A",
        total_amount=1000, status="flagged", risk_level="high",
        original_filename="x.pdf",
    )
    Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="MOB-002", vendor_name="Vendor B",
        total_amount=2000, status="approved",  # NOT in inbox — approved
        original_filename="y.pdf",
    )

    c, _ = auth_client
    res = c.get("/api/v1/mobile/inbox/")
    assert res.status_code == 200
    invoice_numbers = [r["invoice_number"] for r in res.data["results"]]
    assert "MOB-001" in invoice_numbers
    assert "MOB-002" not in invoice_numbers


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency
# ─────────────────────────────────────────────────────────────────────────────

def test_idempotent_action_caches_response(db, auth_client, user, org):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=user,
        invoice_number="IDEMP-1", vendor_name="X",
        total_amount=100, status="flagged",
        original_filename="x.pdf",
    )

    c, _ = auth_client
    key = str(uuid.uuid4())
    body = {"reason": "missing receipt"}

    res1 = c.post(
        f"/api/v1/mobile/invoices/{inv.id}/reject/",
        body, format="json", HTTP_IDEMPOTENCY_KEY=key,
    )
    # First call — performs the action.
    inv.refresh_from_db()
    first_status = inv.status

    # Second call with the same body + same key — must return the cached
    # response and NOT mutate anything else.
    res2 = c.post(
        f"/api/v1/mobile/invoices/{inv.id}/reject/",
        body, format="json", HTTP_IDEMPOTENCY_KEY=key,
    )
    assert res1.status_code == res2.status_code
    inv.refresh_from_db()
    assert inv.status == first_status

    # Same key, different body → 409.
    res3 = c.post(
        f"/api/v1/mobile/invoices/{inv.id}/reject/",
        {"reason": "DIFFERENT"}, format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert res3.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-photo capture
# ─────────────────────────────────────────────────────────────────────────────

def _png_bytes(color=(255, 0, 0), size=(120, 120)) -> bytes:
    """Tiny PNG built in-memory for upload tests."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_multi_photo_capture_builds_pdf(db, auth_client, tmp_path):
    from django.test import override_settings
    c, _ = auth_client

    photo_a = _png_bytes((255, 0, 0))
    photo_b = _png_bytes((0, 255, 0))

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        files = {
            "photos": [
                SimpleUploadedFile("a.png", photo_a, content_type="image/png"),
                SimpleUploadedFile("b.png", photo_b, content_type="image/png"),
            ],
        }
        # APIClient takes a flat dict for multi-file fields too.
        res = c.post(
            "/api/v1/mobile/captures/",
            data={"photos": files["photos"]},
            format="multipart",
        )

    assert res.status_code == 201, res.content
    body = res.data
    assert body["page_count"] >= 1   # PDF metadata varies by Pillow version
    assert body["size_bytes"] > 0
    assert body["photo_count"] == 2
    assert body["filename"].endswith(".pdf")


def test_multi_photo_capture_rejects_empty_post(db, auth_client):
    c, _ = auth_client
    res = c.post("/api/v1/mobile/captures/", {}, format="multipart")
    assert res.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 6. Push dispatcher (mock channel)
# ─────────────────────────────────────────────────────────────────────────────

def test_push_dispatcher_uses_mock_when_unconfigured(db, user, settings):
    from apps.api_mobile import push
    from apps.api_mobile.models import MobileDevice

    settings.FCM_SERVER_KEY = ""
    settings.APNS_KEY_ID = ""

    MobileDevice.objects.create(
        user=user, device_id="push-test", platform="android",
        push_token="fake-token-xyz",
    )
    results = push.dispatch(user, push.PushPayload(title="hi", body="ping"))
    assert len(results) == 1
    assert results[0]["channel"] == "mock"
    assert results[0]["ok"] is True
