"""Evidence Assurance — frontend pages (TADGEEG-FIN-AUDIT-6D).

Auditor-only, organization-scoped, server-rendered pages that surface every 6D
backend capability: the assurance overview, the integrity exception report (with
an on-demand sweep), the coverage report, the immutable evidence index, and the
engagement retention policy.

Reporting only: no page here deletes, repairs, or purges evidence, and none of
them change a readiness conclusion.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.audit.engagement_models import AuditEngagement
from apps.audit.evidence_models import AuditEvidenceRetentionPolicy
from apps.audit.services import evidence_assurance as assurance
from apps.audit.services import evidence_lifecycle as lc
from apps.frontend.page_views import _ctx

_P = AuditEvidenceRetentionPolicy


def _org(request):
    return getattr(request.user, "organization", None)


def _engagements(org):
    return list(AuditEngagement.objects.filter(organization=org)[:200]) if org else []


def _selected_engagement(request, org):
    eid = request.GET.get("engagement") or request.POST.get("engagement")
    if not eid or org is None:
        return None
    return AuditEngagement.objects.filter(pk=eid, organization=org).first()


def _guard(request):
    """Auditor-only. Returns a 403 response, or None when allowed."""
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


@login_required(login_url="/login/")
def assurance_overview(request):
    """Assurance landing page: dashboard widgets + links to each report."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    dashboard = assurance.assurance_dashboard(
        organization=org, engagement=engagement) if org else {}
    return render(request, "audit/assurance/overview.html", _ctx(
        request, "audit",
        dashboard=dashboard,
        engagements=_engagements(org),
        selected_engagement=engagement,
    ))


@login_required(login_url="/login/")
def integrity_report(request):
    """Integrity exception report; POST runs an on-demand sweep."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    notice = error = None
    sweep_stats = None

    if request.method == "POST" and request.POST.get("action") == "sweep":
        try:
            sweep_stats = assurance.sweep_attachments(
                organization=org, engagement=engagement, actor=request.user)
            notice = (f"Sweep complete — checked {sweep_stats['checked']}, "
                      f"verified {sweep_stats['ok']}, failed {sweep_stats['failed']}.")
        except Exception as exc:
            error = str(exc)

    report = assurance.integrity_exception_report(
        organization=org, engagement=engagement) if org else {}
    return render(request, "audit/assurance/integrity.html", _ctx(
        request, "audit",
        report=report,
        sweep_stats=sweep_stats,
        engagements=_engagements(org),
        selected_engagement=engagement,
        notice=notice,
        error=error,
    ))


@login_required(login_url="/login/")
def coverage_report(request):
    """Evidence coverage per GL finding and SAD item."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    coverage = assurance.evidence_coverage(
        organization=org, engagement=engagement) if org else {}
    return render(request, "audit/assurance/coverage.html", _ctx(
        request, "audit",
        coverage=coverage,
        engagements=_engagements(org),
        selected_engagement=engagement,
    ))


@login_required(login_url="/login/")
def evidence_index_page(request):
    """The immutable evidence index (no download URLs by design)."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    index = assurance.evidence_index(
        organization=org, engagement=engagement) if org else []
    return render(request, "audit/assurance/index.html", _ctx(
        request, "audit",
        index=index,
        engagements=_engagements(org),
        selected_engagement=engagement,
    ))


@login_required(login_url="/login/")
def retention_policy_page(request):
    """View/set/apply the engagement-level retention policy (metadata only)."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _selected_engagement(request, org)
    notice = error = None

    if request.method == "POST" and engagement is not None:
        try:
            policy = assurance.set_retention_policy(
                engagement=engagement, actor=request.user,
                policy=request.POST.get("policy", _P.Policy.YEARS_7),
                custom_years=request.POST.get("custom_years") or None,
                reason=request.POST.get("reason", ""))
            notice = "Retention policy saved."
            if request.POST.get("apply"):
                result = assurance.apply_retention_policy(
                    policy_obj=policy, actor=request.user)
                notice = (f"Policy applied to {result['marked']} attachment(s) "
                          f"(metadata only; {result['skipped_frozen']} frozen skipped).")
        except Exception as exc:
            error = str(exc)
    elif request.method == "POST":
        error = "Choose an engagement first."

    policies = list(AuditEvidenceRetentionPolicy.objects.filter(
        organization=org).select_related("engagement")) if org else []
    current = next((p for p in policies if engagement and p.engagement_id == engagement.id), None)

    return render(request, "audit/assurance/retention.html", _ctx(
        request, "audit",
        policies=policies,
        current=current,
        policy_choices=_P.Policy.choices,
        engagements=_engagements(org),
        selected_engagement=engagement,
        notice=notice,
        error=error,
    ))
