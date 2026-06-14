"""CRM-1D — Customer Directory + Customer Profile (read-only) tests."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.authentication.models import Organization
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.payments.choices import PaymentProvider, PaymentPurpose, PaymentStatus
from apps.payments.models import PaymentTransaction
from apps.platform_admin import selectors
from apps.platform_admin.models import CustomerNote, SupportTicket

pytestmark = pytest.mark.django_db


# ── factories ─────────────────────────────────────────────────────────────────
def _org_user(organization, email, role="junior_auditor", **kw):
    User = get_user_model()
    return User.objects.create_user(
        email=email, password="x", full_name=email.split("@")[0],
        organization=organization, role=role, **kw
    )


def _subscription(organization, status=SubscriptionStatus.ACTIVE):
    plan = Plan.objects.create(
        code=PlanCode.STARTER, name_ar="ستارتر", name_en="Starter",
        invoice_limit=100, price="50.00",
    )
    return OrganizationSubscription.objects.create(
        organization=organization, plan=plan, status=status,
        invoice_limit=100, used_invoices=10, reserved_invoices=5,
    )


def _payment(organization, amount="77.00", status=PaymentStatus.PAID):
    return PaymentTransaction.objects.create(
        organization=organization, provider=PaymentProvider.MOYASAR,
        purpose=PaymentPurpose.SUBSCRIPTION, amount=amount, currency="SAR",
        status=status,
    )


# ══ Selector tests ════════════════════════════════════════════════════════════
def test_list_crm_customers_returns_orgs(organization):
    assert organization in list(selectors.list_crm_customers())


def test_list_crm_customers_search_by_name(organization):
    assert organization in list(selectors.list_crm_customers(q=organization.name[:4]))
    assert list(selectors.list_crm_customers(q="zzz-no-match")) == []


def test_list_crm_customers_search_by_user_email(organization):
    _org_user(organization, "findme@tenant.test")
    results = list(selectors.list_crm_customers(q="findme@tenant"))
    assert organization in results


def test_list_crm_customers_filter_active_inactive(organization):
    assert organization in list(selectors.list_crm_customers(status="active"))
    assert list(selectors.list_crm_customers(status="inactive")) == []


def test_list_crm_customers_filter_country(organization):
    other = next(
        v for v in Organization.Country.values if v != organization.country
    )
    assert organization in list(
        selectors.list_crm_customers(country=organization.country)
    )
    assert list(selectors.list_crm_customers(country=other)) == []


def test_list_crm_customers_filter_subscription(organization):
    _subscription(organization, status=SubscriptionStatus.ACTIVE)
    assert organization in list(selectors.list_crm_customers(subscription="active"))
    assert list(selectors.list_crm_customers(subscription="none")) == []


def test_enrich_customer_rows_sets_display_attrs(organization):
    _org_user(organization, "u1@tenant.test", role="admin")
    _org_user(organization, "u2@tenant.test")
    SupportTicket.objects.create(
        organization=organization, created_by=None, title="t",
        description="d", status=SupportTicket.Status.OPEN,
    )
    _subscription(organization)
    rows = selectors.enrich_customer_rows(
        list(selectors.list_crm_customers()), include_financial=True
    )
    org = rows[0]
    assert org.crm_users_count == 2
    assert org.crm_primary_email == "u1@tenant.test"  # admin preferred
    assert org.crm_open_tickets == 1
    assert org.crm_plan_name == "Starter"


def test_enrich_hides_financial_when_not_permitted(organization):
    _subscription(organization)
    rows = selectors.enrich_customer_rows(
        list(selectors.list_crm_customers()), include_financial=False
    )
    assert rows[0].crm_plan_name is None
    assert rows[0].crm_sub_status is None


def test_subscription_summary_handles_no_subscription(organization):
    assert selectors.get_customer_subscription_summary(organization) is None


def test_subscription_summary_returns_usable(organization):
    sub = _subscription(organization, status=SubscriptionStatus.ACTIVE)
    found = selectors.get_customer_subscription_summary(organization)
    assert found.id == sub.id
    assert found.remaining_invoices == 85  # 100 - 10 - 5


def test_payment_summary_handles_no_payments(organization):
    summary = selectors.get_customer_payment_summary(organization)
    assert summary["transactions"] == []
    assert summary["total_count"] == 0
    assert summary["paid_count"] == 0


def test_payment_summary_counts(organization):
    _payment(organization, status=PaymentStatus.PAID)
    _payment(organization, status=PaymentStatus.FAILED)
    summary = selectors.get_customer_payment_summary(organization)
    assert summary["total_count"] == 2
    assert summary["paid_count"] == 1


def test_profile_bundle_keys_and_financial_gate(organization):
    _subscription(organization)
    _payment(organization)
    full = selectors.get_crm_customer_profile(organization.id, include_financial=True)
    for key in ("organization", "users", "tickets", "notes", "activities", "audits"):
        assert key in full
    assert full["subscription"] is not None
    assert full["payments"] is not None

    gated = selectors.get_crm_customer_profile(organization.id, include_financial=False)
    assert gated["subscription"] is None
    assert gated["payments"] is None


def test_profile_returns_none_for_missing_org():
    import uuid

    assert selectors.get_crm_customer_profile(uuid.uuid4()) is None


# ══ View access tests ═════════════════════════════════════════════════════════
def test_directory_anonymous_redirected(client):
    resp = client.get(reverse("platform_admin:crm:customers"))
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


def test_directory_non_staff_forbidden(client, regular_user):
    client.force_login(regular_user)
    assert client.get(reverse("platform_admin:crm:customers")).status_code == 403


def test_directory_staff_without_group_forbidden(client, staff_no_group):
    client.force_login(staff_no_group)
    assert client.get(reverse("platform_admin:crm:customers")).status_code == 403


@pytest.mark.parametrize("role_fixture", ["owner_user", "readonly_user", "support_user", "finance_user"])
def test_directory_visible_to_crm_roles(client, request, role_fixture):
    user = request.getfixturevalue(role_fixture)
    client.force_login(user)
    assert client.get(reverse("platform_admin:crm:customers")).status_code == 200


def test_directory_renders_customer(client, owner_user, organization):
    _org_user(organization, "x@tenant.test")
    client.force_login(owner_user)
    body = client.get(reverse("platform_admin:crm:customers")).content.decode()
    assert organization.name in body


def test_directory_post_is_405(client, owner_user):
    client.force_login(owner_user)
    assert client.post(reverse("platform_admin:crm:customers")).status_code == 405


# ── Customer profile ─────────────────────────────────────────────────────────
def test_profile_missing_org_404(client, owner_user):
    import uuid

    client.force_login(owner_user)
    url = reverse("platform_admin:crm:customer_detail", args=[uuid.uuid4()])
    assert client.get(url).status_code == 404


def test_profile_renders_tabs(client, owner_user, organization):
    client.force_login(owner_user)
    url = reverse("platform_admin:crm:customer_detail", args=[organization.id])
    body = client.get(url).content.decode()
    # Assert on the Alpine tab identifiers (locale-independent; visible labels
    # are translated when the active language is Arabic).
    for tab in ("overview", "users", "tickets", "notes", "activity", "audit"):
        assert f"tab==='{tab}'" in body


def test_profile_post_is_405(client, owner_user, organization):
    client.force_login(owner_user)
    url = reverse("platform_admin:crm:customer_detail", args=[organization.id])
    assert client.post(url).status_code == 405


# ── Financial gating: Support must NOT see subscription/payment data ──────────
# "Starter" is a DB plan name (never localized); tab==='payments' is the literal
# Alpine marker that only renders when can_view_financial. Both are robust to the
# Arabic test locale (unlike numeric amounts, which get localized digits).
def test_support_agent_cannot_see_financial_data(client, support_user, organization):
    _subscription(organization)  # plan "Starter"
    _payment(organization, amount="77.00")
    client.force_login(support_user)
    body = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    ).content.decode()
    assert "Starter" not in body
    assert "tab==='payments'" not in body
    assert "tab==='subscription'" not in body


def test_finance_officer_can_see_financial_data(client, finance_user, organization):
    _subscription(organization)
    _payment(organization, amount="77.00")
    client.force_login(finance_user)
    body = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    ).content.decode()
    assert "Starter" in body
    assert "tab==='payments'" in body
    assert "tab==='subscription'" in body


# ── Read-only guarantee: no CRM mutation form in rendered HTML ───────────────
# The base layout has a framework language-switcher (POST to /i18n/setlang/) and
# logout — those are not CRM mutations. The guarantee we assert: no POST form
# targets a CRM route, and the CRM filter form is GET.
def test_no_crm_post_forms_in_profile(client, owner_user, organization):
    client.force_login(owner_user)
    body = client.get(
        reverse("platform_admin:crm:customer_detail", args=[organization.id])
    ).content.decode()
    assert 'method="post" action="/platform-admin/crm' not in body
    assert "/platform-admin/crm/customers/" in body  # only safe GET links


def test_directory_filter_form_is_get(client, owner_user, organization):
    client.force_login(owner_user)
    body = client.get(reverse("platform_admin:crm:customers")).content.decode()
    assert 'method="get"' in body  # filter form is read-only GET
    assert 'method="post" action="/platform-admin/crm' not in body
