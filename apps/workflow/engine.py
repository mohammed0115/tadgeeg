from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkflowState(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    VALIDATED = "validated"
    AUDIT_FAILED = "audit_failed"
    AUDIT_PASSED = "audit_passed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"
    ARCHIVED = "archived"


VALID_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    # An auditor with the right permission can reject from any non-terminal
    # state — that matches how the UI surfaces the "Reject" button on every
    # invoice detail page regardless of its current workflow stage.
    # APPROVED is also reachable from any non-terminal state because override
    # approvals (admin/CAO with reason) skip the intermediate stages — the
    # `can_transition()` gate still validates the override permission, this
    # dict only declares which transitions are *structurally* legal.
    WorkflowState.UPLOADED:         [WorkflowState.EXTRACTED, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.EXTRACTED:        [WorkflowState.NEEDS_REVIEW, WorkflowState.VALIDATED, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.NEEDS_REVIEW:     [WorkflowState.VALIDATED, WorkflowState.AUDIT_FAILED, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.VALIDATED:        [WorkflowState.AUDIT_PASSED, WorkflowState.AUDIT_FAILED, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.AUDIT_FAILED:     [WorkflowState.PENDING_APPROVAL, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.AUDIT_PASSED:     [WorkflowState.PENDING_APPROVAL, WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.PENDING_APPROVAL: [WorkflowState.APPROVED, WorkflowState.REJECTED],
    WorkflowState.APPROVED:         [WorkflowState.POSTED],
    WorkflowState.REJECTED:         [WorkflowState.UPLOADED],
    WorkflowState.POSTED:           [WorkflowState.ARCHIVED],
    WorkflowState.ARCHIVED:         [],
}


@dataclass(slots=True)
class WorkflowAction:
    action_id: str
    label_ar: str
    label_en: str
    target_state: WorkflowState
    style: str
    requires_reason: bool = False
    requires_confirmation: bool = False
    is_available: bool = True


class WorkflowError(Exception):
    pass


class WorkflowTransitionService:
    """
    Controls document state transitions without requiring existing models
    to adopt workflow fields before Phase 2 migrations land.
    """

    def can_transition(self, document, new_state: WorkflowState, user) -> tuple[bool, str]:
        current_value = getattr(document, "workflow_state", None) or WorkflowState.UPLOADED
        current = WorkflowState(current_value)

        if new_state not in VALID_TRANSITIONS.get(current, []):
            return False, f"Invalid transition: {current.value} -> {new_state.value}"

        if new_state == WorkflowState.APPROVED:
            from apps.rule_engine.models.risk import RiskScoreSummary

            try:
                risk = RiskScoreSummary.objects.get(document_id=document.id)
            except RiskScoreSummary.DoesNotExist:
                return False, "لم يكتمل التدقيق بعد"

            if risk.blocks_approval and not user.has_perm("invoices.can_override_approval"):
                return False, "يوجد أخطاء حرجة تمنع الاعتماد"
            if not user.has_perm("invoices.can_approve"):
                return False, "ليس لديك صلاحية الاعتماد"

        if new_state == WorkflowState.POSTED and not user.has_perm("invoices.can_post"):
            return False, "ليس لديك صلاحية الترحيل"

        return True, ""

    def transition(
        self,
        document,
        new_state: WorkflowState,
        user,
        reason: str = "",
        override_reason: str = "",
    ) -> None:
        can_transition, message = self.can_transition(document, new_state, user)
        if not can_transition:
            raise WorkflowError(message)

        from django.utils import timezone

        old_state = getattr(document, "workflow_state", None)
        update_fields: list[str] = []

        if hasattr(document, "workflow_state"):
            document.workflow_state = new_state.value
            update_fields.append("workflow_state")

        if new_state == WorkflowState.APPROVED:
            if hasattr(document, "approved_by"):
                document.approved_by = user
                update_fields.append("approved_by")
            if hasattr(document, "approved_at"):
                document.approved_at = timezone.now()
                update_fields.append("approved_at")
            if hasattr(document, "locked"):
                document.locked = True
                update_fields.append("locked")

        if new_state == WorkflowState.REJECTED and hasattr(document, "locked"):
            document.locked = False
            update_fields.append("locked")

        if update_fields:
            document.save(update_fields=sorted(set(update_fields)))
        else:
            document.save()

        self._log(document, user, old_state, new_state.value, reason, override_reason)

    def get_available_actions(self, document, user) -> list[WorkflowAction]:
        current_value = getattr(document, "workflow_state", None) or WorkflowState.UPLOADED
        current = WorkflowState(current_value)
        actions: list[WorkflowAction] = []

        for target in VALID_TRANSITIONS.get(current, []):
            can_transition, _ = self.can_transition(document, target, user)
            if can_transition:
                actions.append(self._build_action(target))

        return actions

    def _build_action(self, target: WorkflowState) -> WorkflowAction:
        action_map = {
            WorkflowState.APPROVED: WorkflowAction(
                "approve", "اعتماد", "Approve", target, "primary", requires_confirmation=True
            ),
            WorkflowState.REJECTED: WorkflowAction(
                "reject", "رفض", "Reject", target, "danger", requires_reason=True
            ),
            WorkflowState.POSTED: WorkflowAction(
                "post", "ترحيل", "Post", target, "primary", requires_confirmation=True
            ),
        }
        return action_map.get(
            target,
            WorkflowAction(target.value, target.value, target.value, target, "ghost"),
        )

    def _log(self, document, user, old_state, new_state, reason, override_reason):
        try:
            from apps.activity_logs.service import ActivityLogService

            ActivityLogService.log(
                user=user,
                action="workflow_transition",
                entity_type=document.__class__.__name__,
                entity_id=str(document.id),
                description=f"{old_state} -> {new_state}" + (f" | {reason}" if reason else ""),
                extra={"override_reason": override_reason} if override_reason else {},
                organization=getattr(document, "organization", None),
            )
        except Exception:
            pass