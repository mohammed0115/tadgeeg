"""Finding Repository — data access layer for AuditFinding."""

import logging
from typing import List

from ..models import AuditDocument, AuditFinding

logger = logging.getLogger(__name__)


class FindingRepository:
    @staticmethod
    def bulk_create_from_ai_result(doc: AuditDocument, ai_result: dict) -> None:
        findings = []

        for anomaly in ai_result.get("anomalies") or []:
            if not isinstance(anomaly, dict):
                continue
            findings.append(
                AuditFinding(
                    document=doc,
                    finding_type=AuditFinding.FindingType.ANOMALY,
                    severity=anomaly.get("severity", "low"),
                    title=str(anomaly.get("type", "Anomaly"))[:255],
                    details=anomaly.get("details", ""),
                    source="ai",
                )
            )

        for vr in ai_result.get("validation_results") or []:
            if not isinstance(vr, dict):
                continue
            if vr.get("status") in ("warning", "failed"):
                findings.append(
                    AuditFinding(
                        document=doc,
                        finding_type=AuditFinding.FindingType.VALIDATION,
                        severity="high" if vr.get("status") == "failed" else "medium",
                        title=str(vr.get("check", "Validation Issue"))[:255],
                        details=vr.get("details", ""),
                        source="ai",
                    )
                )

        if findings:
            AuditFinding.objects.bulk_create(findings)
            logger.info(
                "FindingRepository: created %d findings for document %s",
                len(findings),
                doc.pk,
            )

    # Legacy interface used by the existing AuditProcessingService
    def bulk_create(self, document, findings: list) -> list:
        """Create AuditFinding records from list of dicts (legacy interface)."""
        if not findings:
            return []

        objs = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            objs.append(
                AuditFinding(
                    document=document,
                    finding_type=f.get("finding_type", "validation"),
                    severity=f.get("severity", "low"),
                    title=str(f.get("title", ""))[:255],
                    details=str(f.get("details", "")),
                    source=f.get("source", "ai"),
                )
            )

        try:
            created = AuditFinding.objects.bulk_create(objs, ignore_conflicts=True)
            logger.info(
                "FindingRepository: created %d findings for document %s",
                len(created),
                document.pk,
            )
            return created
        except Exception as exc:
            logger.exception(
                "FindingRepository.bulk_create failed for document %s: %s",
                document.pk,
                exc,
            )
            return []
