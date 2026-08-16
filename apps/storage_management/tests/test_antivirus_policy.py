from io import BytesIO
from unittest.mock import patch

import pytest

from apps.storage_management.exceptions import StorageValidationError
from apps.storage_management.services.storage.service import StorageService


class _Policy:
    max_file_size_mb = 10
    allowed_extensions = []
    allowed_mime_types = []
    antivirus_scan_enabled = True


def test_antivirus_required_fails_closed_when_scanner_is_missing():
    service = StorageService()
    with patch("apps.storage_management.services.storage.service.subprocess.run", side_effect=OSError):
        with pytest.raises(StorageValidationError, match="required but unavailable"):
            service.validate_file(BytesIO(b"test"), _Policy(), name="test.pdf", mime="application/pdf")
