"""Auditing Result View."""

import logging
from collections import defaultdict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View

from apps.auditing.models import AuditDocument

logger = logging.getLogger(__name__)


class AuditDocumentResultView(LoginRequiredMixin, View):
    """Display the AI audit result for a specific document."""

    login_url = "/login/"
    template_name = "auditing/result.html"

    def get(self, request, pk):
        document = self._get_document(request, pk)

        # Group findings by type
        findings_by_type = defaultdict(list)
        for finding in document.findings.all():
            findings_by_type[finding.finding_type].append(finding)

        # Extract structured sections from ai_result
        ai_result = document.ai_result or {}
        extracted_data = ai_result.get("extracted_data", {})
        anomalies = ai_result.get("anomalies", [])
        compliance_review = ai_result.get("compliance_review", {})
        recommendations = ai_result.get("recommendations", [])
        executive_summary = ai_result.get("executive_summary", "")
        confidence_score = ai_result.get("confidence_score", document.overall_confidence)

        # Normalize confidence to percentage
        if isinstance(confidence_score, float) and confidence_score <= 1.0:
            confidence_pct = round(confidence_score * 100, 1)
        else:
            confidence_pct = round(float(confidence_score or 0), 1)

        context = {
            "doc": document,
            "findings_by_type": dict(findings_by_type),
            "anomaly_findings": findings_by_type.get("anomaly", []),
            "validation_findings": findings_by_type.get("validation", []),
            "compliance_findings": findings_by_type.get("compliance", []),
            "recommendation_findings": findings_by_type.get("recommendation", []),
            "extracted_data": extracted_data,
            "anomalies": anomalies,
            "compliance_review": compliance_review,
            "recommendations": recommendations,
            "executive_summary": executive_summary,
            "confidence_pct": confidence_pct,
            "ai_result": ai_result,
        }
        return render(request, self.template_name, context)

    def _get_document(self, request, pk) -> AuditDocument:
        """Fetch document ensuring user can access it."""
        try:
            doc = AuditDocument.objects.prefetch_related("findings").get(pk=pk)
        except AuditDocument.DoesNotExist:
            raise Http404("المستند غير موجود.")

        # Access control: own document or same organization
        user_org = getattr(request.user, "organization", None)
        owns = doc.uploaded_by_id == request.user.pk
        same_org = (
            user_org is not None
            and doc.organization_id is not None
            and str(doc.organization_id) == str(user_org.pk)
        )
        if not (owns or same_org or request.user.is_staff):
            raise Http404("المستند غير موجود.")

        return doc
