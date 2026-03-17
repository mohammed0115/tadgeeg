"""
R007 — Forward-Date Invoice Fraud Rule

Detects systematic forward-dating fraud: a pattern where the same vendor
repeatedly submits invoices dated in the future across multiple transactions.

Distinction from R005-D01 (DateValidationRule):
  R005-D01  → flags a SINGLE document whose date > today (data quality)
  R007      → flags a VENDOR PATTERN of forward-dating (fraud signal)

Fraud signal logic:
  F07a  — This document's date is in the future (pre-condition)
  F07b  — Vendor has ≥ PATTERN_THRESHOLD forward-dated invoices in the
           last LOOKBACK_DAYS (systemic pattern, not a one-off error)
  F07c  — Forward-date gap > MAX_ACCEPTABLE_DAYS (material misstatement risk:
           revenue recognised in wrong fiscal period)

Severity matrix:
  Pattern + large gap  → CRITICAL
  Pattern only         → HIGH
  Single future date   → MEDIUM (defer to R005-D01 for LOW-severity cases)

Applies to: invoice, receipt, purchase_order
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .base_rule import AuditRule, RuleResult, Severity

logger = logging.getLogger("finai")

# ── Thresholds ─────────────────────────────────────────────────────────────────
LOOKBACK_DAYS            = 180    # 6-month window for pattern detection
PATTERN_THRESHOLD        = 3      # Min forward-dated invoices to flag a pattern
MAX_ACCEPTABLE_DAYS      = 7      # Gap > this is material (grace for transit time)
CRITICAL_GAP_DAYS        = 30     # Gap > this → CRITICAL severity


class ForwardDateFraudRule(AuditRule):
    """
    Detects systematic forward-dating fraud at the vendor level.

    The rule runs three sub-checks (F07a → F07b → F07c) in increasing
    severity.  All three are evaluated independently; their results are
    aggregated into the final RuleResult.
    """

    rule_id    = "R007"
    rule_name  = "Forward-Date Invoice Fraud Detection"
    severity   = Severity.HIGH
    applies_to = {"invoice", "receipt", "purchase_order"}
    description = (
        "Detects vendors who systematically submit forward-dated invoices "
        "as a fraud or revenue-manipulation pattern."
    )

    def evaluate(
        self,
        document: dict,
        organization_id: Optional[int] = None,
        context: Optional[dict] = None,
    ) -> RuleResult:
        context = context or {}

        # ── Pre-condition: parse document date ────────────────────────────────
        date_str = document.get("date") or document.get("invoice_date")
        if not date_str:
            return self._skip("No document date — R007 cannot evaluate")

        try:
            doc_date = date.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            return self._skip(f"Unparseable date '{date_str}' — R007 skipped")

        today          = date.today()
        vendor_name    = (document.get("vendor_name") or "").strip()
        document_number = document.get("document_number") or "?"

        signals: list[str] = []
        details: dict = {
            "document_date":   str(doc_date),
            "today":           str(today),
            "vendor_name":     vendor_name,
            "document_number": document_number,
        }

        # ── F07a: Is this document's date in the future? ──────────────────────
        days_ahead = (doc_date - today).days
        is_future  = days_ahead > 0

        if not is_future:
            # No forward dating — nothing for this rule to do
            return self._pass(details={"document_date": str(doc_date), "today": str(today)})

        details["days_ahead"] = days_ahead
        signals.append(
            f"F07a: Document dated {days_ahead} day(s) in the future ({doc_date})"
        )

        # Determine initial severity from gap size
        if days_ahead > CRITICAL_GAP_DAYS:
            self.severity = Severity.CRITICAL
            signals.append(
                f"F07c: Forward-date gap {days_ahead}d exceeds critical threshold "
                f"({CRITICAL_GAP_DAYS}d) — potential fiscal-period misstatement"
            )
        elif days_ahead > MAX_ACCEPTABLE_DAYS:
            self.severity = Severity.HIGH

        # ── F07b: Vendor pattern check ────────────────────────────────────────
        if vendor_name and organization_id:
            pattern = self._check_vendor_pattern(vendor_name, organization_id, today)
            details.update(pattern)

            if pattern.get("forward_dated_count", 0) >= PATTERN_THRESHOLD:
                # Upgrade to CRITICAL if pattern + large gap
                if days_ahead > MAX_ACCEPTABLE_DAYS:
                    self.severity = Severity.CRITICAL

                signals.append(
                    f"F07b: Vendor '{vendor_name}' has "
                    f"{pattern['forward_dated_count']} forward-dated invoices "
                    f"in the last {LOOKBACK_DAYS} days — systematic fraud pattern detected"
                )

        if not signals:
            return self._pass(details=details)

        return self._fail(
            explanation=" | ".join(signals),
            details=details,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_vendor_pattern(
        self,
        vendor_name: str,
        organization_id: int,
        today: date,
    ) -> dict:
        """
        Query historical invoices for this vendor and count forward-dated ones.

        Returns a dict with pattern metrics.
        Avoids N+1: single aggregation query.
        """
        from django.db.models import Count, Q

        try:
            from apps.invoices.models import Invoice

            lookback_start = today - timedelta(days=LOOKBACK_DAYS)

            # All invoices for this vendor in the lookback window
            qs = Invoice.objects.filter(
                organization_id=organization_id,
                vendor_name__iexact=vendor_name,
                invoice_date__gte=lookback_start,
            )

            # Single annotated query: total + forward-dated in one round-trip
            agg = qs.aggregate(
                total=Count("id"),
                forward_dated=Count(
                    "id",
                    filter=Q(invoice_date__gt=today),
                ),
            )

            total_count        = agg.get("total") or 0
            forward_dated_count = agg.get("forward_dated") or 0
            pattern_ratio      = (
                round(forward_dated_count / total_count, 3)
                if total_count > 0 else 0.0
            )

            logger.debug(
                "[R007] vendor=%r org=%s total=%d forward_dated=%d ratio=%.2f",
                vendor_name, organization_id,
                total_count, forward_dated_count, pattern_ratio,
            )

            return {
                "vendor_total_invoices_lookback": total_count,
                "forward_dated_count":            forward_dated_count,
                "forward_dated_ratio":            pattern_ratio,
                "lookback_days":                  LOOKBACK_DAYS,
                "pattern_threshold":              PATTERN_THRESHOLD,
            }

        except Exception as exc:
            logger.warning("[R007] Vendor pattern check failed: %s", exc)
            return {
                "vendor_pattern_check_error": str(exc),
                "forward_dated_count":        0,
            }
