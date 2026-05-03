"""
Trial balance + GL ledger reports — Phase 7.1.

Both reports run as a single SQL aggregation per call, so they remain
fast even with hundreds of thousands of journal lines (PostgreSQL
indexes on `entry__entry_date` and `account` carry the heavy lifting).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import F, Q, Sum

from apps.ledger.models import Account, JournalEntry, JournalLine


def trial_balance(organization, *,
                  as_of: Optional[date] = None,
                  base_currency_only: bool = True) -> list[dict]:
    """One row per account with debit + credit + net balance up to ``as_of``.

    Voided entries are excluded — they're already reversed by their
    compensating entry, so counting both would double-zero the balance.
    """
    qs = JournalLine.objects.filter(
        entry__organization=organization,
        entry__status=JournalEntry.Status.POSTED,
    )
    if as_of:
        qs = qs.filter(entry__entry_date__lte=as_of)

    debit_field  = "base_debit"  if base_currency_only else "debit"
    credit_field = "base_credit" if base_currency_only else "credit"

    agg = (
        qs.values("account_id", "account__code", "account__name",
                  "account__account_type")
          .annotate(
              total_debit=Sum(debit_field, default=Decimal("0")),
              total_credit=Sum(credit_field, default=Decimal("0")),
          )
          .order_by("account__code")
    )

    out: list[dict] = []
    grand_d = Decimal("0")
    grand_c = Decimal("0")
    for row in agg:
        d = Decimal(str(row["total_debit"] or 0))
        c = Decimal(str(row["total_credit"] or 0))
        net = d - c
        # For credit-normal accounts, flip the sign so the displayed
        # balance is intuitive (a positive number means "more credit").
        normal_side_credit = row["account__account_type"] in {
            "liability", "equity", "revenue",
        }
        balance = (-net if normal_side_credit else net)
        out.append({
            "account_id":   str(row["account_id"]),
            "code":         row["account__code"],
            "name":         row["account__name"],
            "account_type": row["account__account_type"],
            "debit":        float(d.quantize(Decimal("0.01"))),
            "credit":       float(c.quantize(Decimal("0.01"))),
            "balance":      float(balance.quantize(Decimal("0.01"))),
            "side":         "credit" if normal_side_credit else "debit",
        })
        grand_d += d
        grand_c += c

    return [{
        "rows":        out,
        "totals": {
            "debit":  float(grand_d.quantize(Decimal("0.01"))),
            "credit": float(grand_c.quantize(Decimal("0.01"))),
            "diff":   float((grand_d - grand_c).quantize(Decimal("0.01"))),
            "is_balanced": grand_d == grand_c,
        },
    }]


def general_ledger(organization, account_code: str, *,
                   from_date: Optional[date] = None,
                   to_date: Optional[date] = None,
                   limit: int = 500) -> dict:
    """Per-account ledger with a running balance.

    Useful for drill-down from the trial balance: click the account row,
    see every entry that hit it inside the window, plus the running
    balance after each line."""
    account = Account.objects.filter(
        organization=organization, code=account_code,
    ).first()
    if not account:
        return {"account": None, "lines": [], "opening_balance": 0,
                "closing_balance": 0}

    base = JournalLine.objects.filter(
        entry__organization=organization,
        entry__status=JournalEntry.Status.POSTED,
        account=account,
    )

    # Opening balance — everything posted strictly before ``from_date``.
    # When the caller doesn't specify a window (``from_date is None``), the
    # opening balance is *zero* — every line in the account belongs to the
    # window and the running balance starts from scratch. The pre-fix code
    # summed the entire account into both opening AND window, double-counting
    # every line.
    if from_date:
        opening_qs = base.filter(entry__entry_date__lt=from_date)
        opening_d = opening_qs.aggregate(s=Sum("base_debit"))["s"]  or Decimal("0")
        opening_c = opening_qs.aggregate(s=Sum("base_credit"))["s"] or Decimal("0")
        opening = opening_d - opening_c
    else:
        opening = Decimal("0")

    window = base
    if from_date:
        window = window.filter(entry__entry_date__gte=from_date)
    if to_date:
        window = window.filter(entry__entry_date__lte=to_date)

    rows: list[dict] = []
    running = opening
    for li in (window.select_related("entry").order_by("entry__entry_date",
                                                       "entry__entry_number",
                                                       "line_number")[:limit]):
        d = Decimal(str(li.base_debit or 0))
        c = Decimal(str(li.base_credit or 0))
        running = running + d - c
        rows.append({
            "entry_number": li.entry.entry_number,
            "entry_date":   li.entry.entry_date.isoformat(),
            "description":  li.entry.description,
            "reference":    li.entry.reference,
            "source":       li.entry.source,
            "debit":        float(d.quantize(Decimal("0.01"))),
            "credit":       float(c.quantize(Decimal("0.01"))),
            "running_balance": float(running.quantize(Decimal("0.01"))),
        })

    return {
        "account": {
            "id":           str(account.id),
            "code":         account.code,
            "name":         account.name,
            "account_type": account.account_type,
        },
        "from_date":       from_date.isoformat() if from_date else None,
        "to_date":         to_date.isoformat()   if to_date   else None,
        "opening_balance": float(opening.quantize(Decimal("0.01"))),
        "closing_balance": float(running.quantize(Decimal("0.01"))),
        "lines":           rows,
        "row_count":       len(rows),
    }
