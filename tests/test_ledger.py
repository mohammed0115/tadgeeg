"""
Tests for Phase 7.1 — General Ledger.

Covers:
  • Default chart-of-accounts seeds 28+ accounts on first call.
  • post_entry rejects non-balancing entries / both-side lines / unknown
    account codes.
  • Idempotency: same idempotency_key returns the original entry.
  • post_invoice_to_gl produces the expected DR/CR lines for purchase + sale.
  • Trial balance sums to zero across debits + credits for posted entries.
  • General ledger drilldown shows running balance.
  • Voiding generates a compensating entry; the original becomes immutable.
  • Hash chain: two posted entries link via the chain (no skipping, no edits).
  • Multi-currency: FX rate fallback chain works (exact → nearest → identity).
  • Posted-entry payload cannot be mutated (HashChain enforces it).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.integrity import GENESIS_HASH, verify_chain
from apps.authentication.models import Organization, User
from apps.ledger import reports as gl_reports
from apps.ledger import services as gl
from apps.ledger.models import Account, ExchangeRate, JournalEntry


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Ledger Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="ledger-admin@test.local", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="ledger-jr@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chart of accounts
# ─────────────────────────────────────────────────────────────────────────────

def test_default_chart_seeds_idempotently(db, org):
    out = gl.ensure_default_accounts(org)
    assert out["created"] >= 25
    assert out["total"] >= 25

    # Re-run — nothing new.
    out2 = gl.ensure_default_accounts(org)
    assert out2["created"] == 0
    assert out2["total"] == out["total"]


def test_account_normal_side(db, org):
    gl.ensure_default_accounts(org)
    assert gl.get_account(org, "1100").normal_side == "debit"   # Cash → debit-normal
    assert gl.get_account(org, "2100").normal_side == "credit"  # AP → credit-normal
    assert gl.get_account(org, "4100").normal_side == "credit"  # Revenue
    assert gl.get_account(org, "5200").normal_side == "debit"   # Expense


# ─────────────────────────────────────────────────────────────────────────────
# Entry validation
# ─────────────────────────────────────────────────────────────────────────────

def test_post_entry_rejects_unbalanced(db, org, admin):
    gl.ensure_default_accounts(org)
    with pytest.raises(ValueError, match="not balanced"):
        gl.post_entry(
            organization=org, entry_date=date.today(),
            description="bad",
            lines=[
                {"account_code": "1100", "debit":  100},
                {"account_code": "4100", "credit":  90},
            ],
        )


def test_post_entry_rejects_both_sides_on_one_line(db, org):
    gl.ensure_default_accounts(org)
    with pytest.raises(ValueError, match="exactly one"):
        gl.post_entry(
            organization=org, entry_date=date.today(), description="bad",
            lines=[
                {"account_code": "1100", "debit": 50, "credit": 50},
                {"account_code": "4100", "credit": 50},
            ],
        )


def test_post_entry_rejects_unknown_account(db, org):
    gl.ensure_default_accounts(org)
    with pytest.raises(ValueError, match="not found"):
        gl.post_entry(
            organization=org, entry_date=date.today(), description="bad",
            lines=[
                {"account_code": "9999", "debit":  100},
                {"account_code": "4100", "credit": 100},
            ],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────────

def test_idempotency_returns_existing_entry(db, org):
    gl.ensure_default_accounts(org)
    e1 = gl.post_entry(
        organization=org, entry_date=date.today(), description="iden",
        idempotency_key="abc",
        lines=[
            {"account_code": "1100", "debit":  100},
            {"account_code": "4100", "credit": 100},
        ],
    )
    e2 = gl.post_entry(
        organization=org, entry_date=date.today(), description="iden again",
        idempotency_key="abc",   # same key
        lines=[
            {"account_code": "1100", "debit":  500},  # different lines!
            {"account_code": "4100", "credit": 500},
        ],
    )
    assert e1.pk == e2.pk
    assert JournalEntry.objects.filter(idempotency_key="abc").count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Invoice → GL
# ─────────────────────────────────────────────────────────────────────────────

def test_post_purchase_invoice_to_gl(db, org, admin):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="P-100", vendor_name="V1",
        subtotal=Decimal("1000"), vat_amount=Decimal("150"),
        total_amount=Decimal("1150"),
        invoice_date=date.today(),
        currency="SAR", original_filename="x.pdf",
    )
    entry = gl.post_invoice_to_gl(inv, direction="purchase", created_by=admin)

    assert entry.status == JournalEntry.Status.POSTED
    assert entry.is_balanced()
    assert float(entry.total_debits()) == 1150.0   # 1000 expense + 150 VAT in
    codes = {li.account.code for li in entry.lines.all()}
    assert codes == {"5200", "1250", "2100"}


def test_post_sale_invoice_to_gl(db, org, admin):
    from apps.invoices.models import Invoice

    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="S-200", vendor_name="ignored",
        customer_name="Buyer", customer_vat_number="300000000000003",
        subtotal=Decimal("5000"), vat_amount=Decimal("750"),
        total_amount=Decimal("5750"),
        invoice_date=date.today(),
        currency="SAR", original_filename="y.pdf",
    )
    entry = gl.post_invoice_to_gl(inv, direction="sale", created_by=admin)
    assert entry.is_balanced()
    codes = {li.account.code for li in entry.lines.all()}
    assert codes == {"1200", "4100", "2200"}


def test_invoice_post_is_idempotent(db, org, admin):
    from apps.invoices.models import Invoice
    inv = Invoice.objects.create(
        organization=org, uploaded_by=admin,
        invoice_number="ID-1", vendor_name="V",
        subtotal=Decimal("100"), vat_amount=Decimal("15"),
        total_amount=Decimal("115"),
        invoice_date=date.today(),
        currency="SAR", original_filename="i.pdf",
    )
    e1 = gl.post_invoice_to_gl(inv, direction="purchase")
    e2 = gl.post_invoice_to_gl(inv, direction="purchase")
    assert e1.pk == e2.pk


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

def test_trial_balance_sums_to_zero(db, org):
    gl.ensure_default_accounts(org)
    gl.post_entry(
        organization=org, entry_date=date.today(), description="A",
        lines=[
            {"account_code": "1100", "debit":  100},
            {"account_code": "4100", "credit": 100},
        ],
    )
    gl.post_entry(
        organization=org, entry_date=date.today(), description="B",
        lines=[
            {"account_code": "5200", "debit":  50},
            {"account_code": "2100", "credit": 50},
        ],
    )
    tb = gl_reports.trial_balance(org)[0]
    assert tb["totals"]["is_balanced"] is True
    assert tb["totals"]["debit"] == 150.0
    assert tb["totals"]["credit"] == 150.0


def test_general_ledger_running_balance(db, org):
    gl.ensure_default_accounts(org)
    today = date.today()
    gl.post_entry(
        organization=org, entry_date=today,
        description="cash in #1",
        lines=[
            {"account_code": "1100", "debit":  300},
            {"account_code": "4100", "credit": 300},
        ],
    )
    gl.post_entry(
        organization=org, entry_date=today,
        description="cash out",
        lines=[
            {"account_code": "5200", "debit":  100},
            {"account_code": "1100", "credit": 100},
        ],
    )
    out = gl_reports.general_ledger(org, account_code="1100")
    assert out["account"]["code"] == "1100"
    assert len(out["lines"]) == 2
    # Running balance after the two entries: 300 - 100 = 200
    assert out["lines"][-1]["running_balance"] == 200.0


# ─────────────────────────────────────────────────────────────────────────────
# Voiding
# ─────────────────────────────────────────────────────────────────────────────

def test_void_generates_compensating_entry(db, org, admin):
    gl.ensure_default_accounts(org)
    e = gl.post_entry(
        organization=org, entry_date=date.today(), description="V",
        lines=[
            {"account_code": "1100", "debit":  200},
            {"account_code": "4100", "credit": 200},
        ],
    )
    void = gl.void_entry(e, user=admin, reason="duplicate")
    e.refresh_from_db()
    # Original stays POSTED — both entries are part of the trial balance,
    # the compensation is what zeroes the accounts.
    assert e.status == JournalEntry.Status.POSTED
    assert e.voided_by_entry_id == void.pk
    assert e.voided_at is not None
    # The void entry has the opposite debit/credit pattern.
    debits = {li.account.code: li.debit for li in void.lines.all()}
    credits = {li.account.code: li.credit for li in void.lines.all()}
    assert debits.get("4100") == Decimal("200")    # was a credit, now a debit
    assert credits.get("1100") == Decimal("200")   # was a debit, now a credit
    # Trial balance after void must net to zero for the touched accounts.
    tb = gl_reports.trial_balance(org)[0]
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["1100"]["balance"] == 0.0
    assert rows["4100"]["balance"] == 0.0
    # Calling void_entry twice is a no-op — returns the existing void.
    void2 = gl.void_entry(e, user=admin, reason="duplicate")
    assert void2.pk == void.pk


def test_voided_entry_payload_is_immutable_after_post(db, org):
    gl.ensure_default_accounts(org)
    e = gl.post_entry(
        organization=org, entry_date=date.today(), description="immutable",
        lines=[
            {"account_code": "1100", "debit":  10},
            {"account_code": "4100", "credit": 10},
        ],
    )
    e.description = "tampered"
    with pytest.raises(ValidationError):
        e.save()


# ─────────────────────────────────────────────────────────────────────────────
# Hash chain
# ─────────────────────────────────────────────────────────────────────────────

def test_chain_links_two_entries(db, org):
    gl.ensure_default_accounts(org)
    a = gl.post_entry(
        organization=org, entry_date=date.today(), description="first",
        lines=[
            {"account_code": "1100", "debit": 1},
            {"account_code": "4100", "credit": 1},
        ],
    )
    b = gl.post_entry(
        organization=org, entry_date=date.today(), description="second",
        lines=[
            {"account_code": "1100", "debit": 2},
            {"account_code": "4100", "credit": 2},
        ],
    )
    a.refresh_from_db(); b.refresh_from_db()
    assert a.previous_hash == GENESIS_HASH
    assert b.previous_hash == a.event_hash
    assert b.chain_position == a.chain_position + 1

    rep = verify_chain(JournalEntry, str(org.id))
    assert rep.is_intact
    assert rep.rows_checked == 2


# ─────────────────────────────────────────────────────────────────────────────
# Multi-currency
# ─────────────────────────────────────────────────────────────────────────────

def test_fx_rate_fallback_chain(db, org):
    today = date.today()
    # Persist USD→SAR @ 3.75 last week.
    ExchangeRate.objects.create(
        organization=org,
        from_currency="USD", to_currency="SAR",
        rate=Decimal("3.75"), rate_date=today - timedelta(days=7),
        source="manual",
    )
    # Ask for today — no exact row → falls back to nearest prior.
    r = gl.get_or_create_fx_rate(
        organization=org, from_currency="USD", to_currency="SAR",
        rate_date=today,
    )
    assert r.rate == Decimal("3.75")
    assert r.source == "manual"

    # Identity rate when from == to.
    r2 = gl.get_or_create_fx_rate(
        organization=org, from_currency="SAR", to_currency="SAR",
        rate_date=today,
    )
    assert r2.rate == Decimal("1")


def test_post_entry_with_fx_converts_base_amounts(db, org, admin):
    gl.ensure_default_accounts(org)
    today = date.today()
    ExchangeRate.objects.create(
        organization=org, from_currency="USD", to_currency="SAR",
        rate=Decimal("3.75"), rate_date=today, source="manual",
    )
    e = gl.post_entry(
        organization=org, entry_date=today, description="USD entry",
        currency="USD", base_currency="SAR",
        lines=[
            {"account_code": "1100", "debit":  100},
            {"account_code": "4100", "credit": 100},
        ],
    )
    # Each line's base_debit / base_credit should be 100 × 3.75 = 375.
    for li in e.lines.all():
        if li.debit > 0:
            assert li.base_debit == Decimal("375.0000")
        else:
            assert li.base_credit == Decimal("375.0000")


# ─────────────────────────────────────────────────────────────────────────────
# API role gates
# ─────────────────────────────────────────────────────────────────────────────

def test_api_post_entry_requires_finance_role(db, junior):
    c = APIClient(); c.force_authenticate(junior)
    r = c.post("/api/v1/ledger/entries/", {
        "entry_date": date.today().isoformat(),
        "description": "bad",
        "lines": [],
    }, format="json")
    assert r.status_code == 403


def test_api_post_invoice_to_gl(db, admin):
    from apps.invoices.models import Invoice
    inv = Invoice.objects.create(
        organization=admin.organization, uploaded_by=admin,
        invoice_number="API-1", vendor_name="V",
        subtotal=Decimal("100"), vat_amount=Decimal("15"),
        total_amount=Decimal("115"),
        invoice_date=date.today(), currency="SAR",
        original_filename="z.pdf",
    )
    c = APIClient(); c.force_authenticate(admin)
    r = c.post("/api/v1/ledger/post-invoice/", {
        "invoice_id": str(inv.id), "direction": "purchase",
    }, format="json")
    assert r.status_code == 201
    assert r.data["is_balanced"] is True
    assert len(r.data["lines"]) == 3


def test_api_trial_balance(db, admin):
    gl.ensure_default_accounts(admin.organization)
    gl.post_entry(
        organization=admin.organization, entry_date=date.today(),
        description="t", lines=[
            {"account_code": "1100", "debit":  10},
            {"account_code": "4100", "credit": 10},
        ],
    )
    c = APIClient(); c.force_authenticate(admin)
    r = c.get("/api/v1/ledger/trial-balance/")
    assert r.status_code == 200
    assert r.data["totals"]["is_balanced"] is True
    assert r.data["totals"]["debit"] == 10.0
