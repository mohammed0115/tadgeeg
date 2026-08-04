"""
Document Report API Views — Tadgeeg Reporting System v2.

Endpoints:
    POST /api/v1/reports/document/           Generate single-document report
    GET  /api/v1/reports/document/<id>/      Retrieve saved document report
    GET  /api/v1/reports/document/<id>/pdf/  Download PDF
    GET  /api/v1/reports/document/<id>/html/ View HTML in browser
    POST /api/v1/reports/executive/          Generate executive report
    GET  /api/v1/reports/executive/latest/   Latest saved executive report
    GET  /api/v1/reports/executive/<id>/pdf/ Download executive PDF
"""

import logging
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsSeniorAuditorOrAbove
from .models import Report
from .document_serializers import (
    DocumentReportRequestSerializer,
    ExecutiveReportRequestSerializer,
    DocumentAuditReportSerializer,
    ExecutiveReportSerializer,
)

logger = logging.getLogger("finai")


def _get_org(request):
    return getattr(request.user, "organization", None)


# ─────────────────────────────────────────────────────────────
# Document Report Views
# ─────────────────────────────────────────────────────────────

class DocumentReportGenerateView(APIView):
    """
    POST /api/v1/reports/document/

    Body:
        {
            "document_id":   "<uuid>",
            "document_type": "sales_invoice|purchase_order|...",
            "language":      "ar|en",
            "save":          true
        }

    Returns full DocumentAuditReport JSON.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = _get_org(request)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

        req_ser = DocumentReportRequestSerializer(data=request.data)
        if not req_ser.is_valid():
            return Response(req_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        document_id   = req_ser.validated_data.get("document_id")   # may be None
        document_type = req_ser.validated_data["document_type"]
        language      = req_ser.validated_data.get("language", "ar")
        do_save       = req_ser.validated_data.get("save", True)

        try:
            from core.services.document_report_service import DocumentReportService
            svc = DocumentReportService(org, request.user)
            # No document_id → aggregate summary for all documents of this type
            if not document_id:
                data = svc.build_summary(document_type, language)
            else:
                data = svc.build(str(document_id), document_type, language)

            # Optionally persist
            if do_save:
                is_summary = not document_id
                report_obj = Report.objects.create(
                    organization=org,
                    generated_by=request.user,
                    title=self._report_title(data, language, summary=is_summary),
                    report_type=f"document_audit_{document_type}",
                    language=language,
                    data=data,
                    narrative={},
                )
                data["report_meta"]["report_id"] = str(report_obj.id)

            return Response(data, status=status.HTTP_201_CREATED)

        except Exception as exc:
            logger.exception("DocumentReport generation failed for %s/%s: %s", document_type, document_id, exc)
            return Response(
                {"error": f"Report generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    def _report_title(data: dict, language: str, summary: bool = False) -> str:
        meta = data.get("report_meta", {})
        raw_label = meta.get("document_type_label_ar") if language == "ar" else meta.get("document_type_label_en", "")
        doc_label = str(raw_label or "").strip()
        if summary:
            return f"تقرير إجمالي — {doc_label}".strip() if language == "ar" else \
                   f"Summary Report — {doc_label}".strip()
        raw_doc_num = data.get("key_fields", {}).get("document_number", "")
        doc_num = str(raw_doc_num or "").strip()
        return f"تقرير تدقيق — {doc_label} {doc_num}".strip() if language == "ar" else \
               f"Audit Report — {doc_label} {doc_num}".strip()


def _refresh_stale_report(report, org, user) -> dict:
    """
    Re-generate report data if the saved copy is stale (total_rules == 0
    but the document still exists). Updates the report row in-place.
    Returns the (possibly fresh) data dict.
    """
    data = report.data or {}
    summary = data.get("summary", {})
    meta = data.get("report_meta", {})

    # Nothing to refresh if it's a summary-type report or already has data
    if summary.get("total_rules", 0) != 0:
        return data
    doc_id   = meta.get("document_id")
    doc_type = meta.get("document_type") or (report.report_type or "").replace("document_audit_", "")
    language = meta.get("language", "ar")
    if not doc_id or not doc_type:
        return data

    try:
        from core.services.document_report_service import DocumentReportService
        svc       = DocumentReportService(org, user)
        fresh     = svc.build(str(doc_id), doc_type, language)
        fresh["report_meta"]["report_id"] = str(report.id)
        report.data = fresh
        report.save(update_fields=["data"])
        logger.info("Auto-refreshed stale report %s (%s/%s)", report.id, doc_type, doc_id)
        return fresh
    except Exception as exc:
        logger.warning("Auto-refresh failed for report %s: %s", report.id, exc)
        return data


class DocumentReportDetailView(APIView):
    """GET /api/v1/reports/document/<pk>/ — Retrieve saved document report."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = _get_org(request)
        try:
            report = Report.objects.get(pk=pk, organization=org)
        except Report.DoesNotExist:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

        data = _refresh_stale_report(report, org, request.user)
        return Response(data)


class DocumentReportPDFView(APIView):
    """GET /api/v1/reports/document/<pk>/pdf/ — Download PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = _get_org(request)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)
        try:
            report = Report.objects.get(pk=pk, organization=org)
        except Report.DoesNotExist:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

        data = _refresh_stale_report(report, org, request.user)
        context = self._build_context(data, request)
        html_str = render_to_string("reports/document_audit_report.html", context, request=request)

        try:
            from apps.reports.views import _render_report_pdf_bytes, _attachment_disposition
            pdf_bytes = _render_report_pdf_bytes(html_str, request.build_absolute_uri("/"))
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            safe_title = (report.title or "report").replace(" ", "_")[:60]
            response["Content-Disposition"] = _attachment_disposition(f"{safe_title}.pdf")
            return response
        except (ModuleNotFoundError, OSError) as exc:
            # Serve the HTML instead of a 503, matching /reports/<id>/pdf/ and
            # /reports/invoice-audit/<id>/pdf/. Three PDF endpoints answered the
            # same failure three different ways, so a client could not write one
            # branch that handled all of them.
            #
            # HTML with 200 was chosen over 503-everywhere because the report
            # itself is fine — only the renderer is missing — and a browser can
            # print it. The response is made impossible to mistake for a PDF by
            # three things together: content type, the .html filename, and the
            # X-Report-PDF-Fallback header for an API client that only checks
            # the status code.
            logger.warning(
                "WeasyPrint unavailable (%s) for document report %s — serving HTML fallback: %s",
                type(exc).__name__, pk, exc,
            )
            from apps.reports.views import _attachment_disposition

            safe_title = (report.title or "report").replace(" ", "_")[:60]
            response = HttpResponse(html_str, content_type="text/html; charset=utf-8")
            response["Content-Disposition"] = _attachment_disposition(f"{safe_title}.html")
            response["X-Report-PDF-Fallback"] = "html"
            return response
        except Exception as exc:
            logger.error("PDF generation failed for document report %s: %s", pk, exc)
            return Response(
                {"error": _("PDF generation failed. Use the /html/ endpoint to view the report.")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    def _build_context(data: dict, request) -> dict:
        return {
            "report":             data,
            "meta":               data.get("report_meta", {}),
            "summary":            data.get("summary", {}),
            "key_fields":         data.get("key_fields", {}),
            "rules":              data.get("rule_evaluation", []),
            "violations":         data.get("violations", []),
            "compliance":         data.get("compliance", {}),
            "ai":                 data.get("ai_insights", {}),
            "recs":               data.get("recommendations", []),
            "trail":              data.get("audit_trail", {}),
            "specific":           data.get("document_specific", {}),
            "narrative":          data.get("ai_narrative", {}),
            "is_rtl":             data.get("report_meta", {}).get("language", "ar") == "ar",
            "request":            request,
        }


class DocumentReportHTMLView(DocumentReportPDFView):
    """GET /api/v1/reports/document/<pk>/html/ — View HTML in browser."""

    def get(self, request, pk):
        org = _get_org(request)
        try:
            report = Report.objects.get(pk=pk, organization=org)
        except Report.DoesNotExist:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

        data = _refresh_stale_report(report, org, request.user)
        context = self._build_context(data, request)
        html_str = render_to_string("reports/document_audit_report.html", context, request=request)
        return HttpResponse(html_str, content_type="text/html; charset=utf-8")


# ─────────────────────────────────────────────────────────────
# Executive Report Views
# ─────────────────────────────────────────────────────────────

class ExecutiveReportGenerateView(APIView):
    """
    POST /api/v1/reports/executive/

    Body:
        {
            "date_from": "YYYY-MM-DD",   (optional)
            "date_to":   "YYYY-MM-DD",   (optional)
            "language":  "ar|en",
            "save":      true
        }

    Returns full ExecutiveReport JSON.
    """
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    def post(self, request):
        org = _get_org(request)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

        req_ser = ExecutiveReportRequestSerializer(data=request.data)
        if not req_ser.is_valid():
            return Response(req_ser.errors, status=status.HTTP_400_BAD_REQUEST)

        date_from = req_ser.validated_data.get("date_from")
        date_to   = req_ser.validated_data.get("date_to")
        language  = req_ser.validated_data.get("language", "ar")
        do_save   = req_ser.validated_data.get("save", True)

        try:
            from core.services.document_report_service import ExecutiveReportService
            svc  = ExecutiveReportService(org, request.user)
            data = svc.build(date_from=date_from, date_to=date_to, language=language)

            if do_save:
                meta = data.get("report_meta", {})
                report_obj = Report.objects.create(
                    organization=org,
                    generated_by=request.user,
                    title="التقرير التنفيذي الشامل" if language == "ar" else "Executive Audit Report",
                    report_type="executive_summary",
                    language=language,
                    period_from=str(date_from) if date_from else "",
                    period_to=str(date_to)   if date_to   else "",
                    data=data,
                    narrative={},
                )
                data["report_meta"]["report_id"] = str(report_obj.id)

            return Response(data, status=status.HTTP_201_CREATED)

        except Exception as exc:
            logger.exception("ExecutiveReport generation failed: %s", exc)
            return Response(
                {"error": f"Executive report failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExecutiveReportLatestView(APIView):
    """GET /api/v1/reports/executive/latest/ — Latest saved executive report."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        report = (
            Report.objects.filter(organization=org, report_type="executive_summary")
            .order_by("-created_at")
            .first()
        )
        if not report:
            return Response({"error": "No executive report found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(report.data)


def _exec_report_context(report, request) -> dict:
    """Build template context for executive report. Safe against None/empty data."""
    data = report.data or {}
    return {
        "report":        data,
        "meta":          data.get("report_meta", {}),
        "exec_sum":      data.get("executive_summary", {}),
        "financial":     data.get("financial_overview", {}),
        "audit_ov":      data.get("audit_overview", {}),
        "risk":          data.get("risk_analysis", {}),
        "compliance":    data.get("compliance_overview", {}),
        "top_issues":    data.get("top_issues", []),
        "ai":            data.get("ai_insights", {}),
        "recs":          data.get("recommendations", []),
        "doc_breakdown": data.get("document_breakdown", []),
        "is_rtl":        data.get("report_meta", {}).get("language", "ar") == "ar",
        "request":       request,
    }


def _get_executive_report(pk, org):
    """
    Fetch an executive report by pk + organization.
    Does NOT filter by report_type — supports both 'executive_summary'
    and any legacy type strings stored by older generation code.
    """
    try:
        return Report.objects.get(pk=pk, organization=org)
    except Report.DoesNotExist:
        return None


class ExecutiveReportPDFView(APIView):
    """GET /api/v1/reports/executive/<pk>/pdf/ — Download executive PDF."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = _get_org(request)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

        report = _get_executive_report(pk, org)
        if report is None:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

        context  = _exec_report_context(report, request)
        html_str = render_to_string("reports/executive_report.html", context, request=request)

        try:
            from apps.reports.views import _render_report_pdf_bytes
            pdf_bytes = _render_report_pdf_bytes(html_str, request.build_absolute_uri("/"))
            response  = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = 'attachment; filename="executive_report.pdf"'
            return response
        except OSError as exc:
            logger.warning("WeasyPrint OSError (missing system libs) for executive report %s: %s", pk, exc)
            return Response(
                {"error": _("PDF libraries are not configured on the server. Use the /html/ endpoint to view the report.")},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.error("PDF generation failed for executive report %s: %s", pk, exc)
            return Response(
                {"error": _("PDF generation failed. Use the /html/ endpoint to view the report.")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExecutiveReportHTMLView(APIView):
    """GET /api/v1/reports/executive/<pk>/html/ — View executive report in browser."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = _get_org(request)
        if not org:
            return Response({"error": "No organization."}, status=status.HTTP_403_FORBIDDEN)

        report = _get_executive_report(pk, org)
        if report is None:
            return Response({"error": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

        context  = _exec_report_context(report, request)
        html_str = render_to_string("reports/executive_report.html", context, request=request)
        return HttpResponse(html_str, content_type="text/html; charset=utf-8")


# ─── Widget Config View ───────────────────────────────────────────────────────

class ReportWidgetsView(APIView):
    """
    GET /api/v1/reports/widgets/?report_type=document_audit&document_type=sales_invoice
    GET /api/v1/reports/widgets/?report_type=executive

    Returns the ordered list of dashboard widget definitions for the given report context.
    The frontend uses this to render the correct widget layout without hard-coded logic.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .dashboard_widgets import get_widgets
        report_type   = request.query_params.get("report_type", "document_audit")
        document_type = request.query_params.get("document_type")

        if report_type not in ("document_audit", "executive"):
            return Response(
                {"error": "report_type must be 'document_audit' or 'executive'"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if report_type == "document_audit" and not document_type:
            return Response(
                {"error": "document_type is required when report_type=document_audit"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        widgets = get_widgets(report_type, document_type)
        return Response({"report_type": report_type, "document_type": document_type, "widgets": widgets})


# ─── JSON Schema View ─────────────────────────────────────────────────────────

class ReportSchemaView(APIView):
    """
    GET /api/v1/reports/schema/?type=document
    GET /api/v1/reports/schema/?type=executive
    GET /api/v1/reports/schema/?type=document_specific&document_type=sales_invoice

    Returns the JSON Schema for the requested report type.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .schemas import DOCUMENT_REPORT_SCHEMA, EXECUTIVE_REPORT_SCHEMA, DOCUMENT_SPECIFIC_SCHEMAS
        schema_type   = request.query_params.get("type", "document")
        document_type = request.query_params.get("document_type")

        if schema_type == "document":
            return Response(DOCUMENT_REPORT_SCHEMA)
        if schema_type == "executive":
            return Response(EXECUTIVE_REPORT_SCHEMA)
        if schema_type == "document_specific":
            if not document_type:
                return Response(DOCUMENT_SPECIFIC_SCHEMAS)
            schema = DOCUMENT_SPECIFIC_SCHEMAS.get(document_type)
            if not schema:
                return Response({"error": f"Unknown document_type '{document_type}'"}, status=400)
            return Response(schema)

        return Response(
            {"error": "type must be 'document', 'executive', or 'document_specific'"},
            status=status.HTTP_400_BAD_REQUEST,
        )
