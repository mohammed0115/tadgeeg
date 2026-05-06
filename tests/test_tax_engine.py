"""
Tests for Phase 7.4 — multi-jurisdiction tax engine.

Covers:
  • get_handler routes to the right handler per ISO code.
  • KSA TRN format validation (15 digits, starts + ends with 3).
  • UAE TRN: 15 digits.
  • EU VAT: country code prefix + 8-12 alphanumerics, rate looked up
    from EU_STANDARD_RATES.
  • US EIN format: NN-NNNNNNN.
  • compute() returns base + tax + total quantised to 2 decimals.
  • supported_countries() includes KSA, UAE, US, and EU member states.
  • API endpoints validate + compute against the right handler.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.authentication.models import Organization, User
from apps.ledger.tax_engine import (
    EUVATHandler, KSAVATHandler, UAEVATHandler, USSalesTaxHandler,
    BaseTaxHandler, get_handler, supported_countries,
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

def test_get_handler_routes_ksa():
    h = get_handler("SA")
    assert isinstance(h, KSAVATHandler)
    assert h.standard_rate == Decimal("15")


def test_get_handler_routes_uae():
    h = get_handler("AE")
    assert isinstance(h, UAEVATHandler)
    assert h.standard_rate == Decimal("5")


def test_get_handler_routes_eu_member_state():
    h = get_handler("DE")
    assert isinstance(h, EUVATHandler)
    assert h.standard_rate == Decimal("19")
    assert h.country_code == "DE"


def test_get_handler_routes_eu_high_rate():
    h = get_handler("SE")
    assert isinstance(h, EUVATHandler)
    assert h.standard_rate == Decimal("25")


def test_get_handler_unknown_returns_base_handler():
    h = get_handler("ZZ")
    assert isinstance(h, BaseTaxHandler)
    assert h.standard_rate == Decimal("0")


def test_get_handler_handles_empty_country():
    assert isinstance(get_handler(""), BaseTaxHandler)


def test_get_handler_uppercases_input():
    h = get_handler("sa")
    assert isinstance(h, KSAVATHandler)


# ─────────────────────────────────────────────────────────────────────────────
# KSA TRN
# ─────────────────────────────────────────────────────────────────────────────

def test_ksa_trn_valid():
    h = KSAVATHandler()
    r = h.validate_tax_id("300000000000003")
    assert r.valid is True
    assert r.country == "SA"


def test_ksa_trn_invalid_first_digit():
    h = KSAVATHandler()
    r = h.validate_tax_id("400000000000003")
    assert r.valid is False


def test_ksa_trn_invalid_last_digit():
    h = KSAVATHandler()
    r = h.validate_tax_id("300000000000007")
    assert r.valid is False


def test_ksa_trn_wrong_length():
    h = KSAVATHandler()
    assert h.validate_tax_id("300003").valid is False
    assert h.validate_tax_id("3000000000000033").valid is False  # 16 digits


def test_ksa_trn_strips_non_digits():
    h = KSAVATHandler()
    r = h.validate_tax_id("3 0000-0000.000003")
    assert r.valid is True


# ─────────────────────────────────────────────────────────────────────────────
# UAE TRN
# ─────────────────────────────────────────────────────────────────────────────

def test_uae_trn_valid():
    h = UAEVATHandler()
    r = h.validate_tax_id("100123456789012")
    assert r.valid is True


def test_uae_trn_invalid_length():
    h = UAEVATHandler()
    assert h.validate_tax_id("12345").valid is False


# ─────────────────────────────────────────────────────────────────────────────
# EU VAT
# ─────────────────────────────────────────────────────────────────────────────

def test_eu_vat_format_ok():
    h = EUVATHandler(member_state="DE")
    r = h.validate_tax_id("DE123456789")
    assert r.valid is True
    assert r.tax_id == "DE123456789"


def test_eu_vat_format_strips_separators():
    h = EUVATHandler(member_state="FR")
    r = h.validate_tax_id("FR-123 456 789")
    assert r.valid is True


def test_eu_vat_no_country_prefix_invalid():
    h = EUVATHandler(member_state="DE")
    r = h.validate_tax_id("123456789")
    assert r.valid is False


# ─────────────────────────────────────────────────────────────────────────────
# US EIN
# ─────────────────────────────────────────────────────────────────────────────

def test_us_ein_with_dash():
    h = USSalesTaxHandler()
    r = h.validate_tax_id("12-3456789")
    assert r.valid is True


def test_us_ein_without_dash():
    h = USSalesTaxHandler()
    r = h.validate_tax_id("123456789")
    assert r.valid is True


def test_us_ein_too_short():
    h = USSalesTaxHandler()
    assert h.validate_tax_id("12-345").valid is False


def test_us_state_rate_injectable():
    h = USSalesTaxHandler(state_rate=Decimal("8.875"))
    assert h.standard_rate == Decimal("8.875")


# ─────────────────────────────────────────────────────────────────────────────
# compute()
# ─────────────────────────────────────────────────────────────────────────────

def test_ksa_compute_15_percent():
    h = KSAVATHandler()
    r = h.compute(Decimal("1000"))
    assert r.tax_amount == Decimal("150.00")
    assert r.total_amount == Decimal("1150.00")
    assert r.rate_pct == Decimal("15")


def test_uae_compute_5_percent():
    h = UAEVATHandler()
    r = h.compute(Decimal("1000"))
    assert r.tax_amount == Decimal("50.00")
    assert r.total_amount == Decimal("1050.00")


def test_eu_germany_19_percent():
    h = EUVATHandler(member_state="DE")
    r = h.compute(Decimal("1000"))
    assert r.tax_amount == Decimal("190.00")


def test_zero_rated_compute():
    h = KSAVATHandler()
    r = h.compute(Decimal("1000"), category="zero")
    assert r.tax_amount == Decimal("0.00")
    assert r.total_amount == Decimal("1000.00")
    assert r.rate_label == "zero-rated"


def test_compute_quantises_to_two_decimals():
    h = KSAVATHandler()
    r = h.compute(Decimal("33.33"))
    # 33.33 × 0.15 = 4.9995 → rounds to 5.00 (HALF_UP)
    assert r.tax_amount == Decimal("5.00")


def test_compute_carries_account_codes():
    h = KSAVATHandler()
    r = h.compute(Decimal("100"))
    assert r.output_account_code == "2200"
    assert r.input_account_code == "1250"


# ─────────────────────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────────────────────

def test_supported_countries_contains_gcc_and_eu():
    rows = supported_countries()
    codes = {r["code"] for r in rows}
    assert {"SA", "AE", "US", "DE", "FR"}.issubset(codes)


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="Tax API Org")


@pytest.fixture
def user(db, org):
    return User.objects.create_user(
        email="tax@test.local", full_name="Tax", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


def test_api_jurisdictions_list(db, user):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.get("/api/v1/ledger/tax/jurisdictions/")
    assert resp.status_code == 200
    codes = {r["code"] for r in resp.data["results"]}
    assert "SA" in codes and "DE" in codes


def test_api_validate_ksa_trn(db, user):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/v1/ledger/tax/validate/",
        {"country": "SA", "tax_id": "300000000000003"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["valid"] is True


def test_api_compute_ksa(db, user):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/v1/ledger/tax/compute/",
        {"country": "SA", "base_amount": 1000},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["tax_amount"] == 150.0
    assert resp.data["total_amount"] == 1150.0


def test_api_compute_rejects_negative(db, user):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/v1/ledger/tax/compute/",
        {"country": "SA", "base_amount": -100},
        format="json",
    )
    assert resp.status_code == 400


def test_api_compute_rejects_garbage_amount(db, user):
    from rest_framework.test import APIClient
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/v1/ledger/tax/compute/",
        {"country": "SA", "base_amount": "not a number"},
        format="json",
    )
    assert resp.status_code == 400
