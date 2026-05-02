"""Notification service helpers.

Producers anywhere in the codebase call :func:`notify` to push an in-app alert.
The function is safe to call from sync or async contexts and never raises.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.db.models import Q

from .models import Notification

logger = logging.getLogger(__name__)


def notify(
    user,
    title: str,
    message: str = "",
    *,
    severity: str = Notification.Severity.INFO,
    category: str = Notification.Category.SYSTEM,
    link: str = "",
    source_type: str = "",
    source_id: str = "",
    organization=None,
) -> Notification | None:
    """Create an in-app notification for a single user.

    Returns the Notification instance, or None if creation failed.
    Failures are logged but never raised so notification bugs don't break
    business flows.
    """
    if user is None or not getattr(user, "is_authenticated", True):
        return None
    try:
        return Notification.objects.create(
            user=user,
            organization=organization or getattr(user, "organization", None),
            severity=severity,
            category=category,
            title=title[:200],
            message=message,
            link=link[:500],
            source_type=source_type[:50],
            source_id=str(source_id)[:64] if source_id else "",
        )
    except Exception as exc:
        logger.warning("notify() failed for user=%s title=%r: %s", getattr(user, "pk", None), title, exc)
        return None


def notify_org(
    organization,
    title: str,
    message: str = "",
    *,
    user_filter: dict | None = None,
    **kwargs,
) -> int:
    """Notify every active user in an organization. Returns count created."""
    if organization is None:
        return 0
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        qs = User.objects.filter(organization=organization, is_active=True)
        if user_filter:
            qs = qs.filter(**user_filter)
        count = 0
        for u in qs:
            n = notify(u, title, message, organization=organization, **kwargs)
            if n is not None:
                count += 1
        return count
    except Exception as exc:
        logger.warning("notify_org failed for org=%s: %s", getattr(organization, "pk", None), exc)
        return 0


# ─── Convenience shortcuts for common audit/fraud events ────────────────────

def notify_high_risk_invoice(user, invoice):
    """Triggered when an invoice gets risk_level=high or critical."""
    risk = getattr(invoice, "risk_level", "high") or "high"
    return notify(
        user,
        title=f"⚠️ {invoice.__class__.__name__} flagged: {risk}",
        message=f"Invoice {getattr(invoice, 'invoice_number', invoice.pk)} from "
                f"{getattr(invoice, 'vendor_name', 'unknown vendor')} requires manual review.",
        severity=Notification.Severity.DANGER if risk in ("high", "critical") else Notification.Severity.WARNING,
        category=Notification.Category.FRAUD,
        link=f"/invoices/{invoice.pk}/",
        source_type="invoice",
        source_id=str(invoice.pk),
    )


def notify_fraud_detected(user, document, indicators: Iterable[str]):
    """Triggered when fraud-detection rules fire."""
    indicators = list(indicators)
    return notify(
        user,
        title=f"🚨 Fraud indicators detected ({len(indicators)})",
        message="Triggered: " + ", ".join(indicators[:5]),
        severity=Notification.Severity.CRITICAL,
        category=Notification.Category.FRAUD,
        link=f"/invoices/{document.pk}/" if hasattr(document, "pk") else "",
        source_type=type(document).__name__.lower(),
        source_id=str(getattr(document, "pk", "")),
    )


def notify_compliance_failed(user, document, standard: str = "ZATCA"):
    return notify(
        user,
        title=f"❌ {standard} compliance failed",
        message=f"Document {getattr(document, 'invoice_number', document.pk)} failed {standard} validation.",
        severity=Notification.Severity.DANGER,
        category=Notification.Category.COMPLIANCE,
        link=f"/invoices/{document.pk}/" if hasattr(document, "pk") else "",
        source_type=type(document).__name__.lower(),
        source_id=str(getattr(document, "pk", "")),
    )


def notify_upload_complete(user, processed: int, failed: int = 0):
    if failed:
        return notify(
            user,
            title=f"⚠️ Upload finished with errors",
            message=f"{processed} processed, {failed} failed.",
            severity=Notification.Severity.WARNING,
            category=Notification.Category.UPLOAD,
            link="/invoices/",
        )
    return notify(
        user,
        title=f"✅ {processed} document(s) processed",
        message="All documents were uploaded and analyzed successfully.",
        severity=Notification.Severity.SUCCESS,
        category=Notification.Category.UPLOAD,
        link="/invoices/",
    )


# ─── Read state ──────────────────────────────────────────────────────────────

def get_unread_count(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    """Mark every unread notification for the user as read. Returns count."""
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    from django.utils import timezone
    return Notification.objects.filter(user=user, is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
