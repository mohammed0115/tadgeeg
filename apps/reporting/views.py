from __future__ import annotations

import logging

from django.http import HttpResponse

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.reporting.exceptions import ReportGenerationError
from apps.reporting.models import Report
from apps.reporting.permissions import CanGenerateReport
from apps.reporting.selectors import get_reports_for_org
from apps.reporting.serializers import (
    GenerateReportSerializer,
    ReportListSerializer,
    ReportSerializer,
)
from apps.reporting.services.report_service import ReportService

logger = logging.getLogger(__name__)


class ReportViewSet(ModelViewSet):
    """CRUD + generation + export for Report objects.

    * ``list`` / ``retrieve`` — return reports scoped to the user's org.
    * ``create`` — disabled; use the ``/generate`` action instead.
    * ``update`` / ``partial_update`` / ``destroy`` — disabled.

    Extra actions
    -------------
    POST  /reports/generate/           — generate a new report
    GET   /reports/{id}/download-url/  — get the download URL
    GET   /reports/{id}/export/        — stream CSV or JSON
    """

    permission_classes = [CanGenerateReport]
    http_method_names = ["get", "post", "head", "options"]

    # ------------------------------------------------------------------ #
    # Queryset / serializer selection
    # ------------------------------------------------------------------ #

    def get_queryset(self):
        user = self.request.user
        org = getattr(user, "organization", None)

        if user.is_staff or user.is_superuser:
            return Report.objects.select_related(
                "organization", "generated_by", "related_audit_job"
            ).prefetch_related("items").order_by("-created_at")

        if org is None:
            return Report.objects.none()

        return (
            get_reports_for_org(org)
            .select_related("organization", "generated_by", "related_audit_job")
            .prefetch_related("items")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return ReportListSerializer
        return ReportSerializer

    # ------------------------------------------------------------------ #
    # Disabled mutations
    # ------------------------------------------------------------------ #

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use /generate/ to create reports."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    # ------------------------------------------------------------------ #
    # /generate/
    # ------------------------------------------------------------------ #

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """Trigger synchronous report generation and return the report."""
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        report_type: str = data["report_type"]
        audit_job_id = data.get("audit_job_id")
        fmt: str = data.get("format", "json")

        user = request.user
        org = getattr(user, "organization", None)
        if org is None and not (user.is_staff or user.is_superuser):
            return Response(
                {"detail": "User has no associated organisation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        svc = ReportService()

        try:
            if report_type == Report.ReportType.AUDIT_SUMMARY:
                report = svc.generate_audit_summary_report(
                    organization=org,
                    generated_by=user,
                    audit_job_id=str(audit_job_id) if audit_job_id else None,
                )
            elif report_type == Report.ReportType.ISSUES_EXPORT:
                report = svc.generate_issues_export(
                    organization=org,
                    generated_by=user,
                    audit_job_id=str(audit_job_id) if audit_job_id else None,
                    format=fmt,
                )
            elif report_type == Report.ReportType.ORG_AUDIT_OVERVIEW:
                report = svc.generate_org_overview(
                    organization=org,
                    generated_by=user,
                )
            else:
                return Response(
                    {"detail": f"Unsupported report_type: {report_type}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as exc:
            logger.exception("Report generation error: %s", exc)
            return Response(
                {"detail": "Report generation failed.", "error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        out_serializer = ReportSerializer(report, context={"request": request})
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------ #
    # /{id}/download-url/
    # ------------------------------------------------------------------ #

    @action(detail=True, methods=["get"], url_path="download-url")
    def download_url(self, request, pk=None):
        """Return the URL from which the report file can be downloaded."""
        report: Report = self.get_object()
        svc = ReportService()
        try:
            url = svc.get_report_download_url(report)
        except ReportGenerationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"url": url})

    # ------------------------------------------------------------------ #
    # /{id}/export/
    # ------------------------------------------------------------------ #

    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        """Stream the report as CSV or JSON.

        Format resolution order:
        1. ``format`` query param (``csv`` | ``json``)
        2. ``Accept`` request header (``text/csv`` → CSV, else JSON)
        """
        report: Report = self.get_object()

        if report.status != Report.Status.READY:
            return Response(
                {"detail": f"Report is not ready (status={report.status})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        svc = ReportService()
        fmt = request.query_params.get("format", "").lower()
        if not fmt:
            accept = request.META.get("HTTP_ACCEPT", "")
            fmt = "csv" if "text/csv" in accept else "json"

        if fmt == "csv":
            csv_content = svc.export_to_csv(report)
            response = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = (
                f'attachment; filename="report_{report.id}.csv"'
            )
            return response

        # Default: JSON
        json_data = svc.export_to_json(report)
        return Response(json_data)
