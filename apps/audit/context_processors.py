"""Audit context processor — surfaces the approval-inbox count to every
authenticated request so the sidebar badge stays accurate.

Cheap query — a single ``COUNT`` filtered by org + status. Safe to call
on every request because:

  • Anonymous / no-org users return 0 without hitting the DB.
  • The query is indexed (Invoice.organization_id + Invoice.status).
"""
from __future__ import annotations


def approval_inbox(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"approval_inbox_count": 0}
    org = getattr(user, "organization", None)
    if org is None:
        return {"approval_inbox_count": 0}

    try:
        from apps.invoices.models import Invoice
    except Exception:
        return {"approval_inbox_count": 0}

    try:
        count = Invoice.objects.filter(
            organization=org,
            status__in=("flagged", "pending_approval", "pending"),
        ).count()
    except Exception:
        count = 0
    return {"approval_inbox_count": count}
