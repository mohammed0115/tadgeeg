"""Trial Users Dashboard — permissions, derivation, conversion, exports (§B).

There is NO middleware fronting ``/api/platform-admin/`` (core/namespace_access
defines the prefixes but is absent from MIDDLEWARE), so the view permission
classes are the only access control. Every endpoint is therefore tested for all
three identities rather than sampled.

Time is injected everywhere it matters. Two tests in this repo already flake
because they read the wall clock; the activity buckets will not join them.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from apps.authentication.models import AuditLog, Organization
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.leads.models import TrialLeadProfile
from apps.leads.trial_selectors import (
    ActivityBucket,
    TrialStatus,
    annotate_activity,
    base_queryset,
    build_summary,
    get_dashboard_queryset,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

SUMMARY = "/api/platform-admin/trial-users/summary/"
LIST = "/api/platform-admin/trial-users/"
XLSX = "/api/platform-admin/trial-users/export.xlsx"
PDF = "/api/platform-admin/trial-users/export.pdf"

ENDPOINTS = [SUMMARY, LIST, XLSX, PDF]


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff@tadgeeg.test", password="StrongPass123!", full_name="Staff",
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def org_admin_user(db, plans):
    """A customer. Gets Role.ADMIN, exactly like every self-service registrant.

    Given a usable subscription deliberately: without one,
    SubscriptionRequiredMiddleware answers 402 before the request reaches the
    view, and the permission assertions below would pass because of the billing
    wall rather than because the permission class works. The point of these
    tests is the permission class.
    """
    from apps.billing.services.subscription_service import SubscriptionService

    org = Organization.objects.create(name="Customer Co")
    user = User.objects.create_user(
        email="customer@example.com", password="StrongPass123!",
        full_name="Customer", role=User.Role.ADMIN, organization=org,
    )
    SubscriptionService().create_free_trial(org)
    return user


def make_lead(email, *, country="SA", benefit="company", last_login=None,
              used_invoices=0, subscription=None, plan_code=None):
    org = Organization.objects.create(name=f"Org {email}")
    user = User.objects.create_user(
        email=email, password="StrongPass123!", full_name=f"User {email}",
        role=User.Role.ADMIN, organization=org,
    )
    if last_login is not None:
        user.last_login = last_login
        user.save(update_fields=["last_login"])

    if subscription is not None:
        plan = Plan.objects.get(code=plan_code or PlanCode.FREE_TRIAL)
        now = timezone.now()
        OrganizationSubscription.objects.create(
            organization=org, plan=plan, status=subscription,
            starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29),
            invoice_limit=plan.invoice_limit, used_invoices=used_invoices,
        )

    return TrialLeadProfile.objects.create(
        user=user, country=country, primary_benefit=benefit,
    )


# ── permission matrix: the only access control on this prefix ────────────────

@pytest.mark.parametrize("path", ENDPOINTS)
def test_anonymous_is_rejected(client, path):
    assert client.get(path).status_code in (401, 403)


@pytest.mark.parametrize("path", ENDPOINTS)
def test_org_admin_role_is_forbidden(client, org_admin_user, path):
    client.force_login(org_admin_user)
    resp = client.get(path)
    assert resp.status_code == 403, (
        f"{path} returned {resp.status_code} to a non-staff user with role='admin'. "
        "Every registrant has that role."
    )


@pytest.mark.parametrize("path", [SUMMARY, LIST])
def test_staff_reaches_the_view_body(client, staff_user, path):
    client.force_login(staff_user)
    resp = client.get(path)
    assert resp.status_code == 200, resp.content[:300]
    resp.json()


def test_convert_endpoint_rejects_non_staff(client, org_admin_user, plans):
    lead = make_lead("lead@example.com")
    client.force_login(org_admin_user)
    resp = client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "starter"}, content_type="application/json",
    )
    assert resp.status_code == 403


def test_convert_endpoint_rejects_anonymous(client, plans):
    lead = make_lead("lead@example.com")
    resp = client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "starter"}, content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ── D3 activity buckets, with time pinned ────────────────────────────────────

def test_activity_never_started(plans):
    make_lead("never@example.com", last_login=None)
    now = timezone.now()
    row = annotate_activity(base_queryset(), now=now).get()
    assert row.activity == ActivityBucket.NEVER_STARTED


def test_activity_active_requires_recent_login_and_an_invoice(plans):
    now = timezone.now()
    make_lead(
        "active@example.com", last_login=now - timedelta(days=2),
        used_invoices=3, subscription=SubscriptionStatus.TRIALING,
    )
    row = annotate_activity(base_queryset(), now=now).get()
    assert row.invoices_used == 3
    assert row.activity == ActivityBucket.ACTIVE


def test_recent_login_without_invoices_is_idle_not_active(plans):
    now = timezone.now()
    make_lead(
        "nouse@example.com", last_login=now - timedelta(days=1),
        used_invoices=0, subscription=SubscriptionStatus.TRIALING,
    )
    row = annotate_activity(base_queryset(), now=now).get()
    assert row.activity == ActivityBucket.IDLE


def test_stale_login_is_idle_even_with_invoices(plans):
    now = timezone.now()
    make_lead(
        "stale@example.com", last_login=now - timedelta(days=40),
        used_invoices=99, subscription=SubscriptionStatus.TRIALING,
    )
    row = annotate_activity(base_queryset(), now=now).get()
    assert row.activity == ActivityBucket.IDLE


def test_activity_boundary_is_evaluated_against_injected_now(plans):
    """Same row, two different 'now' values, two different buckets."""
    login_at = timezone.now() - timedelta(days=5)
    make_lead(
        "boundary@example.com", last_login=login_at,
        used_invoices=1, subscription=SubscriptionStatus.TRIALING,
    )
    early = annotate_activity(base_queryset(), now=login_at + timedelta(days=1)).get()
    assert early.activity == ActivityBucket.ACTIVE

    later = annotate_activity(base_queryset(), now=login_at + timedelta(days=30)).get()
    assert later.activity == ActivityBucket.IDLE


# ── trial status derivation (ADR 0002) ───────────────────────────────────────

def test_status_is_derived_not_stored(plans):
    make_lead("t@example.com", subscription=SubscriptionStatus.TRIALING)
    assert base_queryset().get().trial_status == TrialStatus.TRIALING
    # No status column exists on the model.
    assert not hasattr(TrialLeadProfile, "trial_status_field")
    assert "trial_status" not in [f.name for f in TrialLeadProfile._meta.get_fields()]


def test_status_no_subscription(plans):
    make_lead("none@example.com")
    assert base_queryset().get().trial_status == TrialStatus.NO_SUBSCRIPTION


def test_status_expired(plans):
    make_lead("e@example.com", subscription=SubscriptionStatus.EXPIRED)
    assert base_queryset().get().trial_status == TrialStatus.EXPIRED


def test_status_paid_takes_precedence_over_a_superseded_trial(plans):
    lead = make_lead("p@example.com", subscription=SubscriptionStatus.EXPIRED)
    starter = Plan.objects.get(code=PlanCode.STARTER)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=lead.user.organization, plan=starter,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now, ends_at=now + timedelta(days=30),
        invoice_limit=starter.invoice_limit,
    )
    assert base_queryset().get().trial_status == TrialStatus.PAID


# ── summary + filters ────────────────────────────────────────────────────────

def test_summary_groups_by_country_and_client_type(plans):
    make_lead("a@example.com", country="SA", benefit="company")
    make_lead("b@example.com", country="SA", benefit="accountant")
    make_lead("c@example.com", country="AE", benefit="company")

    summary = build_summary(get_dashboard_queryset())
    assert summary["total"] == 3
    assert dict((r["value"], r["count"]) for r in summary["by_country"]) == {"SA": 2, "AE": 1}
    assert dict((r["value"], r["count"]) for r in summary["by_client_type"]) == {
        "company": 2, "accountant": 1,
    }


def test_filters_narrow_the_queryset(plans):
    make_lead("a@example.com", country="SA")
    make_lead("b@example.com", country="AE")
    assert get_dashboard_queryset(country="SA").count() == 1
    assert get_dashboard_queryset(country="AE").count() == 1
    # An unrecognised value is ignored rather than passed to the ORM.
    assert get_dashboard_queryset(country="ZZ").count() == 2


def test_summary_endpoint_reports_filters(client, staff_user, plans):
    make_lead("a@example.com", country="SA")
    make_lead("b@example.com", country="AE")
    client.force_login(staff_user)
    body = client.get(SUMMARY + "?country=SA").json()
    assert body["total"] == 1
    assert body["filters_applied"]["country"] == "SA"


def test_list_endpoint_never_returns_the_registration_ip(client, staff_user, plans):
    lead = make_lead("ip@example.com")
    TrialLeadProfile.objects.filter(pk=lead.pk).update(registered_ip="203.0.113.9")

    client.force_login(staff_user)
    body = client.get(LIST).json()
    assert body["count"] == 1
    assert "registered_ip" not in body["results"][0], "ADR 0004 §2 — IP must not leave the admin"
    assert "203.0.113.9" not in client.get(LIST).content.decode()


# ── exports ──────────────────────────────────────────────────────────────────

def test_xlsx_export_is_a_workbook(client, staff_user, plans):
    make_lead("x@example.com")
    client.force_login(staff_user)
    resp = client.get(XLSX)
    assert resp.status_code == 200
    assert "spreadsheetml" in resp["Content-Type"]
    assert resp.content[:2] == b"PK", "xlsx is a zip container"


def test_xlsx_export_respects_filters(client, staff_user, plans):
    import openpyxl

    make_lead("sa@example.com", country="SA")
    make_lead("ae@example.com", country="AE")
    client.force_login(staff_user)

    resp = client.get(XLSX + "?country=SA")
    from io import BytesIO
    sheet = openpyxl.load_workbook(BytesIO(resp.content)).active
    emails = [row[1] for row in sheet.iter_rows(min_row=2, values_only=True) if row[1]]
    assert emails == ["sa@example.com"], (
        "The export dumped rows outside the active filter — a data-exposure bug."
    )


def test_xlsx_export_excludes_the_ip_column(client, staff_user, plans):
    lead = make_lead("ip2@example.com")
    TrialLeadProfile.objects.filter(pk=lead.pk).update(registered_ip="203.0.113.9")
    client.force_login(staff_user)
    assert b"203.0.113.9" not in client.get(XLSX).content


def test_pdf_export_renders_or_reports_unavailable(client, staff_user, plans):
    """WeasyPrint is present here, but a slimmer image may lack its system
    libraries — in which case 503, never 500."""
    make_lead("p@example.com")
    client.force_login(staff_user)
    resp = client.get(PDF)
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert resp["Content-Type"] == "application/pdf"
        assert resp.content[:5] == b"%PDF-"


# ── conversion (STEP 6) ──────────────────────────────────────────────────────

def test_conversion_activates_a_paid_subscription(client, staff_user, plans):
    lead = make_lead("conv@example.com", subscription=SubscriptionStatus.TRIALING)
    client.force_login(staff_user)

    resp = client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "starter"}, content_type="application/json",
    )
    assert resp.status_code == 201, resp.content[:300]

    sub = OrganizationSubscription.objects.get(
        organization=lead.user.organization, plan__code=PlanCode.STARTER,
    )
    assert sub.status == SubscriptionStatus.ACTIVE
    assert base_queryset().get().trial_status == TrialStatus.PAID


def test_conversion_writes_an_audit_record(client, staff_user, plans):
    lead = make_lead("audit@example.com", subscription=SubscriptionStatus.TRIALING)
    client.force_login(staff_user)
    client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "starter"}, content_type="application/json",
    )

    entry = AuditLog.objects.filter(
        organization=lead.user.organization,
        details__action_type="trial_converted_to_paid",
    ).first()
    assert entry is not None, "conversion must be audited"
    assert entry.user_id == staff_user.id, "the audit must name the actor"
    assert entry.details["new_value"]["plan"] == "starter"
    assert entry.details["metadata"]["payment_taken"] is False


def test_double_conversion_is_refused(client, staff_user, plans):
    lead = make_lead("double@example.com", subscription=SubscriptionStatus.TRIALING)
    client.force_login(staff_user)
    url = f"/api/platform-admin/trial-users/{lead.id}/convert/"

    first = client.post(url, data={"plan_code": "starter"}, content_type="application/json")
    assert first.status_code == 201

    second = client.post(url, data={"plan_code": "business"}, content_type="application/json")
    assert second.status_code == 409, "a second conversion must be refused, not silently applied"

    paid = OrganizationSubscription.objects.filter(
        organization=lead.user.organization,
        status=SubscriptionStatus.ACTIVE, plan__is_trial=False,
    )
    assert paid.count() == 1, "double-conversion created a second paid subscription"


def test_conversion_rejects_a_trial_plan(client, staff_user, plans):
    lead = make_lead("badplan@example.com")
    client.force_login(staff_user)
    resp = client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "free_trial"}, content_type="application/json",
    )
    assert resp.status_code == 400


def test_conversion_requires_a_plan_code(client, staff_user, plans):
    lead = make_lead("noplan@example.com")
    client.force_login(staff_user)
    resp = client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={}, content_type="application/json",
    )
    assert resp.status_code == 400


def test_conversion_does_not_change_plan_pricing(client, staff_user, plans):
    """Conversion must not mutate the catalogue."""
    before = {p.code: (p.price, p.invoice_limit) for p in Plan.objects.all()}
    lead = make_lead("price@example.com", subscription=SubscriptionStatus.TRIALING)
    client.force_login(staff_user)
    client.post(
        f"/api/platform-admin/trial-users/{lead.id}/convert/",
        data={"plan_code": "starter"}, content_type="application/json",
    )
    after = {p.code: (p.price, p.invoice_limit) for p in Plan.objects.all()}
    assert before == after


# ── page shell ───────────────────────────────────────────────────────────────

def test_dashboard_page_requires_staff(client, org_admin_user):
    client.force_login(org_admin_user)
    resp = client.get("/platform-admin/trial-users/")
    assert resp.status_code in (302, 403)


def test_dashboard_page_renders_for_staff(client, staff_user, plans):
    client.force_login(staff_user)
    resp = client.get("/platform-admin/trial-users/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "trialUsersDashboard()" in body
    # The approved layout's action bar (§L.5). The export URLs are built from a
    # template literal, so assert on the builder and its call sites rather than
    # on a concatenated string that never appears in the source.
    assert "trial-users/export." in body
    assert "exportUrl('xlsx')" in body and "exportUrl('pdf')" in body
    assert "Convert to paid customer" in body
