"""
Auto-trigger rule engine audit on typed document save.

Handles all typed document models defined in apps.documents.typed_models.
Each post_save signal fires run_audit_task asynchronously via Celery,
scoped to the document's organization for full tenant isolation.
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("rule_engine")

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
    status = getattr(instance, "audit_status", None) or getattr(instance, "approval_status", None) or ""
    # Always trigger on creation; on updates only when status transitions to a ready state
    return status.lower() in _READY_STATUSES or status == ""


def _dispatch_audit(instance, document_type: str) -> None:
    """Fire run_audit_task.delay() in a non-blocking, fault-tolerant way."""
    try:
        org_id = str(instance.organization_id)
        doc_id = str(instance.pk)
        from apps.rule_engine.tasks.audit_tasks import run_audit_task
        run_audit_task.delay(
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
