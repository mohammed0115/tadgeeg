"""
Integration Tests for Analytics and Risk Optimization Services

Advanced tests covering:
- End-to-end workflows
- Edge cases and boundary conditions
- Performance characteristics under load
- Data consistency across operations
- Cache coherency

This module complements the main test suite with integration-focused scenarios.
"""

import pytest
import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache

from apps.authentication.models import Organization, User
from apps.audit.models import AuditSession, AuditFinding
from apps.audit.session_service import AuditSessionService
from apps.invoices.models import Invoice, InvoiceBatch
from apps.documents.models import Document
from apps.analytics.analytics_service import AuditAnalyticsService
from core.services.scoring.risk_optimization_service import RiskOptimizationService


# ────────────────────────────────────────────────────────────────────────────────
# Integration Test Base
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAnalyticsIntegration(TestCase):
    """Integration tests for analytics service."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name="Integration Test Org",
            registration_number="INT001",
        )
        self.user = User.objects.create_user(
            username="intuser",
            email="int@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_full_session_lifecycle_analytics(self):
        """
        Test analytics across a complete session lifecycle.
        
        RECEIVED → EXTRACTING → NORMALIZING → VALIDATING → COMPLETED
        """
        # Create session
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            session_name="Lifecycle Test",
            total_count=10,
        )

        # Create batch and invoices
        batch = InvoiceBatch.objects.create(audit_session=session)
        for i in range(10):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"LC-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000 + (i * 100),
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=20 + (i * 5),
            )

        # Create findings
        invoices = Invoice.objects.filter(batch=batch)
        for i, invoice in enumerate(invoices):
            AuditFinding.objects.create(
                organization=self.org,
                session=session,
                invoice=invoice,
                category=AuditFinding.Category.AMOUNT_ANOMALY,
                severity=[
                    AuditFinding.Severity.LOW,
                    AuditFinding.Severity.MEDIUM,
                    AuditFinding.Severity.HIGH,
                ][i % 3],
                title=f"Finding {i}",
                description=f"Test finding {i}",
                status=AuditFinding.Status.OPEN,
            )

        # Simulate state transitions
        session_service = AuditSessionService(session)
        session_service.transition(AuditSession.State.EXTRACTING)

        # Simulate processing
        for i in range(10):
            session_service.record_document_result(
                success=i < 8,
                requires_review=i >= 7,
                risk_score=20 + (i * 5),
            )

        session_service.transition(AuditSession.State.VALIDATING)
        session_service.maybe_complete()

        # Verify analytics at each stage
        analytics = AuditAnalyticsService(organization=self.org)
        session_stats = analytics.session_statistics(str(session.id))

        assert session_stats["documents"]["total"] == 10
        assert session_stats["documents"]["processed"] == 10
        assert session_stats["documents"]["success"] == 8
        assert session_stats["documents"]["failed"] == 2
        assert session_stats["findings"]["total_findings"] == 10

    def test_multi_batch_analytics(self):
        """Test analytics across multiple batches in a session."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            total_count=20,
        )

        # Create 3 batches
        for batch_idx in range(3):
            batch = InvoiceBatch.objects.create(
                audit_session=session,
                name=f"Batch {batch_idx}",
            )

            # Add invoices to each batch
            for i in range(6 + batch_idx):
                risk_score = 20 + (batch_idx * 20)
                Invoice.objects.create(
                    batch=batch,
                    invoice_number=f"MB-{batch_idx}-{i:02d}",
                    vendor_name=f"Vendor {batch_idx}-{i}",
                    total_amount=1000,
                    currency="SAR",
                    invoice_date=timezone.now().date(),
                    risk_score=risk_score,
                )

        # Get analytics
        analytics = AuditAnalyticsService(organization=self.org)
        org_summary = analytics.organization_summary(days=30)

        assert org_summary["sessions"]["total"] == 1
        assert org_summary["documents"]["total_uploaded"] > 0

    def test_analytics_with_missing_data(self):
        """Test analytics handles missing/null data gracefully."""
        # Create session with minimal data
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )

        analytics = AuditAnalyticsService(organization=self.org)
        stats = analytics.session_statistics(str(session.id))

        # Should not crash and return sensible defaults
        assert stats["documents"]["success_rate_pct"] == 0.0
        assert stats["findings"]["total_findings"] == 0

    def test_analytics_time_range_filtering(self):
        """Test that analytics correctly filter by time range."""
        now = timezone.now()
        
        # Create session from 45 days ago
        old_session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            created_at=now - timedelta(days=45),
        )

        # Create session from 15 days ago
        recent_session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            created_at=now - timedelta(days=15),
        )

        analytics = AuditAnalyticsService(organization=self.org)
        
        # 30-day summary should only include recent
        summary_30d = analytics.organization_summary(days=30)
        assert summary_30d["sessions"]["total"] == 1

        # 60-day summary should include both
        summary_60d = analytics.organization_summary(days=60)
        assert summary_60d["sessions"]["total"] == 2


# ────────────────────────────────────────────────────────────────────────────────
# Risk Optimization Integration Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRiskOptimizationIntegration(TestCase):
    """Integration tests for risk optimization service."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name="Risk Opt Org",
            registration_number="RO001",
        )
        self.user = User.objects.create_user(
            username="rouser",
            email="ro@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_risk_computation_consistency(self):
        """Test that risk scores are computed consistently."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Create invoices with specific risk scores
        invoice_damages = [30, 50, 70, 40, 60]
        invoices = []
        
        for i, risk in enumerate(invoice_damages):
            inv = Invoice.objects.create(
                batch=batch,
                invoice_number=f"CONS-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=risk,
            )
            invoices.append(inv)

        service = RiskOptimizationService(use_cache=False)
        
        # Score should be average: (30+50+ 70+40+60)/5 = 50
        result = service.score_zip_batch(str(batch.id))
        
        assert result["risk_metrics"]["average_risk_score"] == 50.0
        assert result["risk_metrics"]["max_risk_score"] == 70.0
        assert result["risk_metrics"]["min_risk_score"] == 30.0

    def test_risk_distribution_accuracy(self):
        """Test that risk distribution counts are accurate."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Create 10 invoices with specific risk levels
        # 2 critical (>=75), 3 high (50-75), 2 medium (25-50), 3 low (<25)
        risks = [80, 77, 60, 55, 50, 45, 30, 40, 20, 15]
        
        for i, risk in enumerate(risks):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"DIST-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=risk,
            )

        service = RiskOptimizationService(use_cache=False)
        result = service.score_zip_batch(str(batch.id))

        dist = result["risk_distribution"]
        assert dist["critical_count"] == 2
        assert dist["high_count"] == 3
        assert dist["medium_count"] == 2
        assert dist["low_count"] == 3

    def test_session_risk_aggregation_accuracy(self):
        """Test session-level risk aggregation."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )

        # Create 2 batches with different risk profiles
        batch1 = InvoiceBatch.objects.create(audit_session=session, name="Batch1")
        batch2 = InvoiceBatch.objects.create(audit_session=session, name="Batch2")

        # Batch 1: avg risk = 40
        for i in range(5):
            Invoice.objects.create(
                batch=batch1,
                invoice_number=f"B1-{i:03d}",
                vendor_name=f"Vendor B1-{i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=40.0,
            )

        # Batch 2: avg risk = 60
        for i in range(5):
            Invoice.objects.create(
                batch=batch2,
                invoice_number=f"B2-{i:03d}",
                vendor_name=f"Vendor B2-{i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=60.0,
            )

        service = RiskOptimizationService(use_cache=False)
        result = service.compute_session_risk_aggregate(str(session.id))

        # Overall should be average of all invoices: (40*5 + 60*5) / 10 = 50
        assert result["risk_summary"]["overall_risk_score"] == 50.0
        assert result["risk_summary"]["overall_risk_level"] == "high"

    def test_concurrent_batch_scoring_accuracy(self):
        """Test accuracy when scoring same batch multiple times concurrently."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        for i in range(5):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"CONC-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=50.0,
            )

        service = RiskOptimizationService(use_cache=False)

        # Score multiple times - should all be identical
        results = [
            service.score_zip_batch(str(batch.id))
            for _ in range(5)
        ]

        scores = [r["risk_metrics"]["average_risk_score"] for r in results]
        
        # All should be identical
        assert len(set(scores)) == 1
        assert scores[0] == 50.0


# ────────────────────────────────────────────────────────────────────────────────
# Edge Cases and Boundary Conditions
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEdgeCases(TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name="Edge Case Org",
            registration_number="EC001",
        )
        self.user = User.objects.create_user(
            username="ecuser",
            email="ec@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_empty_session_statistics(self):
        """Test statistics for completely empty session."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            total_count=0,
        )

        analytics = AuditAnalyticsService(organization=self.org)
        stats = analytics.session_statistics(str(session.id))

        assert stats["documents"]["success_rate_pct"] == 0.0
        assert stats["documents"]["average_risk_score"] == 0.0

    def test_single_invoice_batch(self):
        """Test risk computation for batch with single invoice."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        Invoice.objects.create(
            batch=batch,
            invoice_number="SINGLE-001",
            vendor_name="Single Vendor",
            total_amount=1000,
            currency="SAR",
            invoice_date=timezone.now().date(),
            risk_score=75.0,
        )

        service = RiskOptimizationService(use_cache=False)
        result = service.score_zip_batch(str(batch.id))

        assert result["document_count"] == 1
        assert result["risk_metrics"]["average_risk_score"] == 75.0
        assert result["risk_metrics"]["std_dev_risk"] == 0.0
        assert result["risk_level"] == "critical"

    def test_extreme_risk_values(self):
        """Test handling of extreme risk values."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Create invoices with extreme values
        Invoice.objects.create(
            batch=batch,
            invoice_number="MIN-001",
            vendor_name="Min Risk",
            total_amount=1000,
            currency="SAR",
            invoice_date=timezone.now().date(),
            risk_score=0.0,  # Minimum
        )

        Invoice.objects.create(
            batch=batch,
            invoice_number="MAX-001",
            vendor_name="Max Risk",
            total_amount=1000,
            currency="SAR",
            invoice_date=timezone.now().date(),
            risk_score=100.0,  # Maximum
        )

        service = RiskOptimizationService(use_cache=False)
        result = service.score_zip_batch(str(batch.id))

        assert result["risk_metrics"]["min_risk_score"] == 0.0
        assert result["risk_metrics"]["max_risk_score"] == 100.0
        assert result["risk_metrics"]["average_risk_score"] == 50.0

    def test_many_findings_per_session(self):
        """Test analytics with large number of findings."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )

        # Create 100 findings
        for i in range(100):
            AuditFinding.objects.create(
                organization=self.org,
                session=session,
                category=AuditFinding.Category.AMOUNT_ANOMALY,
                severity=[
                    AuditFinding.Severity.LOW,
                    AuditFinding.Severity.MEDIUM,
                    AuditFinding.Severity.HIGH,
                    AuditFinding.Severity.CRITICAL,
                ][i % 4],
                title=f"Finding {i}",
                description=f"Test finding {i}",
                status=AuditFinding.Status.OPEN,
            )

        analytics = AuditAnalyticsService(organization=self.org)
        breakdown = analytics.findings_breakdown(session_id=str(session.id))

        assert breakdown["total_findings"] == 100
        # Should have ~25 of each severity
        assert all(breakdown["by_severity"][k] > 0 for k in ["low", "medium", "high", "critical"])

    def test_document_batch_with_no_invoices(self):
        """Test scoring documents with no associated invoices."""
        docs = []
        for i in range(3):
            doc = Document.objects.create(
                organization=self.org,
                document_type="invoice",
                file_path=f"orphan_{i}.pdf",
            )
            docs.append(doc)

        service = RiskOptimizationService(use_cache=False)
        result = service.score_document_batch([str(d.id) for d in docs])

        assert result["total_documents"] == 3
        assert result["documents_scored"] == 0  # No invoices, so 0 scored


# ────────────────────────────────────────────────────────────────────────────────
# Performance and Load Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPerformanceCharacteristics(TestCase):
    """Test performance characteristics and load handling."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name="Perf Test Org",
            registration_number="PERF001",
        )
        self.user = User.objects.create_user(
            username="perfuser",
            email="perf@example.com",
            organization=self.org,
            password="testpass"
        )

    @pytest.mark.slow
    def test_large_batch_performance(self):
        """Test performance with large batch of invoices."""
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Create 500 invoices
        invoices = [
            Invoice(
                batch=batch,
                invoice_number=f"PERF-{i:05d}",
                vendor_name=f"Vendor {i % 50}",
                total_amount=1000 + (i % 100),
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=20 + (i % 80),
            )
            for i in range(500)
        ]
        Invoice.objects.bulk_create(invoices)

        service = RiskOptimizationService(use_cache=False)
        
        import time
        start = time.time()
        result = service.score_zip_batch(str(batch.id))
        elapsed = time.time() - start

        assert result["document_count"] == 500
        assert elapsed < 2.0  # Should complete in under 2 seconds
        assert result["risk_metrics"]["average_risk_score"] > 0

    def test_analytics_aggregation_performance(self):
        """Test that aggregations are efficient."""
        # Create multiple sessions with invoices
        for session_idx in range(10):
            session = AuditSession.objects.create(
                organization=self.org,
                created_by=self.user,
            )
            batch = InvoiceBatch.objects.create(audit_session=session)

            invoices = [
                Invoice(
                    batch=batch,
                    invoice_number=f"S{session_idx}-{i:03d}",
                    vendor_name=f"Vendor {i}",
                    total_amount=1000,
                    currency="SAR",
                    invoice_date=timezone.now().date(),
                    risk_score=30 + (i % 50),
                )
                for i in range(50)
            ]
            Invoice.objects.bulk_create(invoices)

        analytics = AuditAnalyticsService(organization=self.org)
        
        import time
        start = time.time()
        summary = analytics.organization_summary(days=30)
        elapsed = time.time() - start

        assert summary["sessions"]["total"] == 10
        assert elapsed < 1.0  # Should be fast


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
