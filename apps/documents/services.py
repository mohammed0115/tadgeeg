"""
Documents App — Service Layer

DocumentStateHistoryService:
    Append-only recorder for Document.processing_status transitions.
    All writes go through this class — never write DocumentStateHistory directly.

Usage:
    from apps.documents.services import DocumentStateHistoryService

    DocumentStateHistoryService.record(
        document=doc,
        from_state=Document.ProcessingStatus.PENDING,
        to_state=Document.ProcessingStatus.PROCESSING,
        reason="Pipeline stage 1 started",
        metadata={"pipeline_version": "2.0"},
    )
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Optional

logger = logging.getLogger("finai")


class DocumentStateHistoryService:
    """
    Append-only recorder for Document processing_status transitions.

    Design:
      - Classmethod API — no instance state, fully stateless.
      - Never raises — all DB errors are caught and logged.
      - Auto-enriches metadata with worker hostname + timestamp.
      - Uses bulk_create for batch recording (pipeline checkpoints).
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    @classmethod
    def record(
        cls,
        *,
        document,
        from_state: str,
        to_state: str,
        changed_by=None,
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional["DocumentStateHistory"]:   # type: ignore[name-defined]  # noqa: F821
        """
        Record a single state transition.

        Args:
            document:    Document model instance.
            from_state:  Previous ProcessingStatus value (empty string for initial).
            to_state:    New ProcessingStatus value.
            changed_by:  User instance or None (system/Celery transition).
            reason:      Human-readable reason for the transition.
            metadata:    Arbitrary JSON context (pipeline_version, ms, worker …).

        Returns:
            Saved DocumentStateHistory instance, or None on DB error.
        """
        from .models import DocumentStateHistory

        enriched = cls._enrich_metadata(metadata or {})

        logger.info(
            "[DocumentStateHistory] doc=%s %s → %s | reason=%r | who=%s",
            document.pk,
            from_state or "—",
            to_state,
            reason,
            getattr(changed_by, "email", "system"),
        )

        try:
            entry = DocumentStateHistory(
                document=document,
                from_state=from_state or "",
                to_state=to_state,
                changed_by=changed_by,
                reason=reason[:500],
                metadata=enriched,
            )
            entry.save()
            return entry
        except Exception as exc:
            logger.warning(
                "[DocumentStateHistory] Failed to record doc=%s %s→%s: %s",
                document.pk, from_state, to_state, exc,
            )
            return None

    @classmethod
    def record_bulk(
        cls,
        entries: list[dict[str, Any]],
    ) -> int:
        """
        Bulk-insert multiple history entries in one DB round-trip.

        Each entry is a dict with keys matching `record()` kwargs.
        Returns the count of rows inserted.

        Usage:
            DocumentStateHistoryService.record_bulk([
                {"document": doc1, "from_state": "pending", "to_state": "processing", ...},
                {"document": doc2, "from_state": "processing", "to_state": "failed", ...},
            ])
        """
        from .models import DocumentStateHistory

        objects = []
        for e in entries:
            enriched = cls._enrich_metadata(e.get("metadata") or {})
            objects.append(
                DocumentStateHistory(
                    document=e["document"],
                    from_state=e.get("from_state") or "",
                    to_state=e["to_state"],
                    changed_by=e.get("changed_by"),
                    reason=(e.get("reason") or "")[:500],
                    metadata=enriched,
                )
            )

        if not objects:
            return 0

        try:
            created = DocumentStateHistory.objects.bulk_create(objects, ignore_conflicts=False)
            logger.info("[DocumentStateHistory] Bulk inserted %d entries", len(created))
            return len(created)
        except Exception as exc:
            logger.warning("[DocumentStateHistory] Bulk insert failed: %s", exc)
            return 0

    @classmethod
    def get_history(
        cls,
        document,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return the state history for a Document as a list of dicts.
        Ordered chronologically (oldest first).

        Avoids N+1: fetches changed_by in the same query.
        """
        from .models import DocumentStateHistory

        qs = (
            DocumentStateHistory.objects
            .filter(document=document)
            .select_related("changed_by")
            .order_by("created_at")[:limit]
        )

        result = []
        for entry in qs:
            result.append({
                "id":         str(entry.id),
                "from_state": entry.from_state or None,
                "to_state":   entry.to_state,
                "changed_by": entry.changed_by.email if entry.changed_by_id else "system",
                "reason":     entry.reason,
                "metadata":   entry.metadata,
                "created_at": entry.created_at.isoformat(),
            })
        return result

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _enrich_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """Inject worker hostname into metadata for traceability."""
        enriched = dict(metadata)
        if "worker" not in enriched:
            try:
                enriched["worker"] = socket.gethostname()
            except Exception:
                enriched["worker"] = "unknown"
        return enriched
