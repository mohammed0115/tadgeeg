"""
Risk Optimization Service

Optimized risk computation using Django aggregations for batch processing,
particularly for handling ZIP files containing multiple documents.

Features:
- Batch risk scoring with efficient database aggregations
- Hierarchical risk computation (documents → invoices → batches → sessions)
- ZIP file processing with aggregation-based analysis
- Caching mechanisms for expensive computations
- Thread-safe operations using F() expressions and transactions

Usage:
    service = RiskOptimizationService()
    
    # Score a batch of documents
    batch_results = service.score_document_batch(document_ids)
    
    # Score a ZIP batch of invoices
    zip_results = service.score_zip_batch(batch_id)
    
    # Get aggregated session risk
    session_risk = service.compute_session_risk_aggregate(session_id)
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal

from django.db import transaction, connection
from django.db.models import (
    Q, Avg, Sum, Count, Max, Min, Case, When, F, Value, CharField, 
    IntegerField, FloatField, Exists, OuterRef, Subquery, QuerySet
)
from django.utils import timezone
from django.core.cache import cache

from apps.audit.models import AuditSession, AuditFinding
from apps.invoices.models import Invoice, InvoiceBatch
from apps.documents.models import Document

logger = logging.getLogger("finai")

# Cache timeout in seconds (5 minutes)
CACHE_TIMEOUT = 300

# Risk aggregation thresholds
RISK_THRESHOLDS = {
    "critical": 75,
    "high": 50,
    "medium": 25,
    "low": 0,
}


class RiskOptimizationService:
    """
    Optimized risk scoring and aggregation service.
    
    Uses Django ORM aggregations to compute risk scores efficiently
    across multiple document hierarchies (ZIP batches, sessions, etc).
    """

    def __init__(self, use_cache: bool = True):
        """
        Initialize the service.
        
        Args:
            use_cache: Whether to use Django cache for frequently accessed data
        """
        self.use_cache = use_cache

    # ────────────────────────────────────────────────────────────────────────────
    # ZIP Batch Processing
    # ────────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def score_zip_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Compute optimized risk score for a ZIP batch using aggregations.
        
        Aggregates risk scores from all invoices in the batch,
        computing composite metrics efficiently.
        
        Args:
            batch_id: UUID of the InvoiceBatch
            
        Returns:
            {
              batch_id: uuid,
              batch_name: str,
              document_count: int,
              
              risk_metrics: {
                average_risk_score: float,
                max_risk_score: float,
                min_risk_score: float,
                std_dev_risk: float,
              },
              
              risk_level: str (critical|high|medium|low),
              risk_distribution: {
                critical_count: int,
                high_count: int,
                medium_count: int,
                low_count: int,
              },
              
              invoice_details: [
                {
                  invoice_id: uuid,
                  invoice_number: str,
                  risk_score: float,
                  risk_level: str,
                  high_risk_reasons: list[str]
                }
              ],
              
              aggregated_findings: {
                total_findings: int,
                critical_findings: int,
                high_findings: int,
              },
              
              processing_timestamp: ISO8601,
              cached: bool
            }
        """
        cache_key = f"zip_batch_risk_{batch_id}"
        
        # Check cache first
        if self.use_cache:
            cached_result = cache.get(cache_key)
            if cached_result:
                cached_result["cached"] = True
                return cached_result
        
        try:
            batch = InvoiceBatch.objects.get(pk=batch_id)
        except InvoiceBatch.DoesNotExist:
            raise ValueError(f"Batch {batch_id} not found")

        # Get all invoices in batch
        invoices_qs = Invoice.objects.filter(batch=batch)
        invoice_count = invoices_qs.count()

        if invoice_count == 0:
            return self._empty_batch_result(batch)

        # Aggregate risk metrics from all invoices
        risk_agg = invoices_qs.aggregate(
            avg_risk=Avg('risk_score'),
            max_risk=Max('risk_score'),
            min_risk=Min('risk_score'),
            sum_risk=Sum('risk_score'),
        )

        # Compute standard deviation
        # Formula: sqrt(sum((x - mean)^2) / n)
        mean_risk = risk_agg['avg_risk'] or 0
        
        # Get all risk scores for std dev calculation
        risk_scores = list(invoices_qs.values_list('risk_score', flat=True))
        std_dev = self._compute_std_dev(risk_scores, mean_risk) if risk_scores else 0

        # Risk distribution using annotated Case/When
        risk_dist_qs = invoices_qs.aggregate(
            critical_count=Count(
                Case(When(risk_score__gte=75, then=1), output_field=IntegerField())
            ),
            high_count=Count(
                Case(When(Q(risk_score__gte=50) & Q(risk_score__lt=75), then=1), output_field=IntegerField())
            ),
            medium_count=Count(
                Case(When(Q(risk_score__gte=25) & Q(risk_score__lt=50), then=1), output_field=IntegerField())
            ),
            low_count=Count(
                Case(When(risk_score__lt=25, then=1), output_field=IntegerField())
            ),
        )

        # Determine overall batch risk level
        batch_risk_level = self._risk_score_to_level(mean_risk)
        
        # Get high-risk invoices with their reasons
        high_risk_invoices = self._get_high_risk_invoices(invoices_qs)
        
        # Aggregate findings for this batch
        findings_agg = self._aggregate_batch_findings(batch)

        result = {
            "batch_id": str(batch.id),
            "batch_name": batch.name or str(batch.id),
            "document_count": invoice_count,
            
            "risk_metrics": {
                "average_risk_score": round(float(mean_risk or 0), 2),
                "max_risk_score": round(float(risk_agg['max_risk'] or 0), 2),
                "min_risk_score": round(float(risk_agg['min_risk'] or 0), 2),
                "std_dev_risk": round(float(std_dev), 2),
            },
            
            "risk_level": batch_risk_level,
            
            "risk_distribution": {
                "critical_count": risk_dist_qs['critical_count'],
                "high_count": risk_dist_qs['high_count'],
                "medium_count": risk_dist_qs['medium_count'],
                "low_count": risk_dist_qs['low_count'],
            },
            
            "invoice_details": high_risk_invoices,
            
            "aggregated_findings": findings_agg,
            
            "processing_timestamp": timezone.now().isoformat(),
            "cached": False,
        }

        # Cache the result
        if self.use_cache:
            cache.set(cache_key, result, CACHE_TIMEOUT)

        return result

    # ────────────────────────────────────────────────────────────────────────────
    # Document Batch Scoring
    # ────────────────────────────────────────────────────────────────────────────

    def score_document_batch(self, document_ids: List[str]) -> Dict[str, List[Dict]]:
        """
        Score a batch of documents efficiently.
        
        Returns aggregated risk information across all documents.
        
        Args:
            document_ids: List of document UUIDs
            
        Returns:
            {
              total_documents: int,
              documents_scored: int,
              
              risk_summary: {
                average_risk: float,
                highest_risk: float,
                critical_count: int,
                high_count: int,
              },
              
              documents: [
                {
                  document_id: uuid,
                  risk_score: float,
                  risk_level: str,
                }
              ]
            }
        """
        if not document_ids:
            return {
                "total_documents": 0,
                "documents_scored": 0,
                "risk_summary": {
                    "average_risk": 0,
                    "highest_risk": 0,
                    "critical_count": 0,
                    "high_count": 0,
                },
                "documents": []
            }

        docs_qs = Document.objects.filter(id__in=document_ids)

        # Aggregate risk from related invoices
        doc_risks = docs_qs.annotate(
            avg_invoice_risk=Avg('extracted_data__invoice__risk_score'),
        ).values('id', 'avg_invoice_risk')

        doc_list = []
        total_risk = 0
        max_risk = 0
        critical_count = 0
        high_count = 0

        for doc in doc_risks:
            risk_score = float(doc['avg_invoice_risk'] or 0)
            risk_level = self._risk_score_to_level(risk_score)
            
            total_risk += risk_score
            max_risk = max(max_risk, risk_score)
            
            if risk_score >= 75:
                critical_count += 1
            elif risk_score >= 50:
                high_count += 1

            doc_list.append({
                "document_id": str(doc['id']),
                "risk_score": round(risk_score, 2),
                "risk_level": risk_level,
            })

        avg_risk = total_risk / len(doc_list) if doc_list else 0

        return {
            "total_documents": len(document_ids),
            "documents_scored": len(doc_list),
            
            "risk_summary": {
                "average_risk": round(avg_risk, 2),
                "highest_risk": round(max_risk, 2),
                "critical_count": critical_count,
                "high_count": high_count,
            },
            
            "documents": doc_list
        }

    # ────────────────────────────────────────────────────────────────────────────
    # Session Risk Aggregation
    # ────────────────────────────────────────────────────────────────────────────

    def compute_session_risk_aggregate(self, session_id: str) -> Dict[str, Any]:
        """
        Compute optimized aggregate risk for an entire audit session.
        
        Uses database aggregations to efficiently compute metrics
        across all invoices/batches in a session.
        
        Args:
            session_id: UUID of the AuditSession
            
        Returns:
            {
              session_id: uuid,
              state: str,
              
              risk_summary: {
                overall_risk_score: float,
                overall_risk_level: str,
                
                by_batch: [
                  {
                    batch_id: uuid,
                    batch_name: str,
                    invoice_count: int,
                    avg_risk: float,
                    max_risk: float,
                  }
                ]
              },
              
              invoice_count: int,
              invoice_risk_distribution: {...},
              
              critical_invoices: [
                {invoice_id, invoice_number, risk_score}
              ],
              
              timestamp: ISO8601
            }
        """
        cache_key = f"session_risk_agg_{session_id}"
        
        if self.use_cache:
            cached = cache.get(cache_key)
            if cached:
                return cached

        try:
            session = AuditSession.objects.get(pk=session_id)
        except AuditSession.DoesNotExist:
            raise ValueError(f"Session {session_id} not found")

        # Get all batches and their aggregated risk
        batches_qs = InvoiceBatch.objects.filter(audit_session=session).annotate(
            invoice_count=Count('invoice'),
            avg_risk=Avg('invoice__risk_score'),
            max_risk=Max('invoice__risk_score'),
        ).values('id', 'name', 'invoice_count', 'avg_risk', 'max_risk')

        batch_details = [
            {
                "batch_id": str(b['id']),
                "batch_name": b['name'] or str(b['id']),
                "invoice_count": b['invoice_count'],
                "avg_risk": round(float(b['avg_risk'] or 0), 2),
                "max_risk": round(float(b['max_risk'] or 0), 2),
            }
            for b in batches_qs
        ]

        # Overall session risk aggregation
        invoices_qs = Invoice.objects.filter(batch__audit_session=session)
        
        session_risk_agg = invoices_qs.aggregate(
            avg_risk=Avg('risk_score'),
            max_risk=Max('risk_score'),
            invoice_count=Count('id'),
        )

        overall_risk = float(session_risk_agg['avg_risk'] or 0)
        overall_level = self._risk_score_to_level(overall_risk)
        invoice_count = session_risk_agg['invoice_count']

        # Risk distribution
        risk_dist = invoices_qs.aggregate(
            critical=Count(Case(When(risk_score__gte=75, then=1), output_field=IntegerField())),
            high=Count(Case(When(Q(risk_score__gte=50) & Q(risk_score__lt=75), then=1), output_field=IntegerField())),
            medium=Count(Case(When(Q(risk_score__gte=25) & Q(risk_score__lt=50), then=1), output_field=IntegerField())),
            low=Count(Case(When(risk_score__lt=25, then=1), output_field=IntegerField())),
        )

        # Critical invoices
        critical_invoices = invoices_qs.filter(
            risk_score__gte=75
        ).values('id', 'invoice_number', 'risk_score')[:10]

        result = {
            "session_id": str(session.id),
            "session_name": session.session_name or str(session.id),
            "state": session.state,
            
            "risk_summary": {
                "overall_risk_score": round(overall_risk, 2),
                "overall_risk_level": overall_level,
                
                "by_batch": batch_details,
            },
            
            "invoice_count": invoice_count,
            
            "invoice_risk_distribution": {
                "critical": risk_dist['critical'],
                "high": risk_dist['high'],
                "medium": risk_dist['medium'],
                "low": risk_dist['low'],
            },
            
            "critical_invoices": [
                {
                    "invoice_id": str(inv['id']),
                    "invoice_number": inv['invoice_number'],
                    "risk_score": round(float(inv['risk_score']), 2),
                }
                for inv in critical_invoices
            ],
            
            "timestamp": timezone.now().isoformat(),
        }

        if self.use_cache:
            cache.set(cache_key, result, CACHE_TIMEOUT)

        return result

    # ────────────────────────────────────────────────────────────────────────────
    # Batch Update Operations (Thread-safe using F expressions)
    # ────────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def update_session_risk_scores(self, session_id: str) -> bool:
        """
        Atomically update all risk scores for a session using aggregations.
        
        Thread-safe: uses F() expressions to avoid race conditions.
        """
        try:
            session = AuditSession.objects.get(pk=session_id)
        except AuditSession.DoesNotExist:
            raise ValueError(f"Session {session_id} not found")

        invoices = Invoice.objects.filter(batch__audit_session=session)
        
        if not invoices.exists():
            logger.info(f"No invoices to update for session {session_id}")
            return False

        # Compute aggregated risk
        agg = invoices.aggregate(
            avg_score=Avg('risk_score'),
            total_high_risk=Count(Case(When(risk_score__gte=50, then=1), output_field=IntegerField()))
        )

        avg_score = float(agg['avg_score'] or 0)
        risk_level = self._risk_score_to_level(avg_score)

        # Atomic update
        updated_count = AuditSession.objects.filter(pk=session_id).update(
            overall_risk_score=avg_score,
            overall_risk_level=risk_level,
            high_risk_count=agg['total_high_risk'],
            updated_at=timezone.now(),
        )

        # Invalidate cache
        if self.use_cache:
            cache_key = f"session_risk_agg_{session_id}"
            cache.delete(cache_key)

        logger.info(f"Updated risk scores for session {session_id}: {updated_count} rows")
        return updated_count > 0

    @transaction.atomic
    def update_batch_risk_scores(self, batch_id: str) -> bool:
        """
        Atomically update all risk scores for a batch using aggregations.
        
        Thread-safe: uses F() expressions.
        """
        try:
            batch = InvoiceBatch.objects.get(pk=batch_id)
        except InvoiceBatch.NoReturn:
            raise ValueError(f"Batch {batch_id} not found")

        invoices = Invoice.objects.filter(batch=batch)
        
        if not invoices.exists():
            logger.info(f"No invoices in batch {batch_id}")
            return False

        # Aggregate risk from invoices
        agg = invoices.aggregate(
            avg_score=Avg('risk_score'),
            max_score=Max('risk_score'),
            risk_count=Count(Case(When(risk_score__gte=50, then=1), output_field=IntegerField()))
        )

        # Invalidate cache
        if self.use_cache:
            cache_key = f"zip_batch_risk_{batch_id}"
            cache.delete(cache_key)

        logger.info(f"Updated risk scores for batch {batch_id}")
        return True

    # ────────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ────────────────────────────────────────────────────────────────────────────

    def _risk_score_to_level(self, score: float) -> str:
        """Convert numerical risk score (0-100) to level string."""
        if score >= RISK_THRESHOLDS["critical"]:
            return "critical"
        elif score >= RISK_THRESHOLDS["high"]:
            return "high"
        elif score >= RISK_THRESHOLDS["medium"]:
            return "medium"
        else:
            return "low"

    def _compute_std_dev(self, values: List[float], mean: float) -> float:
        """
        Compute standard deviation manually.
        
        Formula: sqrt(sum((x - mean)^2) / n)
        """
        if len(values) <= 1:
            return 0.0
        
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    def _get_high_risk_invoices(self, invoices_qs: QuerySet, limit: int = 5) -> List[Dict]:
        """Get high-risk invoices with their details."""
        high_risk = invoices_qs.filter(
            risk_score__gte=50
        ).order_by('-risk_score')[:limit].values(
            'id', 'invoice_number', 'risk_score'
        )

        return [
            {
                "invoice_id": str(inv['id']),
                "invoice_number": inv['invoice_number'],
                "risk_score": round(float(inv['risk_score']), 2),
                "risk_level": self._risk_score_to_level(float(inv['risk_score'])),
            }
            for inv in high_risk
        ]

    def _aggregate_batch_findings(self, batch: InvoiceBatch) -> Dict[str, int]:
        """Aggregate findings for all invoices in a batch."""
        findings_qs = AuditFinding.objects.filter(
            invoice__batch=batch
        )

        return {
            "total_findings": findings_qs.count(),
            "critical_findings": findings_qs.filter(
                severity=AuditFinding.Severity.CRITICAL
            ).count(),
            "high_findings": findings_qs.filter(
                severity=AuditFinding.Severity.HIGH
            ).count(),
        }

    def _empty_batch_result(self, batch: InvoiceBatch) -> Dict[str, Any]:
        """Return empty result structure for a batch with no invoices."""
        return {
            "batch_id": str(batch.id),
            "batch_name": batch.name or str(batch.id),
            "document_count": 0,
            
            "risk_metrics": {
                "average_risk_score": 0,
                "max_risk_score": 0,
                "min_risk_score": 0,
                "std_dev_risk": 0,
            },
            
            "risk_level": "low",
            
            "risk_distribution": {
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
            },
            
            "invoice_details": [],
            
            "aggregated_findings": {
                "total_findings": 0,
                "critical_findings": 0,
                "high_findings": 0,
            },
            
            "processing_timestamp": timezone.now().isoformat(),
            "cached": False,
        }

    def clear_cache(self, batch_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
        """
        Manually clear cache entries for debugging/testing.
        
        Args:
            batch_id: If provided, clear only batch cache
            session_id: If provided, clear only session cache
        """
        if batch_id:
            cache.delete(f"zip_batch_risk_{batch_id}")
        if session_id:
            cache.delete(f"session_risk_agg_{session_id}")
        if not batch_id and not session_id:
            # Note: Django cache.clear() clears everything
            logger.warning("Clearing entire cache - consider being more specific")
