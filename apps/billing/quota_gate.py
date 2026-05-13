"""Quota gate around the audit pipeline.

Every audit run — manual, bulk, signal-driven, celery retry, reprocess
— enters the system through ``apps.rule_engine.pipeline.v2.compat.
run_audit_compat``. Wrapping that single function with this gate is
enough to guarantee that:

  1. No audit starts unless the org has a usable subscription with
     remaining quota.
  2. Successful audits consume exactly one unit per (document, audit_run).
  3. System-error failures release the reservation — no silent billing
     for runs that produced no useful output.
  4. Duplicate invocations for the same document (signal + view, celery
     retry, force_rerun-after-success) cannot multi-charge.

Idempotency is layered:

  • ``QuotaService.reserve_invoice_audit`` already returns the existing
    open reserve for a given document instead of creating a duplicate.
  • ``QuotaService.consume_invoice_audit`` returns the existing consume
    row for a given document instead of charging twice.
  • This module additionally short-circuits the gate entirely when an
    AuditRun for the same (document_id, organization_id) has already
    been billed (consume row exists in the ledger).

Public API:
  - QuotaExceeded — raised when the pipeline is blocked by quota.
  - run_audit_with_quota(...) — drop-in replacement for run_audit_compat.
  - install_gate() — monkey-patches run_audit_compat to be the gated
    version. Called from BillingConfig.ready so application code does
    not have to import the wrapped version explicitly.
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from apps.billing.choices import UsageAction
from apps.billing.models import UsageLedger
from apps.billing.services.quota_service import (
    NoActiveSubscription,
    QuotaError,
    QuotaExceeded as _QuotaServiceExceeded,
    QuotaService,
)


logger = logging.getLogger("billing.quota_gate")


class QuotaExceeded(Exception):
    """Raised by ``run_audit_with_quota`` when no audit may proceed.

    Surfaces ``reason`` from ``QuotaService.can_audit`` so callers can
    show the right Arabic-localised message.
    """
    def __init__(self, reason: str, *, remaining: int = 0, subscription=None):
        self.reason = reason
        self.remaining = remaining
        self.subscription = subscription
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        if self.reason == "no_subscription":
            return _("Please choose a subscription plan before auditing invoices.")
        if self.reason == "subscription_expired":
            return _("Your subscription has expired. Please renew to continue auditing.")
        if self.reason == "quota_exceeded":
            return _("You have used all available invoices in your current plan.")
        return _("Audit blocked by billing quota.")


# ─── document → org resolver ─────────────────────────────────────────────────
def _resolve_document_and_org(document_id, organization_id):
    """Look up the Document + Organization rows from the ids the pipeline
    was called with. Errors propagate to the caller — billing should
    never silently swallow a missing document."""
    from apps.documents.models import Document
    from apps.authentication.models import Organization
    org = Organization.objects.get(pk=organization_id)
    doc = Document.objects.get(pk=document_id, organization=org)
    return doc, org


def _already_billed(organization, document) -> bool:
    """A consume row exists for this (org, document) → already charged.

    Used to short-circuit a re-run of a previously-completed audit.
    Cheaper than letting reserve/consume cycle through their own
    idempotency checks every time.
    """
    return UsageLedger.objects.filter(
        organization=organization,
        document=document,
        action=UsageAction.CONSUME,
    ).exists()


# ─── the gated runner ────────────────────────────────────────────────────────
def run_audit_with_quota(
    document_id, document_type, organization_id,
    *,
    triggered_by: str = "upload",
    force_rerun: bool = False,
    engine_override=None,
):
    """Drop-in for ``run_audit_compat`` with a billing reserve/consume
    cycle wrapped around it.

    Behaviour:
      • If the document has already been billed (consume row exists)
        and the caller isn't forcing a re-run, skip the gate and call
        the real pipeline directly — re-running an analysis on an
        already-paid invoice must not charge again.
      • Otherwise: ``QuotaService.can_audit`` → reserve → pipeline →
        consume (success) or release (system error).
    """
    from apps.rule_engine.pipeline.v2.compat import (
        run_audit_compat as _original,
    )

    # Document + org are looked up at the start so a missing row fails
    # before we touch the quota table.
    doc, org = _resolve_document_and_org(document_id, organization_id)
    svc = QuotaService()

    # Already paid? Re-running analytics on a billed document is free.
    if not force_rerun and _already_billed(org, doc):
        logger.info(
            "[quota_gate] document %s already billed for org %s — pipeline runs without re-charge",
            document_id, organization_id,
        )
        return _original(
            document_id=document_id, document_type=document_type,
            organization_id=organization_id, triggered_by=triggered_by,
            force_rerun=force_rerun, engine_override=engine_override,
        )

    # Quota check.
    decision = svc.can_audit(org)
    if not decision["allowed"]:
        raise QuotaExceeded(
            decision["reason"],
            remaining=decision["remaining"],
            subscription=decision["subscription"],
        )

    # Reserve. QuotaService is itself idempotent on document — repeated
    # reserves for the same document don't multi-count.
    try:
        svc.reserve_invoice_audit(org, document=doc, reason=f"triggered_by={triggered_by}")
    except _QuotaServiceExceeded as exc:
        # Race: someone consumed the last slot between can_audit and reserve.
        raise QuotaExceeded("quota_exceeded") from exc
    except NoActiveSubscription as exc:
        raise QuotaExceeded("no_subscription") from exc

    # Run the pipeline. Anything raises → release the reservation so the
    # quota counter doesn't drift.
    try:
        audit_run = _original(
            document_id=document_id, document_type=document_type,
            organization_id=organization_id, triggered_by=triggered_by,
            force_rerun=force_rerun, engine_override=engine_override,
        )
    except Exception as exc:
        try:
            svc.release_invoice_audit(
                org, document=doc,
                reason=f"system_error: {type(exc).__name__}",
            )
        except QuotaError:
            logger.exception("[quota_gate] release after pipeline failure also raised")
        raise

    # Successful return — consume the reservation. AuditRun status is
    # the source of truth: if the pipeline persisted FAILED, treat it
    # as system error and release instead of consuming.
    from apps.rule_engine.models import AuditRun as _AuditRunModel
    if isinstance(audit_run, _AuditRunModel) and audit_run.status == _AuditRunModel.Status.FAILED:
        try:
            svc.release_invoice_audit(
                org, document=doc, reason="audit_run.status=failed",
            )
        except QuotaError:
            logger.exception("[quota_gate] release on AuditRun.failed raised")
        return audit_run

    try:
        svc.consume_invoice_audit(
            org, document=doc, audit_run=audit_run if isinstance(audit_run, _AuditRunModel) else None,
            reason=f"triggered_by={triggered_by}",
        )
    except QuotaError:
        # Last resort: log loudly. The reservation has already been
        # written and the audit ran; we'd rather have an over-counted
        # ledger entry than silently lose billing for a successful run.
        logger.exception("[quota_gate] consume failed for completed audit %s", audit_run)
    return audit_run


# ─── monkey-patch install ────────────────────────────────────────────────────
_INSTALLED = False


def install_gate() -> None:
    """Replace ``apps.rule_engine.pipeline.v2.compat.run_audit_compat``
    with the gated version. Idempotent — safe to call twice (e.g. test
    runner re-importing AppConfigs).

    Toggle off with BILLING_QUOTA_GATE_ENABLED=False for emergency
    debugging — but every audit will then bypass quota.
    """
    global _INSTALLED
    from django.conf import settings
    if not getattr(settings, "BILLING_QUOTA_GATE_ENABLED", True):
        logger.warning("[quota_gate] BILLING_QUOTA_GATE_ENABLED=False — gate not installed")
        return
    if _INSTALLED:
        return

    import apps.rule_engine.pipeline.v2.compat as compat_mod
    original = compat_mod.run_audit_compat
    if getattr(original, "_billing_gated", False):
        _INSTALLED = True
        return

    def _gated(*args, **kwargs):
        return run_audit_with_quota(*args, **kwargs)

    _gated._billing_gated = True               # type: ignore[attr-defined]
    _gated._original = original                # type: ignore[attr-defined]
    compat_mod.run_audit_compat = _gated
    _INSTALLED = True
    logger.info("[quota_gate] installed around run_audit_compat")
