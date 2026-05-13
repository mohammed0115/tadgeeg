"""Unified Fraud Detection Engine (F-3).

Closes the audit-review gap: signals existed across four modules
(rule_engine catalogue, invoice processor, AI service, vendor profile),
but a SOC2 / CIA auditor asking "show me this invoice's fraud score"
saw a fragmented surface. This module is the single answer they call.

Design:
  • The engine never re-derives signals from scratch — it READS
    them from the existing sources. Duplicate detection still lives
    in the invoice processor, Benford in the AI service, vendor risk
    on VendorProfile, behavioral rules in the rule-engine catalog.
  • Each signal has a 0–100 score + severity + reason. The engine
    returns the bundle PLUS a weighted total + top-3 highest
    contributors so the auditor can drill in.
  • All signals are optional — if the source module is uninstalled
    or returns nothing, the signal is reported as ``available=False``.

Call sites:
  • ``apps.invoices.views.InvoiceDetailView`` — surface in the
    fraud-summary card (Stage 11+).
  • Reports / dashboards — overall org fraud heat-map.
  • Audit pipeline post-hook — log a fraud_score per AuditRun.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional


logger = logging.getLogger("audit.fraud_engine")


# ─── Signal envelope ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FraudSignal:
    """One fraud indicator's contribution to the overall score."""
    name:        str                    # "duplicate" | "benford" | "vendor_risk" | "behavioral" | "structural"
    score:       int                    # 0–100, higher = more fraud-like
    weight:      Decimal                # contribution weight 0–1
    severity:    str                    # "low" | "medium" | "high" | "critical"
    reason:      str                    # one-line human explanation
    available:   bool = True            # False = the underlying signal couldn't be computed
    detail:      dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "score":     self.score,
            "weight":    str(self.weight),
            "severity":  self.severity,
            "reason":    self.reason,
            "available": self.available,
            "detail":    self.detail,
        }


# Weights sum to 1.0. Tuned conservatively — duplicate is the strongest
# fraud indicator we have today, vendor risk is the second-strongest.
# Override per deployment via settings.FRAUD_ENGINE_WEIGHTS.
_DEFAULT_WEIGHTS = {
    "duplicate":   Decimal("0.30"),
    "benford":     Decimal("0.20"),
    "vendor_risk": Decimal("0.25"),
    "behavioral":  Decimal("0.15"),
    "structural":  Decimal("0.10"),
}


@dataclass(frozen=True)
class FraudAssessment:
    """The engine's full output for one invoice."""
    invoice_id:     str
    total_score:    int                 # weighted 0–100
    severity:       str                 # bucketed
    signals:        List[FraudSignal]
    top_contributors: List[FraudSignal]  # 3 highest score*weight

    def to_dict(self) -> dict:
        return {
            "invoice_id":   self.invoice_id,
            "total_score":  self.total_score,
            "severity":     self.severity,
            "signals":      [s.to_dict() for s in self.signals],
            "top_contributors": [s.to_dict() for s in self.top_contributors],
        }


def _bucket_severity(score: int) -> str:
    if score >= 75: return "critical"
    if score >= 50: return "high"
    if score >= 25: return "medium"
    return "low"


def _weights():
    from django.conf import settings
    override = getattr(settings, "FRAUD_ENGINE_WEIGHTS", None) or {}
    out = {}
    for k, v in _DEFAULT_WEIGHTS.items():
        out[k] = Decimal(str(override.get(k, v)))
    return out


# ─── Per-signal evaluators (read from existing sources) ─────────────────────

def _signal_duplicate(invoice) -> FraudSignal:
    """Strong signal — exact duplicates are almost always fraud or process error."""
    weight = _weights()["duplicate"]
    if getattr(invoice, "is_duplicate", False):
        return FraudSignal(
            name="duplicate", score=100, weight=weight,
            severity="critical",
            reason=f"Exact duplicate of invoice {invoice.duplicate_of_id}",
            detail={"duplicate_of_id": str(getattr(invoice, "duplicate_of_id", ""))},
        )
    return FraudSignal(
        name="duplicate", score=0, weight=weight,
        severity="low", reason="No duplicate detected",
    )


def _signal_benford(invoice) -> FraudSignal:
    """Read Benford analysis if the AI service computed one for this invoice."""
    weight = _weights()["benford"]
    extracted = getattr(invoice, "extracted_data", None) or {}
    risk_block = extracted.get("ai_risk") or extracted.get("risk") or {}
    benford = risk_block.get("benford") or risk_block.get("benford_score")
    if benford is None:
        return FraudSignal(
            name="benford", score=0, weight=weight,
            severity="low", reason="Not computed for this invoice",
            available=False,
        )
    try:
        score = max(0, min(100, int(float(benford) * 100) if benford <= 1 else int(benford)))
    except (TypeError, ValueError):
        score = 0
    return FraudSignal(
        name="benford", score=score, weight=weight,
        severity=_bucket_severity(score),
        reason=f"Benford-law deviation score {score}/100",
        detail={"raw": benford},
    )


def _signal_vendor_risk(invoice) -> FraudSignal:
    """Vendor risk score from VendorProfile (if the vendor is known)."""
    weight = _weights()["vendor_risk"]
    score = 0
    detail = {}
    try:
        from apps.invoices.models import VendorProfile
        vp = VendorProfile.objects.filter(
            organization=invoice.organization,
            vendor_name__iexact=invoice.vendor_name,
        ).first()
        if vp is None:
            return FraudSignal(
                name="vendor_risk", score=20, weight=weight,
                severity="medium", reason="Unknown / first-time vendor",
                detail={"unknown_vendor": True},
            )
        score = int(round(float(vp.risk_score or 0)))
        detail = {
            "vendor_id":   str(vp.pk),
            "tier":        getattr(vp, "risk_tier", "") or "",
        }
    except Exception as exc:                # pragma: no cover
        logger.warning("vendor risk lookup failed: %s", exc)
    return FraudSignal(
        name="vendor_risk", score=score, weight=weight,
        severity=_bucket_severity(score),
        reason=f"Vendor risk score {score}/100",
        detail=detail,
    )


def _signal_behavioral(invoice) -> FraudSignal:
    """Behavioral rule hits — weekend / late-night / clustering. Read from
    the invoice's validation_details if the rule-engine pipeline ran."""
    weight = _weights()["behavioral"]
    from apps.invoices.models import InvoiceValidationResult
    val = (
        InvoiceValidationResult.objects
        .filter(invoice=invoice)
        .order_by("-validated_at")
        .first()
    )
    if val is None or not val.validation_details:
        return FraudSignal(
            name="behavioral", score=0, weight=weight,
            severity="low", reason="No validation run yet",
            available=False,
        )
    behavior_hits = []
    for code, info in (val.validation_details or {}).items():
        if not isinstance(info, dict):
            continue
        text = " ".join(filter(None, [
            info.get("description") or "", info.get("message") or "", code,
        ])).lower()
        if any(t in text for t in (
            "weekend", "late night", "after hours", "cluster", "spike",
            "structuring", "round amount", "duplicate", "ghost", "benford",
        )):
            behavior_hits.append({"code": code, "severity": info.get("severity", "medium")})
    if not behavior_hits:
        return FraudSignal(
            name="behavioral", score=0, weight=weight,
            severity="low", reason="No behavioral anomalies flagged",
        )
    # Score = min(100, hits × 25). Three hits → 75 → "high".
    score = min(100, len(behavior_hits) * 25)
    return FraudSignal(
        name="behavioral", score=score, weight=weight,
        severity=_bucket_severity(score),
        reason=f"{len(behavior_hits)} behavioral rule(s) hit",
        detail={"hits": behavior_hits[:10]},
    )


def _signal_structural(invoice) -> FraudSignal:
    """Structural fraud cues: alterations, handwritten text, missing
    invoice number, sub-cap rounding artefacts. All present as Invoice
    fields today."""
    weight = _weights()["structural"]
    points = 0
    reasons = []
    if getattr(invoice, "has_alterations", False):
        points += 35
        reasons.append("alterations detected")
    if getattr(invoice, "is_handwritten", False):
        points += 20
        reasons.append("handwritten")
    if not getattr(invoice, "invoice_number", ""):
        points += 15
        reasons.append("missing invoice number")
    if getattr(invoice, "ocr_confidence", 100) < 50:
        points += 10
        reasons.append("low OCR confidence")
    score = min(100, points)
    return FraudSignal(
        name="structural", score=score, weight=weight,
        severity=_bucket_severity(score),
        reason=", ".join(reasons) if reasons else "Document structure looks clean",
    )


# ─── Engine ─────────────────────────────────────────────────────────────────
class FraudDetectionEngine:
    """Unified fraud-score surface. Stateless; instantiate freely."""

    SIGNAL_EVALUATORS = (
        _signal_duplicate,
        _signal_benford,
        _signal_vendor_risk,
        _signal_behavioral,
        _signal_structural,
    )

    def evaluate(self, invoice) -> FraudAssessment:
        signals = [evaluator(invoice) for evaluator in self.SIGNAL_EVALUATORS]
        total = self._weighted_total(signals)
        top = sorted(
            [s for s in signals if s.available],
            key=lambda s: float(s.weight) * s.score,
            reverse=True,
        )[:3]
        return FraudAssessment(
            invoice_id=str(invoice.pk),
            total_score=total,
            severity=_bucket_severity(total),
            signals=signals,
            top_contributors=top,
        )

    @staticmethod
    def _weighted_total(signals: List[FraudSignal]) -> int:
        usable = [s for s in signals if s.available]
        if not usable:
            return 0
        # Re-normalise weights over only the available signals.
        total_weight = sum(s.weight for s in usable) or Decimal("1")
        weighted = sum((Decimal(s.score) * s.weight) for s in usable) / total_weight
        return int(round(float(weighted)))


def assess_invoice(invoice) -> FraudAssessment:
    """Convenience function for callers that don't want the class."""
    return FraudDetectionEngine().evaluate(invoice)
