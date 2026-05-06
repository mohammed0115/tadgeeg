"""
GL posting orchestration — Phase 7.1.

  • ``ensure_default_accounts(org)`` — seed the chart-of-accounts on first
    use so every org has the standard handful of accounts (AR/AP/Cash/
    VAT-Input/VAT-Output/Revenue/Expense) the invoice/payment posters need.
  • ``post_invoice_to_gl(invoice, …)`` — produce the canonical journal
    entry for an invoice. Balanced by construction.
  • ``post_bank_payment_to_gl(transaction, invoice)`` — when a bank
    debit is reconciled to a payable invoice, post the AP/Cash leg.
  • ``void_entry(entry, user)`` — generate a compensating entry that
    reverses ``entry`` instead of editing it (legal-evidence rule).
  • ``get_or_create_fx_rate(...)`` + ``convert_to_base(...)`` — the
    multi-currency primitives the poster pipes amounts through.

The poster is idempotent: pass the same ``idempotency_key`` twice and
the second call returns the first entry instead of double-posting.
This lets a webhook retry (or a Celery worker re-run) without
producing duplicate accruals.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.db import models, transaction
from django.utils import timezone

from apps.ledger.models import (
    Account, ExchangeRate, JournalEntry, JournalLine,
)

logger = logging.getLogger("finai.ledger")


# ─────────────────────────────────────────────────────────────────────────────
# Default chart of accounts
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CHART = [
    # (code, name, type, normal_side handled by type)
    ("1000", "Assets",                          "asset"),
    ("1100", "Cash & Cash Equivalents",         "asset"),
    ("1110", "Cash on Hand",                    "asset"),
    ("1120", "Bank — Operating",                "asset"),
    ("1200", "Accounts Receivable",             "asset"),
    ("1300", "Inventory",                       "asset"),
    ("1400", "Prepaid Expenses",                "asset"),
    ("1500", "Fixed Assets",                    "asset"),

    ("2000", "Liabilities",                     "liability"),
    ("2100", "Accounts Payable",                "liability"),
    ("2200", "VAT Output (Sales)",              "liability"),
    ("2300", "Accrued Expenses",                "liability"),

    ("1250", "VAT Input (Purchases)",           "asset"),  # input VAT is recoverable

    ("3000", "Equity",                          "equity"),
    ("3100", "Owner's Capital",                 "equity"),
    ("3200", "Retained Earnings",               "equity"),

    ("4000", "Revenue",                         "revenue"),
    ("4100", "Sales Revenue",                   "revenue"),
    ("4200", "Service Revenue",                 "revenue"),

    ("5000", "Expenses",                        "expense"),
    ("5100", "Cost of Goods Sold",              "expense"),
    ("5200", "Operating Expenses",              "expense"),
    ("5210", "Office Supplies",                 "expense"),
    ("5220", "Rent Expense",                    "expense"),
    ("5230", "Utilities",                       "expense"),
    ("5300", "Bank Charges",                    "expense"),
    ("5400", "FX Gain/Loss",                    "expense"),
]


def ensure_default_accounts(organization) -> dict:
    """Idempotently create every default account that's missing.

    Returns ``{created, total}`` so the caller (UI / migrations / first
    upload) can show a "12 accounts seeded" message.
    """
    created = 0
    for code, name, acct_type in DEFAULT_CHART:
        _, was_created = Account.objects.get_or_create(
            organization=organization, code=code,
            defaults={"name": name, "account_type": acct_type, "is_active": True},
        )
        if was_created:
            created += 1
    total = Account.objects.filter(organization=organization).count()
    return {"created": created, "total": total}


def get_account(organization, code: str) -> Optional[Account]:
    return Account.objects.filter(organization=organization, code=code).first()


# ─────────────────────────────────────────────────────────────────────────────
# Multi-currency
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_fx_rate(organization, *,
                          from_currency: str, to_currency: str,
                          rate_date: date,
                          fallback_rate: Decimal = Decimal("1")) -> ExchangeRate:
    """Resolve a rate. If we don't have one for the exact date, fall back
    to the most-recent prior date. Last resort is the supplied
    ``fallback_rate`` so posting never blocks on a missing rate.
    """
    if from_currency == to_currency:
        return ExchangeRate(
            organization=organization,
            from_currency=from_currency, to_currency=to_currency,
            rate=Decimal("1"), rate_date=rate_date, source="identity",
        )

    exact = ExchangeRate.objects.filter(
        organization=organization,
        from_currency=from_currency, to_currency=to_currency,
        rate_date=rate_date,
    ).first()
    if exact:
        return exact

    nearest = (
        ExchangeRate.objects
        .filter(organization=organization,
                from_currency=from_currency, to_currency=to_currency,
                rate_date__lte=rate_date)
        .order_by("-rate_date").first()
    )
    if nearest:
        return nearest

    # Persist a placeholder so subsequent postings see it and the auditor
    # can fix it later. Marking source='fallback' lets the dashboard flag
    # entries that posted under an estimated rate.
    return ExchangeRate.objects.create(
        organization=organization,
        from_currency=from_currency, to_currency=to_currency,
        rate=fallback_rate, rate_date=rate_date, source="fallback",
    )


def convert_to_base(amount: Decimal, *, fx_rate: Decimal) -> Decimal:
    """Multiply by ``fx_rate`` and quantise to 4dp."""
    if amount is None:
        return Decimal("0")
    return (Decimal(str(amount)) * Decimal(str(fx_rate))).quantize(Decimal("0.0001"))


# ─────────────────────────────────────────────────────────────────────────────
# Entry posting
# ─────────────────────────────────────────────────────────────────────────────

def _next_entry_number(organization) -> str:
    year = timezone.now().year
    prefix = f"JE-{year}-"
    last = (
        JournalEntry.objects
        .filter(organization=organization, entry_number__startswith=prefix)
        .order_by("-entry_number").first()
    )
    if not last:
        return f"{prefix}00001"
    try:
        seq = int(last.entry_number.rsplit("-", 1)[-1])
    except ValueError:
        seq = 0
    return f"{prefix}{seq + 1:05d}"


@transaction.atomic
def post_entry(*,
               organization,
               entry_date: date,
               description: str,
               lines: list[dict],
               reference: str = "",
               source: str = JournalEntry.Source.MANUAL,
               source_object_id: str = "",
               currency: str = "SAR",
               base_currency: str = "SAR",
               idempotency_key: str = "",
               created_by=None,
               post_immediately: bool = True) -> JournalEntry:
    """Create + balance-check + persist a journal entry.

    ``lines`` is a list of dicts:
      ``{"account_code": "1200", "debit": "1150", "description": "..."}`` or
      ``{"account_code": "4100", "credit": "1000", "cost_center": "..."}``.

    Raises ``ValueError`` if:
      • ``lines`` is empty
      • a referenced account doesn't exist for this org
      • a line has both debit and credit (or neither)
      • totals don't balance after FX conversion
    """
    # Idempotency check — a repeat call with the same key returns the
    # original entry instead of creating a duplicate.
    if idempotency_key:
        existing = JournalEntry.objects.filter(
            organization=organization, idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing

    if not lines:
        raise ValueError("at least one line is required")

    # Phase 7.2 — period guard. If the org has set up periods, the
    # entry_date must fall inside an OPEN one. Orgs that never created
    # periods get the legacy "always open" behaviour, so adopting period
    # close is opt-in.
    period = _find_period_for(organization, entry_date)
    if period is not None and not period.is_open:
        raise ValueError(
            f"period '{period.name}' is {period.status} — "
            f"cannot post into a non-open period"
        )

    fx = get_or_create_fx_rate(
        organization=organization,
        from_currency=currency, to_currency=base_currency,
        rate_date=entry_date,
    )
    fx_rate = fx.rate

    # Build the entry header (we save first so lines can FK to it).
    entry = JournalEntry.objects.create(
        organization=organization,
        entry_number=_next_entry_number(organization),
        entry_date=entry_date,
        description=description[:255],
        reference=reference[:100],
        source=source,
        source_object_id=str(source_object_id or ""),
        currency=currency,
        base_currency=base_currency,
        fx_rate=fx_rate,
        status=JournalEntry.Status.DRAFT,
        idempotency_key=idempotency_key,
        created_by=created_by,
    )

    total_d = Decimal("0")
    total_c = Decimal("0")
    for idx, ln in enumerate(lines, start=1):
        code = ln.get("account_code")
        if not code:
            raise ValueError(f"line {idx}: account_code is required")

        account = get_account(organization, code)
        if account is None:
            raise ValueError(f"line {idx}: account '{code}' not found")

        debit  = Decimal(str(ln.get("debit", 0) or 0))
        credit = Decimal(str(ln.get("credit", 0) or 0))
        if debit < 0 or credit < 0:
            raise ValueError(f"line {idx}: amounts must be non-negative")
        if (debit > 0) == (credit > 0):
            raise ValueError(
                f"line {idx}: exactly one of debit/credit must be > 0"
            )

        JournalLine.objects.create(
            entry=entry, line_number=idx,
            account=account,
            debit=debit, credit=credit,
            base_debit=convert_to_base(debit, fx_rate=fx_rate),
            base_credit=convert_to_base(credit, fx_rate=fx_rate),
            description=str(ln.get("description") or ""),
            cost_center=str(ln.get("cost_center") or ""),
            project_code=str(ln.get("project_code") or ""),
        )
        total_d += debit
        total_c += credit

    if total_d != total_c:
        raise ValueError(
            f"entry not balanced: debits {total_d} ≠ credits {total_c}"
        )

    if post_immediately:
        entry.status = JournalEntry.Status.POSTED
        entry.posted_at = timezone.now()
        # Saving with status=POSTED triggers the HashChainMixin pre_save
        # signal, which assigns the chain hash. From this point on the
        # entry's payload (number, date, description) is immutable.
        entry.save()

    return entry


# ─────────────────────────────────────────────────────────────────────────────
# Domain-specific posters
# ─────────────────────────────────────────────────────────────────────────────

def post_invoice_to_gl(invoice, *,
                       direction: str = "purchase",
                       created_by=None,
                       post_immediately: bool = True) -> JournalEntry:
    """Create the standard accrual entry for an invoice.

    Direction = ``"purchase"`` (default — accounts payable):
        DR  5200 Operating Expenses        net
        DR  1250 VAT Input                 vat
            CR  2100 Accounts Payable      gross

    Direction = ``"sale"`` (revenue + AR):
        DR  1200 Accounts Receivable       gross
            CR  4100 Sales Revenue         net
            CR  2200 VAT Output            vat
    """
    org = invoice.organization
    ensure_default_accounts(org)

    subtotal = Decimal(str(invoice.subtotal or 0))
    vat      = Decimal(str(invoice.vat_amount or 0))
    total    = Decimal(str(invoice.total_amount or 0))
    if total == 0:
        raise ValueError("invoice has no total — cannot post")

    # Most invoices ship with subtotal+vat=total; if any pair is zero
    # we infer the third so partial extracts still post cleanly.
    if subtotal == 0 and vat == 0:
        subtotal, vat = total, Decimal("0")
    elif subtotal == 0:
        subtotal = total - vat
    elif total == 0:
        total = subtotal + vat

    base_currency = "SAR"
    invoice_currency = invoice.currency or base_currency
    entry_date = invoice.invoice_date or timezone.now().date()
    idem = f"invoice:{invoice.id}:{direction}"

    if direction == "sale":
        lines = [
            {"account_code": "1200", "debit":  total,  "description": "Receivable"},
            {"account_code": "4100", "credit": subtotal, "description": "Revenue"},
        ]
        if vat > 0:
            lines.append({"account_code": "2200", "credit": vat,
                          "description": "VAT Output"})
        description = f"Sale invoice {invoice.invoice_number or str(invoice.id)[:8]}"
    else:
        lines = [
            {"account_code": "5200", "debit": subtotal, "description": "Expense"},
        ]
        if vat > 0:
            lines.append({"account_code": "1250", "debit": vat,
                          "description": "VAT Input"})
        lines.append({"account_code": "2100", "credit": total,
                      "description": "Payable"})
        description = f"Purchase invoice {invoice.invoice_number or str(invoice.id)[:8]} — {invoice.vendor_name or '-'}"

    return post_entry(
        organization=org, entry_date=entry_date,
        description=description, reference=invoice.invoice_number or "",
        source=JournalEntry.Source.INVOICE,
        source_object_id=str(invoice.id),
        currency=invoice_currency, base_currency=base_currency,
        idempotency_key=idem, created_by=created_by,
        post_immediately=post_immediately,
        lines=lines,
    )


def post_bank_payment_to_gl(transaction_row, invoice=None, *,
                            cash_account_code: str = "1120",
                            ap_account_code: str = "2100",
                            ar_account_code: str = "1200",
                            created_by=None) -> JournalEntry:
    """Post a bank-side leg.

    Debit transaction (we paid a vendor):
        DR  AP                       — clears the payable
            CR  Bank Operating       — cash out

    Credit transaction (a customer paid us):
        DR  Bank Operating           — cash in
            CR  AR                   — clears the receivable
    """
    org = transaction_row.account.connection.organization
    ensure_default_accounts(org)

    amount = Decimal(str(transaction_row.amount))
    when   = transaction_row.posted_at.date() if transaction_row.posted_at else timezone.now().date()
    direction = transaction_row.direction
    idem = f"bank:{transaction_row.id}"
    ref  = transaction_row.reference or transaction_row.external_id

    if direction == "debit":
        lines = [
            {"account_code": ap_account_code,   "debit":  amount},
            {"account_code": cash_account_code, "credit": amount},
        ]
        desc = f"Bank payment to {transaction_row.counterparty[:40]}"
    else:
        lines = [
            {"account_code": cash_account_code, "debit":  amount},
            {"account_code": ar_account_code,   "credit": amount},
        ]
        desc = f"Bank receipt from {transaction_row.counterparty[:40]}"

    return post_entry(
        organization=org, entry_date=when,
        description=desc, reference=ref,
        source=JournalEntry.Source.BANK,
        source_object_id=str(transaction_row.id),
        currency=transaction_row.currency or "SAR",
        idempotency_key=idem, created_by=created_by,
        lines=lines,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Voiding (compensation) — never edit a posted entry
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def void_entry(entry: JournalEntry, *, user=None,
               reason: str = "") -> JournalEntry:
    """Generate a compensating entry that reverses ``entry``.

    The original *stays POSTED* — its lines are still part of the trial
    balance. The compensation is also POSTED, with mirrored debits and
    credits, so the two entries net to zero across every account they
    touched. Updating the FK pointer (``voided_by_entry``) is allowed
    because that field is *not* part of ``_chain_payload`` — only the
    immutable fields the chain commits to are protected.

    SAP and Oracle work the same way: a posted entry is forever, you only
    ever post its mirror.
    """
    if entry.voided_by_entry_id:
        return entry.voided_by_entry  # already voided — return existing void

    reverse_lines = []
    for li in entry.lines.order_by("line_number"):
        if li.debit > 0:
            reverse_lines.append({
                "account_code": li.account.code,
                "credit": li.debit,
                "description": f"void {li.description}"[:255],
            })
        else:
            reverse_lines.append({
                "account_code": li.account.code,
                "debit": li.credit,
                "description": f"void {li.description}"[:255],
            })

    void = post_entry(
        organization=entry.organization,
        entry_date=timezone.now().date(),
        description=f"VOID {entry.entry_number}: {reason or entry.description}"[:255],
        reference=entry.entry_number,
        source=JournalEntry.Source.SYSTEM,
        source_object_id=str(entry.id),
        currency=entry.currency, base_currency=entry.base_currency,
        idempotency_key=f"void:{entry.id}",
        created_by=user,
        post_immediately=True,
        lines=reverse_lines,
    )

    # Original stays POSTED so it's still part of the trial balance — the
    # compensating entry that follows it nets each account back to zero.
    entry.voided_at = timezone.now()
    entry.voided_by_entry = void
    entry.save(update_fields=["voided_at", "voided_by_entry", "updated_at"])
    return void


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.2 — Accounting periods + period-close engine
# ─────────────────────────────────────────────────────────────────────────────

from calendar import monthrange


def _find_period_for(organization, on_date: date):
    """Return the period that covers ``on_date``, or None if no periods exist.

    Imported lazily so the module-level fields don't pull AccountingPeriod
    before the migration runs.
    """
    from apps.ledger.models import AccountingPeriod
    return AccountingPeriod.objects.filter(
        organization=organization,
        start_date__lte=on_date,
        end_date__gte=on_date,
    ).first()


def ensure_periods_for_year(organization, fiscal_year: int) -> dict:
    """Create the 12 monthly periods for ``fiscal_year`` if missing.

    Idempotent — calling twice creates nothing new on the second run.
    Plays nicely with calendar fiscal years; orgs that follow a different
    fiscal year start (April / July) override start/end on each period
    after creation.
    """
    from apps.ledger.models import AccountingPeriod

    created = 0
    for month in range(1, 13):
        last_day = monthrange(fiscal_year, month)[1]
        _, was_created = AccountingPeriod.objects.get_or_create(
            organization=organization,
            fiscal_year=fiscal_year, period_number=month,
            defaults={
                "name":       f"{fiscal_year}-{month:02d}",
                "start_date": date(fiscal_year, month, 1),
                "end_date":   date(fiscal_year, month, last_day),
                "status":     AccountingPeriod.Status.OPEN,
            },
        )
        if was_created:
            created += 1
    total = AccountingPeriod.objects.filter(
        organization=organization, fiscal_year=fiscal_year,
    ).count()
    return {"created": created, "total": total, "fiscal_year": fiscal_year}


@transaction.atomic
def close_period(period, *, user=None,
                 fx_revaluation: bool = True) -> dict:
    """Close a period — block further postings and (optionally) book the
    FX-revaluation entry that brings every foreign-currency balance to
    today's rate.

    Returns a summary the caller / API surface can show to the user:
    ``{ok, period, entries_count, fx_revaluation_entry_id}``.
    """
    from apps.ledger.models import AccountingPeriod

    if period.status not in {AccountingPeriod.Status.OPEN,
                             AccountingPeriod.Status.CLOSING}:
        raise ValueError(f"cannot close a {period.status} period")

    period.status = AccountingPeriod.Status.CLOSING
    period.save(update_fields=["status", "updated_at"])

    summary = {
        "ok": False,
        "period_id": str(period.id),
        "period_name": period.name,
        "entries_count": JournalEntry.objects.filter(
            organization=period.organization,
            entry_date__gte=period.start_date,
            entry_date__lte=period.end_date,
            status=JournalEntry.Status.POSTED,
        ).count(),
        "fx_revaluation_entry_id": None,
    }

    # FX revaluation: re-translate every foreign-currency balance at the
    # rate effective on period.end_date. Skipping for now if the org has
    # no FX rates on file — keeps the flow runnable in single-currency setups.
    if fx_revaluation:
        revaluation_id = _post_fx_revaluation(period, user=user)
        summary["fx_revaluation_entry_id"] = (
            str(revaluation_id) if revaluation_id else None
        )

    period.status = AccountingPeriod.Status.CLOSED
    period.closed_at = timezone.now()
    period.closed_by = user
    period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    summary["ok"] = True
    return summary


@transaction.atomic
def reopen_period(period, *, user=None, reason: str = "") -> None:
    """Reopen a CLOSED period (admin only). LOCKED periods cannot reopen."""
    from apps.ledger.models import AccountingPeriod
    if period.status == AccountingPeriod.Status.LOCKED:
        raise ValueError("locked periods cannot be reopened")
    if period.status != AccountingPeriod.Status.CLOSED:
        raise ValueError(f"cannot reopen a {period.status} period")
    period.status = AccountingPeriod.Status.OPEN
    period.notes = (period.notes + f"\nReopened {timezone.now():%Y-%m-%d %H:%M} "
                    f"by {user.email if user else '?'}: {reason or '-'}").strip()
    period.closed_at = None
    period.closed_by = None
    period.save(update_fields=["status", "notes", "closed_at", "closed_by", "updated_at"])


@transaction.atomic
def lock_period(period, *, user=None) -> None:
    """One-way lock — period cannot be reopened after this.

    Reserved for the auditor's final sign-off on a closed period.
    """
    from apps.ledger.models import AccountingPeriod
    if period.status != AccountingPeriod.Status.CLOSED:
        raise ValueError(f"only CLOSED periods can be locked (got {period.status})")
    period.status = AccountingPeriod.Status.LOCKED
    period.locked_at = timezone.now()
    period.locked_by = user
    period.save(update_fields=["status", "locked_at", "locked_by", "updated_at"])


def _post_fx_revaluation(period, *, user=None):
    """Compute the unrealised FX gain/loss across every foreign-currency
    journal line in the period and post the offsetting entry.

    Returns the new entry id, or None if there's nothing to revalue.
    """
    from collections import defaultdict
    from apps.ledger.models import JournalLine

    org = period.organization

    # Aggregate by currency: sum of (debit - credit) at original rate ×
    # the rate effective at end_date minus the per-line base amount.
    movements = (
        JournalLine.objects
        .filter(
            entry__organization=org,
            entry__status=JournalEntry.Status.POSTED,
            entry__entry_date__gte=period.start_date,
            entry__entry_date__lte=period.end_date,
        )
        .exclude(entry__currency=models.F("entry__base_currency"))
        .select_related("entry")
    )

    # Build per-(currency, account) net amounts.
    by_pair: dict = defaultdict(lambda: {"src": Decimal("0"), "base": Decimal("0")})
    for li in movements:
        key = (li.entry.currency, li.account_id)
        sign_d = Decimal(str(li.debit or 0)) - Decimal(str(li.credit or 0))
        sign_b = Decimal(str(li.base_debit or 0)) - Decimal(str(li.base_credit or 0))
        by_pair[key]["src"]  += sign_d
        by_pair[key]["base"] += sign_b
        by_pair[key]["account_id"] = li.account_id

    if not by_pair:
        return None

    base_currency = "SAR"
    fx_account = get_account(org, "5400")  # FX Gain/Loss
    if fx_account is None:
        return None

    reval_lines: list[dict] = []
    total_diff = Decimal("0")

    for (currency, account_id), agg in by_pair.items():
        rate = get_or_create_fx_rate(
            organization=org,
            from_currency=currency, to_currency=base_currency,
            rate_date=period.end_date,
        ).rate
        new_base = (agg["src"] * rate).quantize(Decimal("0.0001"))
        diff = (new_base - agg["base"]).quantize(Decimal("0.0001"))
        if diff == 0:
            continue
        total_diff += diff

        # The account's balance in base currency moves by ``diff``.
        # Asset/expense net gain → DR account, CR FX P/L; loss → reverse.
        from apps.ledger.models import Account as _Acct
        target = _Acct.objects.get(pk=account_id)
        if diff > 0:
            reval_lines.append({"account_code": target.code, "debit":  diff})
        else:
            reval_lines.append({"account_code": target.code, "credit": -diff})

    if not reval_lines:
        return None

    # Single offsetting line on FX P/L so the entry balances.
    if total_diff > 0:
        reval_lines.append({"account_code": "5400", "credit": total_diff})
    else:
        reval_lines.append({"account_code": "5400", "debit":  -total_diff})

    entry = post_entry(
        organization=org, entry_date=period.end_date,
        description=f"FX revaluation — period {period.name}",
        source=JournalEntry.Source.SYSTEM,
        source_object_id=str(period.id),
        currency=base_currency, base_currency=base_currency,
        idempotency_key=f"fx-reval:{period.id}",
        created_by=user, lines=reval_lines,
    )
    return entry.id
