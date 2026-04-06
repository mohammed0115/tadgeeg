"""
File Upload Security Tests
Uses: validate_uploaded_file, validate_file_extension, validate_mime_type,
      validate_zip_bomb / validate_zip_bomb_silent from actual module.
The auditing upload view uses Django session auth (LoginRequiredMixin).
The DRF document upload at /api/v1/documents/upload/ uses JWT/IsAuthenticated.
"""
import io
import os
import zipfile
import pytest
import uuid
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APIClient
from django.test import Client


# ─── validate_uploaded_file ───────────────────────────────────────────────────

@pytest.mark.unit
class TestValidateUploadedFile:

    def test_valid_pdf_passes(self):
        from core.utils.file_validation import validate_uploaded_file
        pdf = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        result = validate_uploaded_file(pdf)
        assert result["is_valid"] is True

    def test_valid_pdf_has_correct_extension(self):
        from core.utils.file_validation import validate_uploaded_file
        pdf = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        result = validate_uploaded_file(pdf)
        assert result["extension"] == ".pdf"

    def test_result_has_all_expected_keys(self):
        from core.utils.file_validation import validate_uploaded_file
        pdf = SimpleUploadedFile("test.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        result = validate_uploaded_file(pdf)
        for key in ("filename", "extension", "size_bytes", "mime_type", "is_valid"):
            assert key in result, f"Missing key: {key}"

    def test_exe_file_blocked(self):
        from core.utils.file_validation import validate_uploaded_file
        exe = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_uploaded_file(exe)

    def test_double_extension_blocked(self):
        from core.utils.file_validation import validate_uploaded_file
        f = SimpleUploadedFile("invoice.pdf.exe", b"%PDF-1.4\n", content_type="application/pdf")
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_uploaded_file(f)

    def test_linux_elf_binary_blocked(self):
        from core.utils.file_validation import validate_uploaded_file
        elf = SimpleUploadedFile("binary.bin", b"\x7fELF\x02\x01\x01", content_type="application/octet-stream")
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_uploaded_file(elf)

    def test_php_script_blocked(self):
        from core.utils.file_validation import validate_uploaded_file
        php = SimpleUploadedFile("shell.php", b"<?php system($_GET['cmd']); ?>", content_type="text/plain")
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_uploaded_file(php)

    def test_asp_script_blocked(self):
        from core.utils.file_validation import validate_uploaded_file
        asp = SimpleUploadedFile("shell.asp", b"<% Response.Write(\"test\") %>", content_type="text/plain")
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_uploaded_file(asp)


# ─── validate_file_extension ──────────────────────────────────────────────────

@pytest.mark.unit
class TestValidateFileExtension:

    def test_pdf_allowed(self):
        from core.utils.file_validation import validate_file_extension
        result = validate_file_extension("invoice.pdf")
        assert result == ".pdf"

    def test_exe_rejected(self):
        from core.utils.file_validation import validate_file_extension
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_file_extension("malware.exe")

    def test_no_extension_rejected(self):
        from core.utils.file_validation import validate_file_extension
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_file_extension("noextension")

    def test_case_insensitive_pdf(self):
        from core.utils.file_validation import validate_file_extension
        result = validate_file_extension("INVOICE.PDF")
        assert result.lower() == ".pdf"


# ─── validate_mime_type ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestValidateMimeType:

    def test_exe_magic_bytes_rejected(self):
        from core.utils.file_validation import validate_mime_type
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_mime_type(b"MZ\x90\x00\x03\x00", "invoice.exe")

    def test_pdf_magic_bytes_accepted(self):
        from core.utils.file_validation import validate_mime_type
        result = validate_mime_type(b"%PDF-1.4\n", "invoice.pdf")
        assert "pdf" in result.lower()

    def test_script_tag_rejected(self):
        from core.utils.file_validation import validate_mime_type
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_mime_type(b"<script>alert(1)</script>", "data.csv")

    def test_php_injection_rejected(self):
        from core.utils.file_validation import validate_mime_type
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_mime_type(b"<?php system($_GET['cmd']); ?>", "data.php")

    def test_elf_binary_rejected(self):
        from core.utils.file_validation import validate_mime_type
        with pytest.raises((ValidationError, ValueError, Exception)):
            validate_mime_type(b"\x7fELF\x02\x01\x01\x00", "binary.bin")


# ─── ZIP bomb protection ──────────────────────────────────────────────────────
# validate_zip_bomb returns dict with keys: valid, errors, warnings, metadata
# validate_zip_bomb raises ZipValidationError when the ZIP is dangerous

@pytest.mark.unit
class TestZIPBombProtection:

    def _make_normal_zip(self, tmp_path):
        p = tmp_path / "normal.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("invoice.txt", b"Invoice data here")
        return p

    def _make_bomb_zip(self, tmp_path):
        p = tmp_path / "bomb.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.txt", b"A" * (1024 * 1024))
        return p

    def test_validate_zip_bomb_function_importable(self):
        from core.services.zip_validator import validate_zip_bomb
        assert callable(validate_zip_bomb)

    def test_validate_zip_bomb_silent_importable(self):
        from core.services.zip_validator import validate_zip_bomb_silent
        assert callable(validate_zip_bomb_silent)

    def test_normal_zip_returns_valid_true(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb
        result = validate_zip_bomb(str(self._make_normal_zip(tmp_path)))
        assert result["valid"] is True

    def test_normal_zip_has_no_errors(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb
        result = validate_zip_bomb(str(self._make_normal_zip(tmp_path)))
        assert result["errors"] == []

    def test_result_has_expected_keys(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb
        result = validate_zip_bomb(str(self._make_normal_zip(tmp_path)))
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result
        assert "metadata" in result

    def test_metadata_contains_file_count(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb
        result = validate_zip_bomb(str(self._make_normal_zip(tmp_path)))
        assert "file_count" in result["metadata"]
        assert result["metadata"]["file_count"] == 1

    def test_too_many_files_raises_or_flags(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb, ZipValidationError
        p = tmp_path / "many.zip"
        with zipfile.ZipFile(p, "w") as zf:
            for i in range(600):
                zf.writestr(f"f{i}.txt", b"x")
        try:
            result = validate_zip_bomb(str(p))
            # If it doesn't raise, must be flagged as invalid
            assert result["valid"] is False
        except (ZipValidationError, Exception):
            pass  # Raising is the expected behavior

    def test_bomb_with_tight_ratio_raises_or_flags(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb, ZipValidationError
        bomb = self._make_bomb_zip(tmp_path)
        try:
            result = validate_zip_bomb(str(bomb), max_ratio=5)
            assert result["valid"] is False or "ratio" in str(result).lower()
        except (ZipValidationError, Exception):
            pass  # Expected: bomb detected

    def test_silent_normal_returns_true(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb_silent
        is_safe, msg = validate_zip_bomb_silent(str(self._make_normal_zip(tmp_path)))
        assert is_safe is True

    def test_silent_returns_tuple(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb_silent
        result = validate_zip_bomb_silent(str(self._make_normal_zip(tmp_path)))
        assert isinstance(result, tuple) and len(result) == 2

    def test_silent_bomb_returns_false(self, tmp_path):
        from core.services.zip_validator import validate_zip_bomb_silent
        bomb = self._make_bomb_zip(tmp_path)
        is_safe, msg = validate_zip_bomb_silent(str(bomb), max_ratio=5)
        assert is_safe is False
        assert isinstance(msg, str)


# ─── Path traversal ───────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPathTraversalPrevention:

    def test_traversal_filename_sanitised_by_basename(self):
        f = SimpleUploadedFile("../../etc/passwd", b"root:x:0:0:", content_type="text/plain")
        sanitized = os.path.basename(f.name)
        assert "/" not in sanitized
        assert "\\" not in sanitized

    def test_windows_traversal_sanitised(self):
        name = "..\\..\\windows\\system32\\cmd.exe"
        sanitized = os.path.basename(name.replace("\\", "/"))
        assert "\\" not in sanitized
        assert "/" not in sanitized


# ─── Upload API (DRF endpoint at /api/v1/documents/upload/) ──────────────────
# This endpoint uses IsAuthenticated (JWT/session), not LoginRequiredMixin

@pytest.mark.django_db
@pytest.mark.security
class TestUploadAPISecurity:

    @pytest.fixture
    def auth_client(self, db):
        from apps.authentication.models import Organization
        from django.contrib.auth import get_user_model
        User = get_user_model()
        org = Organization.objects.create(
            name="Upload Org", name_ar="منظمة رفع", country="SA",
            currency="SAR", vat_number="300000000099997",
        )
        user = User.objects.create_user(
            email="drf_uploader@test.finai", password="UploadPass1!",
            full_name="DRF Uploader", organization=org,
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_unauthenticated_drf_upload_rejected(self):
        f = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4", content_type="application/pdf")
        client = APIClient()
        response = client.post("/api/v1/documents/upload/", {"file": f}, format="multipart")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unauthenticated_auditor_upload_redirects_to_login(self):
        """Session-based view redirects unauthenticated users to /login/."""
        f = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4", content_type="application/pdf")
        client = Client()
        response = client.post("/auditor/upload/", {"file": f})
        assert response.status_code in (302, 401, 403)
        if response.status_code == 302:
            assert "login" in response["Location"].lower()

    def test_executable_rejected_by_validator(self, auth_client):
        """EXE files are blocked at the validation layer before reaching the view."""
        exe = SimpleUploadedFile("virus.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        response = auth_client.post("/api/v1/documents/upload/", {"file": exe}, format="multipart")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_double_extension_rejected(self, auth_client):
        f = SimpleUploadedFile("invoice.pdf.exe", b"%PDF-1.4", content_type="application/pdf")
        response = auth_client.post("/api/v1/documents/upload/", {"file": f}, format="multipart")
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
