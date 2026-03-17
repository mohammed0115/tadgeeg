"""
Quick Start Guide - Analytics & Risk Optimization Services

This guide will get you up and running with the new analytics and risk 
optimization services for Tadgeeg-AI in 5 minutes.
"""

# ════════════════════════════════════════════════════════════════════════════════
# INSTALLATION & SETUP
# ════════════════════════════════════════════════════════════════════════════════

# 1. Ensure services are created in the correct locations:
#    ✓ apps/analytics/analytics_service.py         (AuditAnalyticsService)
#    ✓ core/services/scoring/risk_optimization_service.py  (RiskOptimizationService)

# 2. Add the following to your Django settings if using Redis cache (recommended):

# In finai_backend/settings.py:

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
        'KEY_PREFIX': 'tadgeeg',
        'TIMEOUT': 300,  # 5 minutes
    }
}

# ════════════════════════════════════════════════════════════════════════════════
# BASIC USAGE - SESSION ANALYTICS
# ════════════════════════════════════════════════════════════════════════════════

from apps.analytics.analytics_service import AuditAnalyticsService
from apps.audit.models import AuditSession

# Initialize service
service = AuditAnalyticsService()

# Get a session
session = AuditSession.objects.first()

# Extract statistics
stats = service.session_statistics(str(session.id))

print(f"""
Session Statistics:
  ID: {stats['session_id']}
  State: {stats['state']}
  Documents:
    - Total: {stats['documents']['total']}
    - Processed: {stats['documents']['processed']}
    - Success Rate: {stats['documents']['success_rate_pct']}%
  Risk:
    - Score: {stats['risk_summary']['overall_risk_score']}
    - Level: {stats['risk_summary']['overall_risk_level']}
  Findings: {stats['findings']['total_findings']}
""")

# ════════════════════════════════════════════════════════════════════════════════
# ORGANIZATION ANALYTICS
# ════════════════════════════════════════════════════════════════════════════════

from apps.authentication.models import Organization

org = Organization.objects.first()
service = AuditAnalyticsService(organization=org)

# Get organization summary for last 30 days
summary = service.organization_summary(days=30)

print(f"""
Organization Summary (Last 30 days):
  Sessions:
    - Total: {summary['sessions']['total']}
    - Completed: {summary['sessions']['completed']}
    - Failed: {summary['sessions']['failed']}
    - Completion Rate: {summary['sessions']['completion_rate_pct']}%
  Documents:
    - Total: {summary['documents']['total_uploaded']}
    - Avg Risk: {summary['documents']['average_risk_score']}
    - By Level: {summary['documents']['by_risk_level']}
  Performance:
    - Throughput: {summary['performance']['throughput_documents_per_day']} docs/day
""")

# ════════════════════════════════════════════════════════════════════════════════
# RISK SCORING - ZIP BATCHES
# ════════════════════════════════════════════════════════════════════════════════

from core.services.scoring.risk_optimization_service import RiskOptimizationService
from apps.invoices.models import InvoiceBatch

# Initialize service with caching
service = RiskOptimizationService(use_cache=True)

# Get a batch
batch = InvoiceBatch.objects.first()

# Score the batch
result = service.score_zip_batch(str(batch.id))

print(f"""
ZIP Batch Risk Score:
  Batch: {result['batch_name']}
  Documents: {result['document_count']}
  Risk Metrics:
    - Average: {result['risk_metrics']['average_risk_score']}
    - Max: {result['risk_metrics']['max_risk_score']}
    - Min: {result['risk_metrics']['min_risk_score']}
    - Std Dev: {result['risk_metrics']['std_dev_risk']}
  Risk Level: {result['risk_level']}
  Distribution: {result['risk_distribution']}
  Cached: {result['cached']}

High-Risk Invoices:
""")

for inv in result['invoice_details'][:5]:
    print(f"  - {inv['invoice_number']}: {inv['risk_score']} ({inv['risk_level']})")

# ════════════════════════════════════════════════════════════════════════════════
# SESSION RISK AGGREGATION
# ════════════════════════════════════════════════════════════════════════════════

from apps.audit.models import AuditSession

session = AuditSession.objects.first()

# Compute session-level risk
result = service.compute_session_risk_aggregate(str(session.id))

print(f"""
Session Risk Aggregate:
  Session: {result['session_name']}
  State: {result['state']}
  Overall Risk: {result['risk_summary']['overall_risk_score']} ({result['risk_summary']['overall_risk_level']})
  
  Invoices by Batch:
""")

for batch in result['risk_summary']['by_batch']:
    print(f"    {batch['batch_name']}: {batch['invoice_count']} invoices, avg risk {batch['avg_risk']}")

print(f"\n  Risk Distribution: {result['invoice_risk_distribution']}")

if result['critical_invoices']:
    print(f"\n  Critical Invoices:")
    for inv in result['critical_invoices'][:5]:
        print(f"    - {inv['invoice_number']}: {inv['risk_score']}")

# ════════════════════════════════════════════════════════════════════════════════
# FINDINGS ANALYSIS
# ════════════════════════════════════════════════════════════════════════════════

# Get findings breakdown
breakdown = service.findings_breakdown(days=30)

print(f"""
Findings Analysis (Last 30 days):
  Total Findings: {breakdown['total_findings']}
  By Severity:
""")

for severity, count in breakdown['by_severity'].items():
    print(f"    - {severity}: {count}")

print(f"\n  By Category:")
for i, (category, count) in enumerate(breakdown['by_category'].items()):
    if i >= 5:
        print(f"    ... and {len(breakdown['by_category']) - 5} more")
        break
    print(f"    - {category}: {count}")

print(f"\n  By Status:")
for status, count in breakdown['by_status'].items():
    print(f"    - {status}: {count}")

print(f"\n  Unresolved: {breakdown['unresolved_count']}")
print(f"  Resolution Rate: {breakdown['resolution_rate_pct']}%")

# ════════════════════════════════════════════════════════════════════════════════
# RUNNING TESTS
# ════════════════════════════════════════════════════════════════════════════════

# Test files are located in:
#   tests/test_analytics_and_risk_optimization.py    (Main test suite)
#   tests/test_analytics_integration.py               (Integration tests)
#   tests/test_zip_and_race_conditions.py             (Advanced race condition tests)

# Run all tests:
# pytest tests/ -v

# Run specific test class:
# pytest tests/test_analytics_and_risk_optimization.py::TestAuditAnalyticsService -v

# Run with coverage:
# pytest tests/ --cov=apps/analytics --cov=core/services/scoring -v

# Run race condition tests:
# pytest tests/test_zip_and_race_conditions.py -v

# Run integration tests:
# pytest tests/test_analytics_integration.py -v

# Run slow tests (like performance tests):
# pytest tests/ -v -m slow

# ════════════════════════════════════════════════════════════════════════════════
# CONCURRENT OPERATIONS EXAMPLE
# ════════════════════════════════════════════════════════════════════════════════

import threading
from concurrent.futures import ThreadPoolExecutor

# Thread-safe batch processing
def process_batches_parallel(batch_ids, num_workers=4):
    service = RiskOptimizationService()
    results = []
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(service.score_zip_batch, bid): bid 
            for bid in batch_ids
        }
        
        for future in futures:
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"Error processing batch: {e}")
    
    return results

# Example usage:
# batches = InvoiceBatch.objects.all()[:10]
# batch_ids = [str(b.id) for b in batches]
# results = process_batches_parallel(batch_ids, num_workers=4)

# ════════════════════════════════════════════════════════════════════════════════
# CACHING & PERFORMANCE OPTIMIZATION
# ════════════════════════════════════════════════════════════════════════════════

# With caching enabled (default):
service = RiskOptimizationService(use_cache=True)

# First call: Computes and caches
result1 = service.score_zip_batch(batch_id)
print(f"First call - Cached: {result1['cached']}")  # False

# Second call: Returns cached result
result2 = service.score_zip_batch(batch_id)
print(f"Second call - Cached: {result2['cached']}")  # True

# Manually clear cache
service.clear_cache(batch_id=batch_id)

# Third call: Recomputes
result3 = service.score_zip_batch(batch_id)
print(f"Third call - Cached: {result3['cached']}")  # False

# ════════════════════════════════════════════════════════════════════════════════
# ERROR HANDLING
# ════════════════════════════════════════════════════════════════════════════════

from apps.analytics.analytics_service import SessionNotFoundError

service = AuditAnalyticsService()

try:
    stats = service.session_statistics("non-existent-id")
except SessionNotFoundError:
    print("Session not found!")

try:
    result = service.score_zip_batch("non-existent-id")
except ValueError as e:
    print(f"Batch error: {e}")

# ════════════════════════════════════════════════════════════════════════════════
# PERFORMANCE TIPS
# ════════════════════════════════════════════════════════════════════════════════

# 1. Use caching for frequently accessed metrics
service = RiskOptimizationService(use_cache=True)

# 2. Batch operations together
batch_ids = [str(b.id) for b in InvoiceBatch.objects.all()]
for batch_id in batch_ids:
    result = service.score_zip_batch(batch_id)

# 3. For large result sets, consider pagination
large_org_summary = service.organization_summary(days=90)

# 4. Clear cache periodically if data changes frequently
service.clear_cache()

# 5. Use read-only replica if available for analytics
# This is handled at Django ORM level with database routing

# ════════════════════════════════════════════════════════════════════════════════
# TROUBLESHOOTING
# ════════════════════════════════════════════════════════════════════════════════

# Issue: Inconsistent risk scores
# Solution: Clear cache and recompute
# service.clear_cache()
# service.update_session_risk_scores(session_id)

# Issue: High memory usage
# Solution: Use iterator for large querysets
# from django.db.models import QuerySet
# invoices = Invoice.objects.filter(batch=batch).iterator(chunk_size=1000)

# Issue: Slow queries
# Solution: Check database indexes
# from django.db import connection
# from django.test.utils import override_settings
# 
# with override_settings(DEBUG=True):
#     result = service.organization_summary(days=30)
#     print(connection.queries[-1])

# Issue: Race conditions in tests
# Solution: Use TransactionTestCase
# from django.test import TransactionTestCase
# 
# class MyTest(TransactionTestCase):
#     def test_concurrent_updates(self): ...

# ════════════════════════════════════════════════════════════════════════════════
# FOR MORE INFORMATION
# ════════════════════════════════════════════════════════════════════════════════

# Read the full documentation:
# - ANALYTICS_AND_RISK_SERVICES_DOC.py
#
# Check the test files for comprehensive examples:
# - tests/test_analytics_and_risk_optimization.py
# - tests/test_analytics_integration.py
# - tests/test_zip_and_race_conditions.py
#
# Service source code:
# - apps/analytics/analytics_service.py
# - core/services/scoring/risk_optimization_service.py
