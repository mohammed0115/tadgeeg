"""Transactions App Models"""

import uuid
from django.db import models
from apps.authentication.models import User, Organization


class Transaction(models.Model):
    """Financial transaction record."""

    class TransactionType(models.TextChoices):
        INCOME = "income", "Income / Revenue"
        EXPENSE = "expense", "Expense"
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        TRANSFER = "transfer", "Transfer"
        JOURNAL_ENTRY = "journal_entry", "Journal Entry"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="transactions")
    external_id = models.CharField(max_length=100, blank=True, help_text="ID in source ERP system")
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="SAR")
    vat_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    category = models.CharField(max_length=100, blank=True)
    sub_category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    vendor_name = models.CharField(max_length=255, blank=True)
    vendor_vat_number = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    reference_number = models.CharField(max_length=100, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    transaction_date = models.DateField()
    posted_date = models.DateField(null=True, blank=True)
    account_debit = models.CharField(max_length=50, blank=True)
    account_credit = models.CharField(max_length=50, blank=True)
    cost_center = models.CharField(max_length=50, blank=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_transactions"
    )
    source_document = models.ForeignKey(
        "documents.Document", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transactions"
    )
    risk_score = models.FloatField(default=0.0, help_text="0-100 AI risk score")
    risk_level = models.CharField(
        max_length=10, choices=RiskLevel.choices, default=RiskLevel.LOW
    )
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.TextField(blank=True)
    is_duplicate = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates"
    )
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "transactions"
        ordering = ["-transaction_date", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "transaction_date"]),
            models.Index(fields=["organization", "transaction_type"]),
            models.Index(fields=["risk_level"]),
            models.Index(fields=["is_flagged"]),
            models.Index(fields=["vendor_name"]),
            models.Index(fields=["reference_number"]),
        ]

    def __str__(self):
        return f"{self.transaction_type} | {self.amount} {self.currency} | {self.transaction_date}"


class JournalEntry(models.Model):
    """Double-entry bookkeeping journal entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="journal_entries")
    entry_number = models.CharField(max_length=50)
    entry_date = models.DateField()
    description = models.TextField()
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="journal_entries")
    is_manual = models.BooleanField(default=False, help_text="Manual entries flagged for extra scrutiny")
    is_reversed = models.BooleanField(default=False)
    reversal_date = models.DateField(null=True, blank=True)
    is_suspicious = models.BooleanField(default=False)
    total_debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    lines = models.JSONField(default=list, help_text="List of debit/credit line items")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "journal_entries"
        ordering = ["-entry_date"]
        indexes = [
            models.Index(fields=["organization", "entry_date"]),
            models.Index(fields=["is_manual", "is_suspicious"]),
        ]
