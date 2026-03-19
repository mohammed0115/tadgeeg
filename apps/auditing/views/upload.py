"""Auditing Upload View."""

import logging
import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from ..forms import AuditDocumentUploadForm
from ..models import AuditDocument
from ..repositories.document_repository import DocumentRepository
from ..selectors.document_selector import DocumentSelector
from ..services.audit_processing_service import AuditProcessingService

logger = logging.getLogger(__name__)


class AuditDocumentUploadView(LoginRequiredMixin, View):
    template_name = "auditing/upload.html"
    login_url = "/login/"

    def get(self, request):
        initial = {}
        doc_type = request.GET.get("type", "")
        if doc_type:
            initial["selected_doc_type"] = doc_type
        form = AuditDocumentUploadForm(initial=initial)
        recent = DocumentSelector.get_user_documents(request.user)[:5]
        return render(request, self.template_name, {
            "form": form,
            "recent": recent,
            "preselected_type": doc_type,
        })

    def post(self, request):
        form = AuditDocumentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            recent = DocumentSelector.get_user_documents(request.user)[:5]
            return render(request, self.template_name, {"form": form, "recent": recent})

        uploaded_file = form.cleaned_data["file"]
        selected_type = (
            form.cleaned_data.get("selected_doc_type") or AuditDocument.DocumentType.OTHER
        )
        language = form.cleaned_data.get("language") or "auto"

        document = DocumentRepository.create(
            uploaded_by=request.user,
            file=uploaded_file,
            original_name=uploaded_file.name,
            selected_doc_type=selected_type,
            language=language,
        )

        try:
            service = AuditProcessingService()
            service.process(document)
        except Exception as exc:
            logger.exception("Audit processing failed for document %s", document.pk)

        return redirect("auditor:result", pk=document.pk)
