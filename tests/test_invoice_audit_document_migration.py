"""Regression tests for 0018 applying the conservative invoice-document backfill."""

import importlib

import pytest


@pytest.mark.django_db
def test_backfill_links_only_a_unique_same_organization_document():
    from apps.authentication.models import Organization, User
    from io import StringIO

    from django.core.management import call_command

    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService
    from apps.documents.models import Document
    from apps.invoices.models import Invoice
    from apps.rule_engine.pipeline.v2.compat import run_audit_compat

    migration = importlib.import_module(
        "apps.invoices.migrations.0018_invoice_audit_document_backfill"
    )
    organization = Organization.objects.create(name="Backfill org", name_ar="ملء")
    other_organization = Organization.objects.create(name="Other org", name_ar="أخرى")
    user = User.objects.create_user(
        email="backfill@example.invalid", password="TestPass123!", organization=organization
    )
    exact_document = Document.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="unique.pdf",
        file_size=100,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )
    exact_invoice = Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="unique.pdf",
        file_size=100,
    )
    orphan_invoice = Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="missing.pdf",
        file_size=100,
    )
    ambiguous_invoice = Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="duplicate.pdf",
        file_size=100,
    )
    for _ in range(2):
        Document.objects.create(
            organization=organization,
            uploaded_by=user,
            original_filename="duplicate.pdf",
            file_size=100,
            mime_type="application/pdf",
            document_type=Document.DocumentType.INVOICE,
        )
    cross_org_invoice = Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="cross-org.pdf",
        file_size=100,
    )
    Document.objects.create(
        organization=other_organization,
        original_filename="cross-org.pdf",
        file_size=100,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )

    migration.apply_missed_audit_document_backfill(importlib.import_module("django.apps").apps, None)

    exact_invoice.refresh_from_db()
    orphan_invoice.refresh_from_db()
    ambiguous_invoice.refresh_from_db()
    cross_org_invoice.refresh_from_db()
    assert exact_invoice.audit_document_id == exact_document.id
    assert orphan_invoice.audit_document_id is None
    assert ambiguous_invoice.audit_document_id is None
    assert cross_org_invoice.audit_document_id is None

    call_command("seed_billing_plans", stdout=StringIO())
    pending = SubscriptionService().create_pending_paid_subscription(
        organization, Plan.objects.get(code=PlanCode.STARTER)
    )
    SubscriptionService().activate_subscription(pending)
    audit_run = run_audit_compat(
        document_id=str(exact_invoice.id),
        document_type="sales_invoice",
        organization_id=str(organization.id),
        triggered_by="legacy_reprocess",
        engine_override="v1",
    )
    assert audit_run.status == "completed"


@pytest.mark.django_db
def test_this_guard_can_fail():
    """A missing bridge must fail the real gate before 0018, then recover after it.

    This test deliberately creates fresh rows that no prior migration invocation
    can have touched.  It does not mock the backfill or the quota gate: the
    `UnknownDocumentType` is the production failure that made legacy invoices
    unauditable, and the successful second call proves 0018 repaired that exact
    condition.
    """
    from io import StringIO

    from django.core.management import call_command

    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.quota_gate import UnknownDocumentType, run_audit_with_quota
    from apps.billing.services.subscription_service import SubscriptionService
    from apps.documents.models import Document
    from apps.invoices.models import Invoice

    migration = importlib.import_module(
        "apps.invoices.migrations.0018_invoice_audit_document_backfill"
    )
    organization = Organization.objects.create(
        name="Backfill failure-proof org", name_ar="ملء فشل"
    )
    user = User.objects.create_user(
        email="backfill-failure-proof@example.invalid",
        password="TestPass123!",
        organization=organization,
    )
    document = Document.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="fresh-legacy-invoice.pdf",
        file_size=321,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )
    invoice = Invoice.objects.create(
        organization=organization,
        uploaded_by=user,
        original_filename="fresh-legacy-invoice.pdf",
        file_size=321,
    )
    assert invoice.audit_document_id is None

    call_command("seed_billing_plans", stdout=StringIO())
    pending = SubscriptionService().create_pending_paid_subscription(
        organization, Plan.objects.get(code=PlanCode.STARTER)
    )
    SubscriptionService().activate_subscription(pending)

    with pytest.raises(UnknownDocumentType, match="has no audit_document"):
        run_audit_with_quota(
            document_id=str(invoice.id),
            document_type="sales_invoice",
            organization_id=str(organization.id),
            triggered_by="legacy_reprocess",
            engine_override="v1",
        )

    migration.apply_missed_audit_document_backfill(
        importlib.import_module("django.apps").apps, None
    )
    invoice.refresh_from_db()
    assert invoice.audit_document_id == document.id

    audit_run = run_audit_with_quota(
        document_id=str(invoice.id),
        document_type="sales_invoice",
        organization_id=str(organization.id),
        triggered_by="legacy_reprocess",
        engine_override="v1",
    )
    assert audit_run.status == "completed"
