"""The official invoice upload must remain pinned to V1 until a measured switch.

This file intentionally enters through ``/api/v1/invoices/upload/``.  A direct
call to ``run_audit_compat`` cannot establish what the upload dispatcher
actually passes to Celery, which is the regression this guard exists to catch.
"""

import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient


@pytest.fixture
def upload_actor(db):
    """A fresh organisation, user, and paid subscription for one upload only."""
    from django.utils import timezone

    from apps.authentication.models import Organization, User
    from apps.billing.choices import PlanCode, SubscriptionStatus
    from apps.billing.models import OrganizationSubscription, Plan

    org = Organization.objects.create(
        name="Upload Generation Pin Co",
        name_ar="منشأة تثبيت الرفع",
    )
    plan, _ = Plan.objects.get_or_create(
        code=PlanCode.BUSINESS,
        defaults={
            "name_ar": "خطة اختبار",
            "name_en": "Test Plan",
            "invoice_limit": 1000,
            "user_limit": 10,
        },
    )
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now - timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=30),
        invoice_limit=getattr(plan, "invoice_limit", None) or 1000,
        user_limit=getattr(plan, "user_limit", None) or 10,
        used_invoices=0,
    )
    user = User.objects.create_user(
        email=f"upload-pin-{uuid.uuid4().hex[:8]}@example.com",
        password="UploadPin!12345",
        organization=org,
    )
    return org, user


def _upload(client, invoice_number: str):
    """Use the production HTTP entrypoint with one already-structured invoice."""
    csv_body = (
        "invoice_number,vendor_name,invoice_date,subtotal,vat_amount,total_amount,currency\n"
        f"{invoice_number},Pin Generation Supplier,2026-08-14,1000,150,1150,SAR\n"
    )
    uploaded = SimpleUploadedFile(
        f"{invoice_number}.csv",
        csv_body.encode("utf-8"),
        content_type="text/csv",
    )
    return client.post("/api/v1/invoices/upload/", {"file": uploaded}, format="multipart")


def _saved_run(org, invoice_number: str):
    """Return the persisted run for the invoice created by the HTTP upload."""
    from apps.invoices.models import Invoice
    from apps.rule_engine.models import AuditRun

    invoice = Invoice.objects.get(organization=org, invoice_number=invoice_number)
    run = AuditRun.objects.filter(
        organization_id=org.id,
        document_id=invoice.id,
        document_type="sales_invoice",
    ).latest("started_at")
    run.refresh_from_db()  # Never assert a potentially stale AuditRun instance.
    return run


@pytest.mark.django_db(transaction=True)
def test_the_upload_path_pins_v1(upload_actor):
    """🔴 A production upload persists V1 (``engine_version == '2.0'``).

    The assertion is deliberately about the stored ``AuditRun`` rather than
    the Celery call arguments: it fails when the dispatcher drops the override
    and the configured V2 default takes over.
    """
    org, user = upload_actor
    client = APIClient()
    client.force_authenticate(user=user)

    response = _upload(client, "UPLOAD-PIN-V1-001")

    assert response.status_code == 201, response.content[:500]
    assert response.data["failed"] == 0, response.data
    run = _saved_run(org, "UPLOAD-PIN-V1-001")
    assert str(run.engine_version) == "2.0", (
        f"engine_version = {run.engine_version!r}, not '2.0': the upload path "
        "lost engine_override='v1'.  A generation change must be deliberate, "
        "measured, and accompanied by an update to this guard."
    )


@pytest.mark.django_db(transaction=True)
def test_this_guard_can_fail(upload_actor, monkeypatch):
    """Removing the upload override produces a different persisted generation.

    The HTTP upload remains real; only the task object's ``delay`` adapter is
    temporarily made to discard the one value the production regression lost.
    The original eager task then executes unpinned, proving the primary guard
    observes the override instead of merely reading its source text.
    """
    from apps.rule_engine.tasks.audit_tasks_v2 import run_audit_compat_task

    org, user = upload_actor
    client = APIClient()
    client.force_authenticate(user=user)
    original_delay = run_audit_compat_task.delay

    def _without_override(*args, **kwargs):
        kwargs.pop("engine_override", None)
        return original_delay(*args, **kwargs)

    monkeypatch.setattr(run_audit_compat_task, "delay", _without_override)
    response = _upload(client, "UPLOAD-PIN-UNPINNED-001")

    assert response.status_code == 201, response.content[:500]
    assert response.data["failed"] == 0, response.data
    unpinned = _saved_run(org, "UPLOAD-PIN-UNPINNED-001")
    assert str(unpinned.engine_version) != "2.0", (
        "Discarding engine_override='v1' left the upload on V1, so the "
        "primary upload-generation guard does not measure the pin it claims "
        "to protect."
    )
