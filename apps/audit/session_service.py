"""
AuditSession Service

Manages the full AuditSession lifecycle:
- Creation from an upload request
- State transitions (validated against state machine)
- Progress tracking (incremental counter updates)
- Completion checks and risk summary computation
- Executive summary generation
- Error capture

Usage:
    svc = AuditSessionService(session)
    svc.transition(AuditSession.State.EXTRACTING)
    svc.record_document_result(success=True, requires_review=False)
    svc.maybe_complete()
"""

import logging
from django.db import transaction
from django.utils import timezone

from .models import AuditSession, AuditFinding

logger = logging.getLogger("finai")


class InvalidStateTransition(Exception):
    pass


class AuditSessionService:
    """Service class that manages a single AuditSession instance."""

    def __init__(self, session: AuditSession):
        self.session = session

    # ── State machine ─────────────────────────────────────────────────────────

    def transition(self, new_state: str, *, save: bool = True) -> AuditSession:
        """
        Move session to new_state.

        Raises InvalidStateTransition if the transition is not allowed.
        Sets started_at / completed_at timestamps where appropriate.
        """
        session = self.session
        if not session.can_transition_to(new_state):
            raise InvalidStateTransition(
                f"Cannot transition {session.state!r} → {new_state!r} "
                f"for session {session.id}"
            )

        old_state = session.state
        session.state = new_state

        if new_state == AuditSession.State.EXTRACTING and not session.started_at:
            session.started_at = timezone.now()

        if new_state in (AuditSession.State.COMPLETED, AuditSession.State.FAILED):
            session.completed_at = timezone.now()

        if save:
            session.save(update_fields=["state", "started_at", "completed_at", "updated_at"])

        logger.info(
            "[AuditSession] %s transitioned %s → %s",
            session.id, old_state, new_state,
        )
        return session

    # ── Progress tracking ─────────────────────────────────────────────────────

    def record_document_result(
        self,
        *,
        success: bool,
        requires_review: bool = False,
        risk_score: float = 0.0,
        is_duplicate: bool = False,
        has_compliance_issue: bool = False,
        error_msg: str = "",
    ) -> None:
        """
        Atomically increment counters after one document finishes processing.
        Thread-safe: uses F() expressions.
        """
        from django.db.models import F

        updates: dict = {"processed_count": F("processed_count") + 1}

        if success:
            updates["success_count"] = F("success_count") + 1
        else:
            updates["failed_count"] = F("failed_count") + 1
            if error_msg:
                # Append error to log
                self.session.refresh_from_db(fields=["error_log"])
                self.session.error_log = (self.session.error_log or []) + [error_msg]
                self.session.save(update_fields=["error_log"])

        if requires_review:
            updates["review_required_count"] = F("review_required_count") + 1

        if is_duplicate:
            updates["duplicate_count"] = F("duplicate_count") + 1

        if has_compliance_issue:
            updates["compliance_issues"] = F("compliance_issues") + 1

        if risk_score >= 50:
            updates["high_risk_count"] = F("high_risk_count") + 1

        AuditSession.objects.filter(pk=self.session.pk).update(**updates)
        self.session.refresh_from_db()

    def maybe_complete(self) -> bool:
        """
        Check if all documents have been processed.
        If so, compute risk summary and transition to COMPLETED or REVIEW_REQUIRED.

        Returns True if session was finalised.
        """
        self.session.refresh_from_db()
        s = self.session

        if s.is_terminal:
            return False

        if s.total_count == 0 or s.processed_count < s.total_count:
            return False

        # Compute aggregate risk
        self._compute_risk_summary()

        # Determine terminal state
        needs_review = s.review_required_count > 0 or s.high_risk_count > 0
        terminal = (
            AuditSession.State.REVIEW_REQUIRED if needs_review
            else AuditSession.State.COMPLETED
        )

        try:
            if s.state == AuditSession.State.VALIDATING:
                self.transition(terminal)
            elif s.state not in (AuditSession.State.COMPLETED, AuditSession.State.FAILED,
                                  AuditSession.State.REVIEW_REQUIRED):
                # Jump directly to terminal if we somehow skipped VALIDATING
                s.state = terminal
                s.completed_at = timezone.now()
                s.save(update_fields=["state", "completed_at", "updated_at"])
        except InvalidStateTransition:
            logger.warning("[AuditSession] Could not auto-complete %s from state %s", s.id, s.state)
            return False

        logger.info(
            "[AuditSession] %s finalised as %s | docs=%d ok=%d fail=%d review=%d",
            s.id, terminal, s.total_count, s.success_count, s.failed_count, s.review_required_count,
        )
        return True

    # ── Risk summary ──────────────────────────────────────────────────────────

    def _compute_risk_summary(self) -> None:
        """Aggregate risk scores from linked invoices and save to session."""
        try:
            from apps.invoices.models import Invoice
            from django.db.models import Avg

            qs = Invoice.objects.filter(batch__audit_session=self.session)
            agg = qs.aggregate(avg_risk=Avg("risk_score"))
            avg_score = float(agg.get("avg_risk") or 0)

            if avg_score >= 75:
                level = "critical"
            elif avg_score >= 50:
                level = "high"
            elif avg_score >= 25:
                level = "medium"
            else:
                level = "low"

            AuditSession.objects.filter(pk=self.session.pk).update(
                overall_risk_score=avg_score,
                overall_risk_level=level,
            )
            self.session.refresh_from_db()
        except Exception as exc:
            logger.warning("[AuditSession] Risk summary failed: %s", exc)

    # ── Executive summary ─────────────────────────────────────────────────────

    def generate_executive_summary(self, language: str = "ar") -> dict:
        """
        Generate an AI executive summary for this session and persist it.
        """
        from core.services.ai_service import generate_audit_narrative

        s = self.session
        payload = {
            "organization": {"name": s.organization.name},
            "report_type":  "executive_summary",
            "audit_period": {
                "from": s.started_at.isoformat() if s.started_at else None,
                "to":   s.completed_at.isoformat() if s.completed_at else None,
            },
            "session_stats": {
                "total_documents":   s.total_count,
                "processed":         s.processed_count,
                "success":           s.success_count,
                "failed":            s.failed_count,
                "review_required":   s.review_required_count,
                "duplicates":        s.duplicate_count,
                "compliance_issues": s.compliance_issues,
                "high_risk":         s.high_risk_count,
                "overall_risk_score": s.overall_risk_score,
                "overall_risk_level": s.overall_risk_level,
            },
        }

        try:
            narrative = generate_audit_narrative(payload, language=language)
        except Exception as exc:
            logger.warning("[AuditSession] AI narrative failed: %s", exc)
            narrative = {}

        AuditSession.objects.filter(pk=s.pk).update(executive_summary=narrative)
        s.executive_summary = narrative
        return narrative

    # ── Findings helper ───────────────────────────────────────────────────────

    def add_finding(
        self,
        *,
        title: str,
        description: str,
        category: str = AuditFinding.Category.OTHER,
        severity: str = AuditFinding.Severity.MEDIUM,
        rule_code: str = "",
        invoice=None,
        document=None,
        evidence: dict = None,
        remediation: str = "",
    ) -> AuditFinding:
        """Create an AuditFinding linked to this session."""
        return AuditFinding.objects.create(
            organization=self.session.organization,
            session=self.session,
            invoice=invoice,
            document=document,
            rule_code=rule_code,
            category=category,
            severity=severity,
            title=title,
            description=description,
            evidence=evidence or {},
            remediation=remediation,
        )

    # ── Class-level factory ───────────────────────────────────────────────────

    @classmethod
    def create_session(
        cls,
        organization,
        created_by,
        total_count: int,
        session_name: str = "",
    ) -> "AuditSessionService":
        """Create a new AuditSession and return its service wrapper."""
        session = AuditSession.objects.create(
            organization=organization,
            created_by=created_by,
            session_name=session_name or f"Upload {timezone.now().strftime('%Y-%m-%d %H:%M')}",
            total_count=total_count,
            state=AuditSession.State.RECEIVED,
        )
        logger.info(
            "[AuditSession] Created %s for org=%s user=%s docs=%d",
            session.id, organization.id, created_by.id if created_by else "?", total_count,
        )
        return cls(session)
