"""Auditing Upload View."""

import logging
import mimetypes
import os

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from apps.auditing.forms import AuditDocumentUploadForm
from apps.auditing.models import AuditDocument
from apps.auditing.repositories.document_repository import DocumentRepository
from apps.auditing.services.audit_processing_service import AuditProcessingService

logger = logging.getLogger(__name__)


class AuditDocumentUploadView(LoginRequiredMixin, View):
    """Handle financial document uploads for AI auditing."""

    login_url = "/login/"
    template_name = "auditing/upload.html"

    def get(self, request):
        form = AuditDocumentUploadForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = AuditDocumentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        uploaded_file = form.cleaned_data["file"]
        selected_doc_type = form.cleaned_data.get("selected_doc_type", "auto")
        language = form.cleaned_data.get("language", "auto")

        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(uploaded_file.name)
        mime_type = mime_type or "application/octet-stream"

        # Get organization from user
        organization = getattr(request.user, "organization", None)

        # Create document record
        repo = DocumentRepository()
        document = repo.create(
            uploaded_by=request.user,
            organization=organization,
            file=uploaded_file,
            original_name=uploaded_file.name,
            mime_type=mime_type,
            file_size=uploaded_file.size,
            selected_doc_type=selected_doc_type or "auto",
            language=language or "auto",
            status=AuditDocument.Status.PENDING,
        )

        # Run the audit pipeline synchronously
        try:
            service = AuditProcessingService()
            document = service.process(document)
        except Exception as exc:
            logger.exception("Audit processing failed for document %s: %s", document.pk, exc)

        return redirect("auditing:result", pk=document.pk)
