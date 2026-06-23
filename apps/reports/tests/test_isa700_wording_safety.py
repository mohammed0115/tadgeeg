"""TADGEEG-FIN-AUDIT-5B — ISA-700 safe-wording hardening tests.

Proves the automated opinion service emits an audit-readiness / draft-direction
output with the required disclaimer and WITHOUT formal-opinion wording. These
tests are DB-free (the service's prose builders take plain dicts), so they do
not depend on the pre-existing broken `org` fixture in tests/test_isa700_opinion.py.
"""
from __future__ import annotations

import json

from apps.reports.services.isa700_opinion_service import (
    SAFE_DISCLAIMER_AR,
    SAFE_DISCLAIMER_EN,
    ISA700OpinionService,
)

# Phrases that would imply the system issued a formal/licensed audit opinion.
UNSAFE_EN = [
    "in our opinion", "present fairly", "do not present fairly",
    "opinion issued", "unqualified opinion issued", "qualified opinion issued",
    "adverse opinion issued", "we express an audit opinion",
]
UNSAFE_AR = ["في رأينا", "تعرض بعدالة"]


def _svc():
    return ISA700OpinionService(None, None)


def _all_paragraph_text(svc):
    """Concatenate the prose for all four direction types."""
    out = []
    for t in ("unqualified", "qualified", "adverse", "disclaimer"):
        p = svc._build_opinion_paragraph(t, "basis", 92.0)
        out.append(p["opinion_en"])
        out.append(p["opinion_ar"])
    return "\n".join(out)


class TestOpinionParagraphWording:
    def test_no_unsafe_english_phrases(self):
        text = _all_paragraph_text(_svc()).lower()
        for phrase in UNSAFE_EN:
            assert phrase not in text, f"unsafe EN phrase emitted: {phrase}"

    def test_no_unsafe_arabic_phrases(self):
        text = _all_paragraph_text(_svc())
        for phrase in UNSAFE_AR:
            assert phrase not in text, f"unsafe AR phrase emitted: {phrase}"

    def test_paragraph_carries_disclaimer_and_review_flag(self):
        p = _svc()._build_opinion_paragraph("unqualified", "basis", 95.0)
        assert p["is_formal_opinion"] is False
        assert p["subject_to_auditor_review"] is True
        assert p["disclaimer_en"] == SAFE_DISCLAIMER_EN
        assert p["disclaimer_ar"] == SAFE_DISCLAIMER_AR
        assert "subject to auditor review" in p["opinion_en"].lower()
        assert "رهن مراجعة المدقّق" in p["opinion_type_ar"]

    def test_direction_labels_are_not_formal_opinion_labels(self):
        for t in ("unqualified", "qualified", "adverse", "disclaimer"):
            p = _svc()._build_opinion_paragraph(t, "basis", 80.0)
            assert "subject to auditor review" in p["opinion_type_en"].lower()
            # The internal CODE is preserved for compatibility.
            assert p["opinion_type"] == t
            assert p["suggested_opinion_direction"] == t

    def test_basis_paragraph_no_our_opinion_assertion(self):
        b = _svc()._build_basis_for_opinion(
            "unqualified",
            {"compliance_score": 92.0, "critical_failures": 0,
             "duplicate_count": 0, "high_risk_count": 0},
            {}, [])
        blob = (b["basis_en"] + b["basis_ar"]).lower()
        assert "in our opinion" not in blob
        assert "في رأينا" not in (b["basis_en"] + b["basis_ar"])
        assert "subject to auditor review" in b["basis_en"].lower()
        assert "licensed auditor" in b["basis_en"].lower()


class TestDisclaimerConstants:
    def test_disclaimer_text(self):
        assert "does not constitute a formal audit opinion" in SAFE_DISCLAIMER_EN
        assert "licensed auditor" in SAFE_DISCLAIMER_EN
        assert "رأي تدقيق" in SAFE_DISCLAIMER_AR
        assert "مدقّق مرخّص" in SAFE_DISCLAIMER_AR

    def test_auditor_responsibility_is_preparation_framed(self):
        en = ISA700OpinionService.AUDITOR_RESPONSIBILITY_EN.lower()
        # System must not claim it expresses the opinion.
        assert "our responsibility is to express" not in en
        assert "licensed auditor" in en
        assert "not a formal audit opinion" in en
