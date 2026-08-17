from unittest.mock import patch

import pytest
from celery.exceptions import Retry

from apps.documents.models import BulkUploadJob
from apps.documents.tasks import process_bulk_upload_job


@pytest.mark.django_db
def test_bulk_upload_retries_transient_processing_failure(organization):
    job = BulkUploadJob.objects.create(
        organization=organization,
        source_filename="invoices.csv",
        source_format=BulkUploadJob.SourceFormat.CSV,
        summary={"stored_path": "bulk/invoices.csv"},
    )

    with patch("django.core.files.storage.default_storage.exists", return_value=True), patch(
        "django.core.files.storage.default_storage.open", side_effect=OSError("temporary storage outage")
    ), patch.object(process_bulk_upload_job, "retry", side_effect=Retry()) as retry:
        with pytest.raises(Retry):
            process_bulk_upload_job.run(str(job.id))

    job.refresh_from_db()
    assert job.status == BulkUploadJob.Status.PENDING
    assert "temporary storage outage" in job.summary["last_retry_error"]
    retry.assert_called_once()
