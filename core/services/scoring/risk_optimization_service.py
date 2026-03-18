"""Compatibility batch risk scoring service used by legacy tests and callers."""

from __future__ import annotations

from django.core.cache import cache
from django.db.models import Avg, Max, Min

from apps.invoices.models import Invoice, InvoiceBatch


class RiskOptimizationService:
    """Score invoice batches with optional caching and deterministic aggregates."""

    def __init__(self, *, use_cache: bool = True, cache_timeout: int = 60):
        self.use_cache = use_cache
        self.cache_timeout = cache_timeout

    def _cache_key(self, batch_id: str) -> str:
        return f"risk-optimization:batch:{batch_id}"

    def clear_cache(self, *, batch_id: str) -> None:
        cache.delete(self._cache_key(batch_id))

    def score_zip_batch(self, batch_id: str) -> dict:
        cache_key = self._cache_key(batch_id)
        if self.use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return {**cached, "cached": True}

        batch = InvoiceBatch.objects.get(pk=batch_id)
        invoices = Invoice.objects.filter(batch=batch)
        metrics = invoices.aggregate(
            avg_score=Avg("risk_score"),
            max_score=Max("risk_score"),
            min_score=Min("risk_score"),
        )

        result = {
            "batch_id": str(batch.id),
            "document_count": invoices.count(),
            "risk_metrics": {
                "average_risk_score": float(metrics["avg_score"] or 0.0),
                "max_risk_score": float(metrics["max_score"] or 0.0),
                "min_risk_score": float(metrics["min_score"] or 0.0),
            },
            "cached": False,
        }

        if self.use_cache:
            cache.set(cache_key, {k: v for k, v in result.items() if k != "cached"}, self.cache_timeout)
        return result
