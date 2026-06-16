"""Role-setup idempotency tests (CRM-1B)."""

import pytest
from django.contrib.auth.models import Group

from apps.platform_admin import permissions as perms
from apps.platform_admin.services.crm_roles import ensure_platform_crm_groups

pytestmark = pytest.mark.django_db


def test_ensure_creates_all_groups():
    report = ensure_platform_crm_groups()
    assert set(report["created"]) == set(perms.ALL_CRM_GROUPS)
    assert report["existing"] == []
    assert report["assignments"] == 0
    for name in perms.ALL_CRM_GROUPS:
        assert Group.objects.filter(name=name).exists()


def test_ensure_is_idempotent():
    ensure_platform_crm_groups()
    second = ensure_platform_crm_groups()
    # Second run creates nothing and reports all as existing.
    assert second["created"] == []
    assert set(second["existing"]) == set(perms.ALL_CRM_GROUPS)
    # No duplicate groups.
    assert Group.objects.filter(name__in=perms.ALL_CRM_GROUPS).count() == len(
        perms.ALL_CRM_GROUPS
    )


def test_ensure_does_not_assign_users(django_user_model):
    user = django_user_model.objects.create_user(
        email="x@test", password="x", full_name="x", is_staff=True
    )
    ensure_platform_crm_groups()
    user.refresh_from_db()
    # Setup never assigns membership.
    assert user.groups.count() == 0


def test_management_command_runs_idempotently():
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("setup_platform_crm_roles", stdout=out)
    first = out.getvalue()
    assert "Created group" in first
    assert "No user assignments performed." in first

    out2 = StringIO()
    call_command("setup_platform_crm_roles", stdout=out2)
    second = out2.getvalue()
    assert "Existing group" in second
    assert Group.objects.filter(name__in=perms.ALL_CRM_GROUPS).count() == len(
        perms.ALL_CRM_GROUPS
    )
