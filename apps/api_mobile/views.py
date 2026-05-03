"""
Mobile API views — Phase 2.1.

Endpoints (all under ``/api/v1/mobile/``):

  POST /auth/login              — email + password → access + refresh tokens
  POST /auth/refresh            — refresh-token rotation (delegates to simplejwt)
  POST /auth/logout             — blocklist the refresh token
  POST /devices/register        — upsert a MobileDevice with FCM/APNs token
  POST /devices/biometric       — store the device's ed25519 public key
  GET  /inbox/                  — paginated list of items needing the user's action
  POST /invoices/<id>/approve/  — approve an invoice (with idempotency)
  POST /invoices/<id>/reject/   — reject an invoice (with idempotency)
  POST /captures/               — N photos → server-built PDF
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.api_mobile import captures as caps
from apps.api_mobile.models import IdempotencyKey, MobileDevice

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency helpers
# ─────────────────────────────────────────────────────────────────────────────

IDEMPOTENCY_TTL = timedelta(hours=24)


def _idempotency_lookup(request, request_body: bytes):
    """Return a cached Response for a repeated mutation, or None.

    The mobile app sends ``Idempotency-Key`` (header) on every mutation. We
    persist (status, body) per (user, key) so retries return the same answer
    without re-running the side effect.

    If the same key arrives with a *different* request body, that's a client
    bug — we refuse it with 409 so the bug surfaces fast.
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, None

    body_hash = hashlib.sha256(request_body or b"").hexdigest()
    rec = IdempotencyKey.objects.filter(user=request.user, key=key).first()
    if rec and rec.expires_at > timezone.now():
        if rec.request_hash and rec.request_hash != body_hash:
            return Response(
                {"error": "Idempotency-Key reused with a different request body"},
                status=409,
            ), None
        return Response(rec.response_body, status=rec.response_status), None

    return None, (key, body_hash)


def _idempotency_store(request, marker, response):
    """Persist (status, body) for a future retry."""
    if not marker:
        return response
    key, body_hash = marker
    try:
        body = response.data if hasattr(response, "data") else {}
        IdempotencyKey.objects.update_or_create(
            user=request.user, key=key,
            defaults={
                "request_path":   request.path,
                "request_hash":   body_hash,
                "response_status": response.status_code,
                "response_body":  body if isinstance(body, dict) else {"data": body},
                "expires_at":     timezone.now() + IDEMPOTENCY_TTL,
            },
        )
    except Exception as exc:
        logger.warning("[idempotency] failed to persist key: %s", exc)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class MobileLoginView(APIView):
    """POST /api/v1/mobile/auth/login

    Body: ``{"email": "...", "password": "...", "device_id": "...", "platform": "ios|android|web", "device_name": "..."}``

    Returns ``{"access": "...", "refresh": "...", "user": {...}, "device": {...}}``.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from django.contrib.auth import authenticate

        email    = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        device_id   = (request.data.get("device_id") or "").strip()
        device_name = (request.data.get("device_name") or "").strip()
        platform    = (request.data.get("platform") or "android").strip().lower()

        if not email or not password:
            return Response({"error": "email and password are required"}, status=400)
        if platform not in {"ios", "android", "web"}:
            return Response({"error": "platform must be ios|android|web"}, status=400)

        user = authenticate(request, username=email, password=password)
        if not user or not user.is_active:
            return Response({"error": "invalid credentials"}, status=401)

        refresh = RefreshToken.for_user(user)
        device = None
        if device_id:
            device, _ = MobileDevice.objects.update_or_create(
                user=user, device_id=device_id,
                defaults={"platform": platform, "device_name": device_name,
                          "last_seen_at": timezone.now(), "is_active": True},
            )

        return Response({
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id":           str(user.id),
                "email":        user.email,
                "full_name":    user.full_name,
                "role":         user.role,
                "organization": str(user.organization_id) if user.organization_id else None,
            },
            "device": (
                {"id": str(device.id), "device_id": device.device_id,
                 "platform": device.platform, "name": device.device_name}
                if device else None
            ),
        })


class MobileLogoutView(APIView):
    """POST /api/v1/mobile/auth/logout — blocklist the refresh token + deactivate the device row."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("refresh", "")
        device_id = request.data.get("device_id", "")
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            pass
        if device_id:
            MobileDevice.objects.filter(user=request.user, device_id=device_id).update(is_active=False)
        return Response({"ok": True})


class MobileDeviceRegisterView(APIView):
    """POST /api/v1/mobile/devices/register — upsert push token + device metadata."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        device_id   = (request.data.get("device_id") or "").strip()
        if not device_id:
            return Response({"error": "device_id is required"}, status=400)
        defaults = {"last_seen_at": timezone.now(), "is_active": True}
        for field in ("platform", "device_name", "push_token"):
            v = request.data.get(field)
            if v is not None:
                defaults[field] = v
        device, created = MobileDevice.objects.update_or_create(
            user=request.user, device_id=device_id, defaults=defaults,
        )
        return Response({
            "id": str(device.id), "created": created,
            "device_id": device.device_id, "platform": device.platform,
            "push_token_set": bool(device.push_token),
        })


class MobileBiometricRegisterView(APIView):
    """POST /api/v1/mobile/devices/biometric — store the device's public key.

    The mobile app generates an ed25519 key pair on first biometric unlock and
    sends the *public* half to us. Future sensitive actions (approve / reject)
    will be co-signed by this key — we trust the device because its private
    half is gated behind FaceID/TouchID. (Full WebAuthn sign-and-verify lives
    in a follow-up story; this row is the foundation.)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        device_id = (request.data.get("device_id") or "").strip()
        pubkey    = (request.data.get("public_key") or "").strip()
        if not device_id or not pubkey:
            return Response({"error": "device_id and public_key are required"}, status=400)

        # Sanity-check: PEM format (lightweight — we don't decode here).
        if not re.search(r"BEGIN [A-Z ]*PUBLIC KEY", pubkey):
            return Response({"error": "public_key must be PEM-encoded"}, status=400)

        try:
            device = MobileDevice.objects.get(user=request.user, device_id=device_id)
        except MobileDevice.DoesNotExist:
            return Response({"error": "device not registered — call /devices/register first"},
                            status=404)

        device.biometric_pubkey = pubkey
        device.save(update_fields=["biometric_pubkey", "updated_at"])
        return Response({"ok": True, "device_id": device.device_id})


# ─────────────────────────────────────────────────────────────────────────────
# Inbox
# ─────────────────────────────────────────────────────────────────────────────

class MobileInboxView(APIView):
    """GET /api/v1/mobile/inbox/

    Returns the pending-action queue: invoices flagged for review or
    pending the user's approval, sorted newest first. Pagination via
    ``?cursor=<created_at>`` for infinite-scroll on phones.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.invoices.models import Invoice
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": [], "next_cursor": None})

        qs = (
            Invoice.objects
            .filter(organization=org, status__in=["flagged", "pending"])
            .order_by("-updated_at")
        )
        cursor = request.GET.get("cursor")
        if cursor:
            qs = qs.filter(updated_at__lt=cursor)

        page = list(qs[:25])
        next_cursor = page[-1].updated_at.isoformat() if len(page) == 25 else None

        return Response({
            "results": [
                {
                    "id":             str(i.id),
                    "invoice_number": i.invoice_number or "",
                    "vendor":         i.vendor_name or "",
                    "total_amount":   float(i.total_amount or 0),
                    "currency":       i.currency or "SAR",
                    "risk_level":     i.risk_level or "medium",
                    "risk_score":     float(i.risk_score or 0),
                    "status":         i.status,
                    "updated_at":     i.updated_at.isoformat(),
                    "deep_link":      f"tadgeeg://invoices/{i.id}",
                }
                for i in page
            ],
            "next_cursor": next_cursor,
            "count": len(page),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Approve / Reject (idempotent)
# ─────────────────────────────────────────────────────────────────────────────

class MobileInvoiceActionView(APIView):
    """POST /api/v1/mobile/invoices/<uuid>/approve|reject/

    Honours ``Idempotency-Key`` header so retried network requests don't
    double-act. Delegates the actual approval logic to the existing
    ``InvoiceApproveView`` so role-gates and the override workflow stay in
    one place.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        if action not in {"approve", "reject"}:
            return Response({"error": "action must be approve or reject"}, status=400)

        # Idempotency check before doing anything.
        body = request.body or b""
        cached, marker = _idempotency_lookup(request, body)
        if cached is not None:
            return cached

        from apps.invoices.views import InvoiceApproveView
        approve_view = InvoiceApproveView.as_view()
        # Forward the request body to the existing view, mapping the mobile
        # contract onto the desktop one.
        payload = {
            "action": action,
            "reason": request.data.get("reason", ""),
            "override": bool(request.data.get("override", False)),
            "override_reason": request.data.get("override_reason", ""),
        }
        # Build a fresh DRF request manually — we already have one, so just
        # mutate request.data is risky. Easier: call the underlying view.
        # We reuse the same request because the auth context is identical.
        request._full_data = payload  # DRF caches parsed data here
        try:
            response = approve_view(request._request, pk=pk)
        except Exception as exc:
            logger.exception("[mobile.action] %s failed: %s", action, exc)
            response = Response({"error": "server error"}, status=500)

        return _idempotency_store(request, marker, response)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-photo capture
# ─────────────────────────────────────────────────────────────────────────────

class MobileCaptureView(APIView):
    """POST /api/v1/mobile/captures/ — N photos → single server-built PDF.

    Multipart form: ``photos[]`` repeated. Returns the URL of the PDF the
    server saved under ``MEDIA_ROOT``.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        files = request.FILES.getlist("photos") or request.FILES.getlist("photos[]")
        if not files:
            return Response({"error": "no photos uploaded"}, status=400)
        if len(files) > 30:
            return Response({"error": "max 30 photos per capture"}, status=413)

        try:
            result = caps.save_capture_pdf(request.user, files)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("[mobile.captures] PDF build failed: %s", exc)
            return Response({"error": "PDF build failed"}, status=500)

        return Response({
            "ok":         True,
            "pdf_url":    result["pdf_url"],
            "filename":   result["filename"],
            "page_count": result["page_count"],
            "size_bytes": result["size_bytes"],
            "photo_count": len(files),
        }, status=201)
