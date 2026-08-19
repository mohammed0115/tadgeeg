"""
Platform CRM permissions layer (CRM-1B).

Access model
------------
Every CRM user must FIRST be an authenticated platform staff member
(``user.is_authenticated and user.is_staff``). On top of that, capabilities are
granted via membership in one of five Django Groups.

Decision (documented): a staff user with NO CRM group is *not* a CRM user — all
helpers return ``False`` for them. The single exception is ``is_superuser``,
which is treated as an implicit Platform Owner (full access). A non-staff
superuser is still denied, because is_staff is a hard precondition for CRM.

These helpers are the single source of truth. Operational views (CRM-1C onward)
must gate on them; the lightweight decorator/mixin below are provided for that
future use. No operational views exist in CRM-1B.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

# ── Group names (also the canonical role identifiers) ─────────────────────────
GROUP_PLATFORM_OWNER = "Platform Owner"
GROUP_PLATFORM_ADMIN = "Platform Admin"
GROUP_SUPPORT_AGENT = "Support Agent"
GROUP_FINANCE_OFFICER = "Finance Officer"
GROUP_READONLY_AUDITOR = "Readonly Auditor"

ALL_CRM_GROUPS = (
    GROUP_PLATFORM_OWNER,
    GROUP_PLATFORM_ADMIN,
    GROUP_SUPPORT_AGENT,
    GROUP_FINANCE_OFFICER,
    GROUP_READONLY_AUDITOR,
)

# ── Capability → role sets ────────────────────────────────────────────────────
# Read access: every CRM role can read.
_ROLE_VIEW = frozenset(ALL_CRM_GROUPS)
# Ticket management: owner, admin, support.
_ROLE_MANAGE_TICKETS = frozenset(
    {GROUP_PLATFORM_OWNER, GROUP_PLATFORM_ADMIN, GROUP_SUPPORT_AGENT}
)
# Adding customer notes: owner, admin, support, finance (each in their lane).
_ROLE_ADD_NOTE = frozenset(
    {GROUP_PLATFORM_OWNER, GROUP_PLATFORM_ADMIN, GROUP_SUPPORT_AGENT, GROUP_FINANCE_OFFICER}
)
# Viewing financial CRM data: owner, admin, finance, and readonly (read-all).
_ROLE_VIEW_FINANCIAL = frozenset(
    {GROUP_PLATFORM_OWNER, GROUP_PLATFORM_ADMIN, GROUP_FINANCE_OFFICER, GROUP_READONLY_AUDITOR}
)
# Managing financial CRM data (future CRM-1F actions): owner, finance only.
# Platform Admin is intentionally excluded until a later decision.
_ROLE_MANAGE_FINANCIAL = frozenset({GROUP_PLATFORM_OWNER, GROUP_FINANCE_OFFICER})
# Global contact identities are platform-level configuration, not tenant billing
# data. Restrict changes to the two platform administration roles.
_ROLE_MANAGE_PLATFORM_CONTACT = frozenset({GROUP_PLATFORM_OWNER, GROUP_PLATFORM_ADMIN})
# Generic write capability (any non-readonly CRM role).
_ROLE_WRITE = frozenset(
    {GROUP_PLATFORM_OWNER, GROUP_PLATFORM_ADMIN, GROUP_SUPPORT_AGENT, GROUP_FINANCE_OFFICER}
)


# ── Internal predicates ───────────────────────────────────────────────────────
def _staff_authenticated(user) -> bool:
    """True only for an authenticated platform staff member."""
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_staff", False)
    )


def _in_any_group(user, names) -> bool:
    """True if a staff user is a superuser or belongs to any of ``names``."""
    if not _staff_authenticated(user):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name__in=list(names)).exists()


# ── Public helpers ────────────────────────────────────────────────────────────
def is_platform_crm_user(user) -> bool:
    """Staff member who belongs to at least one CRM group (or is superuser)."""
    return _in_any_group(user, ALL_CRM_GROUPS)


def has_crm_role(user, role_name: str) -> bool:
    """True if the staff user holds the given CRM group (superuser passes all)."""
    if not _staff_authenticated(user):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name=role_name).exists()


def can_view_crm(user) -> bool:
    return _in_any_group(user, _ROLE_VIEW)


def can_manage_tickets(user) -> bool:
    return _in_any_group(user, _ROLE_MANAGE_TICKETS)


def can_add_customer_note(user) -> bool:
    return _in_any_group(user, _ROLE_ADD_NOTE)


def can_view_financial_crm_data(user) -> bool:
    return _in_any_group(user, _ROLE_VIEW_FINANCIAL)


def can_manage_financial_crm_data(user) -> bool:
    return _in_any_group(user, _ROLE_MANAGE_FINANCIAL)


def can_perform_crm_write(user) -> bool:
    return _in_any_group(user, _ROLE_WRITE)


def can_manage_platform_contact_settings(user) -> bool:
    """May edit global public contact identity such as WhatsApp Business."""
    return _in_any_group(user, _ROLE_MANAGE_PLATFORM_CONTACT)


def is_readonly_crm_user(user) -> bool:
    """
    True if the user is a CRM user whose only effective access is read-only.

    A superuser is never read-only (they have full access). A user holding both
    Readonly Auditor and a write-capable group is treated as a write user.
    """
    if not _staff_authenticated(user):
        return False
    if getattr(user, "is_superuser", False):
        return False
    group_names = set(user.groups.values_list("name", flat=True))
    if GROUP_READONLY_AUDITOR not in group_names:
        return False
    return not (group_names & _ROLE_WRITE)


# ── Lightweight gate for future operational views (CRM-1C+) ───────────────────
def crm_permission_required(check=can_view_crm):
    """
    View decorator factory. ``check`` is one of the helpers above.

    Raises PermissionDenied (403) when the check fails. Not wired to any view in
    CRM-1B — provided so CRM-1C views have a consistent, tested gate to use.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not check(getattr(request, "user", None)):
                raise PermissionDenied("CRM access denied.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class PlatformCRMRequiredMixin:
    """CBV mixin requiring CRM read access. For future operational views."""

    crm_check = staticmethod(can_view_crm)

    def dispatch(self, request, *args, **kwargs):
        if not self.crm_check(getattr(request, "user", None)):
            raise PermissionDenied("CRM access denied.")
        return super().dispatch(request, *args, **kwargs)
