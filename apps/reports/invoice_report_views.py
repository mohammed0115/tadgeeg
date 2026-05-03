"""
Invoice Audit Report API Views — Clean sub-endpoint design.

Endpoints:
    POST /api/v1/reports/invoice-audit/                   Generate report
    GET  /api/v1/reports/invoice-audit/<pk>/              Full report JSON
    GET  /api/v1/reports/invoice-audit/<pk>/html/         View as HTML
    GET  /api/v1/reports/invoice-audit/<pk>/pdf/          Download PDF
    GET  /api/v1/reports/invoice-audit/<pk>/high-risk/    High-risk invoices
    GET  /api/v1/reports/invoice-audit/<pk>/failed-rules/ Failed rules aggregate
    GET  /api/v1/reports/invoice-audit/<pk>/supplier-analysis/ Supplier breakdown

Multi-tenant security:
    Every view uses _TenantReportMixin which:
    1. Reads org from request.user.organization
    2. ALWAYS scopes Report.objects.get(pk=pk, organization=org)
    3. Returns 404 (not 403) to prevent enumeration attacks
"""

import logging

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Report
from .services.invoice_audit_service import InvoiceAuditReportService
from .invoice_serializers import (
    InvoiceAuditReportRequestSerializer,
    InvoiceAuditReportSerializer,
)

try:
    from apps.reports.tasks import generate_invoice_audit_report
except Exception:  # pragma: no cover - Celery may be unavailable in lightweight test runs
    generate_invoice_audit_report = None

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Tenant Security Mixin
# ─────────────────────────────────────────────────────────────────────────────

class _TenantReportMixin:
    """
    Enforces tenant isolation for every report access.

    Pattern:
        ALWAYS filter Report by (pk=pk, organization=org, report_type=...)
        NEVER trust pk alone — a user from Org A must never read Org B reports.

    Returns 404 (not 403) on cross-tenant access to prevent enumeration.
    """

    _REPORT_TYPES = ("invoice_audit",)   # subclasses may override

    def _org(self):
        org = getattr(self.request.user, "organization", None)
        if not org:
            return None
        return org

    def _get_report(self, pk) -> Report | None:
        org = self._org()
        if not org:
            return None
        try:
            return Report.objects.get(
                pk=pk,
                organization=org,
                report_type__in=self._REPORT_TYPES,
            )
        except Report.DoesNotExist:
            return None

    def _not_found(self):
        return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

    def _no_org(self):
        return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)


# ─────────────────────────────────────────────────────────────────────────────
# Context builder (shared by HTML + PDF views)
# ─────────────────────────────────────────────────────────────────────────────

def _build_template_context(data: dict) -> dict:
    """Map report dict to template context variables."""
    hdr = data.get("report_header", {})
    return {
        "report":        data,
        "header":        hdr,
        "summary":       data.get("summary", {}),
        "executive":     data.get("executive_summary", {}),
        "decision":      data.get("decision_support", {}),
        "compliance":    data.get("compliance_engine", {}),
        "high_risk":     data.get("high_risk_invoices", []),
        "failed_rules":  data.get("failed_rules_analysis", []),
        "suppliers":     data.get("supplier_analysis", []),
        "risk":          data.get("risk_analysis", {}),
        "anomalies":     data.get("anomalies", {}),
        "recs":          data.get("actions_and_recommendations", {}),
        "is_rtl":        hdr.get("language", "ar") == "ar",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generate
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportGenerateView(APIView):
    """
    POST /api/v1/reports/invoice-audit/

    Body:
        {
            "date_from": "YYYY-MM-DD",  (optional)
            "date_to":   "YYYY-MM-DD",  (optional)
            "language":  "ar|en",
            "save":      true
        }

    Returns full InvoiceAuditReport JSON (201 Created).
    report_header.report_id is populated when save=true.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

        req_ser = InvoiceAuditReportRequestSerializer(data=request.data)
        if not req_ser.is_valid():
            return Response(req_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        date_from = req_ser.validated_data.get("date_from")
        date_to   = req_ser.validated_data.get("date_to")
        language  = req_ser.validated_data.get("language", "ar")
        do_save   = req_ser.validated_data.get("save", True)

        use_async = req_ser.validated_data.get("use_async", False)

        if use_async:
            task_runner = generate_invoice_audit_report
            if task_runner is None:
                from apps.reports.tasks import generate_invoice_audit_report as task_runner
            task = task_runner.delay(
                org_id=str(org.id),
                user_id=str(request.user.id),
                date_from=str(date_from) if date_from else None,
                date_to=str(date_to)   if date_to   else None,
                language=language,
            )
            return Response(
                {"task_id": task.id, "status": "queued"},
                status=status.HTTP_202_ACCEPTED,
            )

        try:
            svc  = InvoiceAuditReportService(org, request.user)
            data = svc.build(date_from=date_from, date_to=date_to, language=language)
            report_header = data.setdefault("report_header", {})

            if do_save:
                report_title = (
                    report_header.get("title")
                    or report_header.get("title_en")
                    or report_header.get("title_ar")
                    or "Invoice Audit Report"
                )
                report_obj = Report.objects.create(
                    organization=org,
                    generated_by=request.user,
                    title=report_title,
                    report_type="invoice_audit",
                    language=language,
                    period_from=str(date_from) if date_from else "",
                    period_to=str(date_to)   if date_to   else "",
                    data=data,
                    narrative={},
                )
                report_header["report_id"] = str(report_obj.id)

            return Response(data, status=status.HTTP_201_CREATED)

        except Exception as exc:
            logger.exception("InvoiceAuditReport generation failed: %s", exc)
            return Response(
                {"error": f"Report generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Detail — full report JSON
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportDetailView(_TenantReportMixin, APIView):
    """GET /api/v1/reports/invoice-audit/<pk>/ — Full report JSON."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()
        return Response(report.data)


# ─────────────────────────────────────────────────────────────────────────────
# HTML view
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportHTMLView(_TenantReportMixin, APIView):
    """GET /api/v1/reports/invoice-audit/<pk>/html/ — View as HTML in browser."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()

        context  = _build_template_context(report.data)
        context["request"] = request
        html_str = render_to_string(
            "reports/invoice_audit_report_v2.html", context, request=request
        )
        return HttpResponse(html_str, content_type="text/html; charset=utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# PDF view
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceAuditReportPDFView(_TenantReportMixin, APIView):
    """GET /api/v1/reports/invoice-audit/<pk>/pdf/ — Download PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()

        context  = _build_template_context(report.data)
        context["request"] = request
        html_str = render_to_string(
            "reports/invoice_audit_report_v2.html", context, request=request
        )

        try:
            from apps.reports.views import _render_report_pdf_bytes
            pdf_bytes = _render_report_pdf_bytes(html_str, request.build_absolute_uri("/"))
            response  = HttpResponse(pdf_bytes, content_type="application/pdf")
            safe_title = (report.title or "invoice_audit").replace(" ", "_")[:60]
            response["Content-Disposition"] = f'attachment; filename="{safe_title}.pdf"'
            return response
        except Exception as exc:
            logger.error("PDF generation failed for report %s: %s", pk, exc)
            response = HttpResponse(html_str, content_type="text/html; charset=utf-8")
            response["X-Report-PDF-Fallback"] = "html"
            return response


# ─────────────────────────────────────────────────────────────────────────────
# Sub-endpoints (paginated slices of the stored report)
# ─────────────────────────────────────────────────────────────────────────────

class HighRiskInvoicesView(_TenantReportMixin, APIView):
    """
    GET /api/v1/reports/invoice-audit/<pk>/high-risk/

    Returns the high_risk_invoices section of a saved report.
    Supports ?limit=N query parameter (default 25, max 100).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()

        limit  = min(int(request.query_params.get("limit", 25)), 100)
        items  = report.data.get("high_risk_invoices", [])[:limit]
        return Response({
            "count":   len(report.data.get("high_risk_invoices", [])),
            "results": items,
        })


class FailedRulesView(_TenantReportMixin, APIView):
    """
    GET /api/v1/reports/invoice-audit/<pk>/failed-rules/

    Returns failed_rules_analysis — sorted by failure_count descending.
    Supports ?category=<cat> filter and ?limit=N.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()

        rules    = report.data.get("failed_rules_analysis", [])
        category = request.query_params.get("category")
        if category:
            rules = [r for r in rules if r.get("category") == category]
        limit = min(int(request.query_params.get("limit", 50)), 200)
        return Response({
            "count":   len(rules),
            "results": rules[:limit],
        })


class SupplierAnalysisView(_TenantReportMixin, APIView):
    """
    GET /api/v1/reports/invoice-audit/<pk>/supplier-analysis/

    Returns supplier_analysis — sorted by total_spend descending.
    Supports ?risk_tier=<tier> filter and ?limit=N.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()

        suppliers = report.data.get("supplier_analysis", [])
        risk_tier = request.query_params.get("risk_tier")
        if risk_tier:
            suppliers = [s for s in suppliers if s.get("risk_tier") == risk_tier]
        limit = min(int(request.query_params.get("limit", 50)), 200)
        return Response({
            "count":   len(suppliers),
            "results": suppliers[:limit],
        })


class ComplianceEngineView(_TenantReportMixin, APIView):
    """
    GET /api/v1/reports/invoice-audit/<pk>/compliance/

    Returns compliance_engine section — rule pass/fail by category.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not self._org():
            return self._no_org()
        report = self._get_report(pk)
        if not report:
            return self._not_found()
        return Response(report.data.get("compliance_engine", {}))
