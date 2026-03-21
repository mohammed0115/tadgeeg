"""
Tests for ZIP Bomb Validation.

Run with:
    pytest tests/test_zip_bomb_protection.py -v
"""

import io
import zipfile
import pytest
from core.services.zip_validator import (
    validate_zip_bomb,
    validate_zip_bomb_silent,
    ZipValidationError,
)


class TestZipBombValidation:
    """Test decompression bomb protection."""

    def test_normal_zip_passes(self):
        """Normal, uncompressed ZIP should pass validation."""
        # Create a normal ZIP with a single text file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("readme.txt", "Hello World" * 100)  # ~1.1 KB
        
        zip_buffer.seek(0)
        result = validate_zip_bomb(zip_buffer)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["metadata"]["file_count"] == 1
        print(f"✓ Normal ZIP passed: {result['metadata']}")

    def test_corrupt_zip_fails(self):
        """Corrupt ZIP should be rejected."""
        bad_zip = io.BytesIO(b"This is not a ZIP file")
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(bad_zip)
        
        assert "Invalid or corrupt" in str(exc_info.value)
        print(f"✓ Corrupt ZIP rejected: {exc_info.value}")

    def test_suspicious_compression_ratio_fails(self):
        """ZIP with suspicious compression ratio should be rejected."""
        # Create a ZIP with highly repetitive data (highly compressible)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # A string of zeros with maximum compression
            zf.writestr("bomb.txt", "0" * (2 * 1024 * 1024))  # 2 MB of zeros
        
        zip_buffer.seek(0)
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(zip_buffer, max_ratio=100)
        
        assert "compression ratio" in str(exc_info.value).lower()
        print(f"✓ Suspicious compression rejected: {exc_info.value}")

    def test_oversized_uncompressed_file_fails(self):
        """ZIP with single file > limit should be rejected."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
            # Create a file larger than 500 MB limit (store, no compression)
            # We'll create a small marker and use the allowed limit
            large_content = "X" * (600 * 1024 * 1024)  # 600 MB
            zf.writestr("huge_file.txt", large_content)
        
        zip_buffer.seek(0)
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(zip_buffer, max_file_size=500 * 1024 * 1024)
        
        assert "exceeds" in str(exc_info.value).lower() or "larger than" in str(exc_info.value).lower()
        print(f"✓ Oversized file rejected: {exc_info.value}")

    def test_excessive_total_uncompressed_size_fails(self):
        """ZIP with total uncompressed size > limit should be rejected."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
            # Create multiple files totaling > 1 GB
            for i in range(3):
                content = f"File {i}\n" * (300 * 1024 * 1024)  # 300 MB each
                zf.writestr(f"file_{i}.txt", content)
        
        zip_buffer.seek(0)
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(zip_buffer, max_total_size=1000 * 1024 * 1024)
        
        assert "exceed" in str(exc_info.value).lower()
        print(f"✓ Excessive total size rejected: {exc_info.value}")

    def test_path_traversal_attack_fails(self):
        """ZIP with path traversal should be rejected."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious content")
        
        zip_buffer.seek(0)
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(zip_buffer)
        
        assert "traversal" in str(exc_info.value).lower()
        print(f"✓ Path traversal rejected: {exc_info.value}")

    def test_too_many_files_fails(self):
        """ZIP with too many files should be rejected."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            # Create 510 small files (exceeds 500 limit)
            for i in range(510):
                zf.writestr(f"file_{i:04d}.txt", f"Content {i}")
        
        zip_buffer.seek(0)
        
        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(zip_buffer, max_files=500)
        
        assert "exceeds" in str(exc_info.value).lower() or "contains" in str(exc_info.value).lower()
        print(f"✓ Too many files rejected: {exc_info.value}")

    def test_silent_validation_returns_tuple(self):
        """Silent validation should return (bool, str) tuple, not raise."""
        bad_zip = io.BytesIO(b"Not a ZIP")
        
        is_valid, error_msg = validate_zip_bomb_silent(bad_zip)
        
        assert is_valid is False
        assert isinstance(error_msg, str)
        assert len(error_msg) > 0
        print(f"✓ Silent validation returns tuple: ({is_valid}, '{error_msg}')")

    def test_silent_validation_passes_for_good_zip(self):
        """Silent validation should return (True, '') for good ZIP."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("good.txt", "This is fine")
        
        zip_buffer.seek(0)
        
        is_valid, error_msg = validate_zip_bomb_silent(zip_buffer)
        
        assert is_valid is True
        assert error_msg == ""
        print(f"✓ Silent validation passes for good ZIP")

    def test_warning_for_nested_zip(self):
        """Nested ZIP should generate warning (not error by default)."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            # Create nested ZIP
            nested = io.BytesIO()
            with zipfile.ZipFile(nested, "w") as nested_zf:
                nested_zf.writestr("inner.txt", "Inner content")
            zf.writestr("nested.zip", nested.getvalue())
        
        zip_buffer.seek(0)
        result = validate_zip_bomb(zip_buffer, allow_nesting=True)
        
        assert result["valid"] is True
        assert any("nested" in w.lower() for w in result["warnings"])
        assert result["metadata"]["has_nesting"] is True
        print(f"✓ Nested ZIP generates warning: {result['warnings']}")

    def test_metadata_tracking(self):
        """Validation should track metadata."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("file_a.txt", "A" * 100)
            zf.writestr("file_b.txt", "B" * 200)
        
        zip_buffer.seek(0)
        result = validate_zip_bomb(zip_buffer)
        
        meta = result["metadata"]
        assert meta["file_count"] == 2
        assert meta["total_uncompressed"] == 300
        assert meta["max_ratio"] >= 0
        assert meta["has_nesting"] is False
        print(f"✓ Metadata tracked correctly: {meta}")


class TestZipValidationIntegration:
    """Integration tests with form validation."""

    def test_form_validation_calls_validator(self):
        """Test that forms.validate_zip_contents uses the new validator."""
        from apps.auditing.forms import validate_zip_contents
        from django.forms import ValidationError
        
        # Good ZIP
        good_zip = io.BytesIO()
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("document.txt", "Valid content")
        good_zip.seek(0)
        good_zip.name = "docs.zip"
        
        # Should not raise
        try:
            validate_zip_contents(good_zip)
            print("✓ Form validation passes for good ZIP")
        except ValidationError:
            pytest.fail("Good ZIP should not raise ValidationError")
        
        # Bad ZIP (corrupt)
        bad_zip = io.BytesIO(b"Not a ZIP")
        bad_zip.name = "corrupt.zip"
        
        # Should raise ValidationError
        with pytest.raises(ValidationError):
            validate_zip_contents(bad_zip)
        print("✓ Form validation rejects corrupt ZIP")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
