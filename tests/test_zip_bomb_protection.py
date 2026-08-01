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


# One megabyte of zeros, reused for every streamed write. Allocated once.
_CHUNK = b"\0" * (1024 * 1024)


def _streamed_bomb(members, compression=zipfile.ZIP_DEFLATED):
    """Build a ZIP whose central directory *declares* huge members, without
    ever materialising them in the harness.

    ``members`` is a list of ``(name, megabytes)``.

    A protection test must never perform the attack it defends against. The
    original versions of the two tests below did exactly that — they built the
    decompressed payload as a Python string first (measured at 1.8 GB and
    2.1 GB per loop iteration), which is what OOM-killed the whole `tests/`
    run at ~8.8 GB RSS. The guard itself never expands anything: it reads the
    declared sizes from the central directory. So the archive only has to
    *declare* the size, and streaming zeros through ``ZipFile.open(..., "w")``
    declares it at roughly one chunk of resident memory.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, megabytes in members:
            with zf.open(name, "w") as dst:
                for _ in range(megabytes):
                    dst.write(_CHUNK)
    buf.seek(0)
    return buf


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
        """A member declaring more than the per-file limit must be rejected.

        `max_ratio` is deliberately permissive so that the *size* rule is the
        one under test: a compressed bomb also trips the ratio rule, and a test
        that could pass on either gives no signal about which one works.
        """
        zip_buffer = _streamed_bomb([("huge_file.bin", 600)])

        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(
                zip_buffer,
                max_file_size=500 * 1024 * 1024,
                max_ratio=10**9,
            )

        msg = str(exc_info.value).lower()
        assert "exceeds" in msg or "larger than" in msg
        assert "600 mb" in msg, f"the declared size should be named: {msg}"
        print(f"✓ Oversized file rejected: {exc_info.value}")

    def test_excessive_total_uncompressed_size_fails(self):
        """Members that are individually legal but collectively over the cap.

        Each member is 400 MB — under the 500 MB per-file limit — so the
        per-file rule cannot fire and the *total* rule is what must catch this.
        """
        zip_buffer = _streamed_bomb([(f"file_{i}.bin", 400) for i in range(3)])

        with pytest.raises(ZipValidationError) as exc_info:
            validate_zip_bomb(
                zip_buffer,
                max_file_size=500 * 1024 * 1024,
                max_total_size=1000 * 1024 * 1024,
                max_ratio=10**9,
            )

        msg = str(exc_info.value).lower()
        assert "exceed" in msg
        assert "total declared" in msg, (
            f"the total rule should be the one that fired, not per-file: {msg}"
        )
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


class TestGuardDoesNotExpandPayloads:
    """The guard must reject a bomb *without* expanding it — and this must be
    measured, not assumed.

    `tests/` could not complete on a 12 GB machine: the kernel OOM-killed it at
    ~8.8 GB RSS. The cause was not the guard but two tests in this file, which
    built the decompressed payload as a Python object before handing it over —
    performing the very attack they defend against. The guard itself peaks at
    ~16 MB on the same input because it reads declared sizes from the central
    directory (`core/services/zip_validator.py:156,181,188`).

    This test pins that property so the pattern cannot come back silently.
    """

    def test_guard_rejects_a_real_bomb_within_a_memory_ceiling(self):
        import subprocess
        import sys
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent
        # A subprocess is required: ru_maxrss is a per-process high-water mark,
        # so measuring in-process would inherit whatever earlier tests peaked at
        # and the ceiling would prove nothing.
        probe = """
import io, resource, sys, zipfile
sys.path.insert(0, %r)
from core.services.zip_validator import validate_zip_bomb, ZipValidationError

buf = io.BytesIO()
chunk = b"\\0" * (1024 * 1024)
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    with zf.open("bomb.bin", "w") as dst:
        for _ in range(2000):          # declares 2 GB
            dst.write(chunk)
buf.seek(0)
try:
    validate_zip_bomb(buf, max_file_size=500 * 1024 * 1024, max_ratio=10**9)
    print("NOT_REJECTED")
except ZipValidationError:
    print("REJECTED")
print(int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
""" % str(repo)

        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=300, cwd=str(repo),
        )
        assert out.returncode == 0, f"probe crashed: {out.stderr[-500:]}"
        verdict, peak_mb = out.stdout.split()
        peak_mb = int(peak_mb)

        assert verdict == "REJECTED", "a 2 GB declared member was not rejected"
        # The archive declares 2 GB. Anything near that means something expanded
        # it. 512 MB is generous headroom over the ~16 MB actually observed.
        assert peak_mb < 512, (
            f"guard peaked at {peak_mb} MB validating a 2 GB declared bomb — "
            f"something is expanding the payload instead of reading the "
            f"central directory"
        )
