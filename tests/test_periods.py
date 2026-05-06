"""
Tests for Phase 7.2 — Accounting Periods (close / reopen / lock).

Covers:
  • ensure_periods_for_year creates 12 monthly OPEN periods.
  • post_entry refuses to write into a CLOSED period (the headline guard).
  • close_period transitions OPEN → CLOSED and stamps closed_at + closed_by.
  • reopen_period only works on CLOSED, not LOCKED.
  • lock_period is one-way (LOCKED → anything else raises).
  • A second close on an already-CLOSED period is a no-op error.
  • API list/close/reopen are gated by finance/admin roles.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.authentication.models import Organization, User
from apps.ledger import services as gl
from apps.ledger.models import AccountingPeriod, JournalEntry


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Periods Test Org")


@pytest.fixture
def admin(db, org):
    return User.objects.create_user(
        email="periods-admin@test.local", full_name="Admin", password="x",
        organization=org, role=User.Role.ADMIN,
    )


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="periods-jr@test.local", full_name="Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Period seeding
# ─────────────────────────────────────────────────────────────────────────────

def test_ensure_periods_for_year_creates_twelve(db, org):
    result = gl.ensure_periods_for_year(org, 2026)
    assert result["created"] == 12
    assert result["total"] == 12
    qs = AccountingPeriod.objects.filter(organization=org, fiscal_year=2026)
    assert qs.count() == 12
    assert qs.filter(status=AccountingPeriod.Status.OPEN).count() == 12

    # Idempotent: a second call adds nothing.
    again = gl.ensure_periods_for_year(org, 2026)
    assert again["created"] == 0


def test_period_dates_are_correct_for_february(db, org):
    gl.ensure_periods_for_year(org, 2026)
    feb = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=2)
    assert feb.start_date == date(2026, 2, 1)
    assert feb.end_date == date(2026, 2, 28)


# ─────────────────────────────────────────────────────────────────────────────
# Posting guard — the whole point of period close
# ─────────────────────────────────────────────────────────────────────────────

def test_post_entry_blocked_in_closed_period(db, org, admin):
    gl.ensure_default_accounts(org)
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin)

    with pytest.raises(ValueError, match="cannot post into"):
        gl.post_entry(
            organization=org, entry_date=date(2026, 1, 15),
            description="late entry",
            lines=[
                {"account_code": "1100", "debit":  100},
                {"account_code": "4100", "credit": 100},
            ],
        )


def test_post_entry_allowed_in_open_period(db, org):
    gl.ensure_default_accounts(org)
    gl.ensure_periods_for_year(org, 2026)
    e = gl.post_entry(
        organization=org, entry_date=date(2026, 3, 15),
        description="march entry",
        lines=[
            {"account_code": "1100", "debit":  100},
            {"account_code": "4100", "credit": 100},
        ],
    )
    assert e.status == JournalEntry.Status.POSTED


def test_post_entry_with_no_period_defined_is_allowed(db, org):
    """An org that hasn't seeded periods yet should not be blocked from
    posting — periods are opt-in, not mandatory."""
    gl.ensure_default_accounts(org)
    e = gl.post_entry(
        organization=org, entry_date=date(2026, 6, 1),
        description="no period defined",
        lines=[
            {"account_code": "1100", "debit":  100},
            {"account_code": "4100", "credit": 100},
        ],
    )
    assert e.pk


# ─────────────────────────────────────────────────────────────────────────────
# State machine
# ─────────────────────────────────────────────────────────────────────────────

def test_close_period_stamps_metadata(db, org, admin):
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin, fx_revaluation=False)

    jan.refresh_from_db()
    assert jan.status == AccountingPeriod.Status.CLOSED
    assert jan.closed_at is not None
    assert jan.closed_by_id == admin.id


def test_close_already_closed_raises(db, org, admin):
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin, fx_revaluation=False)
    jan.refresh_from_db()

    with pytest.raises(ValueError, match="cannot close"):
        gl.close_period(jan, user=admin, fx_revaluation=False)


def test_reopen_a_closed_period(db, org, admin):
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin, fx_revaluation=False)
    jan.refresh_from_db()

    gl.reopen_period(jan, user=admin, reason="manual adj")
    jan.refresh_from_db()
    assert jan.status == AccountingPeriod.Status.OPEN


def test_reopen_an_open_period_raises(db, org, admin):
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    with pytest.raises(ValueError):
        gl.reopen_period(jan, user=admin, reason="x")


def test_lock_a_closed_period(db, org, admin):
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin, fx_revaluation=False)
    jan.refresh_from_db()

    gl.lock_period(jan, user=admin)
    jan.refresh_from_db()
    assert jan.status == AccountingPeriod.Status.LOCKED


def test_lock_is_one_way(db, org, admin):
    """Once LOCKED, reopen must raise — no escape hatch by design."""
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    gl.close_period(jan, user=admin, fx_revaluation=False)
    jan.refresh_from_db()
    gl.lock_period(jan, user=admin)
    jan.refresh_from_db()

    with pytest.raises(ValueError):
        gl.reopen_period(jan, user=admin, reason="urgent")


def test_lock_open_period_raises(db, org, admin):
    """Cannot lock something that hasn't been closed first."""
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)
    with pytest.raises(ValueError):
        gl.lock_period(jan, user=admin)


# ─────────────────────────────────────────────────────────────────────────────
# API role gating
# ─────────────────────────────────────────────────────────────────────────────

def test_api_period_close_requires_finance_role(db, junior, org):
    from rest_framework.test import APIClient
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)

    client = APIClient()
    client.force_authenticate(user=junior)
    resp = client.post(f"/api/v1/ledger/periods/{jan.id}/close/", format="json")
    assert resp.status_code == 403


def test_api_period_close_admin_succeeds(db, admin, org):
    from rest_framework.test import APIClient
    gl.ensure_periods_for_year(org, 2026)
    jan = AccountingPeriod.objects.get(organization=org, fiscal_year=2026, period_number=1)

    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post(
        f"/api/v1/ledger/periods/{jan.id}/close/",
        {"fx_revaluation": False},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.data["ok"] is True
    jan.refresh_from_db()
    assert jan.status == AccountingPeriod.Status.CLOSED
