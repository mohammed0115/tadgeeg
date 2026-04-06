"""
Explainable anomaly detector for financial documents.

This adapter reuses the rule-engine anomaly logic so the Financial AI pipeline
can produce the same explainable anomaly output for invoices, purchase orders,
payments, and similar financial documents.

Detections include:
- price anomalies vs historical averages (z-score, IQR)
- duplicate patterns
- unusual submission frequency
- vendor anomalies
- optional Isolation Forest outlier detection
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from apps.rule_engine.risk.anomaly_engine import DocumentAnomalyDetector
from apps.rule_engine.rules.base import NormalizedDocument

logger = logging.getLogger("finai")


class AnomalyDetector:
    """JSON-friendly anomaly detector used by the FinancialAIEngine."""

    DOC_TYPE_MAP = {
        "invoice": "sales_invoice",
        "sales_invoice": "sales_invoice",
        "purchase_order": "purchase_order",
        "po": "purchase_order",
        "payment": "payment",
        "payment_voucher": "payment",
        "bank_statement": "bank_statement",
    }

    def __init__(self, organization_id: int = None, enable_ml: bool = True):
        self.organization_id = organization_id
        self._detector = DocumentAnomalyDetector(enable_ml=enable_ml)

    def detect(
        self,
        document: Optional[dict],
        vendor_context: Optional[dict] = None,
        history_context: Optional[dict] = None,
    ) -> dict:
        """Return anomaly_score (0–100), explanation, and explainable findings."""
        document = document or {}
        normalized_doc = self._to_normalized_document(document)

        vendor_context = vendor_context or self._build_vendor_context(document)
        history_context = history_context or self._build_history_context(document)

        analysis = self._detector.analyze(
            normalized_doc,
            vendor_context=vendor_context,
            history_context=history_context,
        )
        payload = analysis.to_dict()
        payload["requires_review"] = bool(payload.get("anomaly_score", 0) >= 40)
        payload["primary_drivers"] = [
            {
                "code": finding.get("code"),
                "severity": finding.get("severity"),
                "contribution": finding.get("contribution"),
                "description": finding.get("description"),
            }
            for finding in payload.get("findings", [])[:3]
        ]
        return payload

    def _to_normalized_document(self, document: dict) -> NormalizedDocument:
        typed_data = {
            "is_duplicate": bool(document.get("is_duplicate", False)),
            "duplicate_of_id": document.get("duplicate_of_id") or document.get("duplicate_of"),
            "metadata": document.get("metadata", {}),
        }

        if document.get("matched_document_ids"):
            typed_data["matched_document_ids"] = list(document.get("matched_document_ids") or [])

        return NormalizedDocument(
            document_id=str(document.get("document_id") or document.get("id") or "unknown"),
            document_type=self.DOC_TYPE_MAP.get(str(document.get("document_type") or "").lower(), "sales_invoice"),
            organization_id=str(document.get("organization_id") or self.organization_id or ""),
            document_number=document.get("document_number") or document.get("invoice_number") or document.get("po_number"),
            document_date=self._coerce_date(document.get("date") or document.get("document_date") or document.get("invoice_date")),
            total_amount=self._safe_float(document.get("total_amount") or document.get("amount")),
            currency=document.get("currency"),
            counterparty_name=document.get("vendor_name") or document.get("supplier_name") or document.get("payee_name"),
            tax_id=document.get("vendor_vat_number") or document.get("tax_id"),
            approved_by_id=document.get("approved_by_id"),
            status=document.get("status"),
            typed_data=typed_data,
            org_context=document.get("org_context") or {},
        )

    def _build_vendor_context(self, document: dict) -> dict:
        vendor_name = str(
            document.get("vendor_name")
            or document.get("supplier_name")
            or document.get("payee_name")
            or ""
        ).strip()
        tax_id = str(document.get("vendor_vat_number") or document.get("tax_id") or "").strip()

        context = {
            "counterparty_name": vendor_name or tax_id or "unknown vendor",
            "is_approved": document.get("vendor_approved"),
            "flags": list(document.get("vendor_flags") or []),
            "risk_score": self._safe_float(document.get("vendor_risk_score") or document.get("risk_score")),
        }

        if self.organization_id and vendor_name:
            try:
                from apps.invoices.services.vendor_intelligence import VendorIntelligenceService

                db_context = VendorIntelligenceService().build_vendor_context(
                    organization_id=self.organization_id,
                    vendor_name=vendor_name,
                    tax_id=tax_id,
                )
                if db_context:
                    context.update({k: v for k, v in db_context.items() if v not in (None, "", [])})
            except Exception as exc:
                logger.debug("[AnomalyDetector] Vendor context lookup skipped: %s", exc)

        return context

    def _build_history_context(self, document: dict) -> dict:
        matched_ids = document.get("matched_document_ids") or []
        return {
            "peer_amounts": list(document.get("peer_amounts") or document.get("historical_amounts") or []),
            "recent_run_count": int(document.get("recent_run_count") or 0),
            "high_risk_count": int(document.get("high_risk_count") or 0),
            "lookback_days": int(document.get("lookback_days") or 90),
            "duplicate_documents": int(document.get("duplicate_documents") or len(matched_ids) or (1 if document.get("is_duplicate") else 0)),
            "same_amount_count": int(document.get("same_amount_count") or 0),
        }

    @staticmethod
    def _coerce_date(value: Any):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                try:
                    return date.fromisoformat(value)
                except ValueError:
                    return value
        return value

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
