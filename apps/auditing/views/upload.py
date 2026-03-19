"""Auditing Upload View."""

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from ..forms import AuditDocumentUploadForm
from ..models import AuditDocument
from ..repositories.document_repository import DocumentRepository
from ..selectors.document_selector import DocumentSelector
from ..services.audit_processing_service import AuditProcessingService
from core.services.upload_router import DocumentUploadRouter

logger = logging.getLogger(__name__)

# Document types that must go through the invoice pipeline so they
# appear in /invoices/ with full 30-rule validation + ZATCA compliance.
INVOICE_TYPES = {"invoice"}


class AuditDocumentUploadView(LoginRequiredMixin, View):
    template_name = "auditing/upload.html"
    login_url = "/login/"

    def get(self, request):
        doc_type = request.GET.get("type", "")
        initial = {"selected_doc_type": doc_type} if doc_type else {}
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
        selected_type = form.cleaned_data.get("selected_doc_type") or AuditDocument.DocumentType.OTHER
        language = form.cleaned_data.get("language") or "auto"

        # ── Route through DocumentUploadRouter ──────────────────────────────
        # Invoice → invoice pipeline → /invoices/<pk>/
        # Other typed docs → typed document pipeline → /documents/<type>/<pk>/
        # Users without org → AI Auditor fallback → /auditor/result/<pk>/
        router = DocumentUploadRouter()
        result = router.route(
            uploaded_file=uploaded_file,
            document_type=selected_type,
            user=request.user,
            language=language,
            organization=getattr(request.user, "organization", None),
        )
        return redirect(result.result_url)
