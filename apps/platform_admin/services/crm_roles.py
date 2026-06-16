"""
Idempotent CRM role (Django Group) setup (CRM-1B).

Creates the five CRM groups if missing. Never deletes groups, never changes
existing group permissions destructively, and never assigns users.
"""

import logging

from apps.platform_admin.permissions import ALL_CRM_GROUPS

logger = logging.getLogger("finai")


def ensure_platform_crm_groups() -> dict:
    """
    Ensure the CRM groups exist (idempotent).

    Returns a report dict::

        {"created": [...], "existing": [...], "assignments": 0}

    ``assignments`` is always 0 — this helper never touches user membership.
    """
    from django.contrib.auth.models import Group

    created, existing = [], []
    for name in ALL_CRM_GROUPS:
        _group, was_created = Group.objects.get_or_create(name=name)
        (created if was_created else existing).append(name)

    return {"created": created, "existing": existing, "assignments": 0}
