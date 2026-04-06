"""
Compatibility wrapper around the dynamic `RiskEngine`.

Historically the pipeline called `RiskAggregator.compute(results, assignments)`.
To preserve that interface while fixing under-scoring of critical documents,
this adapter now delegates to the explainable, contextual `RiskEngine`.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

from django.utils import timezone

from apps.rule_engine.risk.risk_engine import RiskEngine

logger = logging.getLogger("rule_engine")


class RiskAggregator:
    """
    Backward-compatible adapter for the dynamic risk scoring engine.

    Optional contextual inputs let callers enrich the score with document amount,
    approval state, vendor posture, and behavioral history without breaking the
    older `(results, assignments)` call pattern.
    """

    def __init__(self, engine: Optional[RiskEngine] = None):
        self.engine = engine or RiskEngine()

    def compute(
        self,
        results: list,
        assignments: list,
        normalized_doc=None,
        vendor_context: Optional[dict] = None,
        history_context: Optional[dict] = None,
        erp_context: Optional[dict] = None,
    ) -> dict:
        vendor_context = vendor_context if vendor_context is not None else self._derive_vendor_context(normalized_doc)
        history_context = history_context if history_context is not None else self._derive_history_context(normalized_doc)

        context = SimpleNamespace(
            normalized_doc=normalized_doc,
            rule_results=results or [],
            rule_assignments=assignments or [],
            vendor_context=vendor_context or {},
            history_context=history_context or {},
            erp_context=erp_context or {},
        )
        return self.engine.compute(context).to_dict()

    def _derive_vendor_context(self, normalized_doc) -> dict:
        if normalized_doc is None:
            return {}

        try:
            from apps.invoices.services.vendor_intelligence import VendorIntelligenceService

            vendor_name = str(
                getattr(normalized_doc, "counterparty_name", None)
                or normalized_doc.get("vendor_name")
                or normalized_doc.get("payee_name")
                or ""
            ).strip()
            vendor_tax_id = str(
                getattr(normalized_doc, "tax_id", None)
                or normalized_doc.get("vendor_vat_number")
                or normalized_doc.get("payee_vat_number")
                or ""
            ).strip()

            vendor_context = VendorIntelligenceService().build_vendor_context(
                organization_id=normalized_doc.organization_id,
                vendor_name=vendor_name,
                tax_id=vendor_tax_id,
            )
            if vendor_context:
                return vendor_context

            approved_registry = {
                str(value).strip().lower()
                for value in (normalized_doc.get_org("approved_vendor_ids") or [])
                if str(value).strip()
            }
            blocked_registry = {
                str(value).strip().lower()
                for value in (normalized_doc.get_org("blocked_vendor_ids") or [])
                if str(value).strip()
            }
            identifiers = [value.lower() for value in (vendor_name, vendor_tax_id) if value]
            is_approved = None
            if identifiers and any(value in approved_registry for value in identifiers):
                is_approved = True
            elif identifiers and any(value in blocked_registry for value in identifiers):
                is_approved = False

            flags = []
            if identifiers and any(value in blocked_registry for value in identifiers):
                flags.append("blocked_vendor")

            prior_risk = self._safe_float(normalized_doc.get("risk_score"))
            if prior_risk is not None and prior_risk >= 70:
                flags.append("historically_high_risk")

            return {
                "is_approved": is_approved,
                "flags": flags,
                "counterparty_name": vendor_name or vendor_tax_id or "unknown",
                "risk_score": prior_risk,
            }
        except Exception as exc:
            logger.debug("[RiskAggregator] Vendor context derivation skipped: %s", exc)
            return {}

    def _derive_history_context(self, normalized_doc) -> dict:
        if normalized_doc is None:
            return {}

        try:
            from apps.rule_engine.models import AuditRun

            lookback_days = 90
            since = timezone.now() - timedelta(days=lookback_days)
            qs = AuditRun.objects.filter(
                organization_id=normalized_doc.organization_id,
                document_type=normalized_doc.document_type,
                started_at__gte=since,
            )
            return {
                "recent_run_count": qs.count(),
                "high_risk_count": qs.filter(risk_level__in=["high", "critical"]).count(),
                "lookback_days": lookback_days,
            }
        except Exception as exc:
            logger.debug("[RiskAggregator] History context derivation skipped: %s", exc)
            return {}

    @staticmethod
    def _safe_float(value):
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

