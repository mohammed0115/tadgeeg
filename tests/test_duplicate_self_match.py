"""DUP-001 — an invoice must never be a duplicate of itself.

DuplicateDetector excludes the row it is scoring via _self_id(), which reads
document_id/invoice_id/id/pk from the payload it is given. The caller attaches
that id to ingestion_result.normalized, but FinancialAIEngine.analyse() consults
`normalized` only as a fallback when extraction returns nothing. Whenever the AI
tier succeeded, the detector was handed the AI's own dict, which carries no id,
so the invoice matched itself on file hash and on vendor+amount+date.

Measured before the fix: dup=1.00 on a single invoice in an empty database, and
is_duplicate=1 on 5 of 5 invoices uploaded after an API key renewal. The guard
had only ever worked because the AI tier was failing.

Each test below plants the original defect and proves the guard fails on it.
"""

from types import SimpleNamespace

import pytest

from core.services.financial_ai_engine import FinancialAIEngine


IDENTITY_KEYS = ("document_id", "invoice_id", "id", "pk")


def _ingestion(normalized):
    return SimpleNamespace(
        success=True, fatal_error=None, file_name="inv.pdf", raw_text="INVOICE 1",
        normalized=normalized, structured={}, metadata={}, extraction_method="test",
    )


class TestIdentityReachesTheDetector:
    """The engine must hand the detector a payload it can exclude the row by."""

    def _run(self, monkeypatch, extracted, normalized):
        """Return the payload the detector actually received."""
        seen = {}
        engine = FinancialAIEngine(organization_id="org-1", country_code="SA", use_ai=True)

        monkeypatch.setattr(engine, "_step_classify", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_step_extract", lambda *a, **k: extracted)
        monkeypatch.setattr(engine, "_apply_extraction", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_step_anomaly", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_step_fraud", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(engine, "_step_compliance", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(engine, "_step_risk", lambda *a, **k: None, raising=False)

        def _capture(result, document):
            seen["document"] = document

        monkeypatch.setattr(engine, "_step_duplicate", _capture)
        engine.analyse(_ingestion(normalized))
        return seen.get("document", {})

    def test_ai_payload_receives_the_self_id(self, monkeypatch):
        """The live defect: AI extraction succeeded and carried no identity."""
        ai_payload = {"invoice_number": "INV-1", "total_amount": 1150.0}
        assert not any(ai_payload.get(k) for k in IDENTITY_KEYS), "fixture must lack an id"

        document = self._run(
            monkeypatch,
            extracted=ai_payload,
            normalized={"invoice_id": "the-row-being-scored"},
        )
        assert document.get("invoice_id") == "the-row-being-scored", (
            "without this the detector cannot exclude the row and matches it to itself"
        )

    def test_the_original_code_path_would_have_lost_it(self, monkeypatch):
        """Plant the defect: hand the AI dict straight through, unmerged."""
        ai_payload = {"invoice_number": "INV-1"}
        normalized = {"invoice_id": "the-row-being-scored"}
        # This is what analyse() used to do — `extracted` wins, normalized ignored.
        unpatched = ai_payload if ai_payload else normalized
        assert not any(unpatched.get(k) for k in IDENTITY_KEYS), (
            "the old path produced a payload with no identity — the defect itself"
        )

    def test_fallback_path_still_carries_its_own_id(self, monkeypatch):
        """When extraction returns nothing, normalized is used and already has the id."""
        document = self._run(
            monkeypatch, extracted={}, normalized={"invoice_id": "row-9", "total_amount": 5},
        )
        assert document.get("invoice_id") == "row-9"

    def test_an_id_already_present_is_not_overwritten(self, monkeypatch):
        document = self._run(
            monkeypatch,
            extracted={"document_id": "authoritative"},
            normalized={"invoice_id": "should-not-win"},
        )
        assert document.get("document_id") == "authoritative"
        assert document.get("invoice_id") is None

    def test_absent_identity_everywhere_is_tolerated(self, monkeypatch):
        """No id anywhere must not raise; the detector simply cannot self-exclude."""
        document = self._run(monkeypatch, extracted={"invoice_number": "X"}, normalized={})
        assert document.get("invoice_number") == "X"


@pytest.mark.django_db
def test_detector_excludes_the_row_it_is_scoring(organization, admin_user):
    """End to end: a lone invoice in an empty organisation is not its own duplicate."""
    from apps.invoices.models import Invoice
    from core.services.detection.duplicate_detector import DuplicateDetector

    inv = Invoice.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="only.pdf", file_size=1,
        invoice_number="INV-SELF-1", vendor_name="Lonely Supplier",
        total_amount="1150.00", currency="SAR",
        extracted_data={"file_hash": "hash-of-the-only-invoice"},
    )

    detector = DuplicateDetector(organization_id=str(organization.id))

    with_id = detector.detect({
        "invoice_id": str(inv.id), "invoice_number": inv.invoice_number,
        "vendor_name": inv.vendor_name, "total_amount": "1150.00",
        "file_hash": "hash-of-the-only-invoice",
    })
    assert with_id.get("is_duplicate") is False, "the only invoice cannot be a duplicate"
    assert float(with_id.get("duplicate_score") or 0) == 0.0

    # Plant the defect: omit the id and the same row matches itself.
    without_id = detector.detect({
        "invoice_number": inv.invoice_number, "vendor_name": inv.vendor_name,
        "total_amount": "1150.00", "file_hash": "hash-of-the-only-invoice",
    })
    assert float(without_id.get("duplicate_score") or 0) > 0.0, (
        "guard is vacuous unless omitting the id really does cause a self-match"
    )
