"""
Auto-trigger rule engine audit on typed document save.

Handles all typed document models defined in apps.documents.typed_models.
Each post_save signal fires run_audit_task asynchronously via Celery,
scoped to the document's organization for full tenant isolation.
"""
import logging
import threading
from contextlib import contextmanager

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("rule_engine")


# Thread-local flag that lets bulk multi-record uploads skip per-row Celery
# dispatch (a 500-row Excel would otherwise queue 500 audit tasks). When set,
# the caller is expected to dispatch a single audit for the file as a whole.
_local = threading.local()


@contextmanager
def suppress_audit_dispatch():
    """Context manager that disables auto-audit dispatch for the current thread."""
    prev = getattr(_local, "suppressed", False)
    _local.suppressed = True
    try:
        yield
    finally:
        _local.suppressed = prev


def _is_suppressed() -> bool:
    return bool(getattr(_local, "suppressed", False))

# Map typed model class name → SupportedDocumentType string used by rule engine
_MODEL_TO_DOC_TYPE = {
    "PurchaseOrder":     "purchase_order",
    "BankStatement":     "bank_statement",
    "PayrollSheet":      "payroll",
    "ExpenseReport":     "expense",
    "VATReturn":         "tax_return",
    "FixedAsset":        "fixed_asset",
    "SalesReceipt":      "sales_receipt",
    "GoodsReceiptNote":  "grn",
    "PaymentVoucher":    "payment",
}

# Statuses that indicate the document is ready for audit
_READY_STATUSES = {"validated", "approved", "pending", "pending_review"}


def _should_trigger(instance) -> bool:
    """Return True if this save should kick off an audit run."""
    if _is_suppressed():
        return False
    status = getattr(instance, "audit_status", None) or getattr(instance, "approval_status", None) or ""
    # Always trigger on creation; on updates only when status transitions to a ready state
    return status.lower() in _READY_STATUSES or status == ""


def _has_active_run(doc_id: str, document_type: str, org_id: str) -> bool:
    """Deduplication guard — returns True if a run is already active/recent."""
    try:
        from datetime import timedelta
        from django.utils import timezone
        from apps.rule_engine.models import AuditRun
        cutoff = timezone.now() - timedelta(hours=1)
        return AuditRun.objects.filter(
            document_id=doc_id,
            document_type=document_type,
            organization_id=org_id,
            status__in=[
                AuditRun.Status.PENDING,
                AuditRun.Status.RUNNING,
                AuditRun.Status.COMPLETED,
            ],
            started_at__gte=cutoff,
        ).exists()
    except Exception:
        return False  # fail open


_BROKER_REACHABLE_CACHE = {"checked_at": 0, "reachable": None}


def _broker_reachable() -> bool:
    """Lightweight TCP probe of the Celery broker. Cached for 30s so we don't
    re-probe on every save. Returns False fast when the broker is down,
    avoiding the multi-second result-backend reconnect loop inside .delay().
    """
    import time as _time
    import socket
    from urllib.parse import urlparse
    from django.conf import settings

    now = _time.time()
    if _BROKER_REACHABLE_CACHE["reachable"] is not None and now - _BROKER_REACHABLE_CACHE["checked_at"] < 30:
        return _BROKER_REACHABLE_CACHE["reachable"]

    url = urlparse(getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"))
    host = url.hostname or "localhost"
    port = url.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1.0):
            reachable = True
    except Exception:
        reachable = False
    _BROKER_REACHABLE_CACHE.update(checked_at=now, reachable=reachable)
    return reachable


def _dispatch_audit(instance, document_type: str) -> None:
    """Fire run_audit_compat_task.delay() in a non-blocking, fault-tolerant way."""
    if not _broker_reachable():
        logger.debug("[Signal] Broker unreachable; skipping audit dispatch for %s %s",
                     document_type, instance.pk)
        return
    try:
        org_id = str(instance.organization_id)
        doc_id = str(instance.pk)

        if _has_active_run(doc_id, document_type, org_id):
            logger.info(
                "[Signal] Skipping duplicate dispatch: type=%s doc=%s already active",
                document_type, doc_id,
            )
            return

        from apps.rule_engine.tasks.audit_tasks_v2 import run_audit_compat_task
        run_audit_compat_task.delay(
            document_id=doc_id,
            document_type=document_type,
            organization_id=org_id,
            triggered_by="auto_signal",
        )
        logger.info(
            f"[Signal] Queued audit: type={document_type}, doc={doc_id}, org={org_id}"
        )
    except Exception as exc:
        # Never let a signal failure break the document save
        logger.warning(
            f"[Signal] Failed to queue audit for {document_type} {instance.pk}: {exc}"
        )


# ── Per-model signal handlers ─────────────────────────────────────────────────

@receiver(post_save, sender="documents.GoodsReceiptNote")
def on_grn_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "grn")


@receiver(post_save, sender="documents.PaymentVoucher")
def on_payment_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "payment")


@receiver(post_save, sender="documents.PurchaseOrder")
def on_purchase_order_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "purchase_order")


@receiver(post_save, sender="documents.BankStatement")
def on_bank_statement_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "bank_statement")


@receiver(post_save, sender="documents.PayrollSheet")
def on_payroll_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "payroll")


@receiver(post_save, sender="documents.ExpenseReport")
def on_expense_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "expense")


@receiver(post_save, sender="documents.VATReturn")
def on_vat_return_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "tax_return")


@receiver(post_save, sender="documents.FixedAsset")
def on_fixed_asset_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "fixed_asset")


@receiver(post_save, sender="documents.SalesReceipt")
def on_sales_receipt_save(sender, instance, created, **kwargs):
    if _should_trigger(instance):
        _dispatch_audit(instance, "sales_receipt")
