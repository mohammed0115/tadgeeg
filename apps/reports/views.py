"""Reports Views — AI-generated audit and financial reports (including Invoice Audit)"""

import logging
import json
from datetime import date
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
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


# ─── Helper: collect invoice section data ─────────────────────────────────────

def _collect_invoice_data(org, date_from=None, date_to=None) -> dict:
    """Aggregate all invoice audit data for reports."""
    inv_qs = Invoice.objects.filter(organization=org)
    if date_from:
        inv_qs = inv_qs.filter(invoice_date__gte=date_from)
    if date_to:
        inv_qs = inv_qs.filter(invoice_date__lte=date_to)

    # ── Overall stats ──────────────────────────────────────────────────────────
    stats = inv_qs.aggregate(
        total_invoices=Count("id"),
        total_amount=Sum("total_amount"),
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
            total_amount=Sum("total_amount"),
            avg_amount=Avg("total_amount"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
        )
        .order_by("-total_amount")[:15]
    )
    vendor_list = []
    total_spend = float(stats["total_amount"] or 0)
    for v in vendor_stats:
        v_total = float(v["total_amount"] or 0)
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
            "total_amount":    round(float(stats["total_amount"]  or 0), 2),
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
        }

        # ── Invoice Audit Section ──────────────────────────────────────────────
        if include_invoices:
            audit_data["invoice_audit"] = _collect_invoice_data(org, date_from, date_to)

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
        narrative = generate_audit_narrative(audit_data, language=language)

        # ── Save Report ────────────────────────────────────────────────────────
        report = Report.objects.create(
            organization=org,
            generated_by=request.user,
            report_type=report_type,
            language=language,
            period_from=date_from,
            period_to=date_to,
            data=audit_data,
            narrative=narrative,
            title=f"{report_type.replace('_', ' ').title()} Report — {date_to}",
        )

        return Response({
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

        data = _collect_invoice_data(org, date_from, date_to)

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
        response["Content-Disposition"] = f'attachment; filename="finai-export-{org.id}.json"'
        return response
