"""CRM-1E — Support Ticketing operations (services, forms, views, security)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.authentication.models import AuditLog
from apps.platform_admin import forms as crm_forms
from apps.platform_admin.models import (
    CustomerActivity,
    SupportTicket,
    TicketMessage,
)
from apps.platform_admin.services import crm_operations as ops

pytestmark = pytest.mark.django_db


def _make_ticket(organization, actor, **kw):
    return ops.create_support_ticket(
        actor=actor, organization=organization,
        title=kw.pop("title", "T"), description=kw.pop("description", "d"), **kw
    )


# ══ Service tests ═════════════════════════════════════════════════════════════
def test_create_support_ticket_writes_audit_and_activity(organization, support_user):
    ticket = _make_ticket(organization, support_user,
                          category=SupportTicket.Category.BILLING,
                          priority=SupportTicket.Priority.HIGH)
    assert ticket.status == SupportTicket.Status.OPEN
    assert ticket.created_by_id == support_user.id
    audit = AuditLog.objects.filter(resource_id=str(ticket.id)).latest("timestamp")
    assert audit.details["action_type"] == "support_ticket_created"
    assert CustomerActivity.objects.filter(
        organization=organization,
        activity_type=CustomerActivity.ActivityType.TICKET_CREATED,
    ).exists()


def test_create_requires_title_and_description(organization, support_user):
    with pytest.raises(ValidationError):
        ops.create_support_ticket(actor=support_user, organization=organization,
                                  title="  ", description="x")
    with pytest.raises(ValidationError):
        ops.create_support_ticket(actor=support_user, organization=organization,
                                  title="x", description="  ")


def test_non_manager_cannot_create(organization, readonly_user, finance_user):
    for actor in (readonly_user, finance_user):
        with pytest.raises(PermissionDenied):
            _make_ticket(organization, actor)


def test_add_ticket_message(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    msg = ops.add_ticket_message(actor=support_user, ticket=ticket,
                                 message="hello", internal_only=True)
    assert TicketMessage.objects.filter(id=msg.id).exists()
    assert msg.internal_only is True
    audit = AuditLog.objects.filter(resource_id=str(msg.id)).latest("timestamp")
    assert audit.details["action_type"] == "ticket_message_added"


def test_add_empty_message_rejected(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    with pytest.raises(ValidationError):
        ops.add_ticket_message(actor=support_user, ticket=ticket, message="   ")


def test_change_status_requires_reason(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    with pytest.raises(ValidationError):
        ops.change_ticket_status(actor=support_user, ticket=ticket,
                                 new_status=SupportTicket.Status.RESOLVED, reason="")


def test_change_status_sets_resolved_at_and_audits(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    ops.change_ticket_status(actor=support_user, ticket=ticket,
                             new_status=SupportTicket.Status.RESOLVED, reason="fixed")
    ticket.refresh_from_db()
    assert ticket.status == SupportTicket.Status.RESOLVED
    assert ticket.resolved_at is not None
    audit = AuditLog.objects.filter(
        resource_id=str(ticket.id), details__action_type="ticket_status_changed"
    ).latest("timestamp")
    assert audit.details["old_value"] == SupportTicket.Status.OPEN
    assert audit.details["new_value"] == SupportTicket.Status.RESOLVED
    assert audit.details["reason"] == "fixed"


def test_invalid_transition_rejected(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    ops.change_ticket_status(actor=support_user, ticket=ticket,
                             new_status=SupportTicket.Status.RESOLVED, reason="r")
    ticket.refresh_from_db()
    # resolved → pending_customer is not allowed
    with pytest.raises(ValidationError):
        ops.change_ticket_status(actor=support_user, ticket=ticket,
                                 new_status=SupportTicket.Status.PENDING_CUSTOMER,
                                 reason="r")


def test_reopen_clears_resolved_at(organization, support_user):
    ticket = _make_ticket(organization, support_user)
    ops.change_ticket_status(actor=support_user, ticket=ticket,
                             new_status=SupportTicket.Status.RESOLVED, reason="r")
    ops.change_ticket_status(actor=support_user, ticket=ticket,
                             new_status=SupportTicket.Status.OPEN, reason="reopen")
    ticket.refresh_from_db()
    assert ticket.status == SupportTicket.Status.OPEN
    assert ticket.resolved_at is None


def test_assign_ticket_to_staff_and_audit(organization, support_user, finance_user):
    ticket = _make_ticket(organization, support_user)
    ops.assign_ticket(actor=support_user, ticket=ticket,
                      assigned_to=finance_user, reason="balance")
    ticket.refresh_from_db()
    assert ticket.assigned_to_id == finance_user.id
    audit = AuditLog.objects.filter(
        resource_id=str(ticket.id), details__action_type="ticket_assigned"
    ).latest("timestamp")
    assert audit.details["new_value"] == finance_user.email
    # CustomerActivity is written with the literal "ticket_assigned" type, and
    # its display renders without error (no enum member → raw value; documented
    # technical debt deferred to a future migration-bearing phase).
    activity = CustomerActivity.objects.filter(organization=organization).latest(
        "created_at"
    )
    assert activity.activity_type == "ticket_assigned"
    assert activity.get_activity_type_display() == "ticket_assigned"


def test_assign_to_non_crm_user_rejected(organization, support_user, regular_user):
    ticket = _make_ticket(organization, support_user)
    with pytest.raises(ValidationError):
        ops.assign_ticket(actor=support_user, ticket=ticket,
                          assigned_to=regular_user, reason="x")


def test_assign_none_unassigns(organization, support_user):
    ticket = _make_ticket(organization, support_user, assigned_to=support_user)
    ops.assign_ticket(actor=support_user, ticket=ticket, assigned_to=None, reason="x")
    ticket.refresh_from_db()
    assert ticket.assigned_to_id is None


def test_non_manager_cannot_change_status(organization, support_user, readonly_user):
    ticket = _make_ticket(organization, support_user)
    with pytest.raises(PermissionDenied):
        ops.change_ticket_status(actor=readonly_user, ticket=ticket,
                                 new_status=SupportTicket.Status.CLOSED, reason="x")


# ══ Form tests ════════════════════════════════════════════════════════════════
def test_create_form_requires_title(organization):
    form = crm_forms.CreateSupportTicketForm(
        data={"organization": organization.id, "title": "  ",
              "category": "general", "priority": "medium", "description": "d"}
    )
    assert not form.is_valid()
    assert "title" in form.errors


def test_create_form_assigned_to_must_be_crm_staff(organization):
    User = get_user_model()
    outsider = User.objects.create_user(email="out@t.test", password="x",
                                        full_name="o", organization=organization)
    form = crm_forms.CreateSupportTicketForm(
        data={"organization": organization.id, "title": "t", "category": "general",
              "priority": "medium", "description": "d", "assigned_to": outsider.id}
    )
    assert not form.is_valid()
    assert "assigned_to" in form.errors


def test_message_form_requires_text():
    assert not crm_forms.TicketMessageForm(data={"message": "  "}).is_valid()
    assert crm_forms.TicketMessageForm(data={"message": "hi"}).is_valid()


def test_status_form_requires_reason():
    f = crm_forms.TicketStatusUpdateForm(data={"status": "resolved", "reason": " "})
    assert not f.is_valid()
    assert "reason" in f.errors


# ══ View access + operation tests ═════════════════════════════════════════════
def test_create_ticket_get_access(client, owner_user, support_user, finance_user,
                                   readonly_user, staff_no_group, regular_user):
    url = reverse("platform_admin:crm:ticket_create")
    # managers: 200
    for u in (owner_user, support_user):
        client.force_login(u)
        assert client.get(url).status_code == 200
    # non-managers: 403
    for u in (finance_user, readonly_user, staff_no_group, regular_user):
        client.force_login(u)
        assert client.get(url).status_code == 403
    # anonymous: redirect
    client.logout()
    assert client.get(url).status_code == 302


def test_create_ticket_post_creates_and_redirects(client, support_user, organization):
    client.force_login(support_user)
    resp = client.post(reverse("platform_admin:crm:ticket_create"), {
        "organization": str(organization.id), "title": "New issue",
        "category": "technical", "priority": "high", "description": "desc",
    })
    assert resp.status_code == 302
    ticket = SupportTicket.objects.get(title="New issue")
    assert resp["Location"].endswith(f"/{ticket.id}/")


def test_post_message_creates_and_redirects(client, support_user, organization):
    client.force_login(support_user)
    ticket = _make_ticket(organization, support_user)
    resp = client.post(
        reverse("platform_admin:crm:ticket_message", args=[ticket.id]),
        {"message": "looking into it", "internal_only": "on"},
    )
    assert resp.status_code == 302
    assert TicketMessage.objects.filter(ticket=ticket, internal_only=True).exists()


def test_post_status_changes_and_redirects(client, support_user, organization):
    client.force_login(support_user)
    ticket = _make_ticket(organization, support_user)
    resp = client.post(
        reverse("platform_admin:crm:ticket_status", args=[ticket.id]),
        {"status": "resolved", "reason": "done"},
    )
    assert resp.status_code == 302
    ticket.refresh_from_db()
    assert ticket.status == SupportTicket.Status.RESOLVED


def test_post_assign_changes_and_redirects(client, support_user, owner_user, organization):
    client.force_login(support_user)
    ticket = _make_ticket(organization, support_user)
    resp = client.post(
        reverse("platform_admin:crm:ticket_assign", args=[ticket.id]),
        {"assigned_to": str(owner_user.id), "reason": "escalate"},
    )
    assert resp.status_code == 302
    ticket.refresh_from_db()
    assert ticket.assigned_to_id == owner_user.id


def test_readonly_cannot_post_create(client, readonly_user, organization):
    client.force_login(readonly_user)
    resp = client.post(reverse("platform_admin:crm:ticket_create"), {
        "organization": str(organization.id), "title": "x", "category": "general",
        "priority": "medium", "description": "d",
    })
    assert resp.status_code == 403
    assert not SupportTicket.objects.filter(title="x").exists()


def test_finance_cannot_post_status(client, finance_user, support_user, organization):
    ticket = _make_ticket(organization, support_user)
    client.force_login(finance_user)
    resp = client.post(
        reverse("platform_admin:crm:ticket_status", args=[ticket.id]),
        {"status": "closed", "reason": "x"},
    )
    assert resp.status_code == 403
    ticket.refresh_from_db()
    assert ticket.status == SupportTicket.Status.OPEN


def test_write_routes_reject_get(client, support_user, organization):
    client.force_login(support_user)
    ticket = _make_ticket(organization, support_user)
    for name in ("ticket_message", "ticket_status", "ticket_assign"):
        url = reverse(f"platform_admin:crm:{name}", args=[ticket.id])
        assert client.get(url).status_code == 405  # POST-only, no GET mutation


def test_post_to_missing_ticket_404(client, support_user):
    client.force_login(support_user)
    url = reverse("platform_admin:crm:ticket_status", args=[uuid.uuid4()])
    assert client.post(url, {"status": "open", "reason": "x"}).status_code == 404


# ══ UI smoke ══════════════════════════════════════════════════════════════════
def test_new_ticket_button_only_for_managers(client, support_user, readonly_user):
    new_url = reverse("platform_admin:crm:ticket_create")
    client.force_login(support_user)
    assert new_url in client.get(reverse("platform_admin:crm:tickets")).content.decode()
    client.force_login(readonly_user)
    assert new_url not in client.get(reverse("platform_admin:crm:tickets")).content.decode()


def test_reply_form_only_for_managers(client, support_user, readonly_user, organization):
    ticket = _make_ticket(organization, support_user)
    detail = reverse("platform_admin:crm:ticket_detail", args=[ticket.id])
    msg_action = reverse("platform_admin:crm:ticket_message", args=[ticket.id])
    client.force_login(support_user)
    assert msg_action in client.get(detail).content.decode()
    # readonly sees the ticket but no write form
    client.force_login(readonly_user)
    body = client.get(detail).content.decode()
    assert client.get(detail).status_code == 200
    assert msg_action not in body


def test_internal_badge_renders(client, support_user, organization):
    ticket = _make_ticket(organization, support_user)
    ops.add_ticket_message(actor=support_user, ticket=ticket,
                           message="secret", internal_only=True)
    client.force_login(support_user)
    body = client.get(
        reverse("platform_admin:crm:ticket_detail", args=[ticket.id])
    ).content.decode()
    assert "secret" in body
