"""Tests for auditing app models."""

import pytest
from django.contrib.auth import get_user_model

from apps.auditing.models import AuditDocument, AuditFinding

User = get_user_model()


@pytest.mark.django_db
class TestAuditDocument:
    def test_create_document(self):
        user = User.objects.create_user(username="u1", password="p1", email="u@test.com")
        doc = AuditDocument.objects.create(
            uploaded_by=user,
            original_name="test.pdf",
            selected_doc_type=AuditDocument.DocumentType.INVOICE,
            status=AuditDocument.Status.PENDING,
        )
        assert doc.pk is not None
        assert doc.status == "pending"
        assert str(doc) == "test.pdf (pending)"

    def test_default_status_is_pending(self):
        doc = AuditDocument(original_name="x.pdf")
        assert doc.status == AuditDocument.Status.PENDING

    def test_document_type_choices_complete(self):
        types = [c[0] for c in AuditDocument.DocumentType.choices]
        assert "invoice" in types
        assert "bank_statement" in types
        assert "payroll" in types
        assert "tax_declaration" in types
        assert "other" in types

    def test_risk_level_choices(self):
        levels = [c[0] for c in AuditDocument.RiskLevel.choices]
        assert "low" in levels
        assert "medium" in levels
        assert "high" in levels

    def test_doc_type_display_fallback(self):
        user = User.objects.create_user(username="u2", password="p2", email="u2@test.com")
        doc = AuditDocument.objects.create(
            uploaded_by=user,
            original_name="bank.pdf",
            selected_doc_type=AuditDocument.DocumentType.BANK_STATEMENT,
        )
        assert "bank" in doc.doc_type_display.lower() or doc.doc_type_display == "Bank Statement"

    def test_status_transitions(self):
        user = User.objects.create_user(username="u3", password="p3", email="u3@test.com")
        doc = AuditDocument.objects.create(
            uploaded_by=user,
            original_name="invoice.pdf",
        )
        assert doc.status == AuditDocument.Status.PENDING

        doc.status = AuditDocument.Status.PROCESSING
        doc.save()
        doc.refresh_from_db()
        assert doc.status == AuditDocument.Status.PROCESSING

        doc.status = AuditDocument.Status.COMPLETED
        doc.save()
        doc.refresh_from_db()
        assert doc.status == AuditDocument.Status.COMPLETED


@pytest.mark.django_db
class TestAuditFinding:
    def test_create_finding(self):
        user = User.objects.create_user(username="fu1", password="fp1", email="f@test.com")
        doc = AuditDocument.objects.create(
            uploaded_by=user,
            original_name="doc.pdf",
        )
        finding = AuditFinding.objects.create(
            document=doc,
            finding_type=AuditFinding.FindingType.ANOMALY,
            severity=AuditFinding.Severity.HIGH,
            title="Test Anomaly",
            details="Something is wrong",
            source="ai",
        )
        assert finding.pk is not None
        assert str(finding) == "[high] Test Anomaly"

    def test_finding_type_choices(self):
        types = [c[0] for c in AuditFinding.FindingType.choices]
        assert "anomaly" in types
        assert "validation" in types
        assert "compliance" in types
        assert "risk" in types

    def test_bulk_create(self):
        user = User.objects.create_user(username="bu1", password="bp1", email="b@test.com")
        doc = AuditDocument.objects.create(
            uploaded_by=user,
            original_name="bulk.pdf",
        )
        findings = [
            AuditFinding(
                document=doc,
                finding_type=AuditFinding.FindingType.VALIDATION,
                severity=AuditFinding.Severity.MEDIUM,
                title=f"Finding {i}",
            )
            for i in range(3)
        ]
        AuditFinding.objects.bulk_create(findings)
        assert doc.findings.count() == 3
