"""
Bank-connector data model — Phase 5 of the Enterprise Roadmap.

  • ``BankConnection`` — one row per (org, bank). Holds environment, encrypted
                        credentials, last-sync cursor.
  • ``BankAccount``    — accounts surfaced by the connector.
  • ``BankTransaction`` — every line on every statement, deduplicated by
                          ``(account, external_id)``.
  • ``Reconciliation`` — link between a transaction and an invoice with a
                         fuzzy-match score and an audit trail of who
                         confirmed / rejected the suggestion.

Credentials live encrypted with the same Fernet key the ZATCA app uses
(``apps.zatca.crypto.encrypt_secret``) so that no plaintext API token
ever sits in the DB.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone


class BankConnection(models.Model):
    """A live (or simulated) link to one Saudi bank's API."""

    class BankCode(models.TextChoices):
        AL_RAJHI = "al_rajhi", "Al Rajhi Bank"
        SNB      = "snb",      "Saudi National Bank"
        RIYAD    = "riyad",    "Riyad Bank"
        SAB      = "sab",      "Saudi Awwal Bank"
        BSF      = "bsf",      "Banque Saudi Fransi"
        OTHER    = "other",    "Other (statement upload only)"

    class Environment(models.TextChoices):
        MOCK       = "mock",       "Mock (offline, deterministic)"
        SANDBOX    = "sandbox",    "Sandbox"
        PRODUCTION = "production", "Production"

    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending credentials"
        ACTIVE   = "active",   "Active"
        ERROR    = "error",    "Error during last sync"
        DISABLED = "disabled", "Disabled by admin"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="bank_connections",
    )
    bank_code     = models.CharField(max_length=16, choices=BankCode.choices)
    display_name  = models.CharField(max_length=100, blank=True,
                                     help_text="Human label shown in the UI when an org has multiple connections to the same bank.")
    environment   = models.CharField(max_length=12, choices=Environment.choices,
                                     default=Environment.MOCK)
    status        = models.CharField(max_length=12, choices=Status.choices,
                                     default=Status.PENDING, db_index=True)

    credentials_encrypted = models.BinaryField(
        null=True, blank=True,
        help_text="Fernet ciphertext of a JSON dict {api_key, secret, ...}.",
    )
    last_sync_at  = models.DateTimeField(null=True, blank=True)
    last_error    = models.CharField(max_length=512, blank=True)

    created_by    = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="bank_connections",
    )
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bank_connections"
        ordering = ["bank_code", "-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "bank_code", "environment", "display_name"],
                name="bank_conn_unique_per_org_env",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_bank_code_display()} [{self.environment}/{self.status}]"


class BankAccount(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection    = models.ForeignKey(
        BankConnection, on_delete=models.CASCADE, related_name="accounts",
    )
    account_number = models.CharField(max_length=48, db_index=True)
    iban           = models.CharField(max_length=34, blank=True, db_index=True)
    nickname       = models.CharField(max_length=100, blank=True)
    currency       = models.CharField(max_length=3, default="SAR")
    balance_cached = models.DecimalField(max_digits=18, decimal_places=2,
                                         default=Decimal("0"))
    balance_fetched_at = models.DateTimeField(null=True, blank=True)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bank_accounts"
        ordering = ["account_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "account_number"],
                name="bank_acct_unique_per_conn",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.account_number} ({self.currency})"


class BankTransaction(models.Model):
    """One line on a bank statement.

    ``external_id`` is the bank's reference; we deduplicate on
    ``(account, external_id)`` so resyncing a window doesn't double-count.
    """

    class Direction(models.TextChoices):
        DEBIT  = "debit",  "Debit"
        CREDIT = "credit", "Credit"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account       = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions",
    )
    external_id   = models.CharField(max_length=128, db_index=True)
    posted_at     = models.DateTimeField(db_index=True)
    direction     = models.CharField(max_length=8, choices=Direction.choices)
    amount        = models.DecimalField(max_digits=18, decimal_places=2)
    currency      = models.CharField(max_length=3, default="SAR")
    reference     = models.CharField(max_length=255, blank=True, db_index=True)
    description   = models.TextField(blank=True)
    counterparty  = models.CharField(max_length=255, blank=True, db_index=True)
    raw_payload   = models.JSONField(default=dict, blank=True)
    imported_at   = models.DateTimeField(default=timezone.now)
    is_reconciled = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "bank_transactions"
        ordering = ["-posted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "external_id"],
                name="bank_tx_unique_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "posted_at"]),
            models.Index(fields=["counterparty", "posted_at"]),
        ]

    def __str__(self) -> str:
        sign = "-" if self.direction == "debit" else "+"
        return f"{sign}{self.amount} {self.currency} {self.posted_at:%Y-%m-%d} {self.counterparty[:24]}"


class Reconciliation(models.Model):
    """Link between a bank transaction and an invoice (or proof that no
    invoice matched). The match score + reason list explain why the engine
    suggested this pair, so a senior auditor can confirm or override."""

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested by engine"
        CONFIRMED = "confirmed", "Confirmed by auditor"
        REJECTED  = "rejected",  "Rejected — not a match"
        MANUAL    = "manual",    "Manually paired"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="reconciliations",
    )
    invoice       = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reconciliations",
    )
    transaction   = models.ForeignKey(
        BankTransaction, on_delete=models.CASCADE,
        related_name="reconciliations",
    )
    score         = models.PositiveSmallIntegerField(
        default=0, help_text="0–100 fuzzy-match score from the engine.",
    )
    reasons       = models.JSONField(default=list, blank=True,
                                     help_text="Per-signal explanations driving the score.")
    status        = models.CharField(max_length=12, choices=Status.choices,
                                     default=Status.SUGGESTED, db_index=True)

    reconciled_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reconciliations",
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes         = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bank_reconciliations"
        ordering = ["-score", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "invoice"],
                name="bank_recon_unique_pair",
                condition=models.Q(invoice__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "score"]),
        ]

    def __str__(self) -> str:
        return f"recon {self.transaction_id}↔{self.invoice_id} [{self.status}/{self.score}]"
