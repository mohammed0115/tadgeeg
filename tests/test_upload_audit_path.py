"""An upload of a typed document must actually reach the audit pipeline.

Eleven document types never got audited. Two defects stacked on the same path:
`run_audit_compat` recursed into its own billing wrapper, and underneath that
the wrapper resolved `document_id` as a Document primary key while every
normalizer resolves it as the TYPED record's key. Fixing the first exposed the
second, which failed just as completely — `Document.DoesNotExist` on every
upload.

WHY 3,946 TESTS PASSED OVER BOTH

apps/billing/tests/test_quota_gate.py calls `run_audit_with_quota` directly and
mocks the pipeline behind it. That skips the monkey-patched module attribute,
which is where the recursion lived, and mocks away the resolver, which is where
the id-space mismatch lived. Every test of the gate avoided both defects in the
gate.

So these tests enter where production enters: `compat.run_audit_compat`, after
`install_gate()`, with a real typed record and its real primary key. No mock
stands between the call and the resolver.

No MagicMock appears in the verification path at all — a mock answers getattr
for any name, and that is exactly how an earlier fix in this file passed its
own tests while calling the wrong function.
"""

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.fixture
def org_with_quota(db):
    """An organisation with an active paid subscription."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService
    from apps.billing.tests._factories import make_org

    call_command("seed_billing_plans", stdout=StringIO())
    org = make_org(name="Upload Path Org")
    plan = Plan.objects.get(code=PlanCode.STARTER)
    pending = SubscriptionService().create_pending_paid_subscription(org, plan)
    SubscriptionService().activate_subscription(pending)
    return org


@pytest.fixture
def purchase_order(org_with_quota):
    """A real typed record with its real Document, as an upload produces."""
    from apps.documents.models import Document
    from apps.documents.typed_models import PurchaseOrder

    document = Document.objects.create(
        organization=org_with_quota,
        document_type="purchase_order",
        file="po.pdf",
        original_filename="po.pdf",
        file_size=1024,
        mime_type="application/pdf",
    )
    return PurchaseOrder.objects.create(
        document=document,
        organization=org_with_quota,
        po_number="PO-TEST-001",
        vendor_name="Test Vendor",
    )


@pytest.fixture
def gate_installed():
    from apps.billing import quota_gate

    quota_gate.install_gate()
    import apps.rule_engine.pipeline.v2.compat as compat_mod
    return compat_mod


# ── The path production takes ────────────────────────────────────────────────

@pytest.mark.django_db
def test_official_entrypoint_audits_a_typed_document(
    purchase_order, org_with_quota, gate_installed
):
    """The whole point: the typed record's own pk, through the patched entry.

    Before the fix this raised Document.DoesNotExist from the resolver and no
    AuditRun was ever created for this document type.
    """
    compat_mod = gate_installed

    run = compat_mod.run_audit_compat(
        document_id=str(purchase_order.pk),
        document_type="purchase_order",
        organization_id=str(org_with_quota.pk),
    )

    assert run is not None, "the pipeline returned nothing"
    run.refresh_from_db()
    assert str(run.document_id) == str(purchase_order.pk), (
        "the AuditRun is not tied to the typed record the caller named"
    )
    assert run.total_rules > 0, (
        "the run applied no rules — the normalizer did not find the record, "
        "which means the id space is still wrong"
    )


@pytest.mark.django_db
def test_quota_is_consumed_once_per_document(
    purchase_order, org_with_quota, gate_installed
):
    """Resolving through the typed record must not break the billing it feeds.

    The ledger keys on the Document row, so the resolver returning the right
    Document is what makes idempotency work at all.
    """
    from apps.billing.choices import UsageAction
    from apps.billing.models import UsageLedger

    compat_mod = gate_installed
    kwargs = dict(
        document_id=str(purchase_order.pk),
        document_type="purchase_order",
        organization_id=str(org_with_quota.pk),
    )

    compat_mod.run_audit_compat(**kwargs)
    compat_mod.run_audit_compat(**kwargs)          # a retry, or signal + view

    consumes = UsageLedger.objects.filter(
        organization=org_with_quota,
        document=purchase_order.document,
        action=UsageAction.CONSUME,
    ).count()
    assert consumes == 1, f"the document was charged {consumes} times"


@pytest.mark.django_db
def test_unknown_document_type_fails_loudly(org_with_quota, gate_installed):
    """Billing does not swallow a type it cannot resolve.

    The resolver's own docstring promises this; without it, an unregistered
    type would silently skip both the audit and the charge.
    """
    from apps.billing.quota_gate import UnknownDocumentType

    compat_mod = gate_installed

    with pytest.raises(UnknownDocumentType) as excinfo:
        compat_mod.run_audit_compat(
            document_id="00000000-0000-0000-0000-000000000000",
            document_type="not_a_real_document_type",
            organization_id=str(org_with_quota.pk),
        )
    assert "not_a_real_document_type" in str(excinfo.value), (
        "the error does not name the type that could not be resolved"
    )


@pytest.mark.django_db
def test_a_missing_typed_record_is_distinguishable_from_an_unknown_type(
    org_with_quota, gate_installed
):
    """Two different failures must not share one exception, or the operator
    cannot tell "billing does not know this type" from "the record is gone"."""
    from apps.documents.typed_models import PurchaseOrder

    compat_mod = gate_installed

    with pytest.raises(PurchaseOrder.DoesNotExist):
        compat_mod.run_audit_compat(
            document_id="00000000-0000-0000-0000-000000000000",
            document_type="purchase_order",
            organization_id=str(org_with_quota.pk),
        )


# ── The guard, seen failing ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_this_guard_can_fail(purchase_order, org_with_quota, gate_installed, monkeypatch):
    """Reinstate the defect and confirm the guard above catches it.

    The resolver is patched back to its Document-keyed form here — the file is
    not edited. A guard nobody has watched fail is not a guard.
    """
    from apps.billing import quota_gate

    compat_mod = gate_installed

    def _broken_resolver(document_id, organization_id, document_type):
        # The bug, verbatim: read document_id as a Document primary key.
        from apps.authentication.models import Organization
        from apps.documents.models import Document

        org = Organization.objects.get(pk=organization_id)
        return Document.objects.get(pk=document_id, organization=org), org

    monkeypatch.setattr(quota_gate, "_resolve_document_and_org", _broken_resolver)

    from apps.documents.models import Document

    with pytest.raises(Document.DoesNotExist):
        compat_mod.run_audit_compat(
            document_id=str(purchase_order.pk),
            document_type="purchase_order",
            organization_id=str(org_with_quota.pk),
        )


# ── The extraction itself must stay honest as types are added ────────────────

def test_every_gated_document_type_resolves_to_a_model(db):
    """Every registered type must resolve to a model that carries a Document.

    This is the check that would have caught a near-miss: deriving the class
    name from the document type — "".join(p.capitalize() for p in ...) —
    resolves 15 of 21 and silently misses five that have perfectly good models:

        expense    -> ExpenseReport      grn        -> GoodsReceiptNote
        payment    -> PaymentVoucher     payroll    -> PayrollSheet
        tax_return -> VATReturn

    Adopting it would have reinstated the exact outage this shipment fixes, for
    those five. The name is read from the normalizer instead, and this test
    fails the moment a newly registered type has no model behind it.
    """
    from apps.billing.quota_gate import UnknownDocumentType, _typed_model_for
    from apps.rule_engine.normalizers import DocumentNormalizerFactory

    registry = (getattr(DocumentNormalizerFactory, "_registry", None)
                or getattr(DocumentNormalizerFactory, "registry", None) or {})
    assert registry, "the normalizer registry is empty"

    unresolved, no_document = [], []
    for document_type in sorted(registry):
        try:
            model = _typed_model_for(document_type)
        except UnknownDocumentType:
            unresolved.append(document_type)
            continue
        # Sales invoices are normalized by Invoice.pk and deliberately bridge
        # to Document through Invoice.audit_document for quota accounting.
        if document_type == "sales_invoice":
            if model.__name__ != "Invoice":
                no_document.append((document_type, model.__name__))
            continue
        if not hasattr(model, "document"):
            no_document.append((document_type, model.__name__))

    assert not unresolved, (
        f"registered type(s) {unresolved} resolve to no model in the documents "
        f"app, so an upload of them would raise instead of being audited"
    )
    assert not no_document, (
        f"{no_document} resolve to models with no Document relation; billing "
        f"has nothing to charge against"
    )


@pytest.mark.django_db
def test_sales_invoice_resolves_to_its_explicit_quota_document(org_with_quota):
    """Sales invoices now enter the same quota gate as typed documents.

    The pipeline addresses the Invoice by its own UUID, while UsageLedger is
    keyed to Document.  The invoice-owned bridge must preserve both meanings
    without guessing a Document id from the invoice id.
    """
    from apps.billing.quota_gate import _resolve_document_and_org, _typed_model_for
    from apps.documents.models import Document
    from apps.invoices.models import Invoice

    document = Document.objects.create(
        organization=org_with_quota,
        file="invoices/test.pdf",
        original_filename="test.pdf",
        file_size=1,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )
    invoice = Invoice.objects.create(
        organization=org_with_quota,
        original_filename="test.pdf",
        audit_document=document,
    )

    assert _typed_model_for("sales_invoice") is Invoice
    resolved_document, resolved_org = _resolve_document_and_org(
        str(invoice.pk), str(org_with_quota.pk), "sales_invoice"
    )
    assert resolved_document.pk == document.pk
    assert resolved_org.pk == org_with_quota.pk
