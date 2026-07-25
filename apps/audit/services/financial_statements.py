"""Financial Statements review (TADGEEG-FIN-AUDIT-9A · IAS 1).

Derives a Balance Sheet and Income Statement from a staged Trial Balance
(1A/1B) using the existing ``AccountMapping`` classification taxonomy, computes
key ratios, a year-over-year comparison against the prior trial balance, and
deterministic classification-anomaly flags.

REUSE (no duplication): reads ``TrialBalanceImport`` / ``TrialBalanceRow`` /
``AccountMapping`` built in 1A/1B. Nothing here is persisted, uses AI, writes to
``apps.ledger`` or issues an audit opinion — it is a deterministic auditor aid,
always re-derived from the current trial balance.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from apps.audit.trial_balance_models import (
    AccountMapping,
    TrialBalanceImport,
    TrialBalanceRow,
)

_ZERO = Decimal("0")

# ── IAS 1 line grouping, keyed by the AccountMapping.Category taxonomy ────────
_Cat = AccountMapping.Category
ASSET_CATS = [_Cat.CASH_AND_BANK, _Cat.ACCOUNTS_RECEIVABLE, _Cat.INVENTORY,
              _Cat.FIXED_ASSETS, _Cat.OTHER_ASSETS]
CURRENT_ASSET_CATS = [_Cat.CASH_AND_BANK, _Cat.ACCOUNTS_RECEIVABLE,
                      _Cat.INVENTORY, _Cat.OTHER_ASSETS]
LIABILITY_CATS = [_Cat.ACCOUNTS_PAYABLE, _Cat.VAT_TAX, _Cat.LOANS,
                  _Cat.OTHER_LIABILITIES]
CURRENT_LIABILITY_CATS = [_Cat.ACCOUNTS_PAYABLE, _Cat.VAT_TAX, _Cat.OTHER_LIABILITIES]
EQUITY_CATS = [_Cat.EQUITY]
REVENUE_CATS = [_Cat.REVENUE]
EXPENSE_CATS = [_Cat.COST_OF_SALES, _Cat.PAYROLL_EXPENSE, _Cat.OPERATING_EXPENSE,
                _Cat.FINANCE_COST]
OTHER_PL_CATS = [_Cat.OTHER_INCOME_EXPENSE]

# Categories whose normal balance is a DEBIT (assets, expenses).
_DEBIT_NORMAL = set(ASSET_CATS) | set(EXPENSE_CATS)
# Categories whose normal balance is a CREDIT (liabilities, equity, revenue).
_CREDIT_NORMAL = set(LIABILITY_CATS) | set(EQUITY_CATS) | set(REVENUE_CATS)

# A sign anomaly below this (currency) is treated as immaterial noise.
_SIGN_TOLERANCE = Decimal("1")
# Accounting-equation imbalance tolerance.
_EQUATION_TOLERANCE = Decimal("1")

_LABELS = {c.value: c.label for c in _Cat}


class FinancialStatementError(Exception):
    """Raised when statements cannot be derived (e.g. no trial balance)."""


def _net_debit(row: TrialBalanceRow) -> Decimal:
    """Signed net debit for a row (debit-positive). Falls back to closing_balance."""
    nd = (row.closing_debit or _ZERO) - (row.closing_credit or _ZERO)
    if nd == _ZERO:
        return row.closing_balance or _ZERO
    return nd


def _mapping_for(engagement) -> dict:
    """account_code → mapped_category for the engagement."""
    return dict(AccountMapping.objects
                .filter(engagement=engagement)
                .values_list("account_code", "mapped_category"))


def _aggregate(tb_import: TrialBalanceImport, mapping: dict):
    """Return (by_category net-debit dict, list of unmapped rows)."""
    by_cat: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    unmapped = []
    for row in tb_import.rows.all():
        cat = mapping.get(row.account_code) or _Cat.UNKNOWN.value
        if cat == _Cat.UNKNOWN.value:
            unmapped.append(row)
        by_cat[cat] += _net_debit(row)
    return by_cat, unmapped


def _present(cat: str, net_debit: Decimal) -> Decimal:
    """Presentation amount: debit-normal as-is, credit-normal flipped positive."""
    if cat in {c.value for c in _CREDIT_NORMAL} or cat in {c.value for c in OTHER_PL_CATS}:
        return -net_debit
    return net_debit


def _lines(cats, by_cat) -> list[dict]:
    out = []
    for c in cats:
        amount = _present(c.value, by_cat.get(c.value, _ZERO))
        out.append({"category": c.value, "label": c.label, "amount": amount})
    return out


def _total(lines) -> Decimal:
    return sum((l["amount"] for l in lines), _ZERO)


def _ratio(numerator, denominator):
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _build_from_import(tb_import, mapping) -> dict:
    by_cat, unmapped = _aggregate(tb_import, mapping)

    assets = _lines(ASSET_CATS, by_cat)
    liabilities = _lines(LIABILITY_CATS, by_cat)
    equity = _lines(EQUITY_CATS, by_cat)
    revenue = _lines(REVENUE_CATS, by_cat)
    expenses = _lines(EXPENSE_CATS, by_cat)
    other_pl = _lines(OTHER_PL_CATS, by_cat)

    total_assets = _total(assets)
    total_liabilities = _total(liabilities)
    total_equity = _total(equity)
    total_revenue = _total(revenue)
    total_expenses = _total(expenses)
    other_income = _total(other_pl)
    net_profit = total_revenue + other_income - total_expenses
    equity_incl_profit = total_equity + net_profit

    current_assets = sum((_present(c.value, by_cat.get(c.value, _ZERO))
                          for c in CURRENT_ASSET_CATS), _ZERO)
    current_liabilities = sum((_present(c.value, by_cat.get(c.value, _ZERO))
                               for c in CURRENT_LIABILITY_CATS), _ZERO)
    cost_of_sales = _present(_Cat.COST_OF_SALES.value,
                             by_cat.get(_Cat.COST_OF_SALES.value, _ZERO))
    gross_profit = total_revenue - cost_of_sales

    return {
        "import_id": str(tb_import.id),
        "filename": tb_import.original_filename or str(tb_import.id),
        "balance_sheet": {
            "assets": assets, "liabilities": liabilities, "equity": equity,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "equity_incl_profit": equity_incl_profit,
            "liabilities_plus_equity": total_liabilities + equity_incl_profit,
        },
        "income_statement": {
            "revenue": revenue, "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit, "expenses": expenses,
            "other_income": other_income,
            "total_revenue": total_revenue, "total_expenses": total_expenses,
            "net_profit": net_profit,
        },
        "ratios": {
            "current_ratio": _ratio(current_assets, current_liabilities),
            "debt_to_equity": _ratio(total_liabilities, equity_incl_profit),
            "gross_margin_pct": _ratio(gross_profit, total_revenue),
            "net_margin_pct": _ratio(net_profit, total_revenue),
            "return_on_equity_pct": _ratio(net_profit, equity_incl_profit),
        },
        "by_category": {k: _present(k, v) for k, v in by_cat.items()},
        "_unmapped": unmapped,  # internal, stripped before returning to callers
    }


def _anomalies(current: dict, unmapped) -> list[dict]:
    """Deterministic classification / integrity flags (advisory)."""
    flags = []
    bs = current["balance_sheet"]

    # 1. Accounting equation: Assets == Liabilities + Equity (incl. profit).
    imbalance = bs["total_assets"] - bs["liabilities_plus_equity"]
    if abs(imbalance) > _EQUATION_TOLERANCE:
        flags.append({"kind": "equation_imbalance", "severity": "high",
                      "message": f"Balance sheet does not balance by {imbalance}.",
                      "amount": str(imbalance)})

    # 2. Negative equity.
    if bs["equity_incl_profit"] < 0:
        flags.append({"kind": "negative_equity", "severity": "high",
                      "message": "Total equity (incl. profit) is negative.",
                      "amount": str(bs["equity_incl_profit"])})

    # 3. Sign anomalies per category (balance opposite to its normal side).
    for cat, amount in current["by_category"].items():
        if cat in {c.value for c in _DEBIT_NORMAL} and amount < -_SIGN_TOLERANCE:
            flags.append({"kind": "sign_anomaly", "severity": "medium",
                          "message": f"{_LABELS.get(cat, cat)} has an abnormal credit balance.",
                          "amount": str(amount)})
        elif cat in {c.value for c in _CREDIT_NORMAL} and amount < -_SIGN_TOLERANCE:
            flags.append({"kind": "sign_anomaly", "severity": "medium",
                          "message": f"{_LABELS.get(cat, cat)} has an abnormal debit balance.",
                          "amount": str(amount)})

    # 4. Unmapped accounts → cannot be classified into the statements.
    if unmapped:
        flags.append({"kind": "unmapped_accounts", "severity": "medium",
                      "message": f"{len(unmapped)} account(s) are unmapped and excluded "
                                 "from the statements.",
                      "amount": str(len(unmapped)),
                      "accounts": [r.account_code for r in unmapped[:25]]})
    return flags


def _yoy(current: dict, prior: dict | None) -> dict | None:
    """Per-category deltas current vs prior."""
    if prior is None:
        return None
    cur, pri = current["by_category"], prior["by_category"]
    rows = []
    for cat in {c.value for c in _Cat if c != _Cat.UNKNOWN}:
        c_amt, p_amt = cur.get(cat, _ZERO), pri.get(cat, _ZERO)
        if c_amt == _ZERO and p_amt == _ZERO:
            continue
        delta = c_amt - p_amt
        rows.append({
            "category": cat, "label": _LABELS.get(cat, cat),
            "current": c_amt, "prior": p_amt, "delta": delta,
            "delta_pct": _ratio(delta, abs(p_amt)) if p_amt else None,
        })
    rows.sort(key=lambda r: -abs(r["delta"]))
    return {
        "prior_import_id": prior["import_id"],
        "prior_filename": prior["filename"],
        "rows": rows,
        "net_profit_current": current["income_statement"]["net_profit"],
        "net_profit_prior": prior["income_statement"]["net_profit"],
    }


def build_financial_statements(engagement, *, tb_import=None) -> dict:
    """Build the IAS 1 statements + ratios + YoY + anomalies for an engagement.

    Uses the latest completed trial balance unless ``tb_import`` is given.
    """
    imports = list(TrialBalanceImport.objects.filter(engagement=engagement)
                   .order_by("-created_at"))
    if tb_import is not None:
        current_import = tb_import
        prior_import = next((i for i in imports if i.id != tb_import.id), None)
    else:
        current_import = imports[0] if imports else None
        prior_import = imports[1] if len(imports) > 1 else None

    if current_import is None:
        raise FinancialStatementError(
            "no trial balance imported for this engagement.")

    mapping = _mapping_for(engagement)
    current = _build_from_import(current_import, mapping)
    prior = _build_from_import(prior_import, mapping) if prior_import else None

    unmapped = current.pop("_unmapped")
    if prior is not None:
        prior.pop("_unmapped", None)

    return {
        "advisory_only": True,
        "note": ("Derived from the trial balance and account mappings. A "
                 "deterministic auditor aid — not a formal opinion."),
        "engagement": str(engagement.id),
        "statements": current,
        "anomalies": _anomalies(current, unmapped),
        "year_over_year": _yoy(current, prior),
        "imports": [{"id": str(i.id),
                     "filename": i.original_filename or str(i.id),
                     "created_at": i.created_at.isoformat()} for i in imports[:12]],
    }
