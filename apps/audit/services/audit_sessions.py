"""Audit session workflow service."""

from django.db.models import Avg, Max
from django.utils import timezone

from apps.audit.models import AuditFinding, AuditSession


class AuditSessionService:
    """Explicit state and progress manager for audit sessions."""

    ALLOWED_TRANSITIONS = {
        AuditSession.Status.RECEIVED: {
            AuditSession.Status.EXTRACTING,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.EXTRACTING: {
            AuditSession.Status.NORMALIZING,
            AuditSession.Status.VALIDATING,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.NORMALIZING: {
            AuditSession.Status.VALIDATING,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.VALIDATING: {
            AuditSession.Status.ACTION_REQUIRED,
            AuditSession.Status.REVIEW_REQUIRED,
            AuditSession.Status.COMPLETED,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.REVIEW_REQUIRED: {
            AuditSession.Status.VALIDATING,
            AuditSession.Status.ACTION_REQUIRED,
            AuditSession.Status.COMPLETED,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.ACTION_REQUIRED: {
            AuditSession.Status.REVIEW_REQUIRED,
            AuditSession.Status.COMPLETED,
            AuditSession.Status.FAILED,
        },
        AuditSession.Status.COMPLETED: set(),
        AuditSession.Status.FAILED: set(),
    }

    @classmethod
    def create_session(cls, *, organization, created_by=None, name="", total_count=0, context=None):
        return AuditSession.objects.create(
            organization=organization,
            created_by=created_by,
            name=name,
            total_count=max(0, int(total_count or 0)),
            context=context or {},
        )

    @classmethod
    def sync_expected_total(cls, session: AuditSession, total_count: int):
        total_count = max(0, int(total_count or 0))
        if session.total_count == total_count:
            return session
        session.total_count = total_count
        session.save(update_fields=["total_count", "updated_at"])
        return session

    @classmethod
    def transition(cls, session: AuditSession, new_status: str, *, error_message: str = ""):
        if session.status == new_status:
            return session

        allowed = cls.ALLOWED_TRANSITIONS.get(session.status, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid audit session transition: {session.status} -> {new_status}")

        session.status = new_status
        update_fields = ["status", "updated_at"]

        if new_status == AuditSession.Status.EXTRACTING and not session.started_at:
            session.started_at = timezone.now()
            update_fields.append("started_at")

        if new_status == AuditSession.Status.COMPLETED:
            session.completed_at = timezone.now()
            session.failed_at = None
            session.last_error = ""
            update_fields.extend(["completed_at", "failed_at", "last_error"])

        if new_status == AuditSession.Status.FAILED:
            session.failed_at = timezone.now()
            session.completed_at = None
            if error_message:
                session.last_error = error_message
                update_fields.append("last_error")
            update_fields.extend(["failed_at", "completed_at"])

        if error_message and new_status != AuditSession.Status.FAILED:
            session.last_error = error_message
            update_fields.append("last_error")

        session.save(update_fields=list(dict.fromkeys(update_fields)))
        return session

    @classmethod
    def has_file_hash(cls, session: AuditSession, file_hash: str) -> bool:
        if not file_hash:
            return False
        return session.invoices.filter(extracted_data__file_hash=file_hash).exists()

    @classmethod
    def advance_to_extracting(cls, session: AuditSession):
        if session.status == AuditSession.Status.RECEIVED:
            return cls.transition(session, AuditSession.Status.EXTRACTING)
        return session

    @classmethod
    def advance_to_normalizing(cls, session: AuditSession):
        if session.status in {AuditSession.Status.RECEIVED, AuditSession.Status.EXTRACTING}:
            if session.status == AuditSession.Status.RECEIVED:
                cls.transition(session, AuditSession.Status.EXTRACTING)
                session.refresh_from_db(fields=["status", "started_at"])
            return cls.transition(session, AuditSession.Status.NORMALIZING)
        return session

    @classmethod
    def advance_to_validating(cls, session: AuditSession):
        if session.status == AuditSession.Status.RECEIVED:
            cls.transition(session, AuditSession.Status.EXTRACTING)
            session.refresh_from_db(fields=["status", "started_at"])
        if session.status in {
            AuditSession.Status.EXTRACTING,
            AuditSession.Status.NORMALIZING,
            AuditSession.Status.REVIEW_REQUIRED,
            AuditSession.Status.ACTION_REQUIRED,
        }:
            return cls.transition(session, AuditSession.Status.VALIDATING)
        return session

    @classmethod
    def record_success(cls, session: AuditSession, invoice, *, review_required: bool = False):
        cls._update_progress(
            session,
            processed_delta=1,
            success_delta=1,
            review_required_delta=1 if review_required else 0,
            duplicate_delta=1 if getattr(invoice, "is_duplicate", False) else 0,
            high_risk_delta=1 if getattr(invoice, "risk_level", "") in {"high", "critical"} else 0,
        )
        cls._refresh_risk_rollup(session)
        return cls.finalize_if_ready(session)

    @classmethod
    def record_failure(cls, session: AuditSession, error_message: str):
        cls._update_progress(
            session,
            processed_delta=1,
            failed_delta=1,
            error_message=error_message,
        )
        return cls.finalize_if_ready(session)

    @classmethod
    def finalize_if_ready(cls, session: AuditSession):
        from .summaries import AuditSessionSummaryService

        session.refresh_from_db()
        if not session.total_count or session.processed_count < session.total_count:
            return session

        if session.success_count == 0 and session.failed_count >= session.total_count:
            finalized = cls.transition(session, AuditSession.Status.FAILED, error_message=session.last_error)
            AuditSessionSummaryService.sync_session_context(finalized)
            return finalized

        has_critical_findings = session.findings.filter(
            status=AuditFinding.Status.OPEN,
            severity=AuditFinding.Severity.CRITICAL,
        ).exists()
        has_open_findings = session.findings.filter(status=AuditFinding.Status.OPEN).exists()

        if has_critical_findings:
            finalized = cls.transition(session, AuditSession.Status.ACTION_REQUIRED)
            AuditSessionSummaryService.sync_session_context(finalized)
            return finalized

        if session.review_required_count > 0 or session.failed_count > 0 or has_open_findings:
            finalized = cls.transition(session, AuditSession.Status.REVIEW_REQUIRED)
            AuditSessionSummaryService.sync_session_context(finalized)
            return finalized

        finalized = cls.transition(session, AuditSession.Status.COMPLETED)
        AuditSessionSummaryService.sync_session_context(finalized)
        return finalized

    @classmethod
    def _update_progress(
        cls,
        session: AuditSession,
        *,
        processed_delta: int = 0,
        success_delta: int = 0,
        failed_delta: int = 0,
        review_required_delta: int = 0,
        duplicate_delta: int = 0,
        high_risk_delta: int = 0,
        error_message: str = "",
    ):
        session.processed_count = max(0, session.processed_count + processed_delta)
        session.success_count = max(0, session.success_count + success_delta)
        session.failed_count = max(0, session.failed_count + failed_delta)
        session.review_required_count = max(0, session.review_required_count + review_required_delta)
        session.duplicate_count = max(0, session.duplicate_count + duplicate_delta)
        session.high_risk_count = max(0, session.high_risk_count + high_risk_delta)
        if error_message:
            session.last_error = error_message

        update_fields = [
            "processed_count",
            "success_count",
            "failed_count",
            "review_required_count",
            "duplicate_count",
            "high_risk_count",
            "updated_at",
        ]
        if error_message:
            update_fields.append("last_error")
        session.save(update_fields=update_fields)
        return session

    @classmethod
    def _refresh_risk_rollup(cls, session: AuditSession):
        aggregates = session.invoices.aggregate(
            avg_risk=Avg("risk_score"),
            max_risk=Max("risk_score"),
        )
        session.average_risk_score = float(aggregates.get("avg_risk") or 0.0)
        session.max_risk_score = float(aggregates.get("max_risk") or 0.0)
        session.save(update_fields=["average_risk_score", "max_risk_score", "updated_at"])
        return session
