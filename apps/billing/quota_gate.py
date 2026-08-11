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
        if self.reason == "rerun_confirmation_required":
            return _(
                "This document has already been audited. A fresh re-audit will "
                "consume one invoice from your quota. Pass force_rerun_confirmed=True "
                "to continue."
            )
        return _("Audit blocked by billing quota.")


# ─── document → org resolver ─────────────────────────────────────────────────
class UnknownDocumentType(Exception):
    """Raised when no normalizer is registered for a document type.

    Named separately from a missing record so the caller can tell "billing does
    not know this type" apart from "the record is gone" — the docstring below
    promises billing never swallows either, and a shared exception would blur
    which one happened.
    """


def _typed_model_for(document_type):
    """The model whose primary key `document_id` refers to, for this type.

    Read out of the normalizer registry — the same registry the pipeline
    dispatches on — so the two cannot disagree. A second map maintained here
    would drift from it, and that class of drift is the root of nearly every
    defect in this repository.
    """
    import inspect
    import re

    from django.apps import apps as django_apps

    from apps.rule_engine.normalizers import DocumentNormalizerFactory

    registry = (getattr(DocumentNormalizerFactory, "_registry", None)
                or getattr(DocumentNormalizerFactory, "registry", None) or {})
    normalizer = registry.get(document_type)
    if normalizer is None:
        raise UnknownDocumentType(
            f"No normalizer registered for document_type={document_type!r}; "
            f"billing cannot resolve which model owns this id."
        )

    source = inspect.getsource(normalizer.normalize)
    match = re.search(r"([A-Z][A-Za-z0-9_]+)\.objects\.", source)
    if not match:
        raise UnknownDocumentType(
            f"Normalizer for {document_type!r} does not resolve a model by id; "
            f"billing cannot determine the owning model."
        )

    # Scoped to the `documents` app, not searched across every installed model.
    #
    # Three different models are named JournalEntry — in documents, transactions
    # and ledger. A global search by class name returned whichever the registry
    # happened to yield first, which is how this function was handed a model
    # with no `document` field and broke eighteen billing tests.
    #
    # The class name is read from the normalizer rather than derived from the
    # document type, because the two do not correspond: expense -> ExpenseReport,
    # grn -> GoodsReceiptNote, payment -> PaymentVoucher, payroll -> PayrollSheet,
    # tax_return -> VATReturn. Deriving "".join(p.capitalize() ...) resolves 15
    # of 21 types and would have raised UnknownDocumentType for five that have
    # perfectly good models — reinstating the same outage for those five.
    try:
        return django_apps.get_model("documents", match.group(1))
    except LookupError:
        raise UnknownDocumentType(
            f"{document_type!r} maps to model {match.group(1)!r}, which is not "
            f"in the documents app, so it carries no Document to bill against. "
            f"Sales invoices are the known case: no post_save fires for them and "
            f"processor.py calls run_audit_task (V1) directly, while this gate "
            f"patches run_audit_compat only — they never reach here. Raising is "
            f"the correct outcome, not a case to special-case."
        ) from None


def _resolve_document_and_org(document_id, organization_id, document_type):
    """Look up the Document + Organization rows from the ids the pipeline
    was called with. Errors propagate to the caller — billing should
    never silently swallow a missing document.

    `document_id` IS THE TYPED RECORD'S PRIMARY KEY, not a Document row id.

    That is what every other component on this path means by it. Each
    normalizer resolves it that way — `PurchaseOrder.objects.get(id=document_id)`
    and the same in all 21 of them — and documents/signals.py:137 passes
    `str(instance.pk)` from the typed instance that fired the signal.

    This function read it as a Document primary key. The two are different id
    spaces: AuditMixin gives each typed record its own UUID and a OneToOne
    `document` pointing at the Document row. Measured on 500 rows each of
    PurchaseOrder and FixedAsset, id == document_id in zero of them. So every
    upload of the eleven typed document types raised Document.DoesNotExist here
    and no audit ever ran for them. The failure was invisible until the
    recursion in this same module was fixed, because that raised first.

    The typed model comes from the normalizer registry rather than a second
    hand-written map. A map written here would drift from the one the pipeline
    actually dispatches on, and hand-maintained lists are the root of nearly
    every defect this codebase has produced.

    One explicit path, no fallback: trying Document first and retreating to the
    typed record would leave nobody able to say which meaning is authoritative,
    which is the ambiguity that caused this.
    """
    from apps.authentication.models import Organization

    org = Organization.objects.get(pk=organization_id)

    model = _typed_model_for(document_type)
    # No select_related: the gate fetches exactly one row, so saving one query
    # is not worth an assumption about the relation's name. It also assumed
    # every typed model carries `document`, which broke on the one that does
    # not and took eighteen billing tests with it.
    record = model.objects.get(pk=document_id)
    return record.document, org


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
    force_rerun_confirmed: bool = False,
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

    Re-bill confirmation (Stage 9 — H-2):
      Setting ``force_rerun=True`` is interpreted as "I want a fresh
      audit even though this document was already billed." That fresh
      run is billed as a separate consume. To prevent accidental
      double-billing (e.g. retried POST), the caller MUST also set
      ``force_rerun_confirmed=True``. If force_rerun=True and the
      document is already billed but the caller did NOT confirm, the
      gate refuses with ``QuotaExceeded("rerun_confirmation_required")``.
      First-time runs (no prior consume) ignore both flags.
    """
    # Resolve the pipeline to call. Do NOT re-import run_audit_compat here.
    #
    # install_gate() replaces compat.run_audit_compat with _gated. An import at
    # CALL time runs after that replacement, so the name resolves to _gated
    # itself and the chain becomes _gated -> run_audit_with_quota -> _gated,
    # without end. Every call through the patched entry point raised
    # RecursionError, and the function the gate had saved was never read.
    #
    # The wrapper is identified by IDENTITY, not by asking it what it is. An
    # earlier version used getattr(entry, "_original", None) with a fallback,
    # which broke five existing tests: they inject a fake pipeline with
    # mock.patch on this attribute, and a MagicMock answers getattr for every
    # name — so the fallback never fired and the gate called mock._original()
    # instead of the mock. Identity is the one question a mock cannot answer
    # wrongly.
    from apps.rule_engine.pipeline.v2 import compat as _compat_mod

    _entry = _compat_mod.run_audit_compat
    if _entry is _GATED_WRAPPER:
        # Production: the module attribute is our own wrapper. Calling it would
        # re-enter this function forever, so call what it displaced.
        _original = _ORIGINAL_RUN_AUDIT
    else:
        # Not our wrapper — either the gate is not installed, or a caller has
        # substituted the entry point deliberately (the existing tests inject a
        # fake pipeline this way). Honour whatever is there.
        _original = _entry

    # Document + org are looked up at the start so a missing row fails
    # before we touch the quota table.
    doc, org = _resolve_document_and_org(document_id, organization_id, document_type)
    svc = QuotaService()

    already_billed = _already_billed(org, doc)

    # Already paid? Re-running analytics on a billed document is free.
    if not force_rerun and already_billed:
        logger.info(
            "[quota_gate] document %s already billed for org %s — pipeline runs without re-charge",
            document_id, organization_id,
        )
        return _original(
            document_id=document_id, document_type=document_type,
            organization_id=organization_id, triggered_by=triggered_by,
            force_rerun=force_rerun, engine_override=engine_override,
        )

    # Force-rerun on an already-billed document MUST be explicitly
    # confirmed — protects against accidental double-charging from a
    # retried POST or a stuck "Re-audit" button.
    if force_rerun and already_billed and not force_rerun_confirmed:
        raise QuotaExceeded("rerun_confirmation_required")

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

    # If this run was an explicitly-confirmed re-audit of an
    # already-billed document, allow the consume to create a fresh
    # ledger row (audit_run-keyed dedup still protects from celery retries).
    allow_rebill = bool(force_rerun and force_rerun_confirmed and already_billed)
    try:
        svc.consume_invoice_audit(
            org, document=doc, audit_run=audit_run if isinstance(audit_run, _AuditRunModel) else None,
            reason=f"triggered_by={triggered_by}",
            allow_rebill=allow_rebill,
        )
    except QuotaError:
        # Last resort: log loudly. The reservation has already been
        # written and the audit ran; we'd rather have an over-counted
        # ledger entry than silently lose billing for a successful run.
        logger.exception("[quota_gate] consume failed for completed audit %s", audit_run)
    return audit_run


# ─── monkey-patch install ────────────────────────────────────────────────────
_INSTALLED = False

#: The wrapper install_gate() puts on the compat module, and the function it
#: displaced. Held here rather than read back off the module attribute, because
#: that attribute is the one thing that cannot be trusted to identify itself:
#: tests replace it with a MagicMock, and a MagicMock answers getattr for any
#: name at all — so `getattr(entry, "_original", None)` returns a child mock
#: instead of None and the fallback never fires. An identity check against the
#: wrapper stored here is unambiguous for every case.
_GATED_WRAPPER = None
_ORIGINAL_RUN_AUDIT = None


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
    # Recorded module-side too: run_audit_with_quota identifies the wrapper by
    # identity against _GATED_WRAPPER, which no mock can imitate.
    global _GATED_WRAPPER, _ORIGINAL_RUN_AUDIT
    _GATED_WRAPPER = _gated
    _ORIGINAL_RUN_AUDIT = original
    _INSTALLED = True
    logger.info("[quota_gate] installed around run_audit_compat")
