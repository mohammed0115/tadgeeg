"""
Duplicate Invoice Detector

Detects duplicate financial documents using a multi-signal similarity approach:

  Signal 1 — Exact document number + vendor match (hash collision)
  Signal 2 — Fuzzy vendor name + document number
  Signal 3 — Same vendor + amount + date (near-duplicate)
  Signal 4 — File content hash (bit-for-bit duplicate upload)
  Signal 5 — Cross-month duplicate (same number, different period)

Each signal contributes to a composite duplicate_score (0.0–1.0).

The detector is organisation-scoped (never compares across tenants).
"""

import hashlib
import logging
import re
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger("finai")

# Score weights per signal
WEIGHT_EXACT_MATCH = 1.0
WEIGHT_FUZZY_NUMBER = 0.85
WEIGHT_AMOUNT_DATE = 0.80
WEIGHT_FILE_HASH = 1.0
WEIGHT_CROSS_MONTH = 0.70

# Thresholds
AMOUNT_TOLERANCE = Decimal("0.05")       # ±5% amount difference allowed
NAME_SIMILARITY_THRESHOLD = 0.82         # Vendor name fuzzy threshold
DATE_WINDOW_DAYS = 7                     # Days to consider "same period"


class DuplicateDetector:
    """
    Multi-signal duplicate document detector.

    Usage:
        detector = DuplicateDetector(organization_id=org.id)
        result = detector.detect(document)
        print(result['duplicate_score'], result['duplicate_reasons'])
    """

    def __init__(self, organization_id: int = None):
        self.organization_id = organization_id

    def detect(self, document: dict) -> dict:
        """
        Run all duplicate detection signals against the document.

        Args:
            document: Normalised document dict from the ingestion engine.

        Returns:
            {
              duplicate_score: float (0–1),
              is_duplicate: bool,
              duplicate_reasons: list[str],
              matched_document_ids: list[int],
              signals: dict
            }
        """
        signals: dict[str, float] = {}
        reasons: list[str] = []
        matched_ids: list[int] = []

        # ── Signal 1: Exact number + vendor ──────────────────────────────────
        score1, matches1, reason1 = self._check_exact_number(document)
        if score1 > 0:
            signals["exact_number_vendor"] = score1
            reasons.append(reason1)
            matched_ids.extend(matches1)

        # ── Signal 2: Fuzzy number match ──────────────────────────────────────
        score2, matches2, reason2 = self._check_fuzzy_number(document)
        if score2 > 0:
            signals["fuzzy_number"] = score2
            reasons.append(reason2)
            matched_ids.extend(matches2)

        # ── Signal 3: Amount + date proximity ─────────────────────────────────
        score3, matches3, reason3 = self._check_amount_date(document)
        if score3 > 0:
            signals["amount_date"] = score3
            reasons.append(reason3)
            matched_ids.extend(matches3)

        # ── Signal 4: File hash ───────────────────────────────────────────────
        score4, matches4, reason4 = self._check_file_hash(document)
        if score4 > 0:
            signals["file_hash"] = score4
            reasons.append(reason4)
            matched_ids.extend(matches4)

        # ── Signal 5: Cross-month ─────────────────────────────────────────────
        score5, matches5, reason5 = self._check_cross_month(document)
        if score5 > 0:
            signals["cross_month"] = score5
            reasons.append(reason5)
            matched_ids.extend(matches5)

        # ── Aggregate score ───────────────────────────────────────────────────
        composite = self._aggregate_signals(signals)
        is_duplicate = composite >= 0.70

        return {
            "duplicate_score": round(composite, 4),
            "is_duplicate": is_duplicate,
            "duplicate_reasons": reasons,
            "matched_document_ids": list(set(matched_ids)),
            "signals": signals,
        }

    # ── Signals ───────────────────────────────────────────────────────────────

    def _check_exact_number(self, doc: dict) -> tuple[float, list, str]:
        """Exact match on document_number + normalised vendor_name."""
        doc_number = self._normalise_doc_number(doc.get("document_number", ""))
        vendor = self._normalise_vendor(doc.get("vendor_name", ""))

        if not doc_number or not vendor:
            return 0.0, [], ""

        try:
            from apps.invoices.models import Invoice

            qs = Invoice.objects.filter(
                invoice_number__iexact=doc_number,
            )
            if self.organization_id:
                qs = qs.filter(organization_id=self.organization_id)

            matches = []
            for inv in qs:
                existing_vendor = self._normalise_vendor(inv.vendor_name or "")
                if self._vendor_similar(vendor, existing_vendor):
                    matches.append(inv.id)

            if matches:
                return (
                    WEIGHT_EXACT_MATCH,
                    matches,
                    f"Document number '{doc_number}' already exists for vendor '{vendor}'",
                )
        except Exception as exc:
            logger.warning("[DuplicateDetector] exact_number check error: %s", exc)

        return 0.0, [], ""

    def _check_fuzzy_number(self, doc: dict) -> tuple[float, list, str]:
        """Fuzzy match on document number (catches typos)."""
        doc_number = self._normalise_doc_number(doc.get("document_number", ""))
        if not doc_number or len(doc_number) < 3:
            return 0.0, [], ""

        try:
            from apps.invoices.models import Invoice

            qs = Invoice.objects.only("id", "invoice_number", "vendor_name")
            if self.organization_id:
                qs = qs.filter(organization_id=self.organization_id)

            matches = []
            for inv in qs[:500]:  # Cap to avoid full-table scan
                existing_num = self._normalise_doc_number(inv.invoice_number or "")
                if existing_num and SequenceMatcher(None, doc_number, existing_num).ratio() >= 0.92:
                    matches.append(inv.id)

            if matches:
                return (
                    WEIGHT_FUZZY_NUMBER,
                    matches,
                    f"Document number '{doc_number}' is very similar to existing records",
                )
        except Exception as exc:
            logger.warning("[DuplicateDetector] fuzzy_number check error: %s", exc)

        return 0.0, [], ""

    def _check_amount_date(self, doc: dict) -> tuple[float, list, str]:
        """Same vendor + similar amount + same date window."""
        vendor = self._normalise_vendor(doc.get("vendor_name", ""))
        total = doc.get("total_amount", 0)
        date_str = doc.get("date")

        if not vendor or not total or not date_str:
            return 0.0, [], ""

        try:
            from apps.invoices.models import Invoice
            from datetime import date, timedelta
            import datetime as dt

            try:
                parsed_date = dt.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                return 0.0, [], ""

            date_from = parsed_date - timedelta(days=DATE_WINDOW_DAYS)
            date_to = parsed_date + timedelta(days=DATE_WINDOW_DAYS)

            tolerance = Decimal(str(total)) * AMOUNT_TOLERANCE
            amount_min = float(Decimal(str(total)) - tolerance)
            amount_max = float(Decimal(str(total)) + tolerance)

            qs = Invoice.objects.filter(
                invoice_date__range=(date_from, date_to),
                total_amount__range=(amount_min, amount_max),
            )
            if self.organization_id:
                qs = qs.filter(organization_id=self.organization_id)

            matches = []
            for inv in qs:
                existing_vendor = self._normalise_vendor(inv.vendor_name or "")
                if self._vendor_similar(vendor, existing_vendor):
                    matches.append(inv.id)

            if matches:
                return (
                    WEIGHT_AMOUNT_DATE,
                    matches,
                    f"Similar amount {total} from '{vendor}' on/near {date_str} already exists",
                )
        except Exception as exc:
            logger.warning("[DuplicateDetector] amount_date check error: %s", exc)

        return 0.0, [], ""

    def _check_file_hash(self, doc: dict) -> tuple[float, list, str]:
        """Check if the file hash (SHA-256) already exists."""
        file_hash = doc.get("metadata", {}).get("file_hash")
        if not file_hash:
            return 0.0, [], ""

        try:
            from apps.invoices.models import InvoiceValidationResult

            qs = InvoiceValidationResult.objects.filter(
                details__file_hash=file_hash
            )
            if self.organization_id:
                qs = qs.filter(invoice__organization_id=self.organization_id)

            if qs.exists():
                ids = list(qs.values_list("invoice_id", flat=True))
                return (
                    WEIGHT_FILE_HASH,
                    ids,
                    f"Identical file content (hash={file_hash[:12]}…) already uploaded",
                )
        except Exception as exc:
            logger.warning("[DuplicateDetector] file_hash check error: %s", exc)

        return 0.0, [], ""

    def _check_cross_month(self, doc: dict) -> tuple[float, list, str]:
        """Same document number appearing in different months (re-used numbers)."""
        doc_number = self._normalise_doc_number(doc.get("document_number", ""))
        date_str = doc.get("date")

        if not doc_number or not date_str:
            return 0.0, [], ""

        try:
            from apps.invoices.models import Invoice
            import datetime as dt

            try:
                parsed_date = dt.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                return 0.0, [], ""

            qs = Invoice.objects.filter(
                invoice_number__iexact=doc_number,
            ).exclude(invoice_date__year=parsed_date.year, invoice_date__month=parsed_date.month)

            if self.organization_id:
                qs = qs.filter(organization_id=self.organization_id)

            if qs.exists():
                ids = list(qs.values_list("id", flat=True))
                return (
                    WEIGHT_CROSS_MONTH,
                    ids,
                    f"Document number '{doc_number}' used in a different period",
                )
        except Exception as exc:
            logger.warning("[DuplicateDetector] cross_month check error: %s", exc)

        return 0.0, [], ""

    # ── Score aggregation ─────────────────────────────────────────────────────

    def _aggregate_signals(self, signals: dict[str, float]) -> float:
        """
        Combine signals using weighted maximum:
        The highest single signal dominates, others contribute diminishing returns.
        """
        if not signals:
            return 0.0

        sorted_scores = sorted(signals.values(), reverse=True)
        aggregate = sorted_scores[0]
        for i, score in enumerate(sorted_scores[1:], start=1):
            aggregate += score * (0.2 ** i)

        return min(aggregate, 1.0)

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_doc_number(s: str) -> str:
        return re.sub(r"[\s\-_/]", "", s).upper()

    @staticmethod
    def _normalise_vendor(s: str) -> str:
        return re.sub(r"[^\w\s]", "", s.lower()).strip()

    def _vendor_similar(self, a: str, b: str) -> bool:
        return SequenceMatcher(None, a, b).ratio() >= NAME_SIMILARITY_THRESHOLD

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file. Useful to set before calling detect()."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
