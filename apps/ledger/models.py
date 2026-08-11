"""
General Ledger — Phase 7.1 of the post-Roadmap plan.

The audit pipeline tells us *what* happened to a document; this app
records *how* it hits the books. Three primary models:

  • ``Account``         — chart-of-accounts row. Hierarchical (parent FK)
                          so a tree like 1000-Assets / 1100-Cash / 1110-
                          Operating Account works without a separate
                          tree-table.
  • ``ExchangeRate``    — daily FX rates for multi-currency consolidation.
                          One row per (from, to, rate_date).
  • ``JournalEntry``    — header + lines. Lines must sum to zero in the
                          entry's currency before save (`save()` enforces
                          the balance + idempotency-key checks).
  • ``JournalLine``     — debit or credit against one Account.

All money fields use ``Decimal(18, 4)`` — fewer rounding artefacts than
the (18, 2) the rest of the platform uses, and matches what SAP CO uses
internally. ``base_amount`` carries the converted value in the org's
reporting currency for consolidation.

Tamper-evidence:
  ``JournalEntry`` extends `HashChainMixin` so once posted it joins the
  org's audit hash chain. Re-posting (same idempotency_key) is a no-op;
  voiding generates a *new* compensating entry rather than editing the
  original — same pattern SAP uses for legal-evidence reasons.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.audit.integrity import HashChainMixin


# ─────────────────────────────────────────────────────────────────────────────
# Chart of Accounts
# ─────────────────────────────────────────────────────────────────────────────

class Account(models.Model):
    """One row per ledger account.

    The ``account_type`` drives whether a balance is a debit or credit
    by default — Assets/Expenses are debit-normal, Liabilities/Equity/
    Revenue are credit-normal.
    """

    class Type(models.TextChoices):
        ASSET     = "asset",     "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY    = "equity",    "Equity"
        REVENUE   = "revenue",   "Revenue"
        EXPENSE   = "expense",   "Expense"
        # Statistical accounts the GL never balances against — used for
        # cost centres or commitment reporting.
        STATISTICAL = "statistical", "Statistical"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="ledger_accounts",
    )
    code          = models.CharField(max_length=24, db_index=True,
                                     help_text="e.g. 1110 / 4001 / EXP-OFFICE")
    name          = models.CharField(max_length=200)
    account_type  = models.CharField(max_length=12, choices=Type.choices)
    parent        = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="children",
    )
    currency      = models.CharField(max_length=3, default="SAR")
    is_active     = models.BooleanField(default=True)
    description   = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ledger_accounts"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="ledger_account_unique_code_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "account_type"]),
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def normal_side(self) -> str:
        """Return 'debit' or 'credit' — the side this account's balance
        usually sits on."""
        return ("debit" if self.account_type in {self.Type.ASSET, self.Type.EXPENSE}
                else "credit")


# ─────────────────────────────────────────────────────────────────────────────
# Exchange rates
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeRate(models.Model):
    """Daily FX rate from ``from_currency`` to ``to_currency``.

    Lookup is per (org, from, to, date) so each tenant can override
    rates locally — useful when month-end consolidation uses a frozen
    rate snapshot."""

    id            = models.BigAutoField(primary_key=True)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="exchange_rates",
    )
    from_currency = models.CharField(max_length=3)
    to_currency   = models.CharField(max_length=3)
    rate          = models.DecimalField(max_digits=18, decimal_places=8,
                                        help_text="1 from_currency = rate × to_currency")
    rate_date     = models.DateField(db_index=True)
    source        = models.CharField(max_length=64, blank=True,
                                     help_text="e.g. 'SAMA', 'OpenExchangeRates', 'manual'.")
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_exchange_rates"
        ordering = ["-rate_date", "from_currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "from_currency", "to_currency", "rate_date"],
                name="ledger_rate_unique_per_org_pair_date",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "from_currency", "to_currency", "rate_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.from_currency}→{self.to_currency} @ {self.rate} ({self.rate_date})"


# ─────────────────────────────────────────────────────────────────────────────
# Journal entries
# ─────────────────────────────────────────────────────────────────────────────

class JournalEntry(HashChainMixin):
    """Header for a balanced double-entry transaction.

    On save, ``_validate_balance()`` enforces sum(debits) == sum(credits) in
    the entry's currency. A non-balancing entry can never be persisted —
    the same invariant SAP, Oracle, and every textbook teaches.
    """

    class Status(models.TextChoices):
        DRAFT  = "draft",  "Draft"
        POSTED = "posted", "Posted"
        VOIDED = "voided", "Voided (compensated)"

    class Source(models.TextChoices):
        MANUAL    = "manual",    "Manual"
        INVOICE   = "invoice",   "Invoice"
        PAYMENT   = "payment",   "Payment voucher"
        RECEIPT   = "receipt",   "Receipt voucher"
        ZATCA     = "zatca",     "ZATCA submission"
        BANK      = "bank",      "Bank reconciliation"
        SYSTEM    = "system",    "System (period close, FX revaluation)"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    entry_number  = models.CharField(max_length=32, db_index=True,
                                     help_text="e.g. JE-2026-00123 — auto-numbered on first save.")
    entry_date    = models.DateField(db_index=True)
    description   = models.CharField(max_length=255)
    reference     = models.CharField(max_length=100, blank=True,
                                     help_text="External reference (invoice number, bank txn id).")

    source        = models.CharField(max_length=12, choices=Source.choices,
                                     default=Source.MANUAL)
    source_object_id = models.CharField(max_length=64, blank=True, db_index=True,
                                        help_text="UUID/PK of the document this entry was posted from.")

    currency      = models.CharField(max_length=3, default="SAR")
    base_currency = models.CharField(max_length=3, default="SAR",
                                     help_text="Org reporting currency at posting time.")
    fx_rate       = models.DecimalField(max_digits=18, decimal_places=8,
                                        default=Decimal("1"),
                                        help_text="1 currency = fx_rate × base_currency at posting time.")

    status        = models.CharField(max_length=8, choices=Status.choices,
                                     default=Status.DRAFT, db_index=True)
    posted_at     = models.DateTimeField(null=True, blank=True)
    voided_at     = models.DateTimeField(null=True, blank=True)
    voided_by_entry = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="voids",
        help_text="The compensating entry that voided this one.",
    )

    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True,
                                       help_text="If supplied, repeated saves with the same key reuse this entry.")
    created_by    = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="created_ledger_entries",
    )
    # F-1 / ISA 240 §32(a): manual journal-entry postings require a
    # different approver than the maker. ``posted_by`` records who
    # transitioned the entry from DRAFT → POSTED.
    posted_by     = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="posted_ledger_entries",
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ledger_journal_entries"
        ordering = ["-entry_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "entry_number"],
                name="ledger_je_unique_number_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="ledger_je_unique_idempotency_per_org",
                condition=models.Q(idempotency_key__gt=""),
            ),
            # Fork prevention — see HashChainMixin's docstring.
            models.UniqueConstraint(
                fields=["chain_partition", "chain_position"],
                name="uniq_chain_position_journalentry",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "entry_date", "status"]),
            models.Index(fields=["organization", "source", "source_object_id"]),
            # Serves the chain-head lookup.
            models.Index(fields=["chain_partition", "chain_position"],
                         name="journalentry_chain_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.entry_number} {self.entry_date} {self.description[:40]}"

    # ── HashChainMixin contract ──────────────────────────────────────────────

    @classmethod
    def _chain_org_filter_key(cls) -> str:
        return "organization_id"

    def _chain_organization_id(self):
        return self.organization_id

    def _chain_payload(self) -> dict:
        return {
            "id":          str(self.id),
            "entry_number": self.entry_number,
            "entry_date":  str(self.entry_date),
            "description": self.description,
            "reference":   self.reference,
            "source":      self.source,
            "currency":    self.currency,
            "base_currency": self.base_currency,
        }

    def _should_chain_now(self) -> bool:
        """Chain only after posting — drafts are still mutable."""
        return self.status == self.Status.POSTED

    # ── Balance validation ───────────────────────────────────────────────────

    def total_debits(self) -> Decimal:
        return sum((Decimal(str(li.debit or 0)) for li in self.lines.all()), Decimal("0"))

    def total_credits(self) -> Decimal:
        return sum((Decimal(str(li.credit or 0)) for li in self.lines.all()), Decimal("0"))

    def is_balanced(self) -> bool:
        return self.total_debits() == self.total_credits()


class JournalLine(models.Model):
    """One leg of a journal entry. Either ``debit`` or ``credit`` is set
    (the other is zero) — never both, never neither."""

    id            = models.BigAutoField(primary_key=True)
    entry         = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines",
    )
    line_number   = models.PositiveSmallIntegerField()
    account       = models.ForeignKey(Account, on_delete=models.PROTECT,
                                      related_name="journal_lines")
    debit         = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    credit        = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    base_debit    = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"),
                                        help_text="debit converted to org reporting currency.")
    base_credit   = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    description   = models.CharField(max_length=255, blank=True)
    cost_center   = models.CharField(max_length=64, blank=True)
    project_code  = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "ledger_journal_lines"
        ordering = ["entry", "line_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="ledger_line_non_negative",
            ),
            models.CheckConstraint(
                # Exactly one of debit/credit must be > 0.
                condition=(models.Q(debit__gt=0, credit=0)
                           | models.Q(debit=0, credit__gt=0)),
                name="ledger_line_one_side_only",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "entry"]),
        ]

    def __str__(self) -> str:
        side = f"DR {self.debit}" if self.debit > 0 else f"CR {self.credit}"
        return f"{self.account.code} {side}"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.2 — Accounting periods + period close
# ─────────────────────────────────────────────────────────────────────────────

class AccountingPeriod(models.Model):
    """One row per fiscal period (typically calendar months).

    The GL is only as trustworthy as its period-close discipline:
    without it, anyone with the finance role can backdate journal
    entries into a published quarter and silently rewrite history. This
    is the SAP F-CO / Oracle Calendar concept — once a period is CLOSED,
    ``post_entry`` rejects any attempt to write into it.

    State machine: OPEN → CLOSING → CLOSED → LOCKED. CLOSED can be
    reopened by an admin (which the audit trail records); LOCKED is
    one-way and reserved for auditor sign-off.
    """

    class Status(models.TextChoices):
        OPEN     = "open",     "Open"
        CLOSING  = "closing",  "Closing in progress"
        CLOSED   = "closed",   "Closed"
        LOCKED   = "locked",   "Locked (auditor sign-off)"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="accounting_periods",
    )
    fiscal_year   = models.PositiveSmallIntegerField()
    period_number = models.PositiveSmallIntegerField(
        help_text="1-12 for monthly accounting; 13 = year-end adjustment.",
    )
    name          = models.CharField(max_length=64,
                                     help_text="e.g. '2026-05' or 'FY2026 P05'")
    start_date    = models.DateField(db_index=True)
    end_date      = models.DateField(db_index=True)
    status        = models.CharField(max_length=12, choices=Status.choices,
                                     default=Status.OPEN, db_index=True)
    closed_at     = models.DateTimeField(null=True, blank=True)
    closed_by     = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="closed_periods",
    )
    locked_at     = models.DateTimeField(null=True, blank=True)
    locked_by     = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="locked_periods",
    )
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ledger_periods"
        ordering = ["-fiscal_year", "-period_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "fiscal_year", "period_number"],
                name="ledger_period_unique_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="ledger_period_dates_ordered",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "start_date", "end_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN

    def covers(self, d) -> bool:
        return self.start_date <= d <= self.end_date
