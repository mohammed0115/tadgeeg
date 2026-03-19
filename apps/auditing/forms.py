"""Auditing App Forms."""

import os

from django import forms

from .models import AuditDocument

ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".xlsx", ".xls", ".csv", ".json", ".zip",
}
MAX_FILE_SIZE_MB = 50


class AuditDocumentUploadForm(forms.Form):
    file = forms.FileField(
        label="File",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".pdf,.jpg,.jpeg,.png,.tiff,.xlsx,.xls,.csv,.json,.zip",
            }
        ),
    )
    selected_doc_type = forms.ChoiceField(
        choices=[("", "Auto Detect")] + AuditDocument.DocumentType.choices,
        required=False,
        label="Document Type",
    )
    language = forms.ChoiceField(
        choices=[
            ("auto", "Auto"),
            ("ar", "Arabic"),
            ("en", "English"),
            ("ar-en", "Bilingual"),
        ],
        required=False,
        initial="auto",
        label="Language",
    )

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            return f
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError(f"File type '{ext}' is not supported.")
        if f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise forms.ValidationError(
                f"File size exceeds {MAX_FILE_SIZE_MB}MB limit."
            )
        return f
