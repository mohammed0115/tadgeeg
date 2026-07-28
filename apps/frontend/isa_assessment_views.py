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

Phase 8H adds the three list-driven ISA assessments:

  * ISA 300 Planning  → ``isa300_planning.build_audit_strategy`` / ``build_audit_plan``
  * ISA 330 Responses → ``isa330_risk_responses.map_responses`` (AssessedRisk list)
  * ISA 240 Fraud     → ``isa240_fraud_response.assess_fraud_responses`` (factor list)

The list-builder pages accept parallel-array rows (``name[]``) so several risks /
factors can be entered and mapped in one deterministic pass. Still stateless: no
model, no migration, no ledger writes.
"""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from apps.audit.services import evidence_lifecycle as lc  # reuse is_auditor
from apps.frontend.page_views import _ctx


def _pdf_response(html_str, filename, request):
    """Render a self-contained HTML string to a downloadable PDF (or None)."""
    try:
        from weasyprint import HTML as _WP
    except Exception:  # pragma: no cover - depends on system libs
        return None
    pdf = _WP(string=html_str, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


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


# ─────────────────────────────────────────────────────────────────────────────
# ISA 300 — Planning (overall strategy + detailed plan)
# ─────────────────────────────────────────────────────────────────────────────
_INDUSTRIES = ["retail", "manufacturing", "services", "banking", "insurance",
               "construction", "non_profit", "technology", "other"]


@login_required(login_url="/login/")
def planning(request):
    """ISA 300 — build an overall audit strategy and a detailed plan."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import isa300_planning as pl

    form = {"organization_name": "", "reporting_period": "", "industry": "retail",
            "revenue_base": "0", "is_listed": False, "is_first_year": False,
            "prior_year_modification": False, "has_internal_audit": False,
            "has_subsidiaries": False, "risk_areas": ""}
    strategy = plan = error = None
    if request.method == "POST":
        form.update({
            "organization_name": request.POST.get("organization_name", ""),
            "reporting_period": request.POST.get("reporting_period", ""),
            "industry": request.POST.get("industry", "retail"),
            "revenue_base": request.POST.get("revenue_base", "0"),
            "is_listed": request.POST.get("is_listed") == "on",
            "is_first_year": request.POST.get("is_first_year") == "on",
            "prior_year_modification": request.POST.get("prior_year_modification") == "on",
            "has_internal_audit": request.POST.get("has_internal_audit") == "on",
            "has_subsidiaries": request.POST.get("has_subsidiaries") == "on",
            "risk_areas": request.POST.get("risk_areas", ""),
        })
        risk_areas = tuple(line.strip() for line in form["risk_areas"].splitlines()
                           if line.strip())
        try:
            ctx = pl.EngagementContext(
                organization_name=form["organization_name"] or "the entity",
                reporting_period=form["reporting_period"] or "the period",
                industry=form["industry"], revenue_base=_dec(form["revenue_base"]),
                is_listed=form["is_listed"], is_first_year=form["is_first_year"],
                prior_year_modification=form["prior_year_modification"],
                has_internal_audit=form["has_internal_audit"],
                has_subsidiaries=form["has_subsidiaries"],
                risk_areas_known_in_advance=risk_areas)
            strat = pl.build_audit_strategy(ctx)
            strategy = strat.to_dict()
            plan = pl.build_audit_plan(strat).to_dict()
        except Exception as exc:
            error = str(exc)

        if strategy and not error and request.POST.get("export") == "pdf":
            html = render_to_string("audit/isa/planning_pdf.html", {
                "strategy": strategy, "plan": plan, "form": form})
            entity = (form["organization_name"] or "entity").replace(" ", "_")
            pdf = _pdf_response(html, f"audit-plan-{entity}.pdf", request)
            if pdf is not None:
                return pdf
            error = "PDF export unavailable on this server."

    return render(request, "audit/isa/planning.html", _ctx(
        request, "audit", form=form, strategy=strategy, plan=plan, error=error,
        industries=_INDUSTRIES))


# ─────────────────────────────────────────────────────────────────────────────
# ISA 330 — Responses to Assessed Risks (AssessedRisk list-builder)
# ─────────────────────────────────────────────────────────────────────────────
_ASSERTIONS = ["existence", "completeness", "accuracy", "cutoff",
               "classification", "valuation", "rights_obligations", "presentation"]
_IR_LEVELS = ["low", "medium", "high", "significant"]
_CR_LEVELS = ["low", "medium", "high"]


def _parse_rows(request, *names):
    """Zip parallel POST arrays (name[]) into per-row dicts."""
    columns = {n: request.POST.getlist(f"{n}[]") for n in names}
    length = max((len(v) for v in columns.values()), default=0)
    rows = []
    for i in range(length):
        rows.append({n: (columns[n][i] if i < len(columns[n]) else "") for n in names})
    return rows


@login_required(login_url="/login/")
def responses(request):
    """ISA 330 — map assessed risks to responsive procedures."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import isa330_risk_responses as rr

    rows, mappings, error = [], None, None
    if request.method == "POST":
        raw = _parse_rows(request, "risk_name", "assertion", "inherent_risk",
                          "control_risk", "is_significant", "is_fraud")
        rows = [r for r in raw if r["risk_name"].strip()]
        if not rows:
            error = "Add at least one assessed risk."
        else:
            try:
                risks = [rr.AssessedRisk(
                    name=r["risk_name"].strip(),
                    assertion=r["assertion"] or "existence",
                    inherent_risk=r["inherent_risk"] or "medium",
                    control_risk=r["control_risk"] or "medium",
                    is_significant_risk=(r["is_significant"] == "yes"),
                    is_fraud_risk=(r["is_fraud"] == "yes")) for r in rows]
                mappings = [m.to_dict() for m in rr.map_responses(risks)]
            except Exception as exc:
                error = str(exc)

    return render(request, "audit/isa/responses.html", _ctx(
        request, "audit", rows=rows, mappings=mappings, error=error,
        assertions=_ASSERTIONS, ir_levels=_IR_LEVELS, cr_levels=_CR_LEVELS))


# ─────────────────────────────────────────────────────────────────────────────
# ISA 240 — Fraud response plan (FraudRiskFactor list-builder)
# ─────────────────────────────────────────────────────────────────────────────
_SEVERITIES = ["low", "medium", "high"]
_SIGNALS = ["", "duplicate", "benford", "vendor_risk", "behavioral", "structural"]


@login_required(login_url="/login/")
def fraud(request):
    """ISA 240 — build the fraud response plan from identified factors."""
    denied = _guard(request)
    if denied:
        return denied
    from apps.audit.services import isa240_fraud_response as fr

    rows, result, error = [], None, None
    if request.method == "POST":
        raw = _parse_rows(request, "factor_name", "description", "severity",
                          "assertions", "detected_by")
        rows = [r for r in raw if r["factor_name"].strip()]
        try:
            factors = [fr.FraudRiskFactor(
                name=r["factor_name"].strip(), description=r["description"].strip(),
                severity=r["severity"] or "medium",
                affected_assertions=tuple(
                    a.strip() for a in r["assertions"].split(",") if a.strip()),
                detected_by=r["detected_by"]) for r in rows]
            result = fr.assess_fraud_responses(factors).to_dict()
            result["overall_label"] = result["overall_severity"].replace("_", " ").title()
            for p in result["procedures"] + result["mgmt_override"]:
                p["label"] = p["name"].replace("_", " ").capitalize()
        except Exception as exc:
            error = str(exc)

    return render(request, "audit/isa/fraud.html", _ctx(
        request, "audit", rows=rows, result=result, error=error,
        severities=_SEVERITIES, signals=_SIGNALS))
