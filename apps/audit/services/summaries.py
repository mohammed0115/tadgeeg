"""Audit session executive summary generation."""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Q

from apps.audit.models import AuditFinding
from apps.billing.ai_access import ai_access_allowed
from core.services.ai_service import generate_audit_narrative


class AuditSessionSummaryService:
    """Build grounded executive summaries from structured session data only."""

    @classmethod
    def build_snapshot(cls, session) -> dict:
        findings = session.findings.filter(status=AuditFinding.Status.OPEN)
        finding_totals = findings.aggregate(
            critical=Count("id", filter=Q(severity=AuditFinding.Severity.CRITICAL)),
            high=Count("id", filter=Q(severity=AuditFinding.Severity.HIGH)),
            medium=Count("id", filter=Q(severity=AuditFinding.Severity.MEDIUM)),
            low=Count("id", filter=Q(severity=AuditFinding.Severity.LOW)),
        )

        top_findings = list(
            findings.order_by("-last_detected_at").values("rule_code", "severity", "message")[:5]
        )

        recommendations = []
        if finding_totals["critical"]:
            recommendations.append("معالجة البنود الحرجة قبل أي اعتماد أو إقفال للجلسة.")
        if session.duplicate_count:
            recommendations.append("مراجعة الفواتير المكررة والتحقق من عدم صرفها مرتين.")
        if session.review_required_count:
            recommendations.append("توجيه البنود المتبقية إلى المراجعة اليدوية وإغلاق أسباب التعليق.")
        if not recommendations:
            recommendations.append("الجلسة مستقرة، ويمكن الانتقال إلى إعداد التقرير النهائي.")

        return {
            "session_id": str(session.id),
            "status": session.status,
            "total_documents": session.total_count,
            "processed_count": session.processed_count,
            "success_count": session.success_count,
            "failed_count": session.failed_count,
            "review_required_count": session.review_required_count,
            "duplicate_count": session.duplicate_count,
            "high_risk_count": session.high_risk_count,
            "average_risk_score": round(float(session.average_risk_score or 0), 2),
            "max_risk_score": round(float(session.max_risk_score or 0), 2),
            "finding_totals": finding_totals,
            "top_findings": top_findings,
            "recommendations": recommendations,
        }

    @classmethod
    def generate_summary(cls, session, *, language: str = "ar", use_ai: bool = False) -> dict:
        snapshot = cls.build_snapshot(session)
        summary = cls._deterministic_summary(snapshot, language=language)
        source = "deterministic"

        org = getattr(session, "organization", None)
        if use_ai and getattr(settings, "OPENAI_API_KEY", "") and ai_access_allowed(org):
            try:
                narrative = generate_audit_narrative(
                    {
                        "session": snapshot,
                        "top_findings": snapshot["top_findings"],
                        "recommendations": snapshot["recommendations"],
                    },
                    language=language,
                )
                summary = narrative.get("executive_summary") or summary
                source = "ai_grounded"
            except Exception:
                source = "deterministic"

        return {
            "language": language,
            "source": source,
            "summary": summary,
            "snapshot": snapshot,
        }

    @classmethod
    def sync_session_context(cls, session) -> dict:
        payload = {
            "ar": cls.generate_summary(session, language="ar", use_ai=False),
            "en": cls.generate_summary(session, language="en", use_ai=False),
        }
        context = dict(session.context or {})
        context["executive_summary"] = payload
        session.context = context
        session.save(update_fields=["context", "updated_at"])
        return payload

    @staticmethod
    def _deterministic_summary(snapshot: dict, *, language: str = "ar") -> str:
        finding_totals = snapshot["finding_totals"]
        if language == "en":
            return (
                f"Processed {snapshot['processed_count']} of {snapshot['total_documents']} documents. "
                f"{snapshot['review_required_count']} require review, {snapshot['duplicate_count']} are duplicates, "
                f"and {finding_totals.get('critical', 0)} critical findings remain open."
            )

        return (
            f"تمت معالجة {snapshot['processed_count']} من أصل {snapshot['total_documents']} مستندات. "
            f"هناك {snapshot['review_required_count']} عناصر تحتاج مراجعة، و{snapshot['duplicate_count']} حالات تكرار، "
            f"مع بقاء {finding_totals.get('critical', 0)} ملاحظة حرجة مفتوحة."
        )
