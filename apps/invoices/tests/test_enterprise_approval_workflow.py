from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.authentication.models import Organization, User
from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription, Plan
from apps.invoices.models import ApprovalWorkflow, Invoice, InvoiceApprovalRequest
from apps.invoices.services.approval_workflow_service import (
    ApprovalWorkflowError,
    decide,
    request_approval,
)


@pytest.mark.django_db
def test_enterprise_multistage_workflow_rejects_self_approval_and_completes():
    call_command("seed_billing_plans")
    org = Organization.objects.create(name="Workflow Enterprise")
    plan = Plan.objects.get(code=PlanCode.ENTERPRISE)
    now = timezone.now()
    OrganizationSubscription.objects.create(
        organization=org, plan=plan, status=SubscriptionStatus.ACTIVE,
        starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29),
        invoice_limit=plan.invoice_limit, user_limit=plan.user_limit,
        feature_tiers_snapshot=plan.feature_tiers,
    )
    requester = User.objects.create_user(
        email="requester@workflow.test", password="x", full_name="Requester",
        organization=org, role=User.Role.FINANCE_MANAGER,
    )
    manager = User.objects.create_user(
        email="manager@workflow.test", password="x", full_name="Manager",
        organization=org, role=User.Role.FINANCE_MANAGER,
    )
    cao = User.objects.create_user(
        email="cao@workflow.test", password="x", full_name="CAO",
        organization=org, role=User.Role.CHIEF_AUDIT_OFFICER,
    )
    invoice = Invoice.objects.create(
        organization=org, uploaded_by=requester, original_filename="workflow.pdf",
        total_amount="1000.00",
    )
    workflow = ApprovalWorkflow.objects.create(
        organization=org, name="Two eyes", stages=[
            {"role": User.Role.FINANCE_MANAGER},
            {"role": User.Role.CHIEF_AUDIT_OFFICER},
        ],
    )
    request = request_approval(invoice=invoice, workflow=workflow, requester=requester)
    assert request.status == InvoiceApprovalRequest.Status.PENDING

    with pytest.raises(ApprovalWorkflowError, match="Requester"):
        decide(request=request, approver=requester, decision="approved")

    request = decide(request=request, approver=manager, decision="approved")
    assert request.current_stage == 1
    request = decide(request=request, approver=cao, decision="approved")
    assert request.status == InvoiceApprovalRequest.Status.APPROVED
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.APPROVED
    assert invoice.approved_by == cao
