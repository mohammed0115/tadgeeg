"""The executive report is scoped by organisation, and absence of one refuses.

`ExecutiveReportDetailView._fetch_document_audit_data` carried a comment saying
the scope filter existed because without it the method handed another company's
invoice number, totals and audit scores to any authenticated caller. The code
under the comment applied the filter conditionally:

    scoped = Invoice.objects.all()
    if organization is not None:
        scoped = scoped.filter(organization=organization)

which is the opposite of a scope filter: the one case it skips is the case with
no scope to enforce. A caller with no organisation — an authenticated user who
has none, or AnonymousUser through the template view — got the unfiltered
queryset. It is the same shape as the other defects in this repository: a claim
that reads as protection and is not one.

Nothing routed the view, so it was latent. These guards exist because routing
it is the next shipment, and a conditional filter on a routed endpoint is an
IDOR on a financial platform. The routing does not land until they are green.

`permission_classes = [IsAuthenticated]` is asserted here too, but it is not
what closes this: the leak was reachable *while authenticated*. Authentication
says who is asking. The filter says what they may read.
"""

import uuid

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.authentication.models import Organization, User
from apps.invoices.models import Invoice
from apps.reports.executive_report_views import (
    ExecutiveReportDetailView,
    executive_report_view,
)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Scope Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Scope Org B")


@pytest.fixture
def user_a(db, org_a):
    return User.objects.create_user(
        email="scope-a@test.local", full_name="Scope A", password="x",
        organization=org_a, role=User.Role.ADMIN,
    )


@pytest.fixture
def user_b(db, org_b):
    return User.objects.create_user(
        email="scope-b@test.local", full_name="Scope B", password="x",
        organization=org_b, role=User.Role.ADMIN,
    )


@pytest.fixture
def orphan_user(db, org_a):
    """Authenticated, and belonging to nothing. This is the caller that leaked."""
    user = User.objects.create_user(
        email="scope-orphan@test.local", full_name="Scope Orphan", password="x",
        organization=org_a, role=User.Role.ADMIN,
    )
    User.objects.filter(pk=user.pk).update(organization=None)
    user.refresh_from_db()
    assert user.organization is None
    return user


@pytest.fixture
def invoice_b(db, org_b, user_b):
    """The row a caller from org A must never see."""
    return Invoice.objects.create(
        organization=org_b, uploaded_by=user_b,
        invoice_number="INV-SECRET-B", vendor_name="VendorB",
        total_amount=4321, original_filename="b.pdf",
    )


@pytest.fixture
def invoice_a(db, org_a, user_a):
    return Invoice.objects.create(
        organization=org_a, uploaded_by=user_a,
        invoice_number="INV-OWN-A", vendor_name="VendorA",
        total_amount=1234, original_filename="a.pdf",
    )


def _call(user, document_id, document_type="invoice"):
    request = APIRequestFactory().get("/unrouted/")
    force_authenticate(request, user=user)
    return ExecutiveReportDetailView.as_view()(
        request, document_type=document_type, document_id=str(document_id)
    )


# ── The scope decisions ──────────────────────────────────────────────────────


def test_another_tenants_invoice_is_not_found(user_a, invoice_b):
    """404, not 403: "exists but is not yours" is itself information."""
    response = _call(user_a, invoice_b.id)

    assert response.status_code == 404
    assert "INV-SECRET-B" not in str(response.data)
    assert "VendorB" not in str(response.data)


def test_a_missing_invoice_and_a_foreign_one_answer_alike(user_a, invoice_b):
    """A probe must not be able to tell the two apart."""
    foreign = _call(user_a, invoice_b.id)
    absent = _call(user_a, uuid.uuid4())

    assert foreign.status_code == absent.status_code == 404


def test_a_caller_with_no_organization_is_refused(orphan_user, invoice_b):
    """The exact caller the conditional let through."""
    response = _call(orphan_user, invoice_b.id)

    assert response.status_code == 403
    assert "INV-SECRET-B" not in str(response.data)


def test_no_organization_means_no_rows_at_the_method_too(invoice_b):
    """The refusal lives in the method, not only in the view above it.

    Whatever eventually calls this — a URLconf, a template view, a management
    command — cannot obtain rows without a scope.
    """
    with pytest.raises(PermissionDenied):
        ExecutiveReportDetailView()._fetch_document_audit_data(
            "invoice", str(invoice_b.id), organization=None
        )


def test_the_owner_gets_the_report(user_a, invoice_a):
    """Positive control, and it must assert 200.

    This started as `assert status not in (403, 404)`, on the reasoning that a
    200 also depends on the AI generator. A 400 satisfies that assertion, and a
    400 is exactly what the endpoint returned: the metadata block calls
    audit_date.isoformat() on a value this view had already turned into a
    string, so every request for a caller's own invoice failed. Driving it in a
    browser found it; this test had passed throughout.

    A positive control that accepts an error is not a positive control.
    """
    response = _call(user_a, invoice_a.id)

    assert response.status_code == 200, response.data
    assert response.data["status"] == "success"
    assert response.data["metadata"]["generated_at"]


def test_the_owners_row_is_the_one_fetched(user_a, invoice_a, invoice_b):
    fetched = ExecutiveReportDetailView()._fetch_document_audit_data(
        "invoice", str(invoice_a.id), organization=user_a.organization
    )

    assert fetched["document_number"] == "INV-OWN-A"


def test_the_template_view_refuses_an_anonymous_caller(db, invoice_b):
    """AnonymousUser has no `organization`, which is how it reached the leak.

    executive_report_view instantiates the API view and calls .get() directly,
    so it bypasses permission_classes entirely — another reason the filter, not
    the permission, is what closes this.
    """
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    request = RequestFactory().get("/unrouted/")
    request.user = AnonymousUser()

    response = executive_report_view(request, "invoice", str(invoice_b.id))

    assert response.status_code != 200
    assert b"INV-SECRET-B" not in response.content


def test_the_permission_class_is_stated_not_inherited():
    """A settings change must not be able to open this endpoint silently."""
    assert IsAuthenticated in ExecutiveReportDetailView.permission_classes


# ── The planted defect ───────────────────────────────────────────────────────


def test_the_shipped_conditional_handed_over_another_tenants_row(
    monkeypatch, orphan_user, invoice_b
):
    """Put the two lines back, unmodified, and watch the guard above go quiet.

    Patched onto the class rather than edited into the file, and written out
    rather than mocked — a mock would prove only that a mock returns what it
    was told to. This is the real queryset against real rows.
    """

    def _as_shipped(self, document_type, document_id, organization=None):
        scoped = Invoice.objects.all()
        if organization is not None:                      # the line as shipped
            scoped = scoped.filter(organization=organization)
        invoice = scoped.get(id=document_id)
        return {"document_number": invoice.invoice_number,
                "company": str(invoice.organization),
                "total_amount": float(invoice.total_amount)}

    monkeypatch.setattr(
        ExecutiveReportDetailView, "_fetch_document_audit_data", _as_shipped
    )

    leaked = ExecutiveReportDetailView()._fetch_document_audit_data(
        "invoice", str(invoice_b.id), organization=None
    )

    assert leaked["document_number"] == "INV-SECRET-B", (
        "the shipped conditional no longer returns a foreign row, so the guard "
        "above is no longer distinguishing anything"
    )
    assert leaked["total_amount"] == 4321.0


def test_only_the_patched_version_leaks(orphan_user, invoice_b):
    """Same call, unpatched. The contrast is the whole point of the test above."""
    with pytest.raises((PermissionDenied, NotFound)):
        ExecutiveReportDetailView()._fetch_document_audit_data(
            "invoice", str(invoice_b.id), organization=None
        )
