"""Auditing App Forms."""

import os
import hashlib
import logging

from django import forms

from .models import AuditDocument
from core.services.zip_validator import validate_zip_bomb, ZipValidationError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".xlsx", ".xls", ".csv", ".json", ".zip",
}
MAX_FILE_SIZE_MB = 50
SUSPICIOUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.sh', '.dll', '.so', '.app'}


class MultipleFileInput(forms.FileInput):
    """Custom file input that supports multiple files."""
    def __init__(self, attrs=None):
        super().__init__(attrs)
        if not self.attrs:
            self.attrs = {}
        self.attrs['multiple'] = True


def validate_zip_contents(file_obj):
    """Prevent ZIP bomb attacks using comprehensive validation."""
    if not file_obj.name.lower().endswith('.zip'):
        return
    
    try:
        file_obj.seek(0)
        validate_zip_bomb(file_obj)
    except ZipValidationError as e:
        raise forms.ValidationError(str(e))
    except Exception as e:
        raise forms.ValidationError(f"Error validating ZIP: {str(e)}")


def log_file_upload(file_obj, filename):
    """Log file upload with hash for audit trail."""
    try:
        file_obj.seek(0)
        file_hash = hashlib.sha256(file_obj.read()).hexdigest()
        logger.info(f"[Security] File uploaded: {filename} (size={file_obj.size}, hash={file_hash})")
    except Exception as e:
        logger.warning(f"[Security] Could not hash file {filename}: {e}")


class AuditDocumentUploadForm(forms.Form):
    file = forms.FileField(
        label="File",
        widget=MultipleFileInput(
            attrs={
                "accept": ".pdf,.jpg,.jpeg,.png,.tiff,.xlsx,.xls,.csv,.json,.zip",
            }
        ),
        required=True,
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

    def clean(self):
        """Validate all uploaded files (supports multiple)."""
        cleaned_data = super().clean()
        
        # Get all files directly from request
        files = self.files.getlist('file')
        if not files:
            raise forms.ValidationError("Please select at least one file.")
        
        validated_files = []
        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise forms.ValidationError(f"File type '{ext}' is not supported: {f.name}")
            if f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise forms.ValidationError(
                    f"File '{f.name}' exceeds {MAX_FILE_SIZE_MB}MB limit."
                )
            # Validate ZIP contents if it's a ZIP file
            if ext == '.zip':
                try:
                    validate_zip_contents(f)
                    f.seek(0)  # Reset after validation
                except forms.ValidationError:
                    raise  # Re-raise form validation errors
                except Exception as e:
                    raise forms.ValidationError(f"ZIP validation error: {str(e)}")
            
            # Log upload with hash
            log_file_upload(f, f.name)
            f.seek(0)
            validated_files.append(f)
        
        # Store validated files list in cleaned_data
        cleaned_data['file'] = validated_files
        return cleaned_data
