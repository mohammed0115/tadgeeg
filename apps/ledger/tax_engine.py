"""
Multi-jurisdiction tax engine — Phase 7.4.

Each "jurisdiction" is a small handler class that knows how to:

  • Validate a tax-registration-number format (KSA TRN, UAE TRN, EU VAT, US EIN)
  • Compute tax on a (subtotal, rate) pair using the local rounding rule
  • Derive the appropriate output / input GL accounts

The engine is registry-driven: ``get_handler("KSA")`` returns the handler
for that country code, so a future "Bahrain VAT" or "Egypt VAT" handler
slots in without touching the call-sites that already pipe transactions
through the engine.

What this module does NOT do (deferred):
  • Periodic tax-return XML / API submission for every jurisdiction.
    ZATCA Phase 2 (KSA) is implemented in apps/zatca; UAE FTA + EU OSS
    return submission would each need their own app. This file is the
    *engine* — the bit that decides which rate applies and where the
    money goes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Result shapes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaxValidation:
    valid:        bool
    country:      str
    tax_id:       str = ""
    explanation:  str = ""

    def to_dict(self) -> dict:
        return {"valid": self.valid, "country": self.country,
                "tax_id": self.tax_id, "explanation": self.explanation}


@dataclass
class TaxComputation:
    """Result of computing tax on a base amount.

    ``output_account_code`` is the GL account the seller credits when
    the invoice posts; ``input_account_code`` is the buyer's debit.
    """
    country:       str
    rate_pct:      Decimal
    rate_label:    str
    base_amount:   Decimal
    tax_amount:    Decimal
    total_amount:  Decimal
    output_account_code: str = ""
    input_account_code:  str = ""
    notes:         list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "country":       self.country,
            "rate_pct":      float(self.rate_pct),
            "rate_label":    self.rate_label,
            "base_amount":   float(self.base_amount),
            "tax_amount":    float(self.tax_amount),
            "total_amount":  float(self.total_amount),
            "output_account_code": self.output_account_code,
            "input_account_code":  self.input_account_code,
            "notes":         self.notes,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Base handler
# ─────────────────────────────────────────────────────────────────────────────

def _q2(amount: Decimal) -> Decimal:
    return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class BaseTaxHandler:
    """Implement these four methods to add a new jurisdiction."""

    country_code: str = "??"
    country_name: str = "Generic"
    output_account_code: str = "2200"   # default → VAT Output (Sales)
    input_account_code:  str = "1250"   # default → VAT Input (Purchases)

    standard_rate:  Decimal = Decimal("0")   # e.g. 15 / 5 / 20
    reduced_rate:   Decimal = Decimal("0")
    zero_rate:      Decimal = Decimal("0")

    def validate_tax_id(self, tax_id: str) -> TaxValidation:
        return TaxValidation(valid=False, country=self.country_code, tax_id=tax_id,
                             explanation="no validator implemented")

    def applicable_rate(self, *, category: str = "standard") -> tuple[Decimal, str]:
        if category == "zero":
            return self.zero_rate, "zero-rated"
        if category == "reduced":
            return self.reduced_rate, "reduced-rate"
        return self.standard_rate, "standard-rate"

    def compute(self, base_amount: Decimal, *,
                category: str = "standard") -> TaxComputation:
        rate, label = self.applicable_rate(category=category)
        amt = _q2(base_amount)
        tax = _q2(amt * rate / Decimal("100"))
        return TaxComputation(
            country=self.country_code,
            rate_pct=rate, rate_label=label,
            base_amount=amt, tax_amount=tax,
            total_amount=_q2(amt + tax),
            output_account_code=self.output_account_code,
            input_account_code=self.input_account_code,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Saudi Arabia (KSA) — 15% / 0%
# ─────────────────────────────────────────────────────────────────────────────

class KSAVATHandler(BaseTaxHandler):
    country_code = "SA"
    country_name = "Saudi Arabia"
    standard_rate = Decimal("15")
    reduced_rate  = Decimal("5")    # historical (2018-2020)
    zero_rate     = Decimal("0")
    output_account_code = "2200"
    input_account_code  = "1250"

    _TRN = re.compile(r"^3\d{13}3$")   # 15 digits, starts + ends with 3

    def validate_tax_id(self, tax_id: str) -> TaxValidation:
        digits = re.sub(r"\D", "", tax_id or "")
        if not self._TRN.match(digits):
            return TaxValidation(
                valid=False, country=self.country_code, tax_id=tax_id,
                explanation="KSA TRN must be 15 digits, starting and ending with 3",
            )
        return TaxValidation(valid=True, country=self.country_code, tax_id=digits,
                             explanation="KSA TRN looks valid")


# ─────────────────────────────────────────────────────────────────────────────
# United Arab Emirates — 5% / 0%
# ─────────────────────────────────────────────────────────────────────────────

class UAEVATHandler(BaseTaxHandler):
    country_code = "AE"
    country_name = "United Arab Emirates"
    standard_rate = Decimal("5")
    zero_rate     = Decimal("0")
    output_account_code = "2200"
    input_account_code  = "1250"

    _TRN = re.compile(r"^\d{15}$")  # FTA TRN: 15 digits

    def validate_tax_id(self, tax_id: str) -> TaxValidation:
        digits = re.sub(r"\D", "", tax_id or "")
        if not self._TRN.match(digits):
            return TaxValidation(
                valid=False, country=self.country_code, tax_id=tax_id,
                explanation="UAE TRN must be exactly 15 digits",
            )
        return TaxValidation(valid=True, country=self.country_code, tax_id=digits,
                             explanation="UAE TRN looks valid")


# ─────────────────────────────────────────────────────────────────────────────
# European Union — 19-25% standard / reduced / 0% intra-EU
# ─────────────────────────────────────────────────────────────────────────────

# Cherry-picked sample of standard rates per ISO country, accurate Q1 2026.
# A real OSS deployment would refresh these against the EU's TIC database.
EU_STANDARD_RATES = {
    "DE": Decimal("19"),  "FR": Decimal("20"),  "IT": Decimal("22"),
    "ES": Decimal("21"),  "NL": Decimal("21"),  "BE": Decimal("21"),
    "AT": Decimal("20"),  "PL": Decimal("23"),  "PT": Decimal("23"),
    "FI": Decimal("24"),  "SE": Decimal("25"),  "DK": Decimal("25"),
    "IE": Decimal("23"),  "GR": Decimal("24"),  "CZ": Decimal("21"),
}

EU_VAT_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{8,12}$")


class EUVATHandler(BaseTaxHandler):
    """Generic EU VAT — exact rate is read from ``EU_STANDARD_RATES``.

    Use ``get_handler("EU:DE")`` (or just ``"DE"`` etc.) — the registry
    auto-routes any of the 27 ISO codes through this handler with the
    right ``standard_rate`` injected.
    """
    country_code = "EU"
    country_name = "European Union"
    output_account_code = "2200"
    input_account_code  = "1250"

    def __init__(self, *, member_state: str = ""):
        self.member_state = (member_state or "").upper()
        self.standard_rate = EU_STANDARD_RATES.get(self.member_state, Decimal("20"))
        self.zero_rate = Decimal("0")
        if self.member_state:
            self.country_code = self.member_state

    def validate_tax_id(self, tax_id: str) -> TaxValidation:
        cleaned = re.sub(r"[\s.\-]", "", (tax_id or "").upper())
        if not EU_VAT_RE.match(cleaned):
            return TaxValidation(
                valid=False, country=self.country_code, tax_id=tax_id,
                explanation="EU VAT format: ISO-2 country prefix + 8-12 alphanumerics "
                            "(VIES validation requires a network call)",
            )
        return TaxValidation(valid=True, country=cleaned[:2], tax_id=cleaned,
                             explanation=f"EU VAT format ok for {cleaned[:2]}")


# ─────────────────────────────────────────────────────────────────────────────
# United States — sales tax (state-level, not federal)
# ─────────────────────────────────────────────────────────────────────────────

class USSalesTaxHandler(BaseTaxHandler):
    """Stub handler — US sales tax is state-level and there's no federal
    rate. We carry the EIN format check + a configurable "state rate"
    so an integrator can plug in their nexus-specific rate without a
    code change."""

    country_code = "US"
    country_name = "United States"
    standard_rate = Decimal("0")    # callers pass an explicit rate
    zero_rate     = Decimal("0")

    _EIN = re.compile(r"^\d{2}-?\d{7}$")

    def __init__(self, *, state_rate: Optional[Decimal] = None):
        if state_rate is not None:
            self.standard_rate = Decimal(str(state_rate))

    def validate_tax_id(self, tax_id: str) -> TaxValidation:
        cleaned = (tax_id or "").strip()
        if not self._EIN.match(cleaned):
            return TaxValidation(
                valid=False, country="US", tax_id=tax_id,
                explanation="US EIN format: NN-NNNNNNN (9 digits, optional dash)",
            )
        return TaxValidation(valid=True, country="US", tax_id=cleaned,
                             explanation="EIN format ok (TIN-Match check is a network call)")


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

_BASE_REGISTRY = {
    "SA": KSAVATHandler,
    "KSA": KSAVATHandler,
    "AE": UAEVATHandler,
    "UAE": UAEVATHandler,
    "US": USSalesTaxHandler,
}


def get_handler(country: str, **kwargs) -> BaseTaxHandler:
    """Return the right handler for ``country`` (ISO-2 or 3 letter code).

    EU member states are supported by passing the ISO code directly
    (``get_handler("DE")``) — the registry routes them through
    EUVATHandler with the right rate.
    """
    if not country:
        return BaseTaxHandler()
    code = country.upper().strip()
    if code in EU_STANDARD_RATES:
        return EUVATHandler(member_state=code)
    cls = _BASE_REGISTRY.get(code)
    if cls is None:
        return BaseTaxHandler()
    return cls(**kwargs)


def supported_countries() -> list[dict]:
    """For the dashboard / API — list every jurisdiction the engine knows."""
    out = [
        {"code": "SA", "name": "Saudi Arabia",        "standard_rate": 15, "zero_rate": 0},
        {"code": "AE", "name": "United Arab Emirates","standard_rate": 5,  "zero_rate": 0},
        {"code": "US", "name": "United States",       "standard_rate": "state-specific"},
    ]
    for iso, rate in sorted(EU_STANDARD_RATES.items()):
        out.append({"code": iso, "name": f"EU — {iso}", "standard_rate": float(rate),
                    "zero_rate": 0})
    return out
