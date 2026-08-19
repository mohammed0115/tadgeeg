from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.authentication.models import Organization
from apps.storage_management.exceptions import StorageConfigurationError
from apps.storage_management.services.backup_readiness import backup_destination_readiness


@pytest.mark.django_db
def test_backup_readiness_reports_unconfigured_destination_safely():
    org = Organization.objects.create(name="Backup readiness test")
    with patch(
        "apps.storage_management.services.backup_readiness.StorageResolver.get_provider",
        side_effect=StorageConfigurationError("No configured backup storage provider."),
    ):
        result = backup_destination_readiness(org)

    assert result == {
        "ready": False,
        "reason": "No configured backup storage provider.",
        "provider": None,
    }
