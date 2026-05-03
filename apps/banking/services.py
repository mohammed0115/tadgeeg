"""
Bank-connection orchestration — Phase 5.

  • ``sync_connection(connection)`` — pulls the latest accounts + transactions
    from the bank, persists new rows (deduplicated by ``external_id``),
    updates ``last_sync_at``.
  • ``run_reconciliation(organization)`` — feeds the org's recent debit
    transactions + outstanding invoices through the reconciliation engine
    and persists every match above the medium-confidence threshold as a
    ``Reconciliation(SUGGESTED)`` row.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.banking.connectors.registry import get_connector
from apps.banking.models import (
    BankAccount, BankConnection, BankTransaction, Reconciliation,
)
from apps.banking.reconcile import match_window
from apps.zatca import crypto as zatca_crypto

logger = logging.getLogger("finai.banking")


# ─────────────────────────────────────────────────────────────────────────────
# Credential helpers
# ─────────────────────────────────────────────────────────────────────────────

def store_credentials(connection: BankConnection, credentials: dict) -> None:
    """Encrypt ``credentials`` (a JSON dict) and persist on the connection."""
    blob = json.dumps(credentials).encode("utf-8")
    connection.credentials_encrypted = zatca_crypto.encrypt_secret(blob)
    connection.save(update_fields=["credentials_encrypted", "updated_at"])


def load_credentials(connection: BankConnection) -> dict:
    if not connection.credentials_encrypted:
        return {}
    try:
        return json.loads(
            zatca_crypto.decrypt_secret(connection.credentials_encrypted).decode("utf-8")
        )
    except Exception as exc:
        logger.warning("[banking] credential decrypt failed for %s: %s",
                       connection.id, exc)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Sync
# ─────────────────────────────────────────────────────────────────────────────

def sync_connection(connection: BankConnection, *,
                    lookback_days: int = 30) -> dict:
    """Fetch accounts + transactions for ``connection`` and upsert them.

    Returns a summary dict the dashboard / API displays:
    ``{accounts_seen, transactions_imported, transactions_skipped,
       since, until, ok, error}``.
    """
    summary = {
        "accounts_seen":          0,
        "transactions_imported":  0,
        "transactions_skipped":   0,
        "since":                  None,
        "until":                  None,
        "ok":                     False,
        "error":                  "",
    }

    creds = load_credentials(connection)
    connector = get_connector(connection.bank_code,
                              environment=connection.environment, credentials=creds)

    try:
        connector.authenticate()
    except Exception as exc:
        connection.status = BankConnection.Status.ERROR
        connection.last_error = str(exc)[:512]
        connection.save(update_fields=["status", "last_error", "updated_at"])
        summary["error"] = str(exc)[:240]
        return summary

    # 1. Accounts.
    try:
        for info in connector.fetch_accounts():
            account, created = BankAccount.objects.update_or_create(
                connection=connection,
                account_number=info.account_number,
                defaults={
                    "iban":     info.iban,
                    "currency": info.currency,
                    "nickname": info.nickname,
                    "balance_cached":     info.balance,
                    "balance_fetched_at": timezone.now(),
                },
            )
            summary["accounts_seen"] += 1
    except Exception as exc:
        connection.status = BankConnection.Status.ERROR
        connection.last_error = f"fetch_accounts: {exc}"[:512]
        connection.save(update_fields=["status", "last_error", "updated_at"])
        summary["error"] = str(exc)[:240]
        return summary

    # 2. Transactions per account.
    until = timezone.now()
    since = (connection.last_sync_at or until - timedelta(days=lookback_days))
    summary["since"] = since.isoformat()
    summary["until"] = until.isoformat()

    for account in connection.accounts.filter(is_active=True):
        try:
            txs = connector.fetch_transactions(
                account_number=account.account_number,
                from_date=since, to_date=until,
            )
        except Exception as exc:
            logger.warning("[banking] fetch_transactions failed for %s: %s",
                           account.account_number, exc)
            continue

        for tx in txs:
            _, created = BankTransaction.objects.update_or_create(
                account=account, external_id=tx.external_id,
                defaults={
                    "posted_at":    tx.posted_at,
                    "direction":    tx.direction,
                    "amount":       tx.amount,
                    "currency":     tx.currency,
                    "reference":    tx.reference,
                    "description":  tx.description,
                    "counterparty": tx.counterparty,
                    "raw_payload":  tx.raw,
                },
            )
            if created:
                summary["transactions_imported"] += 1
            else:
                summary["transactions_skipped"] += 1

    connection.status = BankConnection.Status.ACTIVE
    connection.last_error = ""
    connection.last_sync_at = until
    connection.save(update_fields=["status", "last_error", "last_sync_at", "updated_at"])
    summary["ok"] = True
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def run_reconciliation(organization, *, lookback_days: int = 60,
                       min_score: int = 60) -> dict:
    """Match recent debit transactions to outstanding invoices.

    Persists each suggested pair as a ``Reconciliation(SUGGESTED)`` row.
    Skips pairs that already have a Reconciliation (any status) so the
    auditor's confirm/reject decisions stick.
    """
    from apps.invoices.models import Invoice

    since = timezone.now() - timedelta(days=lookback_days)
    txs = list(
        BankTransaction.objects
        .filter(account__connection__organization=organization,
                posted_at__gte=since,
                direction=BankTransaction.Direction.DEBIT,
                is_reconciled=False)
        .select_related("account__connection")
    )
    invoices = list(
        Invoice.objects.filter(organization=organization)
        .exclude(status__in=["rejected"])
    )

    matches = match_window(txs, invoices, min_score=min_score)

    created = 0
    for m in matches:
        # Skip if a Reconciliation already exists for this (tx, invoice).
        existing = Reconciliation.objects.filter(
            organization=organization,
            transaction=m.transaction, invoice=m.invoice,
        ).first()
        if existing:
            continue
        Reconciliation.objects.create(
            organization=organization,
            transaction=m.transaction,
            invoice=m.invoice,
            score=m.score,
            reasons=m.reasons,
            status=Reconciliation.Status.SUGGESTED,
        )
        created += 1

    return {
        "transactions_considered": len(txs),
        "invoices_considered":     len(invoices),
        "suggestions_created":     created,
        "since":                   since.isoformat(),
    }


def confirm_reconciliation(recon: Reconciliation, *, user) -> Reconciliation:
    recon.status = Reconciliation.Status.CONFIRMED
    recon.reconciled_by = user
    recon.reconciled_at = timezone.now()
    recon.save(update_fields=["status", "reconciled_by", "reconciled_at", "updated_at"])
    if recon.transaction:
        recon.transaction.is_reconciled = True
        recon.transaction.save(update_fields=["is_reconciled"])
    return recon


def reject_reconciliation(recon: Reconciliation, *, user, notes: str = "") -> Reconciliation:
    recon.status = Reconciliation.Status.REJECTED
    recon.reconciled_by = user
    recon.reconciled_at = timezone.now()
    if notes:
        recon.notes = notes
    recon.save(update_fields=["status", "reconciled_by", "reconciled_at",
                              "notes", "updated_at"])
    return recon
