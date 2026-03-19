"""Finding Repository — data access layer for AuditFinding."""

import logging

logger = logging.getLogger(__name__)


class FindingRepository:
    """Data access layer for AuditFinding model."""

    def bulk_create(self, document, findings: list) -> list:
        """
        Bulk create AuditFinding records for a document.

        Each dict in findings should have:
            finding_type, severity, title, details (optional)
        """
        from apps.auditing.models import AuditFinding

        if not findings:
            return []

        objs = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            objs.append(AuditFinding(
                document=document,
                finding_type=f.get("finding_type", "validation"),
                severity=f.get("severity", "low"),
                title=str(f.get("title", ""))[:255],
                details=str(f.get("details", "")),
            ))

        try:
            created = AuditFinding.objects.bulk_create(objs, ignore_conflicts=True)
            logger.info(
                "FindingRepository: created %d findings for document %s",
                len(created), document.pk,
            )
            return created
        except Exception as exc:
            logger.exception(
                "FindingRepository.bulk_create failed for document %s: %s",
                document.pk, exc,
            )
            return []
