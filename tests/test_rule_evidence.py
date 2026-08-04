"""A rule that fires must say which field, what it found, and what it wanted.

Findings used to carry one Arabic sentence: «الضريبة 99 لا تطابق المتوقع 15».
That reads well and is useless to everything else — a UI cannot highlight the
offending field from prose, `rule_precision` cannot group misfires by field,
and an auditor deciding whether the engine was right has to parse a sentence
per finding.

So `_rule()` now also carries `field` / `actual` / `expected`. Absent keys, not
nulls: a rule with no structured evidence must say nothing rather than claim
`actual=None`, which is the same unmeasured-is-not-zero distinction the quota
and precision code keeps.
"""

from datetime import date
from decimal import Decimal

import pytest

from core.services.invoice_validator import _rule, run_all_rules


# ── The helper's contract ────────────────────────────────────────────────────

def test_evidence_keys_are_absent_rather_than_null_when_unknown():
    result = _rule(False, "desc", "msg")
    assert "field" not in result
    assert "actual" not in result
    assert "expected" not in result


def test_a_zero_actual_is_still_recorded():
    """`if actual is not None` — not `if actual`. 0 is a finding, not a blank."""
    assert _rule(False, "d", "m", field="total_amount", actual=0)["actual"] == 0


def test_passing_rules_are_downgraded_to_info():
    assert _rule(True, "d", "m", severity="critical")["severity"] == "info"
    assert _rule(False, "d", "m", severity="critical")["severity"] == "critical"


# ── End to end, through the real engine ──────────────────────────────────────

@pytest.fixture
def invoice(db, organization, admin_user):
    from apps.invoices.models import Invoice

    return Invoice.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="x.pdf", invoice_date=date(2026, 3, 1),
        invoice_number="A1", vendor_name="V", currency="SAR",
        subtotal=Decimal("100"), vat_amount=Decimal("99"),
        vat_rate=Decimal("15"), total_amount=Decimal("115"),
    )


@pytest.mark.django_db
def test_a_vat_miscalculation_shows_its_arithmetic(invoice, organization):
    """The whole point: the auditor sees the sum, not just the verdict."""
    details = run_all_rules(invoice, organization)["rule_details"]["VAT-002"]

    assert details["passed"] is False
    assert details["field"] == "vat_amount"
    assert details["actual"] == 99.0
    assert "15.0" in details["expected"]
    assert "100.0" in details["expected"] and "15%" in details["expected"]


@pytest.mark.django_db
def test_the_header_and_vat_groups_all_carry_a_field(invoice, organization):
    details = run_all_rules(invoice, organization)["rule_details"]

    without_field = [
        code for code in details
        if (code.startswith("INV-") or code.startswith("VAT-"))
        and "field" not in details[code]
    ]
    assert not without_field, f"rules with no structured evidence: {without_field}"


@pytest.mark.django_db
def test_evidence_survives_the_branch_where_the_expected_value_is_undefined(
    db, organization, admin_user
):
    """VAT-002 computes `expected_vat` only when subtotal > 0.

    The enriched call reads it inside a conditional expression, so the
    zero-subtotal branch must never touch it. Getting this wrong is a
    NameError on every invoice with no subtotal — a whole-audit crash, not a
    wrong number.
    """
    from apps.invoices.models import Invoice

    invoice = Invoice.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="x.pdf", invoice_date=date(2026, 3, 1),
        invoice_number="B1", vendor_name="V", currency="SAR",
        subtotal=Decimal("0"), vat_amount=Decimal("0"),
        total_amount=Decimal("100"),
    )

    details = run_all_rules(invoice, organization)["rule_details"]["VAT-002"]
    assert "المجموع الفرعي" in details["expected"]


@pytest.mark.django_db
def test_the_human_message_is_kept_alongside_the_structured_evidence(invoice, organization):
    """The Arabic sentence is what a person reads; it must not be replaced."""
    details = run_all_rules(invoice, organization)["rule_details"]["VAT-003"]
    assert details["message"]
    assert details["description"]
