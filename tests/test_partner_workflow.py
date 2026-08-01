"""Review workflow, approval rules, notifications and exports (Phase 2B §E.7/§F).

The state machine is enforced in the SERVICE layer, so these tests call the
endpoints rather than the model: a check that only exists in the UI is not a
check, and a hand-crafted API call is the thing it has to survive.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from apps.authentication.models import AuditLog, Organization
from apps.partners.models import (
    ApplicationStatus,
    Partner,
    PartnerApplication,
    PartnerStatus,
    PartnerTier,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

ADMIN = "/api/platform-admin/partner-applications/"


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="reviewer@tadgeeg.test", password="StrongPass123!", full_name="Reviewer",
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def org_admin_user(db):
    from io import StringIO

    from django.core.management import call_command

    from apps.billing.services.subscription_service import SubscriptionService

    call_command("seed_billing_plans", stdout=StringIO())
    org = Organization.objects.create(name="Customer Co")
    user = User.objects.create_user(
        email="customer@example.com", password="StrongPass123!",
        full_name="Customer", role=User.Role.ADMIN, organization=org,
    )
    SubscriptionService().create_free_trial(org)
    return user


def make_application(**overrides):
    data = {
        "company_name": "Nile Systems",
        "contact_name": "Sara Ahmed",
        "email": "sara@nile.example",
        "mobile": "+201001234567",
        "country": "EG",
        "requested_partner_type": "distributor",
        "declaration_accepted": True,
        "company_summary": "ERP integrator.",
    }
    data.update(overrides)
    return PartnerApplication.objects.create(**data)


def transition(client, application, action, **payload):
    return client.post(
        f"{ADMIN}{application.id}/{action}/", data=payload, content_type="application/json"
    )


# ═══ permissions, per endpoint, all three identities ═════════════════════════

def _endpoints(application):
    return [
        ("get", ADMIN, None),
        ("get", f"{ADMIN}{application.id}/", None),
        ("post", f"{ADMIN}{application.id}/review/", {}),
        ("post", f"{ADMIN}{application.id}/approve/", {"partner_tier": "gold"}),
        ("post", f"{ADMIN}{application.id}/reject/", {}),
        ("post", f"{ADMIN}{application.id}/notes/", {"note": "x"}),
        ("get", f"{ADMIN}export.xlsx", None),
        ("get", f"{ADMIN}export.pdf", None),
    ]


def test_anonymous_cannot_reach_any_application_endpoint(client):
    application = make_application()
    for method, url, payload in _endpoints(application):
        call = getattr(client, method)
        resp = call(url, data=payload, content_type="application/json") if payload is not None else call(url)
        assert resp.status_code in (401, 403), f"{method.upper()} {url} → {resp.status_code}"


def test_org_admin_role_cannot_reach_any_application_endpoint(client, org_admin_user):
    application = make_application()
    client.force_login(org_admin_user)
    for method, url, payload in _endpoints(application):
        call = getattr(client, method)
        resp = call(url, data=payload, content_type="application/json") if payload is not None else call(url)
        assert resp.status_code == 403, f"{method.upper()} {url} → {resp.status_code}"


def test_staff_can_list_and_read(client, staff_user):
    make_application()
    client.force_login(staff_user)

    listing = client.get(ADMIN)
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    application = PartnerApplication.objects.get()
    detail = client.get(f"{ADMIN}{application.id}/")
    assert detail.status_code == 200
    assert detail.json()["company_name"] == "Nile Systems"


# ═══ state machine ═══════════════════════════════════════════════════════════

def test_submitted_to_under_review(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    assert transition(client, application, "review").status_code == 200
    application.refresh_from_db()
    assert application.status == ApplicationStatus.UNDER_REVIEW


def test_approved_is_terminal(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    assert transition(client, application, "approve", partner_tier="gold").status_code == 200

    for action in ("review", "reject", "approve"):
        resp = transition(client, application, action, partner_tier="gold")
        assert resp.status_code == 409, f"{action} was allowed from a terminal state"


def test_rejected_is_terminal(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    assert transition(client, application, "reject", reason="Not a fit").status_code == 200

    for action in ("review", "approve"):
        resp = transition(client, application, action, partner_tier="gold")
        assert resp.status_code == 409


def test_unknown_action_is_rejected(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    assert transition(client, application, "explode").status_code == 400


# ═══ D3 — approval requires a tier ═══════════════════════════════════════════

def test_approval_without_a_tier_is_refused(client, staff_user):
    """Phase 2A found that a tier-less Technical/Training partner appears in NO
    public section. Requiring a tier at approval closes that hole."""
    application = make_application(requested_partner_type="technical")
    client.force_login(staff_user)

    resp = transition(client, application, "approve")
    assert resp.status_code == 400
    assert "tier" in resp.json()["detail"].lower()

    application.refresh_from_db()
    assert application.status == ApplicationStatus.SUBMITTED
    assert Partner.objects.count() == 0


def test_approval_with_an_invalid_tier_is_refused(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    assert transition(client, application, "approve", partner_tier="diamond").status_code == 400
    assert Partner.objects.count() == 0


def test_approval_creates_a_linked_partner(client, staff_user):
    application = make_application()
    client.force_login(staff_user)

    resp = transition(client, application, "approve", partner_tier="gold")
    assert resp.status_code == 200

    partner = Partner.objects.get()
    assert partner.partner_tier == PartnerTier.GOLD
    assert partner.source_application_id == application.id
    assert partner.company_name == application.company_name
    # Approval is commercial; publication is editorial and stays a separate,
    # audited decision.
    assert partner.status == PartnerStatus.DRAFT


def test_approved_partner_is_not_public_until_published(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    transition(client, application, "approve", partner_tier="gold")

    from apps.partners.selectors import get_public_partners

    assert get_public_partners().count() == 0


def test_approval_carries_contact_details_but_they_stay_unserved(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    transition(client, application, "approve", partner_tier="silver")

    partner = Partner.objects.get()
    assert partner.contact_email == application.email
    assert "contact_email" not in partner.public_payload()


# ═══ audit ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "action,payload,action_type",
    [
        ("review", {}, "partner_application_under_review"),
        ("approve", {"partner_tier": "gold"}, "partner_application_approved"),
        ("reject", {"reason": "no"}, "partner_application_rejected"),
    ],
)
def test_every_transition_is_audited(client, staff_user, action, payload, action_type):
    application = make_application()
    client.force_login(staff_user)
    transition(client, application, action, **payload)

    entry = AuditLog.objects.filter(details__action_type=action_type).first()
    assert entry is not None, f"{action} was not audited"
    assert entry.user_id == staff_user.id
    assert entry.details["old_value"]["status"] == "submitted"


# ═══ notes ═══════════════════════════════════════════════════════════════════

def test_note_is_added_and_never_public(client, staff_user):
    application = make_application()
    client.force_login(staff_user)

    resp = client.post(
        f"{ADMIN}{application.id}/notes/",
        data={"note": "Checked the CR — looks genuine."}, content_type="application/json",
    )
    assert resp.status_code == 201

    client.logout()
    from django.urls import reverse

    body = client.get(reverse("frontend:partners")).content.decode()
    assert "looks genuine" not in body


def test_empty_note_is_rejected(client, staff_user):
    application = make_application()
    client.force_login(staff_user)
    resp = client.post(
        f"{ADMIN}{application.id}/notes/", data={"note": "   "}, content_type="application/json"
    )
    assert resp.status_code == 400


# ═══ email ═══════════════════════════════════════════════════════════════════

def test_approval_sends_an_email(client, staff_user, django_capture_on_commit_callbacks):
    """Mail is scheduled with transaction.on_commit (see notifications.py).

    A test's transaction is rolled back, so on_commit callbacks never fire
    unless captured. Without this fixture the assertion would silently test
    nothing — mail.outbox would be empty because the callback was discarded,
    not because sending failed.
    """
    application = make_application()
    client.force_login(staff_user)
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        transition(client, application, "approve", partner_tier="gold")

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [application.email]
    assert "approved" in message.subject.lower()


def test_rejection_sends_an_email_without_the_internal_reason(
    client, staff_user, django_capture_on_commit_callbacks
):
    application = make_application()
    client.force_login(staff_user)
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        transition(client, application, "reject", reason="Their CR looked dubious to me")

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "dubious" not in body, "the internal rejection reason must not be emailed"
    assert staff_user.email not in body, "the reviewer's identity must not be emailed"
    assert str(application.id) not in body


def test_a_mail_failure_does_not_lose_the_decision(
    client, staff_user, monkeypatch, django_capture_on_commit_callbacks
):
    """Mail is sent on_commit, so it cannot roll the transition back."""
    application = make_application()
    client.force_login(staff_user)

    def boom(*args, **kwargs):
        raise RuntimeError("SMTP is down")

    monkeypatch.setattr(
        "apps.partners.notifications.send_application_decision", boom
    )

    with django_capture_on_commit_callbacks(execute=True):
        resp = transition(client, application, "approve", partner_tier="gold")
    assert resp.status_code == 200

    application.refresh_from_db()
    assert application.status == ApplicationStatus.APPROVED, (
        "an SMTP outage must cost a notification, never the decision"
    )
    assert Partner.objects.count() == 1


# ═══ exports ═════════════════════════════════════════════════════════════════

def test_xlsx_export_respects_filters(client, staff_user):
    from io import BytesIO

    import openpyxl

    make_application(company_name="Egypt Co", country="EG", email="a@x.example")
    make_application(company_name="Saudi Co", country="SA", email="b@x.example")
    client.force_login(staff_user)

    resp = client.get(f"{ADMIN}export.xlsx?country=EG")
    assert resp.status_code == 200
    sheet = openpyxl.load_workbook(BytesIO(resp.content)).active
    names = [row[0] for row in sheet.iter_rows(min_row=2, values_only=True) if row[0]]
    assert names == ["Egypt Co"], f"export ignored the filter: {names}"


def test_exports_exclude_the_submitter_ip(client, staff_user):
    make_application(submitted_ip="203.0.113.9")
    client.force_login(staff_user)
    assert b"203.0.113.9" not in client.get(f"{ADMIN}export.xlsx").content


def test_pdf_export_renders_or_reports_unavailable(client, staff_user):
    make_application()
    client.force_login(staff_user)
    resp = client.get(f"{ADMIN}export.pdf")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert resp.content[:5] == b"%PDF-"


# ═══ admin filters ═══════════════════════════════════════════════════════════

def test_admin_filters(client, staff_user):
    make_application(company_name="Alpha", country="EG", email="a@x.example")
    make_application(company_name="Beta", country="SA", email="b@x.example",
                     requested_partner_type="technical")
    client.force_login(staff_user)

    assert client.get(ADMIN + "?country=EG").json()["count"] == 1
    assert client.get(ADMIN + "?requested_partner_type=technical").json()["count"] == 1
    assert client.get(ADMIN + "?q=Alpha").json()["count"] == 1
    assert client.get(ADMIN + "?status=submitted").json()["count"] == 2
    # Unrecognised values are ignored, not passed to the ORM.
    assert client.get(ADMIN + "?status=bogus").json()["count"] == 2
