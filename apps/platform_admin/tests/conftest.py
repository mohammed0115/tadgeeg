"""Shared fixtures for Platform CRM tests (CRM-1B)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.authentication.models import Organization
from apps.platform_admin import permissions as perms
from apps.platform_admin.services.crm_roles import ensure_platform_crm_groups


@pytest.fixture
def organization(db):
    return Organization.objects.create(
        name="Acme Audit Co",
        name_ar="شركة أكمي",
        country=Organization.Country.SAUDI_ARABIA,
        currency=Organization.Currency.SAR,
    )


@pytest.fixture
def crm_groups(db):
    """Ensure CRM groups exist before building role users."""
    ensure_platform_crm_groups()
    return perms.ALL_CRM_GROUPS


def _make_user(email, *, is_staff=True, is_superuser=False, groups=()):
    User = get_user_model()
    user = User.objects.create_user(
        email=email,
        password="TestPass123!",
        full_name=email.split("@")[0],
        is_staff=is_staff,
    )
    if is_superuser:
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
    return user


@pytest.fixture
def owner_user(crm_groups):
    return _make_user("owner@platform.test", groups=[perms.GROUP_PLATFORM_OWNER])


@pytest.fixture
def admin_user(crm_groups):
    return _make_user("padmin@platform.test", groups=[perms.GROUP_PLATFORM_ADMIN])


@pytest.fixture
def support_user(crm_groups):
    return _make_user("support@platform.test", groups=[perms.GROUP_SUPPORT_AGENT])


@pytest.fixture
def finance_user(crm_groups):
    return _make_user("finance@platform.test", groups=[perms.GROUP_FINANCE_OFFICER])


@pytest.fixture
def readonly_user(crm_groups):
    return _make_user("readonly@platform.test", groups=[perms.GROUP_READONLY_AUDITOR])


@pytest.fixture
def staff_no_group(db):
    """Authenticated staff member with NO CRM group."""
    return _make_user("nogroup@platform.test", is_staff=True)


@pytest.fixture
def superuser(db):
    return _make_user("root@platform.test", is_staff=True, is_superuser=True)


@pytest.fixture
def regular_user(db):
    """Non-staff customer user — must never reach CRM."""
    return _make_user("customer@tenant.test", is_staff=False)
