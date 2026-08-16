from io import BytesIO
from unittest.mock import Mock, patch

import pytest
from django.db import IntegrityError

from apps.authentication.models import Organization
from apps.storage_management.exceptions import StorageUploadError
from apps.storage_management.models import AuditFile, FileStorageMapping
from apps.storage_management.services.storage.service import StorageService


@pytest.mark.django_db
def test_upload_compensates_external_object_when_metadata_persistence_fails(admin_user):
    organization = Organization.objects.create(
        name="Storage Compensation Org",
        name_ar="منظمة تعويض التخزين",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
        vat_number="300000000000003",
    )
    admin_user.organization = organization
    admin_user.save(update_fields=["organization"])
    service = StorageService()
    file_obj = BytesIO(b"content")
    file_obj.name = "evidence.pdf"
    backend = Mock()
    backend.save.return_value = "org/evidence.pdf"
    provider = Mock()
    provider.name = "local"
    audit_file = Mock()
    audit_file.id = "audit-file-id"

    with patch.object(service, "_get_policy"), patch.object(service, "validate_file"), patch(
        "apps.storage_management.services.storage.service._resolver.get_backend", return_value=backend
    ), patch(
        "apps.storage_management.services.storage.service._resolver.get_provider", return_value=provider
    ), patch.object(AuditFile.objects, "create", return_value=audit_file), patch.object(
        FileStorageMapping.objects, "create", side_effect=IntegrityError("mapping failed")
    ):
        with pytest.raises(StorageUploadError, match="Metadata persistence failed"):
            service.upload_file(file_obj, organization, admin_user)

    backend.delete.assert_called_once_with("org/evidence.pdf")
    assert audit_file.status == AuditFile.Status.FAILED
