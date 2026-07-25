"""Financial Statements review — frontend page (TADGEEG-FIN-AUDIT-9A · IAS 1).

Auditor-only, engagement-scoped page that renders the Balance Sheet / Income
Statement derived from the trial balance (1A/1B) via the 9A service, with key
ratios, a year-over-year comparison and classification-anomaly flags.

Advisory only: derived on the fly, nothing persisted, no ledger writes.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.audit.services import financial_statements as fs
from apps.frontend.page_views import _ctx


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


@login_required(login_url="/login/")
def financial_statements(request):
    """Render the derived IAS 1 statements for the selected engagement."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    eid = request.GET.get("engagement")
    engagement = (AuditEngagement.objects.filter(pk=eid, organization=org).first()
                  if eid and org else None)

    data = error = None
    if engagement is not None:
        try:
            data = fs.build_financial_statements(engagement)
        except fs.FinancialStatementError as exc:
            error = str(exc)

    return render(request, "audit/financial_statements/review.html", _ctx(
        request, "audit",
        engagement=engagement,
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        data=data, error=error,
    ))
