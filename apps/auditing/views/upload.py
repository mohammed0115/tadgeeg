"""Auditing Upload View."""

import io
import logging
import os
import zipfile

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from ..forms import AuditDocumentUploadForm
from ..models import AuditDocument
from ..repositories.document_repository import DocumentRepository
from ..selectors.document_selector import DocumentSelector
from ..services.audit_processing_service import AuditProcessingService
from core.services.upload_router import DocumentUploadRouter
from core.services.zip_validator import validate_zip_bomb_silent

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

        uploaded_files = form.cleaned_data["file"]  # Now a list of files
        selected_type = form.cleaned_data.get("selected_doc_type") or AuditDocument.DocumentType.OTHER
        language = form.cleaned_data.get("language") or "auto"

        router = DocumentUploadRouter()
        results = []
        
        # Process each file (including extracting ZIPs)
        for f in uploaded_files:
            ext = os.path.splitext(f.name)[1].lower()
            
            # If ZIP, extract and process each file
            if ext == '.zip':
                results.extend(self._process_zip_upload(
                    f, selected_type, language, request.user, router
                ))
            else:
                # Single file processing
                f.seek(0)
                result = router.route(
                    uploaded_file=f,
                    document_type=selected_type,
                    user=request.user,
                    language=language,
                    organization=getattr(request.user, "organization", None),
                )
                results.append(result)
        
        # Redirect to first result, or upload page if all failed
        if results and results[0].success:
            return redirect(results[0].result_url)
        else:
            recent = DocumentSelector.get_user_documents(request.user)[:5]
            return render(request, self.template_name, {
                "form": form,
                "recent": recent,
                "error": "Upload failed. Please try again."
            })
    
    def _process_zip_upload(self, zip_file, doc_type, language, user, router):
        """Extract ZIP and process each contained file."""
        results = []
        try:
            zip_file.seek(0)
            # ZIP was already validated in form.clean_file()
            with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    
                    name = os.path.basename(member.filename)
                    ext = os.path.splitext(name)[1].lower()
                    
                    # Skip unsupported file types inside ZIP
                    if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", 
                                   ".xlsx", ".xls", ".csv", ".json"}:
                        continue
                    
                    try:
                        data = zf.read(member)
                        file_like = io.BytesIO(data)
                        file_like.name = name
                        file_like.size = len(data)
                        
                        result = router.route(
                            uploaded_file=file_like,
                            document_type=doc_type,
                            user=user,
                            language=language,
                            organization=getattr(user, "organization", None),
                        )
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Failed to process ZIP member {name}: {e}")
                        continue
        except zipfile.BadZipFile as e:
            logger.error(f"Bad ZIP file {zip_file.name}: {e}")
        except Exception as e:
            logger.error(f"ZIP extraction failed: {e}")
        
        return results
