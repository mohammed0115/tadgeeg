"""External Confirmations — frontend (TADGEEG-FIN-AUDIT-9C · ISA 505).

Auditor page: create confirmation requests for an engagement, send them, record
the party's reply, reconcile (matched / discrepancy), and copy the secure
response link. Plus a PUBLIC, token-gated response page for the external party
(no account required) — anonymous access is intentional and is not subscription
gated (the billing middleware only checks authenticated users).

Advisory only: a discrepancy is flagged, never auto-posted; no ledger writes.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.audit.confirmation_models import AuditConfirmationRequest
from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import confirmation_request as cs
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.frontend.page_views import _ctx

_C = AuditConfirmationRequest


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _engagement(request):
    org = _org(request)
    eid = request.GET.get("engagement") or request.POST.get("engagement")
    if not eid or org is None:
        return None
    return AuditEngagement.objects.filter(pk=eid, organization=org).first()


@login_required(login_url="/login/")
def confirmations(request):
    """Auditor confirmation register + create + per-request actions."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        try:
            if action == "create":
                cs.create_confirmation(
                    engagement=engagement, actor=request.user,
                    party_name=request.POST.get("party_name", ""),
                    recorded_amount=request.POST.get("recorded_amount", "0"),
                    confirmation_type=request.POST.get("confirmation_type", "receivable"),
                    currency=request.POST.get("currency", "SAR"),
                    party_reference=request.POST.get("party_reference", ""),
                    party_email=request.POST.get("party_email", ""),
                    tolerance=request.POST.get("tolerance", "0") or "0")
                notice = "Confirmation request created."
            elif action in ("send", "reconcile", "no_reply", "cancel", "record"):
                req = AuditConfirmationRequest.objects.filter(
                    pk=request.POST.get("confirmation"), organization=org,
                    engagement=engagement).first()
                if req is None:
                    error = "Confirmation not found."
                elif action == "send":
                    cs.send(request=req, actor=request.user); notice = "Sent."
                elif action == "record":
                    cs.record_response(request=req, actor=request.user,
                                       confirmed_amount=request.POST.get("confirmed_amount", "0"),
                                       note=request.POST.get("note", ""))
                    notice = "Response recorded."
                elif action == "reconcile":
                    cs.reconcile(request=req, actor=request.user); notice = "Reconciled."
                elif action == "no_reply":
                    cs.mark_no_reply(request=req, actor=request.user); notice = "Marked no-reply."
                elif action == "cancel":
                    cs.cancel(request=req, actor=request.user); notice = "Cancelled."
            else:
                error = "Unknown action."
        except cs.ConfirmationError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)

    requests, counts = [], {}
    if engagement is not None:
        requests = list(AuditConfirmationRequest.objects.filter(engagement=engagement)
                        .select_related("requested_by").order_by("-created_at")[:200])
        counts = cs.status_counts(organization=org, engagement=engagement)

    return render(request, "audit/confirmations/list.html", _ctx(
        request, "audit",
        engagement=engagement,
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        requests=requests, counts=counts,
        type_choices=_C.ConfirmationType.choices,
        error=error, notice=notice,
    ))


def confirmation_respond(request, token):
    """PUBLIC token-gated response page for the external party (no login)."""
    req = AuditConfirmationRequest.objects.filter(response_token=token).first()
    if req is None:
        return render(request, "audit/confirmations/respond.html",
                      {"not_found": True}, status=404)

    done = error = None
    if request.method == "POST" and req.status == _C.Status.SENT:
        agree = request.POST.get("agree") == "1"
        amount = req.recorded_amount if agree else request.POST.get("confirmed_amount", "")
        try:
            cs.record_response(request=req, confirmed_amount=amount,
                               note=request.POST.get("note", ""))
            done = True
        except cs.ConfirmationError as exc:
            error = str(exc)
        req.refresh_from_db()

    return render(request, "audit/confirmations/respond.html", {
        "req": req,
        "already": req.status != _C.Status.SENT and not done,
        "done": done,
        "error": error,
    })
