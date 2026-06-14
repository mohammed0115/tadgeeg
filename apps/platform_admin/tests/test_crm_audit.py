"""Audit-helper tests (CRM-1B).

Confirms CRM actions are recorded in the EXISTING AuditLog without extending its
Action enum, with the detailed verb in details["action_type"], plus an optional
CustomerActivity timeline entry.
"""

import pytest

from apps.authentication.models import AuditLog
from apps.platform_admin.models import CustomerActivity
from apps.platform_admin.services.crm_audit import log_crm_action

pytestmark = pytest.mark.django_db


def test_log_crm_action_writes_auditlog(organization, owner_user):
    audit = log_crm_action(
        actor=owner_user,
        organization=organization,
        action_type="customer_suspended",
        resource_type="organization",
        resource_id=organization.id,
        reason="Non-payment",
        old_value={"is_active": True},
        new_value={"is_active": False},
        metadata={"source": "test"},
    )
    assert audit is not None
    audit.refresh_from_db()
    assert audit.user_id == owner_user.id
    assert audit.organization_id == organization.id
    assert audit.resource_type == "organization"
    assert audit.resource_id == str(organization.id)


def test_details_carry_action_type_and_payload(organization, owner_user):
    audit = log_crm_action(
        actor=owner_user,
        organization=organization,
        action_type="note_added",
        resource_type="customer_note",
        resource_id="123",
        reason="context",
        old_value={"a": 1},
        new_value={"a": 2},
    )
    assert audit.details["action_type"] == "note_added"
    assert audit.details["reason"] == "context"
    assert audit.details["old_value"] == {"a": 1}
    assert audit.details["new_value"] == {"a": 2}


def test_uses_existing_action_choice_not_extended(organization, owner_user):
    audit = log_crm_action(
        actor=owner_user,
        organization=organization,
        action_type="ticket_created",
        resource_type="support_ticket",
        resource_id="t1",
    )
    # The umbrella action MUST be an existing AuditLog.Action choice. The detailed
    # CRM verb lives only in details — the enum is never extended.
    assert audit.action in AuditLog.Action.values
    assert audit.action == AuditLog.Action.CONFIG_CHANGED
    assert "ticket_created" not in AuditLog.Action.values


def test_writes_customer_activity_when_org_present(organization, owner_user):
    before = CustomerActivity.objects.filter(organization=organization).count()
    log_crm_action(
        actor=owner_user,
        organization=organization,
        action_type="customer_viewed",
        resource_type="organization",
        resource_id=organization.id,
    )
    after = CustomerActivity.objects.filter(organization=organization).count()
    assert after == before + 1
    activity = CustomerActivity.objects.filter(organization=organization).latest(
        "created_at"
    )
    assert activity.activity_type == CustomerActivity.ActivityType.CRM_AUDIT_LOGGED


def test_no_platform_audit_log_model_exists():
    # The CRM-1A decision forbids a separate PlatformAuditLog. Guard against it.
    from django.apps import apps as django_apps

    model_names = {m.__name__ for m in django_apps.get_models()}
    assert "PlatformAuditLog" not in model_names


def test_record_activity_can_be_suppressed(organization, owner_user):
    before = CustomerActivity.objects.filter(organization=organization).count()
    log_crm_action(
        actor=owner_user,
        organization=organization,
        action_type="ticket_created",
        resource_type="support_ticket",
        resource_id="t9",
        record_activity=False,
    )
    after = CustomerActivity.objects.filter(organization=organization).count()
    assert after == before  # suppressed
