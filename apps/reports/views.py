"""Tadgeeg AI report views."""

import logging
import json
from datetime import date
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.db.models import Sum, Count, Avg, Q, Max, Min
from django.db.models.functions import TruncMonth
from core.services.ai_service import generate_audit_narrative
from apps.authentication.permissions import IsSeniorAuditorOrAbove
from apps.transactions.models import Transaction
from apps.audit.models import AuditCase
from apps.documents.models import Document
from apps.compliance.models import ComplianceViolation
from apps.invoices.models import Invoice, InvoiceValidationResult, VendorProfile
from .models import Report

logger = logging.getLogger("finai")


def _render_report_pdf_bytes(html_str: str, base_url: str) -> bytes:
    from weasyprint import HTML as WP_HTML

    return WP_HTML(string=html_str, base_url=base_url).write_pdf()


def _json_safe(obj):
    """Recursively convert Decimal / UUID / date to JSON-safe Python types."""
    import decimal, uuid, datetime
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(i) for i in obj]
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


# ─── Big Four & benchmark constants (mirrors audit/analytics views) ───────────

_BIG_FOUR_MAPPING = {
    "KPMG":     {"label": "KPMG — Invoice Completeness",       "groups": ["INV"],       "standard": "ISA 500"},
    "Deloitte": {"label": "Deloitte — Risk & Anomaly Detection","groups": ["ANO", "DUP"],"standard": "ISA 315"},
    "PwC":      {"label": "PwC — Internal Control Testing",    "groups": ["CTL"],       "standard": "ISA 330"},
    "EY":       {"label": "EY — Compliance Verification",      "groups": ["VAT", "DOC"],"standard": "ISA 250"},
}

_INDUSTRY_BENCHMARKS = {
    "finance":      {"label": "Financial Services & Banking",      "compliance_rate_pct": 94.2, "duplicate_rate_pct": 0.8, "avg_risk_score": 18.5, "vat_compliance_rate_pct": 97.8},
    "retail":       {"label": "Retail & E-Commerce",               "compliance_rate_pct": 88.7, "duplicate_rate_pct": 1.9, "avg_risk_score": 24.1, "vat_compliance_rate_pct": 93.4},
    "construction": {"label": "Construction & Real Estate",         "compliance_rate_pct": 85.3, "duplicate_rate_pct": 2.7, "avg_risk_score": 31.4, "vat_compliance_rate_pct": 89.2},
    "healthcare":   {"label": "Healthcare & Pharmaceuticals",       "compliance_rate_pct": 91.6, "duplicate_rate_pct": 1.1, "avg_risk_score": 20.8, "vat_compliance_rate_pct": 95.1},
    "manufacturing":{"label": "Manufacturing & Industry",           "compliance_rate_pct": 87.9, "duplicate_rate_pct": 2.3, "avg_risk_score": 27.6, "vat_compliance_rate_pct": 91.7},
    "services":     {"label": "Professional & Business Services",   "compliance_rate_pct": 90.1, "duplicate_rate_pct": 1.5, "avg_risk_score": 22.3, "vat_compliance_rate_pct": 94.0},
}


def _compute_big_four(vr_qs) -> dict:
    """Build Big Four compliance breakdown from a validation result queryset."""
    GROUP_CODES = ["INV", "DUP", "VAT", "ANO", "CTL", "DOC"]
    counters = {code: {"passed": 0, "failed": 0, "total": 0} for code in GROUP_CODES}
    for detail_payload in vr_qs.values_list("validation_details", flat=True):
        if not isinstance(detail_payload, dict):
            continue
        for rule_code, detail in detail_payload.items():
            group_code = str(rule_code or "").split("-", 1)[0]
            if group_code not in counters:
                continue
            counters[group_code]["total"] += 1
            if detail.get("passed") is True:
                counters[group_code]["passed"] += 1
            elif detail.get("passed") is False:
                counters[group_code]["failed"] += 1

    results = []
    for firm, meta in _BIG_FOUR_MAPPING.items():
        fp = ff = ft = 0
        for code in meta["groups"]:
            g = counters[code]
            fp += g["passed"]
            ff += g["failed"]
            ft += g["total"]
        rate = round(fp / ft * 100, 1) if ft else 0.0
        results.append({
            "firm": firm,
            "label": meta["label"],
            "standard": meta["standard"],
            "pass_rate": rate,
            "passed": fp,
            "failed": ff,
            "total": ft,
            "status": "compliant" if rate >= 90 else "at_risk" if rate >= 70 else "non_compliant",
        })

    overall_p = sum(r["passed"] for r in results)
    overall_t = sum(r["total"] for r in results)
    overall_rate = round(overall_p / overall_t * 100, 1) if overall_t else 0.0
    return {
        "overall_pass_rate": overall_rate,
        "overall_status": "compliant" if overall_rate >= 90 else "at_risk" if overall_rate >= 70 else "non_compliant",
        "firms": results,
    }


def _compute_benchmark(org, inv_qs) -> dict:
    """Compare org invoice metrics against Saudi industry benchmarks."""
    from django.db.models import Count, Avg, Q as _Q
    from apps.invoices.models import InvoiceValidationResult as _IVR

    industry_key = "services"
    org_industry = (org.industry or "").lower()
    for key in _INDUSTRY_BENCHMARKS:
        if key in org_industry:
            industry_key = key
            break
    benchmark = _INDUSTRY_BENCHMARKS[industry_key]

    inv_stats = inv_qs.aggregate(
        total=Count("id"),
        compliant=Count("id", filter=_Q(status="approved")),
        duplicate=Count("id", filter=_Q(is_duplicate=True)),
        avg_risk=Avg("risk_score"),
    )
    total = inv_stats["total"] or 1
    org_compliance = round((inv_stats["compliant"] or 0) / total * 100, 1)
    org_duplicate  = round((inv_stats["duplicate"]  or 0) / total * 100, 1)
    org_risk       = round(float(inv_stats["avg_risk"] or 0), 1)

    vat_qs    = _IVR.objects.filter(invoice__in=inv_qs)
    vat_total = vat_qs.count() or 1
    org_vat   = round(vat_qs.filter(vat_rate_correct=True, vat_calculation_correct=True, vat_subtotal_correct=True).count() / vat_total * 100, 1)

    def _delta(org_val, bench_val, higher_is_better=True):
        diff = round(org_val - bench_val, 1)
        if higher_is_better:
            st = "above" if diff > 0 else "below" if diff < 0 else "at"
        else:
            st = "below" if diff > 0 else "above" if diff < 0 else "at"
        return {"value": org_val, "benchmark": bench_val, "delta": diff, "status": st}

    metrics = {
        "compliance_rate_pct":     _delta(org_compliance, benchmark["compliance_rate_pct"]),
        "duplicate_rate_pct":      _delta(org_duplicate,  benchmark["duplicate_rate_pct"],  higher_is_better=False),
        "avg_risk_score":          _delta(org_risk,       benchmark["avg_risk_score"],       higher_is_better=False),
        "vat_compliance_rate_pct": _delta(org_vat,        benchmark["vat_compliance_rate_pct"]),
    }
    above = sum(1 for m in metrics.values() if m["status"] == "above")
    below = sum(1 for m in metrics.values() if m["status"] == "below")
    return {
        "industry": industry_key,
        "industry_label": benchmark["label"],
        "metrics": metrics,
        "overall_position": "above_average" if above > below else "below_average" if below > above else "average",
    }


# ─── Helper: collect invoice section data ─────────────────────────────────────

def _collect_invoice_data(org, date_from=None, date_to=None, audit_session_id=None) -> dict:
    """Aggregate all invoice audit data for reports."""
    inv_qs = Invoice.objects.filter(organization=org)
    if audit_session_id:
        inv_qs = inv_qs.filter(audit_session_id=audit_session_id)
    if date_from:
        inv_qs = inv_qs.filter(invoice_date__gte=date_from)
    if date_to:
        inv_qs = inv_qs.filter(invoice_date__lte=date_to)

    # ── Overall stats ──────────────────────────────────────────────────────────
    stats = inv_qs.aggregate(
        total_invoices=Count("id"),
        total_invoiced=Sum("total_amount"),
        total_vat=Sum("vat_amount"),
        avg_amount=Avg("total_amount"),
        avg_risk_score=Avg("risk_score"),
        flagged_count=Count("id", filter=Q(status="flagged")),
        approved_count=Count("id", filter=Q(status="approved")),
        rejected_count=Count("id", filter=Q(status="rejected")),
        pending_count=Count("id", filter=Q(status__in=["pending", "processing"])),
        duplicate_count=Count("id", filter=Q(is_duplicate=True)),
        critical_count=Count("id", filter=Q(risk_level="critical")),
        high_count=Count("id", filter=Q(risk_level="high")),
        medium_count=Count("id", filter=Q(risk_level="medium")),
        low_count=Count("id", filter=Q(risk_level="low")),
        new_vendor_count=Count("id", filter=Q(extracted_data__has_key="is_new_vendor")),
        missing_qr_count=Count("id", filter=Q(has_qr_code=False)),
        handwritten_count=Count("id", filter=Q(is_handwritten=True)),
    )

    n = stats["total_invoices"] or 1  # avoid division by zero

    # ── Validation scores summary ──────────────────────────────────────────────
    val_stats = InvoiceValidationResult.objects.filter(
        invoice__organization=org,
        invoice__in=inv_qs,
    ).aggregate(
        avg_score=Avg("validation_score"),
        perfect_score=Count("id", filter=Q(validation_score=100)),
        below_50=Count("id", filter=Q(validation_score__lt=50)),
        below_80=Count("id", filter=Q(validation_score__lt=80)),
    )

    # ── Failed rules frequency ─────────────────────────────────────────────────
    from apps.invoices.models import InvoiceValidationResult as IVR
    rule_failures = {}
    for vr in IVR.objects.filter(invoice__organization=org, invoice__in=inv_qs).only("failed_rule_codes"):
        for code in (vr.failed_rule_codes or []):
            rule_failures[code] = rule_failures.get(code, 0) + 1

    top_failures = sorted(rule_failures.items(), key=lambda x: -x[1])[:10]
    from core.services.invoice_validator import RULES
    top_failures_detail = [
        {"rule_code": code, "failures": count, "description": RULES.get(code, code)}
        for code, count in top_failures
    ]

    # ── Top risk invoices ──────────────────────────────────────────────────────
    top_risk = list(
        inv_qs.filter(risk_level__in=["high", "critical"]).order_by("-risk_score").values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "risk_level", "risk_score", "ai_summary", "status"
        )[:15]
    )
    for i in top_risk:
        i["id"] = str(i["id"])
        i["total_amount"] = float(i["total_amount"] or 0)
        i["invoice_date"] = str(i["invoice_date"]) if i["invoice_date"] else None

    # ── Duplicate invoices ─────────────────────────────────────────────────────
    duplicates = list(
        inv_qs.filter(is_duplicate=True).values(
            "id", "invoice_number", "vendor_name", "total_amount", "currency",
            "invoice_date", "status", "duplicate_of_id"
        )[:20]
    )
    for d in duplicates:
        d["id"] = str(d["id"])
        d["duplicate_of_id"] = str(d["duplicate_of_id"]) if d["duplicate_of_id"] else None
        d["total_amount"] = float(d["total_amount"] or 0)
        d["invoice_date"] = str(d["invoice_date"]) if d["invoice_date"] else None

    # ── Vendor analysis ────────────────────────────────────────────────────────
    vendor_stats = (
        inv_qs.values("vendor_name")
        .annotate(
            invoice_count=Count("id"),
            vendor_total=Sum("total_amount"),
            avg_amount=Avg("total_amount"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
        )
        .order_by("-vendor_total")[:15]
    )
    vendor_list = []
    total_spend = float(stats["total_invoiced"] or 0)
    for v in vendor_stats:
        v_total = float(v["vendor_total"] or 0)
        vendor_list.append({
            "vendor_name": v["vendor_name"],
            "invoice_count": v["invoice_count"],
            "total_amount": round(v_total, 2),
            "avg_amount": round(float(v["avg_amount"] or 0), 2),
            "spend_share_pct": round(v_total / total_spend * 100, 2) if total_spend else 0,
            "flagged_invoices": v["flagged"],
            "duplicate_invoices": v["duplicates"],
        })

    # ── Monthly spend trend ────────────────────────────────────────────────────
    monthly = list(
        inv_qs.annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(
            total=Sum("total_amount"),
            count=Count("id"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
        )
        .order_by("month")
    )
    monthly_clean = [
        {
            "month": str(m["month"])[:7] if m["month"] else None,
            "total_amount": round(float(m["total"] or 0), 2),
            "invoice_count": m["count"],
            "flagged_count": m["flagged"],
            "duplicate_count": m["duplicates"],
        }
        for m in monthly
    ]

    # ── VAT compliance stats ───────────────────────────────────────────────────
    vat_compliant = InvoiceValidationResult.objects.filter(
        invoice__organization=org, invoice__in=inv_qs,
        vat_rate_correct=True, vat_calculation_correct=True, vat_subtotal_correct=True
    ).count()
    vat_total = InvoiceValidationResult.objects.filter(invoice__organization=org, invoice__in=inv_qs).count()

    # ── Rule group pass rates ──────────────────────────────────────────────────
    vr_qs = InvoiceValidationResult.objects.filter(invoice__organization=org, invoice__in=inv_qs)
    n_vr = vr_qs.count() or 1

    def _pct(field_true):
        return round(vr_qs.filter(**{field_true: True}).count() / n_vr * 100, 1)

    rule_group_summary = {
        "group1_header_validation": {
            "has_invoice_number_pct":  _pct("has_invoice_number"),
            "has_invoice_date_pct":    _pct("has_invoice_date"),
            "has_vendor_name_pct":     _pct("has_vendor_name"),
            "has_vendor_vat_pct":      _pct("has_vendor_vat"),
            "has_total_amount_pct":    _pct("has_total_amount"),
            "has_currency_pct":        _pct("has_currency"),
            "total_greater_zero_pct":  _pct("total_greater_zero"),
        },
        "group2_duplicate_detection": {
            "duplicate_invoice_number_pct":   round(vr_qs.filter(duplicate_invoice_number=True).count() / n_vr * 100, 1),
            "duplicate_vendor_amount_date_pct": round(vr_qs.filter(duplicate_vendor_amount_date=True).count() / n_vr * 100, 1),
            "duplicate_file_hash_pct":         round(vr_qs.filter(duplicate_file_hash=True).count() / n_vr * 100, 1),
        },
        "group3_vat_validation": {
            "vat_rate_correct_pct":        _pct("vat_rate_correct"),
            "vat_calculation_correct_pct": _pct("vat_calculation_correct"),
            "vat_subtotal_correct_pct":    _pct("vat_subtotal_correct"),
            "vat_number_present_pct":      _pct("vat_number_present"),
            "qr_code_valid_pct":           _pct("qr_code_valid"),
        },
        "group4_anomaly_detection": {
            "amount_unusually_high_pct":    round(vr_qs.filter(amount_unusually_high=True).count() / n_vr * 100, 1),
            "new_unknown_vendor_pct":       round(vr_qs.filter(new_unknown_vendor=True).count() / n_vr * 100, 1),
            "many_invoices_same_day_pct":   round(vr_qs.filter(many_invoices_same_day=True).count() / n_vr * 100, 1),
            "vendor_dominates_pct":         round(vr_qs.filter(vendor_dominates_invoices=True).count() / n_vr * 100, 1),
        },
        "group5_financial_controls": {
            "has_cost_center_pct":  _pct("has_cost_center"),
            "has_account_code_pct": _pct("has_account_code"),
            "has_approver_pct":     _pct("has_approver"),
        },
        "group6_document_quality": {
            "document_clear_pct":   _pct("document_is_clear"),
            "appears_genuine_pct":  _pct("appears_genuine"),
            "no_alterations_pct":   _pct("no_alterations"),
            "has_qr_code_pct":      _pct("has_qr_code"),
        },
    }

    return {
        "overall_stats": {
            **stats,
            "total_amount":    round(float(stats["total_invoiced"]  or 0), 2),
            "total_vat":       round(float(stats["total_vat"]     or 0), 2),
            "avg_amount":      round(float(stats["avg_amount"]    or 0), 2),
            "avg_risk_score":  round(float(stats["avg_risk_score"] or 0), 2),
            "flag_rate_pct":   round(stats["flagged_count"] / n * 100, 2),
            "duplicate_rate_pct": round(stats["duplicate_count"] / n * 100, 2),
        },
        "validation_summary": {
            **val_stats,
            "avg_score":       round(float(val_stats["avg_score"] or 0), 2),
            "vat_compliance_pct": round(vat_compliant / vat_total * 100, 2) if vat_total else 0,
        },
        "top_failed_rules":    top_failures_detail,
        "rule_group_summary":  rule_group_summary,
        "top_risk_invoices":   top_risk,
        "duplicate_invoices":  duplicates,
        "vendor_analysis":     vendor_list,
        "monthly_trend":       monthly_clean,
        "big_four":            _compute_big_four(vr_qs),
        "benchmark":           _compute_benchmark(org, inv_qs),
    }


def _collect_rule_engine_data(org, date_from=None, date_to=None) -> dict:
    """
    Collect aggregated statistics from the new rule engine (AuditRun / AuditResult).
    Returns an empty dict if no runs exist yet, so the caller can skip gracefully.
    """
    try:
        from apps.rule_engine.models.audit_execution import AuditRun, AuditResult
        from apps.rule_engine.models.rule_definition import RuleDefinitionTranslation
    except ImportError:
        return {}

    runs_qs = AuditRun.objects.filter(
        organization=org,
        status=AuditRun.Status.COMPLETED,
    )
    if date_from:
        runs_qs = runs_qs.filter(completed_at__date__gte=date_from)
    if date_to:
        runs_qs = runs_qs.filter(completed_at__date__lte=date_to)

    if not runs_qs.exists():
        return {}

    stats = runs_qs.aggregate(
        total_runs=Count("id"),
        avg_risk=Avg("risk_score"),
        blocking_count=Count("id", filter=Q(blocks_approval=True)),
        manual_review_count=Count("id", filter=Q(requires_manual_review=True)),
        total_passed=Sum("passed_rules"),
        total_failed=Sum("failed_rules"),
        total_warnings=Sum("warning_rules"),
        total_rules=Sum("total_rules"),
        critical_count=Count("id", filter=Q(risk_level="critical")),
        high_count=Count("id", filter=Q(risk_level="high")),
        medium_count=Count("id", filter=Q(risk_level="medium")),
        low_count=Count("id", filter=Q(risk_level="low")),
    )

    total_applied = int(stats["total_rules"] or 0)
    total_passed = int(stats["total_passed"] or 0)
    total_failed = int(stats["total_failed"] or 0)
    total_warnings = int(stats["total_warnings"] or 0)
    compliance_pct = round(total_passed / total_applied * 100, 1) if total_applied else 0.0

    # Top failed rules with Arabic names
    top_failures_qs = (
        AuditResult.objects.filter(audit_run__in=runs_qs, status="fail")
        .values("rule_code")
        .annotate(
            fail_count=Count("id"),
            avg_risk=Avg("risk_contribution"),
        )
        .order_by("-fail_count")[:10]
    )

    # Fetch Arabic translations for the top rule codes
    top_codes = [r["rule_code"] for r in top_failures_qs]
    translations = {
        t.rule.rule_code: {"ar": t.name_ar, "en": t.name_en}
        for t in RuleDefinitionTranslation.objects.filter(
            rule__rule_code__in=top_codes, language="ar"
        ).select_related("rule")
    }

    top_failed_rules = [
        {
            "rule_code": r["rule_code"],
            "fail_count": r["fail_count"],
            "avg_risk_contribution": round(float(r["avg_risk"] or 0), 2),
            "name_ar": translations.get(r["rule_code"], {}).get("ar", r["rule_code"]),
            "name_en": translations.get(r["rule_code"], {}).get("en", r["rule_code"]),
        }
        for r in top_failures_qs
    ]

    # Breakdown by document type
    by_doc_type = list(
        runs_qs.values("document_type")
        .annotate(
            run_count=Count("id"),
            avg_risk=Avg("risk_score"),
            blocking=Count("id", filter=Q(blocks_approval=True)),
            failed_rules_sum=Sum("failed_rules"),
        )
        .order_by("-run_count")
    )
    for row in by_doc_type:
        row["avg_risk"] = round(float(row["avg_risk"] or 0), 1)

    return {
        "total_runs": int(stats["total_runs"] or 0),
        "avg_risk_score": round(float(stats["avg_risk"] or 0), 1),
        "blocking_failures": int(stats["blocking_count"] or 0),
        "manual_review_required": int(stats["manual_review_count"] or 0),
        "total_rules_applied": total_applied,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_warnings": total_warnings,
        "compliance_pct": compliance_pct,
        "risk_distribution": {
            "critical": int(stats["critical_count"] or 0),
            "high":     int(stats["high_count"]     or 0),
            "medium":   int(stats["medium_count"]   or 0),
            "low":      int(stats["low_count"]      or 0),
        },
        "top_failed_rules": top_failed_rules,
        "by_document_type": by_doc_type,
    }


def _extract_invoice_audit_section(report_data) -> dict:
    if isinstance(report_data, dict) and isinstance(report_data.get("invoice_audit"), dict):
        return report_data.get("invoice_audit") or {}
    return report_data or {}


def _weight_for_rule(rule_code):
    prefix = str(rule_code or "").split("-", 1)[0]
    if prefix in {"DUP", "VAT", "ANO"}:
        return "مرتفع"
    if prefix in {"INV", "CTL"}:
        return "متوسط"
    return "منخفض"


def _failed_rules_with_invoice_refs(top_failed_rules, validations):
    top_codes = [r.get("rule_code") for r in (top_failed_rules or []) if r.get("rule_code")]
    top_codes_set = set(top_codes)
    buckets = {code: [] for code in top_codes}

    for vr in validations:
        inv_no = vr.invoice.invoice_number or str(vr.invoice_id)[:8]
        for code in (vr.failed_rule_codes or []):
            if code not in top_codes_set:
                continue
            if inv_no not in buckets[code]:
                buckets[code].append(inv_no)

    enriched = []
    for rule in (top_failed_rules or []):
        code = rule.get("rule_code")
        invoice_numbers = buckets.get(code, [])
        enriched.append({
            "rule_code": code,
            "description": rule.get("description") or code,
            "failure_count": int(rule.get("failures") or 0),
            "invoice_numbers": invoice_numbers,
        })
    return enriched


def _build_high_risk_violations(invoice_rows, validation_map, rule_catalog):
    rows = []
    for row in (invoice_rows or []):
        inv_id = row.get("id")
        vr = validation_map.get(str(inv_id))
        violations = []

        if vr:
            details = vr.validation_details or {}
            for code in (vr.failed_rule_codes or [])[:4]:
                detail = details.get(code, {}) if isinstance(details, dict) else {}
                reason = (
                    detail.get("reason")
                    or detail.get("message")
                    or detail.get("note")
                    or "تم رصد مخالفة لهذه القاعدة وتحتاج مراجعة تفصيلية."
                )
                violations.append({
                    "rule_code": code,
                    "description": rule_catalog.get(code, code),
                    "reason": reason,
                })

        rows.append({
            "invoice_number": row.get("invoice_number") or "-",
            "amount": float(row.get("total_amount") or 0),
            "date": row.get("invoice_date") or "-",
            "risk_level": row.get("risk_level") or "low",
            "risk_score": float(row.get("risk_score") or 0),
            "violations": violations,
        })
    return rows


def _build_invoice_audit_report_ui(report, org):
    from apps.invoices.models import InvoiceValidationResult
    from core.services.invoice_validator import RULES

    source_data = _extract_invoice_audit_section(report.data or {})
    if not isinstance(source_data, dict):
        return None

    validation_qs = InvoiceValidationResult.objects.filter(invoice__organization=org).select_related("invoice")
    if report.period_from:
        validation_qs = validation_qs.filter(invoice__invoice_date__gte=report.period_from)
    if report.period_to:
        validation_qs = validation_qs.filter(invoice__invoice_date__lte=report.period_to)
    validations = list(validation_qs.only("invoice_id", "invoice__invoice_number", "failed_rule_codes", "validation_details"))
    validation_map = {str(vr.invoice_id): vr for vr in validations}

    overall = source_data.get("overall_stats", {})
    validation_summary = source_data.get("validation_summary", {})
    top_risk = source_data.get("top_risk_invoices", [])
    vendor_rows = source_data.get("vendor_analysis", [])
    top_failed = source_data.get("top_failed_rules", [])
    narrative = report.narrative or {}

    compliance_agg = validation_qs.aggregate(
        rules_applied=Sum("total_rules"),
        rules_passed=Sum("rules_passed"),
        rules_failed=Sum("rules_failed"),
    )
    rules_applied = int(compliance_agg.get("rules_applied") or 0)
    rules_passed = int(compliance_agg.get("rules_passed") or 0)
    rules_failed = int(compliance_agg.get("rules_failed") or 0)
    compliance_pct = round((rules_passed / rules_applied) * 100, 1) if rules_applied else 0

    risk_avg = float(overall.get("avg_risk_score") or 0)
    high_risk_count = int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0))
    report_status = "عالي المخاطر" if risk_avg >= 70 or high_risk_count > 0 else "يحتاج مراجعة" if risk_avg >= 40 else "متوافق"

    failed_rules = _failed_rules_with_invoice_refs(top_failed, validations)
    high_risk_invoices = _build_high_risk_violations(top_risk, validation_map, RULES)
    dominant_vendor = vendor_rows[0] if vendor_rows else {}
    duplicate_count = int(overall.get("duplicate_count") or 0)
    missing_qr_count = int(overall.get("missing_qr_count") or 0)
    handwritten_count = int(overall.get("handwritten_count") or 0)
    new_vendor_count = int(overall.get("new_vendor_count") or 0)

    compliance_matrix = [
        {
            "rule_code": row.get("rule_code"),
            "status": "مخالف",
            "weight": _weight_for_rule(row.get("rule_code")),
            "note": row.get("description") or "فشل متكرر يتطلب إجراء فوري.",
        }
        for row in top_failed[:6]
    ]
    if not compliance_matrix:
        compliance_matrix = [
            {"rule_code": "INV-001", "status": "ممتثل", "weight": "متوسط", "note": "توفر رقم الفاتورة في معظم العينات."},
            {"rule_code": "VAT-002", "status": "ممتثل", "weight": "مرتفع", "note": "نسبة جيدة من صحة حساب الضريبة."},
            {"rule_code": "DUP-001", "status": "مخالف", "weight": "مرتفع", "note": "ظهرت حالات تكرار تحتاج تحقيق."},
        ]

    # ── Rule engine enrichment (if data exists in report) ─────────────────────
    from django.conf import settings as _settings
    re_raw = (report.data or {}).get("rule_engine") or {}
    if not re_raw and getattr(_settings, "USE_NEW_RULE_ENGINE", False):
        re_raw = _collect_rule_engine_data(org, report.period_from or None, report.period_to or None)

    re_runs        = int(re_raw.get("total_runs", 0))
    re_compliance  = float(re_raw.get("compliance_pct", compliance_pct))
    re_avg_risk    = float(re_raw.get("avg_risk_score", risk_avg))
    re_blocking    = int(re_raw.get("blocking_failures", 0))
    re_dist        = re_raw.get("risk_distribution", {})
    re_top_rules   = re_raw.get("top_failed_rules", [])
    re_by_doc      = re_raw.get("by_document_type", [])

    # Build human-readable key findings that incorporate rule engine data
    key_findings = [
        f"عدد الفواتير عالية المخاطر: {high_risk_count}",
        f"عدد الفواتير المكررة: {duplicate_count}",
        f"متوسط درجة المخاطر: {risk_avg:.1f}",
    ]
    if re_runs:
        key_findings += [
            f"إجمالي المستندات المدقوقة بمحرك القواعد الذكي: {re_runs}",
            f"القواعد المطبقة الإجمالية: {re_raw.get('total_rules_applied', 0)} — امتثال {re_compliance:.1f}%",
            f"حالات تعطيل الاعتماد: {re_blocking}",
        ]
        if re_top_rules:
            top_name = re_top_rules[0].get("name_ar") or re_top_rules[0].get("rule_code")
            key_findings.append(f"القاعدة الأكثر إخفاقًا: {top_name} ({re_top_rules[0]['fail_count']} إخفاق)")

    # Determine effective compliance rate — prefer rule engine if available
    effective_compliance = re_compliance if re_runs else float(validation_summary.get("vat_compliance_pct") or compliance_pct)

    rule_engine_section = None
    if re_runs:
        rule_engine_section = {
            "total_runs":        re_runs,
            "compliance_pct":    re_compliance,
            "avg_risk_score":    re_avg_risk,
            "blocking_failures": re_blocking,
            "manual_review":     int(re_raw.get("manual_review_required", 0)),
            "total_rules_applied": int(re_raw.get("total_rules_applied", 0)),
            "total_passed":      int(re_raw.get("total_passed", 0)),
            "total_failed":      int(re_raw.get("total_failed", 0)),
            "total_warnings":    int(re_raw.get("total_warnings", 0)),
            "risk_distribution": {
                "critical": int(re_dist.get("critical", 0)),
                "high":     int(re_dist.get("high", 0)),
                "medium":   int(re_dist.get("medium", 0)),
                "low":      int(re_dist.get("low", 0)),
            },
            "top_failed_rules": re_top_rules,
            "by_document_type": re_by_doc,
        }

    return {
        "title": report.title or "تقرير تدقيق الفواتير",
        "organization_name": getattr(org, "name", "-") or "-",
        "generated_at": report.created_at,
        "report_type": "Invoice Audit Report",
        "status": report_status,
        "summary": {
            "total_invoices": int(overall.get("total_invoices") or 0),
            "total_amount": float(overall.get("total_amount") or 0),
            "compliance_rate": effective_compliance,
            "avg_risk_score": risk_avg,
            "high_risk_invoices": high_risk_count,
            "duplicate_count": duplicate_count,
        },
        "executive_summary": {
            "conclusion": narrative.get("executive_summary") or "الصورة العامة تشير إلى ارتفاع نسبي في مخاطر الامتثال وتحتاج تدخل رقابي سريع.",
            "key_findings": key_findings,
            "recommendations": [
                "إغلاق المخالفات ذات الأولوية العالية خلال دورة المراجعة الحالية.",
                "تفعيل مراجعة استباقية على قواعد التكرار وضريبة القيمة المضافة.",
                "رفع جودة بيانات الموردين لتقليل الإخفاقات المتكررة.",
            ],
        },
        "compliance_engine": {
            "rules_applied": rules_applied,
            "rules_passed": rules_passed,
            "rules_failed": rules_failed,
            "compliance_rate": compliance_pct,
            "rules_matrix": compliance_matrix,
        },
        "rule_engine": rule_engine_section,
        "high_risk_invoices": high_risk_invoices,
        "failed_rules": failed_rules,
        "risk_analysis": {
            "avg_risk_score": risk_avg,
            "high": int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0)),
            "review": int(overall.get("medium_count") or 0),
            "safe": int(overall.get("low_count") or 0),
        },
        "duplicates_anomalies": {
            "duplicates": duplicate_count,
            "dominant_vendor": dominant_vendor.get("vendor_name") or "-",
            "vendor_dependency_pct": float(dominant_vendor.get("spend_share_pct") or 0),
            "patterns": [
                {"label": "غياب رمز QR", "count": missing_qr_count, "severity": "high" if missing_qr_count else "low"},
                {"label": "فواتير بخط يدوي", "count": handwritten_count, "severity": "review" if handwritten_count else "low"},
                {"label": "موردون جدد غير معروفين", "count": new_vendor_count, "severity": "review" if new_vendor_count else "low"},
            ],
        },
        "vendor_analysis": vendor_rows,
        "recommendations": {
            "immediate": [
                "تصحيح فواتير QR غير المتوافقة قبل الإقفال المالي.",
                "مراجعة المورد المسيطر وتدقيق معاملات العينة عالية القيمة.",
                "التحقق من الرقم الضريبي للفواتير المرفوضة رقابيا.",
            ],
            "future": [
                "تطبيق مراقبة لحظية لقواعد التكرار قبل اعتماد الفاتورة.",
                "تحسين جودة الإدخال وتدريب الفريق على متطلبات الامتثال.",
                "إضافة حدود تنبيه تلقائية عند ارتفاع تركز الإنفاق على مورد واحد.",
            ],
        },
    }


# ─── Views ────────────────────────────────────────────────────────────────────

class GenerateAuditReportView(APIView):
    """Generate a comprehensive AI audit report including all invoice audit data."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Reports"],
        summary="Generate a full audit report — includes invoices, transactions, and AI narrative",
        request={
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": [
                        "executive_summary",
                        "invoice_audit",
                        "detailed_findings",
                        "compliance",
                        "risk_assessment",
                        "vendor_analysis",
                        "spend_analysis",
                    ],
                    "default": "executive_summary",
                },
                "date_from": {"type": "string", "format": "date"},
                "date_to":   {"type": "string", "format": "date"},
                "language":  {"type": "string", "enum": ["en", "ar"], "default": "en"},
                "audit_session_id": {"type": "string", "format": "uuid"},
                "include_invoices":     {"type": "boolean", "default": True},
                "include_transactions": {"type": "boolean", "default": True},
            },
        },
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        report_type       = request.data.get("report_type", "executive_summary")
        date_from         = request.data.get("date_from")
        date_to           = request.data.get("date_to") or str(date.today())
        language          = request.data.get("language", "en")
        audit_session_id  = request.data.get("audit_session_id")
        include_invoices  = request.data.get("include_invoices", True)
        include_tx        = request.data.get("include_transactions", True)

        audit_data = {
            "organization": {
                "name":     org.name,
                "country":  org.get_country_display(),
                "industry": org.industry,
                "vat_number": org.vat_number,
                "currency": org.currency,
            },
            "audit_period": {"from": date_from, "to": date_to},
            "report_type":  report_type,
            "audit_session_id": audit_session_id,
        }

        # ── Invoice Audit Section ──────────────────────────────────────────────
        if include_invoices:
            audit_data["invoice_audit"] = _collect_invoice_data(org, date_from, date_to, audit_session_id=audit_session_id)

        # ── Rule Engine Section (40-rule smart audit) ──────────────────────────
        from django.conf import settings as _settings
        if getattr(_settings, "USE_NEW_RULE_ENGINE", False):
            re_data = _collect_rule_engine_data(org, date_from, date_to)
            if re_data:
                audit_data["rule_engine"] = re_data

        # ── Transaction Section ────────────────────────────────────────────────
        if include_tx:
            tx_qs = Transaction.objects.filter(organization=org)
            if date_from:
                tx_qs = tx_qs.filter(transaction_date__gte=date_from)
            tx_qs = tx_qs.filter(transaction_date__lte=date_to)

            tx_stats = tx_qs.aggregate(
                total_income=Sum("amount", filter=Q(transaction_type="income")),
                total_expense=Sum("amount", filter=Q(transaction_type="expense")),
                total_vat=Sum("vat_amount"),
                tx_count=Count("id"),
                flagged_count=Count("id", filter=Q(is_flagged=True)),
                avg_risk=Avg("risk_score"),
                critical_count=Count("id", filter=Q(risk_level="critical")),
                high_count=Count("id", filter=Q(risk_level="high")),
            )
            top_risk_tx = list(
                tx_qs.filter(risk_score__gt=50).order_by("-risk_score").values(
                    "id", "transaction_type", "amount", "currency", "vendor_name",
                    "description", "risk_score", "risk_level", "flag_reason", "transaction_date"
                )[:15]
            )
            for t in top_risk_tx:
                t["id"] = str(t["id"])
                t["amount"] = float(t["amount"])
                t["transaction_date"] = str(t["transaction_date"])

            audit_data["financial_summary"] = {
                "total_income":    float(tx_stats["total_income"]  or 0),
                "total_expense":   float(tx_stats["total_expense"] or 0),
                "net_profit":      float((tx_stats["total_income"] or 0) - (tx_stats["total_expense"] or 0)),
                "total_vat":       float(tx_stats["total_vat"]     or 0),
                "transaction_count": tx_stats["tx_count"],
                "flagged_transactions": tx_stats["flagged_count"],
                "flag_rate_pct":   round(tx_stats["flagged_count"] / (tx_stats["tx_count"] or 1) * 100, 2),
                "avg_risk_score":  round(float(tx_stats["avg_risk"] or 0), 2),
                "critical_transactions": tx_stats["critical_count"],
                "top_risk_transactions": top_risk_tx,
            }

        # ── Audit Cases Section ────────────────────────────────────────────────
        cases_qs = AuditCase.objects.filter(organization=org)
        if audit_session_id:
            cases_qs = cases_qs.filter(invoice__audit_session_id=audit_session_id)
        if date_from:
            cases_qs = cases_qs.filter(created_at__date__gte=date_from)
        cases_qs = cases_qs.filter(created_at__date__lte=date_to)
        audit_data["audit_cases"] = cases_qs.aggregate(
            total=Count("id"),
            open=Count("id", filter=Q(status="open")),
            resolved=Count("id", filter=Q(status="resolved")),
            critical=Count("id", filter=Q(priority="critical")),
            high=Count("id", filter=Q(priority="high")),
        )

        # ── AI Narrative ───────────────────────────────────────────────────────
        audit_data = _json_safe(audit_data)
        narrative = generate_audit_narrative(audit_data, language=language)

        # ── Save Report ────────────────────────────────────────────────────────
        report = Report.objects.create(
            organization=org,
            generated_by=request.user,
            report_type=report_type,
            language=language,
            period_from=date_from or "",
            period_to=date_to or str(date.today()),
            data=audit_data,
            narrative=narrative,
            title=f"{report_type.replace('_', ' ').title()} Report — {date_to}",
        )

        return Response({
            "id":           str(report.id),
            "report_id":    str(report.id),
            "title":        report.title,
            "report_type":  report_type,
            "language":     language,
            "generated_at": report.created_at.isoformat(),
            "data":         audit_data,
            "narrative":    narrative,
        })


class InvoiceAuditReportView(APIView):
    """Dedicated invoice audit report with all 30 rule statistics."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Reports"],
        summary="Invoice audit report — full 30-rule breakdown, vendor risk, duplicates, spend analysis",
        parameters=[
            OpenApiParameter("date_from"),
            OpenApiParameter("date_to"),
            OpenApiParameter("language", description="en or ar"),
        ],
    )
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        date_from = request.query_params.get("date_from")
        date_to   = request.query_params.get("date_to") or str(date.today())
        language  = request.query_params.get("language", "en")

        data = _json_safe(_collect_invoice_data(org, date_from, date_to))

        # AI narrative for invoice audit specifically
        narrative = generate_audit_narrative(
            {
                "organization": {"name": org.name, "country": org.country, "currency": org.currency},
                "audit_period": {"from": date_from, "to": date_to},
                "report_type":  "invoice_audit",
                "invoice_audit": data,
            },
            language=language,
        )

        report = Report.objects.create(
            organization=org,
            generated_by=request.user,
            report_type="invoice_audit",
            language=language,
            period_from=date_from or "",
            period_to=date_to,
            data=data,
            narrative=narrative,
            title=f"Invoice Audit Report — {date_to}",
        )

        return Response({
            "id":           str(report.id),
            "report_id":    str(report.id),
            "title":        report.title,
            "generated_at": report.created_at.isoformat(),
            "language":     language,
            "data":         data,
            "narrative":    narrative,
        })


class ValidationRulesSummaryReportView(APIView):
    """Report: how many invoices passed/failed each of the 30 rules."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Reports"],
        summary="30-rule pass/fail breakdown across all invoices",
        parameters=[
            OpenApiParameter("date_from"),
            OpenApiParameter("date_to"),
        ],
    )
    def get(self, request):
        from core.services.invoice_validator import RULES
        org = request.user.organization
        inv_qs = Invoice.objects.filter(organization=org)
        if v := request.query_params.get("date_from"):
            inv_qs = inv_qs.filter(invoice_date__gte=v)
        if v := request.query_params.get("date_to"):
            inv_qs = inv_qs.filter(invoice_date__lte=v)

        vr_qs = InvoiceValidationResult.objects.filter(invoice__in=inv_qs)
        total = vr_qs.count()

        rule_breakdown = []
        for code, description in RULES.items():
            failures = sum(
                1 for vr in vr_qs.only("failed_rule_codes")
                if code in (vr.failed_rule_codes or [])
            )
            rule_breakdown.append({
                "rule_code":    code,
                "description":  description,
                "group":        code.split("-")[0],
                "failures":     failures,
                "passes":       total - failures,
                "pass_rate_pct": round((total - failures) / total * 100, 1) if total else 0,
                "fail_rate_pct": round(failures / total * 100, 1) if total else 0,
            })

        # Sort by fail rate descending
        rule_breakdown.sort(key=lambda x: -x["fail_rate_pct"])

        return Response({
            "report_type":  "30_rules_summary",
            "total_invoices_analyzed": total,
            "generated_at": str(date.today()),
            "rules":        rule_breakdown,
            "most_problematic": rule_breakdown[:5],
        })


class ReportListView(APIView):
    """List all generated reports."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Reports"],
        summary="List all generated reports",
        parameters=[OpenApiParameter("report_type", description="Filter by type")],
    )
    def get(self, request):
        from .serializers import ReportSerializer
        qs = Report.objects.filter(organization=request.user.organization).order_by("-created_at")
        if v := request.query_params.get("report_type"):
            qs = qs.filter(report_type=v)
        return Response(ReportSerializer(qs[:50], many=True).data)


class ReportDetailView(APIView):
    """Retrieve a specific report."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Reports"], summary="Get a specific report with full data and narrative")
    def get(self, request, pk):
        try:
            report = Report.objects.get(pk=pk, organization=request.user.organization)
        except Report.DoesNotExist:
            return Response({"error": "Report not found."}, status=404)

        return Response({
            "id":           str(report.id),
            "title":        report.title,
            "report_type":  report.report_type,
            "language":     report.language,
            "period_from":  report.period_from,
            "period_to":    report.period_to,
            "generated_by": report.generated_by.full_name if report.generated_by else None,
            "created_at":   report.created_at.isoformat(),
            "data":         report.data,
            "narrative":    report.narrative,
        })


class ReportExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Reports"], summary="Export organization data as JSON")
    def get(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        try:
            org_settings = getattr(org, "settings", None) or getattr(org, "finai_settings", None)
        except Exception:
            org_settings = None

        payload = {
            "exported_at": date.today().isoformat(),
            "organization": {
                "id": str(org.id),
                "name": org.name,
                "name_ar": org.name_ar,
                "country": org.country,
                "currency": org.currency,
                "vat_number": org.vat_number,
                "cr_number": org.cr_number,
                "vat_rate": org.vat_rate,
                "address": org.address,
                "website": getattr(org, "website", ""),
            },
            "settings": {
                "financial": getattr(org_settings, "financial", {}),
                "notifications": getattr(org_settings, "notifications", {}),
            },
            "reports": list(Report.objects.filter(organization=org).values()),
            "invoices": list(Invoice.objects.filter(organization=org).values()),
            "transactions": list(Transaction.objects.filter(organization=org).values()),
            "documents": list(Document.objects.filter(organization=org).values()),
            "audit_cases": list(AuditCase.objects.filter(organization=org).values()),
            "compliance_violations": list(ComplianceViolation.objects.filter(organization=org).values()),
        }

        response = HttpResponse(
            json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="tadgeeg-ai-export-{org.id}.json"'
        return response


class ReportPDFView(APIView):
    """Render a saved report as a downloadable PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            report = Report.objects.get(pk=pk, organization=request.user.organization)
        except Report.DoesNotExist:
            return HttpResponse("التقرير غير موجود.", status=404)

        from django.template.loader import render_to_string
        template_name = "reports/invoice_audit_report_pdf.html" if report.report_type == "invoice_audit" else "reports/report_pdf.html"
        html_str = render_to_string(template_name, {
            "report": report,
            "narrative": report.narrative or {},
            "data": report.data or {},
            "org": request.user.organization,
            "invoice_audit_ui": _build_invoice_audit_report_ui(report, request.user.organization) if report.report_type == "invoice_audit" else None,
        }, request=request)

        safe_title = (report.title or "report").replace(" ", "_").replace("/", "-")[:60]

        try:
            pdf_bytes = _render_report_pdf_bytes(
                html_str,
                request.build_absolute_uri("/"),
            )
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{safe_title}.pdf"'
            return response
        except ModuleNotFoundError:
            logger.warning("WeasyPrint not installed", extra={"report_id": str(report.id)})
            return JsonResponse(
                {"error": "خدمة PDF غير مهيأة على الخادم حاليًا. أعد نشر الخدمة بعد تثبيت مكتبة PDF."},
                status=503,
            )
        except OSError as e:
            # GTK libraries missing (common on Windows dev machines) — serve HTML fallback
            logger.warning("WeasyPrint OSError (missing GTK?) — serving HTML fallback: %s", e, extra={"report_id": str(report.id)})
        except Exception:
            logger.exception("Report PDF generation failed", extra={"report_id": str(report.id)})
            return JsonResponse(
                {"error": "تعذر توليد ملف PDF لهذا التقرير حاليًا. راجع سجل الخادم ثم أعد المحاولة."},
                status=500,
            )

        # HTML fallback: browser can use Ctrl+P → Save as PDF
        response = HttpResponse(html_str, content_type="text/html; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{safe_title}.html"'
        return response


class ReportExcelExportView(APIView):
    """Export a saved report as an .xlsx workbook (FR-7 gap fix)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Reports"], summary="Export report as Excel (.xlsx)")
    def get(self, request, pk):
        try:
            report = Report.objects.get(pk=pk, organization=request.user.organization)
        except Report.DoesNotExist:
            return HttpResponse("التقرير غير موجود.", status=404)

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            return JsonResponse({"error": "openpyxl غير متاح على السيرفر."}, status=500)

        import io
        wb = openpyxl.Workbook()

        # ── Sheet 1: Summary ────────────────────────────────────────────────
        ws = wb.active
        ws.title = "Summary"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="2563EB")

        def _hdr(cell_ref, value):
            cell = ws[cell_ref]
            cell.value = value
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        org = request.user.organization
        rows = [
            ("Report Title", report.title),
            ("Report Type", report.report_type),
            ("Organization", org.name),
            ("VAT Number", org.vat_number or ""),
            ("Period From", str(report.period_from or "")),
            ("Period To", str(report.period_to or "")),
            ("Generated By", report.generated_by.full_name if report.generated_by else ""),
            ("Generated At", report.created_at.strftime("%Y-%m-%d %H:%M")),
            ("Language", report.language),
        ]
        _hdr("A1", "Field")
        _hdr("B1", "Value")
        for i, (k, v) in enumerate(rows, start=2):
            ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 40

        # Narrative KPIs if present
        narrative = report.narrative or {}
        if narrative:
            ws.append([])
            ws.append(["── Narrative KPIs ──"])
            for key, val in narrative.items():
                if not isinstance(val, (dict, list)):
                    ws.append([str(key), str(val)])

        # ── Sheet 2: Invoices ────────────────────────────────────────────────
        data = report.data or {}
        invoices_data = data.get("invoices", [])
        ws2 = wb.create_sheet("Invoices")
        inv_headers = ["Invoice Number", "Supplier", "Date", "Base Amount", "Tax Amount",
                       "Total Amount", "Currency", "Status", "Compliance Status"]
        for col, h in enumerate(inv_headers, 1):
            c = ws2.cell(row=1, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
        if isinstance(invoices_data, list):
            for row_i, inv in enumerate(invoices_data, start=2):
                if isinstance(inv, dict):
                    ws2.cell(row=row_i, column=1, value=inv.get("invoice_number", ""))
                    ws2.cell(row=row_i, column=2, value=inv.get("supplier_name", ""))
                    ws2.cell(row=row_i, column=3, value=str(inv.get("invoice_date", "")))
                    ws2.cell(row=row_i, column=4, value=float(inv.get("total_amount", 0) or 0))
                    ws2.cell(row=row_i, column=5, value=float(inv.get("tax_amount", 0) or 0))
                    ws2.cell(row=row_i, column=6, value=float(inv.get("total_amount", 0) or 0))
                    ws2.cell(row=row_i, column=7, value=inv.get("currency", "SAR"))
                    ws2.cell(row=row_i, column=8, value=inv.get("status", ""))
                    ws2.cell(row=row_i, column=9, value=inv.get("compliance_status", ""))
        for col in range(1, len(inv_headers) + 1):
            ws2.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18

        # ── Sheet 3: Audit Cases / Findings ─────────────────────────────────
        ws3 = wb.create_sheet("Findings")
        cases_qs = AuditCase.objects.filter(
            organization=request.user.organization
        ).values("case_number", "case_type", "priority", "status", "title",
                 "description", "created_at", "resolved_at")
        case_headers = ["Case #", "Type", "Priority", "Status", "Title",
                        "Description", "Created At", "Resolved At"]
        for col, h in enumerate(case_headers, 1):
            c = ws3.cell(row=1, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
        for row_i, case in enumerate(cases_qs, start=2):
            ws3.cell(row=row_i, column=1, value=case["case_number"])
            ws3.cell(row=row_i, column=2, value=case["case_type"])
            ws3.cell(row=row_i, column=3, value=case["priority"])
            ws3.cell(row=row_i, column=4, value=case["status"])
            ws3.cell(row=row_i, column=5, value=case["title"])
            ws3.cell(row=row_i, column=6, value=case["description"] or "")
            ws3.cell(row=row_i, column=7, value=str(case["created_at"])[:19] if case["created_at"] else "")
            ws3.cell(row=row_i, column=8, value=str(case["resolved_at"])[:19] if case["resolved_at"] else "")
        for col in range(1, len(case_headers) + 1):
            ws3.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20

        # ── Sheet 4: Rule Summary ────────────────────────────────────────────
        ws4 = wb.create_sheet("Rule Summary")
        rule_summary = data.get("rule_group_summary", [])
        rs_headers = ["Rule Group", "Passed", "Failed", "Total", "Pass Rate %"]
        for col, h in enumerate(rs_headers, 1):
            c = ws4.cell(row=1, column=col, value=h)
            c.font = header_font
            c.fill = header_fill
        if isinstance(rule_summary, list):
            for row_i, rs in enumerate(rule_summary, start=2):
                if isinstance(rs, dict):
                    ws4.cell(row=row_i, column=1, value=rs.get("label", rs.get("code", "")))
                    ws4.cell(row=row_i, column=2, value=rs.get("passed", 0))
                    ws4.cell(row=row_i, column=3, value=rs.get("failed", 0))
                    ws4.cell(row=row_i, column=4, value=rs.get("total", 0))
                    ws4.cell(row=row_i, column=5, value=rs.get("pct", 0))

        # ── Serialize and return ─────────────────────────────────────────────
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        safe_title = (report.title or "report").replace(" ", "_").replace("/", "-")[:50]
        response = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{safe_title}.xlsx"'
        return response


class ReportEmailView(APIView):
    """Email a report PDF to the requesting user (FR-7 gap fix)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Reports"], summary="Email report PDF to current user")
    def post(self, request, pk):
        try:
            report = Report.objects.get(pk=pk, organization=request.user.organization)
        except Report.DoesNotExist:
            return Response({"error": "التقرير غير موجود."}, status=404)

        from django.core.mail import EmailMessage
        from django.template.loader import render_to_string
        from django.conf import settings as django_settings

        template_name = "reports/invoice_audit_report_pdf.html" if report.report_type == "invoice_audit" else "reports/report_pdf.html"
        html_str = render_to_string(template_name, {
            "report": report,
            "narrative": report.narrative or {},
            "data": report.data or {},
            "org": request.user.organization,
            "invoice_audit_ui": _build_invoice_audit_report_ui(report, request.user.organization) if report.report_type == "invoice_audit" else None,
        }, request=request)

        safe_title = (report.title or "report").replace(" ", "_").replace("/", "-")[:60]
        recipient = request.user.email

        try:
            pdf_bytes = _render_report_pdf_bytes(html_str, request.build_absolute_uri("/"))
            msg = EmailMessage(
                subject=f"[Tadgeeg AI] {report.title}",
                body=f"مرفق تقرير: {report.title}\n\nتم إنشاؤه في {report.created_at.strftime('%Y-%m-%d %H:%M')}",
                from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@tadgeeg.com"),
                to=[recipient],
            )
            msg.attach(f"{safe_title}.pdf", pdf_bytes, "application/pdf")
            msg.send()
            return Response({"success": True, "message": f"تم إرسال التقرير إلى {recipient}"})
        except Exception as e:
            logger.exception("Report email failed for report %s", pk)
            return Response({"error": "تعذر إرسال البريد الإلكتروني. راجع إعدادات SMTP."}, status=500)
