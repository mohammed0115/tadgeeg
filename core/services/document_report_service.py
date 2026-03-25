"""
DocumentReportService — Unified report builder for all 8 Tadgeeg document types.

Builds a complete, structured JSON report for any document by:
1. Loading the AuditRun + AuditResult records (Rule Engine v2.0)
2. Loading the DocumentCanonicalData snapshot
3. Loading the typed model (Invoice / PurchaseOrder / BankStatement / …)
4. Assembling the standard 9-section report schema
5. Adding document-type-specific sections

The output dict is safe to serialize with DjangoJSONEncoder.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as tz
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger("finai")


# ─── Status helpers ───────────────────────────────────────────────────────────

_RISK_LABEL_AR = {
    "critical": "حرج",
    "high":     "عالي",
    "medium":   "متوسط",
    "low":      "منخفض",
}

_STATUS_LABEL_AR = {
    "clean":        "نظيف",
    "issues_found": "يحتوي على مشاكل",
    "critical":     "حرج — يحتاج تدخلاً فورياً",
    "not_audited":  "لم يُدقَّق بعد",
}

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _safe(v: Any) -> Any:
    """Convert Decimal / date / UUID to JSON-safe primitives."""
    import uuid
    import datetime as dt
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe(i) for i in v]
    return v


# ─── Main service ─────────────────────────────────────────────────────────────

class DocumentReportService:
    """
    Build a full structured report for any document type.

    Usage:
        svc = DocumentReportService(organization, user)
        report = svc.build(document_id, document_type)
        # report is a plain dict, safe for JSON serialization
    """

    def __init__(self, organization, user=None):
        self.org = organization
        self.user = user

    # ─── Public entry point ───────────────────────────────────────────────────

    def build(self, document_id: str, document_type: str, language: str = "ar") -> dict:
        """Return the full report dict for one document."""
        from apps.rule_engine.models import AuditRun, AuditResult, AuditEvidence
        from apps.documents.canonical_models import DocumentCanonicalData

        # ── 1. Rule engine data ──────────────────────────────────────────────
        audit_run = (
            AuditRun.objects.filter(
                organization=self.org,
                document_id=str(document_id),
                status=AuditRun.Status.COMPLETED,
            )
            .order_by("-completed_at")
            .first()
        )

        results = []
        if audit_run:
            results = list(
                AuditResult.objects.filter(audit_run=audit_run)
                .prefetch_related("evidence_items", "rule_assignment__rule__translations")
                .order_by("-risk_contribution")
            )

        # ── 2. Canonical data ────────────────────────────────────────────────
        canonical_rec = DocumentCanonicalData.objects.filter(
            typed_object_id=str(document_id)
        ).first()
        canonical = canonical_rec.canonical_data if canonical_rec else {}
        raw_ai    = canonical_rec.raw_ai_output  if canonical_rec else {}

        # ── 3. Typed model ───────────────────────────────────────────────────
        typed_obj = self._load_typed_object(document_id, document_type)

        # ── 3b. Fallback: use typed_obj.validation_details when no AuditRun ─
        # Documents uploaded via the typed upload pipeline store results in
        # validation_details instead of AuditRun/AuditResult ORM records.
        vd: dict = {}
        if not audit_run and typed_obj:
            vd = getattr(typed_obj, "validation_details", None) or {}

        # Merge canonical from typed_obj fields when canonical_rec is empty
        if not canonical and typed_obj:
            canonical = self._canonical_from_typed(typed_obj, document_type)

        # ── 4. Assemble report sections ──────────────────────────────────────
        summary_data = self._build_summary(audit_run, results, canonical, typed_obj, vd)
        violations   = (self._build_violations(results)
                        if results else self._build_violations_from_vd(vd))
        recommendations = (self._build_recommendations(results, document_type)
                           if results else self._build_recommendations_from_vd(vd))

        compliance_score = float(summary_data.get("compliance_score") or summary_data.get("validation_score") or 0)
        risk_level = summary_data.get("risk_level", "low")
        high_risk_count = 1 if risk_level in ("high", "critical") else 0
        top_violations = [
            {"code": v.get("rule_code", ""), "count": 1}
            for v in violations[:10] if v.get("rule_code")
        ]
        total_amount = float(summary_data.get("total_amount") or 0)

        narrative = self._build_narrative_sections(
            doc_type=document_type,
            org_name=getattr(self.org, "name", ""),
            total=1,
            compliance_score=compliance_score,
            high_risk_count=high_risk_count,
            flagged_count=0,
            top_violations=top_violations,
            risk_dist={},
            total_amount=total_amount,
            language=language,
        )

        report = {
            "report_meta":     self._build_meta(document_id, document_type, audit_run, language, typed_obj),
            "summary":         summary_data,
            "key_fields":      self._build_key_fields(document_type, canonical, typed_obj),
            "rule_evaluation": (self._build_rule_evaluation(results)
                                if results else self._build_rule_evaluation_from_vd(vd)),
            "violations":      violations,
            "ai_insights":     self._build_ai_insights(canonical, raw_ai, document_type, vd),
            "compliance":      self._build_compliance(document_type, canonical, results, vd),
            "recommendations": recommendations,
            "audit_trail":     self._build_audit_trail(audit_run, typed_obj),
            "document_specific": self._build_document_specific(document_type, canonical, typed_obj),
            "narrative_sections": narrative,
        }
        return _safe(report)

    # ─── Section builders ─────────────────────────────────────────────────────

    def _build_meta(self, document_id, document_type, audit_run, language, typed_obj=None) -> dict:
        from apps.rule_engine.models import AuditRun
        status = "not_audited"
        if audit_run:
            if audit_run.risk_level in ("critical",):
                status = "critical"
            elif audit_run.failed_rules > 0:
                status = "issues_found"
            else:
                status = "clean"
        elif typed_obj:
            risk = getattr(typed_obj, "risk_level", "") or ""
            failed = getattr(typed_obj, "rules_failed", 0) or 0
            if risk == "critical":
                status = "critical"
            elif failed > 0 or risk in ("high",):
                status = "issues_found"
            elif getattr(typed_obj, "audit_status", "") in ("validated", "approved"):
                status = "clean"

        return {
            "report_id":       None,          # filled after DB save
            "report_type":     "document_audit",
            "document_type":   document_type,
            "document_id":     str(document_id),
            "organization_id": str(self.org.id),
            "organization_name": getattr(self.org, "name", ""),
            "generated_at":    datetime.now(tz.utc).isoformat(),
            "generated_by":    self._user_name(),
            "language":        language,
            "audit_run_id":    str(audit_run.id) if audit_run else None,
            "status":          status,
            "status_ar":       _STATUS_LABEL_AR.get(status, status),
            "engine_version":  getattr(audit_run, "engine_version", "2.0") if audit_run else "2.0",
            "document_type_label_ar": self._doc_type_ar(document_type),
            "document_type_label_en": self._doc_type_en(document_type),
        }

    def _build_summary(self, audit_run, results, canonical, typed_obj, vd: dict = None) -> dict:
        if not audit_run:
            # Fall back to fields stored directly on the typed model
            passed  = int(getattr(typed_obj, "rules_passed",      0) or 0)
            failed  = int(getattr(typed_obj, "rules_failed",      0) or 0)
            # Also count from vd["rule_details"] if typed_obj fields are still 0
            if passed == 0 and failed == 0 and vd:
                rd = vd.get("rule_details", [])
                passed = sum(1 for r in rd if r.get("passed"))
                failed = sum(1 for r in rd if not r.get("passed"))
            total   = passed + failed
            score   = float(getattr(typed_obj, "validation_score", 0) or 0)
            risk    = (getattr(typed_obj, "risk_level", None) or "unknown").lower()
            currency = (canonical.get("currency")
                        or getattr(typed_obj, "currency", None) or "SAR")
            return {
                "total_amount":          _safe(canonical.get("total_amount")
                                               or getattr(typed_obj, "total_amount", 0)),
                "currency":              currency,
                "item_count":            canonical.get("item_count", 0),
                "total_rules":           total,
                "rules_passed":          passed,
                "rules_failed":          failed,
                "rules_warning":         0,
                "rules_skipped":         0,
                "rules_error":           0,
                "pass_rate":             round(passed / total * 100, 1) if total else 0.0,
                "risk_score":            score,
                "risk_level":            risk,
                "risk_level_ar":         _RISK_LABEL_AR.get(risk, "غير محدد"),
                "blocking_failures":     0,
                "requires_manual_review": risk in ("high", "critical"),
                "blocks_approval":       risk == "critical",
                "error_rate":            round(failed / total * 100, 1) if total else 0.0,
                "processing_time_ms":    0,
                "validated_count":       1 if getattr(typed_obj, "audit_status", "") in ("validated", "approved") else 0,
            }

        total = audit_run.total_rules or 0
        passed = audit_run.passed_rules or 0
        evaluated = total - (audit_run.skipped_rules or 0) - (audit_run.error_rules or 0)
        pass_rate = round(passed / evaluated * 100, 1) if evaluated else 0.0

        return {
            "total_amount":          _safe(canonical.get("total_amount") or getattr(typed_obj, "total_amount", 0)),
            "currency":              canonical.get("currency", "SAR"),
            "item_count":            canonical.get("item_count", 0),
            "total_rules":           total,
            "rules_passed":          passed,
            "rules_failed":          audit_run.failed_rules or 0,
            "rules_warning":         audit_run.warning_rules or 0,
            "rules_skipped":         audit_run.skipped_rules or 0,
            "rules_error":           audit_run.error_rules or 0,
            "pass_rate":             pass_rate,
            "risk_score":            float(audit_run.risk_score or 0),
            "risk_level":            audit_run.risk_level or "unknown",
            "risk_level_ar":         _RISK_LABEL_AR.get(audit_run.risk_level, "غير محدد"),
            "blocking_failures":     audit_run.results.filter(status="fail", blocks_approval=True).count(),
            "requires_manual_review": audit_run.requires_manual_review,
            "blocks_approval":       audit_run.blocks_approval,
            "error_rate":            round((audit_run.failed_rules or 0) / total * 100, 1) if total else 0.0,
            "processing_time_ms":    audit_run.processing_time_ms or 0,
        }

    def _build_key_fields(self, document_type: str, canonical: dict, typed_obj) -> dict:
        """Common + document-type-specific key fields for display."""
        base = {
            "document_number": canonical.get("document_number") or canonical.get("invoice_number") or canonical.get("po_number"),
            "document_date":   canonical.get("document_date") or canonical.get("invoice_date") or canonical.get("po_date"),
            "counterparty":    canonical.get("vendor_name") or canonical.get("customer_name") or canonical.get("taxpayer_name"),
            "tax_id":          canonical.get("vendor_vat_number") or canonical.get("vat_number"),
            "currency":        canonical.get("currency", "SAR"),
            "total_amount":    _safe(canonical.get("total_amount", 0)),
            "subtotal":        _safe(canonical.get("subtotal", 0)),
            "vat_amount":      _safe(canonical.get("vat_amount", 0)),
            "cost_center":     canonical.get("cost_center"),
            "account_code":    canonical.get("account_code"),
        }

        # Merge type-specific fields
        extras = {
            "sales_invoice": {
                "customer_name":    canonical.get("customer_name"),
                "customer_vat":     canonical.get("customer_vat_number"),
                "vat_rate":         canonical.get("vat_rate", 15),
                "due_date":         canonical.get("due_date"),
                "has_qr_code":      canonical.get("has_qr_code", False),
                "qr_code_valid":    canonical.get("qr_code_valid", False),
                "is_duplicate":     canonical.get("is_duplicate", False),
            },
            "purchase_order": {
                "po_number":            canonical.get("po_number"),
                "vendor_name":          canonical.get("vendor_name"),
                "vendor_vat_number":    canonical.get("vendor_vat_number"),
                "vendor_cr_number":     canonical.get("vendor_cr_number"),
                "delivery_date":        canonical.get("delivery_date"),
                "line_items":           canonical.get("line_items", []),
            },
            "bank_statement": {
                "bank_name":        canonical.get("bank_name"),
                "account_number":   canonical.get("account_number"),
                "iban":             canonical.get("iban"),
                "period_from":      canonical.get("period_from"),
                "period_to":        canonical.get("period_to"),
                "opening_balance":  _safe(canonical.get("opening_balance", 0)),
                "closing_balance":  _safe(canonical.get("closing_balance", 0)),
                "total_credits":    _safe(canonical.get("total_credits", 0)),
                "total_debits":     _safe(canonical.get("total_debits", 0)),
                "transaction_count":canonical.get("transaction_count", 0),
            },
            "payroll": {
                "payroll_period":   f"{canonical.get('period_from','')} – {canonical.get('period_to','')}",
                "employee_count":   canonical.get("employee_count", 0),
                "total_gross":      _safe(canonical.get("total_gross", 0)),
                "total_net":        _safe(canonical.get("total_net", 0)),
                "total_deductions": _safe(canonical.get("total_deductions", 0)),
                "department":       canonical.get("department"),
                "company_name":     canonical.get("company_name"),
            },
            "expense_report": {
                "employee_name":        canonical.get("employee_name"),
                "employee_id":          canonical.get("employee_id"),
                "report_number":        canonical.get("report_number"),
                "expense_period":       f"{canonical.get('period_from','')} – {canonical.get('period_to','')}",
                "total_claimed":        _safe(canonical.get("total_claimed", 0)),
                "missing_receipts":     canonical.get("missing_receipts_count", 0),
                "over_policy_lines":    canonical.get("over_policy_limit_count", 0),
            },
            "vat_return": {
                "taxpayer_name":            canonical.get("taxpayer_name"),
                "vat_number":               canonical.get("vat_number"),
                "period_from":              canonical.get("period_from"),
                "period_to":                canonical.get("period_to"),
                "output_vat":               _safe(canonical.get("output_vat", 0)),
                "input_vat":                _safe(canonical.get("input_vat", 0)),
                "net_vat_payable":          _safe(canonical.get("net_vat_payable", 0)),
                "standard_rated_sales":     _safe(canonical.get("standard_rated_sales", 0)),
                "standard_rated_purchases": _safe(canonical.get("standard_rated_purchases", 0)),
                "filing_status":            canonical.get("filing_status"),
                "zatca_reference":          canonical.get("zatca_reference"),
            },
            "fixed_asset": {
                "fiscal_year":        canonical.get("fiscal_year"),
                "company_name":       canonical.get("company_name"),
                "department":         canonical.get("department"),
                "asset_count":        canonical.get("asset_count", 0),
                "total_cost":         _safe(canonical.get("total_cost", 0)),
                "total_depreciation": _safe(canonical.get("total_depreciation", 0)),
                "total_book_value":   _safe(canonical.get("total_book_value", 0)),
                "assets":             canonical.get("assets", [])[:10],  # first 10 for display
            },
            "sales_receipt": {
                "receipt_number":    canonical.get("receipt_number"),
                "receipt_date":      canonical.get("receipt_date"),
                "customer_name":     canonical.get("customer_name"),
                "payment_method":    canonical.get("payment_method"),
                "has_qr_code":       canonical.get("has_qr_code", False),
                "qr_code_valid":     canonical.get("qr_code_valid", False),
                "zatca_invoice_ref": canonical.get("zatca_invoice_ref"),
            },
        }
        base.update(extras.get(document_type, {}))
        return base

    def _build_rule_evaluation(self, results: list) -> list:
        """Build the rule evaluation table from AuditResult queryset."""
        rows = []
        for r in results:
            rule_code = r.rule_code
            name_en = rule_code
            name_ar = rule_code
            suggested_action_ar = ""
            try:
                trans_ar = r.rule_assignment.rule.translations.filter(language="ar").first()
                trans_en = r.rule_assignment.rule.translations.filter(language="en").first()
                if trans_ar:
                    name_ar = trans_ar.name
                    suggested_action_ar = trans_ar.suggested_action or ""
                if trans_en:
                    name_en = trans_en.name
            except Exception:
                pass

            evidence_list = []
            try:
                for ev in r.evidence_items.all():
                    evidence_list.append({
                        "type":           ev.evidence_type,
                        "field_name":     ev.field_name,
                        "field_name_ar":  ev.field_name_ar,
                        "expected":       ev.expected_value,
                        "actual":         ev.actual_value,
                        "description":    ev.description,
                        "description_ar": ev.description_ar,
                    })
            except Exception:
                pass

            rows.append({
                "rule_code":           rule_code,
                "rule_name_en":        name_en,
                "rule_name_ar":        name_ar,
                "status":              r.status,
                "status_ar":           _RULE_STATUS_AR.get(r.status, r.status),
                "severity":            r.applied_severity,
                "severity_ar":         _SEVERITY_AR.get(r.applied_severity, r.applied_severity),
                "explanation_en":      r.explanation or "",
                "explanation_ar":      r.explanation_ar or "",
                "risk_contribution":   float(r.risk_contribution or 0),
                "blocks_approval":     r.blocks_approval,
                "execution_time_ms":   r.execution_time_ms,
                "suggested_action_ar": suggested_action_ar,
                "evidence":            evidence_list,
            })
        return rows

    def _build_violations(self, results: list) -> list:
        """Only FAIL/WARNING results, enriched with recommendations."""
        violations = []
        for r in results:
            if r.status not in ("fail", "warning"):
                continue
            violations.append({
                "rule_code":         r.rule_code,
                "severity":          r.applied_severity,
                "severity_order":    _SEVERITY_ORDER.get(r.applied_severity, 0),
                "severity_ar":       _SEVERITY_AR.get(r.applied_severity, ""),
                "title_en":          r.explanation or "",
                "title_ar":          r.explanation_ar or "",
                "blocks_approval":   r.blocks_approval,
                "risk_contribution": float(r.risk_contribution or 0),
                "recommendation_ar": self._get_suggestion_ar(r),
                "recommendation_en": self._get_suggestion_en(r),
                "financial_impact":  self._estimate_financial_impact(r),
            })
        # Sort: critical first
        violations.sort(key=lambda v: v["severity_order"], reverse=True)
        return violations

    # ── Fallback builders (use typed_obj.validation_details when no AuditRun) ──

    def _build_rule_evaluation_from_vd(self, vd: dict) -> list:
        rows = []
        for r in vd.get("rule_details", []):
            status = "pass" if r.get("passed") else "fail"
            sev    = r.get("severity", "medium")
            rows.append({
                "rule_code":           r.get("code", ""),
                "rule_name_en":        r.get("name", r.get("code", "")),
                "rule_name_ar":        r.get("name", r.get("code", "")),
                "status":              status,
                "status_ar":           _RULE_STATUS_AR.get(status, status),
                "severity":            sev,
                "severity_ar":         _SEVERITY_AR.get(sev, sev),
                "explanation_en":      r.get("message", "") or "",
                "explanation_ar":      r.get("message", "") or "",
                "risk_contribution":   0.0,
                "blocks_approval":     sev in ("critical", "high") and not r.get("passed", True),
                "execution_time_ms":   0,
                "suggested_action_ar": "",
                "evidence":            [],
            })
        return rows

    def _build_violations_from_vd(self, vd: dict) -> list:
        violations = []
        for r in vd.get("rule_details", []):
            if r.get("passed"):
                continue
            sev = r.get("severity", "medium")
            violations.append({
                "rule_code":         r.get("code", ""),
                "severity":          sev,
                "severity_order":    _SEVERITY_ORDER.get(sev, 0),
                "severity_ar":       _SEVERITY_AR.get(sev, sev),
                "title_en":          r.get("name", r.get("code", "")),
                "title_ar":          r.get("name", r.get("code", "")),
                "blocks_approval":   sev in ("critical", "high"),
                "risk_contribution": 0.0,
                "recommendation_ar": r.get("message", "") or "",
                "recommendation_en": r.get("message", "") or "",
                "financial_impact":  0.0,
            })
        violations.sort(key=lambda v: v["severity_order"], reverse=True)
        return violations

    def _build_recommendations_from_vd(self, vd: dict) -> list:
        seen, recs = set(), []
        for r in vd.get("rule_details", []):
            if r.get("passed") or r.get("code") in seen:
                continue
            msg = r.get("message", "") or ""
            seen.add(r.get("code", ""))
            recs.append({
                "priority":        r.get("severity", "medium"),
                "rule_code":       r.get("code", ""),
                "action_en":       msg,
                "action_ar":       msg,
                "impact_ar":       "",
                "impact_en":       "",
                "financial_impact": 0.0,
            })
        return recs[:10]

    @staticmethod
    def _canonical_from_typed(typed_obj, document_type: str) -> dict:
        """Extract a minimal canonical dict from the typed model's own fields."""
        out = {}
        for field in ("total_amount", "currency", "vendor_name", "vendor_vat_number",
                      "invoice_number", "po_number", "bank_name", "account_number",
                      "employee_count", "total_gross_salary", "total_net_salary",
                      "employee_name", "receipt_number", "vat_number"):
            v = getattr(typed_obj, field, None)
            if v is not None:
                out[field] = v
        # Map model fields → canonical keys expected by key_fields builder
        if document_type == "payroll":
            out.setdefault("company_name",    getattr(typed_obj, "company_name",    None))
            out.setdefault("total_gross",     getattr(typed_obj, "total_gross_salary", 0))
            out.setdefault("total_net",       getattr(typed_obj, "total_net_salary",   0))
        if document_type == "bank_statement":
            out.setdefault("closing_balance", getattr(typed_obj, "closing_balance", 0))
            out.setdefault("opening_balance", getattr(typed_obj, "opening_balance", 0))
        return out

    def _build_ai_insights(self, canonical: dict, raw_ai: dict, document_type: str, vd: dict = None) -> dict:
        """Build AI insights section from canonical + raw AI data."""
        anomalies = []
        patterns = []
        risk_factors = []

        # Extract anomaly flags from canonical
        anomaly_flags = {
            "is_duplicate":          ("تكرار مستند", "Duplicate document detected"),
            "has_alterations":       ("تعديلات مشبوهة", "Document alterations detected"),
            "is_handwritten":        ("مستند مكتوب بخط يد", "Handwritten document — lower extraction confidence"),
            "negative_book_value_count": ("قيم دفترية سالبة", "Negative book values detected in assets"),
            "ghost_employee_flags":  ("موظفون وهميون محتملون", "Potential ghost employees flagged"),
            "duplicate_tx_count":    ("معاملات بنكية مكررة", "Duplicate bank transactions detected"),
            "missing_receipts_count":("مصروفات بدون إيصالات", "Expense lines without receipts"),
        }
        for field, (ar_msg, en_msg) in anomaly_flags.items():
            val = canonical.get(field)
            if val and val not in (False, 0, [], {}):
                anomalies.append({"field": field, "message_ar": ar_msg, "message_en": en_msg, "value": _safe(val)})

        # Document-type-specific risk factors
        if document_type == "bank_statement":
            if canonical.get("structuring_risk"):
                risk_factors.append({"ar": "مؤشر تجزئة متعمدة (AML)", "en": "Structuring risk (AML)"})

        if document_type == "payroll":
            dup_ids = canonical.get("duplicate_employee_ids", [])
            if dup_ids:
                risk_factors.append({"ar": f"معرّفات موظفين مكررة: {len(dup_ids)}", "en": f"Duplicate employee IDs: {len(dup_ids)}"})

        vendor_behavior = {}
        if document_type in ("sales_invoice", "purchase_order"):
            vendor_behavior = {
                "vendor_name": canonical.get("vendor_name"),
                "risk_note":   raw_ai.get("vendor_risk_note", ""),
            }

        # Also pull AI summary from vd (typed doc pipeline)
        if vd:
            summary_ar = (raw_ai.get("ai_summary_ar") or raw_ai.get("ai_summary")
                          or vd.get("ai_summary_ar") or "") or ""
            summary_en = (raw_ai.get("ai_summary_en") or raw_ai.get("ai_summary")
                          or vd.get("ai_summary_en") or "") or ""
            # Pull anomalies from vd if none from canonical
            if not anomalies:
                for a in vd.get("anomalies", []):
                    if isinstance(a, dict):
                        anomalies.append({"field": a.get("field", ""), "message_ar": a.get("message", ""), "message_en": a.get("message", ""), "value": None})
                    elif isinstance(a, str):
                        anomalies.append({"field": "", "message_ar": a, "message_en": a, "value": None})
        else:
            summary_ar = raw_ai.get("ai_summary_ar") or raw_ai.get("ai_summary") or ""
            summary_en = raw_ai.get("ai_summary_en") or raw_ai.get("ai_summary") or ""

        return {
            "anomalies":       anomalies,
            "patterns":        patterns,
            "risk_factors":    risk_factors,
            "vendor_behavior": vendor_behavior,
            "ai_summary_ar":   summary_ar,
            "ai_summary_en":   summary_en,
            "has_insights":    bool(anomalies or patterns or risk_factors),
        }

    def _build_compliance(self, document_type: str, canonical: dict, results: list, vd: dict = None) -> dict:
        """Build ZATCA compliance section."""
        # Use failed codes from AuditResults OR from validation_details rule_details
        if results:
            failed_codes = {r.rule_code for r in results if r.status == "fail"}
            warned_codes = {r.rule_code for r in results if r.status == "warning"}
        else:
            rd = (vd or {}).get("rule_details", [])
            failed_codes = {r["code"] for r in rd if not r.get("passed")}
            warned_codes = set()

        vat_validated   = "VAT-02" not in failed_codes
        vat_rate_ok     = "VAT-01" not in failed_codes
        vat_num_ok      = "VAT-04" not in failed_codes
        qr_valid        = "VAT-05" not in failed_codes and canonical.get("qr_code_valid", True)
        no_duplicate    = "DUP-01" not in failed_codes and not canonical.get("is_duplicate", False)

        # Missing mandatory compliance fields
        missing_fields = []
        if not canonical.get("vendor_vat_number") and document_type in ("sales_invoice", "purchase_order"):
            missing_fields.append({"field": "vendor_vat_number", "label_ar": "الرقم الضريبي للمورد"})
        if document_type == "sales_invoice" and not canonical.get("has_qr_code"):
            missing_fields.append({"field": "qr_code", "label_ar": "رمز QR (ZATCA)"})
        if document_type == "vat_return" and not canonical.get("zatca_reference"):
            missing_fields.append({"field": "zatca_reference", "label_ar": "الرقم المرجعي للزكاة"})

        compliance_checks = {
            "vat_calculation_correct": vat_validated,
            "vat_rate_15pct":          vat_rate_ok,
            "vat_number_valid":        vat_num_ok,
            "qr_code_valid":           qr_valid if document_type in ("sales_invoice", "sales_receipt") else None,
            "no_duplicate":            no_duplicate,
            "cost_center_assigned":    bool(canonical.get("cost_center")),
        }
        # Compliance score
        applicable = {k: v for k, v in compliance_checks.items() if v is not None}
        passed_count = sum(1 for v in applicable.values() if v)
        compliance_score = round(passed_count / len(applicable) * 100, 1) if applicable else 100.0

        return {
            "zatca_compliant":   compliance_score >= 80,
            "compliance_score":  compliance_score,
            "checks":            compliance_checks,
            "missing_fields":    missing_fields,
            "failed_rules":      list(failed_codes),
            "warning_rules":     list(warned_codes),
        }

    def _build_recommendations(self, results: list, document_type: str) -> list:
        """Top-priority actionable recommendations based on failed rules."""
        recs = []
        for r in results:
            if r.status not in ("fail", "warning"):
                continue
            action_ar = self._get_suggestion_ar(r)
            action_en = self._get_suggestion_en(r)
            if not action_ar and not action_en:
                continue
            recs.append({
                "priority":   r.applied_severity,
                "rule_code":  r.rule_code,
                "action_en":  action_en,
                "action_ar":  action_ar,
                "impact_ar":  r.explanation_ar or "",
                "impact_en":  r.explanation or "",
                "financial_impact": self._estimate_financial_impact(r),
            })
        # Deduplicate and cap
        seen = set()
        unique = []
        for rec in recs:
            if rec["rule_code"] not in seen:
                seen.add(rec["rule_code"])
                unique.append(rec)
        return unique[:10]

    def _build_audit_trail(self, audit_run, typed_obj=None) -> dict:
        if not audit_run:
            # Fallback: use typed_obj timestamps
            audit_date = None
            if typed_obj:
                d = getattr(typed_obj, "updated_at", None) or getattr(typed_obj, "created_at", None)
                audit_date = d.isoformat() if d else None
            return {
                "auditor":           self._user_name(),
                "audit_date":        audit_date,
                "audit_type":        "automatic",
                "triggered_by":      "upload",
                "engine_version":    "doc_validators/2.0",
                "processing_time_ms": 0,
            }
        return {
            "auditor":         self._user_name(),
            "audit_date":      audit_run.completed_at.isoformat() if audit_run.completed_at else None,
            "audit_type":      "automatic" if audit_run.triggered_by in ("upload", "scheduled") else "manual",
            "triggered_by":    audit_run.triggered_by,
            "engine_version":  audit_run.engine_version or "2.0",
            "processing_time_ms": audit_run.processing_time_ms or 0,
        }

    def _build_document_specific(self, document_type: str, canonical: dict, typed_obj) -> dict:
        """Build type-specific extra sections."""
        builders = {
            "sales_invoice":  self._specific_invoice,
            "purchase_order": self._specific_po,
            "bank_statement": self._specific_bank,
            "payroll":        self._specific_payroll,
            "expense_report": self._specific_expense,
            "vat_return":     self._specific_vat,
            "fixed_asset":    self._specific_asset,
            "sales_receipt":  self._specific_receipt,
        }
        fn = builders.get(document_type)
        return fn(canonical, typed_obj) if fn else {}

    # ── Document-specific section builders ────────────────────────────────────

    def _specific_invoice(self, canonical: dict, obj) -> dict:
        return {
            "vat_breakdown": {
                "subtotal":   _safe(canonical.get("subtotal", 0)),
                "vat_rate":   canonical.get("vat_rate", 15),
                "vat_amount": _safe(canonical.get("vat_amount", 0)),
                "total":      _safe(canonical.get("total_amount", 0)),
                "expected_vat": round(float(canonical.get("subtotal") or 0) * 0.15, 2),
            },
            "qr_validation": {
                "has_qr":   canonical.get("has_qr_code", False),
                "valid":    canonical.get("qr_code_valid", False),
            },
            "zatca_compliance": {
                "e_invoice_type": canonical.get("e_invoice_type", "standard"),
                "vendor_cr":      canonical.get("vendor_cr_number"),
                "buyer_vat":      canonical.get("customer_vat_number"),
            },
            "line_items": canonical.get("line_items", [])[:20],
            "is_duplicate": canonical.get("is_duplicate", False),
            "duplicate_of": canonical.get("duplicate_of"),
        }

    def _specific_po(self, canonical: dict, obj) -> dict:
        return {
            "vendor_validation": {
                "vendor_name":  canonical.get("vendor_name"),
                "vendor_vat":   canonical.get("vendor_vat_number"),
                "vendor_cr":    canonical.get("vendor_cr_number"),
            },
            "budget_check": {
                "budget_limit":   _safe(canonical.get("budget_limit", 0)),
                "total_amount":   _safe(canonical.get("total_amount", 0)),
                "within_budget":  float(canonical.get("total_amount") or 0) <= float(canonical.get("budget_limit") or 999999999),
            },
            "approval_workflow": {
                "approved_by":  canonical.get("approved_by"),
                "approved_at":  canonical.get("approved_at"),
                "cost_center":  canonical.get("cost_center"),
            },
            "line_items": canonical.get("line_items", [])[:20],
        }

    def _specific_bank(self, canonical: dict, obj) -> dict:
        transactions = canonical.get("transactions", [])
        # Suspicious = amount just below AML threshold (54k–60k SAR)
        suspicious = [t for t in transactions if 54000 <= float(t.get("amount", 0)) < 60000]
        return {
            "reconciliation": {
                "opening_balance":   _safe(canonical.get("opening_balance", 0)),
                "total_credits":     _safe(canonical.get("total_credits", 0)),
                "total_debits":      _safe(canonical.get("total_debits", 0)),
                "closing_balance":   _safe(canonical.get("closing_balance", 0)),
                "calculated_closing": round(
                    float(canonical.get("opening_balance") or 0) +
                    float(canonical.get("total_credits") or 0) -
                    float(canonical.get("total_debits") or 0), 2
                ),
            },
            "duplicate_transactions": canonical.get("duplicate_tx_count", 0),
            "suspicious_transactions": len(suspicious),
            "suspicious_list": suspicious[:5],
            "transaction_summary": {
                "count":     len(transactions),
                "max_credit": max((float(t.get("credit", 0)) for t in transactions), default=0),
                "max_debit":  max((float(t.get("debit", 0)) for t in transactions), default=0),
            },
        }

    def _specific_payroll(self, canonical: dict, obj) -> dict:
        employees = canonical.get("employees", [])
        return {
            "salary_breakdown": {
                "total_gross":      _safe(canonical.get("total_gross", 0)),
                "total_allowances": _safe(canonical.get("total_allowances", 0)),
                "total_deductions": _safe(canonical.get("total_deductions", 0)),
                "total_net":        _safe(canonical.get("total_net", 0)),
                "employee_count":   len(employees),
            },
            "employee_validation": {
                "ghost_flags":       len(canonical.get("ghost_employee_flags", [])),
                "duplicate_ids":     len(canonical.get("duplicate_employee_ids", [])),
                "missing_id_count":  sum(1 for e in employees if not e.get("id")),
            },
            "gosi_summary": {
                "total_gosi": _safe(canonical.get("total_gosi", 0)),
            },
            "top_salaries": sorted(employees, key=lambda e: float(e.get("net", 0) or 0), reverse=True)[:5],
        }

    def _specific_expense(self, canonical: dict, obj) -> dict:
        lines = canonical.get("expense_lines", [])
        by_category: dict[str, float] = {}
        for line in lines:
            cat = line.get("category", "other")
            by_category[cat] = by_category.get(cat, 0) + float(line.get("amount", 0) or 0)

        return {
            "receipt_validation": {
                "total_lines":       len(lines),
                "with_receipt":      sum(1 for l in lines if l.get("receipt_attached")),
                "without_receipt":   canonical.get("missing_receipts_count", 0),
            },
            "category_breakdown": [
                {"category": k, "total": round(v, 2)} for k, v in by_category.items()
            ],
            "policy_violations": {
                "over_limit_count": canonical.get("over_policy_limit_count", 0),
                "self_approval":    canonical.get("self_approval_risk", False),
            },
            "total_claimed": _safe(canonical.get("total_claimed", 0)),
        }

    def _specific_vat(self, canonical: dict, obj) -> dict:
        output_vat = float(canonical.get("output_vat") or 0)
        input_vat  = float(canonical.get("input_vat") or 0)
        net_declared = float(canonical.get("net_vat_payable") or 0)
        calculated_net = round(output_vat - input_vat, 2)

        return {
            "vat_calculation": {
                "output_vat":       _safe(output_vat),
                "input_vat":        _safe(input_vat),
                "calculated_net":   calculated_net,
                "declared_net":     _safe(net_declared),
                "arithmetic_ok":    abs(calculated_net - net_declared) <= 1.0,
                "discrepancy":      round(abs(calculated_net - net_declared), 2),
            },
            "filing_details": {
                "filing_status":    canonical.get("filing_status"),
                "filing_date":      canonical.get("filing_date"),
                "due_date":         canonical.get("due_date"),
                "zatca_reference":  canonical.get("zatca_reference"),
                "is_late":          canonical.get("is_late_filing", False),
            },
            "taxable_amounts": {
                "standard_rated_sales":     _safe(canonical.get("standard_rated_sales", 0)),
                "standard_rated_purchases": _safe(canonical.get("standard_rated_purchases", 0)),
                "zero_rated_sales":         _safe(canonical.get("zero_rated_sales", 0)),
                "exempt_sales":             _safe(canonical.get("exempt_sales", 0)),
            },
        }

    def _specific_asset(self, canonical: dict, obj) -> dict:
        assets = canonical.get("assets", [])
        fully_dep = [a for a in assets if a.get("is_fully_depreciated")]
        negative  = [a for a in assets if float(a.get("book_value", 0) or 0) < 0]
        return {
            "depreciation_summary": {
                "total_cost":         _safe(canonical.get("total_cost", 0)),
                "total_accumulated":  _safe(canonical.get("total_accumulated_depreciation", 0)),
                "total_book_value":   _safe(canonical.get("total_book_value", 0)),
                "fully_depreciated":  len(fully_dep),
                "negative_book_value_count": len(negative),
            },
            "asset_lifecycle": {
                "total_assets":    len(assets),
                "by_category":     self._group_assets_by_category(assets),
            },
            "assets_preview": assets[:10],
        }

    def _specific_receipt(self, canonical: dict, obj) -> dict:
        return {
            "payment_validation": {
                "payment_method":  canonical.get("payment_method"),
                "within_cash_limit": float(canonical.get("total_amount") or 0) < 60000,
            },
            "zatca_reference": {
                "receipt_number":    canonical.get("receipt_number"),
                "zatca_invoice_ref": canonical.get("zatca_invoice_ref"),
                "has_qr":           canonical.get("has_qr_code", False),
                "qr_valid":         canonical.get("qr_code_valid", False),
            },
            "line_items": canonical.get("line_items", [])[:20],
        }

    # ─── Helpers ──────────────────────────────────────────────────────────────

    # ─── Bulk / Summary entry point ───────────────────────────────────────────

    def build_summary(self, document_type: str, language: str = "ar") -> dict:
        """
        Build an aggregate summary report for ALL documents of a given type
        in the organization (no specific document_id required).
        """
        from collections import Counter

        typed_objects = list(self._all_typed_objects(document_type))
        total = len(typed_objects)

        scores   = [float(getattr(o, "validation_score", 0) or 0) for o in typed_objects]
        avg_score = round(sum(scores) / total, 1) if total else 0.0

        risk_dist   = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        status_dist = {"validated": 0, "flagged": 0, "approved": 0, "pending": 0, "rejected": 0}
        all_failed  = []

        for obj in typed_objects:
            risk   = (getattr(obj, "risk_level",    None) or "low").lower()
            status = (getattr(obj, "audit_status",  None) or "pending").lower()
            risk_dist[risk]     = risk_dist.get(risk, 0) + 1
            status_dist[status] = status_dist.get(status, 0) + 1
            all_failed.extend(getattr(obj, "failed_rule_codes", None) or [])

        top_violations = [
            {"code": c, "count": n}
            for c, n in Counter(all_failed).most_common(10)
        ]
        high_risk = [o for o in typed_objects if getattr(o, "risk_level", "") in ("high", "critical")]

        # ── Total amount from typed objects ──────────────────────────────────
        total_amount = sum(
            float(getattr(o, "total_amount", 0) or 0)
            for o in typed_objects
        )

        narrative = self._build_narrative_sections(
            doc_type=document_type,
            org_name=getattr(self.org, "name", ""),
            total=total,
            compliance_score=avg_score,
            high_risk_count=risk_dist.get("critical", 0) + risk_dist.get("high", 0),
            flagged_count=status_dist.get("flagged", 0),
            top_violations=top_violations,
            risk_dist=risk_dist,
            total_amount=total_amount,
            language=language,
        )

        return _safe({
            "report_meta": {
                "report_id":              None,
                "report_type":            f"document_summary_{document_type}",
                "document_type":          document_type,
                "document_id":            None,
                "organization_id":        str(self.org.id),
                "organization_name":      getattr(self.org, "name", ""),
                "generated_at":           datetime.now(tz.utc).isoformat(),
                "generated_by":           self._user_name(),
                "language":               language,
                "audit_run_id":           None,
                "status":                 "summary",
                "status_ar":              "تقرير إجمالي",
                "engine_version":         "2.0",
                "document_type_label_ar": self._doc_type_ar(document_type),
                "document_type_label_en": self._doc_type_en(document_type),
            },
            "summary": {
                "total_documents":  total,
                "average_score":    avg_score,
                "risk_distribution":  risk_dist,
                "status_distribution": status_dist,
                "high_risk_count":  risk_dist.get("critical", 0) + risk_dist.get("high", 0),
                "clean_count":      status_dist.get("validated", 0) + status_dist.get("approved", 0),
                "flagged_count":    status_dist.get("flagged", 0),
            },
            "top_violations": top_violations,
            "high_risk_documents": [
                {
                    "id":               str(o.id),
                    "risk_level":       getattr(o, "risk_level", ""),
                    "risk_level_ar":    _RISK_LABEL_AR.get(getattr(o, "risk_level", ""), ""),
                    "validation_score": float(getattr(o, "validation_score", 0) or 0),
                    "audit_status":     getattr(o, "audit_status", ""),
                    "created_at":       o.created_at.isoformat() if getattr(o, "created_at", None) else None,
                    "failed_codes":     getattr(o, "failed_rule_codes", None) or [],
                }
                for o in high_risk[:20]
            ],
            "document_list": [
                {
                    "id":               str(o.id),
                    "risk_level":       getattr(o, "risk_level", ""),
                    "validation_score": float(getattr(o, "validation_score", 0) or 0),
                    "audit_status":     getattr(o, "audit_status", ""),
                    "created_at":       o.created_at.isoformat() if getattr(o, "created_at", None) else None,
                }
                for o in typed_objects[:50]
            ],
            "rule_evaluation":   [],
            "violations":        [],
            "ai_insights":       {
                "anomalies": [], "patterns": [], "risk_factors": [],
                "vendor_behavior": {}, "ai_summary_ar": "", "ai_summary_en": "",
                "has_insights": False,
            },
            "compliance": {
                "zatca_compliant":  avg_score >= 80,
                "compliance_score": avg_score,
                "checks": {}, "missing_fields": [], "failed_rules": [], "warning_rules": [],
            },
            "recommendations":   [],
            "audit_trail": {
                "auditor":           self._user_name(),
                "audit_date":        datetime.now(tz.utc).isoformat(),
                "audit_type":        "summary",
                "triggered_by":      "user_request",
                "engine_version":    "2.0",
                "processing_time_ms": 0,
            },
            "document_specific": {},
            "key_fields":        {},
            "narrative_sections": narrative,
        })

    def _build_narrative_sections(
        self,
        doc_type: str,
        org_name: str,
        total: int,
        compliance_score: float,
        high_risk_count: int,
        flagged_count: int,
        top_violations: list,
        risk_dist: dict,
        total_amount: float = 0.0,
        language: str = "ar",
    ) -> dict:
        """Generate programmatic narrative report sections without AI/OpenAI."""

        doc_ar = self._doc_type_ar(doc_type)
        doc_en = self._doc_type_en(doc_type)
        score  = round(compliance_score, 2)
        industry_benchmark = 94.0
        diff = round(score - industry_benchmark, 1)

        # ── Scope per document type ───────────────────────────────────────────
        scope_map_ar = {
            "sales_invoice":  "تحليل فواتير المبيعات، والتحقق من صحة ضريبة القيمة المضافة والبيانات الضريبية",
            "purchase_order": "مراجعة أوامر الشراء والتحقق من الالتزام بسياسات الشراء والميزانيات المعتمدة",
            "bank_statement": "تحليل كشوف الحساب البنكية والتحقق من التوافق مع السجلات المحاسبية",
            "payroll":        "مراجعة كشوف الرواتب والتحقق من صحة احتسابات الرواتب والاقتطاعات",
            "expense_report": "تدقيق تقارير المصروفات والتحقق من توافر المستندات المؤيدة والامتثال للسياسات",
            "vat_return":     "مراجعة إقرارات ضريبة القيمة المضافة والتحقق من صحة الأرقام المُبلَّغ عنها",
            "fixed_asset":    "تدقيق سجلات الأصول الثابتة والتحقق من صحة الاستهلاك وتصنيف الأصول",
            "sales_receipt":  "مراجعة إيصالات المبيعات والتحقق من اكتمال البيانات وصحة المبالغ",
        }
        scope_map_en = {
            "sales_invoice":  "Analysis of sales invoices, verification of VAT correctness and tax compliance",
            "purchase_order": "Review of purchase orders, compliance with procurement policies and approved budgets",
            "bank_statement": "Analysis of bank statements and reconciliation with accounting records",
            "payroll":        "Review of payroll sheets, verification of salary calculations and deductions",
            "expense_report": "Audit of expense reports, verification of supporting documents and policy compliance",
            "vat_return":     "Review of VAT returns and verification of reported figures",
            "fixed_asset":    "Audit of fixed asset registers, depreciation correctness, and asset classification",
            "sales_receipt":  "Review of sales receipts, completeness of data and amount accuracy",
        }

        # ── Recommendation templates ──────────────────────────────────────────
        rec_map_ar = {
            "sales_invoice": [
                "تحسين عمليات التحقق من الفواتير لتقليل الفواتير المكررة",
                "تعزيز الامتثال لضريبة القيمة المضافة من خلال تدريب الموظفين وتحديث الأنظمة المحاسبية",
                "تعيين معتمدين للفواتير لضمان الامتثال للضوابط المالية",
                "مراجعة سياسة قبول الفواتير وتحديثها بما يتوافق مع متطلبات هيئة الزكاة والضريبة والجمارك",
            ],
            "purchase_order": [
                "تعزيز إجراءات الموافقة على أوامر الشراء قبل التنفيذ",
                "مراجعة سياسة الموردين المعتمدين وتحديث قائمتهم بصفة دورية",
                "ربط أوامر الشراء بالميزانيات التشغيلية المعتمدة آلياً",
            ],
            "bank_statement": [
                "إجراء تسوية بنكية شهرية منتظمة وتوثيقها",
                "مراجعة المعاملات غير المعتادة وإخضاعها لإجراءات تحقق إضافية",
                "تفعيل إشعارات المعاملات الفورية للمراقبة المستمرة",
            ],
            "payroll": [
                "مراجعة احتسابات الرواتب والمكافآت للتأكد من دقتها",
                "التحقق من صحة بيانات الموظفين قبل صرف الرواتب",
                "تطبيق مبدأ الفصل بين الواجبات في عملية إعداد وصرف الرواتب",
            ],
            "expense_report": [
                "اشتراط تقديم مستندات مؤيدة لجميع المصروفات دون استثناء",
                "تحديد سقف للمصروفات النقدية ومطالبة العاملين باتباعها",
                "مراجعة سياسة المصروفات وتحديثها لتشمل معايير الموافقة الإلكترونية",
            ],
            "vat_return": [
                "التحقق من صحة الأرقام المُبلَّغ عنها في إقرارات ضريبة القيمة المضافة",
                "مطابقة أرقام الإقرارات مع بيانات المبيعات والمشتريات الفعلية",
                "الالتزام بمواعيد تقديم الإقرارات الضريبية لتجنب الغرامات",
            ],
            "fixed_asset": [
                "إجراء جرد دوري للأصول الثابتة والتحقق من وجودها الفعلي",
                "مراجعة معدلات الاستهلاك وتوافقها مع السياسة المحاسبية",
                "تحديث سجل الأصول عند كل إضافة أو استبعاد فوراً",
            ],
            "sales_receipt": [
                "التأكد من اكتمال بيانات إيصالات المبيعات قبل الإصدار",
                "ربط الإيصالات بفواتير المبيعات المقابلة تلقائياً",
                "مراجعة الإيصالات ذات القيم الكبيرة من قبل مشرف مالي",
            ],
        }
        rec_map_en = {
            "sales_invoice": [
                "Improve invoice verification processes to reduce duplicate invoices",
                "Strengthen VAT compliance through staff training and accounting system updates",
                "Assign invoice approvers to ensure compliance with financial controls",
                "Review and update invoice acceptance policy to align with ZATCA requirements",
            ],
            "purchase_order": [
                "Strengthen purchase order approval procedures before execution",
                "Periodically review and update the approved vendor list",
                "Automatically link purchase orders to approved operational budgets",
            ],
            "bank_statement": [
                "Perform regular monthly bank reconciliations and document them",
                "Review unusual transactions and subject them to additional verification",
                "Enable instant transaction notifications for continuous monitoring",
            ],
            "payroll": [
                "Review salary and bonus calculations to ensure accuracy",
                "Verify employee data before payroll disbursement",
                "Apply segregation of duties in payroll preparation and disbursement",
            ],
            "expense_report": [
                "Require supporting documents for all expenses without exception",
                "Set cash expense limits and require staff compliance",
                "Review and update expense policy to include electronic approval standards",
            ],
            "vat_return": [
                "Verify figures reported in VAT returns",
                "Reconcile return figures with actual sales and purchase data",
                "Meet VAT return submission deadlines to avoid penalties",
            ],
            "fixed_asset": [
                "Conduct periodic physical inventory of fixed assets",
                "Review depreciation rates for consistency with accounting policy",
                "Update the asset register immediately upon additions or disposals",
            ],
            "sales_receipt": [
                "Ensure completeness of sales receipt data before issuance",
                "Automatically link receipts to corresponding sales invoices",
                "Review high-value receipts by a financial supervisor",
            ],
        }

        recs_ar = rec_map_ar.get(doc_type, ["مراجعة الإجراءات المالية وتعزيز الامتثال للمعايير المحلية والدولية"])
        recs_en = rec_map_en.get(doc_type, ["Review financial procedures and strengthen compliance with local and international standards"])

        # ── Build section texts ───────────────────────────────────────────────
        amount_str = f"{total_amount:,.2f}" if total_amount else "—"
        hi_count   = high_risk_count

        # EXECUTIVE_SUMMARY
        if score >= 90:
            overall_ar = "أظهرت النتائج مستوى امتثال جيداً مع بعض المجالات التي تستدعي المتابعة"
            overall_en = "Results indicate a good compliance level with some areas requiring follow-up"
        elif score >= 70:
            overall_ar = "أظهرت النتائج وجود فجوات في الامتثال تستوجب معالجة فورية"
            overall_en = "Results reveal compliance gaps requiring immediate attention"
        else:
            overall_ar = "أظهرت النتائج وجود قصور واضح في الامتثال يستدعي تدخلاً عاجلاً"
            overall_en = "Results reveal significant compliance deficiencies requiring urgent intervention"

        exec_sum_ar = (
            f"تم إجراء تقييم شامل للمخاطر المرتبطة بـ{doc_ar} لشركة {org_name}. "
            f"شمل التقييم تحليل {total} مستند{'اً' if total > 1 else ''} "
            f"{'بإجمالي ' + amount_str + ' ريال سعودي. ' if total_amount else ''}. "
            f"{overall_ar}. "
            f"تم تصنيف {hi_count} مستند{'اً' if hi_count > 1 else ''} على أنه{'ا' if hi_count > 1 else ''} ذو مخاطر عالية أو حرجة."
        )
        exec_sum_en = (
            f"A comprehensive risk assessment was conducted for {doc_en} at {org_name}. "
            f"The assessment covered {total} document{'s' if total != 1 else ''} "
            f"{'totalling SAR ' + amount_str + '. ' if total_amount else ''}. "
            f"{overall_en}. "
            f"{hi_count} document{'s' if hi_count != 1 else ''} {'were' if hi_count != 1 else 'was'} classified as high or critical risk."
        )

        # KEY_FINDINGS
        findings_ar = [
            f"تم تحليل {total} {'مستنداً' if total > 1 else 'مستند'} من نوع {doc_ar}"
            + (f" بإجمالي {amount_str} ريال سعودي" if total_amount else ""),
            f"بلغت نسبة الامتثال الإجمالية {score}٪",
            f"تم تصنيف {hi_count} مستند{'اً' if hi_count != 1 else ''} على أنه{'ا' if hi_count != 1 else ''} ذو مخاطر عالية",
        ]
        if flagged_count:
            findings_ar.append(f"تم وضع {flagged_count} مستند{'اً' if flagged_count != 1 else ''} تحت المراجعة")
        if top_violations:
            top = top_violations[0]
            findings_ar.append(f"أكثر المخالفات تكراراً: {top.get('code', '—')} ({top.get('count', 0)} مرة)")

        findings_en = [
            f"Analyzed {total} {doc_en} document{'s' if total != 1 else ''}"
            + (f" totalling SAR {amount_str}" if total_amount else ""),
            f"Overall compliance rate: {score}%",
            f"{hi_count} document{'s' if hi_count != 1 else ''} classified as high risk",
        ]
        if flagged_count:
            findings_en.append(f"{flagged_count} document{'s' if flagged_count != 1 else ''} flagged for review")
        if top_violations:
            top = top_violations[0]
            findings_en.append(f"Most frequent violation: {top.get('code', '—')} ({top.get('count', 0)} occurrence{'s' if top.get('count', 0) != 1 else ''})")

        # COMPLIANCE_SECTION
        if score >= industry_benchmark:
            comp_ar = (
                f"أظهرت نتائج التدقيق أن الشركة تلتزم بالمعايير المالية والضريبية المطلوبة، "
                f"حيث بلغت نسبة الامتثال {score}٪، وهو يفوق المعيار الصناعي البالغ {industry_benchmark}٪."
            )
            comp_en = (
                f"Audit results indicate the company meets required financial and regulatory standards, "
                f"with a compliance rate of {score}%, exceeding the industry benchmark of {industry_benchmark}%."
            )
        else:
            comp_ar = (
                f"أظهرت نتائج التدقيق أن الشركة غير ملتزمة بالمعايير المالية والتنظيمية المطلوبة بالكامل، "
                f"حيث بلغت نسبة الامتثال {score}٪ فقط، وهو أقل من المعيار الصناعي البالغ {industry_benchmark}٪ "
                f"بفارق {abs(diff)}٪."
            )
            comp_en = (
                f"Audit results indicate the company does not fully meet required financial and regulatory standards. "
                f"Compliance rate is {score}%, below the industry benchmark of {industry_benchmark}% "
                f"by a margin of {abs(diff)}%."
            )

        # ANOMALIES_SECTION
        anomalies_ar_items = []
        anomalies_en_items = []
        if hi_count:
            anomalies_ar_items.append(f"رصد {hi_count} مستند{'اً' if hi_count != 1 else ''} ذو مخاطر عالية يستوجب مراجعة معمّقة")
            anomalies_en_items.append(f"Detected {hi_count} high-risk document{'s' if hi_count != 1 else ''} requiring in-depth review")
        for v in top_violations[:3]:
            anomalies_ar_items.append(f"تكرار مخالفة {v.get('code', '—')} في {v.get('count', 0)} حالة")
            anomalies_en_items.append(f"Recurring violation {v.get('code', '—')} in {v.get('count', 0)} case{'s' if v.get('count', 0) != 1 else ''}")
        if not anomalies_ar_items:
            anomalies_ar_items.append("لم يتم رصد أي أنماط شاذة تستدعي التنبيه في هذه المرحلة")
            anomalies_en_items.append("No anomalous patterns requiring attention were detected at this stage")

        anom_ar = "تم تحديد الأنماط التالية غير الاعتيادية خلال عملية التدقيق:\n" + "\n".join(
            f"{i+1}. {item}" for i, item in enumerate(anomalies_ar_items)
        )
        anom_en = "The following anomalous patterns were identified during the audit:\n" + "\n".join(
            f"{i+1}. {item}" for i, item in enumerate(anomalies_en_items)
        )

        # SCOPE_AND_METHODOLOGY
        scope_ar = (
            f"شمل نطاق التدقيق {scope_map_ar.get(doc_type, 'مراجعة المستندات المالية والتحقق من الامتثال')}. "
            f"تم استخدام محرك التدقيق الذكي (الإصدار 2.0) الذي يطبّق {total} قاعدة تدقيق آلية "
            f"لتحليل البيانات وتحديد المخاطر والأنماط غير الاعتيادية."
        )
        scope_en = (
            f"The audit scope covered {scope_map_en.get(doc_type, 'review of financial documents and compliance verification')}. "
            f"The intelligent audit engine (version 2.0) was used, applying automated audit rules "
            f"to analyze data and identify risks and anomalous patterns."
        )

        # RECOMMENDATIONS
        recs_numbered_ar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs_ar))
        recs_numbered_en = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs_en))

        # CONCLUSION
        if score >= 90:
            concl_ar = (
                f"تعكس نتائج تدقيق {doc_ar} لشركة {org_name} مستوى امتثال مقبولاً. "
                f"يُوصى بالحفاظ على هذا المستوى والعمل على تحسينه باستمرار."
            )
            concl_en = (
                f"The {doc_en} audit results for {org_name} reflect an acceptable compliance level. "
                f"It is recommended to maintain and continuously improve this level."
            )
        else:
            concl_ar = (
                f"تحتاج شركة {org_name} إلى تحسين ملموس في إجراءات {doc_ar} لضمان الامتثال للمعايير المحلية والدولية. "
                f"يجب اتخاذ إجراءات فورية لمعالجة القضايا المحددة في هذا التقرير."
            )
            concl_en = (
                f"{org_name} needs tangible improvement in {doc_en} procedures to ensure compliance with local and international standards. "
                f"Immediate action must be taken to address the issues identified in this report."
            )

        # MANAGEMENT_RESPONSE_PLACEHOLDER
        mgmt_ar = "يرجى من إدارة الشركة تقديم رد رسمي على النتائج والتوصيات الواردة في هذا التقرير خلال 30 يوم عمل من تاريخ الاستلام."
        mgmt_en = "Management is requested to provide a formal response to the findings and recommendations in this report within 30 business days of receipt."

        return {
            "executive_summary_ar": exec_sum_ar,
            "executive_summary_en": exec_sum_en,
            "key_findings_ar": "\n".join(f"{i+1}. {f}" for i, f in enumerate(findings_ar)),
            "key_findings_en": "\n".join(f"{i+1}. {f}" for i, f in enumerate(findings_en)),
            "compliance_section_ar": comp_ar,
            "compliance_section_en": comp_en,
            "anomalies_section_ar": anom_ar,
            "anomalies_section_en": anom_en,
            "scope_and_methodology_ar": scope_ar,
            "scope_and_methodology_en": scope_en,
            "recommendations_ar": recs_numbered_ar,
            "recommendations_en": recs_numbered_en,
            "conclusion_ar": concl_ar,
            "conclusion_en": concl_en,
            "management_response_ar": mgmt_ar,
            "management_response_en": mgmt_en,
        }

    def _all_typed_objects(self, document_type: str):
        """Return queryset for all org documents of a given type."""
        loaders = {
            "sales_invoice":  ("apps.invoices.models",       "Invoice"),
            "purchase_order": ("apps.documents.typed_models", "PurchaseOrder"),
            "bank_statement": ("apps.documents.typed_models", "BankStatement"),
            "payroll":        ("apps.documents.typed_models", "PayrollSheet"),
            "expense_report": ("apps.documents.typed_models", "ExpenseReport"),
            "vat_return":     ("apps.documents.typed_models", "VATReturn"),
            "fixed_asset":    ("apps.documents.typed_models", "FixedAsset"),
            "sales_receipt":  ("apps.documents.typed_models", "SalesReceipt"),
        }
        entry = loaders.get(document_type)
        if not entry:
            return []
        try:
            import importlib
            module = importlib.import_module(entry[0])
            model_cls = getattr(module, entry[1])
            return model_cls.objects.filter(organization=self.org).order_by("-created_at")
        except Exception as exc:
            logger.debug("Could not load typed model %s: %s", document_type, exc)
            return []

    def _load_typed_object(self, document_id: str, document_type: str):
        """Load the typed model instance. Returns None if not found."""
        loaders = {
            "sales_invoice":  ("apps.invoices.models", "Invoice"),
            "purchase_order": ("apps.documents.typed_models", "PurchaseOrder"),
            "bank_statement": ("apps.documents.typed_models", "BankStatement"),
            "payroll":        ("apps.documents.typed_models", "PayrollSheet"),
            "expense_report": ("apps.documents.typed_models", "ExpenseReport"),
            "vat_return":     ("apps.documents.typed_models", "VATReturn"),
            "fixed_asset":    ("apps.documents.typed_models", "FixedAsset"),
            "sales_receipt":  ("apps.documents.typed_models", "SalesReceipt"),
        }
        entry = loaders.get(document_type)
        if not entry:
            return None
        module_path, class_name = entry
        try:
            import importlib
            module = importlib.import_module(module_path)
            model_cls = getattr(module, class_name)
            return model_cls.objects.filter(id=document_id).first()
        except Exception as exc:
            logger.debug("Could not load typed object %s/%s: %s", document_type, document_id, exc)
            return None

    def _user_name(self) -> str:
        if not self.user:
            return "System"
        try:
            return self.user.get_full_name() or self.user.email
        except Exception:
            return str(self.user)

    def _get_suggestion_ar(self, result) -> str:
        try:
            t = result.rule_assignment.rule.translations.filter(language="ar").first()
            return t.suggested_action if t else ""
        except Exception:
            return ""

    def _get_suggestion_en(self, result) -> str:
        try:
            t = result.rule_assignment.rule.translations.filter(language="en").first()
            return t.suggested_action if t else ""
        except Exception:
            return ""

    def _estimate_financial_impact(self, result) -> float:
        """Rough financial impact proxy (risk_contribution * total from evidence)."""
        try:
            for ev in result.evidence_items.all():
                if ev.actual_value and isinstance(ev.actual_value, (int, float)):
                    return round(float(ev.actual_value) * float(result.risk_contribution or 0), 2)
        except Exception:
            pass
        return 0.0

    def _group_assets_by_category(self, assets: list) -> list:
        cats: dict[str, dict] = {}
        for a in assets:
            cat = a.get("category", "Other")
            if cat not in cats:
                cats[cat] = {"category": cat, "count": 0, "total_cost": 0.0, "total_book_value": 0.0}
            cats[cat]["count"] += 1
            cats[cat]["total_cost"]       += float(a.get("cost", 0) or 0)
            cats[cat]["total_book_value"] += float(a.get("book_value", 0) or 0)
        return list(cats.values())

    @staticmethod
    def _doc_type_ar(dt: str) -> str:
        return {
            "sales_invoice":  "فاتورة مبيعات",
            "purchase_order": "أمر شراء",
            "bank_statement": "كشف حساب بنكي",
            "payroll":        "كشف رواتب",
            "expense_report": "تقرير مصروفات",
            "vat_return":     "إقرار ضريبة القيمة المضافة",
            "fixed_asset":    "سجل الأصول الثابتة",
            "sales_receipt":  "إيصال مبيعات",
        }.get(dt, dt)

    @staticmethod
    def _doc_type_en(dt: str) -> str:
        return {
            "sales_invoice":  "Sales Invoice",
            "purchase_order": "Purchase Order",
            "bank_statement": "Bank Statement",
            "payroll":        "Payroll Sheet",
            "expense_report": "Expense Report",
            "vat_return":     "VAT Return",
            "fixed_asset":    "Fixed Asset Register",
            "sales_receipt":  "Sales Receipt",
        }.get(dt, dt)


# ─── Label maps ───────────────────────────────────────────────────────────────

_RULE_STATUS_AR = {
    "pass":            "ناجح",
    "fail":            "فاشل",
    "warning":         "تحذير",
    "skipped":         "متخطى",
    "not_applicable":  "غير قابل للتطبيق",
    "error":           "خطأ",
}

_SEVERITY_AR = {
    "critical": "حرج",
    "high":     "عالي",
    "medium":   "متوسط",
    "low":      "منخفض",
}


# ─── Executive Report Builder ─────────────────────────────────────────────────

class ExecutiveReportService:
    """
    Build a full organization-wide executive report.
    Aggregates data across ALL document types and all audit runs.
    """

    def __init__(self, organization, user=None):
        self.org = organization
        self.user = user

    def build(self, date_from=None, date_to=None, language: str = "ar") -> dict:
        from apps.rule_engine.models import AuditRun, AuditResult, RiskScoreSummary

        runs_qs = AuditRun.objects.filter(
            organization=self.org, status=AuditRun.Status.COMPLETED
        )
        if date_from:
            runs_qs = runs_qs.filter(started_at__date__gte=date_from)
        if date_to:
            runs_qs = runs_qs.filter(started_at__date__lte=date_to)

        risk_qs = RiskScoreSummary.objects.filter(organization=self.org)

        # ── 1. Compute all sections programmatically ──────────────────────────
        meta          = self._build_meta(date_from, date_to, language)
        exec_sum      = self._build_executive(runs_qs, risk_qs)
        financial     = self._build_financial(runs_qs)
        audit_ov      = self._build_audit_overview(runs_qs)
        risk_anal     = self._build_risk_analysis(runs_qs, risk_qs)
        compliance    = self._build_compliance_overview(runs_qs)
        top_issues    = self._build_top_issues(runs_qs)
        ai_data       = self._build_ai_insights(runs_qs)
        recs          = self._build_recommendations(runs_qs)
        doc_breakdown = self._build_doc_breakdown(runs_qs)

        # ── 2. AI narrative: interprets computed numbers, never fabricates ─────
        ai_narrative = self._call_ai_narrative(
            exec_sum=exec_sum,
            audit_ov=audit_ov,
            risk_anal=risk_anal,
            compliance=compliance,
            financial=financial,
            ai_data=ai_data,
            recs=recs,
            language=language,
        )

        # ── 3. Merge AI fields into computed sections ─────────────────────────
        if ai_narrative:
            lang_key = "summary_ar" if language == "ar" else "summary_en"
            if ai_narrative.get("executive_summary"):
                exec_sum[lang_key] = ai_narrative["executive_summary"]
            exec_sum["auditor_opinion"] = ai_narrative.get("auditor_opinion", "")
            exec_sum["key_risks"]       = ai_narrative.get("key_risks", [])
            rule_rationale = ai_narrative.get("rule_rationale", {})
            for rec in recs:
                code = rec.get("rule_code", "")
                if code in rule_rationale:
                    rec["ai_rationale"] = rule_rationale[code]

        return _safe({
            "report_meta":        meta,
            "executive_summary":  exec_sum,
            "financial_overview": financial,
            "audit_overview":     audit_ov,
            "risk_analysis":      risk_anal,
            "compliance_overview":compliance,
            "top_issues":         top_issues,
            "ai_insights":        ai_data,
            "ai_narrative":       ai_narrative or {},
            "recommendations":    recs,
            "document_breakdown": doc_breakdown,
        })

    def _build_meta(self, date_from, date_to, language) -> dict:
        user_name = "System"
        if self.user:
            try:
                user_name = self.user.get_full_name() or self.user.email
            except Exception:
                pass
        return {
            "report_type":       "executive_summary",
            "organization_id":   str(self.org.id),
            "organization_name": getattr(self.org, "name", ""),
            "generated_at":      datetime.now(tz.utc).isoformat(),
            "generated_by":      user_name,
            "period_from":       str(date_from) if date_from else None,
            "period_to":         str(date_to) if date_to else None,
            "language":          language,
        }

    def _build_executive(self, runs_qs, risk_qs) -> dict:
        from django.db.models import Avg, Count, Sum, Q
        stats = runs_qs.aggregate(
            total_runs=Count("id"),
            avg_risk=Avg("risk_score"),
            total_passed=Sum("passed_rules"),
            total_failed=Sum("failed_rules"),
            total_rules=Sum("total_rules"),
            critical_count=Count("id", filter=Q(risk_level="critical")),
            high_count=Count("id", filter=Q(risk_level="high")),
        )
        total_rules = int(stats["total_rules"] or 0)
        total_passed = int(stats["total_passed"] or 0)
        compliance_pct = round(total_passed / total_rules * 100, 1) if total_rules else 0.0
        avg_risk = float(stats["avg_risk"] or 0)
        overall_score = round(100 - avg_risk, 1)

        top_issues_count = int(stats["critical_count"] or 0) + int(stats["high_count"] or 0)

        risk_level = "low"
        if avg_risk >= 70:
            risk_level = "critical"
        elif avg_risk >= 50:
            risk_level = "high"
        elif avg_risk >= 30:
            risk_level = "medium"

        return {
            "overall_score":     overall_score,
            "risk_level":        risk_level,
            "risk_level_ar":     _RISK_LABEL_AR.get(risk_level, ""),
            "compliance_rate":   compliance_pct,
            "avg_risk_score":    round(avg_risk, 1),
            "total_documents":   int(stats["total_runs"] or 0),
            "top_issues_count":  top_issues_count,
            "summary_ar":        self._exec_summary_ar(overall_score, compliance_pct, risk_level),
            "summary_en":        self._exec_summary_en(overall_score, compliance_pct, risk_level),
        }

    def _build_financial(self, runs_qs) -> dict:
        """Aggregate financial figures from canonical data for the reporting period."""
        from apps.documents.canonical_models import DocumentCanonicalData
        doc_ids = list(runs_qs.values_list("document_id", flat=True))
        canonical_qs = DocumentCanonicalData.objects.filter(typed_object_id__in=doc_ids)

        total_revenue = 0.0
        total_expenses = 0.0
        total_vat_payable = 0.0

        revenue_types = {"sales_invoice", "sales_receipt"}
        expense_types = {"purchase_order", "expense_report", "payroll"}
        vat_types = {"vat_return"}

        for rec in canonical_qs:
            amount = float(rec.canonical_data.get("total_amount") or 0)
            if rec.document_type in revenue_types:
                total_revenue += amount
            elif rec.document_type in expense_types:
                total_expenses += amount
            if rec.document_type in vat_types:
                total_vat_payable += float(rec.canonical_data.get("net_vat_payable") or 0)

        return {
            "total_revenue":    round(total_revenue, 2),
            "total_expenses":   round(total_expenses, 2),
            "net_profit":       round(total_revenue - total_expenses, 2),
            "total_vat_payable":round(total_vat_payable, 2),
            "currency":         "SAR",
        }

    def _build_audit_overview(self, runs_qs) -> dict:
        from django.db.models import Count, Sum, Avg, Q
        stats = runs_qs.aggregate(
            total=Count("id"),
            passed_all=Count("id", filter=Q(failed_rules=0)),
            has_failures=Count("id", filter=Q(failed_rules__gt=0)),
            blocking=Count("id", filter=Q(blocks_approval=True)),
            total_passed=Sum("passed_rules"),
            total_failed=Sum("failed_rules"),
            total_rules=Sum("total_rules"),
        )
        total = int(stats["total"] or 0)
        total_rules = int(stats["total_rules"] or 0)

        # Top failed rule codes across all runs
        from apps.rule_engine.models import AuditResult
        top_failures = list(
            AuditResult.objects.filter(audit_run__in=runs_qs, status="fail")
            .values("rule_code")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        return {
            "total_documents_audited": total,
            "clean_documents":   int(stats["passed_all"] or 0),
            "documents_with_issues": int(stats["has_failures"] or 0),
            "blocking_documents": int(stats["blocking"] or 0),
            "pass_rate":         round(int(stats["passed_all"] or 0) / total * 100, 1) if total else 0.0,
            "failure_rate":      round(int(stats["has_failures"] or 0) / total * 100, 1) if total else 0.0,
            "total_rules_evaluated": total_rules,
            "total_rules_passed": int(stats["total_passed"] or 0),
            "total_rules_failed": int(stats["total_failed"] or 0),
            "top_failed_rules":  top_failures,
        }

    def _build_risk_analysis(self, runs_qs, risk_qs) -> dict:
        from django.db.models import Count
        dist = {
            lvl: runs_qs.filter(risk_level=lvl).count()
            for lvl in ("critical", "high", "medium", "low")
        }
        total = sum(dist.values()) or 1

        high_risk_docs = list(
            risk_qs.filter(risk_level__in=("critical", "high"))
            .order_by("-risk_score")
            .values("document_id", "document_type", "risk_score", "risk_level", "blocking_failures")[:10]
        )

        return {
            "distribution":     {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in dist.items()},
            "high_risk_docs":   high_risk_docs,
            "total_critical":   dist["critical"],
            "total_high":       dist["high"],
        }

    def _build_compliance_overview(self, runs_qs) -> dict:
        from apps.rule_engine.models import AuditResult
        from django.db.models import Count

        vat_rules = ["VAT-01", "VAT-02", "VAT-04", "VAT-05", "TAX-M01"]
        vat_failures = AuditResult.objects.filter(
            audit_run__in=runs_qs, status="fail", rule_code__in=vat_rules
        ).count()

        vat_total = AuditResult.objects.filter(
            audit_run__in=runs_qs, rule_code__in=vat_rules
        ).count()

        vat_compliance = round((1 - vat_failures / vat_total) * 100, 1) if vat_total else 100.0

        return {
            "zatca_compliance_rate": vat_compliance,
            "vat_failures":          vat_failures,
            "vat_total_checks":      vat_total,
        }

    def _build_top_issues(self, runs_qs) -> list:
        from apps.rule_engine.models import AuditResult
        from django.db.models import Count, Avg

        issues = list(
            AuditResult.objects.filter(audit_run__in=runs_qs, status="fail")
            .values("rule_code", "applied_severity")
            .annotate(
                count=Count("id"),
                avg_risk=Avg("risk_contribution"),
            )
            .order_by("-count")[:10]
        )
        for issue in issues:
            issue["avg_risk"] = round(float(issue["avg_risk"] or 0), 2)
        return issues

    def _build_ai_insights(self, runs_qs) -> dict:
        from apps.rule_engine.models import AuditResult
        from django.db.models import Count

        # Fraud indicators: critical rules that keep failing
        fraud_rules = ["DUP-04", "BNK-M07", "PAY-M01", "EXP-M07"]
        fraud_count = AuditResult.objects.filter(
            audit_run__in=runs_qs, status="fail", rule_code__in=fraud_rules
        ).count()

        return {
            "fraud_indicator_count": fraud_count,
            "structuring_alerts":    AuditResult.objects.filter(
                audit_run__in=runs_qs, status="fail", rule_code="BNK-M07"
            ).count(),
            "ghost_employee_alerts": AuditResult.objects.filter(
                audit_run__in=runs_qs, status="fail", rule_code="PAY-M01"
            ).count(),
            "duplicate_alerts":      AuditResult.objects.filter(
                audit_run__in=runs_qs, status="fail", rule_code="DUP-04"
            ).count(),
            "self_approval_alerts":  AuditResult.objects.filter(
                audit_run__in=runs_qs, status="fail", rule_code="EXP-M07"
            ).count(),
        }

    def _build_recommendations(self, runs_qs) -> list:
        from apps.rule_engine.models import AuditResult
        from django.db.models import Count

        top_failures = list(
            AuditResult.objects.filter(audit_run__in=runs_qs, status="fail")
            .values("rule_code", "applied_severity")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )
        recs = []
        for f in top_failures:
            recs.append({
                "priority":    f["applied_severity"],
                "rule_code":   f["rule_code"],
                "occurrence":  f["count"],
                "action_ar":   _RULE_RECOMMENDATION_AR.get(f["rule_code"], "راجع نتائج التدقيق وصحّح الأخطاء."),
                "action_en":   _RULE_RECOMMENDATION_EN.get(f["rule_code"], "Review audit findings and correct errors."),
            })
        return recs

    def _call_ai_narrative(
        self,
        exec_sum: dict,
        audit_ov: dict,
        risk_anal: dict,
        compliance: dict,
        financial: dict,
        ai_data: dict,
        recs: list,
        language: str,
    ) -> dict | None:
        """
        Call AI to generate narrative from computed metrics.
        Returns None on any failure — caller uses programmatic fallback.
        """
        try:
            from core.services.ai_service import generate_executive_report_narrative
            return generate_executive_report_narrative(
                computed_metrics={
                    "overall_score":         exec_sum.get("overall_score"),
                    "compliance_rate":       exec_sum.get("compliance_rate"),
                    "risk_level":            exec_sum.get("risk_level"),
                    "avg_risk_score":        exec_sum.get("avg_risk_score"),
                    "total_documents":       exec_sum.get("total_documents"),
                    "top_issues_count":      exec_sum.get("top_issues_count"),
                    "total_critical":        risk_anal.get("total_critical", 0),
                    "total_high":            risk_anal.get("total_high", 0),
                    "pass_rate":             audit_ov.get("pass_rate"),
                    "failure_rate":          audit_ov.get("failure_rate"),
                    "top_failed_rules":      audit_ov.get("top_failed_rules", []),
                    "zatca_compliance_rate": compliance.get("zatca_compliance_rate"),
                    "vat_failures":          compliance.get("vat_failures"),
                    "fraud_indicator_count": ai_data.get("fraud_indicator_count"),
                    "structuring_alerts":    ai_data.get("structuring_alerts"),
                    "ghost_employee_alerts": ai_data.get("ghost_employee_alerts"),
                    "duplicate_alerts":      ai_data.get("duplicate_alerts"),
                    "self_approval_alerts":  ai_data.get("self_approval_alerts"),
                    "financial":             financial,
                },
                language=language,
                org_name=getattr(self.org, "name", ""),
                country=getattr(self.org, "country", "SA"),
            )
        except Exception as exc:
            logger.warning("AI narrative generation skipped: %s", exc)
            return None

    def _build_doc_breakdown(self, runs_qs) -> list:
        from django.db.models import Count, Avg
        return list(
            runs_qs.values("document_type")
            .annotate(
                count=Count("id"),
                avg_risk=Avg("risk_score"),
                failed=Count("id", __import__("django.db.models", fromlist=["Q"]).Q(failed_rules__gt=0)),
            )
            .order_by("-count")
        )

    def _exec_summary_ar(self, score, compliance, risk_level) -> str:
        level_text = _RISK_LABEL_AR.get(risk_level, risk_level)
        return (
            f"التقييم العام للمنشأة: {score:.1f}/100. "
            f"مستوى الامتثال {compliance:.1f}٪. "
            f"مستوى المخاطر: {level_text}."
        )

    def _exec_summary_en(self, score, compliance, risk_level) -> str:
        return (
            f"Overall organizational score: {score:.1f}/100. "
            f"Compliance rate: {compliance:.1f}%. "
            f"Risk level: {risk_level.upper()}."
        )


# ─── Recommendation lookup maps ───────────────────────────────────────────────

_RULE_RECOMMENDATION_AR: dict[str, str] = {
    "VAT-02":   "تحقق من صحة حسابات ضريبة القيمة المضافة: الأساس + الضريبة = الإجمالي.",
    "VAT-01":   "تأكد من ضبط نسبة الضريبة على 15% وفق لوائح الزكاة والضريبة.",
    "VAT-04":   "أضف الرقم الضريبي الصحيح (15 رقمًا تبدأ بـ 3) لجميع الفواتير.",
    "VAT-05":   "تأكد من صلاحية رمز QR في الفواتير الإلكترونية ZATCA.",
    "DUP-04":   "راجع المستندات المكررة وتحقق من عدم الدفع المزدوج.",
    "BNK-M07":  "راجع المعاملات المشبوهة (التجزئة المتعمدة) وأبلغ عنها وفق لوائح AML.",
    "PAY-M01":  "تحقق من قائمة الموظفين وقارنها بسجلات الموارد البشرية.",
    "EXP-M07":  "تطبيق مبدأ الفصل بين الصلاحيات: لا يجوز الموافقة على مصروف النفس.",
    "EXP-M01":  "تأكد من إرفاق إيصالات لجميع بنود المصروفات.",
    "AST-M02":  "راجع الأصول ذات القيمة الدفترية السالبة وصحّح إدخالات الإهلاك.",
    "BNK-M01":  "مطابقة رصيد الافتتاح + الإيداعات - السحوبات = الرصيد الختامي.",
    "TAX-M01":  "تحقق من حساب صافي الضريبة المستحقة: ضريبة المخرجات - ضريبة المدخلات.",
    "GEN-H01":  "أضف رقمًا مرجعيًا فريدًا لكل مستند.",
    "GEN-H02":  "تأكد من تضمين تاريخ المستند في جميع الوثائق.",
}

_RULE_RECOMMENDATION_EN: dict[str, str] = {
    "VAT-02":   "Verify VAT calculations: subtotal + vat_amount must equal total.",
    "VAT-01":   "Ensure VAT rate is set to 15% per ZATCA regulations.",
    "VAT-04":   "Add valid VAT number (15-digit, starting with 3) to all invoices.",
    "VAT-05":   "Verify QR code validity on all e-invoices per ZATCA Phase 2.",
    "DUP-04":   "Investigate duplicate documents and prevent double payment.",
    "BNK-M07":  "Review suspicious transactions near AML threshold and report as required.",
    "PAY-M01":  "Cross-check payroll list against HR records for ghost employees.",
    "EXP-M07":  "Enforce segregation of duties: managers cannot approve own expenses.",
    "EXP-M01":  "Require receipts for all expense lines above minimum threshold.",
    "AST-M02":  "Review assets with negative book values and correct depreciation entries.",
    "BNK-M01":  "Reconcile: opening balance + credits - debits must equal closing balance.",
    "TAX-M01":  "Verify net VAT: output VAT - input VAT = net VAT payable.",
    "GEN-H01":  "Assign a unique reference number to every document.",
    "GEN-H02":  "Include a valid document date in all records.",
}
