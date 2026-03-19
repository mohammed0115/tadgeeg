"""Auditing App Forms."""

import os

from django import forms

from .models import DOC_TYPE_CHOICES


LANGUAGE_CHOICES = [
    ("auto", "Auto Detect / كشف تلقائي"),
    ("ar", "Arabic / العربية"),
    ("en", "English / الإنجليزية"),
]


class AuditDocumentUploadForm(forms.Form):
    """Form for uploading a financial document for AI auditing."""

    ALLOWED_EXTENSIONS = {
        ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
        ".xlsx", ".xls", ".csv", ".json", ".zip",
    }
    MAX_SIZE_MB = 50

    file = forms.FileField(
        label="الملف",
        widget=forms.ClearableFileInput(attrs={"class": "hidden", "id": "id_file"}),
        help_text=f"الحد الأقصى {MAX_SIZE_MB} ميجابايت. الصيغ المدعومة: PDF، صور، Excel، CSV، JSON، ZIP",
    )

    selected_doc_type = forms.ChoiceField(
        choices=DOC_TYPE_CHOICES,
        initial="auto",
        label="نوع المستند",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    language = forms.ChoiceField(
        choices=LANGUAGE_CHOICES,
        initial="auto",
        label="اللغة",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if not uploaded_file:
            raise forms.ValidationError("يرجى اختيار ملف.")

        # Validate extension
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(self.ALLOWED_EXTENSIONS))
            raise forms.ValidationError(
                f"نوع الملف '{ext}' غير مدعوم. الصيغ المقبولة: {allowed}"
            )

        # Validate size
        max_bytes = self.MAX_SIZE_MB * 1024 * 1024
        if uploaded_file.size > max_bytes:
            raise forms.ValidationError(
                f"حجم الملف ({uploaded_file.size / (1024 * 1024):.1f} ميجابايت) "
                f"يتجاوز الحد الأقصى المسموح به ({self.MAX_SIZE_MB} ميجابايت)."
            )

        return uploaded_file
