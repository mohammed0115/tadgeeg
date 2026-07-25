"""ISA assessment pages (TADGEEG-FIN-AUDIT-8E/8F).

Form-driven, auditor-only frontend for the ISA computation engines already built
in the audit app — no new backend logic:

  * ISA 315 Risk Assessment → ``risk_decomposition.assess``
  * ISA 570 Going Concern   → ``going_concern.assess_going_concern``
  * ISA 540 Estimates       → ``estimates.assess_estimation_uncertainty``

Each page renders a structured input form (fields derived from the engine's own
dataclass), runs the engine on submit, and shows a polished result. Advisory
only: results are auditor aids, never a formal audit opinion, and nothing is
persisted or written to the ledger.

ISA 300 planning and ISA 330/240 (list-driven inputs) are intentionally deferred
— see the progress tracker.
"""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.frontend.page_views import _ctx


def _guard(request):
    if not lc.is_auditor(request.user):
        return render(request, "403.html", _ctx(request, "audit"), status=403)
    return None


def _int(value, *, lo=0, hi=25, default=0):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _dec(value, default=Decimal("0")):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# ISA 315 — Risk Assessment
# ─────────────────────────────────────────────────────────────────────────────
_RISK_GROUPS = [
    ("Inherent risk drivers", "The untouched susceptibility to misstatement.",
     ["industry_volatility", "complexity_of_transactions",
      "susceptibility_to_fraud", "related_party_density"]),
    ("Control strength", "The entity's defences (higher = stronger controls).",
     ["control_design_strength", "control_operating_effectiveness",
      "segregation_of_duties_score", "monitoring_strength"]),
    ("Planned procedures", "Auditor coverage (higher = more persuasive work).",
     ["sample_extent", "procedure_persuasiveness", "timing_of_procedures",
      "staff_competence"]),
]


@login_required(login_url="/login/")
def risk_assessment(request):
    """ISA 315 audit-risk model (IR × CR × DR)."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import risk_decomposition as rd

    values = {name: 0 for group in _RISK_GROUPS for name in group[2]}
    result = None
    if request.method == "POST":
        for name in values:
            values[name] = _int(request.POST.get(name))
        inputs = rd.RiskAssessmentInputs(**values, notes=request.POST.get("notes", ""))
        result = rd.assess(inputs).to_dict()

    groups = [{"title": t, "help": h,
               "fields": [{"name": n, "label": n.replace("_", " ").title(),
                           "value": values[n]} for n in names]}
              for t, h, names in _RISK_GROUPS]

    return render(request, "audit/isa/risk_assessment.html", _ctx(
        request, "audit", groups=groups, result=result))


# ─────────────────────────────────────────────────────────────────────────────
# ISA 570 — Going Concern
# ─────────────────────────────────────────────────────────────────────────────
_GC_GROUPS = [
    ("Financial indicators", ("net_liability_position", "fixed_term_borrowing_due",
        "indications_withdrawal_of_finance", "negative_operating_cash_flow",
        "adverse_key_ratios", "substantial_operating_losses",
        "arrears_or_discontinuance_dividends", "inability_to_pay_creditors",
        "inability_to_comply_with_loan_terms", "change_to_cash_on_delivery")),
    ("Operating indicators", ("intention_to_liquidate", "loss_of_key_management",
        "loss_of_major_market_franchise", "labour_difficulties",
        "shortages_of_supplies", "emergence_of_competitor")),
    ("Other indicators", ("non_compliance_with_capital_or_statutory_requirements",
        "pending_legal_proceedings", "changes_in_law_or_government_policy",
        "uninsured_or_underinsured_catastrophes")),
    ("Mitigating evidence", ("mgmt_has_credible_recovery_plan",
        "parent_letter_of_support", "refinancing_secured")),
]


@login_required(login_url="/login/")
def going_concern(request):
    """ISA 570 going-concern indicator assessment (boolean checklist)."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import going_concern as gc

    bool_fields = {f.name for f in fields(gc.GoingConcernIndicators)}
    checked = set()
    result = None
    if request.method == "POST":
        checked = {n for n in bool_fields if request.POST.get(n) == "on"}
        ind = gc.GoingConcernIndicators(**{n: (n in checked) for n in bool_fields})
        result = gc.assess_going_concern(ind).to_dict()
        result["severity_label"] = result["severity"].replace("_", " ").title()
        result["indicators_labels"] = [x.replace("_", " ").capitalize() for x in result["indicators"]]
        result["mitigants_labels"] = [x.replace("_", " ").capitalize() for x in result["mitigants"]]

    groups = [{"title": t, "is_mitigant": t == "Mitigating evidence",
               "fields": [{"name": n, "label": n.replace("_", " ").capitalize(),
                           "checked": n in checked} for n in names]}
              for t, names in _GC_GROUPS]

    return render(request, "audit/isa/going_concern.html", _ctx(
        request, "audit", groups=groups, result=result))


# ─────────────────────────────────────────────────────────────────────────────
# ISA 540 — Accounting Estimates
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url="/login/")
def estimates(request):
    """ISA 540 estimation-uncertainty assessment."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import estimates as es

    form = {"name": "", "category": "provision", "management_estimate": "0",
            "estimation_method": "point", "complexity": 3, "subjectivity": 3,
            "estimation_uncertainty": 3, "relies_on_external_data": False,
            "prior_period_misstatement": False, "disclosure_quality": 3, "notes": ""}
    result = error = None
    if request.method == "POST":
        form.update({
            "name": request.POST.get("name", ""),
            "category": request.POST.get("category", "provision"),
            "management_estimate": request.POST.get("management_estimate", "0"),
            "estimation_method": request.POST.get("estimation_method", "point"),
            "complexity": _int(request.POST.get("complexity"), lo=1, hi=5, default=3),
            "subjectivity": _int(request.POST.get("subjectivity"), lo=1, hi=5, default=3),
            "estimation_uncertainty": _int(request.POST.get("estimation_uncertainty"), lo=1, hi=5, default=3),
            "relies_on_external_data": request.POST.get("relies_on_external_data") == "on",
            "prior_period_misstatement": request.POST.get("prior_period_misstatement") == "on",
            "disclosure_quality": _int(request.POST.get("disclosure_quality"), lo=1, hi=5, default=3),
            "notes": request.POST.get("notes", ""),
        })
        try:
            profile = es.EstimateProfile(
                name=form["name"] or "Estimate", category=form["category"],
                management_estimate=_dec(form["management_estimate"]),
                estimation_method=form["estimation_method"],
                complexity=form["complexity"], subjectivity=form["subjectivity"],
                estimation_uncertainty=form["estimation_uncertainty"],
                relies_on_external_data=form["relies_on_external_data"],
                prior_period_misstatement=form["prior_period_misstatement"],
                disclosure_quality=form["disclosure_quality"], notes=form["notes"])
            result = es.assess_estimation_uncertainty(profile).to_dict()
            result["severity_label"] = result["severity"].replace("_", " ").title()
        except Exception as exc:
            error = str(exc)

    return render(request, "audit/isa/estimates.html", _ctx(
        request, "audit", form=form, result=result, error=error,
        categories=["provision", "fair_value", "depreciation", "ecl", "other"],
        methods=["point", "range", "discounted_cash_flow", "model_based"],
        scale=[1, 2, 3, 4, 5]))
