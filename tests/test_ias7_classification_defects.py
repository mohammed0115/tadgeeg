"""Regression guards for four IAS 7 misclassifications found in the classifier.

None of these raised anything. The engine returned a confident answer and the
answer was wrong, in the direction that flatters cash generated from operations
— capital expenditure landing in operating, and ordinary trade spend landing in
investing. On a statement of cash flows that is a misstatement, not a cosmetic
issue, and it is exactly the sort of thing an audit product cannot afford to
get wrong quietly.

Each test names the input that used to break and the reason it broke.
"""

import pytest

from apps.analytics.ias7_cashflow_service import IAS7CashFlowClassifier


@pytest.fixture
def classifier():
    return IAS7CashFlowClassifier()


# ── 1. Substring matching on two-letter tokens ───────────────────────────────
# "it" was an investing keyword and the match was `kw in text`, so it fired
# inside credit, debit, audit, capital…

@pytest.mark.parametrize("text", [
    "credit note",
    "debit adjustment",
    "audit fees for the year",
])
def test_words_containing_it_are_not_capital_expenditure(classifier, text):
    result = classifier._classify_by_keywords(text)
    assert result is None or result[0] != "investing", (
        f"{text!r} classified as investing — substring matching is back"
    )


def test_it_support_is_not_capital_expenditure(classifier):
    """«Monthly IT support» is an operating cost that read as investing."""
    result = classifier._classify_by_keywords("monthly it support contract")
    assert result is None or result[0] != "investing"


def test_keywords_still_match_as_whole_words(classifier):
    """The fix must not stop real keywords from matching."""
    assert classifier._classify_by_keywords("new machinery for the plant")[0] == "investing"
    assert classifier._classify_by_keywords("salary payment for employees")[0] == "operating"
    assert classifier._classify_by_keywords("loan repayment to the bank")[0] == "financing"


# ── 2. "purchase" as an investing keyword ────────────────────────────────────

def test_the_word_purchase_alone_does_not_imply_capital_expenditure(classifier):
    """Every invoice is a purchase; the word carries no IAS 7 signal."""
    assert classifier._classify_by_keywords("random purchase") is None


def test_a_real_capital_signal_still_classifies_as_investing(classifier):
    assert classifier._classify_by_keywords("acquisition of land")[0] == "investing"


# ── 3. Vendor patterns resolved by dict order ────────────────────────────────

def test_the_specific_vendor_signal_wins_over_the_generic_one(classifier):
    """«Heavy Equipment Supplier Corp» matches both `equipment` and `supplier`.

    First-match-wins over a plain dict returned whichever pattern happened to
    be declared first — and declaration order meant nothing.
    """
    assert classifier._classify_by_vendor_name("Heavy Equipment Supplier Corp") == (
        "investing", "inv_equipment"
    )


def test_a_plain_supplier_is_still_operating(classifier):
    assert classifier._classify_by_vendor_name("Office Supplies Distributor") == (
        "operating", "op_supplies"
    )


def test_the_bare_word_vendor_is_not_a_capex_signal(classifier):
    """`vendor` was an investing pattern, so any company with it in its name
    turned ordinary trade payables into capital expenditure."""
    result = classifier._classify_by_vendor_name("Preferred Vendor Services LLC")
    assert result is None or result[0] != "investing"


# ── 4. The subcategory was discarded by the finaliser ────────────────────────

def test_the_winning_strategys_subcategory_survives(classifier):
    """op_salary used to be flattened to op_other on every classified invoice.

    The class was kept and the detail thrown away, so every sub-line of the
    cash flow statement collapsed into "other" — the classification looked
    like it worked and told the auditor nothing.
    """
    scores = {
        "operating": [(0.95, "op_salary")],
        "investing": [],
        "financing": [],
    }
    result = classifier._finalize_classification(scores, [], None)

    assert result["cash_flow_class"] == "operating"
    assert result["cash_flow_subcategory"] == "op_salary"


def test_the_most_confident_strategy_names_the_subcategory(classifier):
    scores = {
        "operating": [(0.60, "op_other"), (0.95, "op_salary")],
        "investing": [],
        "financing": [],
    }
    assert classifier._finalize_classification(scores, [], None)["cash_flow_subcategory"] == "op_salary"


def test_an_unclassified_result_carries_no_subcategory(classifier):
    scores = {"operating": [(0.4, "op_salary")], "investing": [], "financing": []}
    result = classifier._finalize_classification(scores, [], None)

    assert result["cash_flow_class"] == "unclassified"
    assert result["cash_flow_subcategory"] == ""
    assert result["cash_flow_confidence"] == 0.0
