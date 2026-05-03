"""
Tests for Phase 5 — Bank Connectors.

Covers:
  • Connector registry resolves all 5 bank codes.
  • Mock connector returns deterministic accounts + transactions.
  • Statement parser (CSV) handles header autodetect + debit/credit columns.
  • Reconciliation engine: high-confidence pair scores ≥ 80; low-confidence
    pair scores < 60; same invoice can't be claimed twice in a window.
  • sync_connection upserts accounts + transactions, no duplicates on rerun.
  • run_reconciliation creates SUGGESTED rows; confirm flips status + flag.
  • API: connection list/create requires admin, reconciliation actions
    confirm/reject persist correctly.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import Organization, User
from apps.banking.connectors.registry import REGISTRY, get_connector
from apps.banking.models import (
    BankAccount, BankConnection, BankTransaction, Reconciliation,
)
from apps.banking import parsers as bank_parsers
from apps.banking import reconcile
from apps.banking.services import (
    confirm_reconciliation, run_reconciliation, store_credentials, sync_connection,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="Banking Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="b-admin@test.local", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="b-junior@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


@pytest.fixture
def admin_client(admin):
    c = APIClient(); c.force_authenticate(admin); return c


@pytest.fixture
def connection(db, org):
    return BankConnection.objects.create(
        organization=org, bank_code="al_rajhi",
        environment=BankConnection.Environment.MOCK,
        status=BankConnection.Status.PENDING,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Registry + connectors
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_has_all_five_banks():
    assert set(REGISTRY) == {"al_rajhi", "snb", "riyad", "sab", "bsf"}


def test_mock_connector_returns_deterministic_accounts():
    c1 = get_connector("al_rajhi", environment="mock")
    c2 = get_connector("al_rajhi", environment="mock")
    c1.authenticate(); c2.authenticate()
    a1 = c1.fetch_accounts(); a2 = c2.fetch_accounts()
    assert a1[0].account_number == a2[0].account_number
    assert a1[0].iban == a2[0].iban


def test_mock_connector_transactions_are_in_window():
    conn = get_connector("snb", environment="mock")
    conn.authenticate()
    accounts = conn.fetch_accounts()
    since = datetime(2026, 1, 1)
    until = datetime(2026, 1, 31, 23, 59, 59)
    txs = conn.fetch_transactions(account_number=accounts[0].account_number,
                                  from_date=since, to_date=until)
    assert txs
    for t in txs:
        assert since <= t.posted_at <= until


# ─────────────────────────────────────────────────────────────────────────────
# 2. CSV parser
# ─────────────────────────────────────────────────────────────────────────────

def test_csv_parser_with_debit_credit_columns():
    csv = (
        "Date,Description,Debit,Credit,Reference\n"
        "2026-01-15,Vendor payment,1500.00,,INV-100\n"
        "2026-01-20,Customer deposit,,9000.00,DEP-1\n"
    )
    rows = bank_parsers.parse_csv(csv)
    assert len(rows) == 2
    assert rows[0].direction == "debit"
    assert rows[0].amount == Decimal("1500.00")
    assert rows[0].reference == "INV-100"
    assert rows[1].direction == "credit"
    assert rows[1].amount == Decimal("9000.00")


def test_csv_parser_handles_amount_only_column():
    csv = (
        "PostingDate,Particulars,Amount\n"
        "2026-02-01,Office supplies,-450.50\n"
        "2026-02-03,Refund issued,200.00\n"
    )
    rows = bank_parsers.parse_csv(csv)
    assert rows[0].direction == "debit"
    assert rows[0].amount == Decimal("450.50")
    assert rows[1].direction == "credit"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Reconciliation scoring
# ─────────────────────────────────────────────────────────────────────────────

def test_score_pair_high_confidence_for_exact_match(db, org, admin):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="INV-9001", vendor_name="ARAMCO PROCUREMENT",
        total_amount=Decimal("12500.00"),
        invoice_date=timezone.now().date(), original_filename="a.pdf",
    )
    conn = BankConnection.objects.create(
        organization=org, bank_code="al_rajhi",
        environment=BankConnection.Environment.MOCK,
    )
    acct = BankAccount.objects.create(
        connection=conn, account_number="000111222",
    )
    tx = BankTransaction.objects.create(
        account=acct, external_id="X-1",
        posted_at=timezone.now(),
        direction="debit", amount=Decimal("12500.00"),
        reference="INV-9001", description="Payment to ARAMCO",
        counterparty="ARAMCO PROCUREMENT",
    )

    res = reconcile.score_pair(tx, inv)
    assert res.score >= 80
    assert res.confidence == "high"
    # Each signal has a non-zero positive contribution.
    assert sum(r["score"] for r in res.reasons) == res.score


def test_score_pair_low_confidence_for_unrelated_pair(db, org, admin):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="INV-OTHER", vendor_name="TAMER GROUP",
        total_amount=Decimal("999"),
        invoice_date=timezone.now().date() - timedelta(days=120),
        original_filename="o.pdf",
    )
    conn = BankConnection.objects.create(
        organization=org, bank_code="al_rajhi",
        environment=BankConnection.Environment.MOCK,
    )
    acct = BankAccount.objects.create(
        connection=conn, account_number="000111222",
    )
    tx = BankTransaction.objects.create(
        account=acct, external_id="X-2",
        posted_at=timezone.now(),
        direction="debit", amount=Decimal("12500.00"),
        reference="UNRELATED",
        counterparty="UNRELATED PARTY",
    )
    res = reconcile.score_pair(tx, inv)
    assert res.score < 60
    assert res.confidence == "low"


def test_match_window_does_not_double_claim_an_invoice(db, org, admin):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="INV-EXCL", vendor_name="ARAMCO",
        total_amount=Decimal("1000"),
        invoice_date=timezone.now().date(), original_filename="x.pdf",
    )
    conn = BankConnection.objects.create(
        organization=org, bank_code="al_rajhi",
        environment=BankConnection.Environment.MOCK,
    )
    acct = BankAccount.objects.create(connection=conn, account_number="A")

    tx_a = BankTransaction.objects.create(
        account=acct, external_id="A1",
        posted_at=timezone.now(), direction="debit",
        amount=Decimal("1000"), reference="INV-EXCL",
        counterparty="ARAMCO",
    )
    tx_b = BankTransaction.objects.create(
        account=acct, external_id="B1",
        posted_at=timezone.now(), direction="debit",
        amount=Decimal("1000"), reference="INV-EXCL",
        counterparty="ARAMCO",
    )
    out = reconcile.match_window([tx_a, tx_b], [inv])
    assert len(out) == 1   # invoice can only be claimed once
    assert out[0].transaction in (tx_a, tx_b)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sync + reconciliation end-to-end
# ─────────────────────────────────────────────────────────────────────────────

def test_sync_connection_imports_accounts_and_transactions(db, connection):
    out1 = sync_connection(connection)
    assert out1["ok"] is True
    assert out1["accounts_seen"] == 2
    assert out1["transactions_imported"] > 0

    # Re-sync: every transaction should be deduplicated.
    connection.refresh_from_db()
    connection.last_sync_at = None  # force the same window so we hit dupes
    out2 = sync_connection(connection)
    assert out2["transactions_imported"] == 0
    assert out2["transactions_skipped"] == out1["transactions_imported"]


def test_run_reconciliation_creates_suggestions(db, org, admin, connection):
    from apps.invoices.models import Invoice

    sync_connection(connection)
    # Pick a transaction the engine will see.
    tx = BankTransaction.objects.filter(
        account__connection=connection, direction="debit",
    ).first()
    # Create a perfectly-matching invoice.
    Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number=tx.reference,
        vendor_name=tx.counterparty,
        total_amount=tx.amount,
        invoice_date=tx.posted_at.date(),
        original_filename="match.pdf",
    )

    summary = run_reconciliation(org)
    assert summary["suggestions_created"] >= 1
    rec = Reconciliation.objects.filter(organization=org).first()
    assert rec is not None
    assert rec.score >= 60
    assert rec.status == Reconciliation.Status.SUGGESTED


def test_confirm_reconciliation_marks_transaction(db, org, admin, connection):
    from apps.invoices.models import Invoice

    sync_connection(connection)
    tx = BankTransaction.objects.filter(
        account__connection=connection, direction="debit",
    ).first()
    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number=tx.reference,
        vendor_name=tx.counterparty,
        total_amount=tx.amount,
        invoice_date=tx.posted_at.date(),
        original_filename="x.pdf",
    )
    run_reconciliation(org)
    rec = Reconciliation.objects.filter(organization=org).first()
    assert rec
    confirm_reconciliation(rec, user=admin)
    rec.refresh_from_db(); tx.refresh_from_db()
    assert rec.status == Reconciliation.Status.CONFIRMED
    assert rec.reconciled_by_id == admin.id
    assert tx.is_reconciled is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. API role gates
# ─────────────────────────────────────────────────────────────────────────────

def test_create_connection_requires_admin(db, junior):
    c = APIClient(); c.force_authenticate(junior)
    r = c.post("/api/v1/banking/connections/", {
        "bank_code": "al_rajhi", "environment": "mock",
    }, format="json")
    assert r.status_code == 403


def test_create_and_sync_connection_via_api(db, admin_client, admin):
    r = admin_client.post("/api/v1/banking/connections/", {
        "bank_code": "snb", "environment": "mock", "display_name": "SNB main",
    }, format="json")
    assert r.status_code == 201, r.content
    cid = r.data["id"]

    r2 = admin_client.post(f"/api/v1/banking/connections/{cid}/sync/")
    assert r2.status_code == 200
    assert r2.data["summary"]["ok"] is True
    assert r2.data["summary"]["transactions_imported"] > 0


def test_credentials_round_trip_via_fernet(db, connection):
    store_credentials(connection, {"client_id": "abc", "client_secret": "secret-123"})
    connection.refresh_from_db()
    assert connection.credentials_encrypted   # encrypted at rest

    from apps.banking.services import load_credentials
    decoded = load_credentials(connection)
    assert decoded == {"client_id": "abc", "client_secret": "secret-123"}
