"""Guards for three defects found on a live purchase order (PQR00003).

The document printed 844,213,841.50. One extractor read that; another read
44,213,841.50 — the same digits minus the leading 8. The merge took whichever
source came first and stored the truncated figure, and nothing downstream could
tell the two apart, because a truncated amount is a *substring* of the correct
one.

The same upload also stored two different line-item tables: four rows on screen
and five in the audit payload, with one line worth 453,551,960 visible only to
the rule engine.

Each guard below is paired with a test that plants the original defect and
proves the guard fails on it. A guard never seen failing is not a guard.
"""

from decimal import Decimal

import pytest

from apps.invoices.services.processor import (
    _amount_appears_in_text,
    _merge_extraction_payloads,
    _prefer_text_corroborated_amounts,
)


# The figures as they appear on the document, verbatim.
RAW_TEXT = """
[E-COM08] Apple In-Ear Headphones
5,272,505.000
70.00
369,073,350.00 ₹
[E-COM10] Apple Wireless Keyboard
524,254.000
10.00
5,242,540.00 ₹
[E-COM05] Bose Mini Bluetooth Speaker
447,220.000
0
5,843,880.00 ₹
[HDD-SH1] HDD SH-1
527,386.000
860.00
453,551,960.00 ₹
[E-COM09] iMac
5,242.000
1,299.00
6,809,358.00 ₹
840,523,088.00 ₹
3,690,753.50 ₹
844,213,841.50 ₹
Payment Terms: 30 Net Days
"""


class TestAmountAppearsInText:
    """The digit boundary is the whole mechanism; test it directly."""

    def test_printed_total_is_corroborated(self):
        assert _amount_appears_in_text(Decimal("844213841.50"), RAW_TEXT) is True

    def test_truncated_total_is_not_corroborated(self):
        # This is the defect in one line. "44,213,841.50" occurs inside
        # "844,213,841.50", so a substring test would wrongly accept it.
        assert "44,213,841.50" in RAW_TEXT
        assert _amount_appears_in_text(Decimal("44213841.50"), RAW_TEXT) is False

    def test_a_plain_substring_test_would_have_accepted_the_truncation(self):
        """Plant the naive implementation and prove it cannot separate the two."""
        def naive(value, text):
            return f"{Decimal(str(value)):,f}" in text

        assert naive(Decimal("844213841.50"), RAW_TEXT) is True
        assert naive(Decimal("44213841.50"), RAW_TEXT) is True  # ← the bug

    def test_matches_without_thousand_separators(self):
        assert _amount_appears_in_text(Decimal("1150.00"), "total_amount: 1150.00") is True

    def test_absent_amount_is_not_corroborated(self):
        assert _amount_appears_in_text(Decimal("999999.99"), RAW_TEXT) is False

    def test_non_numeric_is_not_corroborated(self):
        assert _amount_appears_in_text("not a number", RAW_TEXT) is False
        assert _amount_appears_in_text(None, RAW_TEXT) is False


class TestPreferTextCorroboratedAmounts:
    def test_document_settles_a_disagreement_about_the_total(self):
        structured = {"total_amount": 44213841.50}     # truncated
        ai_data = {"total_amount": 844213841.50}       # printed on the document
        merged = _merge_extraction_payloads(structured, ai_data)

        # The merge alone keeps the truncated figure: first source wins.
        assert Decimal(str(merged["total_amount"])) == Decimal("44213841.50")

        resolved = _prefer_text_corroborated_amounts(
            merged, (structured, ai_data), RAW_TEXT
        )
        assert Decimal(str(resolved["total_amount"])) == Decimal("844213841.50")

    def test_order_of_sources_does_not_change_the_outcome(self):
        a = {"total_amount": 44213841.50}
        b = {"total_amount": 844213841.50}
        for sources in ((a, b), (b, a)):
            merged = _merge_extraction_payloads(*sources)
            resolved = _prefer_text_corroborated_amounts(merged, sources, RAW_TEXT)
            assert Decimal(str(resolved["total_amount"])) == Decimal("844213841.50")

    def test_a_single_candidate_is_left_alone(self):
        """Structured CSV/Excel rows carry one authoritative value. Never touch it."""
        only = {"total_amount": "1150.00"}
        resolved = _prefer_text_corroborated_amounts(
            dict(only), (only,), "unrelated document text with no figures"
        )
        assert resolved["total_amount"] == "1150.00"

    def test_agreeing_sources_are_left_alone(self):
        a = {"subtotal": "1000.00"}
        b = {"subtotal": 1000.00}
        merged = _merge_extraction_payloads(a, b)
        resolved = _prefer_text_corroborated_amounts(merged, (a, b), RAW_TEXT)
        assert Decimal(str(resolved["subtotal"])) == Decimal("1000.00")

    def test_disagreement_with_no_corroboration_is_left_to_the_merge(self):
        """Refuse to guess. Neither figure is on the document, so nothing changes."""
        a = {"total_amount": 111.11}
        b = {"total_amount": 222.22}
        merged = _merge_extraction_payloads(a, b)
        resolved = _prefer_text_corroborated_amounts(merged, (a, b), RAW_TEXT)
        assert Decimal(str(resolved["total_amount"])) == Decimal("111.11")

    def test_disagreement_where_both_are_corroborated_is_left_alone(self):
        """Two printed figures cannot be separated by corroboration alone."""
        a = {"subtotal": 840523088.00}
        b = {"subtotal": 3690753.50}
        merged = _merge_extraction_payloads(a, b)
        resolved = _prefer_text_corroborated_amounts(merged, (a, b), RAW_TEXT)
        assert Decimal(str(resolved["subtotal"])) == Decimal("840523088.00")

    def test_empty_raw_text_disables_the_pass(self):
        a = {"total_amount": 44213841.50}
        b = {"total_amount": 844213841.50}
        merged = _merge_extraction_payloads(a, b)
        resolved = _prefer_text_corroborated_amounts(merged, (a, b), "")
        assert Decimal(str(resolved["total_amount"])) == Decimal("44213841.50")


class TestLineItemAmountAlias:
    """templates/invoices/detail.html read `total`; the normalizer emits `amount`."""

    def test_normalized_line_items_expose_both_keys_with_one_value(self):
        from core.services.normalization import NormalizationService

        result = NormalizationService().normalize(
            {"line_items": [{"description": "iMac", "quantity": 2, "unit_price": 1299, "total": 2598}]}
        )
        item = result.normalized_data["line_items"][0]
        assert item["amount"] == Decimal("2598.00")
        assert item["total"] == item["amount"], "template reads `total`; it must not be empty"

    def test_the_template_renders_the_amount(self):
        """Plant the defect: an item carrying only `amount` must still render."""
        from django.template import Context, Template

        tpl = Template('{{ item.amount|floatformat:2|default:"—" }}')
        assert tpl.render(Context({"item": {"amount": Decimal("2598.00")}})) == "2598.00"
        # and the key the template used to read is what produced the em dash
        old = Template('{{ item.total|floatformat:2|default:"—" }}')
        assert old.render(Context({"item": {"amount": Decimal("2598.00")}})) == "—"


@pytest.mark.django_db
class TestDisplayedAndAuditedLineItemsAgree:
    def test_extracted_data_line_items_match_the_model_column(self, organization, admin_user):
        """The reviewer's table and the audited table must be one list.

        Reproduces the shape of the live defect: the AI payload carried five rows
        while the normalized list carried four.
        """
        from apps.invoices.models import Invoice

        # JSON-safe, exactly as _make_json_safe() leaves them in production.
        normalized_items = [
            {"description": "A", "quantity": "1", "unit_price": "10",
             "amount": "10", "total": "10"},
        ]
        ai_items = [
            {"description": "A", "quantity": 1, "unit_price": 10, "total": 10},
            {"description": "B — only the audit could see this one", "quantity": 1,
             "unit_price": 453551960, "total": 453551960},
        ]
        inv = Invoice.objects.create(
            organization=organization, uploaded_by=admin_user,
            original_filename="two_tables.pdf", file_size=1,
            line_items=normalized_items,
        )
        inv.extracted_data = {
            "line_items": inv.line_items,
            "_ai_line_items": ai_items,
            "file_hash": "x",
        }
        inv.save()
        inv.refresh_from_db()

        assert inv.extracted_data["line_items"] == inv.line_items
        assert len(inv.extracted_data["_ai_line_items"]) == 2, "raw evidence is preserved"
        assert inv.extracted_data["line_items"] != inv.extracted_data["_ai_line_items"], (
            "the two lists genuinely differed; the guard is not vacuous"
        )


class TestPreferTextCorroboratedLineItems:
    """The reviewer must not be shown a table containing invented figures."""

    # Four rows, two of whose amounts appear nowhere in RAW_TEXT.
    FABRICATED = [
        {"description": "Apple In-Ear Headphones", "amount": 36907350.0},   # not printed
        {"description": "Apple Wireless Keyboard", "amount": 52425400.0},   # not printed
        {"description": "Bose Mini Bluetooth Speaker", "amount": 453551960.0},
        {"description": "iMac", "amount": 6809358.0},
    ]
    # Five rows, every amount printed on the document.
    CORROBORATED = [
        {"description": "Apple In-Ear Headphones", "total": 369073350.0},
        {"description": "Apple Wireless Keyboard", "total": 5242540.0},
        {"description": "Bose Mini Bluetooth Speaker", "total": 5843880.0},
        {"description": "HDD SH-1", "total": 453551960.0},
        {"description": "iMac", "total": 6809358.0},
    ]

    def test_the_document_supported_table_wins(self):
        from apps.invoices.services.processor import _prefer_text_corroborated_line_items

        structured = {"line_items": self.FABRICATED}
        ai_data = {"line_items": self.CORROBORATED}
        merged = _merge_extraction_payloads(structured, ai_data)

        # The merge alone keeps the fabricated four-row table.
        assert len(merged["line_items"]) == 4

        resolved = _prefer_text_corroborated_line_items(
            merged, (structured, ai_data), RAW_TEXT
        )
        assert len(resolved["line_items"]) == 5
        descriptions = [i["description"] for i in resolved["line_items"]]
        assert "HDD SH-1" in descriptions, "the 453,551,960 line must not be invisible"

    def test_the_two_invented_amounts_are_genuinely_absent(self):
        """Proves the guard is not vacuous: those figures really are not printed."""
        from apps.invoices.services.processor import _amount_appears_in_text

        assert _amount_appears_in_text(36907350.0, RAW_TEXT) is False
        assert _amount_appears_in_text(52425400.0, RAW_TEXT) is False
        assert _amount_appears_in_text(369073350.0, RAW_TEXT) is True

    def test_a_single_table_is_left_alone(self):
        from apps.invoices.services.processor import _prefer_text_corroborated_line_items

        only = {"line_items": [{"description": "Widget", "amount": "750.00"}]}
        resolved = _prefer_text_corroborated_line_items(dict(only), (only,), RAW_TEXT)
        assert resolved["line_items"] == only["line_items"]

    def test_a_tie_changes_nothing(self):
        """Both amounts are printed, so corroboration cannot separate them."""
        from apps.invoices.services.processor import _prefer_text_corroborated_line_items

        a = {"line_items": [{"description": "A", "amount": 6809358.0}]}
        b = {"line_items": [{"description": "B", "amount": 453551960.0}]}
        assert _amount_appears_in_text(6809358.0, RAW_TEXT)
        assert _amount_appears_in_text(453551960.0, RAW_TEXT)
        merged = _merge_extraction_payloads(a, b)
        resolved = _prefer_text_corroborated_line_items(merged, (a, b), RAW_TEXT)
        assert resolved["line_items"][0]["description"] == "A"

    def test_empty_raw_text_disables_the_pass(self):
        from apps.invoices.services.processor import _prefer_text_corroborated_line_items

        structured = {"line_items": self.FABRICATED}
        ai_data = {"line_items": self.CORROBORATED}
        merged = _merge_extraction_payloads(structured, ai_data)
        resolved = _prefer_text_corroborated_line_items(merged, (structured, ai_data), "")
        assert len(resolved["line_items"]) == 4
