"""Substantive Testing — frontend (TADGEEG-FIN-AUDIT-9D).

Auditor-only, engagement-scoped page covering Inventory (ISA 501), Fixed assets
and Payroll. For each item the auditor enters the recorded (book) value and an
independently-derived tested value — either typed directly or recomputed by the
system (straight-line NBV for assets; gross − deductions for payroll; counted
quantity × unit cost for inventory) — and the system flags a variance outside
tolerance. Deterministic; advisory; no ledger writes.
"""
from __future__ import annotations

from apps.audit.engagement_models import AuditEngagement
from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.audit.services import substantive_testing as st
from apps.audit.substantive_test_models import SubstantiveTestItem
from apps.frontend.page_views import _ctx
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

_I = SubstantiveTestItem
_VALID_AREAS = {a.value for a in _I.Area}


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


def _num(v):
    """Empty string / None → None; else pass through for Decimal coercion."""
    if v in (None, ""):
        return None
    return v


def _build_inputs(area, post):
    """Gather area-specific recompute inputs from the POST body."""
    if area == _I.Area.FIXED_ASSETS and post.get("cost"):
        return {
            "cost": post.get("cost", "0"),
            "salvage": post.get("salvage", "0"),
            "useful_life_years": post.get("useful_life_years", "0"),
            "elapsed_years": post.get("elapsed_years", "0"),
        }
    if area == _I.Area.PAYROLL and post.get("gross"):
        return {"gross": post.get("gross", "0"), "deductions": post.get("deductions", "0")}
    if area == _I.Area.INVENTORY and post.get("unit_cost") and post.get("quantity_counted"):
        return {"quantity": post.get("quantity_counted", "0"),
                "unit_cost": post.get("unit_cost", "0")}
    return {}


@login_required(login_url="/login/")
def substantive_testing(request):
    """Substantive-test register with area tabs + recompute-assisted create."""
    denied = _guard(request)
    if denied:
        return denied
    org = _org(request)
    engagement = _engagement(request)
    area = request.GET.get("area") or request.POST.get("area") or _I.Area.INVENTORY
    if area not in _VALID_AREAS:
        area = _I.Area.INVENTORY
    error = notice = None

    if request.method == "POST" and engagement is not None:
        action = request.POST.get("action", "")
        p = request.POST
        try:
            if action == "create":
                st.create_item(
                    engagement=engagement, actor=request.user, area=area,
                    book_value=p.get("book_value", "0"),
                    item_reference=p.get("item_reference", ""),
                    description=p.get("description", ""),
                    tested_value=_num(p.get("tested_value")),
                    tolerance=p.get("tolerance", "0"),
                    inputs=_build_inputs(area, p),
                    quantity_book=_num(p.get("quantity_book")),
                    quantity_counted=_num(p.get("quantity_counted")))
                notice = "Test item recorded."
            elif action == "import":
                upload = request.FILES.get("file")
                if upload is None:
                    error = "Choose a CSV or XLSX file to import."
                else:
                    summary = st.import_items(
                        engagement=engagement, actor=request.user, area=area,
                        file_obj=upload, filename=upload.name)
                    notice = (f"Imported {summary['created']} item(s)"
                              + (f", skipped {summary['skipped']}"
                                 if summary["skipped"] else "") + ".")
                    if summary["errors"]:
                        error = " · ".join(summary["errors"][:5])
            elif action in ("record", "cancel", "request_evidence"):
                item = SubstantiveTestItem.objects.filter(
                    pk=p.get("item"), organization=org, engagement=engagement).first()
                if item is None:
                    error = "Item not found."
                elif action == "cancel":
                    st.cancel(item=item, actor=request.user)
                    notice = "Item cancelled."
                elif action == "request_evidence":
                    ereq = st.request_evidence(item=item, actor=request.user)
                    notice = f"Evidence request {ereq.request_number} raised."
                else:
                    st.record_tested(item=item, actor=request.user,
                                     tested_value=p.get("tested_value", "0"),
                                     note=p.get("note", ""))
                    notice = "Tested value recorded."
            else:
                error = "Unknown action."
        except st.SubstantiveTestError as exc:
            error = str(exc)
        except Exception as exc:
            error = str(exc)

    items, summary = [], {}
    if engagement is not None:
        items = list(SubstantiveTestItem.objects.filter(engagement=engagement, area=area)
                     .select_related("created_by")
                     .prefetch_related("evidence_requests")
                     .order_by("-created_at")[:300])
        summary = st.area_summary(organization=org, engagement=engagement)

    return render(request, "audit/substantive/register.html", _ctx(
        request, "audit",
        engagement=engagement,
        engagements=list(AuditEngagement.objects.filter(organization=org)[:200]) if org else [],
        items=items, summary=summary, totals=summary.get("_totals", {}), area=area,
        area_choices=_I.Area.choices,
        error=error, notice=notice,
    ))
