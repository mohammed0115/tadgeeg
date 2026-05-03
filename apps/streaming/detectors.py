"""
Window-based anomaly detectors — Phase 3.1 of the Enterprise Roadmap.

Each detector reads the live invoice stream and fires when a sliding-window
condition trips. Detection produces an ``AnomalyHit`` which the worker logs,
publishes back to the bus, and (Phase 3.2) routes to alert channels.

Detectors:

  • VelocityDetector   — same vendor submits more than N invoices in M minutes.
  • SuddenSpikeDetector — vendor's new invoice exceeds μ + kσ of its own
                          last-30-day distribution.
  • VendorConcentrationDetector — vendor crosses X% of org spend in last Y days.

The detectors are deliberately light: they query the DB for the comparison
window every time an event arrives. That's wasteful for high-volume orgs but
keeps the implementation correct + side-effect-free. A follow-up story moves
the windows to in-memory ring buffers when traffic warrants.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from django.utils import timezone

logger = logging.getLogger("finai.streaming")


@dataclass
class AnomalyHit:
    detector: str
    severity: str            # 'low' | 'medium' | 'high' | 'critical'
    invoice_id: str
    organization_id: str
    vendor_name: str
    explanation: str
    details: dict = field(default_factory=dict)
    occurred_at: str = ""

    def __post_init__(self):
        if not self.occurred_at:
            self.occurred_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "detector":        self.detector,
            "severity":        self.severity,
            "invoice_id":      self.invoice_id,
            "organization_id": self.organization_id,
            "vendor_name":     self.vendor_name,
            "explanation":     self.explanation,
            "details":         self.details,
            "occurred_at":     self.occurred_at,
        }


class BaseDetector:
    name = "base"

    def evaluate(self, event) -> Optional[AnomalyHit]:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Velocity — too many invoices from same vendor in a short window
# ─────────────────────────────────────────────────────────────────────────────

class VelocityDetector(BaseDetector):
    """Fires when a vendor submits > ``threshold`` invoices in ``window_minutes``."""

    name = "velocity"

    def __init__(self, threshold: int = 10, window_minutes: int = 60,
                 severity: str = "high"):
        self.threshold = threshold
        self.window_minutes = window_minutes
        self.severity = severity

    def evaluate(self, event) -> Optional[AnomalyHit]:
        if event.type not in {"invoice.uploaded", "invoice.audited"}:
            return None

        org_id = event.organization_id
        vendor = (event.payload or {}).get("vendor_name") or ""
        if not org_id or not vendor:
            return None

        from apps.invoices.models import Invoice
        cutoff = timezone.now() - timedelta(minutes=self.window_minutes)
        count = (
            Invoice.objects
            .filter(organization_id=org_id,
                    vendor_name=vendor,
                    created_at__gte=cutoff)
            .count()
        )
        if count <= self.threshold:
            return None

        return AnomalyHit(
            detector=self.name,
            severity=self.severity,
            invoice_id=event.payload.get("invoice_id", ""),
            organization_id=str(org_id),
            vendor_name=vendor,
            explanation=(
                f"Vendor '{vendor}' submitted {count} invoices in the last "
                f"{self.window_minutes} minutes (threshold: {self.threshold})."
            ),
            details={
                "count": count, "threshold": self.threshold,
                "window_minutes": self.window_minutes,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sudden spike — invoice amount > μ + kσ of vendor's last-30-day distribution
# ─────────────────────────────────────────────────────────────────────────────

class SuddenSpikeDetector(BaseDetector):
    """Z-score outlier on the vendor's own historical amounts."""

    name = "sudden_spike"

    def __init__(self, sigma: float = 5.0, lookback_days: int = 30,
                 min_history: int = 5, severity: str = "high"):
        self.sigma = sigma
        self.lookback_days = lookback_days
        self.min_history = min_history
        self.severity = severity

    def evaluate(self, event) -> Optional[AnomalyHit]:
        if event.type not in {"invoice.uploaded", "invoice.audited"}:
            return None

        org_id = event.organization_id
        vendor = (event.payload or {}).get("vendor_name") or ""
        new_amount = (event.payload or {}).get("total_amount")
        if not (org_id and vendor and new_amount):
            return None
        try:
            new_amount = float(new_amount)
        except (TypeError, ValueError):
            return None
        if new_amount <= 0:
            return None

        from apps.invoices.models import Invoice
        cutoff = timezone.now() - timedelta(days=self.lookback_days)
        qs = Invoice.objects.filter(
            organization_id=org_id,
            vendor_name=vendor,
            created_at__gte=cutoff,
        )
        # Try to exclude the just-uploaded invoice. Best-effort: a non-UUID
        # `invoice_id` (which never matches the DB) just means we keep all
        # rows — the worst case is a slight statistical bias when this
        # invoice is also in the lookback set.
        import uuid as _uuid
        raw_id = event.payload.get("invoice_id")
        if raw_id:
            try:
                qs = qs.exclude(id=_uuid.UUID(str(raw_id)))
            except (ValueError, TypeError):
                pass
        history = list(qs.values_list("total_amount", flat=True))
        history = [float(a) for a in history if a is not None]
        if len(history) < self.min_history:
            return None

        mean = sum(history) / len(history)
        var = sum((a - mean) ** 2 for a in history) / len(history)
        std = math.sqrt(var) if var > 0 else 0.0
        if std == 0:
            return None

        zscore = (new_amount - mean) / std
        if zscore <= self.sigma:
            return None

        return AnomalyHit(
            detector=self.name,
            severity=self.severity,
            invoice_id=event.payload.get("invoice_id", ""),
            organization_id=str(org_id),
            vendor_name=vendor,
            explanation=(
                f"Invoice amount {new_amount:.2f} is {zscore:.1f}σ above "
                f"vendor '{vendor}'s last-{self.lookback_days}-day mean "
                f"({mean:.2f}, n={len(history)})."
            ),
            details={
                "new_amount": new_amount,
                "vendor_mean": round(mean, 2),
                "vendor_std":  round(std, 2),
                "zscore":      round(zscore, 2),
                "history_size": len(history),
                "threshold_sigma": self.sigma,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Vendor concentration — single vendor exceeds X% of org spend in window
# ─────────────────────────────────────────────────────────────────────────────

class VendorConcentrationDetector(BaseDetector):
    """Fires when a vendor crosses ``threshold_pct`` of the org's total
    invoice volume in the last ``window_days`` days."""

    name = "vendor_concentration"

    def __init__(self, threshold_pct: float = 30.0, window_days: int = 30,
                 min_invoices: int = 10, severity: str = "medium"):
        self.threshold_pct = threshold_pct
        self.window_days = window_days
        self.min_invoices = min_invoices
        self.severity = severity

    def evaluate(self, event) -> Optional[AnomalyHit]:
        if event.type not in {"invoice.uploaded", "invoice.audited"}:
            return None

        org_id = event.organization_id
        vendor = (event.payload or {}).get("vendor_name") or ""
        if not (org_id and vendor):
            return None

        from django.db.models import Sum
        from apps.invoices.models import Invoice
        cutoff = timezone.now() - timedelta(days=self.window_days)

        org_qs = Invoice.objects.filter(organization_id=org_id, created_at__gte=cutoff)
        if org_qs.count() < self.min_invoices:
            return None

        org_total    = org_qs.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        vendor_total = (
            org_qs.filter(vendor_name=vendor)
            .aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        )
        if not org_total:
            return None

        pct = float(vendor_total) / float(org_total) * 100
        if pct <= self.threshold_pct:
            return None

        return AnomalyHit(
            detector=self.name,
            severity=self.severity,
            invoice_id=event.payload.get("invoice_id", ""),
            organization_id=str(org_id),
            vendor_name=vendor,
            explanation=(
                f"Vendor '{vendor}' accounts for {pct:.1f}% of total spend in "
                f"the last {self.window_days} days "
                f"(threshold: {self.threshold_pct:.0f}%)."
            ),
            details={
                "vendor_total": float(vendor_total),
                "org_total":    float(org_total),
                "vendor_share_pct": round(pct, 2),
                "window_days": self.window_days,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Detector registry + dispatch
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DETECTORS: list[BaseDetector] = [
    VelocityDetector(),
    SuddenSpikeDetector(),
    VendorConcentrationDetector(),
]


def evaluate_all(event, detectors: Optional[Iterable[BaseDetector]] = None
                ) -> list[AnomalyHit]:
    """Run every detector against ``event`` and return all hits."""
    hits: list[AnomalyHit] = []
    for d in (detectors or DEFAULT_DETECTORS):
        try:
            hit = d.evaluate(event)
        except Exception as exc:
            logger.warning("[detector.%s] crashed: %s", d.name, exc)
            continue
        if hit:
            hits.append(hit)
    return hits
