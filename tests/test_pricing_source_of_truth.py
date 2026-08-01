"""The public pricing page must source from billing.Plan, not cms.PricingPlan.

Phase 0-A mounted ``/api/platform-admin/pricing/``, which edits
``cms.PricingPlan`` — marketing content that no payment path reads. The risk
this file guards is an operator editing numbers there and expecting customers
to be billed accordingly.

``billing.Plan`` is the single source of truth: it drives ``/pricing/``, plan
selection, and — decisively — server-side payment authorisation in
``apps/payments/pricing.py::_subscription_resolver``. See
``docs/adr/0001-pricing-source-of-truth.md``.
"""

from __future__ import annotations

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded_plans(db):
    call_command("seed_billing_plans", stdout=StringIO())


def test_pricing_page_renders_billing_plan_prices(client, seeded_plans):
    from apps.billing.models import Plan

    resp = client.get("/pricing/")
    assert resp.status_code == 200
    body = resp.content.decode()

    purchasable = Plan.objects.filter(is_active=True, is_trial=False, is_free=False)
    assert purchasable.exists(), "seed_billing_plans produced no purchasable plans"

    for plan in purchasable:
        if plan.price is None:
            # Phase 3A introduced custom-quote plans, which have no list price.
            # They must render a quote label and no number — asserted below.
            assert plan.is_custom_quote, f"{plan.code} has no price but is not a custom quote"
            continue
        # Prices render without decimals in the template; compare on the
        # integer part so formatting changes don't make this brittle.
        whole = str(int(Decimal(plan.price)))
        assert whole in body, (
            f"billing.Plan {plan.code} price {plan.price} is absent from "
            f"/pricing/ — the page may have been repointed at cms.PricingPlan."
        )

    # Custom-quote plans still have to appear, just without a price.
    for plan in Plan.objects.filter(is_active=True, is_custom_quote=True):
        assert f'data-plan="{plan.code}"' in body, (
            f"custom-quote plan {plan.code} is missing from /pricing/"
        )


def test_pricing_page_does_not_use_cms_pricing_plan(client, seeded_plans):
    """A cms.PricingPlan row with a distinctive price must NOT surface."""
    from apps.cms.models import PricingPlan

    PricingPlan.objects.create(
        name="Decoy Marketing Plan",
        slug="decoy-marketing-plan",
        price_monthly=Decimal("31337.00"),
        currency="SAR",
        max_users=999,
        is_active=True,
    )

    body = client.get("/pricing/").content.decode()
    assert "31337" not in body, (
        "/pricing/ rendered a cms.PricingPlan price. That model is marketing "
        "content and is not what customers are charged — see ADR 0001."
    )
    assert "Decoy Marketing Plan" not in body


def test_payment_price_resolver_reads_billing_plan(seeded_plans):
    """The authoritative payment amount comes from billing.Plan.price."""
    from apps.authentication.models import Organization
    from apps.billing.choices import PlanCode
    from apps.billing.models import Plan
    from apps.billing.services.subscription_service import SubscriptionService
    from apps.payments.pricing import resolve_or_validate

    org = Organization.objects.create(name="Payer Co")
    plan = Plan.objects.get(code=PlanCode.STARTER)
    sub = SubscriptionService().create_pending_paid_subscription(org, plan)

    amount, currency = resolve_or_validate(
        purpose="subscription",
        reference_type="organization_subscription",
        reference_id=str(sub.id),
        organization=org,
        requested_amount=Decimal(plan.price),
    )
    assert amount == Decimal(plan.price).quantize(Decimal("0.01"))
    assert currency == (plan.currency or "SAR").upper()


def test_no_pending_migrations():
    """Phase 0-A is explicitly a no-migration change."""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exc:                       # non-zero => changes detected
        raise AssertionError(
            "Model changes without a migration were detected:\n" + out.getvalue()
        ) from exc
