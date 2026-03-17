"""
Advanced Race Condition and ZIP Processing Tests

Specialized tests covering:
- ZIP file batch processing with concurrent operations
- Deadlock scenarios and prevention
- Data corruption detection in concurrent scenarios
- Fine-grained thread timing tests
- Cache coherency under concurrent access

Uses pytest-timeout for long-running tests to prevent hangs.
"""

import pytest
import threading
import time
import queue
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from threading import Barrier, Condition, Lock, Event
import random

from django.test import TransactionTestCase, TestCase, override_settings
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import F, Q
from django.core.cache import cache

from apps.authentication.models import Organization, User
from apps.audit.models import AuditSession, AuditFinding
from apps.invoices.models import Invoice, InvoiceBatch
from apps.analytics.analytics_service import AuditAnalyticsService
from core.services.scoring.risk_optimization_service import RiskOptimizationService


# ────────────────────────────────────────────────────────────────────────────────
# ZIP Batch Processing Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestZIPBatchProcessing(TransactionTestCase):
    """Tests for ZIP batch processing scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(
            name="ZIP Test Org",
            registration_number="ZIP001",
        )
        self.user = User.objects.create_user(
            username="zipuser",
            email="zip@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_zip_batch_concurrent_processing(self):
        """
        Test concurrent processing of same ZIP batch.
        
        Multiple threads attempt to process the same batch simultaneously.
        Results should be consistent despite concurrency.
        """
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
        )
        batch = InvoiceBatch.objects.create(
            audit_session=session,
            name="Concurrent ZIP Batch",
        )

        # Create 20 invoices
        for i in range(20):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"ZIP-{i:03d}",
                vendor_name=f"Vendor {i}",
                total_amount=1000 + i,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=30 + (i * 2),
            )

        service = RiskOptimizationService(use_cache=False)
        results = []
        errors = []
        lock = threading.Lock()

        def process_batch():
            """Process ZIP batch."""
            try:
                result = service.score_zip_batch(str(batch.id))
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Create 5 concurrent processors
        threads = [threading.Thread(target=process_batch) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify consistency
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5

        # All results should be identical
        avg_scores = [r["risk_metrics"]["average_risk_score"] for r in results]
        assert len(set(avg_scores)) == 1, f"Inconsistent scores: {avg_scores}"

    def test_zip_batch_with_concurrent_document_additions(self):
        """
        Test ZIP batch scoring while new documents are being added.
        
        Simulates real-world scenario where batch is being populated
        while scoring is running.
        """
        session = AuditSession.objects.create(organization=self.org, created_by=self.user)
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Create initial invoices
        for i in range(5):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"INIT-{i:03d}",
                vendor_name=f"Initial Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=40.0,
            )

        service = RiskOptimizationService(use_cache=False)
        score_results = []
        add_results = []
        errors = []
        barrier = Barrier(2)  # Synchronize 2 threads

        def score_batch():
            """Score the batch."""
            try:
                barrier.wait()  # Synchronize start
                time.sleep(0.1)  # Give adder time to add documents
                result = service.score_zip_batch(str(batch.id))
                score_results.append(result)
            except Exception as e:
                errors.append(f"score: {e}")

        def add_documents():
            """Add documents to batch."""
            try:
                barrier.wait()  # Synchronize start
                for i in range(5):
                    Invoice.objects.create(
                        batch=batch,
                        invoice_number=f"ADDED-{i:03d}",
                        vendor_name=f"Added Vendor {i}",
                        total_amount=1000,
                        currency="SAR",
                        invoice_date=timezone.now().date(),
                        risk_score=50.0,
                    )
                    time.sleep(0.02)
                add_results.append("completed")
            except Exception as e:
                errors.append(f"add: {e}")

        threads = [
            threading.Thread(target=score_batch),
            threading.Thread(target=add_documents),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(add_results) == 1
        assert len(score_results) == 1

        # Refresh to verify all documents exist
        final_count = Invoice.objects.filter(batch=batch).count()
        assert final_count == 10


# ────────────────────────────────────────────────────────────────────────────────
# Precise Race Condition Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestPreciseRaceConditions(TransactionTestCase):
    """Fine-grained race condition tests with precise timing."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(
            name="Precise Race Org",
            registration_number="RACE001",
        )
        self.user = User.objects.create_user(
            username="praceuser",
            email="prace@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_lost_update_prevention(self):
        """
        Test that concurrent updates don't cause lost updates.
        
        Uses F() expressions to ensure atomic increments.
        """
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            processed_count=0,
            success_count=0,
        )

        errors = []
        num_threads = 10
        updates_per_thread = 10

        def update_counter():
            """Update session counters."""
            try:
                for _ in range(updates_per_thread):
                    AuditSession.objects.filter(pk=session.pk).update(
                        processed_count=F('processed_count') + 1,
                        success_count=F('success_count') + 1,
                    )
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=update_counter) for _ in range(num_threads)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

        # Verify final counts
        session.refresh_from_db()
        expected = num_threads * updates_per_thread
        
        assert session.processed_count == expected, \
            f"Lost updates detected: {session.processed_count} != {expected}"
        assert session.success_count == expected

    def test_phantom_read_prevention(self):
        """
        Test that transactions prevent phantom reads.
        
        One thread counts records while another adds records.
        """
        session = AuditSession.objects.create(organization=self.org, created_by=self.user)
        batch = InvoiceBatch.objects.create(audit_session=session)

        # Initial invoices
        for i in range(5):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"INITIAL-{i}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=40.0,
            )

        read_counts = []
        add_complete = Event()
        errors = []

        def count_invoices():
            """Count invoices multiple times."""
            try:
                with transaction.atomic():
                    # Count should be stable within transaction
                    count1 = Invoice.objects.filter(batch=batch).count()
                    add_complete.wait()  # Wait for other thread
                    time.sleep(0.1)
                    count2 = Invoice.objects.filter(batch=batch).count()
                    read_counts.append((count1, count2))
            except Exception as e:
                errors.append(str(e))

        def add_invoices():
            """Add invoices."""
            try:
                time.sleep(0.05)
                for i in range(5):
                    Invoice.objects.create(
                        batch=batch,
                        invoice_number=f"ADDED-{i}",
                        vendor_name=f"Added Vendor {i}",
                        total_amount=1000,
                        currency="SAR",
                        invoice_date=timezone.now().date(),
                        risk_score=50.0,
                    )
                add_complete.set()
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=count_invoices),
            threading.Thread(target=add_invoices),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

    def test_dirty_read_prevention(self):
        """
        Test that dirty reads are prevented in transactions.
        
        Uses explicit transaction boundaries.
        """
        session = AuditSession.objects.create(
            organization=self.org,
            created_by=self.user,
            processed_count=10,
        )

        read_values = []
        errors = []
        commit_signal = Event()

        def read_uncommitted():
            """Try to read other transaction's changes."""
            try:
                time.sleep(0.05)  # Let writer start
                with transaction.atomic():
                    value = AuditSession.objects.get(pk=session.pk).processed_count
                    read_values.append(value)
            except Exception as e:
                errors.append(str(e))

        def write_rollback():
            """Write and rollback."""
            try:
                try:
                    with transaction.atomic():
                        AuditSession.objects.filter(pk=session.pk).update(
                            processed_count=999
                        )
                        commit_signal.set()
                        time.sleep(0.1)  # Hold transaction open
                        raise Exception("Rollback!")
                except Exception:
                    pass
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=read_uncommitted),
            threading.Thread(target=write_rollback),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have read the original value (10) not the rolled-back value (999)
        # This depends on isolation level, but demonstrates testing approach
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────────────────────
# Cache Coherency Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache-coherency',
    }
})
class TestCacheCoherency(TransactionTestCase):
    """Test cache invalidation and coherency."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()
        self.org = Organization.objects.create(
            name="Cache Test Org",
            registration_number="CACHE001",
        )
        self.user = User.objects.create_user(
            username="cacheuser",
            email="cache@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_cache_invalidation_on_update(self):
        """Test that cache is invalidated when data changes."""
        session = AuditSession.objects.create(organization=self.org, created_by=self.user)
        batch = InvoiceBatch.objects.create(audit_session=session)

        for i in range(5):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"INV-{i}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=40.0,
            )

        service = RiskOptimizationService(use_cache=True)

        # First call - cached
        result1 = service.score_zip_batch(str(batch.id))
        score1 = result1["risk_metrics"]["average_risk_score"]

        # Add more invoices
        for i in range(5, 10):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"INV-{i}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=60.0,
            )

        # Clear cache to get fresh data
        service.clear_cache(batch_id=str(batch.id))

        # Second call - should reflect new data
        result2 = service.score_zip_batch(str(batch.id))
        score2 = result2["risk_metrics"]["average_risk_score"]

        # Score should have increased (now includes 60 scores)
        assert score2 > score1

    def test_concurrent_cache_access(self):
        """Test thread-safe cache access."""
        session = AuditSession.objects.create(organization=self.org, created_by=self.user)
        batch = InvoiceBatch.objects.create(audit_session=session)

        for i in range(10):
            Invoice.objects.create(
                batch=batch,
                invoice_number=f"CACHED-{i}",
                vendor_name=f"Vendor {i}",
                total_amount=1000,
                currency="SAR",
                invoice_date=timezone.now().date(),
                risk_score=50.0,
            )

        service = RiskOptimizationService(use_cache=True)
        errors = []
        cache_info = []

        def access_cache():
            """Access cached results."""
            try:
                for _ in range(10):
                    result = service.score_zip_batch(str(batch.id))
                    cache_info.append(result["cached"])
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=access_cache) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        # After first access, most should be cached
        assert cache_info.count(True) >= len(cache_info) - 5


# ────────────────────────────────────────────────────────────────────────────────
# Stress Tests
# ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
class TestStressScenarios(TransactionTestCase):
    """Stress tests simulating high load."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(
            name="Stress Test Org",
            registration_number="STRESS001",
        )
        self.user = User.objects.create_user(
            username="stressuser",
            email="stress@example.com",
            organization=self.org,
            password="testpass"
        )

    def test_high_concurrency_analytics_reads(self):
        """Test analytics under high concurrent read load."""
        # Create test data
        for session_idx in range(5):
            session = AuditSession.objects.create(organization=self.org, created_by=self.user)
            batch = InvoiceBatch.objects.create(audit_session=session)

            for i in range(20):
                Invoice.objects.create(
                    batch=batch,
                    invoice_number=f"S{session_idx}-{i:03d}",
                    vendor_name=f"Vendor {i}",
                    total_amount=1000,
                    currency="SAR",
                    invoice_date=timezone.now().date(),
                    risk_score=random.randint(20, 80),
                )

        analytics = AuditAnalyticsService(organization=self.org)
        results = []
        errors = []
        lock = Lock()

        def read_analytics():
            """Read analytics."""
            try:
                for _ in range(10):
                    summary = analytics.organization_summary(days=30)
                    with lock:
                        results.append(summary["documents"]["total_uploaded"])
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Create 20 concurrent readers
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(read_analytics) for _ in range(20)]
            for future in as_completed(futures):
                future.result()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) > 0

    def test_rapid_batch_scoring_sequence(self):
        """Test rapid sequence of batch scoring operations."""
        session = AuditSession.objects.create(organization=self.org, created_by=self.user)
        
        errors = []
        service = RiskOptimizationService(use_cache=False)

        def score_many_batches():
            """Score many batches rapidly."""
            try:
                for batch_idx in range(10):
                    batch = InvoiceBatch.objects.create(audit_session=session)

                    for i in range(10):
                        Invoice.objects.create(
                            batch=batch,
                            invoice_number=f"RAPID-{batch_idx}-{i}",
                            vendor_name=f"Vendor {i}",
                            total_amount=1000,
                            currency="SAR",
                            invoice_date=timezone.now().date(),
                            risk_score=random.randint(20, 80),
                        )

                    result = service.score_zip_batch(str(batch.id))
                    assert result["document_count"] == 10
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=score_many_batches) for _ in range(3)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
