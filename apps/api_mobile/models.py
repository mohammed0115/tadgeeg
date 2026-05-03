"""
Models for the mobile-API surface — Phase 2.1 of the Enterprise Roadmap.

Two pieces of state live here:

  1. ``MobileDevice`` — one row per (user, device). Stores the FCM/APNs push
     token used to deliver "needs your approval" notifications, plus an
     optional ed25519 / WebAuthn public key the auditor's phone uses to
     sign sensitive actions (biometric-unlock + device-key signature).
  2. ``IdempotencyKey`` — request de-duplication. The mobile app sends
     ``Idempotency-Key: <uuid>`` on every mutating call so a flaky network
     can retry safely. The key is stored alongside the resulting status code
     and JSON body so a retry returns the *same* response instead of running
     a side effect twice.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class MobileDevice(models.Model):
    """Registered phone / tablet for a single user."""

    class Platform(models.TextChoices):
        IOS     = "ios",     "iOS"
        ANDROID = "android", "Android"
        WEB     = "web",     "Web (PWA)"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user          = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="mobile_devices",
    )
    device_id     = models.CharField(
        max_length=128, db_index=True,
        help_text="Stable identifier the app generates on first launch (e.g. iOS identifierForVendor).",
    )
    device_name   = models.CharField(max_length=255, blank=True,
                                     help_text="Human label shown on the security page (e.g. 'iPhone 15 Pro')")
    platform      = models.CharField(max_length=8, choices=Platform.choices)
    push_token    = models.CharField(max_length=512, blank=True,
                                     help_text="FCM token (Android/Web) or APNs token (iOS).")
    biometric_pubkey = models.TextField(
        blank=True,
        help_text="PEM-encoded ed25519 / WebAuthn-COSE public key bound to the device. Optional.",
    )
    last_seen_at  = models.DateTimeField(default=timezone.now)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mobile_devices"
        ordering = ["-last_seen_at"]
        constraints = [
            # One row per (user, device) — registering the same phone twice
            # updates the existing row (push_token rotates frequently).
            models.UniqueConstraint(
                fields=["user", "device_id"],
                name="mobile_device_unique_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["push_token"]),
        ]

    def __str__(self) -> str:
        return f"{self.platform}:{self.device_name or self.device_id[:8]} ({self.user_id})"


class IdempotencyKey(models.Model):
    """Persisted response cache for retried mobile mutations.

    The mobile app generates a UUID per logical request. If the network drops
    and the user retries, the second call hits this row, finds the cached
    response, and returns it instead of re-executing the side-effect.

    Keys are scoped per (user, key) so a malicious client can't replay
    another user's request. ``expires_at`` lets the storage stay bounded.
    """

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user          = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="idempotency_keys",
    )
    key           = models.CharField(max_length=128, db_index=True)
    request_path  = models.CharField(max_length=255)
    request_hash  = models.CharField(max_length=64, blank=True,
                                     help_text="SHA-256 of the request body — guard against key reuse on different payloads.")
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    expires_at    = models.DateTimeField()

    class Meta:
        db_table = "mobile_idempotency_keys"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"],
                name="mobile_idempotency_unique_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.key[:12]}… → {self.response_status}"
