"""Audit governance — frontend pages (TADGEEG-G3.2/G3.3/G6/G2.3).

Surfaces the engagement-governance modules that previously existed only as DRF
API endpoints, so the audit workflow is operable end-to-end from the UI:

  * Issues (G3.2)             — issue → remediation → closure loop.
  * Findings register (G2.3)  — read-only, normalized findings across types.
  * Engagement reports (G6)   — versioned ISA 700-safe report + sign-offs (G3).
  * Engagement team (G3.3)    — assign/remove members.

Every page is auditor-only, organization-scoped and engagement-filtered (via the
``?engagement=<id>`` selector used across the audit module pages). Deterministic,
advisory, no ledger writes. This is purely additive — no backend logic changes.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.audit.engagement_models import AuditEngagement
from apps.audit.issue_models import AuditIssue
from apps.audit.member_models import EngagementMember
from apps.audit.report_models import EngagementReport
from apps.audit.signoff_models import EngagementSignoff
from apps.audit.services import audit_issue as ai
from apps.audit.services import engagement_member as em
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.audit.services import findings_register as fr
from apps.audit.services import report_builder as rb
from apps.audit.services import signoff as so
from apps.frontend.page_views import _ctx

_I = AuditIssue
_R = EngagementReport
_M = EngagementMember
_S = EngagementSignoff
_REPORT_ARTIFACT = "engagement_report"


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


def _engagements(org):
    return list(AuditEngagement.objects.filter(organization=org)[:200]) if org else []


# ── Issues (G3.2) ────────────────────────────────────────────────────────────
@login_required(login_url="/login/")
def issues(request):
    """Audit issues with the remediation → closure loop."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        p = request.POST
        try:
            if action == "create_issue":
                obj = ai.create_issue(
                    engagement=engagement, actor=request.user,
                    title=p.get("title", ""), description=p.get("description", ""),
                    severity=p.get("severity") or None, owner=p.get("owner", ""),
                    due_date=p.get("due_date") or None,
                    remediation_plan=p.get("remediation_plan", ""))
                notice = f"Issue {obj.reference} raised."
            elif action == "remediate":
                issue = AuditIssue.objects.filter(
                    pk=p.get("issue"), organization=org, engagement=engagement).first()
                if issue is None:
                    error = "Issue not found."
                else:
                    ai.record_remediation(
                        issue=issue, actor=request.user,
                        remediation_plan=p.get("remediation_plan", ""),
                        owner=p.get("owner", ""), due_date=p.get("due_date") or None)
                    notice = f"Remediation recorded for {issue.reference}."
            elif action == "set_status":
                issue = AuditIssue.objects.filter(
                    pk=p.get("issue"), organization=org, engagement=engagement).first()
                if issue is None:
                    error = "Issue not found."
                else:
                    ai.set_status(issue=issue, actor=request.user,
                                  status=p.get("status", ""), note=p.get("note", ""))
                    notice = f"Issue {issue.reference} updated."
            else:
                error = "Unknown action."
        except ai.AuditIssueError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    rows, summary = [], {}
    if engagement is not None:
        status = request.GET.get("status") or None
        rows = ai.list_issues(engagement=engagement, status=status)
        summary = ai.summary(organization=org, engagement=engagement)

    return render(request, "audit/issues/list.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        rows=rows, summary=summary,
        severity_choices=_I.Severity.choices,
        status_choices=_I.Status.choices,
        active_status=request.GET.get("status", ""),
        error=error, notice=notice,
    ))


# ── Findings register (G2.3) — read-only ─────────────────────────────────────
@login_required(login_url="/login/")
def findings_register(request):
    """Unified, normalized findings list across GL findings + deficiencies."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    source = request.GET.get("source") or None

    rows, summary = [], {}
    if engagement is not None:
        rows = fr.list_findings(organization=org, engagement=engagement, source=source)
        summary = fr.summary(organization=org, engagement=engagement)

    return render(request, "audit/findings_register/list.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        rows=rows, summary=summary, active_source=request.GET.get("source", ""),
    ))


# ── Engagement reports (G6) + sign-offs (G3) ─────────────────────────────────
@login_required(login_url="/login/")
def reports(request):
    """Versioned, ISA 700-safe engagement reports with role sign-offs."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        p = request.POST
        try:
            if action == "create_report":
                obj = rb.create_report(
                    engagement=engagement, actor=request.user, title=p.get("title", ""))
                notice = f"Report {obj.reference} (v{obj.version}) created."
            elif action == "new_version":
                rep = EngagementReport.objects.filter(
                    pk=p.get("report"), organization=org, engagement=engagement).first()
                if rep is None:
                    error = "Report not found."
                else:
                    obj = rb.new_version(report=rep, actor=request.user)
                    notice = f"Report {obj.reference} regenerated as v{obj.version}."
            elif action == "set_status":
                rep = EngagementReport.objects.filter(
                    pk=p.get("report"), organization=org, engagement=engagement).first()
                if rep is None:
                    error = "Report not found."
                else:
                    rb.set_status(report=rep, actor=request.user, status=p.get("status", ""))
                    notice = f"Report {rep.reference} set to {rep.get_status_display()}."
            elif action == "sign":
                rep = EngagementReport.objects.filter(
                    pk=p.get("report"), organization=org, engagement=engagement).first()
                if rep is None:
                    error = "Report not found."
                else:
                    so.sign(engagement=engagement, actor=request.user,
                            artifact_type=_REPORT_ARTIFACT, artifact_id=rep.id,
                            role=p.get("role", ""), note=p.get("note", ""))
                    notice = f"Sign-off recorded on {rep.reference}."
            else:
                error = "Unknown action."
        except (rb.ReportBuilderError, so.SignoffError) as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    report_rows = []
    if engagement is not None:
        for rep in rb.list_reports(engagement=engagement):
            report_rows.append({
                "r": rep,
                "signoffs": so.status_for(
                    engagement=engagement, artifact_type=_REPORT_ARTIFACT,
                    artifact_id=rep.id),
            })

    return render(request, "audit/reports/list.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        report_rows=report_rows,
        status_choices=_R.Status.choices,
        signoff_role_choices=_S.Role.choices,
        error=error, notice=notice,
    ))


# ── Engagement team (G3.3) ───────────────────────────────────────────────────
@login_required(login_url="/login/")
def team(request):
    """Assign / remove engagement team members (ISA 220 roles)."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None
    User = get_user_model()

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        p = request.POST
        try:
            if action == "assign":
                user = User.objects.filter(pk=p.get("user"), organization=org).first()
                if user is None:
                    error = "User not found in your organization."
                else:
                    em.assign(engagement=engagement, actor=request.user, user=user,
                              role=p.get("role") or None,
                              responsibilities=p.get("responsibilities", ""),
                              due_date=p.get("due_date") or None)
                    notice = f"{user.full_name or user.email} assigned."
            elif action == "remove":
                member = EngagementMember.objects.filter(
                    pk=p.get("member"), organization=org, engagement=engagement).first()
                if member is None:
                    error = "Member not found."
                else:
                    em.remove(member=member, actor=request.user)
                    notice = "Member removed."
            else:
                error = "Unknown action."
        except em.EngagementMemberError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    members, summary, org_users = [], {}, []
    if engagement is not None:
        members = em.list_members(engagement=engagement)
        summary = em.summary(organization=org, engagement=engagement)
        assigned_ids = {m.user_id for m in members}
        org_users = [u for u in User.objects.filter(
            organization=org, is_active=True).order_by("email")[:500]
            if u.pk not in assigned_ids]

    return render(request, "audit/team/list.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        members=members, summary=summary, org_users=org_users,
        role_choices=_M.Role.choices,
        error=error, notice=notice,
    ))
