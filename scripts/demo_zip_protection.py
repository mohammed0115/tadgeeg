#!/usr/bin/env python
"""
ZIP Bomb Protection Demo

Demonstrates the hardening working correctly.

Usage:
    python scripts/demo_zip_protection.py

This script creates test ZIPs and validates them using the new protection.
"""

import io
import os
import sys
import zipfile
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.services.zip_validator import (
    validate_zip_bomb,
    validate_zip_bomb_silent,
    ZipValidationError,
)


def create_normal_zip():
    """Create a normal, safe ZIP file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("document1.pdf", b"PDF Header..." + b"\x00" * 1000)
        zf.writestr("document2.txt", "Invoice\n" * 200)
    buf.seek(0)
    return buf


def create_corrupt_zip():
    """Create a corrupt ZIP file."""
    return io.BytesIO(b"This is not a valid ZIP file")


def create_suspicious_compression_zip():
    """Create a ZIP with suspiciously high compression ratio."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # All zeros compress VERY well (160:1+ ratio)
        zf.writestr("bomb.txt", "0" * (2 * 1024 * 1024))
    buf.seek(0)
    return buf


def create_path_traversal_zip():
    """Create a ZIP with path traversal attack."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../etc/passwd", "malicious")
    buf.seek(0)
    return buf


def test_case(name, zip_creator, should_pass=True):
    """Run a single test case."""
    print(f"\n{'='*70}")
    print(f"Test: {name}")
    print('='*70)
    
    try:
        zip_file = zip_creator()
        is_valid, error = validate_zip_bomb_silent(zip_file)
        
        if should_pass:
            if is_valid:
                print(f"✓ PASS: ZIP was correctly accepted")
                return True
            else:
                print(f"✗ FAIL: ZIP should have passed but was rejected")
                print(f"  Error: {error}")
                return False
        else:
            if not is_valid:
                print(f"✓ PASS: ZIP was correctly rejected")
                print(f"  Reason: {error}")
                return True
            else:
                print(f"✗ FAIL: ZIP should have been rejected but was accepted")
                return False
                
    except Exception as e:
        print(f"✗ EXCEPTION: {e}")
        return False


def main():
    """Run all test cases."""
    print("\n" + "="*70)
    print("ZIP BOMB PROTECTION DEMO")
    print("="*70)
    
    results = []
    
    # Test 1: Normal ZIP
    results.append(test_case(
        "Normal ZIP with multiple documents",
        create_normal_zip,
        should_pass=True
    ))
    
    # Test 2: Corrupt ZIP
    results.append(test_case(
        "Corrupt ZIP (not a real ZIP file)",
        create_corrupt_zip,
        should_pass=False
    ))
    
    # Test 3: Suspicious compression
    results.append(test_case(
        "ZIP with suspicious compression ratio (bomb)",
        create_suspicious_compression_zip,
        should_pass=False
    ))
    
    # Test 4: Path traversal
    results.append(test_case(
        "ZIP with path traversal attack",
        create_path_traversal_zip,
        should_pass=False
    ))
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\n✓ All tests passed! ZIP bomb protection is working correctly.")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
