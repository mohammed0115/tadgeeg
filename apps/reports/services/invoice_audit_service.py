"""
InvoiceAuditReportService — Clean service layer for Invoice Audit Reports.

Architecture principles:
  - Single responsibility: one class, one job (build report dict)
  - Tenant-isolated: every queryset is scoped to self.org, never leaks
  - Read-only: no mutations — pure data transformation
  - Single entry point: build() → dict (JSON-safe)
  - Performance: bulk queries + dicts, no N+1 loops
  - Extensible: each report section is an independent method

Maps the 34 boolean fields of InvoiceValidationResult to named rules with
category, weight, severity, and bilingual labels.  "Inverted" rules (True = BAD,
e.g. duplicate_invoice_number) are handled explicitly so callers never need to
know the inversion logic.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.utils import timezone

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Risk Policy (configurable — could be moved to Django settings later)
# ─────────────────────────────────────────────────────────────────────────────

RISK_THRESHOLDS: Dict[str, float] = {
    "safe":      85.0,   # compliance_score >= 85  → safe
    "review":    60.0,   # 60 <= score < 85        → review
    # below 60                                      → high_risk
}


def classify_risk(compliance_score: float) -> str:
    """Map a compliance score (0–100) to a risk tier string."""
    if compliance_score >= RISK_THRESHOLDS["safe"]:
        return "safe"
    if compliance_score >= RISK_THRESHOLDS["review"]:
        return "review"
    return "high_risk"


RISK_LABEL_AR = {"safe": "آمن", "review": "مراجعة", "high_risk": "عالي المخاطر"}
RISK_LABEL_EN = {"safe": "Safe", "review": "Review", "high_risk": "High Risk"}


# ─────────────────────────────────────────────────────────────────────────────
# Rule Registry — maps every InvoiceValidationResult field to a named rule
# ─────────────────────────────────────────────────────────────────────────────

#  code      field_name                   title_ar                              title_en                        cat        weight  severity  inverted
RULE_REGISTRY: List[Dict] = [
    # ── Group 1: Invoice Header (8) ──────────────────────────────────────────
    {"code": "HDR-001", "field": "has_invoice_number",       "title_ar": "رقم الفاتورة",              "title_en": "Invoice Number",           "category": "header",    "weight": 10, "severity": "high",     "inverted": False},
    {"code": "HDR-002", "field": "has_invoice_date",         "title_ar": "تاريخ الفاتورة",            "title_en": "Invoice Date",             "category": "header",    "weight":  8, "severity": "high",     "inverted": False},
    {"code": "HDR-003", "field": "has_vendor_name",          "title_ar": "اسم المورد",                "title_en": "Vendor Name",              "category": "header",    "weight":  8, "severity": "medium",   "inverted": False},
    {"code": "HDR-004", "field": "has_vendor_vat",           "title_ar": "رقم الضريبة",               "title_en": "Vendor VAT Number",        "category": "header",    "weight": 15, "severity": "critical", "inverted": False},
    {"code": "HDR-005", "field": "has_total_amount",         "title_ar": "إجمالي المبلغ",             "title_en": "Total Amount",             "category": "header",    "weight": 10, "severity": "high",     "inverted": False},
    {"code": "HDR-006", "field": "has_currency",             "title_ar": "العملة",                    "title_en": "Currency",                 "category": "header",    "weight":  5, "severity": "medium",   "inverted": False},
    {"code": "HDR-007", "field": "total_greater_zero",       "title_ar": "المبلغ أكبر من صفر",        "title_en": "Amount Greater Than Zero", "category": "header",    "weight": 10, "severity": "high",     "inverted": False},
    {"code": "HDR-008", "field": "no_vat_without_base",      "title_ar": "عدم وجود ضريبة بدون وعاء", "title_en": "No VAT Without Base",      "category": "header",    "weight":  8, "severity": "high",     "inverted": False},
    # ── Group 2: Duplicate Detection (5) — True = problem found ─────────────
    {"code": "DUP-001", "field": "duplicate_invoice_number",   "title_ar": "تكرار رقم الفاتورة",        "title_en": "Duplicate Invoice Number",       "category": "duplicate", "weight": 20, "severity": "critical", "inverted": True},
    {"code": "DUP-002", "field": "duplicate_vendor_and_number","title_ar": "تكرار المورد والرقم",        "title_en": "Duplicate Vendor + Number",      "category": "duplicate", "weight": 15, "severity": "critical", "inverted": True},
    {"code": "DUP-003", "field": "duplicate_vendor_amount_date","title_ar": "تكرار المورد والمبلغ والتاريخ","title_en": "Duplicate Vendor+Amount+Date", "category": "duplicate", "weight": 15, "severity": "high",     "inverted": True},
    {"code": "DUP-004", "field": "duplicate_file_hash",        "title_ar": "تكرار بصمة الملف",           "title_en": "Duplicate File Hash",            "category": "duplicate", "weight": 20, "severity": "critical", "inverted": True},
    {"code": "DUP-005", "field": "duplicate_across_months",    "title_ar": "تكرار عبر الأشهر",           "title_en": "Duplicate Across Months",        "category": "duplicate", "weight": 10, "severity": "high",     "inverted": True},
    # ── Group 3: VAT Validation (5) ─────────────────────────────────────────
    {"code": "VAT-001", "field": "vat_rate_correct",        "title_ar": "نسبة الضريبة صحيحة",         "title_en": "VAT Rate Correct",             "category": "vat",       "weight": 15, "severity": "critical", "inverted": False},
    {"code": "VAT-002", "field": "vat_calculation_correct", "title_ar": "حساب الضريبة صحيح",           "title_en": "VAT Calculation Correct",      "category": "vat",       "weight": 15, "severity": "critical", "inverted": False},
    {"code": "VAT-003", "field": "vat_subtotal_correct",    "title_ar": "الإجمالي قبل الضريبة صحيح",  "title_en": "VAT Subtotal Correct",         "category": "vat",       "weight": 10, "severity": "high",     "inverted": False},
    {"code": "VAT-004", "field": "vat_number_present",      "title_ar": "رقم التسجيل الضريبي موجود",  "title_en": "VAT Number Present",           "category": "vat",       "weight": 15, "severity": "critical", "inverted": False},
    {"code": "VAT-005", "field": "qr_code_valid",           "title_ar": "رمز QR صالح (ZATCA)",        "title_en": "QR Code Valid (ZATCA)",        "category": "vat",       "weight": 15, "severity": "high",     "inverted": False},
    # ── Group 4: Anomaly Detection (6) — True = anomaly flagged ─────────────
    {"code": "ANO-001", "field": "amount_unusually_high",     "title_ar": "مبلغ مرتفع بشكل غير عادي",  "title_en": "Unusually High Amount",       "category": "anomaly",   "weight": 10, "severity": "medium",   "inverted": True},
    {"code": "ANO-002", "field": "new_unknown_vendor",        "title_ar": "مورد جديد غير معروف",        "title_en": "New Unknown Vendor",          "category": "anomaly",   "weight":  8, "severity": "medium",   "inverted": True},
    {"code": "ANO-003", "field": "many_invoices_same_day",    "title_ar": "فواتير متعددة في يوم واحد",  "title_en": "Many Invoices Same Day",      "category": "anomaly",   "weight":  8, "severity": "medium",   "inverted": True},
    {"code": "ANO-004", "field": "sudden_price_change",       "title_ar": "تغير مفاجئ في الأسعار",     "title_en": "Sudden Price Change",         "category": "anomaly",   "weight": 10, "severity": "high",     "inverted": True},
    {"code": "ANO-005", "field": "many_invoices_year_end",    "title_ar": "فواتير كثيرة في نهاية العام","title_en": "Year-End Invoice Surge",      "category": "anomaly",   "weight":  8, "severity": "medium",   "inverted": True},
    {"code": "ANO-006", "field": "vendor_dominates_invoices", "title_ar": "هيمنة مورد واحد على الإنفاق","title_en": "Vendor Dominates Spending",   "category": "anomaly",   "weight":  8, "severity": "medium",   "inverted": True},
    # ── Group 5: Financial Control (6) ──────────────────────────────────────
    {"code": "CTL-001", "field": "has_cost_center",       "title_ar": "مركز التكلفة موجود",        "title_en": "Cost Center Present",       "category": "control",   "weight":  8, "severity": "medium",   "inverted": False},
    {"code": "CTL-002", "field": "has_account_code",      "title_ar": "كود الحساب موجود",          "title_en": "Account Code Present",      "category": "control",   "weight":  8, "severity": "medium",   "inverted": False},
    {"code": "CTL-003", "field": "within_budget",         "title_ar": "ضمن حدود الميزانية",        "title_en": "Within Budget",             "category": "control",   "weight": 10, "severity": "high",     "inverted": False},
    {"code": "CTL-004", "field": "no_edit_after_approve", "title_ar": "لا تعديل بعد الموافقة",     "title_en": "No Edit After Approval",    "category": "control",   "weight": 10, "severity": "critical", "inverted": False},
    {"code": "CTL-005", "field": "has_approver",          "title_ar": "فاتورة معتمدة",             "title_en": "Has Approver",              "category": "control",   "weight": 10, "severity": "high",     "inverted": False},
    {"code": "CTL-006", "field": "has_audit_trail",       "title_ar": "مسار التدقيق موجود",        "title_en": "Audit Trail Present",       "category": "control",   "weight":  8, "severity": "medium",   "inverted": False},
    # ── Group 6: Document Quality (4) ───────────────────────────────────────
    {"code": "DOC-001", "field": "document_is_clear",  "title_ar": "وضوح المستند",              "title_en": "Document Is Clear",         "category": "document",  "weight":  5, "severity": "low",      "inverted": False},
    {"code": "DOC-002", "field": "appears_genuine",    "title_ar": "مظهر الوثيقة أصلية",       "title_en": "Appears Genuine",           "category": "document",  "weight": 10, "severity": "high",     "inverted": False},
    {"code": "DOC-003", "field": "no_alterations",     "title_ar": "لا توجد تعديلات مشبوهة",   "title_en": "No Alterations Detected",   "category": "document",  "weight": 10, "severity": "high",     "inverted": False},
    {"code": "DOC-004", "field": "has_qr_code",        "title_ar": "رمز QR موجود",             "title_en": "QR Code Present",           "category": "document",  "weight": 10, "severity": "high",     "inverted": False},
]

# Fast lookup: field name → rule dict
_RULE_BY_FIELD: Dict[str, Dict] = {r["field"]: r for r in RULE_REGISTRY}
# Fast lookup: rule code → rule dict
_RULE_BY_CODE: Dict[str, Dict] = {r["code"]: r for r in RULE_REGISTRY}

TOTAL_RULES = len(RULE_REGISTRY)  # 34 actual fields


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe(v: Any) -> Any:
    """Recursively convert Decimal / date / datetime / UUID to JSON primitives."""
    import uuid, datetime as dt
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


def _rule_failed(rule: Dict, validation) -> bool:
    """
    Return True if this rule failed on the given InvoiceValidationResult.
    Inverted rules (True = bad) are handled here so callers never need
    to know about the inversion semantics.
    """
    val = getattr(validation, rule["field"], None)
    if val is None:
        return False
    return bool(val) if rule["inverted"] else not bool(val)


def _violations_for(validation) -> List[Dict]:
    """Return all failed rules for a single InvoiceValidationResult."""
    return [
        {
            "rule_code": rule["code"],
            "title_ar":  rule["title_ar"],
            "title_en":  rule["title_en"],
            "category":  rule["category"],
            "severity":  rule["severity"],
            "weight":    rule["weight"],
        }
        for rule in RULE_REGISTRY
        if _rule_failed(rule, validation)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main Service
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportService:
    """
    Build the complete Invoice Audit Report dict.

    Usage:
        svc  = InvoiceAuditReportService(org, request.user)
        data = svc.build(date_from=date(2025,1,1), date_to=date(2025,12,31))

    Returns a fully JSON-safe dict with 10 sections.
    The dict can be stored directly in Report.data (JSONField) or
    serialized with InvoiceAuditReportSerializer.
    """

    def __init__(self, organization, user=None):
        self.org  = organization
        self.user = user

    # ── Public entry point ────────────────────────────────────────────────────

    def build(
        self,
        date_from: Optional[date] = None,
        date_to:   Optional[date] = None,
        language:  str = "ar",
    ) -> Dict:
        """
        Build and return the full report dict.
        Single DB round-trip strategy:
          1. One queryset for invoices (with select_related)
          2. One queryset for validation results
          3. One queryset for vendor profiles
        No N+1, no per-invoice queries.
        """
        from apps.invoices.models import Invoice, InvoiceValidationResult, VendorProfile

        # ── 1. Tenant-scoped invoice queryset ─────────────────────────────────
        inv_qs = (
            Invoice.objects
            .filter(organization=self.org)
            .select_related("validation")
        )
        if date_from:
            inv_qs = inv_qs.filter(invoice_date__gte=date_from)
        if date_to:
            inv_qs = inv_qs.filter(invoice_date__lte=date_to)

        invoices: List = list(inv_qs)
        invoice_ids = [inv.id for inv in invoices]

        # ── 2. Validation results map {invoice_id → InvoiceValidationResult} ──
        validations: Dict = {
            v.invoice_id: v
            for v in InvoiceValidationResult.objects
            .filter(invoice_id__in=invoice_ids)
            .select_related("invoice")
        }

        # ── 3. Vendor profiles map {vendor_name → VendorProfile} ──────────────
        vendor_profiles: Dict = {
            vp.vendor_name: vp
            for vp in VendorProfile.objects.filter(organization=self.org)
        }

        # ── 4. Assemble sections ───────────────────────────────────────────────
        summary = self._build_summary(invoices, validations)

        compliance_engine = self._build_compliance_engine(validations)
        anomalies         = self._build_anomalies(invoices, validations)

        # KAMs — ISA 701
        from apps.reports.services.kams_service import KAMsService
        kams = KAMsService(self.org, self.user).build(
            summary=summary,
            validations=validations,
            invoices=invoices,
            anomalies=anomalies,
            compliance=compliance_engine,
            language=language,
        )

        # ISA 700 Opinion — Comprehensive auditor opinion report
        from apps.reports.services.isa700_opinion_service import ISA700OpinionService
        isa700_service = ISA700OpinionService(self.org, self.user)
        isa700_opinion_report = isa700_service.generate_opinion(
            summary=summary,
            validations=validations,
            invoices=invoices,
            kams_list=kams.get("kams", []) if isinstance(kams, dict) else [],
            compliance_engine=compliance_engine,
            anomalies=anomalies,
            scope_limitations=None,  # Can be customized per engagement
        )

        # IAS 7 Cash Flow Classification — Classify invoices per IAS 7:2017
        from apps.analytics.ias7_cashflow_service import IAS7CashFlowService
        ias7_service = IAS7CashFlowService(self.org, self.user)
        ias7_classifications = ias7_service.classify_invoices(invoices)
        ias7_cashflow_statement = ias7_service.build_cashflow_statement(invoices)

        report = {
            "report_header":               self._build_header(date_from, date_to, language, summary),
            "summary":                     summary,
            "executive_summary":           self._build_executive_summary(summary, validations, language),
            "compliance_engine":           compliance_engine,
            "high_risk_invoices":          self._build_high_risk_invoices(invoices, validations),
            "failed_rules_analysis":       self._build_failed_rules(validations),
            "supplier_analysis":           self._build_supplier_analysis(invoices, vendor_profiles),
            "risk_analysis":               self._build_risk_analysis(invoices, validations),
            "anomalies":                   anomalies,
            "root_cause_analysis":         self._build_root_cause_analysis(validations),
            "key_audit_matters":           kams,          # ISA 701
            "isa700_auditor_opinion":      isa700_opinion_report,  # ISA 700 comprehensive report
            "ias7_cashflow_classification": ias7_classifications,   # IAS 7 cash flow statement
            "ias7_cashflow_statement":     ias7_cashflow_statement, # IAS 7:2017 structure
            "actions_and_recommendations": self._build_recommendations(summary, validations),
        }
        return _safe(report)

    # ── Section: report_header ────────────────────────────────────────────────

    def _build_header(self, date_from, date_to, language, summary: Dict) -> Dict:
        risk   = summary.get("risk_level", "safe")
        score  = summary.get("compliance_score", 0.0)
        status = (
            "critical" if risk == "high_risk" and score < 40
            else "issues_found" if risk in ("high_risk", "review")
            else "clean"
        )
        return {
            "report_id":        None,           # filled by view after save
            "title":            "تقرير تدقيق الفواتير" if language == "ar" else "Invoice Audit Report",
            "organization_name": getattr(self.org, "name", str(self.org)),
            "organization_id":  str(self.org.id),
            "created_at":       datetime.now(tz=dt_timezone.utc).isoformat(),
            "created_by":       str(self.user) if self.user else None,
            "report_type":      "invoice_audit",
            "language":         language,
            "period_from":      date_from.isoformat() if date_from else None,
            "period_to":        date_to.isoformat()   if date_to   else None,
            "overall_status":   status,
            "overall_status_ar": {"clean": "نظيف", "issues_found": "يحتوي مشاكل", "critical": "حرج"}.get(status, status),
            "isa700_opinion":   self._determine_isa700_opinion(summary),
        }

    def _determine_isa700_opinion(self, summary: Dict) -> Dict:
        """
        Determine formal ISA 700 auditor opinion from computed summary.

        Opinion types (ISA 700 / ISA 705):
          unqualified  — fully compliant, no material misstatements
          qualified    — material issues found but not pervasive
          adverse      — pervasive material misstatements
          disclaimer   — insufficient evidence to form an opinion
        """
        total     = summary.get("total_invoices", 0)
        validated = summary.get("validated_count", 0)
        score     = summary.get("compliance_score", 0.0)
        dup_ct    = summary.get("duplicate_count", 0)
        hr_ct     = summary.get("high_risk_count", 0)

        if total == 0 or validated == 0:
            otype    = "disclaimer"
            basis_ar = "لا تتوفر بيانات فواتير كافية لإبداء رأي تدقيق رسمي."
            basis_en = "Insufficient invoice data to form a formal audit opinion."
        elif score >= RISK_THRESHOLDS["safe"] and dup_ct == 0:
            otype    = "unqualified"
            basis_ar = (
                f"امتثلت الفواتير المدققة ({validated} فاتورة) لمتطلبات إطار إعداد التقارير المالية "
                f"بنسبة امتثال {score:.1f}٪، دون وجود مخالفات جوهرية."
            )
            basis_en = (
                f"The audited invoices ({validated}) comply with the applicable financial reporting "
                f"framework at a {score:.1f}% compliance rate with no material misstatements detected."
            )
        elif score >= RISK_THRESHOLDS["review"]:
            otype    = "qualified"
            basis_ar = (
                f"وُجدت مسائل جوهرية (نسبة امتثال {score:.1f}٪، {dup_ct} تكرار، "
                f"{hr_ct} فاتورة عالية المخاطر) غير منتشرة بشكل يؤثر على التقرير ككل. (ISA 705)"
            )
            basis_en = (
                f"Material issues identified (compliance {score:.1f}%, {dup_ct} duplicate(s), "
                f"{hr_ct} high-risk invoice(s)), but not pervasive enough to affect the report "
                "as a whole. (ISA 705)"
            )
        else:
            otype    = "adverse"
            basis_ar = (
                f"المخالفات الجوهرية منتشرة على نطاق واسع (نسبة امتثال {score:.1f}٪، "
                f"{dup_ct} تكرار، {hr_ct} عالي المخاطر) مما يجعل البيانات المالية مُضلِّلة ككل. "
                "(ISA 705 الفقرة 8)"
            )
            basis_en = (
                f"Material misstatements are pervasive (compliance {score:.1f}%, "
                f"{dup_ct} duplicate(s), {hr_ct} high-risk invoice(s)), rendering the financial "
                "statements as a whole misleading. (ISA 705 para. 8)"
            )

        _LABELS = {
            "unqualified": {"ar": "غير متحفظ",       "en": "Unqualified"},
            "qualified":   {"ar": "متحفظ",           "en": "Qualified"},
            "adverse":     {"ar": "سلبي",            "en": "Adverse"},
            "disclaimer":  {"ar": "امتناع عن الرأي", "en": "Disclaimer of Opinion"},
        }
        return {
            "opinion_type":    otype,
            "opinion_type_ar": _LABELS[otype]["ar"],
            "opinion_type_en": _LABELS[otype]["en"],
            "basis_ar":        basis_ar,
            "basis_en":        basis_en,
            "standard":        "ISA 700 / ISA 705",
        }

    # ── Section: summary ──────────────────────────────────────────────────────

    def _build_summary(self, invoices: List, validations: Dict) -> Dict:
        total = len(invoices)
        if not total:
            return self._empty_summary()

        total_amount   = sum(float(inv.total_amount or 0) for inv in invoices)
        scores         = [v.validation_score for v in validations.values() if v.validation_score is not None]
        avg_score      = sum(scores) / len(scores) if scores else 0.0
        risk_scores    = [float(inv.risk_score or 0) for inv in invoices if inv.risk_score is not None]
        avg_risk       = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
        duplicate_ct   = sum(1 for inv in invoices if inv.is_duplicate)
        high_risk_ct   = sum(1 for inv in invoices if getattr(inv, "risk_level", None) in ("high", "critical"))
        flagged_ct     = sum(1 for inv in invoices if inv.status == "flagged")
        currencies     = list({inv.currency for inv in invoices if inv.currency})
        primary_cur    = currencies[0] if len(currencies) == 1 else "SAR"

        return {
            "total_invoices":      total,
            "total_amount":        round(total_amount, 2),
            "currency":            primary_cur,
            "compliance_score":    round(avg_score, 1),
            "average_risk_score":  round(avg_risk, 1),
            "risk_level":          classify_risk(avg_score),
            "risk_level_ar":       RISK_LABEL_AR.get(classify_risk(avg_score), ""),
            "risk_level_en":       RISK_LABEL_EN.get(classify_risk(avg_score), ""),
            "duplicate_count":     duplicate_ct,
            "high_risk_count":     high_risk_ct,
            "flagged_count":       flagged_ct,
            "validated_count":     len(validations),
            "not_validated_count": total - len(validations),
        }

    def _empty_summary(self) -> Dict:
        return {
            "total_invoices": 0, "total_amount": 0.0, "currency": "SAR",
            "compliance_score": 0.0, "average_risk_score": 0.0,
            "risk_level": "safe", "risk_level_ar": "آمن", "risk_level_en": "Safe",
            "duplicate_count": 0, "high_risk_count": 0, "flagged_count": 0,
            "validated_count": 0, "not_validated_count": 0,
        }

    # ── Section: executive_summary ────────────────────────────────────────────

    def _build_executive_summary(self, summary: Dict, validations: Dict, language: str) -> Dict:
        score    = summary["compliance_score"]
        risk     = summary["risk_level"]
        risk_lbl = RISK_LABEL_AR[risk] if language == "ar" else RISK_LABEL_EN[risk]

        # Key findings (up to 5 significant observations)
        findings = []
        if summary["duplicate_count"]:
            findings.append({
                "code": "FIND-DUP",  "severity": "critical",
                "title_ar": f"اكتُشفت {summary['duplicate_count']} فاتورة مكررة",
                "title_en": f"{summary['duplicate_count']} duplicate invoice(s) detected",
            })
        if summary["high_risk_count"]:
            findings.append({
                "code": "FIND-HIGH",  "severity": "high",
                "title_ar": f"{summary['high_risk_count']} فاتورة مصنّفة عالية المخاطر",
                "title_en": f"{summary['high_risk_count']} invoice(s) classified as high risk",
            })
        if score < 60:
            findings.append({
                "code": "FIND-LOW-COMPLIANCE",  "severity": "critical",
                "title_ar": f"معدل الامتثال منخفض: {score:.1f}%",
                "title_en": f"Low compliance rate: {score:.1f}%",
            })
        if summary["flagged_count"]:
            findings.append({
                "code": "FIND-FLAGGED",  "severity": "high",
                "title_ar": f"{summary['flagged_count']} فاتورة مُعلَّمة للمراجعة",
                "title_en": f"{summary['flagged_count']} invoice(s) flagged for review",
            })
        if summary["not_validated_count"]:
            findings.append({
                "code": "FIND-NOT-VALIDATED",  "severity": "medium",
                "title_ar": f"{summary['not_validated_count']} فاتورة لم تُدقَّق بعد",
                "title_en": f"{summary['not_validated_count']} invoice(s) not yet validated",
            })

        if language == "ar":
            conclusion = (
                f"يُظهر التقرير معدل امتثال إجمالي {score:.1f}% "
                f"على {summary['total_invoices']} فاتورة بإجمالي "
                f"{summary['total_amount']:,.0f} {summary['currency']}. "
                f"مستوى المخاطر: {risk_lbl}."
            )
        else:
            conclusion = (
                f"Report shows {score:.1f}% overall compliance across "
                f"{summary['total_invoices']} invoice(s) totalling "
                f"{summary['total_amount']:,.2f} {summary['currency']}. "
                f"Risk level: {risk_lbl}."
            )

        return {
            "conclusion":       conclusion,
            "compliance_score": score,
            "risk_level":       risk,
            "risk_level_ar":    RISK_LABEL_AR[risk],
            "risk_level_en":    RISK_LABEL_EN[risk],
            "key_findings":     findings,
        }

    # ── Section: compliance_engine ────────────────────────────────────────────

    def _build_compliance_engine(self, validations: Dict) -> Dict:
        if not validations:
            return {
                "total_rules": TOTAL_RULES, "total_checks": 0,
                "passed_rules": 0, "failed_rules": 0, "overall_score": 0.0,
                "by_category": {},
            }

        # Per-rule aggregation in one pass
        rule_pass   = defaultdict(int)  # code → pass count
        rule_fail   = defaultdict(int)  # code → fail count
        cat_pass    = defaultdict(int)  # category → pass count
        cat_fail    = defaultdict(int)  # category → fail count

        for v in validations.values():
            for rule in RULE_REGISTRY:
                failed = _rule_failed(rule, v)
                if failed:
                    rule_fail[rule["code"]]   += 1
                    cat_fail[rule["category"]] += 1
                else:
                    rule_pass[rule["code"]]   += 1
                    cat_pass[rule["category"]] += 1

        n = len(validations)
        total_checks  = n * TOTAL_RULES
        total_passed  = sum(rule_pass.values())
        total_failed  = sum(rule_fail.values())
        overall_score = total_passed / total_checks * 100 if total_checks else 0.0

        categories = sorted({r["category"] for r in RULE_REGISTRY})
        by_category = {}
        for cat in categories:
            p = cat_pass[cat]
            f = cat_fail[cat]
            total_cat = p + f
            by_category[cat] = {
                "passed":     p,
                "failed":     f,
                "score":      round(p / total_cat * 100, 1) if total_cat else 0.0,
                "rule_count": sum(1 for r in RULE_REGISTRY if r["category"] == cat),
            }

        return {
            "total_rules":   TOTAL_RULES,
            "total_checks":  total_checks,
            "passed_rules":  total_passed,
            "failed_rules":  total_failed,
            "overall_score": round(overall_score, 1),
            "by_category":   by_category,
        }

    # ── Section: high_risk_invoices ───────────────────────────────────────────

    def _build_high_risk_invoices(
        self, invoices: List, validations: Dict, limit: int = 25
    ) -> List[Dict]:
        high_risk = [
            inv for inv in invoices
            if getattr(inv, "risk_level", None) in ("high", "critical")
            or float(inv.risk_score or 0) >= 60
        ]
        high_risk.sort(key=lambda i: float(i.risk_score or 0), reverse=True)

        result = []
        for inv in high_risk[:limit]:
            v          = validations.get(inv.id)
            violations = _violations_for(v) if v else []
            result.append({
                "id":               str(inv.id),
                "invoice_number":   inv.invoice_number or "—",
                "supplier_name":    inv.vendor_name or "—",
                "invoice_date":     inv.invoice_date.isoformat() if inv.invoice_date else None,
                "amount":           float(inv.total_amount or 0),
                "currency":         inv.currency or "SAR",
                "risk_level":       inv.risk_level or "unknown",
                "risk_score":       float(inv.risk_score or 0),
                "compliance_score": v.validation_score if v else None,
                "is_duplicate":     bool(inv.is_duplicate),
                "is_flagged":       inv.status == "flagged",
                "violations":       violations[:6],       # top 6 violations
                "violation_count":  len(violations),
            })
        return result

    # ── Section: failed_rules_analysis ───────────────────────────────────────

    def _build_failed_rules(self, validations: Dict) -> List[Dict]:
        """
        Aggregate rule failures across all invoices.
        Returns rules sorted by failure_count descending.
        """
        # {rule_code → [invoice_number, ...]}
        failures: Dict[str, List[str]] = defaultdict(list)

        for v in validations.values():
            inv_num = getattr(v.invoice, "invoice_number", None) or str(v.invoice_id)
            for rule in RULE_REGISTRY:
                if _rule_failed(rule, v):
                    failures[rule["code"]].append(inv_num)

        n = len(validations)
        result = []
        for code, inv_numbers in sorted(failures.items(), key=lambda x: len(x[1]), reverse=True):
            rule = _RULE_BY_CODE[code]
            result.append({
                "rule_code":      code,
                "title_ar":       rule["title_ar"],
                "title_en":       rule["title_en"],
                "category":       rule["category"],
                "severity":       rule["severity"],
                "weight":         rule["weight"],
                "failure_count":  len(inv_numbers),
                "failure_rate":   round(len(inv_numbers) / n * 100, 1) if n else 0.0,
                "invoice_numbers": inv_numbers[:10],   # representative sample
            })
        return result

    # ── Section: supplier_analysis ────────────────────────────────────────────

    def _build_supplier_analysis(
        self, invoices: List, vendor_profiles: Dict
    ) -> List[Dict]:
        if not invoices:
            return []

        # Aggregate per vendor in one pass
        agg: Dict[str, Dict] = defaultdict(lambda: {
            "invoice_count": 0, "total_amount": 0.0,
            "flagged_count": 0, "duplicate_count": 0,
        })
        total_spend = sum(float(inv.total_amount or 0) for inv in invoices)

        for inv in invoices:
            name = inv.vendor_name or "Unknown"
            d = agg[name]
            d["invoice_count"]  += 1
            d["total_amount"]   += float(inv.total_amount or 0)
            if inv.status == "flagged":
                d["flagged_count"] += 1
            if inv.is_duplicate:
                d["duplicate_count"] += 1

        result = []
        for name, d in sorted(agg.items(), key=lambda x: x[1]["total_amount"], reverse=True):
            vp  = vendor_profiles.get(name)
            avg = d["total_amount"] / d["invoice_count"] if d["invoice_count"] else 0.0
            result.append({
                "supplier_name":       name,
                "invoice_count":       d["invoice_count"],
                "total_spend":         round(d["total_amount"], 2),
                "average_invoice":     round(avg, 2),
                "spend_share_percent": round(d["total_amount"] / total_spend * 100, 1) if total_spend else 0.0,
                "flagged_count":       d["flagged_count"],
                "duplicate_count":     d["duplicate_count"],
                "risk_tier":           vp.risk_tier if vp else "unknown",
                "is_new_vendor":       vp.is_new if vp else False,
                "is_suspicious":       vp.is_suspicious if vp else False,
            })
        return result

    # ── Section: risk_analysis ────────────────────────────────────────────────

    def _build_risk_analysis(self, invoices: List, validations: Dict) -> Dict:
        safe_ct = review_ct = high_risk_ct = 0
        total   = len(invoices)

        for inv in invoices:
            v     = validations.get(inv.id)
            score = v.validation_score if v else 0.0
            tier  = classify_risk(score or 0)
            if tier == "safe":
                safe_ct += 1
            elif tier == "review":
                review_ct += 1
            else:
                high_risk_ct += 1

        risk_scores = [float(inv.risk_score or 0) for inv in invoices if inv.risk_score is not None]
        avg_risk    = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

        return {
            "safe_count":        safe_ct,
            "review_count":      review_ct,
            "high_risk_count":   high_risk_ct,
            "safe_pct":          round(safe_ct      / total * 100, 1) if total else 0.0,
            "review_pct":        round(review_ct    / total * 100, 1) if total else 0.0,
            "high_risk_pct":     round(high_risk_ct / total * 100, 1) if total else 0.0,
            "average_risk_score": round(avg_risk, 1),
            "thresholds": RISK_THRESHOLDS,
        }

    # ── Section: anomalies ────────────────────────────────────────────────────

    def _build_anomalies(self, invoices: List, validations: Dict) -> Dict:
        # Duplicate invoices list
        dup_invoices = [
            {
                "id":             str(inv.id),
                "invoice_number": inv.invoice_number or "—",
                "supplier":       inv.vendor_name or "—",
                "amount":         float(inv.total_amount or 0),
                "currency":       inv.currency or "SAR",
            }
            for inv in invoices if inv.is_duplicate
        ]

        # Dominant supplier detection (> 40% spend share)
        total_amount = sum(float(inv.total_amount or 0) for inv in invoices)
        supplier_spend: Dict[str, float] = defaultdict(float)
        for inv in invoices:
            supplier_spend[inv.vendor_name or "Unknown"] += float(inv.total_amount or 0)

        dominant = None
        if total_amount and supplier_spend:
            top_name, top_amt = max(supplier_spend.items(), key=lambda x: x[1])
            pct = top_amt / total_amount * 100
            if pct > 40:
                dominant = {
                    "supplier_name":        top_name,
                    "spend_share_percent":  round(pct, 1),
                    "total_spend":          round(top_amt, 2),
                }

        # Anomaly patterns from InvoiceValidationResult
        anomaly_rules = [r for r in RULE_REGISTRY if r["category"] == "anomaly"]
        abnormal_patterns = []
        for rule in anomaly_rules:
            count = sum(
                1 for v in validations.values()
                if getattr(v, rule["field"], False)  # anomaly = True means flagged
            )
            if count:
                abnormal_patterns.append({
                    "pattern_code":  rule["code"],
                    "title_ar":      rule["title_ar"],
                    "title_en":      rule["title_en"],
                    "severity":      rule["severity"],
                    "affected_count": count,
                })
        abnormal_patterns.sort(key=lambda x: x["affected_count"], reverse=True)

        # ── Benford's Law analysis on invoice amounts ─────────────────────────
        # Requires ≥ 30 samples for a statistically meaningful chi-square test.
        benford_result: Dict = {}
        amounts = [float(inv.total_amount) for inv in invoices
                   if inv.total_amount and float(inv.total_amount) > 0]
        if len(amounts) >= 30:
            try:
                from core.services.ai_service import benford_analysis
                benford_result = benford_analysis(amounts)
            except Exception as exc:
                logger.warning("Benford analysis skipped: %s", exc)

        return {
            "duplicate_invoices":  dup_invoices,
            "dominant_supplier":   dominant,
            "abnormal_patterns":   abnormal_patterns,
            "benford_analysis":    benford_result,
        }

    # ── Section: root_cause_analysis ─────────────────────────────────────────

    def _build_root_cause_analysis(self, validations: Dict) -> Dict:
        """
        ISA 315 root-cause analysis — maps each failed rule category to its
        underlying control weakness.

        Returns:
            {
              "findings": [{"category", "failure_count", "root_cause_ar",
                            "root_cause_en", "isa_reference", "severity"}],
              "dominant_risk_areas": [str],
            }
        """
        # ISA 315 root-cause taxonomy (one cause per rule category)
        _CAUSE: Dict[str, Dict[str, str]] = {
            "header":    {
                "ar": "ضعف إجراءات التوثيق وضبط الجودة عند إعداد الفاتورة (إدخال يدوي غير خاضع للرقابة)",
                "en": "Weak documentation and quality-control procedures at invoice preparation (uncontrolled manual entry)",
            },
            "duplicate": {
                "ar": "غياب ضوابط كشف التكرار وآليات المراجعة الثنائية قبل صرف المدفوعات",
                "en": "Absence of duplicate-detection controls and dual-review mechanisms prior to payment",
            },
            "vat": {
                "ar": "قصور في تطبيق متطلبات الامتثال الضريبي وفق لوائح ZATCA / ضريبة القيمة المضافة",
                "en": "Insufficient application of ZATCA / VAT tax-compliance requirements",
            },
            "anomaly": {
                "ar": "انعدام الرقابة التحليلية الدورية وقواعد الكشف المبكر عن الأنماط غير الطبيعية",
                "en": "Lack of periodic analytical review controls and early-anomaly-detection rules",
            },
            "control": {
                "ar": "ضعف ضوابط الرقابة الداخلية وإجراءات التفويض والموافقة الرسمية",
                "en": "Weak internal controls, delegation-of-authority, and formal approval procedures",
            },
            "document": {
                "ar": "إجراءات غير كافية لضمان سلامة واكتمال الوثائق ومنع التلاعب",
                "en": "Inadequate procedures for document integrity, completeness, and anti-tampering",
            },
        }

        category_failures: Dict[str, int] = defaultdict(int)
        for v in validations.values():
            for rule in RULE_REGISTRY:
                if _rule_failed(rule, v):
                    category_failures[rule["category"]] += 1

        findings: List[Dict] = []
        for cat, count in sorted(category_failures.items(), key=lambda x: x[1], reverse=True):
            if count == 0:
                continue
            cause = _CAUSE.get(cat, {"ar": "غير محدد", "en": "Undetermined"})
            findings.append({
                "category":      cat,
                "failure_count": count,
                "root_cause_ar": cause["ar"],
                "root_cause_en": cause["en"],
                "isa_reference": "ISA 315 — تحديد وتقييم مخاطر التحريف الجوهري",
                "severity":      "critical" if count > 10 else "high" if count > 3 else "medium",
            })

        return {
            "findings":            findings,
            "dominant_risk_areas": [f["category"] for f in findings[:3]],
        }

    # ── Section: actions_and_recommendations ─────────────────────────────────

    def _build_recommendations(self, summary: Dict, validations: Dict) -> Dict:
        immediate = []
        future    = []
        score     = summary["compliance_score"]

        if summary["duplicate_count"]:
            immediate.append({
                "priority":  "critical",
                "code":      "REC-DUP",
                "action_ar": "مراجعة الفواتير المكررة وإيقاف الصرف على المخالف فوراً",
                "action_en": "Review duplicate invoices and halt payment on violating ones immediately",
            })
        if score < 60:
            immediate.append({
                "priority":  "critical",
                "code":      "REC-LOW-COMPLIANCE",
                "action_ar": f"معدل الامتثال {score:.1f}% — مراجعة عاجلة لإجراءات التحقق مطلوبة",
                "action_en": f"Compliance {score:.1f}% — urgent review of verification procedures required",
            })
        if summary["high_risk_count"]:
            immediate.append({
                "priority":  "high",
                "code":      "REC-HIGH-RISK",
                "action_ar": f"مراجعة {summary['high_risk_count']} فاتورة عالية المخاطر قبل الصرف",
                "action_en": f"Review {summary['high_risk_count']} high-risk invoice(s) before payment",
            })

        # Top 3 failed rules → future improvements
        failed_rules = self._build_failed_rules(validations)
        for rule in failed_rules[:3]:
            future.append({
                "priority":  "medium",
                "code":      f"REC-RULE-{rule['rule_code']}",
                "action_ar": f"معالجة {rule['failure_count']} حالة إخفاق في: {rule['title_ar']} (معدل فشل {rule['failure_rate']}%)",
                "action_en": f"Address {rule['failure_count']} failure(s) in: {rule['title_en']} ({rule['failure_rate']}% failure rate)",
            })

        if summary["not_validated_count"]:
            future.append({
                "priority":  "medium",
                "code":      "REC-NOT-VALIDATED",
                "action_ar": f"تشغيل التحقق على {summary['not_validated_count']} فاتورة لم تُدقَّق",
                "action_en": f"Run validation on {summary['not_validated_count']} unvalidated invoice(s)",
            })

        return {
            "immediate_actions":  immediate,
            "future_improvements": future,
        }
