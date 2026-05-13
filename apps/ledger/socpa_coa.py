"""SOCPA-aligned Chart of Accounts (Saudi).

The IFRS-baseline chart in ``apps/ledger/services.DEFAULT_CHART`` is
fine for an international SaaS, but Saudi auditors expect the **SOCPA
mandatory line-items** to be present and named consistently with the
filing template that ZATCA / Zakat returns reference.

This module provides an extension chart that overlays the SOCPA-
mandatory accounts. Call ``ensure_socpa_chart(organization)`` to seed
both the IFRS base and the SOCPA overlay.

Where the standard SOCPA template differs from the IFRS baseline:

  • Zakat & Income Tax — Saudi entities separate **Zakat** (religious
    levy on Saudi/GCC ownership) from **Income Tax** (foreign
    ownership) in equity. We add explicit accounts.
  • End-of-Service Indemnity (EOSI) — Saudi labour law mandates a
    severance liability per Article 84/85 — separate account.
  • Withholding Tax (WHT) — payments to non-residents trigger WHT —
    separate liability account.

The codes follow SOCPA's published numbering when one exists; otherwise
we extend the IFRS hierarchy.
"""
from __future__ import annotations

from apps.ledger.models import Account


# Each row: (code, en_name, ar_name, account_type)
SOCPA_OVERLAY: tuple[tuple[str, str, str, str], ...] = (
    # ─── Assets (extras) ──────────────────────────────────────────────────────
    ("1130", "Bank — Saudi Riyal Account", "حساب البنك بالريال السعودي", "asset"),
    ("1140", "Bank — Foreign Currency",    "حساب البنك بالعملات الأجنبية", "asset"),
    ("1260", "Zakat & Tax Refund Receivable", "الزكاة والضرائب المستردة", "asset"),

    # ─── Liabilities (extras) ─────────────────────────────────────────────────
    ("2400", "End-of-Service Indemnity (EOSI)",
            "مكافأة نهاية الخدمة", "liability"),
    ("2500", "Withholding Tax Payable",
            "ضريبة الاستقطاع المستحقة", "liability"),
    ("2600", "Zakat Payable",
            "الزكاة المستحقة", "liability"),
    ("2700", "Income Tax Payable",
            "ضريبة الدخل المستحقة", "liability"),
    ("2800", "Social Insurance (GOSI) Payable",
            "التأمينات الاجتماعية المستحقة", "liability"),

    # ─── Equity (extras) ──────────────────────────────────────────────────────
    ("3300", "Statutory Reserve (≥10% per Companies Law)",
            "الاحتياطي النظامي", "equity"),
    ("3400", "Zakat & Tax Reserve",
            "احتياطي الزكاة والضرائب", "equity"),

    # ─── Expenses (extras) ────────────────────────────────────────────────────
    ("5250", "GOSI Employer Contribution",
            "حصة صاحب العمل في التأمينات", "expense"),
    ("5260", "EOSI Expense",
            "مصروف مكافأة نهاية الخدمة", "expense"),
    ("5500", "Zakat Expense",
            "مصروف الزكاة", "expense"),
    ("5510", "Income Tax Expense",
            "مصروف ضريبة الدخل", "expense"),
)


def ensure_socpa_chart(organization) -> dict:
    """Idempotently seed both the IFRS baseline and the SOCPA overlay.

    Returns ``{"created": N, "total": M}`` like ``ensure_default_accounts``
    so callers can show a confirmation. The overlay is added on top of
    the baseline, never instead of it.
    """
    from apps.ledger.services import ensure_default_accounts
    base = ensure_default_accounts(organization)

    created = 0
    for code, en_name, ar_name, acct_type in SOCPA_OVERLAY:
        # Account model likely doesn't have ar_name; if it does, set it.
        defaults = {"name": en_name, "account_type": acct_type,
                    "is_active": True}
        if hasattr(Account, "name_ar"):
            defaults["name_ar"] = ar_name
        _, was_created = Account.objects.get_or_create(
            organization=organization, code=code, defaults=defaults,
        )
        if was_created:
            created += 1

    total = Account.objects.filter(organization=organization).count()
    return {
        "created":           base["created"] + created,
        "socpa_added":       created,
        "total":             total,
        "ifrs_base_created": base["created"],
    }
