"""Notification HTTP API.

Endpoints (mounted at /api/v1/notifications/):
  GET    /                  — list recent notifications (latest 50)
  GET    /unread-count/     — unread count + recent N
  POST   /<id>/read/        — mark one as read
  POST   /mark-all-read/    — mark all as read
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from .models import Notification
from .services import get_unread_count, mark_all_read


def _serialize(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "severity": n.severity,
        "category": n.category,
        "title": n.title,
        "message": n.message,
        "link": n.link,
        "source_type": n.source_type,
        "source_id": n.source_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@require_GET
@login_required
def list_notifications(request):
    """Return up to 50 most recent notifications for the user."""
    qs = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
    return JsonResponse({
        "results": [_serialize(n) for n in qs],
        "unread_count": get_unread_count(request.user),
    })


@require_GET
@login_required
def unread_count(request):
    """Lightweight endpoint for the topbar bell badge — fewer fields."""
    qs = Notification.objects.filter(user=request.user).order_by("-created_at")[:8]
    return JsonResponse({
        "unread_count": get_unread_count(request.user),
        "recent": [_serialize(n) for n in qs],
    })


@require_POST
@login_required
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.mark_read()
    return JsonResponse({"success": True, "id": str(n.id)})


@require_POST
@login_required
def mark_all_read_view(request):
    n = mark_all_read(request.user)
    return JsonResponse({"success": True, "marked": n})
