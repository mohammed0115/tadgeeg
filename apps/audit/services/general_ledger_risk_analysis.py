"""Deterministic General Ledger risk analysis (TADGEEG-FIN-AUDIT-2B).

Generates **candidate** risk findings from staged ``GeneralLedgerRow`` data for
one ``GeneralLedgerImport``. Findings are suggestions for an auditor to review,
not conclusions. No AI, no materiality (raw amount thresholds only — temporary
until materiality integration), and nothing is ever written to ``apps.ledger``.

Idempotency: re-running deletes the import's existing ``candidate`` findings and
recreates them; findings a reviewer already acted on (status != candidate) are
preserved and not recreated (matched by deterministic fingerprint).
"""
from __future__ import annotations

import datetime
import hashlib
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.general_ledger_models import (
    GeneralLedgerImport,
    GeneralLedgerRiskFinding,
)

_F = GeneralLedgerRiskFinding
_Cat = _F.Category
_ZERO = Decimal("0")

# Raw amount thresholds (TEMPORARY — replaced by materiality in a later phase).
SIGNIFICANT_AMOUNT = Decimal("10000")
COMMON_THRESHOLDS = (Decimal("10000"), Decimal("50000"), Decimal("100000"))
PERIOD_END_WINDOW_DAYS = 7
# Saudi working-week weekend = Friday(4) & Saturday(5).
WEEKEND_WEEKDAYS = {4, 5}
SENSITIVE_CATEGORIES = {"cash_and_bank", "revenue", "vat_tax", "loans", "equity"}
MANUAL_KEYWORDS = ("manual", "journal entry", "adjustment", "adj ", "reclass",
                   "تسوية", "يدوي", "قيد يدوي", "قيد يومية")

# Base scores per rule (before amount/sensitivity bumps).
_BASE = {
    _Cat.MISSING_DESCRIPTION: 20,
    _Cat.UNMAPPED_ACCOUNT: 35,
    _Cat.ROUND_AMOUNT: 30,
    _Cat.UNUSUAL_TIMING: 30,
    _Cat.PERIOD_END: 45,
    _Cat.MANUAL_ENTRY: 40,
    _Cat.SENSITIVE_ACCOUNT: 45,
    _Cat.THRESHOLD_AVOIDANCE: 55,
    _Cat.DUPLICATE_ENTRY: 60,
    _Cat.UNBALANCED_JOURNAL: 70,
}


def _amount_bump(amount: Decimal) -> int:
    a = abs(amount)
    if a >= Decimal("100000"):
        return 20
    if a >= Decimal("50000"):
        return 12
    if a >= SIGNIFICANT_AMOUNT:
        return 6
    return 0


def _severity_for(score: int) -> str:
    if score <= 30:
        return _F.Severity.LOW
    if score <= 60:
        return _F.Severity.MEDIUM
    if score <= 80:
        return _F.Severity.HIGH
    return _F.Severity.CRITICAL


def _score(category: str, amount: Decimal, *, extra: int = 0) -> int:
    return min(100, _BASE.get(category, 20) + _amount_bump(amount) + extra)


def _fingerprint(import_id, risk_code, row_id, journal_number, account_code, amount) -> str:
    key = f"{import_id}|{risk_code}|{row_id}|{journal_number}|{account_code}|{int(abs(amount) * 100)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _row_date(row):
    return row.transaction_date or row.posting_date


def _row_category(row) -> str:
    return row.mapped_account.mapped_category if row.mapped_account_id else ""


def _is_round(amount: Decimal) -> bool:
    a = abs(amount)
    return a >= SIGNIFICANT_AMOUNT and (a % Decimal("1000") == 0)


def analyze_import(gl_import: GeneralLedgerImport, *, created_by=None) -> dict:
    """Run all deterministic rules over the import's rows. Returns a summary."""
    if gl_import.engagement.organization_id != gl_import.organization_id:
        raise ValidationError("cross-tenant analysis denied.")

    engagement = gl_import.engagement
    organization = gl_import.organization
    period_end = gl_import.period_end or engagement.period_end

    rows = list(gl_import.rows.all())

    # Pre-compute duplicate groups: (date, account_code, debit, credit) seen >1.
    dup_counts: dict[tuple, int] = defaultdict(int)
    for r in rows:
        if r.account_code:
            dup_counts[(_row_date(r), r.account_code, r.debit, r.credit)] += 1

    # Pre-compute per-journal balances for unbalanced-journal findings.
    journal_bal: dict[str, list] = defaultdict(lambda: [_ZERO, _ZERO])
    for r in rows:
        if r.journal_number and r.is_valid:
            journal_bal[r.journal_number][0] += r.debit
            journal_bal[r.journal_number][1] += r.credit

    candidates: list[dict] = []

    def add(row, category, code, title, description, amount, *, extra=0, journal=""):
        score = _score(category, amount, extra=extra)
        candidates.append(dict(
            row=row, journal_number=journal or (row.journal_number if row else ""),
            risk_code=code, risk_title=title, risk_description=description,
            risk_category=category, severity=_severity_for(score), score=score,
            amount_impact=abs(amount),
            account_code=(row.account_code if row else ""),
            account_name=(row.account_name if row else ""),
            mapped_category=(_row_category(row) if row else ""),
            evidence=dict(
                row_number=(row.row_number if row else None),
                debit=str(row.debit) if row else None,
                credit=str(row.credit) if row else None,
                date=str(_row_date(row)) if row and _row_date(row) else None,
            ),
        ))

    for r in rows:
        amount = r.signed_amount if r.signed_amount else (r.debit - r.credit)
        cat = _row_category(r)
        rdate = _row_date(r)

        # A. Missing description
        if len((r.description or "").strip()) < 3:
            add(r, _Cat.MISSING_DESCRIPTION, "GL-RISK-DESC",
                "Missing or too-short description",
                "Journal line has no meaningful description.", amount)

        # B. Unmapped account
        if r.account_code and not r.mapped_account_id:
            add(r, _Cat.UNMAPPED_ACCOUNT, "GL-RISK-UNMAPPED",
                "Unmapped account",
                "Account code is not mapped to an audit category.", amount)

        # C. Round amount
        if _is_round(amount):
            add(r, _Cat.ROUND_AMOUNT, "GL-RISK-ROUND",
                "Large round amount",
                "Entry amount is a large round number.", amount)

        # D. Period-end posting
        if period_end and rdate and isinstance(rdate, datetime.date):
            if 0 <= (period_end - rdate).days < PERIOD_END_WINDOW_DAYS:
                extra = 10 if cat in SENSITIVE_CATEGORIES else 0
                add(r, _Cat.PERIOD_END, "GL-RISK-PERIODEND",
                    "Period-end posting",
                    f"Entry posted within {PERIOD_END_WINDOW_DAYS} days of period end.",
                    amount, extra=extra)

        # E. Weekend / unusual timing (date-based only; no time invented)
        if rdate and isinstance(rdate, datetime.date) and rdate.weekday() in WEEKEND_WEEKDAYS:
            add(r, _Cat.UNUSUAL_TIMING, "GL-RISK-WEEKEND",
                "Weekend posting",
                "Entry dated on a weekend (Fri/Sat).", amount)

        # F. Manual / high-risk source
        haystack = " ".join([
            (r.description or ""), (r.source_system or ""), (r.entered_by or ""),
        ]).lower()
        if any(kw in haystack for kw in MANUAL_KEYWORDS):
            add(r, _Cat.MANUAL_ENTRY, "GL-RISK-MANUAL",
                "Manual journal entry",
                "Entry text/source suggests a manual journal/adjustment.", amount)

        # G. Sensitive account category (with significant amount)
        if cat in SENSITIVE_CATEGORIES and abs(amount) >= SIGNIFICANT_AMOUNT:
            add(r, _Cat.SENSITIVE_ACCOUNT, "GL-RISK-SENSITIVE",
                "Significant posting to a sensitive account",
                f"Significant entry to a {cat} account.", amount, extra=10)

        # H. Threshold avoidance candidate (just below a common threshold)
        a = abs(amount)
        for t in COMMON_THRESHOLDS:
            if t * Decimal("0.95") <= a < t:
                add(r, _Cat.THRESHOLD_AVOIDANCE, "GL-RISK-THRESHOLD",
                    "Amount just below a common threshold",
                    f"Amount is within 5% below {t} (candidate only — not proof).",
                    amount)
                break

        # I. Duplicate journal candidate
        if r.account_code and dup_counts.get((rdate, r.account_code, r.debit, r.credit), 0) > 1:
            add(r, _Cat.DUPLICATE_ENTRY, "GL-RISK-DUP",
                "Possible duplicate entry",
                "Same date, account and amount appears more than once (candidate).",
                amount)

    # J. Unbalanced journal (one finding per unbalanced journal group)
    for jnum, (deb, cred) in journal_bal.items():
        diff = deb - cred
        if abs(diff) > Decimal("0.01"):
            score = _score(_Cat.UNBALANCED_JOURNAL, diff,
                           extra=10 if abs(diff) >= Decimal("50000") else 0)
            candidates.append(dict(
                row=None, journal_number=jnum,
                risk_code="GL-RISK-UNBALANCED",
                risk_title="Unbalanced journal",
                risk_description=f"Journal {jnum} debits != credits (difference {diff}).",
                risk_category=_Cat.UNBALANCED_JOURNAL,
                severity=_severity_for(score), score=score,
                amount_impact=abs(diff), account_code="", account_name="",
                mapped_category="",
                evidence=dict(journal_number=jnum, total_debit=str(deb),
                              total_credit=str(cred), difference=str(diff)),
            ))

    # ── Persist idempotently ────────────────────────────────────────────
    with transaction.atomic():
        # Preserve reviewer-acted findings; replace only candidates.
        reviewed_fps = set(
            _F.objects.filter(general_ledger_import=gl_import)
            .exclude(status=_F.Status.CANDIDATE)
            .values_list("fingerprint", flat=True)
        )
        _F.objects.filter(general_ledger_import=gl_import,
                          status=_F.Status.CANDIDATE).delete()

        to_create: list[_F] = []
        by_severity: dict[str, int] = defaultdict(int)
        by_code: dict[str, int] = defaultdict(int)
        for c in candidates:
            row = c["row"]
            fp = _fingerprint(gl_import.id, c["risk_code"],
                              row.id if row else "", c["journal_number"],
                              c["account_code"], c["amount_impact"])
            if fp in reviewed_fps:
                continue  # an auditor already acted on this exact finding
            to_create.append(_F(
                engagement=engagement, organization=organization,
                general_ledger_import=gl_import, row=row,
                journal_number=c["journal_number"], risk_code=c["risk_code"],
                risk_title=c["risk_title"], risk_description=c["risk_description"],
                risk_category=c["risk_category"], severity=c["severity"],
                score=c["score"], amount_impact=c["amount_impact"],
                account_code=c["account_code"], account_name=c["account_name"],
                mapped_category=c["mapped_category"], evidence_snapshot=c["evidence"],
                fingerprint=fp, status=_F.Status.CANDIDATE,
            ))
            by_severity[c["severity"]] += 1
            by_code[c["risk_code"]] += 1
        _F.objects.bulk_create(to_create)

    return {
        "created": len(to_create),
        "preserved_reviewed": len(reviewed_fps),
        "by_severity": dict(by_severity),
        "by_risk_code": dict(by_code),
        "total_candidates_evaluated": len(candidates),
    }
