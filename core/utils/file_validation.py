"""
File Validation Utilities
Secure file upload handling with MIME type verification and content inspection.
"""

import os
import mimetypes
from pathlib import Path
from django.conf import settings
from rest_framework.exceptions import ValidationError

# Safe MIME types for financial documents
SAFE_MIME_TYPES = {
    'application/pdf': ['.pdf'],
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/png': ['.png'],
    'image/tiff': ['.tiff', '.tif'],
    'image/bmp': ['.bmp'],
    'image/webp': ['.webp'],
    'application/zip': ['.zip'],
    'text/csv': ['.csv'],
    'text/plain': ['.txt'],
    'application/json': ['.json'],
    'application/vnd.ms-excel': ['.xls'],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.macro-enabled.sheet': ['.xlsm'],
}

# Dangerous file signatures (magic bytes) to block
DANGEROUS_SIGNATURES = [
    (b'MZ', 'Windows executable'),  # .exe, .dll
    (b'\x7fELF', 'Linux executable'),  # ELF binary
    (b'\xca\xfe\xba\xbe', 'Mach-O binary'),  # macOS binary
    (b'#!/', 'Shell script'),  # Shebang
    (b'<?php', 'PHP script'),
    (b'<%', 'ASP script'),
    (b'<script', 'JavaScript injection'),
]

MAX_FILE_SIZE = getattr(settings, 'MAX_UPLOAD_SIZE', 50 * 1024 * 1024)  # 50 MB
MAX_ZIP_SIZE = getattr(settings, 'MAX_ZIP_FILE_SIZE', 200 * 1024 * 1024)  # 200 MB


def validate_file_extension(filename: str) -> str:
    """
    Validate file extension is in whitelist.
    
    Args:
        filename: Original filename from upload
        
    Returns:
        Sanitized lowercase extension
        
    Raises:
        ValidationError: If extension not allowed
    """
    ext = Path(filename).suffix.lower()
    
    allowed_extensions = []
    for extensions_list in SAFE_MIME_TYPES.values():
        allowed_extensions.extend(extensions_list)
    
    if ext not in allowed_extensions:
        raise ValidationError(
            f"File type '{ext}' not allowed. "
            f"Allowed types: {', '.join(sorted(set(allowed_extensions)))}"
        )
    
    return ext


def validate_file_size(file_size: int, is_zip: bool = False) -> None:
    """
    Validate file size is within limits.
    
    Args:
        file_size: File size in bytes
        is_zip: Whether this is a ZIP file
        
    Raises:
        ValidationError: If file too large
    """
    max_size = MAX_ZIP_SIZE if is_zip else MAX_FILE_SIZE
    
    if file_size > max_size:
        max_mb = max_size // (1024 * 1024)
        actual_mb = file_size / (1024 * 1024)
        raise ValidationError(
            f"File too large ({actual_mb:.1f} MB). "
            f"Maximum allowed: {max_mb} MB."
        )


def validate_mime_type(file_content: bytes, filename: str) -> str:
    """
    Validate MIME type by inspecting file content (magic bytes).
    
    Args:
        file_content: First 4KB of file (sufficient for magic byte detection)
        filename: Original filename
        
    Returns:
        Detected MIME type
        
    Raises:
        ValidationError: If MIME type doesn't match extension or is dangerous
    """
    ext = Path(filename).suffix.lower()
    
    # Check for dangerous file signatures
    for signature, description in DANGEROUS_SIGNATURES:
        if file_content.startswith(signature):
            raise ValidationError(
                f"File detected as {description}. This file type is not allowed."
            )
    
    # Detect MIME type from magic bytes
    detected_mime, _ = mimetypes.guess_type(filename)
    
    # Try python-magic if available for more accurate detection
    try:
        import magic
        mime_detector = magic.Magic(mime=True)
        detected_mime = mime_detector.from_buffer(file_content)
    except ImportError:
        # Fallback to simple detection
        magic_bytes = {
            b'%PDF': 'application/pdf',
            b'\xff\xd8\xff': 'image/jpeg',
            b'\x89PNG': 'image/png',
            b'GIF87a': 'image/gif',
            b'GIF89a': 'image/gif',
            b'BM': 'image/bmp',
            b'RIFF': 'audio/wav',  # Could also be WEBP
            b'PK\x03\x04': 'application/zip',
        }
        
        for magic_bytes_sig, mime in magic_bytes.items():
            if file_content.startswith(magic_bytes_sig):
                detected_mime = mime
                break
    
    # Validate detected MIME matches extension
    if detected_mime and ext in SAFE_MIME_TYPES.get(detected_mime, []):
        return detected_mime
    
    # If we have confidence it's a safe type, allow it
    if detected_mime in SAFE_MIME_TYPES:
        return detected_mime
    
    # Raise error if MIME mismatch or unknown
    raise ValidationError(
        f"File MIME type mismatch: extension '{ext}' "
        f"but content detected as '{detected_mime}'. "
        f"Please ensure file is genuinely a {ext} file."
    )


def validate_uploaded_file(file_obj, filename: str = None, check_content: bool = True) -> dict:
    """
    Comprehensive file validation combining extension, size, and content checks.
    
    Args:
        file_obj: Django UploadedFile object
        filename: Original filename (defaults to file_obj.name)
        check_content: Whether to inspect file content (slower but safer)
        
    Returns:
        {
            'filename': str,
            'extension': str,
            'size_bytes': int,
            'mime_type': str,
            'is_valid': bool
        }
        
    Raises:
        ValidationError: If any validation fails
    """
    filename = filename or file_obj.name
    file_size = file_obj.size
    
    # Step 1: Extension validation
    ext = validate_file_extension(filename)
    
    # Step 2: Size validation
    is_zip = ext.lower() == '.zip'
    validate_file_size(file_size, is_zip=is_zip)
    
    # Step 3: Content validation (magic bytes)
    mime_type = None
    if check_content:
        # Read first 4KB for magic byte detection
        file_obj.seek(0)
        file_header = file_obj.read(4096)
        file_obj.seek(0)
        
        mime_type = validate_mime_type(file_header, filename)
    else:
        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    
    return {
        'filename': filename,
        'extension': ext,
        'size_bytes': file_size,
        'mime_type': mime_type,
        'is_valid': True
    }
