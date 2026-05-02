"""Build a senior-auditor-grade Findings Register from raw audit data.

The base report serializer surfaces `top_failed_rules` (rule_code + count) and
`top_risk_invoices` (invoice rows + risk score). That's enough for a summary,
but a real audit deliverable needs each finding to carry:

  - Severity     — Critical / High / Medium / Low (so reviewers prioritize)
  - Group        — Header / Duplicate / VAT / Anomaly / Controls / Quality
  - $ Impact     — sum of total_amount across affected invoices
  - Invoice refs — id + number pairs so the report can deep-link
  - Recommendation — what an auditor would advise next

This module enriches the raw rows with the above so templates only have to
render, not compute. All logic is read-only and side-effect free.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from django.utils.translation import gettext_lazy as _

# ─── Rule metadata ───────────────────────────────────────────────────────────
# Severity is the auditor-assigned criticality, not the rule's data category.
# - critical: ZATCA/regulatory violations or duplicates that cause double-payment
# - high:     calculation errors, missing approval, fraud anomalies
# - medium:   missing fields, unknown vendors
# - low:      document quality, controls metadata

RULE_SEVERITY: dict[str, str] = {
    # Header (mostly required-field gaps)
    "INV-001": "high",     # missing invoice number → can't track
    "INV-002": "medium",   # missing date
    "INV-003": "high",     # missing vendor name
    "INV-004": "high",     # missing TRN → tax compliance risk
    "INV-005": "critical", # missing total amount → can't audit
    "INV-006": "medium",   # missing currency
    "INV-007": "critical", # total ≤ 0 → likely error or fraud
    "INV-008": "high",     # VAT without subtotal → calculation error

    # Duplicate detection (financial-impact severe)
    "DUP-001": "critical", # duplicate invoice number for vendor
    "DUP-002": "critical", # exact duplicate
    "DUP-003": "critical", # same vendor + amount + date
    "DUP-004": "critical", # same file uploaded twice
    "DUP-005": "high",     # same number, different month

    # VAT / ZATCA compliance (regulatory)
    "VAT-001": "critical", # wrong VAT rate
    "VAT-002": "critical", # arithmetic error
    "VAT-003": "high",     # subtotal+VAT ≠ total
    "VAT-004": "high",     # missing TRN
    "VAT-005": "critical", # missing/invalid QR (ZATCA Phase 2)

    # Anomaly detection (fraud signals)
    "ANO-001": "high",     # unusually high amount
    "ANO-002": "medium",   # new unknown vendor
    "ANO-003": "high",     # many invoices same day from same vendor
    "ANO-004": "medium",   # sudden price change
    "ANO-005": "medium",   # year-end concentration
    "ANO-006": "high",     # vendor dominates >50% spend

    # Financial controls
    "CTL-001": "medium",   # no cost center
    "CTL-002": "medium",   # no account code
    "CTL-003": "high",     # outside budget
    "CTL-004": "critical", # post-approval modification
    "CTL-005": "high",     # no approver assigned
    "CTL-006": "medium",   # audit trail gap

    # Document quality
    "DOC-001": "low",      # unclear scan
    "DOC-002": "high",     # not genuine
    "DOC-003": "critical", # alteration markers
    "DOC-004": "high",     # no QR on ZATCA invoice

    # ── Doc-validators severities (auto-extracted from doc_validators.py) ──
    "PO-001": "high", "PO-002": "high", "PO-003": "high",
    "PO-004": "critical", "PO-005": "critical", "PO-006": "critical",
    "PO-007": "high", "PO-008": "high", "PO-009": "high", "PO-010": "medium",
    "BNK-001": "critical", "BNK-002": "high", "BNK-003": "critical",
    "BNK-004": "high", "BNK-005": "medium", "BNK-006": "medium",
    "BNK-007": "high", "BNK-008": "high", "BNK-009": "medium",
    "PAY-001": "critical", "PAY-002": "critical", "PAY-003": "critical",
    "PAY-004": "high", "PAY-005": "high", "PAY-006": "medium",
    "PAY-007": "medium", "PAY-008": "high", "PAY-009": "medium",
    "EXP-001": "high", "EXP-002": "critical", "EXP-003": "medium",
    "EXP-004": "high", "EXP-005": "high", "EXP-006": "medium",
    "EXP-007": "medium", "EXP-008": "high",
    "VATR-001": "critical", "VATR-002": "critical", "VATR-003": "high",
    "VATR-004": "critical", "VATR-005": "high", "VATR-006": "high",
    "VATR-007": "high", "VATR-008": "medium",
    "AST-001": "critical", "AST-002": "critical", "AST-003": "high",
    "AST-004": "high", "AST-005": "medium", "AST-006": "critical",
    "AST-007": "medium", "AST-008": "high", "AST-009": "medium",
    "REC-001": "high", "REC-002": "high", "REC-003": "critical",
    "REC-004": "critical", "REC-005": "high", "REC-006": "critical",
    "REC-007": "critical", "REC-008": "critical",
}

RULE_GROUP: dict[str, tuple[str, str]] = {
    "INV":  ("header",     _("Invoice Header")),
    "DUP":  ("duplicate",  _("Duplicates")),
    "VAT":  ("vat",        _("VAT & ZATCA")),
    "ANO":  ("anomaly",    _("Anomalies")),
    "CTL":  ("control",    _("Financial Controls")),
    "DOC":  ("quality",    _("Document Quality")),
    # Doc-validators groups (PO/BNK/PAY/EXP/VATR/AST/REC)
    "PO":   ("po",         _("Purchase Order")),
    "BNK":  ("bank",       _("Bank Statement")),
    "PAY":  ("payroll",    _("Payroll")),
    "EXP":  ("expense",    _("Expense Report")),
    "VATR": ("vat_return", _("VAT Return")),
    "AST":  ("asset",      _("Fixed Asset")),
    "REC":  ("receipt",    _("Sales Receipt")),
}

RULE_RECOMMENDATION: dict[str, str] = {
    "INV-001": _("Reject invoices missing an invoice number; require vendors to resubmit."),
    "INV-002": _("Reject invoices without a date; cannot age or report without it."),
    "INV-003": _("Block any invoice with no vendor — this is a basic control failure."),
    "INV-004": _("Withhold VAT recovery until a valid TRN is provided by the vendor."),
    "INV-005": _("Hold invoice; without a total amount it cannot be paid or audited."),
    "INV-006": _("Set a default currency at the organization level to prevent omissions."),
    "INV-007": _("Investigate any zero/negative invoices — likely data error or refund mishandled."),
    "INV-008": _("Recompute subtotal from line items or reject the invoice."),
    "DUP-001": _("Block payment until duplicate is reconciled with the vendor."),
    "DUP-002": _("This is an exact duplicate — verify whether it was paid before approving."),
    "DUP-003": _("High double-payment risk — match against existing payments before release."),
    "DUP-004": _("Same file uploaded again — quarantine and notify the uploader."),
    "DUP-005": _("Confirm with the vendor whether the invoice number was reused legitimately."),
    "VAT-001": _("Correct the VAT rate to 15%% (KSA) before submitting to ZATCA."),
    "VAT-002": _("Recalculate VAT; the discrepancy will be rejected at e-invoicing submission."),
    "VAT-003": _("Subtotal + VAT must equal total — fix arithmetic error."),
    "VAT-004": _("Request a valid TRN from the vendor; required for input VAT recovery."),
    "VAT-005": _("Re-issue the invoice with a valid ZATCA Phase 2 QR code."),
    "ANO-001": _("Compare to vendor history and obtain documented justification before approval."),
    "ANO-002": _("Onboard the vendor through procurement before processing further invoices."),
    "ANO-003": _("Investigate possible split invoices (structuring) to bypass approval limits."),
    "ANO-004": _("Verify the price change is supported by an updated contract or quote."),
    "ANO-005": _("Year-end concentration may indicate cutoff manipulation — sample for review."),
    "ANO-006": _("Reduce concentration risk by qualifying additional vendors for this category."),
    "CTL-001": _("Assign a cost center; required for departmental budget tracking."),
    "CTL-002": _("Map the invoice to a chart-of-accounts code before posting."),
    "CTL-003": _("Escalate to budget owner for approval of the overage or split into next period."),
    "CTL-004": _("Investigate the post-approval edit — possible internal control breach."),
    "CTL-005": _("Reject; every invoice must have a documented approver."),
    "CTL-006": _("Audit trail must be reconstructed before this invoice can be relied on."),
    "DOC-001": _("Request a clearer scan from the vendor to enable accurate OCR."),
    "DOC-002": _("Document appears tampered — escalate to fraud investigation."),
    "DOC-003": _("Alteration detected — quarantine and run a forensic review."),
    "DOC-004": _("ZATCA Phase 2 mandates a QR code — request a re-issued e-invoice."),

    # ── Doc-validators (Purchase Order) ──
    "PO-001": _("Reject POs missing a PO number; require resubmission."),
    "PO-002": _("Reject POs with missing or future-dated dates."),
    "PO-003": _("Block POs without a vendor name — basic control failure."),
    "PO-004": _("Withhold processing until a valid vendor TRN is provided."),
    "PO-005": _("Recalculate VAT at 15% (KSA) before approval."),
    "PO-006": _("Subtotal + VAT must equal total — fix arithmetic error."),
    "PO-007": _("Escalate to budget owner for over-budget approval."),
    "PO-008": _("Reject; every PO must have a documented approver."),
    "PO-009": _("Investigate price variance against the related invoice or contract."),
    "PO-010": _("Assign a cost center; required for departmental tracking."),
    # Bank Statement
    "BNK-001": _("Reconcile closing balance with transactions before relying on the statement."),
    "BNK-002": _("Investigate large unjustified transactions — possible fraud signal."),
    "BNK-003": _("Investigate duplicate transactions — possible double-posting."),
    "BNK-004": _("Benford's-law anomaly — sample non-conforming transactions for review."),
    "BNK-005": _("Excessive rounded amounts may indicate fabricated data — sample for review."),
    "BNK-006": _("Weekend transactions warrant additional approval evidence."),
    "BNK-007": _("Add a valid bank account number; required for reconciliation."),
    "BNK-008": _("Provide explicit statement period dates."),
    "BNK-009": _("Validate the IBAN against the Saudi format."),
    # Payroll
    "PAY-001": _("Investigate duplicate national IDs — possible ghost employee scheme."),
    "PAY-002": _("Confirm employees physically with HR before next payroll cycle."),
    "PAY-003": _("Recalculate net = gross − deductions; fix the variance."),
    "PAY-004": _("Add GOSI contributions; mandatory under Saudi labor law."),
    "PAY-005": _("Document business justification for raises exceeding 30%."),
    "PAY-006": _("Migrate cash payments to bank transfers per AML guidance."),
    "PAY-007": _("State the explicit payroll period."),
    "PAY-008": _("Reconcile total against the per-employee detail."),
    "PAY-009": _("Verify employee count matches HR master records."),
    # Expense Report
    "EXP-001": _("Require a receipt for every expense line before approval."),
    "EXP-002": _("Investigate duplicate expense claims — possible reimbursement fraud."),
    "EXP-003": _("Escalate over-policy items to the responsible manager."),
    "EXP-004": _("Reject; every expense report needs documented approval."),
    "EXP-005": _("Investigate possible expense splitting to bypass approval limits."),
    "EXP-006": _("Confirm valid expense dates before reimbursement."),
    "EXP-007": _("Recalculate VAT on each line."),
    "EXP-008": _("Reconcile claimed total against the line-item sum."),
    # VAT Return
    "VATR-001": _("Validate the taxpayer TRN against ZATCA records."),
    "VATR-002": _("Recalculate output VAT = standard-rated sales × 15%."),
    "VATR-003": _("Investigate negative input VAT — likely data error."),
    "VATR-004": _("Recalculate net VAT = output − input; fix the variance."),
    "VATR-005": _("Reconcile output VAT against invoice ledger; investigate variance."),
    "VATR-006": _("Reconcile input VAT against purchase ledger; investigate variance."),
    "VATR-007": _("File on time — late filing triggers penalties."),
    "VATR-008": _("Specify the explicit VAT return period."),
    # Fixed Asset
    "AST-001": _("Investigate negative book values — likely posting error or impairment overshoot."),
    "AST-002": _("Cap accumulated depreciation at original cost; correct over-depreciation."),
    "AST-003": _("Validate depreciation rates against the asset class policy."),
    "AST-004": _("Investigate duplicate asset IDs in the register."),
    "AST-005": _("Assign asset IDs to all rows for traceability."),
    "AST-006": _("Recompute book value = cost − accumulated depreciation."),
    "AST-007": _("Validate useful life against the asset's class (3–50 years typical)."),
    "AST-008": _("Reconcile total cost against per-asset records."),
    "AST-009": _("Reject future-dated purchase records; possible fabrication."),
    # Sales Receipt
    "REC-001": _("Reject receipts missing a receipt number."),
    "REC-002": _("Reject receipts with missing or future-dated dates."),
    "REC-003": _("Correct the VAT rate to 15% (KSA)."),
    "REC-004": _("Recalculate VAT amount = subtotal × 15%."),
    "REC-005": _("Re-issue the receipt with a ZATCA QR code."),
    "REC-006": _("QR data must match receipt fields — re-issue with a corrected QR."),
    "REC-007": _("Investigate duplicate receipts — possible double-recording."),
    "REC-008": _("Request a valid seller TRN; required for input VAT recovery."),
}

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Localized severity labels — use the existing translated strings so we don't
# add new msgids the .po files don't already cover.
SEVERITY_LABELS = {
    "critical": _("Critical"),
    "high":     _("High"),
    "medium":   _("Medium"),
    "low":      _("Low"),
}


def severity_for(rule_code: str | None) -> str:
    """Return critical/high/medium/low for a rule code; default to medium."""
    if not rule_code:
        return "medium"
    return RULE_SEVERITY.get(rule_code, "medium")


def group_for(rule_code: str | None) -> tuple[str, str]:
    """Return (group_key, group_label) for a rule code."""
    prefix = (rule_code or "").split("-", 1)[0]
    return RULE_GROUP.get(prefix, ("other", _("Other")))


def recommendation_for(rule_code: str | None) -> str:
    """Return a human auditor-style recommendation, or a generic fallback."""
    if rule_code and rule_code in RULE_RECOMMENDATION:
        return RULE_RECOMMENDATION[rule_code]
    return _("Investigate and resolve before approval; contact the responsible reviewer.")


def build_narrative(
    *,
    findings_register: dict,
    type_label: str = None,
    type_singular: str = None,
) -> dict:
    """Generate the executive narrative + action plan from real findings.

    Replaces the previous hardcoded Arabic copy that referenced "invoices" and
    "QR codes" regardless of doc type. Outputs:

        {
          "conclusion":       "...",                 # 1-line summary
          "key_findings":     ["...", "...", "..."], # 3-5 bullets, real numbers
          "exec_recs":        ["...", "...", "..."], # exec-level next actions
          "immediate":        ["...", ...],          # 3 critical/high actions
          "future":           ["...", ...],          # 3 longer-horizon improvements
        }

    All strings are gettext-translated (so AR/EN both render correctly).
    """
    findings = findings_register.get("findings", [])
    by_sev = findings_register.get("by_severity", {})
    affected = findings_register.get("total_invoices_affected", 0)
    impact = findings_register.get("total_financial_impact", 0)
    crit = by_sev.get("critical", 0)
    high = by_sev.get("high", 0)
    medium = by_sev.get("medium", 0)
    low = by_sev.get("low", 0)
    total_findings = len(findings)
    label_plural = type_label or _("Documents")
    label_singular = type_singular or _("Document")

    # ── Conclusion (1-line, severity-aware) ──
    if total_findings == 0:
        conclusion = _("No rule violations were detected — controls operate as designed.")
    elif crit > 0:
        conclusion = _(
            "Critical issues were detected requiring immediate remediation; "
            "investigate the items below before final approval."
        )
    elif high > 0:
        conclusion = _(
            "Significant issues were detected. Resolve high-severity findings "
            "during the current review cycle."
        )
    elif medium > 0:
        conclusion = _(
            "Minor compliance gaps were detected. Plan remediation in the "
            "next operational sprint."
        )
    else:
        conclusion = _(
            "Only low-severity observations were detected — controls are "
            "broadly effective; address opportunistically."
        )

    # ── Key findings (real numbers, derived) ──
    key_findings: list[str] = []
    if total_findings > 0:
        # Critical/High count
        if crit > 0:
            key_findings.append(
                str(_("%(n)s critical finding(s) requiring immediate action") % {"n": crit})
            )
        if high > 0:
            key_findings.append(
                str(_("%(n)s high-severity finding(s) blocking approval") % {"n": high})
            )
        if medium > 0:
            key_findings.append(
                str(_("%(n)s medium-severity finding(s) for the remediation backlog") % {"n": medium})
            )
        if low > 0:
            key_findings.append(
                str(_("%(n)s low-severity observation(s)") % {"n": low})
            )
        # Affected docs + financial impact
        if affected:
            key_findings.append(
                str(_("Affecting %(count)s %(type)s") % {"count": affected, "type": label_plural})
            )
        if impact:
            key_findings.append(
                str(_("Estimated financial exposure: %(amount).2f SAR") % {"amount": impact})
            )

    # ── Immediate actions: take the top critical+high recommendations ──
    immediate: list[str] = []
    blocking = [f for f in findings if f["severity"] in ("critical", "high")]
    seen_recs: set[str] = set()
    for f in blocking:
        rec = f.get("recommendation")
        if rec and rec not in seen_recs:
            seen_recs.add(rec)
            immediate.append(rec)
        if len(immediate) >= 4:
            break

    # ── Future improvements: medium/low findings + a couple of programmatic ones ──
    future: list[str] = []
    non_blocking = [f for f in findings if f["severity"] in ("medium", "low")]
    seen_future: set[str] = set()
    for f in non_blocking:
        rec = f.get("recommendation")
        if rec and rec not in seen_future:
            seen_future.add(rec)
            future.append(rec)
        if len(future) >= 4:
            break

    # If we have findings but no future entries (all critical/high), generate
    # one programmatic improvement so the future column never looks empty.
    if findings and not future:
        future.append(
            str(_("Add real-time controls so the same rule is caught before %(type)s approval.")
                % {"type": label_singular})
        )
        future.append(
            str(_("Train the team on the most-failed control to drive recurring failures down."))
        )

    # ── Executive recommendations: 3 high-level (severity-aware) ──
    exec_recs: list[str] = []
    if crit > 0 or high > 0:
        exec_recs.append(
            str(_("Close all blocking findings (critical + high) before the next reporting cycle."))
        )
    if rule_failure_concentration := _top_rule_concentration(findings):
        exec_recs.append(
            str(_("Address the dominant control failure (%(code)s) which accounts for most violations.")
                % {"code": rule_failure_concentration})
        )
    if affected:
        exec_recs.append(
            str(_("Run targeted training on the controls that drove most failures across %(count)s %(type)s.")
                % {"count": affected, "type": label_plural})
        )

    return {
        "conclusion":   str(conclusion),
        "key_findings": key_findings,
        "exec_recs":    exec_recs,
        "immediate":    immediate,
        "future":       future,
    }


def _top_rule_concentration(findings: list[dict]) -> str | None:
    """Return the rule code that's responsible for >40% of violations, if any."""
    if not findings:
        return None
    total = sum(f.get("failure_count", 0) for f in findings)
    if not total:
        return None
    top = max(findings, key=lambda f: f.get("failure_count", 0))
    if top.get("failure_count", 0) / total > 0.4:
        return top.get("rule_code")
    return None


def build_findings_register(
    *,
    top_failed_rules: list[dict],
    validations: Iterable,
    rule_catalog: dict[str, str],
) -> dict:
    """Return a richer view of failed rules ready for template consumption.

    Result shape:
        {
            "findings": [
                {
                    "rule_code": "DUP-002",
                    "title":     "Same vendor + invoice number duplicate",
                    "severity":  "critical",
                    "severity_label": "Critical",
                    "group":     "duplicate",
                    "group_label": "Duplicates",
                    "failure_count": 12,
                    "invoices": [{"id": "...", "number": "INV-001", "amount": 1500.0}, ...],
                    "invoice_count": 12,
                    "financial_impact": 18450.0,
                    "recommendation": "Block payment until reconciled.",
                },
                ...
            ],
            "by_severity": {"critical": 2, "high": 5, "medium": 1, "low": 0},
            "total_invoices_affected": 17,
            "total_financial_impact": 53420.0,
        }
    """
    top_codes = {r.get("rule_code") for r in (top_failed_rules or []) if r.get("rule_code")}

    # invoice_id_set per rule_code, plus per-invoice metadata cache
    rule_invoices: dict[str, list[dict]] = defaultdict(list)
    seen_per_rule: dict[str, set[str]] = defaultdict(set)
    affected_invoice_ids: set[str] = set()

    for vr in validations:
        inv = vr.invoice
        inv_key = str(inv.id)
        for code in (vr.failed_rule_codes or []):
            if code not in top_codes or inv_key in seen_per_rule[code]:
                continue
            seen_per_rule[code].add(inv_key)
            rule_invoices[code].append({
                "id":     inv_key,
                "number": inv.invoice_number or inv_key[:8],
                "amount": float(getattr(inv, "total_amount", 0) or 0),
                "vendor": getattr(inv, "vendor_name", "") or "",
                "date":   str(getattr(inv, "invoice_date", "") or ""),
            })
            affected_invoice_ids.add(inv_key)

    findings: list[dict] = []
    by_severity: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    total_impact = 0.0

    for raw in (top_failed_rules or []):
        code = raw.get("rule_code")
        invs = rule_invoices.get(code, [])
        impact = round(sum(i["amount"] for i in invs), 2)
        sev = severity_for(code)
        gkey, glabel = group_for(code)
        title = rule_catalog.get(code, code) if isinstance(rule_catalog, dict) else code
        findings.append({
            "rule_code":         code,
            "title":             raw.get("description") or title,
            "severity":          sev,
            "severity_label":    str(SEVERITY_LABELS[sev]),
            "group":             gkey,
            "group_label":       str(glabel),
            "failure_count":     int(raw.get("failures") or len(invs)),
            "invoices":          invs,
            "invoice_count":     len(invs),
            "financial_impact":  impact,
            "recommendation":    str(recommendation_for(code)),
        })
        by_severity[sev] = by_severity.get(sev, 0) + 1
        total_impact += impact

    # Sort: severity ascending (critical first), then by financial impact descending
    findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), -f["financial_impact"]))

    return {
        "findings":                 findings,
        "by_severity":              by_severity,
        "total_invoices_affected":  len(affected_invoice_ids),
        "total_financial_impact":   round(total_impact, 2),
    }
