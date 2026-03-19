"""Tests for the auditing upload view."""

import io
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.auditing.models import AuditDocument

User = get_user_model()


def _make_pdf_bytes() -> bytes:
    """Return minimal valid PDF-like bytes for testing."""
    return b"%PDF-1.4 test content for upload"


def _make_excel_bytes() -> bytes:
    """Return placeholder bytes for Excel test."""
    return b"PK\x03\x04" + b"\x00" * 20  # Minimal ZIP-like header (xlsx is a zip)


class AuditDocumentUploadViewTests(TestCase):
    """Tests for AuditDocumentUploadView."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="auditor@example.com",
            password="Str0ngP@ssw0rd!",
            full_name="Test Auditor",
        )
        self.upload_url = reverse("auditor:upload")

    def test_unauthenticated_get_redirects_to_login(self):
        response = self.client.get(self.upload_url)
        self.assertIn(response.status_code, [301, 302])
        self.assertIn("/login/", response["Location"])

    def test_authenticated_get_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auditing/upload.html")

    def test_upload_form_in_context(self):
        self.client.force_login(self.user)
        response = self.client.get(self.upload_url)
        self.assertIn("form", response.context)

    def test_post_without_file_shows_form_error(self):
        self.client.force_login(self.user)
        response = self.client.post(self.upload_url, {
            "selected_doc_type": "auto",
            "language": "auto",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auditing/upload.html")

    def test_post_with_invalid_extension_shows_error(self):
        self.client.force_login(self.user)
        bad_file = SimpleUploadedFile("document.docx", b"content", content_type="application/msword")
        response = self.client.post(self.upload_url, {
            "file": bad_file,
            "selected_doc_type": "auto",
            "language": "auto",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auditing/upload.html")
        form = response.context.get("form")
        self.assertIsNotNone(form)
        self.assertIn("file", form.errors)

    def test_post_with_oversized_file_shows_error(self):
        self.client.force_login(self.user)
        # 51 MB file
        big_file = SimpleUploadedFile(
            "big.pdf",
            b"x" * (51 * 1024 * 1024),
            content_type="application/pdf",
        )
        response = self.client.post(self.upload_url, {
            "file": big_file,
            "selected_doc_type": "auto",
            "language": "auto",
        })
        self.assertEqual(response.status_code, 200)
        form = response.context.get("form")
        self.assertIsNotNone(form)
        self.assertIn("file", form.errors)

    @patch("apps.auditing.views.upload.AuditProcessingService")
    def test_valid_pdf_upload_creates_document_and_redirects(self, mock_service_cls):
        """A valid PDF upload should create an AuditDocument and redirect to result."""
        self.client.force_login(self.user)

        # Mock the service to avoid actual file processing
        mock_service = MagicMock()
        mock_service_cls.return_value = mock_service

        def fake_process(doc):
            doc.status = AuditDocument.Status.COMPLETED
            doc.save()
            return doc

        mock_service.process.side_effect = fake_process

        pdf_file = SimpleUploadedFile(
            "bank_statement.pdf",
            _make_pdf_bytes(),
            content_type="application/pdf",
        )

        response = self.client.post(self.upload_url, {
            "file": pdf_file,
            "selected_doc_type": "bank_statement",
            "language": "ar",
        })

        self.assertIn(response.status_code, [301, 302])

        # Verify document was created
        doc = AuditDocument.objects.filter(
            uploaded_by=self.user,
            original_name="bank_statement.pdf",
        ).first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.selected_doc_type, "bank_statement")

        # Verify redirect goes to result page
        result_url = reverse("auditor:result", kwargs={"pk": doc.pk})
        self.assertIn(str(doc.pk), response["Location"])

        # Clean up uploaded file
        if doc.file:
            import os
            try:
                os.remove(doc.file.path)
            except OSError:
                pass

    @patch("apps.auditing.views.upload.AuditProcessingService")
    def test_valid_csv_upload_redirects(self, mock_service_cls):
        """A valid CSV upload should also work."""
        self.client.force_login(self.user)

        mock_service = MagicMock()
        mock_service_cls.return_value = mock_service
        mock_service.process.side_effect = lambda doc: doc

        csv_file = SimpleUploadedFile(
            "payroll.csv",
            b"name,salary\nAli,10000\nSara,12000",
            content_type="text/csv",
        )

        response = self.client.post(self.upload_url, {
            "file": csv_file,
            "selected_doc_type": "payroll",
            "language": "en",
        })

        self.assertIn(response.status_code, [301, 302])

        doc = AuditDocument.objects.filter(
            uploaded_by=self.user,
            original_name="payroll.csv",
        ).first()
        self.assertIsNotNone(doc)

        if doc and doc.file:
            import os
            try:
                os.remove(doc.file.path)
            except OSError:
                pass


class AuditDocumentHistoryViewTests(TestCase):
    """Tests for AuditDocumentHistoryView."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="history@example.com",
            password="Str0ngP@ssw0rd!",
            full_name="History Tester",
        )
        self.history_url = reverse("auditor:history")

    def test_unauthenticated_redirects(self):
        response = self.client.get(self.history_url)
        self.assertIn(response.status_code, [301, 302])

    def test_authenticated_get_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auditing/history.html")

    def test_empty_history_shows_empty_state(self):
        self.client.force_login(self.user)
        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        page_obj = response.context.get("page_obj")
        self.assertIsNotNone(page_obj)
        self.assertEqual(len(page_obj.object_list), 0)

    def test_history_shows_user_documents(self):
        """User should see their own documents in history."""
        self.client.force_login(self.user)

        # Create a document for the user (without actual file)
        doc = AuditDocument.objects.create(
            uploaded_by=self.user,
            original_name="test_statement.pdf",
            status=AuditDocument.Status.COMPLETED,
            overall_risk_level="low",
        )

        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        page_obj = response.context.get("page_obj")
        self.assertIsNotNone(page_obj)
        self.assertEqual(len(page_obj.object_list), 1)
        self.assertEqual(str(page_obj.object_list[0].pk), str(doc.pk))

    def test_history_does_not_show_other_users_documents(self):
        """A user should NOT see documents belonging to other users."""
        other_user = User.objects.create_user(
            email="other@example.com",
            password="OtherP@ss!",
            full_name="Other User",
        )
        AuditDocument.objects.create(
            uploaded_by=other_user,
            original_name="other_doc.pdf",
            status=AuditDocument.Status.COMPLETED,
        )

        self.client.force_login(self.user)
        response = self.client.get(self.history_url)
        self.assertEqual(response.status_code, 200)
        page_obj = response.context.get("page_obj")
        self.assertEqual(len(page_obj.object_list), 0)


class AuditDocumentResultViewTests(TestCase):
    """Tests for AuditDocumentResultView."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="result@example.com",
            password="Str0ngP@ssw0rd!",
            full_name="Result Tester",
        )
        self.doc = AuditDocument.objects.create(
            uploaded_by=self.user,
            original_name="invoice.pdf",
            status=AuditDocument.Status.COMPLETED,
            overall_risk_level="medium",
            overall_confidence=0.85,
            ai_result={
                "executive_summary": "This is a test invoice.",
                "confidence_score": 0.85,
            },
        )

    def test_unauthenticated_redirects(self):
        url = reverse("auditor:result", kwargs={"pk": self.doc.pk})
        response = self.client.get(url)
        self.assertIn(response.status_code, [301, 302])

    def test_authenticated_owner_can_view(self):
        self.client.force_login(self.user)
        url = reverse("auditor:result", kwargs={"pk": self.doc.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "auditing/result.html")

    def test_doc_in_context(self):
        self.client.force_login(self.user)
        url = reverse("auditor:result", kwargs={"pk": self.doc.pk})
        response = self.client.get(url)
        self.assertEqual(response.context["doc"].pk, self.doc.pk)

    def test_other_user_cannot_view(self):
        other_user = User.objects.create_user(
            email="attacker@example.com",
            password="AttackP@ss!",
            full_name="Attacker",
        )
        self.client.force_login(other_user)
        url = reverse("auditor:result", kwargs={"pk": self.doc.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_document_returns_404(self):
        import uuid
        self.client.force_login(self.user)
        url = reverse("auditor:result", kwargs={"pk": uuid.uuid4()})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_confidence_pct_in_context(self):
        self.client.force_login(self.user)
        url = reverse("auditor:result", kwargs={"pk": self.doc.pk})
        response = self.client.get(url)
        confidence_pct = response.context.get("confidence_pct")
        self.assertIsNotNone(confidence_pct)
        self.assertGreaterEqual(confidence_pct, 0)
        self.assertLessEqual(confidence_pct, 100)
