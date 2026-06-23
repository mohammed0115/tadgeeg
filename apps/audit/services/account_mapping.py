"""Account mapping service (TADGEEG-FIN-AUDIT-1B).

Deterministically suggests a canonical audit category for each client
trial-balance account, using simple Arabic/English keyword rules on the account
name/code. It is a **classification layer only**: it never calls AI, never
writes to ``apps.ledger``, and never mutates ledger accounts. Existing *manual*
mappings are always preserved.
"""
from __future__ import annotations

from decimal import Decimal

from apps.audit.trial_balance_models import (
    AccountMapping,
    TrialBalanceImport,
)

_Cat = AccountMapping.Category

# Ordered (category, keywords) — first match wins. Keywords are matched
# case-insensitively as substrings against "<account_name> <account_code>".
# More specific categories are listed before broader ones (e.g. VAT before
# generic tax/expense; cost of sales before operating expense).
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (_Cat.VAT_TAX, ("vat", "value added", "tax", "zakat",
                    "ضريبة", "القيمة المضافة", "قيمة مضافة", "زكاة")),
    (_Cat.CASH_AND_BANK, ("cash", "bank", "petty", "نقد", "نقدية", "بنك", "الصندوق", "صندوق")),
    (_Cat.ACCOUNTS_RECEIVABLE, ("receivable", "debtor", "customer", "trade debtor",
                                "عملاء", "مدينون", "ذمم مدينة", "مدينة")),
    (_Cat.INVENTORY, ("inventory", "stock", "goods", "مخزون", "بضاعة", "بضائع")),
    (_Cat.FIXED_ASSETS, ("fixed asset", "property plant", "equipment", "ppe",
                         "depreciation", "أصول ثابتة", "ممتلكات", "معدات", "إهلاك")),
    (_Cat.ACCOUNTS_PAYABLE, ("payable", "creditor", "supplier", "vendor", "trade creditor",
                             "موردين", "دائنون", "ذمم دائنة", "دائنة")),
    (_Cat.LOANS, ("loan", "borrowing", "facility", "overdraft", "قرض", "قروض", "تمويل", "سلفة")),
    (_Cat.EQUITY, ("equity", "capital", "share", "retained earning", "reserve",
                   "حقوق الملكية", "رأس المال", "راس المال", "رأس مال", "احتياطي", "أرباح مبقاة")),
    (_Cat.REVENUE, ("revenue", "sales", "income from", "turnover",
                    "مبيعات", "إيرادات", "ايرادات", "الإيراد")),
    (_Cat.COST_OF_SALES, ("cost of sales", "cost of goods", "cogs", "purchases",
                          "تكلفة المبيعات", "تكلفة البضاعة", "مشتريات")),
    (_Cat.PAYROLL_EXPENSE, ("salary", "salaries", "payroll", "wage", "staff cost",
                            "رواتب", "أجور", "اجور", "مرتبات", "تكاليف الموظفين")),
    (_Cat.FINANCE_COST, ("finance cost", "interest expense", "bank charge",
                         "تكاليف تمويل", "فوائد", "مصاريف بنكية", "عمولات بنكية")),
    (_Cat.OPERATING_EXPENSE, ("expense", "rent", "utilities", "marketing", "admin",
                              "مصروف", "مصاريف", "إيجار", "ايجار", "تشغيل")),
]


def _normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def suggest_category(account_name: str = "", account_code: str = "") -> tuple[str, Decimal]:
    """Return (category, confidence). Unknown → low confidence."""
    haystack = _normalize(f"{account_name} {account_code}")
    if not haystack:
        return _Cat.UNKNOWN, Decimal("0.000")
    for category, keywords in _RULES:
        for kw in keywords:
            if kw in haystack:
                return category, Decimal("0.700")
    return _Cat.UNKNOWN, Decimal("0.000")


def generate_mappings_from_import(import_batch: TrialBalanceImport, *, created_by=None) -> dict:
    """Create missing AccountMapping rows for each distinct account in an import.

    Preserves any existing mapping for an (engagement, account_code) — manual or
    otherwise — and only creates rows for codes that are not yet mapped. Never
    touches the ledger.

    Returns a small summary dict.
    """
    engagement = import_batch.engagement
    organization = import_batch.organization

    existing_codes = set(
        AccountMapping.objects
        .filter(engagement=engagement)
        .values_list("account_code", flat=True)
    )

    # Distinct (code, name) from the staged rows, first-seen name wins.
    seen: dict[str, str] = {}
    for code, name in (import_batch.rows
                       .exclude(account_code="")
                       .values_list("account_code", "account_name")):
        seen.setdefault(code, name or "")

    created = 0
    by_category: dict[str, int] = {}
    new_rows: list[AccountMapping] = []
    for code, name in seen.items():
        if code in existing_codes:
            continue
        category, confidence = suggest_category(name, code)
        by_category[category] = by_category.get(category, 0) + 1
        new_rows.append(AccountMapping(
            engagement=engagement,
            organization=organization,
            account_code=code,
            account_name=name[:255],
            mapped_category=category,
            mapping_source=AccountMapping.Source.RULE_BASED,
            confidence=confidence,
            created_by=created_by,
        ))
        created += 1

    AccountMapping.objects.bulk_create(new_rows)

    return {
        "created": created,
        "skipped_existing": len(existing_codes & set(seen.keys())),
        "distinct_accounts": len(seen),
        "by_category": by_category,
    }
