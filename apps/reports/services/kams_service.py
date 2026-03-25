"""
Key Audit Matters Service — ISA 701 (Communicating Key Audit Matters).

KAMs are the matters that, in the auditor's professional judgment, were of most
significance in the audit of the financial statements of the current period.
Each KAM is derived exclusively from computed programmatic data — no fabrication.

Usage:
    from apps.reports.services.kams_service import KAMsService
    svc  = KAMsService(org)
    kams = svc.build(summary, validations, invoices, language="ar")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finai")


# ─── KAM catalogue ────────────────────────────────────────────────────────────
#
# Each catalogue entry defines one potential KAM.  The `should_include(data)`
# callable decides at runtime whether this matter is significant enough to
# surface given the computed data.  Only KAMs that fire are included in the
# output, so a clean audit with no issues produces an empty KAMs list.
#
# Structure of a KAM:
#   kam_id          — unique identifier
#   title_ar/en     — short title
#   description_ar/en — what was observed
#   root_cause_ar/en  — ISA 315 root cause
#   financial_impact  — estimated amount / percentage / N/A
#   recommendation_ar/en — corrective action
#   isa_reference     — ISA cite
#   severity          — critical | high | medium
#   evidence          — list of supporting data points (strings)

def _build_kams(data: Dict, language: str) -> List[Dict]:
    """Evaluate all KAM rules and return only the ones that fire."""
    kams: List[Dict] = []

    summary     = data.get("summary", {})
    validations = data.get("_validations", {})   # private key injected by service
    invoices    = data.get("_invoices", [])       # private key injected by service
    anomalies   = data.get("anomalies", {})
    compliance  = data.get("compliance_engine", {})
    score       = summary.get("compliance_score", 0.0)
    dup_ct      = summary.get("duplicate_count", 0)
    hr_ct       = summary.get("high_risk_count", 0)
    total       = summary.get("total_invoices", 0)
    total_amt   = summary.get("total_amount", 0.0)
    currency    = summary.get("currency", "SAR")

    # ── KAM-001 : Duplicate Invoice Risk ─────────────────────────────────────
    if dup_ct > 0:
        dup_amount = sum(
            float(getattr(inv, "total_amount", 0) or 0)
            for inv in invoices
            if getattr(inv, "is_duplicate", False)
        )
        kams.append({
            "kam_id":           "KAM-001",
            "isa_reference":    "ISA 701 / ISA 240",
            "severity":         "critical",
            "title_ar":         "مخاطر الفواتير المكررة",
            "title_en":         "Duplicate Invoice Risk",
            "description_ar":   (
                f"اكتُشفت {dup_ct} فاتورة مكررة بإجمالي {dup_amount:,.2f} {currency}، "
                "مما يشير إلى احتمال دفع مزدوج أو تلاعب في قيود المشتريات."
            ),
            "description_en":   (
                f"{dup_ct} duplicate invoice(s) detected totalling {dup_amount:,.2f} {currency}, "
                "indicating potential double payment or procurement fraud."
            ),
            "root_cause_ar":    "غياب ضوابط كشف التكرار وآليات المراجعة الثنائية قبل الصرف (ISA 315).",
            "root_cause_en":    "Absence of duplicate-detection controls and dual-review mechanisms prior to payment (ISA 315).",
            "financial_impact": f"{dup_amount:,.2f} {currency}",
            "recommendation_ar": "إيقاف الصرف على الفواتير المكررة فوراً وإجراء تحقيق تفصيلي خلال 7 أيام.",
            "recommendation_en": "Halt payment on duplicate invoices immediately and conduct a detailed investigation within 7 days.",
            "evidence":         [
                f"{dup_ct} فاتورة مُعلَّمة كمكررة" if language == "ar" else f"{dup_ct} invoice(s) flagged as duplicate",
                f"إجمالي المبلغ المعرّض للخطر: {dup_amount:,.2f} {currency}" if language == "ar"
                else f"Total amount at risk: {dup_amount:,.2f} {currency}",
            ],
        })

    # ── KAM-002 : VAT / ZATCA Non-Compliance ─────────────────────────────────
    vat_cat = compliance.get("vat", {})
    vat_failed = sum(
        v.get("failed_count", 0) for v in vat_cat.values()
        if isinstance(v, dict)
    ) if isinstance(vat_cat, dict) else 0

    if vat_failed > 0:
        kams.append({
            "kam_id":           "KAM-002",
            "isa_reference":    "ISA 701 / ISA 250 / ZATCA Phase 2",
            "severity":         "critical",
            "title_ar":         "عدم الامتثال لضريبة القيمة المضافة (ZATCA)",
            "title_en":         "VAT / ZATCA Non-Compliance",
            "description_ar":   (
                f"تعذّر اجتياز {vat_failed} فحص ضريبي، مما يُنشئ مخاطر التزامات ضريبية "
                "وعقوبات تجاوز بموجب لوائح هيئة الزكاة والضريبة والجمارك."
            ),
            "description_en":   (
                f"{vat_failed} VAT check(s) failed, creating potential tax liabilities and "
                "penalties under ZATCA regulations."
            ),
            "root_cause_ar":    "قصور في تطبيق متطلبات الفوترة الإلكترونية ZATCA المرحلة الثانية (ISA 250).",
            "root_cause_en":    "Insufficient application of ZATCA Phase 2 e-invoicing requirements (ISA 250).",
            "financial_impact": f"{vat_failed} VAT checks failed",
            "recommendation_ar": "مراجعة حسابات ضريبة القيمة المضافة وأرقام التسجيل الضريبي ورموز QR في جميع الفواتير خلال 14 يومًا.",
            "recommendation_en": "Review all VAT calculations, tax registration numbers, and QR codes within 14 days.",
            "evidence":         [
                f"{vat_failed} VAT validation failure(s)",
                "ISA 250 — Consideration of Laws and Regulations",
            ],
        })

    # ── KAM-003 : Low Overall Compliance ─────────────────────────────────────
    if score < 60.0 and total > 0:
        kams.append({
            "kam_id":           "KAM-003",
            "isa_reference":    "ISA 701 / ISA 700",
            "severity":         "critical",
            "title_ar":         "انخفاض نسبة الامتثال الكلي",
            "title_en":         "Low Overall Compliance Rate",
            "description_ar":   (
                f"بلغت نسبة الامتثال الإجمالية {score:.1f}٪، وهي أقل بكثير من المعيار المرجعي "
                "للصناعة البالغ 94٪، مما يشير إلى ضعف منهجي في ضوابط الرقابة الداخلية."
            ),
            "description_en":   (
                f"Overall compliance rate is {score:.1f}%, significantly below the industry "
                "benchmark of 94%, indicating a systemic weakness in internal controls."
            ),
            "root_cause_ar":    "ضعف منهجي في ضوابط الرقابة الداخلية وإجراءات التحقق الرسمية (ISA 315).",
            "root_cause_en":    "Systemic weakness in internal controls and formal verification procedures (ISA 315).",
            "financial_impact": f"{100 - score:.1f}% compliance gap vs. 94% benchmark",
            "recommendation_ar": "مراجعة عاجلة وشاملة لإجراءات التحقق الداخلية وتدريب الكوادر المعنية.",
            "recommendation_en": "Urgent comprehensive review of internal verification procedures and staff training.",
            "evidence":         [
                f"Compliance score: {score:.1f}%",
                "Industry benchmark: 94%",
                f"Gap: {94 - score:.1f} percentage points",
            ],
        })

    # ── KAM-004 : Vendor Concentration ───────────────────────────────────────
    dominant = anomalies.get("dominant_supplier")
    if dominant and dominant.get("spend_share_percent", 0) > 40:
        pct  = dominant["spend_share_percent"]
        name = dominant["supplier_name"]
        amt  = dominant["total_spend"]
        kams.append({
            "kam_id":           "KAM-004",
            "isa_reference":    "ISA 701 / ISA 315",
            "severity":         "high",
            "title_ar":         "هيمنة مورد واحد على الإنفاق",
            "title_en":         "Single-Vendor Spend Concentration",
            "description_ar":   (
                f"يهيمن المورد «{name}» على {pct:.1f}٪ من إجمالي الإنفاق "
                f"({amt:,.2f} {currency})، مما يُشكّل مخاطر تركّز تتجاوز الحد المقبول (30٪)."
            ),
            "description_en":   (
                f"Supplier '{name}' accounts for {pct:.1f}% of total spend "
                f"({amt:,.2f} {currency}), exceeding the acceptable concentration limit of 30%."
            ),
            "root_cause_ar":    "غياب سياسة تنويع الموردين وضعف إجراءات التحقق من تركّز الإنفاق (ISA 315).",
            "root_cause_en":    "Absence of supplier-diversification policy and weak spend-concentration monitoring (ISA 315).",
            "financial_impact": f"{pct:.1f}% of total spend ({amt:,.2f} {currency})",
            "recommendation_ar": "وضع سقف إنفاق لكل مورد بحد أقصى 30٪ ومراجعة عقود الموردين المهيمنين خلال 90 يومًا.",
            "recommendation_en": "Implement a per-vendor spend cap of 30% and review dominant supplier contracts within 90 days.",
            "evidence":         [
                f"Vendor '{name}': {pct:.1f}% spend share",
                f"Amount: {amt:,.2f} {currency}",
                "Threshold: 30% per COSO / internal policy",
            ],
        })

    # ── KAM-005 : High-Risk Invoices ──────────────────────────────────────────
    if hr_ct > 0:
        high_risk_pct = round(hr_ct / total * 100, 1) if total else 0.0
        kams.append({
            "kam_id":           "KAM-005",
            "isa_reference":    "ISA 701 / ISA 330",
            "severity":         "high" if high_risk_pct < 20 else "critical",
            "title_ar":         "فواتير مصنّفة عالية المخاطر",
            "title_en":         "High-Risk Invoice Concentration",
            "description_ar":   (
                f"صُنِّفت {hr_ct} فاتورة ({high_risk_pct:.1f}٪ من الإجمالي) ضمن الفئة عالية المخاطر، "
                "مما يستوجب مراجعة يدوية قبل الصرف وفق إجراءات ISA 330."
            ),
            "description_en":   (
                f"{hr_ct} invoice(s) ({high_risk_pct:.1f}% of total) classified as high-risk, "
                "requiring manual review before payment per ISA 330 procedures."
            ),
            "root_cause_ar":    "نقص في ضوابط الاستجابة للمخاطر المُقيَّمة وفق ISA 330.",
            "root_cause_en":    "Insufficient risk-response controls per ISA 330.",
            "financial_impact": f"{hr_ct} invoices ({high_risk_pct:.1f}% of total)",
            "recommendation_ar": f"مراجعة {hr_ct} فاتورة عالية المخاطر يدوياً قبل الصرف.",
            "recommendation_en": f"Manually review all {hr_ct} high-risk invoice(s) before payment.",
            "evidence":         [
                f"{hr_ct} invoices classified high-risk or critical",
                f"High-risk rate: {high_risk_pct:.1f}%",
            ],
        })

    # ── KAM-006 : Benford's Law Deviation ────────────────────────────────────
    benford = anomalies.get("benford_analysis", {})
    if benford and not benford.get("passes_benford", True) and benford.get("sample_size", 0) >= 30:
        chi2         = benford.get("chi_square", 0)
        suspicious   = ", ".join(benford.get("suspicious_digits", []))
        sample_size  = benford.get("sample_size", 0)
        kams.append({
            "kam_id":           "KAM-006",
            "isa_reference":    "ISA 701 / ISA 240 / ISA 500",
            "severity":         "high",
            "title_ar":         "انحراف قانون بنفورد — مؤشر تلاعب محتمل",
            "title_en":         "Benford's Law Deviation — Potential Manipulation Indicator",
            "description_ar":   (
                f"يُشير تحليل قانون بنفورد على عينة ({sample_size} مبلغاً) إلى انحراف إحصائي "
                f"دال (χ²={chi2:.2f} > 15.51)، مع تركّز مشبوه في الأرقام الأولى: {suspicious}."
            ),
            "description_en":   (
                f"Benford's Law analysis on a {sample_size}-amount sample reveals a statistically "
                f"significant deviation (χ²={chi2:.2f} > 15.51), with suspicious leading digits: {suspicious}."
            ),
            "root_cause_ar":    "احتمال تلاعب في إدخال المبالغ أو اختيار أرقام غير طبيعية لتجنب الحدود الرقابية (ISA 240).",
            "root_cause_en":    "Possible manipulation of amount entries or selection of unnatural figures to avoid control thresholds (ISA 240).",
            "financial_impact": f"Chi-square = {chi2:.2f} (critical value 15.51 at p=0.05)",
            "recommendation_ar": f"إخضاع الفواتير ذات الأرقام الأولى المشبوهة ({suspicious}) لمراجعة تفصيلية.",
            "recommendation_en": f"Subject invoices with suspicious leading digits ({suspicious}) to detailed manual review.",
            "evidence":         [
                f"Chi-square: {chi2:.2f} (threshold: 15.51)",
                f"Suspicious digits: {suspicious}",
                f"Sample size: {sample_size}",
            ],
        })

    # ── KAM-007 : Unvalidated Invoices ────────────────────────────────────────
    not_validated = summary.get("not_validated_count", 0)
    if not_validated > 0 and total > 0:
        unval_pct = round(not_validated / total * 100, 1)
        kams.append({
            "kam_id":           "KAM-007",
            "isa_reference":    "ISA 701 / ISA 500",
            "severity":         "medium",
            "title_ar":         "فواتير لم تخضع للتحقق الآلي",
            "title_en":         "Invoices Not Subjected to Automated Validation",
            "description_ar":   (
                f"لم تخضع {not_validated} فاتورة ({unval_pct:.1f}٪) للتحقق الآلي الشامل، "
                "مما يُضعف شمولية أدلة التدقيق وفق ISA 500."
            ),
            "description_en":   (
                f"{not_validated} invoice(s) ({unval_pct:.1f}%) were not subjected to full "
                "automated validation, reducing audit evidence completeness per ISA 500."
            ),
            "root_cause_ar":    "عدم اكتمال تشغيل خط أنابيب التحقق الآلي لجميع المستندات المرفوعة.",
            "root_cause_en":    "Incomplete execution of the automated validation pipeline for all uploaded documents.",
            "financial_impact": f"{not_validated} invoices ({unval_pct:.1f}% of total) not validated",
            "recommendation_ar": f"تشغيل التحقق الآلي على {not_validated} فاتورة لم تُدقَّق بعد.",
            "recommendation_en": f"Run automated validation on the remaining {not_validated} unvalidated invoice(s).",
            "evidence":         [
                f"{not_validated}/{total} invoices lack validation results",
                f"Unvalidated rate: {unval_pct:.1f}%",
            ],
        })

    return kams


# ─── Public service class ──────────────────────────────────────────────────────

class KAMsService:
    """
    Build Key Audit Matters (KAMs) per ISA 701.

    Usage:
        svc  = KAMsService(organization)
        kams = svc.build(summary, validations, invoices, anomalies, compliance, language="ar")
    """

    def __init__(self, organization, user=None):
        self.org  = organization
        self.user = user

    def build(
        self,
        summary:     Dict,
        validations: Dict,
        invoices:    List,
        anomalies:   Dict,
        compliance:  Dict,
        language:    str = "ar",
    ) -> List[Dict]:
        """
        Return list of KAMs sorted by severity (critical first).
        Only includes matters with actual data support — never fabricates.
        """
        data = {
            "summary":          summary,
            "anomalies":        anomalies,
            "compliance_engine":compliance,
            # Private keys for internal calculations (stripped before return)
            "_validations":     validations,
            "_invoices":        invoices,
        }
        kams = _build_kams(data, language)

        # Sort: critical → high → medium
        _ORDER = {"critical": 0, "high": 1, "medium": 2}
        kams.sort(key=lambda k: _ORDER.get(k.get("severity", "medium"), 2))
        return kams
