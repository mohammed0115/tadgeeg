"""Vendor Intelligence service layer.

Purpose
-------
Maintain a tenant-isolated supplier intelligence profile that can be reused by
risk scoring, anomaly detection, dashboards, and audit reports.

Usage example
-------------
    from apps.invoices.services.vendor_intelligence import VendorIntelligenceService

    service = VendorIntelligenceService()
    profile = service.update_after_audit(normalized_doc, risk_data)
    vendor_ctx = service.build_vendor_context(
        organization_id=normalized_doc.organization_id,
        vendor_name=normalized_doc.counterparty_name,
        tax_id=normalized_doc.tax_id,
    )
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Avg, Count, Max, Q, Sum
from django.utils import timezone

from apps.invoices.models import Invoice, VendorProfile
from apps.rule_engine.rules.base import NormalizedDocument

logger = logging.getLogger("vendor_intelligence")


@dataclass
class VendorRiskScore:
    """Explainable vendor risk output consumed by the RiskEngine."""

    score: float
    tier: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "tier": self.tier,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


class VendorIntelligenceService:
    """Creates and updates `VendorProfile` records after each audit."""

    RECENT_WINDOW_DAYS = 30
    HIGH_RISK_THRESHOLD = 70.0
    BLOCK_THRESHOLD = 85.0
    LARGE_AMOUNT_REFERENCE = 100000.0

    def update_after_audit(self, normalized_doc: Optional[NormalizedDocument], risk_data: Optional[dict] = None) -> Optional[VendorProfile]:
        risk_data = risk_data or {}
        if not normalized_doc or not getattr(normalized_doc, "counterparty_name", None):
            return None

        vendor_name = str(normalized_doc.counterparty_name or "").strip()
        organization_id = getattr(normalized_doc, "organization_id", None)
        if not vendor_name or not organization_id:
            return None

        existing = VendorProfile.objects.filter(
            organization_id=organization_id,
            vendor_name__iexact=vendor_name,
        ).first()

        invoice_metrics = self._collect_invoice_metrics(organization_id, vendor_name)
        transaction_history = self._build_transaction_history(existing, normalized_doc, risk_data)
        compliance_history, compliance_issue_count = self._build_compliance_history(existing, risk_data)
        frequency_30d = self._frequency_from_history(transaction_history)
        high_risk_audit_count = self._calculate_high_risk_audit_count(existing, risk_data)
        is_approved = self._derive_approval_state(normalized_doc, existing)
        tags = self._derive_tags(existing, risk_data, is_approved)

        score_result = self.calculate_vendor_risk(
            invoice_metrics=invoice_metrics,
            compliance_issue_count=compliance_issue_count,
            frequency_30d=frequency_30d,
            risk_data=risk_data,
            is_approved=is_approved,
            tags=tags,
        )

        current_doc_date = self._coerce_date(getattr(normalized_doc, "document_date", None)) or timezone.now().date()
        current_amount = self._safe_decimal(getattr(normalized_doc, "total_amount", 0))

        defaults = {
            "vendor_vat_number": str(getattr(normalized_doc, "tax_id", None) or normalized_doc.get("vendor_vat_number") or "").strip(),
            "vendor_cr_number": str(normalized_doc.get("vendor_cr_number") or "").strip(),
            "invoice_count": invoice_metrics["invoice_count"],
            "total_amount": invoice_metrics["total_amount"],
            "avg_invoice_amount": invoice_metrics["avg_invoice_amount"],
            "max_invoice_amount": max(invoice_metrics["max_invoice_amount"], current_amount),
            "duplicate_count": invoice_metrics["duplicate_count"],
            "flagged_count": invoice_metrics["flagged_count"],
            "is_new": invoice_metrics["invoice_count"] <= 1 and transaction_history.get("document_counts_total", 1) <= 1,
            "is_suspicious": score_result.score >= self.HIGH_RISK_THRESHOLD or bool(tags),
            "is_approved": is_approved,
            "risk_score": round(score_result.score, 2),
            "risk_tier": score_result.tier,
            "risk_notes": " | ".join(score_result.reasons),
            "tags": tags,
            "transaction_frequency_30d": frequency_30d,
            "compliance_issue_count": compliance_issue_count,
            "high_risk_audit_count": high_risk_audit_count,
            "last_transaction_amount": current_amount,
            "transaction_history": transaction_history,
            "compliance_history": compliance_history,
            "last_audit_at": timezone.now(),
            "last_compliance_issue_at": timezone.now() if compliance_issue_count else (existing.last_compliance_issue_at if existing else None),
            "last_seen": current_doc_date,
        }

        profile, _ = VendorProfile.objects.update_or_create(
            organization_id=organization_id,
            vendor_name=vendor_name,
            defaults=defaults,
        )

        if not profile.first_seen:
            profile.first_seen = current_doc_date
            profile.save(update_fields=["first_seen"])

        profile.refresh_from_db()
        return profile

    def update_from_invoice(self, organization, invoice: Invoice) -> Optional[VendorProfile]:
        """Backward-compatible helper for existing invoice upload flow."""
        if not invoice or not invoice.vendor_name:
            return None

        normalized_doc = NormalizedDocument(
            document_id=str(invoice.id),
            document_type="sales_invoice",
            organization_id=str(getattr(organization, "id", organization)),
            document_number=invoice.invoice_number,
            document_date=invoice.invoice_date,
            total_amount=float(invoice.total_amount or 0),
            currency=invoice.currency,
            counterparty_name=invoice.vendor_name,
            tax_id=invoice.vendor_vat_number,
            approved_by_id=str(invoice.approved_by_id) if invoice.approved_by_id else None,
            typed_data={
                "vendor_name": invoice.vendor_name,
                "vendor_vat_number": invoice.vendor_vat_number,
                "vendor_cr_number": getattr(invoice, "vendor_cr_number", ""),
                "is_duplicate": invoice.is_duplicate,
            },
        )
        risk_data = {
            "risk_score": float(invoice.risk_score or 0),
            "risk_level": invoice.risk_level or "low",
            "anomaly_score": float(invoice.risk_score or 0) if invoice.is_duplicate else 0.0,
            "top_failed_rules": [],
            "anomaly_findings": ([{"code": "duplicate_pattern"}] if invoice.is_duplicate else []),
        }
        return self.update_after_audit(normalized_doc, risk_data)

    def build_vendor_context(self, organization_id, vendor_name: str, tax_id: str | None = None) -> dict:
        vendor_name = str(vendor_name or "").strip()
        tax_id = str(tax_id or "").strip()
        if not organization_id or not vendor_name:
            return {}

        qs = VendorProfile.objects.filter(organization_id=organization_id, vendor_name__iexact=vendor_name)
        profile = qs.first()
        if not profile and tax_id:
            profile = VendorProfile.objects.filter(
                organization_id=organization_id,
                vendor_vat_number=tax_id,
            ).first()
        if not profile:
            return {}

        flags = list(profile.tags or [])
        if profile.is_suspicious and "suspicious_vendor" not in flags:
            flags.append("suspicious_vendor")
        if profile.risk_tier == VendorProfile.RiskTier.BLOCKED and "blocked_vendor" not in flags:
            flags.append("blocked_vendor")
        elif profile.risk_tier == VendorProfile.RiskTier.HIGH and "high_risk_vendor" not in flags:
            flags.append("high_risk_vendor")

        return {
            "counterparty_name": profile.vendor_name,
            "tax_id": profile.vendor_vat_number,
            "risk_score": float(profile.risk_score or 0),
            "vendor_risk_score": float(profile.risk_score or 0),
            "risk_tier": profile.risk_tier,
            "is_approved": profile.is_approved,
            "flags": flags,
            "transaction_count": profile.invoice_count,
            "average_transaction_value": float(profile.avg_invoice_amount or 0),
            "frequency_30d": float(profile.transaction_frequency_30d or 0),
            "compliance_issue_count": int(profile.compliance_issue_count or 0),
            "high_risk_audit_count": int(profile.high_risk_audit_count or 0),
            "last_seen": profile.last_seen.isoformat() if profile.last_seen else None,
        }

    def calculate_vendor_risk(
        self,
        *,
        invoice_metrics: dict,
        compliance_issue_count: int,
        frequency_30d: float,
        risk_data: dict,
        is_approved: Optional[bool],
        tags: list[str],
    ) -> VendorRiskScore:
        invoice_count = max(int(invoice_metrics.get("invoice_count") or 0), 1)
        flagged_count = int(invoice_metrics.get("flagged_count") or 0)
        duplicate_count = int(invoice_metrics.get("duplicate_count") or 0)
        avg_amount = self._safe_float(invoice_metrics.get("avg_invoice_amount")) or 0.0
        anomaly_score = self._safe_float(risk_data.get("anomaly_score")) or 0.0

        flagged_rate = flagged_count / invoice_count
        duplicate_rate = duplicate_count / invoice_count
        compliance_rate = compliance_issue_count / invoice_count
        frequency_factor = min(float(frequency_30d or 0) / 10.0, 1.0)
        amount_factor = min(avg_amount / self.LARGE_AMOUNT_REFERENCE, 1.0)

        score = (
            min(flagged_rate * 35.0, 35.0)
            + min(duplicate_rate * 20.0, 20.0)
            + min(compliance_rate * 20.0, 20.0)
            + min(anomaly_score * 0.15, 15.0)
            + min(frequency_factor * 10.0, 10.0)
            + min(amount_factor * 5.0, 5.0)
        )

        reasons: list[str] = []
        if flagged_count:
            reasons.append(f"flagged invoices: {flagged_count}/{invoice_count}")
        if duplicate_count:
            reasons.append(f"duplicates: {duplicate_count}/{invoice_count}")
        if compliance_issue_count:
            reasons.append(f"compliance issues: {compliance_issue_count}")
        if anomaly_score:
            reasons.append(f"latest anomaly score: {anomaly_score:.1f}")
        if frequency_30d:
            reasons.append(f"30d frequency: {frequency_30d:.1f}")

        if is_approved is False:
            score += 10.0
            reasons.append("vendor not approved")
        if any(flag in tags for flag in ("blocked_vendor", "sanctioned", "watchlist")):
            score += 15.0
            reasons.append("blocked/watchlist status")

        score = min(score, 100.0)
        if any(flag in tags for flag in ("blocked_vendor", "sanctioned")) or score >= self.BLOCK_THRESHOLD:
            tier = VendorProfile.RiskTier.BLOCKED
        elif score >= self.HIGH_RISK_THRESHOLD:
            tier = VendorProfile.RiskTier.HIGH
        elif score >= 40.0:
            tier = VendorProfile.RiskTier.MEDIUM
        else:
            tier = VendorProfile.RiskTier.LOW

        return VendorRiskScore(
            score=round(score, 2),
            tier=tier,
            reasons=reasons or ["stable vendor profile"],
            metrics={
                "invoice_count": invoice_count,
                "flagged_rate": round(flagged_rate, 3),
                "duplicate_rate": round(duplicate_rate, 3),
                "compliance_rate": round(compliance_rate, 3),
                "frequency_30d": round(float(frequency_30d or 0), 2),
                "avg_amount": round(avg_amount, 2),
            },
        )

    def _collect_invoice_metrics(self, organization_id, vendor_name: str) -> dict:
        stats = Invoice.objects.filter(
            organization_id=organization_id,
            vendor_name__iexact=vendor_name,
            is_deleted=False,
        ).aggregate(
            cnt=Count("id"),
            total=Sum("total_amount"),
            avg=Avg("total_amount"),
            max_a=Max("total_amount"),
            flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            dups=Count("id", filter=Q(is_duplicate=True)),
        )
        return {
            "invoice_count": int(stats.get("cnt") or 0),
            "total_amount": self._safe_decimal(stats.get("total") or 0),
            "avg_invoice_amount": self._safe_decimal(stats.get("avg") or 0),
            "max_invoice_amount": self._safe_decimal(stats.get("max_a") or 0),
            "flagged_count": int(stats.get("flagged") or 0),
            "duplicate_count": int(stats.get("dups") or 0),
        }

    def _build_transaction_history(self, profile: Optional[VendorProfile], doc: NormalizedDocument, risk_data: dict) -> dict:
        history = dict(getattr(profile, "transaction_history", {}) or {})
        counts = dict(history.get("document_counts", {}) or {})
        recent = list(history.get("recent_documents", []) or [])

        doc_key = f"{doc.document_type}:{doc.document_id}"
        already_seen = any(item.get("key") == doc_key for item in recent)
        recent = [item for item in recent if item.get("key") != doc_key]
        if not already_seen:
            counts[doc.document_type] = int(counts.get(doc.document_type, 0)) + 1

        event = {
            "key": doc_key,
            "document_type": doc.document_type,
            "document_id": str(doc.document_id),
            "document_number": doc.document_number,
            "amount": self._safe_float(getattr(doc, "total_amount", None)) or 0.0,
            "risk_level": risk_data.get("risk_level", "low"),
            "risk_score": self._safe_float(risk_data.get("risk_score")) or 0.0,
            "audited_at": timezone.now().isoformat(),
        }
        recent.insert(0, event)
        recent = recent[:20]

        return {
            "document_counts": counts,
            "document_counts_total": sum(int(v or 0) for v in counts.values()),
            "last_document_type": doc.document_type,
            "last_document_number": doc.document_number,
            "recent_documents": recent,
        }

    def _build_compliance_history(self, profile: Optional[VendorProfile], risk_data: dict) -> tuple[dict, int]:
        history = dict(getattr(profile, "compliance_history", {}) or {})
        current_codes = self._extract_compliance_rule_codes(risk_data)
        total_issues = int(history.get("total_issues") or getattr(profile, "compliance_issue_count", 0) or 0)
        total_issues += len(current_codes)

        history.update({
            "total_issues": total_issues,
            "last_failed_rules": current_codes,
            "last_risk_level": risk_data.get("risk_level", "low"),
            "last_risk_score": self._safe_float(risk_data.get("risk_score")) or 0.0,
            "last_anomaly_score": self._safe_float(risk_data.get("anomaly_score")) or 0.0,
            "updated_at": timezone.now().isoformat(),
        })
        return history, total_issues

    def _calculate_high_risk_audit_count(self, profile: Optional[VendorProfile], risk_data: dict) -> int:
        count = int(getattr(profile, "high_risk_audit_count", 0) or 0)
        if (risk_data.get("risk_level") or "").lower() in {"high", "critical"}:
            count += 1
        return count

    def _frequency_from_history(self, history: dict) -> float:
        recent = history.get("recent_documents", []) or []
        cutoff = timezone.now() - timedelta(days=self.RECENT_WINDOW_DAYS)
        in_window = 0
        for item in recent:
            ts = item.get("audited_at")
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
            if dt.tzinfo is None:
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            if dt >= cutoff:
                in_window += 1
        return float(in_window)

    def _derive_approval_state(self, doc: NormalizedDocument, profile: Optional[VendorProfile]) -> Optional[bool]:
        approved_registry = {
            str(value).strip().lower()
            for value in (doc.get_org("approved_vendor_ids") or [])
            if str(value).strip()
        }
        blocked_registry = {
            str(value).strip().lower()
            for value in (doc.get_org("blocked_vendor_ids") or [])
            if str(value).strip()
        }
        identifiers = {
            str(doc.counterparty_name or "").strip().lower(),
            str(doc.tax_id or "").strip().lower(),
        }
        identifiers.discard("")

        if identifiers and identifiers & blocked_registry:
            return False
        if identifiers and identifiers & approved_registry:
            return True
        if profile is not None:
            return profile.is_approved
        return None

    def _derive_tags(self, profile: Optional[VendorProfile], risk_data: dict, is_approved: Optional[bool]) -> list[str]:
        tags = list(getattr(profile, "tags", []) or [])
        if is_approved is False and "unapproved_vendor" not in tags:
            tags.append("unapproved_vendor")

        anomaly_score = self._safe_float(risk_data.get("anomaly_score")) or 0.0
        if anomaly_score >= 60 and "anomaly_spike" not in tags:
            tags.append("anomaly_spike")

        for finding in risk_data.get("anomaly_findings", []) or []:
            code = str(finding.get("code") or "").strip()
            if code and code not in tags:
                tags.append(code)

        return tags[:15]

    @staticmethod
    def _extract_compliance_rule_codes(risk_data: dict) -> list[str]:
        codes: list[str] = []
        for item in risk_data.get("top_failed_rules", []) or []:
            code = str(item.get("rule_code") or "").strip()
            if code.startswith(("VAT-", "TAX-", "GAAP-", "CTL-", "SEC-")):
                codes.append(code)
        return list(dict.fromkeys(codes))

    @staticmethod
    def _coerce_date(value) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.fromisoformat(str(value)).date()
        except Exception:
            return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_decimal(value) -> Decimal:
        try:
            return Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except Exception:
            return Decimal("0.00")
