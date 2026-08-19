from __future__ import annotations

import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone

from apps.authentication.models import Organization, User


class OrganizationAPIKey(models.Model):
    """Tenant API credential; only its SHA-256 digest is persisted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    monthly_limit = models.PositiveIntegerField(null=True, blank=True)
    used_this_month = models.PositiveIntegerField(default=0)
    usage_period = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="created_api_keys")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "organization_api_keys"
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="uniq_org_api_key_name")]

    @classmethod
    def issue(cls, *, organization, name: str, scopes: list[str], monthly_limit: int | None, created_by=None):
        raw = f"tdg_{secrets.token_urlsafe(32)}"
        return raw, cls.objects.create(
            organization=organization, name=name, key_prefix=raw[:12],
            key_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=scopes,
            monthly_limit=monthly_limit, created_by=created_by,
        )

    @classmethod
    def authenticate(cls, raw: str):
        if not raw.startswith("tdg_"):
            return None
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return cls.objects.select_related("organization").filter(key_hash=digest, is_active=True).first()


class APIUsageEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.ForeignKey(OrganizationAPIKey, on_delete=models.CASCADE, related_name="usage_events")
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    status_code = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_usage_events"
        indexes = [models.Index(fields=["api_key", "created_at"])]
