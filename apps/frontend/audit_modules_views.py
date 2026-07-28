"""Audit module pages — Trial Balance / General Ledger / SAD / Readiness
(TADGEEG-FIN-AUDIT-8B / 8C / 8D / 8G).

Engagement-scoped, auditor-only frontend that SURFACES services already built in
phases 1A–5D. No new backend logic:

  * 8B Trial Balance  → ``trial_balance_import.parse_and_validate`` (1A/1B)
  * 8C General Ledger → ``general_ledger_import.parse_and_validate`` +
                        ``general_ledger_risk_analysis.analyze_import`` (2A/2B) +
                        ``gl_finding_review.review_finding`` (3B)
  * 8D SAD            → ``audit_difference_summary.recalculate_for_engagement`` (4A)
  * 8G Readiness      → ``audit_readiness_workpaper.generate_for_engagement`` (5A) +
                        ``audit_readiness_export`` links (5D)

Advisory only — no ledger writes, no automatic opinion.
"""
from __future__ import annotations

import os

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.audit.audit_difference_models import AuditDifferenceItem, AuditDifferenceSummary
from apps.audit.engagement_models import AuditEngagement
from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.audit.trial_balance_models import AccountMapping, TrialBalanceImport, TrialBalanceRow
from apps.frontend.page_views import _ctx

_EXT_TO_FORMAT = {"csv": "csv", "xlsx": "xlsx", "xls": "xls"}
_FS = GeneralLedgerRiskFinding.Status


def _org(request):
    return getattr(request.user, "organization", None)


def _guard(request):
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _engagement(request):
    """Resolve ?engagement=<id> within the user's org (or None)."""
    org = _org(request)
    eid = request.GET.get("engagement") or request.POST.get("engagement")
    if not eid or org is None:
        return None
    return AuditEngagement.objects.filter(pk=eid, organization=org).first()


def _engagements(org):
    return list(AuditEngagement.objects.filter(organization=org)[:200]) if org else []


def _ext_format(filename):
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return _EXT_TO_FORMAT.get(ext)


# ─────────────────────────────────────────────────────────────────────────────
# 8B — Trial Balance Analyzer
# ─────────────────────────────────────────────────────────────────────────────
def _tb_anomalies(rows):
    """Deterministic 'unusual account' flags (advisory)."""
    flags = []
    for r in rows:
        # A balance sign inconsistent with the account type is worth a look.
        bal = r.closing_balance
        atype = (r.account_type or "").lower()
        if atype in ("asset", "expense") and bal < 0:
            flags.append((r, f"{atype} account with a credit (negative) closing balance"))
        elif atype in ("liability", "equity", "revenue", "income") and bal > 0:
            flags.append((r, f"{atype} account with a debit (positive) closing balance"))
        elif not r.account_type:
            flags.append((r, "account has no type/classification"))
    return flags[:100]


@login_required(login_url="/login/")
def trial_balance(request):
    """Upload/list TB imports, view rows, mappings and unusual accounts."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        upload = request.FILES.get("uploaded_file")
        if upload is None:
            error = "Choose a CSV/XLSX file to upload."
        else:
            fmt = _ext_format(upload.name)
            if not fmt:
                error = "Unsupported file type. Allowed: csv, xlsx, xls."
            else:
                try:
                    from apps.audit.services import trial_balance_import as tb
                    imp = TrialBalanceImport.objects.create(
                        engagement=engagement, organization=org,
                        uploaded_file=upload, original_filename=upload.name,
                        source_format=fmt, created_by=request.user)
                    tb.parse_and_validate(imp)
                    notice = f"Imported and validated {imp.original_filename}."
                except Exception as exc:
                    error = str(exc)

    imports, detail, rows, mappings, anomalies = [], None, [], [], []
    if engagement is not None:
        imports = list(TrialBalanceImport.objects.filter(engagement=engagement)
                       .order_by("-created_at")[:50])
        detail_id = request.GET.get("import")
        detail = next((i for i in imports if str(i.id) == detail_id),
                      imports[0] if imports else None)
        if detail is not None:
            rows = list(detail.rows.all()[:500])
            mappings = list(AccountMapping.objects.filter(engagement=engagement)[:500])
            anomalies = _tb_anomalies(rows)

    return render(request, "audit/modules/trial_balance.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        imports=imports, detail=detail, rows=rows, mappings=mappings,
        anomalies=anomalies, error=error, notice=notice,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# 8C — General Ledger Review
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url="/login/")
def general_ledger(request):
    """Upload/list GL imports, run 2B risk analysis, review 3B findings."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        try:
            if action == "upload":
                upload = request.FILES.get("uploaded_file")
                fmt = _ext_format(getattr(upload, "name", ""))
                if upload is None or not fmt:
                    error = "Choose a CSV/XLSX general-ledger file."
                else:
                    from apps.audit.services import general_ledger_import as gl
                    imp = GeneralLedgerImport.objects.create(
                        engagement=engagement, organization=org,
                        uploaded_file=upload, original_filename=upload.name,
                        source_format=fmt, created_by=request.user)
                    gl.parse_and_validate(imp)
                    notice = f"Imported {imp.original_filename}."
            elif action == "analyze":
                from apps.audit.services import general_ledger_risk_analysis as gla
                imp = GeneralLedgerImport.objects.filter(
                    pk=request.POST.get("import"), organization=org,
                    engagement=engagement).first()
                if imp is None:
                    error = "Import not found."
                else:
                    result = gla.analyze_import(imp, created_by=request.user)
                    notice = f"Risk analysis complete — {result.get('created', 0)} finding(s)."
            elif action == "review":
                from apps.audit.services import gl_finding_review as review
                finding = GeneralLedgerRiskFinding.objects.filter(
                    pk=request.POST.get("finding"), organization=org,
                    engagement=engagement).first()
                if finding is None:
                    error = "Finding not found."
                else:
                    review.review_finding(
                        finding, actor=request.user,
                        to_status=request.POST.get("to_status", ""),
                        review_reason=request.POST.get("reason", "") or "other",
                        reviewer_note=request.POST.get("note", ""))
                    notice = "Finding reviewed."
            else:
                error = "Unknown action."
        except Exception as exc:
            error = str(exc)

    imports, findings = [], []
    counts = {}
    if engagement is not None:
        imports = list(GeneralLedgerImport.objects.filter(engagement=engagement)
                       .order_by("-created_at")[:50])
        fqs = GeneralLedgerRiskFinding.objects.filter(engagement=engagement)
        status_filter = request.GET.get("status")
        if status_filter:
            fqs = fqs.filter(status=status_filter)
        findings = list(fqs.order_by("-score")[:300])
        from django.db.models import Count
        for r in (GeneralLedgerRiskFinding.objects.filter(engagement=engagement)
                  .values("status").annotate(n=Count("id"))):
            counts[r["status"]] = r["n"]

    return render(request, "audit/modules/general_ledger.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        imports=imports, findings=findings, counts=counts,
        status_choices=_FS.choices, active_status=request.GET.get("status", ""),
        review_statuses=[_FS.ACCEPTED, _FS.DISMISSED, _FS.NEEDS_EVIDENCE, _FS.ESCALATED],
        error=error, notice=notice,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# 8D — Summary of Audit Differences dashboard
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url="/login/")
def sad_dashboard(request):
    """Show/recalculate the engagement's Summary of Audit Differences."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None and \
            request.POST.get("action") == "recalculate":
        try:
            from apps.audit.services import audit_difference_summary as sad
            sad.recalculate_for_engagement(engagement, actor=request.user)
            notice = "SAD recalculated from accepted GL findings."
        except Exception as exc:
            error = str(exc)

    summary, items = None, []
    if engagement is not None:
        summary = (AuditDifferenceSummary.objects.filter(engagement=engagement)
                   .order_by("-created_at").first())
        if summary is not None:
            items = list(summary.items.select_related("gl_finding")
                         .order_by("-amount_impact")[:300])

    return render(request, "audit/modules/sad.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        summary=summary, items=items, error=error, notice=notice,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# 8G — Audit Readiness generate & export
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url="/login/")
def readiness_generate(request):
    """Generate the readiness workpaper (5A) and expose export links (5D)."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    error = notice = None

    if request.method == "POST" and engagement is not None and \
            request.POST.get("action") == "generate":
        try:
            from apps.audit.services import audit_readiness_workpaper as rw
            wp = rw.generate_for_engagement(engagement, actor=request.user)
            # G0 — record report/workpaper issuance in the tamper-evident trail.
            from apps.audit.services import audit_trail
            audit_trail.record_report_issued(
                engagement=engagement, actor=request.user,
                report_kind="readiness_workpaper",
                reference=str(getattr(wp, "id", "") or ""), request=request)
            notice = "Readiness workpaper generated (subject to auditor review)."
        except Exception as exc:
            error = str(exc)

    workpaper = None
    if engagement is not None:
        workpaper = (engagement.readiness_workpapers.order_by("-created_at").first())

    return render(request, "audit/modules/readiness_generate.html", _ctx(
        request, "audit",
        engagement=engagement, engagements=_engagements(org),
        workpaper=workpaper, error=error, notice=notice,
    ))
