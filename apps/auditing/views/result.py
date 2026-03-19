"""Auditing Result View."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import render
from django.views import View

from ..selectors.document_selector import DocumentSelector


class AuditDocumentResultView(LoginRequiredMixin, View):
    template_name = "auditing/result.html"
    login_url = "/login/"

    def get(self, request, pk):
        document = DocumentSelector.get_user_document_by_id(request.user, pk)
        if not document:
            raise Http404

        # Pre-compute data for template
        ai_result = document.ai_result or {}
        extracted_data = ai_result.get("extracted_data", {})
        anomalies = ai_result.get("anomalies", [])
        validation_results = ai_result.get("validation_results", [])
        compliance_review = ai_result.get("compliance_review", {})
        recommendations = ai_result.get("recommendations", [])
        executive_summary = document.executive_summary or ai_result.get("executive_summary", "")

        # Confidence as percentage
        confidence = document.overall_confidence
        if confidence is not None:
            if confidence <= 1.0:
                confidence_pct = round(confidence * 100, 1)
            else:
                confidence_pct = round(confidence, 1)
        else:
            confidence_pct = 0.0

        context = {
            "document": document,
            "doc": document,  # alias for backward compat with existing template
            "ai_result": ai_result,
            "extracted_data": extracted_data,
            "anomalies": anomalies,
            "validation_results": validation_results,
            "compliance_review": compliance_review,
            "recommendations": recommendations,
            "executive_summary": executive_summary,
            "confidence_pct": confidence_pct,
            # Findings from DB grouped for template partials
            "anomaly_findings": list(document.findings.filter(finding_type="anomaly")),
            "validation_findings": list(document.findings.filter(finding_type="validation")),
            "compliance_findings": list(document.findings.filter(finding_type="compliance")),
            "recommendation_findings": list(document.findings.filter(finding_type="risk")),
        }
        return render(request, self.template_name, context)
