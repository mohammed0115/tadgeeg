"""FIN-001 — a rule with nothing to measure must not report PASS.

Five rules used to pass on fields they had never read. VAT-001 compared the model
default vat_rate of 15 against an expected 15, so it passed on 71 of 71 invoices
in the runtime database — a single distinct value, never once discriminating —
and announced "نسبة الضريبة 15.0% ✓" on a US-dollar invoice with no VAT line.
VAT-002's `if sub > 0` guard routed to an else branch that also passed. VAT-003
computed 0 + 0 − 0 == 0 and called that arithmetic consistency. INV-005 tested
`total_amount is not None` on a column defaulting to 0. CTL-003 was a literal
`ok = True` whose own message admitted no budget data existed.

"No evidence" and "evidence checked and sound" are different audit judgements and
a tick cannot mean both.

Every abstention below is paired with a case proving the same rule still judges
when evidence exists — otherwise NOT_APPLICABLE would just be a new way to hide.
"""

from decimal import Decimal

import pytest

from core.services.invoice_validator import TOTAL_RULES, run_all_rules

ABSTAINERS = ("INV-005", "VAT-001", "VAT-002", "VAT-003", "CTL-003")


def _bare(organization, admin_user):
    """An invoice carrying nothing but model defaults."""
    from apps.invoices.models import Invoice
    return Invoice.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="bare.pdf", file_size=1,
    )


def _extracted(organization, admin_user, **kw):
    """An invoice with real monetary evidence."""
    from apps.invoices.models import Invoice
    defaults = dict(
        organization=organization, uploaded_by=admin_user,
        original_filename="real.pdf", file_size=1,
        invoice_number="INV-NA-1", vendor_name="Supplier", currency="SAR",
        subtotal=Decimal("1000.00"), vat_rate=Decimal("15.00"),
        vat_amount=Decimal("150.00"), total_amount=Decimal("1150.00"),
    )
    defaults.update(kw)
    return Invoice.objects.create(**defaults)


@pytest.mark.django_db
class TestAbstentionOnAbsentEvidence:
    def test_all_five_abstain_on_a_bare_invoice(self, organization, admin_user):
        r = run_all_rules(_bare(organization, admin_user), organization, file_hash="")
        na = set(r["not_applicable_rule_codes"])
        assert na == set(ABSTAINERS), f"expected exactly {ABSTAINERS}, got {sorted(na)}"

    def test_none_of_them_is_counted_as_a_pass(self, organization, admin_user):
        r = run_all_rules(_bare(organization, admin_user), organization, file_hash="")
        for code in ABSTAINERS:
            assert code not in r["passed_rule_codes"], f"{code} must not inflate the score"
            assert code not in r["failed_rule_codes"], f"{code} must not condemn the invoice"

    def test_vat_001_says_it_did_not_measure(self, organization, admin_user):
        detail = run_all_rules(
            _bare(organization, admin_user), organization, file_hash=""
        )["rule_details"]["VAT-001"]
        assert detail["applicable"] is False
        assert detail["passed"] is False
        assert "لم تُقَس" in detail["message"], "the message must not read as a tick"
        assert "✓" not in detail["message"]

    def test_the_three_buckets_account_for_every_rule(self, organization, admin_user):
        r = run_all_rules(_bare(organization, admin_user), organization, file_hash="")
        total = r["rules_passed"] + r["rules_failed"] + r["rules_not_applicable"]
        assert total == TOTAL_RULES, "no rule may go uncounted"
        assert r["rules_applicable"] == TOTAL_RULES - r["rules_not_applicable"]

    def test_the_score_excludes_what_was_not_measured(self, organization, admin_user):
        r = run_all_rules(_bare(organization, admin_user), organization, file_hash="")
        expected = round(r["rules_passed"] / r["rules_applicable"] * 100, 2)
        assert r["validation_score"] == expected
        # Plant the old behaviour: scoring over all rules understates it.
        old_style = round(r["rules_passed"] / TOTAL_RULES * 100, 2)
        assert old_style != r["validation_score"], (
            "if these agree the abstention is not affecting the denominator at all"
        )


@pytest.mark.django_db
class TestTheyStillJudgeWhenEvidenceExists:
    """NOT_APPLICABLE must not become a way to avoid judgement."""

    def test_vat_001_passes_on_a_real_fifteen_percent_invoice(self, organization, admin_user):
        detail = run_all_rules(
            _extracted(organization, admin_user), organization, file_hash=""
        )["rule_details"]["VAT-001"]
        assert detail["applicable"] is True
        assert detail["passed"] is True, "the 15% constant must be untouched"

    def test_vat_001_fails_on_a_wrong_rate(self, organization, admin_user):
        detail = run_all_rules(
            _extracted(organization, admin_user, vat_rate=Decimal("5.00")),
            organization, file_hash="",
        )["rule_details"]["VAT-001"]
        assert detail["applicable"] is True
        assert detail["passed"] is False

    def test_vat_002_fails_when_vat_exists_without_a_base(self, organization, admin_user):
        """VAT recorded against no subtotal is a violation, not an absence."""
        detail = run_all_rules(
            _extracted(organization, admin_user,
                       subtotal=Decimal("0"), vat_amount=Decimal("150.00"),
                       total_amount=Decimal("150.00")),
            organization, file_hash="",
        )["rule_details"]["VAT-002"]
        assert detail["applicable"] is True, "must judge, not abstain"
        assert detail["passed"] is False

    def test_vat_003_fails_on_a_real_mismatch(self, organization, admin_user):
        detail = run_all_rules(
            _extracted(organization, admin_user, total_amount=Decimal("9999.00")),
            organization, file_hash="",
        )["rule_details"]["VAT-003"]
        assert detail["applicable"] is True
        assert detail["passed"] is False

    def test_an_extracted_invoice_abstains_on_nothing_but_the_budget_rule(
        self, organization, admin_user
    ):
        """CTL-003 has no budget integration at all, so it abstains regardless."""
        r = run_all_rules(_extracted(organization, admin_user), organization, file_hash="")
        assert set(r["not_applicable_rule_codes"]) == {"CTL-003"}


@pytest.mark.django_db
def test_the_severity_of_an_abstention_is_never_alarming(organization, admin_user):
    """An unmeasured rule must not colour a dashboard as if it had failed."""
    r = run_all_rules(_bare(organization, admin_user), organization, file_hash="")
    for code in r["not_applicable_rule_codes"]:
        assert r["rule_details"][code]["severity"] == "info"
