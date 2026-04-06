"""CDR-02: Three-Way Match (PO ↔ Invoice ↔ GRN)

Validates that the quantity, unit price, total amount, and vendor are
consistent across the procurement triplet:  Purchase Order, Invoice,
and Goods Receipt Note (GRN).

Precondition: context.three_way_match must be populated by
ThreeWayMatchStage (runs before RuleEngineStage).  If the key is
absent or the match result shows no triplet was found, the rule is
skipped gracefully.
"""
from __future__ import annotations

from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class ThreeWayMatchRule(AuditRuleBase):
    rule_code = "CDR-02"
    rule_name_en = "Three-Way Match (PO ↔ Invoice ↔ GRN)"
    rule_name_ar = "المطابقة الثلاثية (أمر الشراء ↔ الفاتورة ↔ مذكرة الاستلام)"
    default_severity = "critical"
    rule_type = "reconciliation"

    # Tolerance inherited from ThreeWayMatchService; can be overridden via rule config.
    DEFAULT_TOLERANCE_PCT = 5.0

    # ── Precondition ──────────────────────────────────────────────────────────

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        """Skip if no three_way_match data is present on the pipeline context."""
        pipeline_ctx = getattr(doc, "_pipeline_context", None)
        if pipeline_ctx is None:
            return False
        match_data = getattr(pipeline_ctx, "three_way_match", {}) or {}
        # Only run if a valid triplet was resolved (at least po_id or grn_id present)
        return bool(match_data.get("po_id") or match_data.get("grn_id"))

    # ── Main execute ──────────────────────────────────────────────────────────

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            pipeline_ctx = getattr(doc, "_pipeline_context", None)
            match_data: dict = {}
            if pipeline_ctx is not None:
                match_data = getattr(pipeline_ctx, "three_way_match", {}) or {}

            if not match_data:
                return self._pass(
                    "No three-way match data available; rule skipped.",
                    "لا توجد بيانات مطابقة ثلاثية؛ تم تخطي القاعدة.",
                )

            match_status = match_data.get("match_status", "")
            match_score  = float(match_data.get("match_score", 1.0))
            discrepancies: list[str] = match_data.get("discrepancies", [])
            checks: list[dict]       = match_data.get("checks", [])

            evidence = self._build_evidence(match_data, checks)

            if match_status == "MATCH":
                return self._pass(
                    f"Three-way match passed (score {match_score:.0%}).",
                    f"نجحت المطابقة الثلاثية (النتيجة {match_score:.0%}).",
                    evidence=evidence,
                )

            if match_status == "MISMATCH":
                desc_en = "Three-way match failed: " + "; ".join(discrepancies) if discrepancies else "Critical mismatch detected."
                desc_ar = "فشلت المطابقة الثلاثية: " + "؛ ".join(discrepancies) if discrepancies else "تم اكتشاف تعارض حرج."
                return self._fail(desc_en, desc_ar, evidence=evidence)

            # PARTIAL — warn, not a hard fail
            desc_en = "Three-way match partially passed: " + "; ".join(discrepancies) if discrepancies else "Minor discrepancies detected."
            desc_ar = "المطابقة الثلاثية جزئية: " + "؛ ".join(discrepancies) if discrepancies else "تم اكتشاف فوارق بسيطة."
            return self._warning(desc_en, desc_ar, evidence=evidence)

        except Exception as exc:
            return self._error(exc)

    # ── Evidence builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_evidence(match_data: dict, checks: list[dict]) -> list[EvidenceItem]:
        evidence = []
        po_id  = match_data.get("po_id")
        grn_id = match_data.get("grn_id")

        for check in checks:
            status = check.get("status", "SKIPPED")
            if status == "SKIPPED":
                continue

            name = check.get("name", "check")
            po_val  = check.get("po_value")
            inv_val = check.get("invoice_value")
            grn_val = check.get("grn_value")

            desc_en = check.get("explanation") or f"{name}: PO={po_val}, Invoice={inv_val}, GRN={grn_val}"
            desc_ar = check.get("explanation_ar") or desc_en

            evidence.append(EvidenceItem(
                evidence_type="cross_document",
                field_name=name,
                field_name_ar=name,
                expected_value=po_val,
                actual_value=inv_val,
                description=desc_en,
                description_ar=desc_ar,
                linked_document_type="purchase_order",
                linked_document_id=str(po_id) if po_id else "",
            ))

            if grn_val is not None and grn_id:
                evidence.append(EvidenceItem(
                    evidence_type="cross_document",
                    field_name=f"{name}_grn",
                    field_name_ar=f"{name} (المستلم)",
                    expected_value=po_val,
                    actual_value=grn_val,
                    description=f"{name}: PO={po_val}, GRN={grn_val}",
                    description_ar=f"{name}: الأمر={po_val}، المستلم={grn_val}",
                    linked_document_type="goods_receipt",
                    linked_document_id=str(grn_id),
                ))

        return evidence
