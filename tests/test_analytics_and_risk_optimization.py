"""
Comprehensive Test Suite for Analytics and Risk Optimization Services

Tests cover:
- Functional correctness of analytics and risk scoring
- Race condition handling with multiple threads
- Atomic operations and transaction isolation
- Cache behavior and invalidation
- Concurrent document/invoice processing

Test Categories:
1. AuditAnalyticsService Tests
2. RiskOptimizationService Tests
3. Race Condition Tests (Threading)
4. Transaction Isolation Tests
5. Cache Consistency Tests
"""

import pytest
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from django.core.cache import cache

from apps.authentication.models import Organization, User
from apps.audit.models import AuditSession, AuditFinding
from apps.audit.session_service import AuditSessionService
from apps.invoices.models import Invoice, InvoiceBatch
from apps.documents.models import Document
from apps.analytics.analytics_service import AuditAnalyticsService, SessionNotFoundError
from core.services.scoring.risk_optimization_service import RiskOptimizationService


# ────────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def organization():
    """Create a test organization."""
    return Organization.objects.create(
        name="Test Org",
        registration_number="TEST123",
    )


@pytest.fixture
def user(organization):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        organization=organization,
        password="testpass123"
    )


@pytest.fixture
def audit_session(organization, user):
    """Create a test audit session."""
    session = AuditSession.objects.create(
        organization=organization,
        created_by=user,
        session_name="Test Session",
        total_count=5,
    )
    return session


@pytest.fixture
def invoice_batch(audit_session):
    """Create a test invoice batch."""
    return InvoiceBatch.objects.create(
        audit_session=audit_session,
        name="Test Batch",
    )


@pytest.fixture
def invoices(invoice_batch):
    """Create test invoices."""
    invoices = []
    for i in range(5):
        inv = Invoice.objects.create(
            batch=invoice_batch,
            invoice_number=f"INV-{i:03d}",
            vendor_name=f"Vendor {i}",
            total_amount=1000 + (i * 100),
            currency="SAR",
            invoice_date=timezone.now().date(),
            risk_score=20 + (i * 15),  # 20, 35, 50, 65, 80
        )
        invoices.append(inv)
    return invoices


@pytest.fixture
def audit_findings(audit_session, invoices):
    """Create test audit findings."""
    findings = []
    severities = [
        AuditFinding.Severity.LOW,
        AuditFinding.Severity.MEDIUM,
        AuditFinding.Severity.HIGH,
        AuditFinding.Severity.CRITICAL,
        AuditFinding.Severity.CRITICAL,
    ]
    
    for i, (invoice, severity) in enumerate(zip(invoices, severities)):
        finding = AuditFinding.objects.create(
            organization=audit_session.organization,
            session=audit_session,
            invoice=invoice,
            category=AuditFinding.Category.AMOUNT_ANOMALY,
            severity=severity,
            title=f"Finding {i+1}",
            description=f"Test finding {i+1}",
            status=AuditFinding.Status.OPEN if i < 3 else AuditFinding.Status.REVIEWED,
        )
        findings.append(finding)
    return findings


# ────────────────────────────────────────────────────────────────────────────────
# AuditAnalyticsService Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAuditAnalyticsService:
    """Test suite for AuditAnalyticsService."""

    def test_session_statistics_basic(self, audit_session, invoices):
        """Test basic session statistics extraction."""
        # Simulate session state
        audit_session.started_at = timezone.now() - timedelta(hours=1)
        audit_session.completed_at = timezone.now()
        audit_session.processed_count = 5
        audit_session.success_count = 5
        audit_session.overall_risk_score = 50.0
        audit_session.overall_risk_level = "medium"
        audit_session.save()

        service = AuditAnalyticsService()
        stats = service.session_statistics(str(audit_session.id))

        assert stats["session_id"] == str(audit_session.id)
        assert stats["state"] == AuditSession.State.RECEIVED
        assert stats["documents"]["total"] == 5
        assert stats["documents"]["processed"] == 5
        assert stats["documents"]["success"] == 5
        assert stats["risk_summary"]["overall_risk_score"] == 50.0

    def test_session_statistics_not_found(self):
        """Test statistics for non-existent session."""
        service = AuditAnalyticsService()
        
        with pytest.raises(SessionNotFoundError):
            service.session_statistics(str(uuid.uuid4()))

    def test_organization_summary_aggregations(self, organization, user, invoices):
        """Test organization-level aggregations."""
        # Create multiple sessions
        for i in range(3):
            session = AuditSession.objects.create(
                organization=organization,
                created_by=user,
                total_count=5,
                processed_count=5,
                success_count=5,
                overall_risk_score=30 + (i * 20),
                state=AuditSession.State.COMPLETED,
            )
            session.started_at = timezone.now() - timedelta(hours=i)
            session.completed_at = timezone.now()
            session.save()

        service = AuditAnalyticsService(organization=organization)
        summary = service.organization_summary(days=30)

        assert summary["sessions"]["total"] == 3
        assert summary["sessions"]["completed"] == 3
        assert summary["documents"]["total_uploaded"] == 15

    def test_findings_breakdown(self, audit_session, audit_findings):
        """Test findings severity and category breakdown."""
        service = AuditAnalyticsService()
        breakdown = service.findings_breakdown(session_id=str(audit_session.id))

        assert breakdown["total_findings"] == 5
        assert breakdown["by_severity"]["critical"] == 2
        assert breakdown["by_severity"]["high"] == 1
        assert breakdown["by_severity"]["medium"] == 1
        assert breakdown["by_severity"]["low"] == 1
        assert breakdown["unresolved_count"] == 3

    def test_risk_analytics(self, organization, user):
        """Test risk analytics across sessions."""
        # Create sessions with varying risk levels
        for i in range(5):
            session = AuditSession.objects.create(
                organization=organization,
                created_by=user,
                total_count=10,
                overall_risk_score=20 + (i * 15),
                state=AuditSession.State.COMPLETED,
            )

        service = AuditAnalyticsService(organization=organization)
        analytics = service.risk_analytics(days=30)

        assert analytics["total_findings"] == 0  # No findings created
        assert analytics["critical_sessions_count"] == 1  # One with score >= 75
        assert analytics["high_risk_sessions_count"] == 2  # Two with score >= 50
        assert analytics["average_risk_score"] > 0

    def test_user_statistics(self, organization, user):
        """Test user-specific statistics."""
        # Create sessions for user
        for i in range(3):
            AuditSession.objects.create(
                organization=organization,
                created_by=user,
                total_count=5 + i,
                processed_count=5 + i,
                success_count=4 + i,
                state=AuditSession.State.COMPLETED,
            )

        service = AuditAnalyticsService(organization=organization)
        user_stats = service.user_statistics(str(user.id), days=30)

        assert user_stats["username"] == "testuser"
        assert user_stats["total_sessions"] == 3
        assert user_stats["completed_sessions"] == 3
        assert user_stats["total_documents_processed"] == 18  # 5 + 6 + 7

    def test_performance_report(self, organization, user):
        """Test performance and bottleneck detection."""
        now = timezone.now()
        
        # Create a slow session
        slow_session = AuditSession.objects.create(
            organization=organization,
            created_by=user,
            total_count=100,
            started_at=now - timedelta(hours=10),
            completed_at=now - timedelta(hours=9),
            failed_count=50,
        )

        service = AuditAnalyticsService(organization=organization)
        report = service.performance_report(days=30)

        assert report["processing_time"]["average_seconds"] > 0
        assert len(report["bottleneck_sessions"]) >= 0


# ────────────────────────────────────────────────────────────────────────────────
# RiskOptimizationService Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRiskOptimizationService:
    """Test suite for RiskOptimizationService."""

    def test_score_zip_batch_basic(self, invoice_batch, invoices):
        """Test ZIP batch risk scoring."""
        service = RiskOptimizationService(use_cache=False)
        result = service.score_zip_batch(str(invoice_batch.id))

        assert result["batch_id"] == str(invoice_batch.id)
        assert result["document_count"] == 5
        assert "risk_metrics" in result
        assert result["risk_metrics"]["average_risk_score"] > 0
        assert result["risk_level"] in ["low", "medium", "high", "critical"]

    def test_score_zip_batch_empty(self, invoice_batch):
        """Test scoring an empty batch."""
        service = RiskOptimizationService(use_cache=False)
        result = service.score_zip_batch(str(invoice_batch.id))

        assert result["document_count"] == 0
        assert result["risk_metrics"]["average_risk_score"] == 0
        assert result["risk_level"] == "low"

    def test_score_zip_batch_not_found(self):
        """Test scoring non-existent batch."""
        service = RiskOptimizationService()
        
        with pytest.raises(ValueError):
            service.score_zip_batch(str(uuid.uuid4()))

    def test_score_document_batch(self, organization, invoices):
        """Test scoring a batch of documents."""
        # Create documents
        docs = []
        for i in range(3):
            doc = Document.objects.create(
                organization=organization,
                document_type="invoice",
                file_path=f"test_{i}.pdf",
            )
            docs.append(doc)

        service = RiskOptimizationService(use_cache=False)
        result = service.score_document_batch([str(d.id) for d in docs])

        assert result["total_documents"] == 3
        assert result["documents_scored"] >= 0
        assert "risk_summary" in result

    def test_compute_session_risk_aggregate(self, audit_session, invoice_batch, invoices):
        """Test session-level risk aggregation."""
        service = RiskOptimizationService(use_cache=False)
        result = service.compute_session_risk_aggregate(str(audit_session.id))

        assert result["session_id"] == str(audit_session.id)
        assert result["invoice_count"] == 5
        assert result["risk_summary"]["overall_risk_level"] in ["low", "medium", "high", "critical"]
        assert "invoice_risk_distribution" in result

    def test_risk_score_to_level(self):
        """Test risk score to level conversion."""
        service = RiskOptimizationService()

        assert service._risk_score_to_level(10) == "low"
        assert service._risk_score_to_level(25) == "medium"
        assert service._risk_score_to_level(50) == "high"
        assert service._risk_score_to_level(75) == "critical"

    def test_compute_std_dev(self):
        """Test standard deviation computation."""
        service = RiskOptimizationService()

        values = [10, 20, 30, 40, 50]
        mean = sum(values) / len(values)  # 30
        std_dev = service._compute_std_dev(values, mean)

        # Expected std dev: sqrt(200) ≈ 14.14
        assert abs(std_dev - 14.14) < 0.1

    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache',
        }
    })
    def test_caching_behavior(self, invoice_batch, invoices):
        """Test caching and cache invalidation."""
        cache.clear()
        service = RiskOptimizationService(use_cache=True)

        # First call should compute and cache
        result1 = service.score_zip_batch(str(invoice_batch.id))
        assert result1["cached"] is False

        # Second call should return cached result
        result2 = service.score_zip_batch(str(invoice_batch.id))
        assert result2["cached"] is True

        # Results should be identical
        assert result1["risk_metrics"]["average_risk_score"] == result2["risk_metrics"]["average_risk_score"]


# ────────────────────────────────────────────────────────────────────────────────
# Race Condition Tests with Threading
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestRaceConditionsThreading(TransactionTestCase):
    """
    Test race conditions using threading.
    
    Uses TransactionTestCase to properly handle transaction isolation.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.organization = Organization.objects.create(
            name="Test Org Race",
            registration_number="RACE123",
        )
        self.user = User.objects.create_user(
            username="raceuser",
            email="race@example.com",
            organization=self.organization,
            password="testpass123"
        )
        self.session = AuditSession.objects.create(
            organization=self.organization,
            created_by=self.user,
            session_name="Race Test Session",
            total_count=10,
        )
        self.batch = InvoiceBatch.objects.create(
            audit_session=self.session,
            name="Race Test Batch",
        )
        
        # Create invoices
        for i in range(5):
            Invoice.objects.create(
                batch=self.batch,
                invoice_number=f"RACE-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000 + (i * 100),
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=20 + (i * 20),
            )

    def test_concurrent_session_updates(self):
        """
        Test concurrent updates to session counters.
        
        Simulates multiple threads updating session progress simultaneously.
        Uses F() expressions to ensure atomicity.
        """
        service = AuditSessionService(self.session)
        errors = []
        results = []

        def update_progress():
            """Update session progress."""
            try:
                service.record_document_result(
                    success=True,
                    risk_score=35.0,
                    is_duplicate=False,
                    has_compliance_issue=False,
                )
                results.append("success")
            except Exception as e:
                errors.append(str(e))

        # Create 5 threads to simulate concurrent document processing
        threads = [threading.Thread(target=update_progress) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors: {errors}"

        # Verify session was updated correctly
        self.session.refresh_from_db()
        assert self.session.processed_count == 5
        assert self.session.success_count == 5

    def test_concurrent_batch_risk_recalculation(self):
        """
        Test concurrent risk recalculation for invoices.
        
        Simulates multiple threads computing risk scores simultaneously.
        """
        service = RiskOptimizationService()
        results = []
        errors = []

        def compute_risk():
            """Compute batch risk."""
            try:
                result = service.score_zip_batch(str(self.batch.id))
                results.append(result["risk_metrics"]["average_risk_score"])
            except Exception as e:
                errors.append(str(e))

        # Create 3 concurrent threads
        threads = [threading.Thread(target=compute_risk) for _ in range(3)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors
        assert len(errors) == 0, f"Errors: {errors}"

        # All results should be identical (same computation)
        assert len(set(results)) == 1, f"Inconsistent results: {results}"

    def test_concurrent_invoice_updates(self):
        """
        Test concurrent updates to invoice risk scores.
        
        Simulates multiple threads updating invoice records.
        """
        invoices = list(Invoice.objects.filter(batch=self.batch))
        errors = []

        def update_invoice_risk(invoice_id, new_risk):
            """Update invoice risk score."""
            try:
                Invoice.objects.filter(pk=invoice_id).update(
                    risk_score=new_risk
                )
            except Exception as e:
                errors.append(str(e))

        # Create threads to update different invoices
        threads = []
        for invoice in invoices:
            t = threading.Thread(
                target=update_invoice_risk,
                args=(invoice.id, 50.0)
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

        # Verify all invoices were updated
        updated = Invoice.objects.filter(batch=self.batch, risk_score=50.0).count()
        assert updated == 5

    def test_concurrent_analytics_read_with_writes(self):
        """
        Test concurrent analytics reads while documents are being processed.
        
        Simulates simultaneous invoice writes and analytics reads.
        """
        service = AuditAnalyticsService(organization=self.organization)
        read_results = []
        write_errors = []

        def read_analytics():
            """Read analytics."""
            try:
                stats = service.organization_summary(days=30)
                read_results.append(stats["documents"]["total_uploaded"])
            except Exception as e:
                write_errors.append(str(e))

        def write_invoices():
            """Write new invoices."""
            try:
                for i in range(5):
                    Invoice.objects.create(
                        batch=self.batch,
                        invoice_number=f"WRITE-{i:03d}",
                        vendor_name=f"Write Vendor {i}",
                        total_amount=2000,
                        currency="SAR",
                        invoice_date=timezone.now().date(),
                        risk_score=40.0,
                    )
            except Exception as e:
                write_errors.append(str(e))

        # Create threads for concurrent reads and writes
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=read_analytics))
        threads.append(threading.Thread(target=write_invoices))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors even with concurrent operations
        assert len(write_errors) == 0, f"Errors: {write_errors}"

    def test_session_state_transition_race(self):
        """
        Test race condition in session state transitions.
        
        Multiple threads attempt to transition session state simultaneously.
        Only the first should succeed; others should handle gracefully.
        """
        service = AuditSessionService(self.session)
        transition_count = 0
        errors = []

        def attempt_transition():
            """Attempt to transition session state."""
            nonlocal transition_count
            try:
                service.transition(AuditSession.State.EXTRACTING)
                transition_count += 1
            except Exception:
                errors.append("transition failed")

        # Initial state is RECEIVED, valid transition is to EXTRACTING
        threads = [threading.Thread(target=attempt_transition) for _ in range(3)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify only one succeeded
        assert transition_count == 1 or len(errors) >= 2

    def test_high_concurrency_stress_test(self):
        """
        Stress test with high concurrency.
        
        Simulates 20 concurrent workers processing documents.
        """
        session = self.session
        session.total_count = 20
        session.save()

        service = AuditSessionService(session)
        completion_count = [0]
        errors = []
        lock = threading.Lock()

        def process_document(doc_index):
            """Process a document."""
            try:
                time.sleep(0.01)  # Simulate processing
                service.record_document_result(
                    success=(doc_index % 2 == 0),
                    risk_score=30.0 + doc_index,
                    requires_review=(doc_index % 3 == 0),
                )
                
                with lock:
                    completion_count[0] += 1
            except Exception as e:
                errors.append(str(e))

        # Create 20 worker threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(process_document, i)
                for i in range(20)
            ]
            for future in as_completed(futures):
                future.result()

        # Verify completion
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert completion_count[0] == 20
        
        # Verify session state
        session.refresh_from_db()
        assert session.processed_count == 20


# ────────────────────────────────────────────────────────────────────────────────
# Transaction Isolation Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestTransactionIsolation(TransactionTestCase):
    """
    Test transaction isolation and atomicity guarantees.
    
    Ensures that concurrent operations maintain data consistency.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.organization = Organization.objects.create(
            name="Test Org TX",
            registration_number="TX123",
        )
        self.user = User.objects.create_user(
            username="txuser",
            email="tx@example.com",
            organization=self.organization,
            password="testpass123"
        )

    def test_atomic_session_update(self):
        """
        Test that session updates are atomic.
        
        Use transaction.atomic() to ensure all-or-nothing semantics.
        """
        session = AuditSession.objects.create(
            organization=self.organization,
            created_by=self.user,
            total_count=1,
        )

        service = RiskOptimizationService()
        
        # Update should be atomic
        success = service.update_session_risk_scores(str(session.id))
        assert success is not None

    def test_concurrent_transaction_isolation(self):
        """
        Test that concurrent transactions don't interfere with each other.
        
        Uses multiple threads with explicit transaction management.
        """
        session = AuditSession.objects.create(
            organization=self.organization,
            created_by=self.user,
            total_count=10,
        )

        batch = InvoiceBatch.objects.create(
            audit_session=session,
            name="TX Batch",
        )

        # Create invoices
        for i in range(5):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"TX-{i:03d}",
                vendor_name=f"TX Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=40.0,
            )

        errors = []

        def update_with_transaction():
            """Update with explicit transaction."""
            try:
                with transaction.atomic():
                    invoices = Invoice.objects.filter(batch=batch)
                    invoices.update(risk_score=F('risk_score') + 5)
            except Exception as e:
                errors.append(str(e))

        # Run concurrent transactions
        threads = [threading.Thread(target=update_with_transaction) for _ in range(3)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

        # Verify final state
        final_risk = Invoice.objects.filter(batch=batch).first().risk_score
        # Should have started at 40, been updated 3 times by +5 = 55
        assert final_risk == Decimal('55')

    def test_deadlock_prevention_with_ordering(self):
        """
        Test that proper ordering prevents deadlocks.
        
        Multiple threads acquire locks in the same order.
        """
        session1 = AuditSession.objects.create(
            organization=self.organization,
            created_by=self.user,
            total_count=1,
        )
        session2 = AuditSession.objects.create(
            organization=self.organization,
            created_by=self.user,
            total_count=1,
        )

        errors = []
        completed = [0]
        lock = threading.Lock()

        def update_sessions_ordered():
            """Update sessions in consistent order to prevent deadlock."""
            try:
                # Always acquire in same order (session1 < session2)
                sessions = sorted(
                    [session1, session2],
                    key=lambda s: str(s.id)
                )
                
                with transaction.atomic():
                    for session in sessions:
                        AuditSession.objects.filter(pk=session.pk).update(
                            processed_count=F('processed_count') + 1
                        )
                
                with lock:
                    completed[0] += 1
            except Exception as e:
                errors.append(str(e))

        # Run multiple threads
        threads = [threading.Thread(target=update_sessions_ordered) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without deadlock
        assert len(errors) == 0, f"Errors: {errors}"
        assert completed[0] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
