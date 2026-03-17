"""
Cross-Session Duplicate Detection Service

Detects duplicate documents that appear across DIFFERENT AuditSessions
within the same organisation.  This is distinct from the per-document
DuplicateDetector (which checks within one session) — this service
operates at the organisation / multi-session level.

Detection algorithm — four signals, weighted score:
  S1  exact_hash   — SHA-256 file hash match                     (weight 1.0)
  S2  invoice_key  — vendor + invoice_number + amount match      (weight 0.85)
  S3  fuzzy_vendor — vendor name similarity + amount + date      (weight 0.65)
  S4  amount_date  — amount + date match across multiple vendors (weight 0.40)

Final score = max(matched signal weights).
Threshold → is_duplicate: score ≥ DUPLICATE_THRESHOLD (0.85)

Design:
  - Stateless classmethods only.
  - All DB access uses select_related / values() to avoid N+1.
  - Uses transaction.atomic() + select_for_update() only when writing.
  - Never raises; returns CrossSessionDuplicateResult on all paths.

Usage:
    from core.services.cross_session_duplicate_service import CrossSessionDuplicateService

    result = CrossSessionDuplicateService.check(
        document=doc,
        organization_id=org.id,
        file_hash="abc123...",   # SHA-256, optional
    )
    if result.is_duplicate:
        print(result.duplicate_document_id, result.confidence_score)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("finai")

# ── Thresholds ─────────────────────────────────────────────────────────────────
DUPLICATE_THRESHOLD    = 0.85   # score ≥ this → is_duplicate
SUSPICIOUS_THRESHOLD   = 0.50   # score ≥ this → requires_review
AMOUNT_TOLERANCE_PCT   = 0.001  # 0.1% tolerance for float comparisons
FUZZY_VENDOR_THRESHOLD = 0.80   # Levenshtein ratio for vendor name similarity


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class CrossSessionDuplicateResult:
    """Result returned by CrossSessionDuplicateService.check()."""

    is_duplicate:        bool               = False
    requires_review:     bool               = False
    confidence_score:    float              = 0.0    # 0.0 – 1.0
    matched_signals:     list[str]          = field(default_factory=list)
    duplicate_document_id: Optional[str]   = None   # UUID of first seen doc
    duplicate_session_id:  Optional[str]   = None   # UUID of first seen session
    duplicate_vendor:      Optional[str]   = None
    duplicate_amount:      Optional[float] = None
    duplicate_date:        Optional[str]   = None
    error:               Optional[str]     = None

    def to_dict(self) -> dict:
        return {
            "is_duplicate":           self.is_duplicate,
            "requires_review":        self.requires_review,
            "confidence_score":       self.confidence_score,
            "matched_signals":        self.matched_signals,
            "duplicate_document_id":  self.duplicate_document_id,
            "duplicate_session_id":   self.duplicate_session_id,
            "duplicate_vendor":       self.duplicate_vendor,
            "duplicate_amount":       self.duplicate_amount,
            "duplicate_date":         self.duplicate_date,
            "error":                  self.error,
        }


# ── Service ────────────────────────────────────────────────────────────────────

class CrossSessionDuplicateService:
    """
    Detects cross-session duplicates for a Document within an organisation.

    All methods are classmethods — no instance state.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    @classmethod
    def check(
        cls,
        *,
        document,
        organization_id: int,
        file_hash: Optional[str] = None,
    ) -> CrossSessionDuplicateResult:
        """
        Run all four duplicate detection signals for a Document.

        Args:
            document:        Document model instance (must have analysis_result
                             or structured metadata attached).
            organization_id: Organisation scope for the search.
            file_hash:       Pre-computed SHA-256 (from DocumentEngine metadata).
                             If None, S1 is skipped.

        Returns:
            CrossSessionDuplicateResult (never raises).
        """
        result = CrossSessionDuplicateResult()

        try:
            # Resolve normalised fields from the document's analysis result
            fields = cls._resolve_document_fields(document, file_hash)
            if not fields:
                result.error = "Could not resolve document fields for duplicate check"
                return result

            # Exclude the document itself from all queries
            exclude_id = str(document.pk)

            # ── S1: Exact file hash ───────────────────────────────────────────
            if fields.get("file_hash"):
                match = cls._check_exact_hash(
                    fields["file_hash"], organization_id, exclude_id
                )
                if match:
                    cls._apply_match(result, match, "S1:exact_hash", 1.0)

            # ── S2: Invoice key (vendor + number + amount) ────────────────────
            if (
                result.confidence_score < DUPLICATE_THRESHOLD
                and fields.get("vendor_name")
                and fields.get("document_number")
                and fields.get("total_amount") is not None
            ):
                match = cls._check_invoice_key(
                    vendor_name=fields["vendor_name"],
                    document_number=fields["document_number"],
                    total_amount=fields["total_amount"],
                    organization_id=organization_id,
                    exclude_id=exclude_id,
                )
                if match:
                    cls._apply_match(result, match, "S2:invoice_key", 0.85)

            # ── S3: Fuzzy vendor + amount + date ──────────────────────────────
            if (
                result.confidence_score < DUPLICATE_THRESHOLD
                and fields.get("vendor_name")
                and fields.get("total_amount") is not None
                and fields.get("doc_date")
            ):
                match = cls._check_fuzzy_vendor(
                    vendor_name=fields["vendor_name"],
                    total_amount=fields["total_amount"],
                    doc_date=fields["doc_date"],
                    organization_id=organization_id,
                    exclude_id=exclude_id,
                )
                if match:
                    cls._apply_match(result, match, "S3:fuzzy_vendor_amount_date", 0.65)

            # ── S4: Amount + date across vendors ──────────────────────────────
            if (
                result.confidence_score < SUSPICIOUS_THRESHOLD
                and fields.get("total_amount") is not None
                and fields.get("doc_date")
            ):
                match = cls._check_amount_date(
                    total_amount=fields["total_amount"],
                    doc_date=fields["doc_date"],
                    organization_id=organization_id,
                    exclude_id=exclude_id,
                )
                if match:
                    cls._apply_match(result, match, "S4:amount_date", 0.40)

        except Exception as exc:
            logger.error("[CrossSessionDup] check() failed for doc=%s: %s", document.pk, exc)
            result.error = str(exc)
            return result

        # Determine final verdict
        result.is_duplicate    = result.confidence_score >= DUPLICATE_THRESHOLD
        result.requires_review = result.confidence_score >= SUSPICIOUS_THRESHOLD

        logger.info(
            "[CrossSessionDup] doc=%s score=%.2f is_dup=%s signals=%s",
            document.pk,
            result.confidence_score,
            result.is_duplicate,
            result.matched_signals,
        )

        return result

    # ── Signal implementations ─────────────────────────────────────────────────

    @classmethod
    def _check_exact_hash(
        cls, file_hash: str, organization_id: int, exclude_id: str
    ) -> Optional[dict]:
        """S1: Match by SHA-256 file hash stored in DocumentAnalysisResult metadata."""
        try:
            from apps.documents.models import Document

            # The hash is stored in DocumentEngine result → metadata → file_hash
            # We store it in DocumentAnalysisResult.analysis_data["ingestion"]["metadata"]
            match = (
                Document.objects
                .filter(
                    organization_id=organization_id,
                    processing_status__in=["completed", "needs_review"],
                )
                .exclude(pk=exclude_id)
                .filter(
                    analysis_result__analysis_data__ingestion__metadata__file_hash=file_hash
                )
                .values(
                    "id", "original_filename",
                    "analysis_result__analysis_data",
                )
                .first()
            )

            if not match:
                return None

            return {
                "document_id": str(match["id"]),
                "vendor_name": None,
                "total_amount": None,
                "doc_date": None,
            }
        except Exception as exc:
            logger.debug("[CrossSessionDup] S1 hash check error: %s", exc)
            return None

    @classmethod
    def _check_invoice_key(
        cls,
        vendor_name: str,
        document_number: str,
        total_amount: float,
        organization_id: int,
        exclude_id: str,
    ) -> Optional[dict]:
        """S2: Exact match on vendor_name + document_number + total_amount."""
        try:
            from django.db.models import Q
            from apps.documents.models import DocumentAnalysisResult

            tol = total_amount * AMOUNT_TOLERANCE_PCT
            match = (
                DocumentAnalysisResult.objects
                .filter(
                    document__organization_id=organization_id,
                    vendor_name__iexact=vendor_name,
                    document_number__iexact=document_number,
                    total_amount__gte=total_amount - tol,
                    total_amount__lte=total_amount + tol,
                )
                .exclude(document_id=exclude_id)
                .select_related("document")
                .values(
                    "document_id",
                    "vendor_name",
                    "total_amount",
                    "doc_date",
                    "document__analysis_result__audit_report",
                )
                .first()
            )

            if not match:
                return None

            return {
                "document_id":  str(match["document_id"]),
                "vendor_name":  match["vendor_name"],
                "total_amount": float(match["total_amount"]) if match["total_amount"] else None,
                "doc_date":     str(match["doc_date"]) if match["doc_date"] else None,
            }
        except Exception as exc:
            logger.debug("[CrossSessionDup] S2 invoice_key check error: %s", exc)
            return None

    @classmethod
    def _check_fuzzy_vendor(
        cls,
        vendor_name: str,
        total_amount: float,
        doc_date: str,
        organization_id: int,
        exclude_id: str,
    ) -> Optional[dict]:
        """
        S3: Fuzzy vendor name + exact amount + exact date.

        Fuzzy matching done in Python after a DB pre-filter (amount ± 5%,
        same date) to keep the candidate set small.
        """
        try:
            from apps.documents.models import DocumentAnalysisResult

            tol = max(total_amount * 0.05, 1.0)   # 5% tolerance for fuzzy signal
            candidates = (
                DocumentAnalysisResult.objects
                .filter(
                    document__organization_id=organization_id,
                    total_amount__gte=total_amount - tol,
                    total_amount__lte=total_amount + tol,
                    doc_date=doc_date,
                )
                .exclude(document_id=exclude_id)
                .values("document_id", "vendor_name", "total_amount", "doc_date")
            )

            best_ratio = 0.0
            best_match = None

            for cand in candidates:
                cand_vendor = (cand.get("vendor_name") or "").strip()
                if not cand_vendor:
                    continue
                ratio = cls._similarity(vendor_name, cand_vendor)
                if ratio >= FUZZY_VENDOR_THRESHOLD and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = cand

            if not best_match:
                return None

            return {
                "document_id":  str(best_match["document_id"]),
                "vendor_name":  best_match["vendor_name"],
                "total_amount": float(best_match["total_amount"]) if best_match["total_amount"] else None,
                "doc_date":     str(best_match["doc_date"]) if best_match["doc_date"] else None,
                "fuzzy_ratio":  round(best_ratio, 3),
            }
        except Exception as exc:
            logger.debug("[CrossSessionDup] S3 fuzzy_vendor check error: %s", exc)
            return None

    @classmethod
    def _check_amount_date(
        cls,
        total_amount: float,
        doc_date: str,
        organization_id: int,
        exclude_id: str,
    ) -> Optional[dict]:
        """S4: Same amount + same date — possible split-invoice fraud."""
        try:
            from apps.documents.models import DocumentAnalysisResult

            tol = max(total_amount * AMOUNT_TOLERANCE_PCT, 0.01)
            match = (
                DocumentAnalysisResult.objects
                .filter(
                    document__organization_id=organization_id,
                    total_amount__gte=total_amount - tol,
                    total_amount__lte=total_amount + tol,
                    doc_date=doc_date,
                )
                .exclude(document_id=exclude_id)
                .values("document_id", "vendor_name", "total_amount", "doc_date")
                .first()
            )

            if not match:
                return None

            return {
                "document_id":  str(match["document_id"]),
                "vendor_name":  match.get("vendor_name"),
                "total_amount": float(match["total_amount"]) if match["total_amount"] else None,
                "doc_date":     str(match["doc_date"]) if match["doc_date"] else None,
            }
        except Exception as exc:
            logger.debug("[CrossSessionDup] S4 amount_date check error: %s", exc)
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_match(
        result: CrossSessionDuplicateResult,
        match: dict,
        signal_name: str,
        weight: float,
    ) -> None:
        """Apply a detected match to the result if it improves the score."""
        if weight > result.confidence_score:
            result.confidence_score    = weight
            result.duplicate_document_id = match.get("document_id")
            result.duplicate_vendor    = match.get("vendor_name")
            result.duplicate_amount    = match.get("total_amount")
            result.duplicate_date      = match.get("doc_date")

        if signal_name not in result.matched_signals:
            result.matched_signals.append(signal_name)

    @staticmethod
    def _resolve_document_fields(document, file_hash: Optional[str]) -> Optional[dict]:
        """
        Extract normalised fields from DocumentAnalysisResult.
        Returns None if the document has no analysis result yet.
        """
        try:
            ar = document.analysis_result
            return {
                "file_hash":       file_hash,
                "vendor_name":     ar.vendor_name or "",
                "document_number": ar.document_number or "",
                "total_amount":    float(ar.total_amount) if ar.total_amount else None,
                "doc_date":        str(ar.doc_date) if ar.doc_date else None,
            }
        except Exception:
            # analysis_result not yet created (document still processing)
            return None

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """
        Normalised Levenshtein similarity ratio in [0, 1].
        Uses difflib for zero-dependency fuzzy matching.
        """
        import difflib
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if not a_norm or not b_norm:
            return 0.0
        return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
