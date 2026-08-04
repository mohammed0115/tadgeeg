"""The payment gateway's words are for the log, not for the customer.

Moyasar answered a misconfigured credential with «You provided your secret key
ID instead of the full secret key». That sentence reached the customer's
browser in an alert(): it names our infrastructure, tells an attacker which
credential is wrong, and means nothing to someone trying to buy a plan.

What replaces it has to satisfy three parties at once — the customer needs an
action, support needs to find the incident, and an attacker must learn nothing.
A random reference code in both the response and the log does all three.
"""

import re
from pathlib import Path
from unittest import mock

import pytest
from rest_framework.test import APIClient

BASE_DIR = Path(__file__).resolve().parents[1]

GATEWAY_SECRET_LEAK = (
    "You provided your secret key ID instead of the full secret key. "
    "Use sk_live_XXXXXXXXXXXX from the Moyasar dashboard."
)


@pytest.fixture
def paid_plan(db):
    """A real PlanCode — the serializer whitelists them, and rightly so."""
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan

    plan, _ = Plan.objects.get_or_create(
        code=PlanCode.PROFESSIONAL,
        defaults=dict(
            name_en="Professional", name_ar="احترافي",
            price=499, currency="SAR", invoice_limit=500, user_limit=10,
            is_active=True,
        ),
    )
    return plan


@pytest.fixture
def failing_gateway():
    from apps.payments.gateways.base import GatewayError

    with mock.patch(
        "apps.payments.services.payment_service.PaymentService.create_transaction",
        side_effect=GatewayError(GATEWAY_SECRET_LEAK),
    ) as patched:
        yield patched


def _select_plan(admin_user, plan):
    client = APIClient()
    client.force_authenticate(admin_user)
    return client.post("/billing/select-plan/", {"plan_code": plan.code}, format="json")


@pytest.mark.django_db
def test_the_gateway_message_never_reaches_the_customer(admin_user, paid_plan, failing_gateway):
    response = _select_plan(admin_user, paid_plan)
    body = str(response.data)

    assert "secret key" not in body.lower()
    assert "sk_live" not in body
    assert "Moyasar" not in body


@pytest.mark.django_db
def test_the_customer_gets_an_action_and_a_reference(admin_user, paid_plan, failing_gateway):
    response = _select_plan(admin_user, paid_plan)

    assert response.status_code == 502
    assert re.fullmatch(r"[0-9a-f]{12}", response.data["reference"]), \
        "reference must be a short opaque code"
    assert response.data["reference"] in str(response.data["detail"]), \
        "the customer cannot quote a reference that is not in the message"


@pytest.mark.django_db
def test_the_full_gateway_detail_is_logged_against_that_reference(
    admin_user, paid_plan, failing_gateway, caplog
):
    """Support must be able to go from the customer's code to the cause."""
    with caplog.at_level("ERROR", logger="billing.views"):
        response = _select_plan(admin_user, paid_plan)

    reference = response.data["reference"]
    matching = [r for r in caplog.records if reference in r.getMessage()]
    assert matching, f"nothing logged under reference {reference}"

    logged = matching[0].getMessage()
    assert "secret key" in logged, "the log lost the detail that explains the failure"
    assert str(admin_user.organization_id) in logged
    assert matching[0].exc_info is not None, "logged without a traceback"


@pytest.mark.django_db
def test_two_failures_get_different_references(admin_user, paid_plan, failing_gateway):
    """A reference derived from the subscription would be guessable, and would
    also collapse separate incidents into one code."""
    first = _select_plan(admin_user, paid_plan).data["reference"]
    second = _select_plan(admin_user, paid_plan).data["reference"]
    assert first != second


# ── The template side ─────────────────────────────────────────────────────────

def test_the_plans_page_no_longer_alerts_the_server_response():
    source = (BASE_DIR / "templates/billing/plans.html").read_text(encoding="utf-8")
    assert "alert(data.detail" not in source
    assert "alert(\"Network error: \" + err.message)" not in source


def test_the_error_is_rendered_as_text_not_markup():
    """innerHTML on a server-supplied string is an injection sink.

    Comments are stripped first: a previous version of this assertion matched
    the word inside the comment that explains why innerHTML is not used, which
    is the same false positive that made me misreport the CSP earlier today.
    """
    source = (BASE_DIR / "templates/billing/plans.html").read_text(encoding="utf-8")
    helper = source.split("function showPlanError")[1].split("\n    }")[0]
    code_only = re.sub(r"//.*", "", helper)
    assert "textContent" in code_only
    assert "innerHTML" not in code_only


def test_the_error_region_is_announced_to_screen_readers():
    source = (BASE_DIR / "templates/billing/plans.html").read_text(encoding="utf-8")
    assert 'role="alert"' in source and 'aria-live' in source
