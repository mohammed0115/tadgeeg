"""Journal Analytics engine (TADGEEG-FIN-AUDIT-7A).

Deterministic, journal-level analytics over staged ``GeneralLedgerRow`` data.

REUSE (deliberate — no logic is duplicated):
  * thresholds/keywords and helpers are IMPORTED from the 2B service
    ``general_ledger_risk_analysis`` (``MANUAL_KEYWORDS``, ``SENSITIVE_CATEGORIES``,
    ``WEEKEND_WEEKDAYS``, ``PERIOD_END_WINDOW_DAYS``, ``_is_round``, ``_row_date``,
    ``_row_category``, ``_severity_for``), so a threshold change stays in ONE place;
  * the High Value rule uses 3A's ``materiality.resolve_materiality`` rather than
    inventing a new threshold.

DIFFERENCE FROM 2B (why this is not a duplicate): 2B analyses **rows** and
produces ``GeneralLedgerRiskFinding`` candidates that feed the auditor review
pipeline (3B → 4A → 5A). 7A analyses **journals** and produces ADVISORY
analytics only. It never creates/updates a finding, never accepts anything,
never issues an opinion, and never writes to ``apps.ledger``.

Only two rules here are genuinely new (High Value Journal, Dormant Account
Activity); the rest are the same deterministic predicates re-expressed at
journal granularity from the shared constants above.
"""
from __future__ import annotations

import datetime
import time
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.general_ledger_models import GeneralLedgerImport
from apps.audit.journal_analytics_models import (
    JournalAnalyticsResult,
    JournalAnalyticsRule,
    JournalAnalyticsRun,
    JournalAnalyticsSummary,
)
# ── REUSED from 2B (single source of truth for these thresholds) ─────────────
from apps.audit.services.general_ledger_risk_analysis import (
    MANUAL_KEYWORDS,
    PERIOD_END_WINDOW_DAYS,
    SENSITIVE_CATEGORIES,
    SIGNIFICANT_AMOUNT,
    WEEKEND_WEEKDAYS,
    _is_round,
    _row_category,
    _row_date,
    _severity_for,
)
from apps.audit.services.gl_finding_materiality import (  # REUSED from 3A
    resolve_materiality,
)

_ZERO = Decimal("0")
_Sev = JournalAnalyticsResult.Severity
_Cat = JournalAnalyticsRule.Category

# Days of inactivity after which an account is considered dormant.
DORMANT_DAYS = 180
# Fallback high-value threshold when the engagement has no materiality profile.
HIGH_VALUE_FALLBACK = SIGNIFICANT_AMOUNT * 10  # 100,000


class AnalyticsError(Exception):
    """Raised when a run cannot be executed."""


# ─────────────────────────────────────────────────────────────────────────────
# Journal aggregation
# ─────────────────────────────────────────────────────────────────────────────
class Journal:
    """An aggregated journal (all rows sharing a journal_number)."""

    __slots__ = ("number", "rows", "total_debit", "total_credit", "date",
                 "accounts", "entered_by", "descriptions", "abs_amount")

    def __init__(self, number):
        self.number = number
        self.rows = []
        self.total_debit = _ZERO
        self.total_credit = _ZERO
        self.date = None
        self.accounts = []
        self.entered_by = ""
        self.descriptions = []
        self.abs_amount = _ZERO

    def add(self, row):
        self.rows.append(row)
        self.total_debit += row.debit or _ZERO
        self.total_credit += row.credit or _ZERO
        rdate = _row_date(row)
        if rdate and (self.date is None or rdate < self.date):
            self.date = rdate
        if row.account_code:
            self.accounts.append(row)
        if row.entered_by and not self.entered_by:
            self.entered_by = row.entered_by
        self.descriptions.append(row.description or "")
        self.abs_amount += abs(row.signed_amount or ((row.debit or _ZERO) - (row.credit or _ZERO)))

    @property
    def primary_account(self):
        return self.accounts[0] if self.accounts else (self.rows[0] if self.rows else None)

    @property
    def text_blob(self) -> str:
        parts = list(self.descriptions)
        for r in self.rows:
            parts.append(r.source_system or "")
            parts.append(r.entered_by or "")
        return " ".join(parts).lower()


def build_journals(rows) -> list[Journal]:
    """Group staged GL rows into journals (blank numbers become synthetic)."""
    groups: dict[str, Journal] = {}
    for row in rows:
        key = row.journal_number or f"ROW-{row.row_number}"
        journal = groups.get(key)
        if journal is None:
            journal = groups[key] = Journal(key)
        journal.add(row)
    return list(groups.values())


# ─────────────────────────────────────────────────────────────────────────────
# Rule definitions — each rule is independent and returns hits (or [])
# ─────────────────────────────────────────────────────────────────────────────
class RuleSpec:
    def __init__(self, code, name, category, base_score, description,
                 recommendation, fn):
        self.code = code
        self.name = name
        self.category = category
        self.base_score = base_score
        self.description = description
        self.recommendation = recommendation
        self.fn = fn


def _hit(journal, *, description, amount=None, evidence=None):
    return {
        "journal": journal,
        "description": description,
        "amount": amount if amount is not None else journal.abs_amount,
        "evidence": evidence or {},
    }


def _rule_round_amount(journal, ctx):
    amount = journal.abs_amount
    if _is_round(amount):
        return [_hit(journal, description=(
            f"Journal total {amount} is a large round number."),
            evidence={"total": str(amount)})]
    return []


def _rule_weekend_posting(journal, ctx):
    d = journal.date
    if d and isinstance(d, datetime.date) and d.weekday() in WEEKEND_WEEKDAYS:
        return [_hit(journal, description=(
            f"Journal dated {d} falls on a weekend (Fri/Sat)."),
            evidence={"date": str(d), "weekday": d.weekday()})]
    return []


def _rule_period_end_posting(journal, ctx):
    d, period_end = journal.date, ctx.get("period_end")
    if period_end and d and isinstance(d, datetime.date):
        delta = (period_end - d).days
        if 0 <= delta < PERIOD_END_WINDOW_DAYS:
            return [_hit(journal, description=(
                f"Journal posted {delta} day(s) before period end ({period_end})."),
                evidence={"date": str(d), "period_end": str(period_end),
                          "days_before_period_end": delta})]
    return []


def _rule_manual_journal(journal, ctx):
    blob = journal.text_blob
    for kw in MANUAL_KEYWORDS:
        if kw in blob:
            return [_hit(journal, description=(
                f"Journal text/source suggests a manual entry (matched '{kw.strip()}')."),
                evidence={"keyword": kw.strip()})]
    return []


def _rule_missing_description(journal, ctx):
    missing = [r for r in journal.rows if len((r.description or "").strip()) < 3]
    if missing:
        return [_hit(journal, description=(
            f"{len(missing)} of {len(journal.rows)} line(s) have no meaningful description."),
            evidence={"lines_missing_description": len(missing)})]
    return []


def _rule_high_value_journal(journal, ctx):
    threshold = ctx["high_value_threshold"]
    if journal.abs_amount >= threshold:
        return [_hit(journal, description=(
            f"Journal total {journal.abs_amount} is at or above the high-value "
            f"threshold {threshold} ({ctx['high_value_basis']})."),
            evidence={"total": str(journal.abs_amount),
                      "threshold": str(threshold),
                      "basis": ctx["high_value_basis"]})]
    return []


def _rule_dormant_account(journal, ctx):
    """An account posted to after a long gap in activity within the import."""
    gaps = ctx["dormant_gaps"]
    hits = []
    seen = set()
    for row in journal.accounts:
        key = (row.account_code, _row_date(row))
        if key in seen:
            continue
        seen.add(key)
        gap = gaps.get(key)
        if gap is not None:
            hits.append(_hit(journal, description=(
                f"Account {row.account_code} was dormant for {gap} day(s) "
                f"before this posting."),
                evidence={"account_code": row.account_code,
                          "dormant_days": gap}))
    return hits[:1]  # one hit per journal is enough for the advisory signal


def _rule_sensitive_account(journal, ctx):
    for row in journal.accounts:
        category = _row_category(row)
        if category in SENSITIVE_CATEGORIES and journal.abs_amount >= SIGNIFICANT_AMOUNT:
            return [_hit(journal, description=(
                f"Significant journal ({journal.abs_amount}) touches a sensitive "
                f"account category '{category}'."),
                evidence={"account_code": row.account_code, "category": category})]
    return []


RULES: list[RuleSpec] = [
    RuleSpec("JA-ROUND", "Round Amount Analysis", _Cat.AMOUNT, 30,
             "Journal totals that are large round numbers.",
             "Inspect supporting documentation for round-sum journals.",
             _rule_round_amount),
    RuleSpec("JA-WEEKEND", "Weekend Posting", _Cat.TIMING, 35,
             "Journals dated on a weekend.",
             "Confirm the business reason for weekend postings.",
             _rule_weekend_posting),
    RuleSpec("JA-PERIODEND", "Period End Posting", _Cat.TIMING, 45,
             "Journals posted close to period end.",
             "Verify cut-off and that the entry belongs in the period.",
             _rule_period_end_posting),
    RuleSpec("JA-MANUAL", "Manual Journal Detection", _Cat.SOURCE, 40,
             "Journals whose text or source indicates a manual entry.",
             "Obtain approval evidence for manual journals.",
             _rule_manual_journal),
    RuleSpec("JA-DESC", "Missing Description", _Cat.DOCUMENTATION, 25,
             "Journals containing lines without a meaningful description.",
             "Request a narrative/description for the affected lines.",
             _rule_missing_description),
    RuleSpec("JA-HIGHVALUE", "High Value Journal", _Cat.AMOUNT, 50,
             "Journals at or above the materiality-based high-value threshold.",
             "Perform substantive testing on high-value journals.",
             _rule_high_value_journal),
    RuleSpec("JA-DORMANT", "Dormant Account Activity", _Cat.ACCOUNT, 45,
             "Postings to accounts after a long period of inactivity.",
             "Investigate why a dormant account was reactivated.",
             _rule_dormant_account),
    RuleSpec("JA-SENSITIVE", "Sensitive Account Usage", _Cat.ACCOUNT, 45,
             "Significant journals touching sensitive account categories.",
             "Review authorisation for postings to sensitive accounts.",
             _rule_sensitive_account),
]

RULES_BY_CODE = {r.code: r for r in RULES}


# ─────────────────────────────────────────────────────────────────────────────
# Rule registry (enable/disable per organization)
# ─────────────────────────────────────────────────────────────────────────────
def ensure_rules(organization) -> list[JournalAnalyticsRule]:
    """Idempotently seed the rule registry for an organization."""
    out = []
    for spec in RULES:
        obj, _created = JournalAnalyticsRule.objects.get_or_create(
            organization=organization, rule_code=spec.code,
            defaults={"name": spec.name, "description": spec.description,
                      "recommendation": spec.recommendation,
                      "category": spec.category})
        out.append(obj)
    return out


def enabled_rule_codes(organization) -> set[str]:
    ensure_rules(organization)
    return set(JournalAnalyticsRule.objects.filter(
        organization=organization, is_enabled=True).values_list("rule_code", flat=True))


def set_rule_enabled(*, organization, rule_code, enabled: bool):
    if rule_code not in RULES_BY_CODE:
        raise AnalyticsError(f"unknown rule: {rule_code}")
    ensure_rules(organization)
    rule = JournalAnalyticsRule.objects.get(
        organization=organization, rule_code=rule_code)
    rule.is_enabled = bool(enabled)
    rule.save(update_fields=["is_enabled", "updated_at"])
    return rule


# ─────────────────────────────────────────────────────────────────────────────
# Context helpers
# ─────────────────────────────────────────────────────────────────────────────
def _high_value_threshold(engagement):
    """Prefer the 3A materiality profile; fall back to a fixed threshold."""
    try:
        profile = resolve_materiality(engagement)
    except Exception:  # pragma: no cover - defensive
        profile = None
    if profile:
        for key in ("performance", "overall"):
            value = profile.get(key)
            if value:
                return Decimal(str(value)), f"3A {key}"
    return HIGH_VALUE_FALLBACK, "default threshold (no materiality profile)"


def _dormant_gaps(rows) -> dict:
    """Map (account_code, date) → dormant-day gap for reactivated accounts."""
    by_account = defaultdict(list)
    for row in rows:
        d = _row_date(row)
        if row.account_code and d and isinstance(d, datetime.date):
            by_account[row.account_code].append(d)

    gaps = {}
    for account, dates in by_account.items():
        ordered = sorted(set(dates))
        for prev, curr in zip(ordered, ordered[1:]):
            delta = (curr - prev).days
            if delta >= DORMANT_DAYS:
                gaps[(account, curr)] = delta
    return gaps


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────
def run_analytics(gl_import: GeneralLedgerImport, *, actor=None,
                  rule_codes=None) -> JournalAnalyticsRun:
    """Execute the enabled deterministic rules over a GL import's journals.

    Advisory only: results are written to the 7A tables and nowhere else.
    """
    if gl_import.engagement.organization_id != gl_import.organization_id:
        raise ValidationError("cross-tenant analytics denied.")

    engagement = gl_import.engagement
    organization = gl_import.organization

    run = JournalAnalyticsRun.objects.create(
        organization=organization, engagement=engagement,
        general_ledger_import=gl_import,
        status=JournalAnalyticsRun.Status.RUNNING,
        started_at=timezone.now(),
        created_by=actor if getattr(actor, "pk", None) else None)

    warnings, errors = [], []
    started = time.monotonic()
    try:
        rows = list(gl_import.rows.all())
        journals = build_journals(rows)

        selected = set(rule_codes) if rule_codes else enabled_rule_codes(organization)
        unknown = selected - set(RULES_BY_CODE)
        if unknown:
            warnings.append(f"ignored unknown rules: {sorted(unknown)}")
            selected -= unknown
        if not selected:
            warnings.append("no rules enabled — nothing was evaluated.")

        threshold, basis = _high_value_threshold(engagement)
        ctx = {
            "period_end": gl_import.period_end or engagement.period_end,
            "high_value_threshold": threshold,
            "high_value_basis": basis,
            "dormant_gaps": _dormant_gaps(rows),
        }
        if not ctx["period_end"]:
            warnings.append("no period end available — period-end rule skipped.")

        weights = dict(JournalAnalyticsRule.objects.filter(
            organization=organization).values_list("rule_code", "weight"))

        results, executed = [], []
        for spec in RULES:
            if spec.code not in selected:
                continue
            rule_started = time.monotonic()
            try:
                for journal in journals:
                    for hit in spec.fn(journal, ctx) or []:
                        score = min(100, int(spec.base_score
                                             * (weights.get(spec.code, 100) / 100)))
                        account_row = hit["journal"].primary_account
                        results.append(JournalAnalyticsResult(
                            run=run, organization=organization,
                            rule_code=spec.code, rule_name=spec.name,
                            severity=_severity_for(score), score=score,
                            journal_number=hit["journal"].number,
                            account_code=getattr(account_row, "account_code", "") or "",
                            account_name=getattr(account_row, "account_name", "") or "",
                            entered_by=hit["journal"].entered_by or "",
                            description=hit["description"],
                            recommendation=spec.recommendation,
                            amount=hit["amount"] or _ZERO,
                            affected_rows=len(hit["journal"].rows),
                            execution_ms=0,
                            evidence=hit["evidence"]))
            except Exception as exc:  # a broken rule must not kill the run
                errors.append(f"{spec.code}: {exc}")
                continue
            rule_ms = int((time.monotonic() - rule_started) * 1000)
            for r in results:
                if r.rule_code == spec.code and not r.execution_ms:
                    r.execution_ms = rule_ms
            executed.append(spec.code)

        with transaction.atomic():
            JournalAnalyticsResult.objects.bulk_create(results, batch_size=500)
            run.status = JournalAnalyticsRun.Status.COMPLETED
            run.rows_analyzed = len(rows)
            run.journals_analyzed = len(journals)
            run.findings_count = len(results)
            run.rules_executed = executed
            run.warnings = warnings
            run.errors = errors
            run.execution_ms = int((time.monotonic() - started) * 1000)
            run.completed_at = timezone.now()
            run.metadata = {
                "high_value_threshold": str(threshold),
                "high_value_basis": basis,
                "dormant_days": DORMANT_DAYS,
                "period_end": str(ctx["period_end"]) if ctx["period_end"] else None,
                "advisory_only": True,
            }
            run.save()
            build_summary(run)
    except Exception as exc:
        run.status = JournalAnalyticsRun.Status.FAILED
        run.errors = errors + [str(exc)]
        run.execution_ms = int((time.monotonic() - started) * 1000)
        run.completed_at = timezone.now()
        run.save()
        raise
    return run


def build_summary(run: JournalAnalyticsRun) -> JournalAnalyticsSummary:
    """Aggregate a completed run into its denormalised summary."""
    results = list(run.results.all())

    by_rule, by_severity = defaultdict(int), defaultdict(int)
    accounts, users = defaultdict(int), defaultdict(int)
    journal_best = {}

    for r in results:
        by_rule[r.rule_code] += 1
        by_severity[r.severity] += 1
        if r.account_code:
            accounts[r.account_code] += 1
        if r.entered_by:
            users[r.entered_by] += 1
        current = journal_best.get(r.journal_number)
        if current is None or r.score > current:
            journal_best[r.journal_number] = r.score

    def bucket(score):
        sev = _severity_for(score)
        if sev in ("high", "critical"):
            return "high"
        return "medium" if sev == "medium" else "low"

    buckets = defaultdict(int)
    for score in journal_best.values():
        buckets[bucket(score)] += 1

    summary, _created = JournalAnalyticsSummary.objects.get_or_create(
        run=run, defaults={"organization": run.organization})
    summary.organization = run.organization
    summary.total_journals = run.journals_analyzed
    summary.analyzed_journals = run.journals_analyzed
    summary.flagged_journals = len(journal_best)
    summary.high_risk_journals = buckets["high"]
    summary.medium_risk_journals = buckets["medium"]
    summary.low_risk_journals = buckets["low"]
    summary.by_rule = dict(by_rule)
    summary.by_severity = dict(by_severity)
    summary.top_accounts = [{"account_code": a, "count": c} for a, c in
                            sorted(accounts.items(), key=lambda kv: -kv[1])[:10]]
    summary.top_users = [{"entered_by": u, "count": c} for u, c in
                         sorted(users.items(), key=lambda kv: -kv[1])[:10]]
    summary.save()
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard & report (JSON only — no PDF in this phase)
# ─────────────────────────────────────────────────────────────────────────────
def latest_run(*, organization, engagement=None):
    qs = JournalAnalyticsRun.objects.filter(
        organization=organization, status=JournalAnalyticsRun.Status.COMPLETED)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    return qs.order_by("-created_at").first()


def dashboard(*, organization, engagement=None) -> dict:
    """Analytics dashboard payload (advisory)."""
    run = latest_run(organization=organization, engagement=engagement)
    history = JournalAnalyticsRun.objects.filter(organization=organization)
    if engagement is not None:
        history = history.filter(engagement=engagement)
    history = list(history.order_by("-created_at")[:10])

    if run is None:
        return {"has_data": False, "advisory_only": True,
                "total_journals": 0, "analyzed_journals": 0,
                "high_risk_journals": 0, "medium_risk_journals": 0,
                "low_risk_journals": 0, "top_rules": [], "top_accounts": [],
                "top_users": [], "execution_history": _history(history)}

    summary = getattr(run, "summary", None) or build_summary(run)
    top_rules = sorted(summary.by_rule.items(), key=lambda kv: -kv[1])[:10]
    return {
        "has_data": True,
        "advisory_only": True,
        "run_id": str(run.id),
        "total_journals": summary.total_journals,
        "analyzed_journals": summary.analyzed_journals,
        "flagged_journals": summary.flagged_journals,
        "high_risk_journals": summary.high_risk_journals,
        "medium_risk_journals": summary.medium_risk_journals,
        "low_risk_journals": summary.low_risk_journals,
        "top_rules": [{"rule_code": c, "name": RULES_BY_CODE[c].name if c in RULES_BY_CODE else c,
                       "count": n} for c, n in top_rules],
        "top_accounts": summary.top_accounts,
        "top_users": summary.top_users,
        "by_severity": summary.by_severity,
        "execution_history": _history(history),
    }


def _history(runs) -> list[dict]:
    return [{
        "run_id": str(r.id),
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "execution_ms": r.execution_ms,
        "rows_analyzed": r.rows_analyzed,
        "journals_analyzed": r.journals_analyzed,
        "findings_count": r.findings_count,
        "rules_executed": r.rules_executed,
    } for r in runs]


def report(*, run) -> dict:
    """JSON analytics report for one run (no PDF in this phase)."""
    summary = getattr(run, "summary", None) or build_summary(run)
    results = list(run.results.all())

    rule_stats = []
    for code, count in sorted(summary.by_rule.items(), key=lambda kv: -kv[1]):
        spec = RULES_BY_CODE.get(code)
        rule_stats.append({
            "rule_code": code,
            "name": spec.name if spec else code,
            "category": spec.category if spec else "",
            "count": count,
            "recommendation": spec.recommendation if spec else "",
        })

    top_findings = [{
        "rule_code": r.rule_code, "rule_name": r.rule_name,
        "journal_number": r.journal_number, "account_code": r.account_code,
        "severity": r.severity, "score": r.score, "amount": str(r.amount),
        "description": r.description, "recommendation": r.recommendation,
        "affected_rows": r.affected_rows, "evidence": r.evidence,
    } for r in sorted(results, key=lambda x: -x.score)[:50]]

    return {
        "advisory_only": True,
        "note": ("Deterministic analytics for auditor consideration. These are "
                 "not audit findings, are never auto-accepted, and do not "
                 "constitute an audit opinion."),
        "summary": {
            "run_id": str(run.id),
            "status": run.status,
            "engagement": str(run.engagement_id),
            "general_ledger_import": str(run.general_ledger_import_id),
            "rows_analyzed": run.rows_analyzed,
            "journals_analyzed": run.journals_analyzed,
            "findings_count": run.findings_count,
            "execution_ms": run.execution_ms,
            "rules_executed": run.rules_executed,
            "warnings": run.warnings,
            "errors": run.errors,
            "high_risk_journals": summary.high_risk_journals,
            "medium_risk_journals": summary.medium_risk_journals,
            "low_risk_journals": summary.low_risk_journals,
        },
        "rule_statistics": rule_stats,
        "charts": {
            "by_severity": summary.by_severity,
            "by_rule": summary.by_rule,
            "top_accounts": summary.top_accounts,
            "top_users": summary.top_users,
        },
        "top_findings": top_findings,
        "recommendations": [
            {"rule_code": s["rule_code"], "recommendation": s["recommendation"]}
            for s in rule_stats if s["recommendation"]
        ],
    }
