from __future__ import annotations

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.authentication.models import Organization
from apps.documents.models import Document

User = get_user_model()


def _org() -> Organization:
    return Organization.objects.create(
        name="Analyse request tenant",
        name_ar="منظمة طلب التحليل",
        country="SA",
        currency="SAR",
        vat_number="300000000000201",
    )


@pytest.mark.django_db
def test_document_analyse_second_click_is_cached_and_does_not_enqueue_twice(monkeypatch):
    from apps.documents import tasks

    org = _org()
    user = User.objects.create_user(
        email="analyse-request@example.test",
        password="StrongPass1!",
        full_name="Analyse Request",
        role=User.Role.SENIOR_AUDITOR,
        organization=org,
    )
    document = Document.objects.create(
        organization=org,
        uploaded_by=user,
        file=SimpleUploadedFile("request.pdf", b"%PDF-1.4", content_type="application/pdf"),
        original_filename="request.pdf",
        file_size=1_200_000,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )
    queued: list[str] = []

    def _capture_delay(document_id: str):
        queued.append(document_id)

    monkeypatch.setattr(tasks.process_document_task, "delay", _capture_delay)
    client = APIClient()
    client.force_authenticate(user)
    url = f"/api/v1/documents/{document.id}/analyse/"

    first = client.post(url, {}, format="json")
    second = client.post(url, {}, format="json")

    assert first.status_code == 202
    assert first.data["cached"] is False
    assert first.data["analysis_request_id"]
    assert second.status_code == 202
    assert second.data["cached"] is True
    assert second.data["analysis_request_id"]
    assert queued == [str(document.id)]
