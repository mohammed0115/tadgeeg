"""Tests for auditing app views."""

import io
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.auditing.models import AuditDocument

User = get_user_model()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="testuser",
        password="testpass123",
        email="test@example.com",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="otheruser",
        password="otherpass123",
        email="other@example.com",
    )


@pytest.fixture
def authenticated_client(client, user):
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def sample_document(db, user):
    return AuditDocument.objects.create(
        uploaded_by=user,
        original_name="sample.pdf",
        selected_doc_type=AuditDocument.DocumentType.INVOICE,
        status=AuditDocument.Status.COMPLETED,
        overall_confidence=0.85,
        overall_risk_level="low",
    )


@pytest.fixture
def other_document(db, other_user):
    return AuditDocument.objects.create(
        uploaded_by=other_user,
        original_name="other.pdf",
        status=AuditDocument.Status.COMPLETED,
    )


class TestUploadView:
    def test_unauthenticated_get_redirects_to_login(self, client):
        url = reverse("auditor:upload")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_authenticated_get_returns_200(self, authenticated_client):
        url = reverse("auditor:upload")
        response = authenticated_client.get(url)
        assert response.status_code == 200

    def test_upload_page_contains_form(self, authenticated_client):
        url = reverse("auditor:upload")
        response = authenticated_client.get(url)
        assert b"file" in response.content or b"form" in response.content.lower()


class TestResultView:
    def test_unauthenticated_get_redirects_to_login(self, client, sample_document):
        url = reverse("auditor:result", kwargs={"pk": sample_document.pk})
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_authenticated_own_document_returns_200(self, authenticated_client, sample_document):
        url = reverse("auditor:result", kwargs={"pk": sample_document.pk})
        response = authenticated_client.get(url)
        assert response.status_code == 200

    def test_other_users_document_returns_404(self, authenticated_client, other_document):
        url = reverse("auditor:result", kwargs={"pk": other_document.pk})
        response = authenticated_client.get(url)
        assert response.status_code == 404

    def test_nonexistent_document_returns_404(self, authenticated_client):
        url = reverse("auditor:result", kwargs={"pk": uuid.uuid4()})
        response = authenticated_client.get(url)
        assert response.status_code == 404

    def test_result_page_shows_document_name(self, authenticated_client, sample_document):
        url = reverse("auditor:result", kwargs={"pk": sample_document.pk})
        response = authenticated_client.get(url)
        assert b"sample.pdf" in response.content


class TestHistoryView:
    def test_unauthenticated_get_redirects_to_login(self, client):
        url = reverse("auditor:history")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_authenticated_get_returns_200(self, authenticated_client):
        url = reverse("auditor:history")
        response = authenticated_client.get(url)
        assert response.status_code == 200

    def test_history_shows_own_documents_only(self, authenticated_client, sample_document, other_document):
        url = reverse("auditor:history")
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert b"sample.pdf" in response.content
        assert b"other.pdf" not in response.content

    def test_history_pagination(self, authenticated_client, user):
        # Create more than PAGE_SIZE documents
        docs = [
            AuditDocument(
                uploaded_by=user,
                original_name=f"doc_{i}.pdf",
                status=AuditDocument.Status.COMPLETED,
            )
            for i in range(25)
        ]
        AuditDocument.objects.bulk_create(docs)
        url = reverse("auditor:history")
        response = authenticated_client.get(url)
        assert response.status_code == 200
