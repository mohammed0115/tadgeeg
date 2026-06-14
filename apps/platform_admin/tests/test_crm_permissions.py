"""Permission tests for the Platform CRM access layer (CRM-1B)."""

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.platform_admin import permissions as perms

pytestmark = pytest.mark.django_db


# ── Anonymous / non-staff are always denied ───────────────────────────────────
def test_anonymous_denied_everywhere():
    anon = AnonymousUser()
    # Every public helper must return False and never raise on AnonymousUser.
    assert perms.is_platform_crm_user(anon) is False
    assert perms.can_view_crm(anon) is False
    assert perms.has_crm_role(anon, perms.GROUP_PLATFORM_OWNER) is False
    assert perms.can_manage_tickets(anon) is False
    assert perms.can_add_customer_note(anon) is False
    assert perms.can_view_financial_crm_data(anon) is False
    assert perms.can_manage_financial_crm_data(anon) is False
    assert perms.can_perform_crm_write(anon) is False
    assert perms.is_readonly_crm_user(anon) is False


def test_regular_non_staff_user_is_not_crm_user(regular_user):
    assert regular_user.is_staff is False
    assert perms.is_platform_crm_user(regular_user) is False
    assert perms.can_view_crm(regular_user) is False
    assert perms.can_perform_crm_write(regular_user) is False


def test_staff_without_group_is_not_crm_user(staff_no_group):
    # DECISION: a staff member with no CRM group has NO CRM access at all.
    assert staff_no_group.is_staff is True
    assert perms.is_platform_crm_user(staff_no_group) is False
    assert perms.can_view_crm(staff_no_group) is False
    assert perms.can_perform_crm_write(staff_no_group) is False
    assert perms.is_readonly_crm_user(staff_no_group) is False


# ── Role capabilities ─────────────────────────────────────────────────────────
def test_platform_owner_has_full_access(owner_user):
    assert perms.is_platform_crm_user(owner_user)
    assert perms.can_view_crm(owner_user)
    assert perms.can_manage_tickets(owner_user)
    assert perms.can_add_customer_note(owner_user)
    assert perms.can_view_financial_crm_data(owner_user)
    assert perms.can_manage_financial_crm_data(owner_user)
    assert perms.can_perform_crm_write(owner_user)
    assert perms.is_readonly_crm_user(owner_user) is False


def test_support_agent_manages_tickets_not_finance(support_user):
    assert perms.can_view_crm(support_user)
    assert perms.can_manage_tickets(support_user)
    assert perms.can_add_customer_note(support_user)
    assert perms.can_perform_crm_write(support_user)
    # Support must not touch or even view financial CRM data.
    assert perms.can_view_financial_crm_data(support_user) is False
    assert perms.can_manage_financial_crm_data(support_user) is False


def test_finance_officer_views_financial_data(finance_user):
    assert perms.can_view_crm(finance_user)
    assert perms.can_view_financial_crm_data(finance_user)
    assert perms.can_manage_financial_crm_data(finance_user)
    assert perms.can_add_customer_note(finance_user)
    # Finance does not manage technical tickets in CRM-1B.
    assert perms.can_manage_tickets(finance_user) is False


def test_readonly_auditor_cannot_write(readonly_user):
    assert perms.can_view_crm(readonly_user)
    assert perms.can_view_financial_crm_data(readonly_user)  # read-all
    assert perms.is_readonly_crm_user(readonly_user) is True
    # No write capability of any kind.
    assert perms.can_perform_crm_write(readonly_user) is False
    assert perms.can_manage_tickets(readonly_user) is False
    assert perms.can_add_customer_note(readonly_user) is False
    assert perms.can_manage_financial_crm_data(readonly_user) is False


def test_platform_admin_no_financial_management(admin_user):
    # Platform Admin manages customers/tickets/notes but NOT financial actions
    # until a later decision (CRM-1F).
    assert perms.can_manage_tickets(admin_user)
    assert perms.can_add_customer_note(admin_user)
    assert perms.can_view_financial_crm_data(admin_user)
    assert perms.can_manage_financial_crm_data(admin_user) is False


def test_has_crm_role_is_specific(support_user):
    assert perms.has_crm_role(support_user, perms.GROUP_SUPPORT_AGENT) is True
    assert perms.has_crm_role(support_user, perms.GROUP_FINANCE_OFFICER) is False


# ── Superuser bypass, but is_staff is still mandatory ─────────────────────────
def test_superuser_has_full_access(superuser):
    assert perms.is_platform_crm_user(superuser)
    assert perms.can_manage_financial_crm_data(superuser)
    assert perms.has_crm_role(superuser, perms.GROUP_FINANCE_OFFICER) is True
    # A superuser is never classified read-only.
    assert perms.is_readonly_crm_user(superuser) is False


def test_non_staff_superuser_is_denied(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    u = User.objects.create_user(
        email="nostaff-root@test", password="x", full_name="x", is_staff=False
    )
    u.is_superuser = True
    u.save(update_fields=["is_superuser"])
    # is_staff is a hard precondition — even a superuser is denied without it.
    assert perms.is_platform_crm_user(u) is False
    assert perms.can_view_crm(u) is False


# ── Decorator gate ────────────────────────────────────────────────────────────
def test_crm_permission_required_decorator(owner_user, readonly_user):
    from django.core.exceptions import PermissionDenied

    @perms.crm_permission_required(perms.can_perform_crm_write)
    def view(request):
        return "ok"

    class Req:
        def __init__(self, user):
            self.user = user

    assert view(Req(owner_user)) == "ok"
    with pytest.raises(PermissionDenied):
        view(Req(readonly_user))
