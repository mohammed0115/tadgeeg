"""Bind the authenticated request tenant to legacy AI adapters."""
from __future__ import annotations

from core.services.ai_budget import org_context


class AIOrganizationContextMiddleware:
    """Expose request.user.organization_id for the duration of one HTTP request.

    New callers pass ``organization`` to the gateway directly.  This middleware
    is the safe migration bridge for older service signatures. Background tasks
    remain responsible for their explicit ``org_context`` blocks.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        org_id = getattr(user, "organization_id", None)
        with org_context(org_id):
            return self.get_response(request)
