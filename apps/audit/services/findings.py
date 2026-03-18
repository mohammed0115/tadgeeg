"""Persistence helpers for user-facing audit findings."""

from __future__ import annotations

from django.utils import timezone

from apps.audit.models import AuditFinding


class AuditFindingService:
    """Create and resolve audit findings from deterministic validation output."""

    @classmethod
    def persist_validation_findings(
        cls,
        *,
        invoice,
        validation_result: dict,
        audit_session=None,
        document=None,
        created_by=None,
    ) -> dict:
        rule_details = validation_result.get("rule_details") or {}
        failed_codes = set(validation_result.get("failed_rule_codes") or [])

        summary = {
            "created_or_updated": 0,
            "resolved": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }

        existing = {
            finding.rule_code: finding
            for finding in AuditFinding.objects.filter(
                invoice=invoice,
                source="validation_engine",
            )
        }

        for code in failed_codes:
            detail = rule_details.get(code) or {}
            severity = cls._normalize_severity(detail.get("severity"))
            finding = existing.get(code)
            defaults = {
                "organization": invoice.organization,
                "audit_session": audit_session or invoice.audit_session,
                "document": document,
                "invoice": invoice,
                "created_by": created_by,
                "rule_code": code,
                "rule_name": detail.get("description") or code,
                "rule_group": code.split("-")[0],
                "severity": severity,
                "status": AuditFinding.Status.OPEN,
                "message": detail.get("message") or detail.get("description") or code,
                "details": detail,
                "resolved_at": None,
                "resolved_by": None,
                "source": "validation_engine",
            }
            if finding:
                for key, value in defaults.items():
                    setattr(finding, key, value)
                finding.last_detected_at = timezone.now()
                finding.save()
            else:
                AuditFinding.objects.create(**defaults)
            summary["created_or_updated"] += 1
            summary[severity] += 1

        for code, finding in existing.items():
            if code in failed_codes or finding.status == AuditFinding.Status.IGNORED:
                continue
            if finding.status != AuditFinding.Status.RESOLVED:
                finding.status = AuditFinding.Status.RESOLVED
                finding.resolved_at = timezone.now()
                finding.resolved_by = created_by
                finding.save(update_fields=["status", "resolved_at", "resolved_by", "last_detected_at"])
                summary["resolved"] += 1

        return summary

    @staticmethod
    def _normalize_severity(value: str | None) -> str:
        normalized = str(value or "medium").strip().lower()
        if normalized in {
            AuditFinding.Severity.CRITICAL,
            AuditFinding.Severity.HIGH,
            AuditFinding.Severity.MEDIUM,
            AuditFinding.Severity.LOW,
        }:
            return normalized
        return AuditFinding.Severity.MEDIUM
