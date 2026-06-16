"""Auditing Upload View."""

import io
import logging
import os
import zipfile

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View

from ..forms import AuditDocumentUploadForm
from ..repositories.document_repository import DocumentRepository
from ..selectors.document_selector import DocumentSelector
# Routed through V2 pipeline via compatibility adapter (Prompt 1.3 migration).
from apps.rule_engine.services.compatibility.legacy_audit_adapter import (
    LegacyAuditProcessingServiceAdapter as AuditProcessingService,
)
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
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        form = AuditDocumentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            # Surface the real validation error (bad extension, oversized,
            # empty/missing file, …) to AJAX clients as JSON instead of a
            # 200 HTML page the widget can only show as a generic failure.
            if is_ajax:
                flat_errors = [
                    f"{field}: {err}" if field != "__all__" else str(err)
                    for field, errs in form.errors.items()
                    for err in errs
                ]
                return JsonResponse(
                    {
                        "success": False,
                        "error": flat_errors[0] if flat_errors else "Invalid upload.",
                        "errors": flat_errors,
                    },
                    status=400,
                )
            recent = DocumentSelector.get_user_documents(request.user)[:5]
            return render(request, self.template_name, {"form": form, "recent": recent})

        uploaded_files = form.cleaned_data["file"]  # Now a list of files
        selected_type = (
            form.cleaned_data.get("selected_doc_type")
            or DocumentUploadRouter.AUTO_DETECT_TYPE
        )
        language = form.cleaned_data.get("doc_language") or "auto"

        router = DocumentUploadRouter()
        results = []
        processing_errors = []

        # Process each file (including extracting ZIPs)
        for f in uploaded_files:
            try:
                ext = os.path.splitext(f.name)[1].lower()

                if ext == '.zip':
                    zip_results = self._process_zip_upload(
                        f, selected_type, language, request.user, router
                    )
                    results.extend(zip_results)
                    if not zip_results:
                        processing_errors.append(
                            f"No processable files found inside {f.name}"
                        )
                    else:
                        for zr in zip_results:
                            if not zr.success and zr.error:
                                processing_errors.append(f"{f.name}: {zr.error}")
                else:
                    f.seek(0)
                    result = router.route(
                        uploaded_file=f,
                        document_type=selected_type,
                        user=request.user,
                        language=language,
                        organization=getattr(request.user, "organization", None),
                    )
                    results.append(result)

                    # Surface the real backend error instead of swallowing it.
                    # Without this, a routed failure (no organisation, invalid
                    # type, parser/OCR crash, processing exception, …) left
                    # processing_errors empty and the user only saw the generic
                    # "upload failed" message.
                    if not result.success and result.error:
                        processing_errors.append(f"{f.name}: {result.error}")
            except Exception as exc:
                logger.exception("Upload processing error for %s: %s", f.name, exc)
                processing_errors.append(f"Failed to process {f.name}: {str(exc)[:200]}")

        # Find first successful result to redirect to
        successful = [r for r in results if r.success]
        if successful:
            return redirect(successful[0].result_url)

        # All failed — surface the real cause. Fall back to any failed result's
        # error if no processing_errors were collected (defensive).
        recent = DocumentSelector.get_user_documents(request.user)[:5]
        if processing_errors:
            error_msg = processing_errors[0]
        else:
            failed_errors = [r.error for r in results if not r.success and r.error]
            error_msg = (
                failed_errors[0]
                if failed_errors
                else "Upload failed. Please check your files and try again."
            )

        # AJAX clients (the upload widgets) expect JSON so they can display the
        # actual error. Return HTTP 400 instead of a 200 HTML page so fetch()
        # treats it as a failure and reads payload.error.
        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "error": error_msg,
                    "errors": processing_errors,
                },
                status=400,
            )

        return render(request, self.template_name, {
            "form": form,
            "recent": recent,
            "error": error_msg,
            "upload_attempted": True,
        })
    
    def _process_zip_upload(self, zip_file, doc_type, language, user, router):
        """Extract ZIP and process each contained file."""
        results = []
        try:
            zip_file.seek(0)
            with zipfile.ZipFile(io.BytesIO(zip_file.read()), "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue

                    # Use basename to avoid path traversal and empty names
                    raw_name = os.path.basename(member.filename) or member.filename
                    name = raw_name.strip() or f"file_{member.header_offset}"
                    ext = os.path.splitext(name)[1].lower()

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
                        logger.error("Failed to process ZIP member %s: %s", name, e)
                        continue
        except zipfile.BadZipFile as e:
            logger.error("Bad ZIP file %s: %s", zip_file.name, e)
        except Exception as e:
            logger.exception("ZIP extraction failed for %s: %s", zip_file.name, e)

        return results
