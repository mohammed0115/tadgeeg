"""INV-009 / INV-010 — the invoice must add up.

Before these rules, nothing in the validator multiplied a quantity by a price or
summed a line table. A live purchase order scored 71% while carrying a table in
which quantity x price matched the line total on one row out of five, and whose
line totals missed the printed subtotal by exactly 2,000 — the same 2,000 by
which one OCR-misread line was short. A human found it with a calculator in
seconds; 34 rules did not.

Each guard is paired with a case that plants the defect and proves the rule
fails on it.
"""

from decimal import Decimal

import pytest

from core.services.invoice_validator import RULES_AR, RULES_EN, TOTAL_RULES, run_all_rules


def _invoice(organization, admin_user, **kwargs):
    from apps.invoices.models import Invoice
    defaults = dict(
        organization=organization, uploaded_by=admin_user,
        original_filename="arith.pdf", file_size=1,
        invoice_number="INV-ARITH-1", vendor_name="Arithmetic Supplier",
        currency="SAR",
    )
    defaults.update(kwargs)
    return Invoice.objects.create(**defaults)


def test_both_rules_are_registered_in_both_languages():
    assert "INV-009" in RULES_AR and "INV-009" in RULES_EN
    assert "INV-010" in RULES_AR and "INV-010" in RULES_EN
    assert TOTAL_RULES == len(RULES_AR) == len(RULES_EN)


@pytest.mark.django_db
class TestINV009LineArithmetic:
    def test_passes_when_every_line_multiplies_out(self, organization, admin_user):
        inv = _invoice(organization, admin_user, subtotal=Decimal("1000.00"), line_items=[
            {"description": "Widget", "quantity": "3", "unit_price": "250", "amount": "750"},
            {"description": "Gadget", "quantity": "2", "unit_price": "125", "amount": "250"},
        ])
        r = run_all_rules(inv, organization, file_hash="")
        assert r["rule_details"]["INV-009"]["passed"] is True

    def test_fails_on_the_live_defect(self, organization, admin_user):
        """Plant the real row: 5,272,505 x 70 is 369,075,350, not 369,073,350."""
        inv = _invoice(organization, admin_user, line_items=[
            {"description": "Apple In-Ear Headphones", "quantity": "5272505",
             "unit_price": "70", "amount": "369073350"},
        ])
        r = run_all_rules(inv, organization, file_hash="")
        detail = r["rule_details"]["INV-009"]
        assert detail["passed"] is False
        assert "369,075,350.00" in detail["message"], "must name the figure it expected"

    def test_fails_when_a_unit_price_was_read_as_zero(self, organization, admin_user):
        inv = _invoice(organization, admin_user, line_items=[
            {"description": "Bose Mini", "quantity": "447220", "unit_price": "0",
             "amount": "5843880"},
        ])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-009"]["passed"] is False

    def test_tolerates_rounding_of_one_unit(self, organization, admin_user):
        inv = _invoice(organization, admin_user, line_items=[
            {"description": "Rounded", "quantity": "3", "unit_price": "33.33", "amount": "100.00"},
        ])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-009"]["passed"] is True

    def test_an_invoice_with_no_line_items_is_not_condemned(self, organization, admin_user):
        inv = _invoice(organization, admin_user, line_items=[])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-009"]["passed"] is True

    def test_unpriced_rows_are_skipped_not_failed(self, organization, admin_user):
        inv = _invoice(organization, admin_user, line_items=[{"description": "Note only"}])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-009"]["passed"] is True


@pytest.mark.django_db
class TestINV010LinesSumToSubtotal:
    def test_passes_when_the_lines_sum_to_the_subtotal(self, organization, admin_user):
        inv = _invoice(organization, admin_user, subtotal=Decimal("1000.00"), line_items=[
            {"description": "Widget", "quantity": "3", "unit_price": "250", "amount": "750"},
            {"description": "Gadget", "quantity": "2", "unit_price": "125", "amount": "250"},
        ])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-010"]["passed"] is True

    def test_fails_on_the_live_two_thousand_gap(self, organization, admin_user):
        """The exact shape of the defect a calculator caught and the suite did not."""
        inv = _invoice(organization, admin_user, subtotal=Decimal("840523088.00"), line_items=[
            {"description": "Headphones", "quantity": "1", "unit_price": "369073350", "amount": "369073350"},
            {"description": "Keyboard", "quantity": "1", "unit_price": "5242540", "amount": "5242540"},
            {"description": "Speaker", "quantity": "1", "unit_price": "5843880", "amount": "5843880"},
            {"description": "HDD", "quantity": "1", "unit_price": "453551960", "amount": "453551960"},
            {"description": "iMac", "quantity": "1", "unit_price": "6809358", "amount": "6809358"},
        ])
        detail = run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-010"]
        assert detail["passed"] is False
        assert "2,000.00" in detail["message"], "must state the size of the gap"

    def test_a_missing_line_is_caught(self, organization, admin_user):
        """The four-row table that hid a 453,551,960 line would now fail here."""
        inv = _invoice(organization, admin_user, subtotal=Decimal("1000.00"), line_items=[
            {"description": "Widget", "quantity": "3", "unit_price": "250", "amount": "750"},
        ])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-010"]["passed"] is False

    def test_skipped_when_there_is_no_subtotal_to_reconcile_against(self, organization, admin_user):
        inv = _invoice(organization, admin_user, subtotal=Decimal("0"), line_items=[
            {"description": "Widget", "quantity": "3", "unit_price": "250", "amount": "750"},
        ])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-010"]["passed"] is True

    def test_skipped_when_there_are_no_line_items(self, organization, admin_user):
        inv = _invoice(organization, admin_user, subtotal=Decimal("1000.00"), line_items=[])
        assert run_all_rules(inv, organization, file_hash="")["rule_details"]["INV-010"]["passed"] is True


@pytest.mark.django_db
def test_both_rules_are_counted_in_the_score(organization, admin_user):
    """A rule absent from the tally cannot change an audit judgement."""
    inv = _invoice(organization, admin_user, subtotal=Decimal("840523088.00"), line_items=[
        {"description": "Headphones", "quantity": "5272505", "unit_price": "70", "amount": "369073350"},
    ])
    r = run_all_rules(inv, organization, file_hash="")
    assert r["total_rules"] == TOTAL_RULES
    # Every rule lands in exactly one of the three buckets. This assertion used to
    # read passed + failed == TOTAL_RULES, which encoded the two-state world that
    # existed before NOT_APPLICABLE: a rule with nothing to measure was forced to
    # call itself a pass. The invariant is stronger now, not weaker — nothing may
    # go uncounted.
    assert (
        r["rules_passed"] + r["rules_failed"] + r["rules_not_applicable"]
    ) == TOTAL_RULES
    assert r["rules_applicable"] == TOTAL_RULES - r["rules_not_applicable"]
    assert "INV-009" in r["failed_rule_codes"]
    assert "INV-010" in r["failed_rule_codes"]
