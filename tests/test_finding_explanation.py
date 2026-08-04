"""XAI: show what the rule compared, and never invent what it did not record.

An auditor signing off on a finding is exercising professional judgement that
ISA will not let them delegate. A conclusion sentence ("VAT is incorrect") does
not support that; a comparison ("VAT rate — expected 15%, found 5%") does.

The engine already produces the comparison on one code path and throws it away
on the other. These tests pin the normalisation, and — more importantly — pin
the refusal: where a rule recorded no structured evidence, the explanation says
so. It does not parse numbers out of the Arabic message to fill the gap. A
plausible-looking fabricated expectation under an audit finding is the same
failure as the hardcoded 98% accuracy figure, in the place where it does the
most damage.
"""

import pytest

from apps.audit.models import AuditFinding
from apps.audit.services.finding_explanation import explain


@pytest.fixture
def finding_factory(db, organization):
    def _make(details, **kwargs):
        return AuditFinding.objects.create(
            organization=organization,
            rule_code=kwargs.pop("rule_code", "VAT-004"),
            rule_name=kwargs.pop("rule_name", "VAT rate validity"),
            message=kwargs.pop("message", "نسبة الضريبة غير صحيحة"),
            details=details,
            **kwargs,
        )
    return _make


# ── The rule_engine path: full structured evidence ───────────────────────────

@pytest.mark.django_db
def test_structured_evidence_becomes_a_checkable_comparison(finding_factory):
    finding = finding_factory({
        "evidence": [{
            "evidence_type": "comparison",
            "field_name": "vat_rate",
            "field_name_ar": "نسبة الضريبة",
            "expected_value": "15%",
            "actual_value": "5%",
            "description_ar": "النسبة القياسية في السعودية 15%",
        }],
    })
    result = explain(finding)

    assert result.complete is True
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check["field"] == "نسبة الضريبة"
    assert check["expected"] == "15%"
    assert check["actual"] == "5%"


@pytest.mark.django_db
def test_the_arabic_field_name_wins_on_an_arabic_first_product(finding_factory):
    finding = finding_factory({
        "evidence": [{"field_name": "vat_rate", "field_name_ar": "نسبة الضريبة",
                      "expected_value": "15%", "actual_value": "5%"}],
    })
    assert explain(finding).checks[0]["field"] == "نسبة الضريبة"


@pytest.mark.django_db
def test_evidence_with_neither_expected_nor_actual_is_dropped(finding_factory):
    """It explains nothing, and keeping it would make the list look complete."""
    finding = finding_factory({
        "evidence": [
            {"field_name": "note", "description": "context only"},
            {"field_name": "total", "expected_value": 100, "actual_value": 90},
        ],
    })
    result = explain(finding)
    assert len(result.checks) == 1
    assert result.checks[0]["field"] == "total"


@pytest.mark.django_db
def test_a_zero_expected_value_is_kept(finding_factory):
    """0 is a value. Only None means "not recorded"."""
    finding = finding_factory({
        "evidence": [{"field_name": "balance", "expected_value": 0, "actual_value": 250}],
    })
    result = explain(finding)
    assert result.complete is True
    assert result.checks[0]["expected"] == 0


# ── The invoice_validator path: a sentence, and honesty about it ─────────────

@pytest.mark.django_db
def test_a_flat_detail_is_marked_incomplete(finding_factory):
    finding = finding_factory({
        "passed": False,
        "description": "VAT rate validity",
        "message": "نسبة الضريبة 5% بدلاً من 15%",
        "severity": "high",
    })
    result = explain(finding)

    assert result.complete is False
    assert result.checks[0]["kind"] == "narrative"
    assert result.checks[0]["note"] == "نسبة الضريبة 5% بدلاً من 15%"


@pytest.mark.django_db
def test_values_are_never_parsed_out_of_the_message_text(finding_factory):
    """THE refusal. The message plainly contains "5%" and "15%".

    Reading them out with a regex would produce an expected/actual pair that
    looks exactly like a real measurement and is a guess. An auditor cannot
    tell the two apart on screen, which is why the guess must not be made.
    """
    finding = finding_factory({"message": "نسبة الضريبة 5% بدلاً من 15%"})
    result = explain(finding)

    assert result.complete is False
    for check in result.checks:
        assert check["expected"] is None
        assert check["actual"] is None


@pytest.mark.django_db
def test_an_empty_details_dict_produces_no_checks(finding_factory):
    result = explain(finding_factory({}))
    assert result.checks == []
    assert result.complete is False


@pytest.mark.django_db
def test_malformed_details_do_not_raise(finding_factory):
    """`details` is a JSONField; nothing guarantees its shape."""
    for details in ({"evidence": "not a list"}, {"evidence": [None, 3, "x"]}, {}):
        result = explain(finding_factory(details))
        assert isinstance(result.checks, list)


# ── What the UI receives ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_the_serializer_carries_the_explanation(finding_factory):
    from apps.audit.serializers import AuditFindingSerializer

    finding = finding_factory({
        "evidence": [{"field_name_ar": "الإجمالي", "expected_value": 100, "actual_value": 90}],
    })
    data = AuditFindingSerializer(finding).data

    assert data["explanation"]["complete"] is True
    assert data["explanation"]["checks"][0]["expected"] == 100


@pytest.mark.django_db
def test_the_card_tells_the_auditor_when_the_check_cannot_be_shown(finding_factory):
    """Silence here reads as "there is nothing more to see", which is false."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    template = (repo / "templates/invoices/session_detail.html").read_text(encoding="utf-8")

    assert "explanation.complete" in template
    assert "Review the invoice directly before relying on this finding" in template


def test_not_recorded_is_distinguishable_from_a_null_value():
    """`fmtCheck` must not render a missing value as the text "null"."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    template = (repo / "templates/invoices/session_detail.html").read_text(encoding="utf-8")
    helper = template.split("fmtCheck(value)")[1].split("},")[0]

    assert "not recorded" in helper
    assert "value === null" in helper
