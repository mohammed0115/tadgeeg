"""
Normalization Service — Phase 1

Converts raw AI-extraction dicts into clean, typed NormalizedDocument instances:
  - Unifies field aliases (vendor_name / supplier / seller → vendor_name)
  - Normalises dates to YYYY-MM-DD
  - Strips currency symbols/commas and converts amounts to Decimal
  - Maps currency aliases to ISO-4217 codes
  - Handles None / empty values safely
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Field alias map ────────────────────────────────────────────────────────────
# Maps every variant the AI might return → canonical field name.

FIELD_ALIASES: dict[str, str] = {
    # Vendor / seller
    "vendor_name":       "vendor_name",
    "vendor":            "vendor_name",
    "supplier":          "vendor_name",
    "supplier_name":     "vendor_name",
    "seller":            "vendor_name",
    "seller_name":       "vendor_name",
    "issuer":            "vendor_name",
    "company":           "vendor_name",
    "from":              "vendor_name",

    # Buyer / customer
    "buyer_name":        "buyer_name",
    "buyer":             "buyer_name",
    "customer":          "buyer_name",
    "customer_name":     "buyer_name",
    "client":            "buyer_name",
    "client_name":       "buyer_name",
    "to":                "buyer_name",

    # Tax / VAT IDs
    "vendor_vat_number": "vendor_vat_number",
    "vendor_vat":        "vendor_vat_number",
    "supplier_vat":      "vendor_vat_number",
    "seller_vat":        "vendor_vat_number",
    "tax_number":        "vendor_vat_number",
    "tax_id":            "vendor_vat_number",
    "vat_number":        "vendor_vat_number",
    "cr_number":         "vendor_vat_number",

    "buyer_vat_number":  "buyer_vat_number",
    "buyer_vat":         "buyer_vat_number",
    "buyer_tax_id":      "buyer_vat_number",
    "customer_vat":      "buyer_vat_number",

    # Invoice identifiers
    "invoice_number":    "invoice_number",
    "invoice_no":        "invoice_number",
    "invoice_id":        "invoice_number",
    "inv_number":        "invoice_number",
    "inv_no":            "invoice_number",
    "number":            "invoice_number",
    "reference":         "invoice_number",
    "ref":               "invoice_number",

    # Dates
    "invoice_date":      "invoice_date",
    "date":              "invoice_date",
    "issue_date":        "invoice_date",
    "document_date":     "invoice_date",
    "billing_date":      "invoice_date",

    "due_date":          "due_date",
    "payment_due":       "due_date",
    "payment_due_date":  "due_date",

    # Amounts
    "subtotal":          "subtotal",
    "sub_total":         "subtotal",
    "net_amount":        "subtotal",
    "amount_before_vat": "subtotal",
    "amount_excl_vat":   "subtotal",

    "tax_amount":        "tax_amount",
    "vat_amount":        "tax_amount",
    "vat":               "tax_amount",
    "tax":               "tax_amount",
    "gst":               "tax_amount",

    "total_amount":      "total_amount",
    "total":             "total_amount",
    "grand_total":       "total_amount",
    "amount_due":        "total_amount",
    "amount_payable":    "total_amount",
    "final_amount":      "total_amount",

    "discount_amount":   "discount_amount",
    "discount":          "discount_amount",

    # Document classification
    "document_type":         "document_type",
    "doc_type":              "document_type",

    "classification_confidence": "classification_confidence",
    "confidence":                "classification_confidence",

    # Currency
    "currency":          "currency",
    "currency_code":     "currency",

    # QR / compliance
    "qr_code":           "qr_code",
    "zatca_qr":          "qr_code",
    "qr":                "qr_code",

    # Risk / audit
    "risk_score":        "risk_score",
    "fraud_score":       "fraud_score",
}


# ── Currency alias map ─────────────────────────────────────────────────────────

CURRENCY_ALIASES: dict[str, str] = {
    # Arabic
    "ريال":          "SAR",
    "ريال سعودي":    "SAR",
    "درهم":          "AED",
    "دينار":         "KWD",
    "دينار بحريني":  "BHD",
    "دينار أردني":   "JOD",
    "ريال قطري":     "QAR",
    "ريال عماني":    "OMR",
    "جنيه":          "EGP",
    # English abbreviations
    "sar":           "SAR",
    "aed":           "AED",
    "kwd":           "KWD",
    "bhd":           "BHD",
    "jod":           "JOD",
    "qar":           "QAR",
    "omr":           "OMR",
    "egp":           "EGP",
    "usd":           "USD",
    "eur":           "EUR",
    "gbp":           "GBP",
    # Long names
    "saudi riyal":   "SAR",
    "riyal":         "SAR",
    "dirham":        "AED",
    "dinar":         "KWD",
    "dollar":        "USD",
    "us dollar":     "USD",
    "euro":          "EUR",
    "pound":         "GBP",
}


# ── Date format patterns (tried in order) ─────────────────────────────────────

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y%m%d",
]


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class NormalizedDocument:
    """Typed, clean representation of a financial document."""

    # Identifiers
    invoice_number:       Optional[str]     = None
    document_type:        Optional[str]     = None
    classification_confidence: float        = 0.0

    # Parties
    vendor_name:          Optional[str]     = None
    vendor_vat_number:    Optional[str]     = None
    buyer_name:           Optional[str]     = None
    buyer_vat_number:     Optional[str]     = None

    # Dates (ISO format str or None)
    invoice_date:         Optional[str]     = None
    due_date:             Optional[str]     = None

    # Amounts
    subtotal:             Optional[Decimal] = None
    tax_amount:           Optional[Decimal] = None
    total_amount:         Optional[Decimal] = None
    discount_amount:      Optional[Decimal] = None

    # Currency
    currency:             str               = "SAR"

    # QR / compliance
    qr_code:              Optional[str]     = None

    # Risk
    risk_score:           float             = 0.0
    fraud_score:          float             = 0.0

    # Anything the normaliser didn't map
    extra_fields:         dict              = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialise to a plain dict (Decimal → str for JSON compatibility)."""
        return {
            "invoice_number":           self.invoice_number,
            "document_type":            self.document_type,
            "classification_confidence": self.classification_confidence,
            "vendor_name":              self.vendor_name,
            "vendor_vat_number":        self.vendor_vat_number,
            "buyer_name":               self.buyer_name,
            "buyer_vat_number":         self.buyer_vat_number,
            "invoice_date":             self.invoice_date,
            "due_date":                 self.due_date,
            "subtotal":                 str(self.subtotal) if self.subtotal is not None else None,
            "tax_amount":               str(self.tax_amount) if self.tax_amount is not None else None,
            "total_amount":             str(self.total_amount) if self.total_amount is not None else None,
            "discount_amount":          str(self.discount_amount) if self.discount_amount is not None else None,
            "currency":                 self.currency,
            "qr_code":                  self.qr_code,
            "risk_score":               self.risk_score,
            "fraud_score":              self.fraud_score,
            **self.extra_fields,
        }


# ── Service ───────────────────────────────────────────────────────────────────

class NormalizationService:
    """
    Converts a raw AI-extraction dict into a NormalizedDocument.

    Usage::

        svc = NormalizationService()
        doc = svc.normalize(raw_extraction_dict)
    """

    def normalize(self, raw: dict[str, Any]) -> NormalizedDocument:
        """
        Main entry point.

        :param raw: Arbitrary dict from FinancialAIEngine / OpenAI extraction.
        :returns:   NormalizedDocument with all fields normalised.
        """
        if not isinstance(raw, dict):
            logger.warning("NormalizationService received non-dict input: %s", type(raw))
            raw = {}

        unified = self._unify_field_names(raw)
        doc = NormalizedDocument()

        doc.invoice_number           = self._clean_str(unified.get("invoice_number"))
        doc.document_type            = self._clean_str(unified.get("document_type"))
        doc.classification_confidence = self._clean_float(unified.get("classification_confidence"), 0.0)

        doc.vendor_name              = self._clean_str(unified.get("vendor_name"))
        doc.vendor_vat_number        = self._clean_vat(unified.get("vendor_vat_number"))
        doc.buyer_name               = self._clean_str(unified.get("buyer_name"))
        doc.buyer_vat_number         = self._clean_vat(unified.get("buyer_vat_number"))

        doc.invoice_date             = self._normalize_date(unified.get("invoice_date"))
        doc.due_date                 = self._normalize_date(unified.get("due_date"))

        doc.subtotal                 = self._normalize_amount(unified.get("subtotal"))
        doc.tax_amount               = self._normalize_amount(unified.get("tax_amount"))
        doc.total_amount             = self._normalize_amount(unified.get("total_amount"))
        doc.discount_amount          = self._normalize_amount(unified.get("discount_amount"))

        doc.currency                 = self._normalize_currency(unified.get("currency", "SAR"))

        doc.qr_code                  = self._clean_str(unified.get("qr_code"))

        doc.risk_score               = self._clean_float(unified.get("risk_score"), 0.0)
        doc.fraud_score              = self._clean_float(unified.get("fraud_score"), 0.0)

        # Store unmapped keys in extra_fields
        known_canonical = set(FIELD_ALIASES.values())
        doc.extra_fields = {
            k: v for k, v in unified.items()
            if k not in known_canonical and v not in (None, "", [], {})
        }

        return doc

    # ── Private helpers ───────────────────────────────────────────────────────

    def _unify_field_names(self, raw: dict) -> dict:
        """Remap every key through FIELD_ALIASES; keep unmapped keys as-is."""
        unified: dict[str, Any] = {}
        for key, value in raw.items():
            canonical = FIELD_ALIASES.get(str(key).lower().strip(), key)
            # Last-write wins; prefer the canonical key if both exist
            if canonical not in unified or unified[canonical] in (None, ""):
                unified[canonical] = value
        return unified

    def _normalize_date(self, value: Any) -> Optional[str]:
        """Parse any date-like value to 'YYYY-MM-DD' string, or None."""
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()

        text = str(value).strip()
        if not text:
            return None

        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        logger.debug("NormalizationService: could not parse date '%s'", text)
        return None

    def _normalize_amount(self, value: Any) -> Optional[Decimal]:
        """
        Clean a monetary value to Decimal.
        Strips: SAR, AED, ريال, $, €, £, commas, spaces, trailing zeros are kept.
        """
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return None

        text = str(value).strip()
        if not text:
            return None

        # Remove currency symbols and words
        for symbol in [
            "SAR", "AED", "KWD", "BHD", "QAR", "OMR", "JOD", "EGP",
            "USD", "EUR", "GBP",
            "ريال سعودي", "ريال", "درهم", "دينار", "جنيه",
            "$", "€", "£", "﷼",
        ]:
            text = text.replace(symbol, "")

        # Remove thousands separators (commas) but keep decimal dot
        text = text.replace(",", "").strip()

        # Handle Arabic-Indic numerals
        arabic_indic_map = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        text = text.translate(arabic_indic_map)

        try:
            return Decimal(text)
        except InvalidOperation:
            logger.debug("NormalizationService: could not parse amount '%s'", value)
            return None

    def _normalize_currency(self, value: Any) -> str:
        """Map currency aliases to ISO-4217 codes. Defaults to SAR."""
        if not value:
            return "SAR"
        text = str(value).strip()
        # Direct ISO match (3 uppercase letters)
        if re.match(r"^[A-Z]{3}$", text):
            return text
        # Try alias map
        lookup = text.lower().strip()
        return CURRENCY_ALIASES.get(lookup, CURRENCY_ALIASES.get(text, "SAR"))

    def _clean_vat(self, value: Any) -> Optional[str]:
        """Return digits-only Saudi Tax ID, or None."""
        if value is None:
            return None
        text = re.sub(r"[^\d]", "", str(value))
        return text if text else None

    def _clean_str(self, value: Any) -> Optional[str]:
        """Strip whitespace; return None for empty/None values."""
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _clean_float(self, value: Any, default: float = 0.0) -> float:
        """Safe float coercion with a default."""
        if value is None:
            return default
        try:
            result = float(value)
            return result if not (result != result) else default  # NaN guard
        except (TypeError, ValueError):
            return default
