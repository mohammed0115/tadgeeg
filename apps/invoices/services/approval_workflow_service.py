"""Enterprise sequential invoice approval workflow."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.services.features import require_feature
from apps.invoices.models import (
    ApprovalWorkflow,
    Invoice,
    InvoiceApprovalDecision,
    InvoiceApprovalRequest,
)


class ApprovalWorkflowError(PermissionError):
    pass


def _stages(workflow: ApprovalWorkflow) -> list[dict]:
    stages = workflow.stages if isinstance(workflow.stages, list) else []
    if not stages:
        raise ApprovalWorkflowError("Workflow has no approval stages.")
    return stages


def request_approval(*, invoice: Invoice, workflow: ApprovalWorkflow, requester):
    require_feature(invoice.organization, "approvals", minimum_tier="multi")
    if workflow.organization_id != invoice.organization_id:
        raise ApprovalWorkflowError("Workflow and invoice must belong to the same organization.")
    if not workflow.is_active or Decimal(str(invoice.total_amount)) < workflow.minimum_amount:
        raise ApprovalWorkflowError("Workflow is not applicable to this invoice.")
    _stages(workflow)
    request, created = InvoiceApprovalRequest.objects.get_or_create(
        invoice=invoice,
        defaults={"workflow": workflow, "requested_by": requester},
    )
    if not created:
        raise ApprovalWorkflowError("An approval request already exists for this invoice.")
    return request


@transaction.atomic
def decide(*, request: InvoiceApprovalRequest, approver, decision: str, reason: str = ""):
    request = InvoiceApprovalRequest.objects.select_for_update().select_related(
        "invoice", "workflow"
    ).get(pk=request.pk)
    if request.status != InvoiceApprovalRequest.Status.PENDING:
        raise ApprovalWorkflowError("Approval request is no longer pending.")
    if request.invoice.organization_id != request.workflow.organization_id:
        raise ApprovalWorkflowError("Approval request organization integrity failure.")
    require_feature(request.invoice.organization, "approvals", minimum_tier="multi")

    stages = _stages(request.workflow)
    required_role = stages[request.current_stage].get("role")
    if required_role and getattr(approver, "role", None) != required_role:
        raise ApprovalWorkflowError("Approver does not have the required workflow role.")
    if approver.id in {request.requested_by_id, request.invoice.uploaded_by_id}:
        raise ApprovalWorkflowError("Requester or uploader cannot approve this invoice.")
    if decision not in InvoiceApprovalDecision.Decision.values:
        raise ApprovalWorkflowError("Unknown approval decision.")
    if decision == InvoiceApprovalDecision.Decision.REJECTED and not reason.strip():
        raise ApprovalWorkflowError("A rejection reason is required.")

    InvoiceApprovalDecision.objects.create(
        request=request,
        stage=request.current_stage,
        approver=approver,
        decision=decision,
        reason=reason.strip(),
    )
    if decision == InvoiceApprovalDecision.Decision.REJECTED:
        request.status = InvoiceApprovalRequest.Status.REJECTED
        request.resolved_at = timezone.now()
    elif request.current_stage + 1 == len(stages):
        request.status = InvoiceApprovalRequest.Status.APPROVED
        request.resolved_at = timezone.now()
        request.invoice.status = Invoice.Status.APPROVED
        request.invoice.approved_by = approver
        request.invoice.approved_at = timezone.now()
        request.invoice.save(update_fields=["status", "approved_by", "approved_at"])
    else:
        request.current_stage += 1
    request.save(update_fields=["status", "current_stage", "resolved_at"])
    return request
