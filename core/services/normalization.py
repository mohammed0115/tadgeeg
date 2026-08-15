"""Deterministic normalization utilities for extracted invoice data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable


ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
ARABIC_MONTHS = {
    "يناير": "January",
    "فبراير": "February",
    "مارس": "March",
    "ابريل": "April",
    "أبريل": "April",
    "مايو": "May",
    "يونيو": "June",
    "يوليو": "July",
    "أغسطس": "August",
    "اغسطس": "August",
    "سبتمبر": "September",
    "أكتوبر": "October",
    "اكتوبر": "October",
    "نوفمبر": "November",
    "ديسمبر": "December",
}
NULL_LIKE_VALUES = {"", "null", "none", "n/a", "na", "-", "--", "غير متوفر"}


@dataclass
class NormalizationResult:
    normalized_data: dict[str, Any]
    raw_values: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    aliases_applied: dict[str, str] = field(default_factory=dict)

    def to_serializable_dict(self) -> dict[str, Any]:
        data = dict(self.normalized_data)
        data["raw_values"] = self.raw_values
        data["normalization_warnings"] = self.warnings
        data["aliases_applied"] = self.aliases_applied
        return _make_json_safe(data)


class NormalizationService:
    """Normalize heterogeneous extraction payloads into a canonical invoice schema."""

    FIELD_ALIASES = {
        "vendor_name": ("vendor_name", "supplier", "supplier_name", "merchant_name", "issued_by"),
        "vendor_vat_number": ("vendor_vat_number", "vendor_tax_id", "supplier_vat", "supplier_tax_id", "tax_id"),
        "invoice_number": ("invoice_number", "document_number", "reference", "invoice_no", "reference_number"),
        "invoice_date": ("invoice_date", "date", "issued_at", "invoice_datetime"),
        "due_date": ("due_date", "payment_due_date"),
        "currency": ("currency", "currency_code", "invoice_currency"),
        "subtotal": ("subtotal", "net_amount", "amount_before_tax"),
        "vat_amount": ("vat_amount", "tax_amount", "vat", "total_vat"),
        "vat_rate": ("vat_rate", "tax_rate"),
        "discount": ("discount", "discount_amount"),
        "total_amount": ("total_amount", "amount", "grand_total", "invoice_total"),
        "customer_name": ("customer_name", "bill_to", "customer"),
        "customer_vat_number": ("customer_vat_number", "customer_tax_id"),
        "payment_method": ("payment_method", "payment_type"),
        "line_items": ("line_items", "items", "rows"),
        "has_qr_code": ("has_qr_code", "qr_code_presence", "qr_present"),
        "confidence_reasoning": ("confidence_reasoning", "reasoning"),
        "uncertainty_flags": ("uncertainty_flags", "warnings", "flags"),
    }

    CURRENCY_ALIASES = {
        "sar": "SAR",
        "ر.س": "SAR",
        "ر. س": "SAR",
        "ريال": "SAR",
        "ريال سعودي": "SAR",
        "saudi riyal": "SAR",
        "aed": "AED",
        "درهم": "AED",
        "uae dirham": "AED",
        "usd": "USD",
        "$": "USD",
        "eur": "EUR",
        "€": "EUR",
        "kwd": "KWD",
        "qar": "QAR",
        "omr": "OMR",
        "bhd": "BHD",
    }

    DATE_FORMATS = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%B %d, %Y",
    )

    def normalize(self, payload: dict[str, Any] | None, *, default_currency: str = "SAR") -> NormalizationResult:
        payload = payload or {}
        raw_values: dict[str, Any] = {}
        warnings: list[str] = []
        aliases_applied: dict[str, str] = {}

        def pick(field_name: str, default: Any = None) -> Any:
            aliases = self.FIELD_ALIASES.get(field_name, (field_name,))
            for alias in aliases:
                if alias in payload and not self._is_null_like(payload.get(alias)):
                    raw_values[field_name] = payload.get(alias)
                    aliases_applied[field_name] = alias
                    return payload.get(alias)
            raw_values[field_name] = default
            return default

        normalized: dict[str, Any] = {
            "vendor_name": self._clean_text(pick("vendor_name", "")),
            "vendor_vat_number": self._clean_text(pick("vendor_vat_number", "")),
            "invoice_number": self._clean_text(pick("invoice_number", "")),
            "invoice_date": self._normalize_date(pick("invoice_date"), warnings, "invoice_date"),
            "due_date": self._normalize_date(pick("due_date"), warnings, "due_date"),
            "currency": self._normalize_currency(pick("currency", default_currency), warnings, default_currency),
            "subtotal": self._normalize_decimal(pick("subtotal"), warnings, "subtotal"),
            "vat_amount": self._normalize_decimal(pick("vat_amount"), warnings, "vat_amount"),
            "vat_rate": self._normalize_decimal(pick("vat_rate"), warnings, "vat_rate"),
            "discount": self._normalize_decimal(pick("discount"), warnings, "discount"),
            "total_amount": self._normalize_decimal(pick("total_amount"), warnings, "total_amount"),
            "customer_name": self._clean_text(pick("customer_name", "")),
            "customer_vat_number": self._clean_text(pick("customer_vat_number", "")),
            "payment_method": self._clean_text(pick("payment_method", "")),
            "line_items": self._normalize_line_items(pick("line_items", []), warnings),
            "has_qr_code": self._normalize_bool(pick("has_qr_code", False)),
            "confidence_reasoning": self._clean_text(pick("confidence_reasoning", "")),
            "uncertainty_flags": self._normalize_flags(pick("uncertainty_flags", [])),
            "raw_text": self._clean_text(payload.get("raw_text", ""), collapse=False),
            "extraction_method": self._clean_text(
                payload.get("extraction_method") or payload.get("_extraction_method") or payload.get("method") or "unknown"
            ),
            # "unknown", not "invoice" — and note the two lines it sits between,
            # which already say "unknown" for exactly this situation.
            #
            # This is the one field that decides WHICH RULES ARE APPLIED. A
            # guess here is not a cosmetic default: it made 17 of 34 measured
            # documents into invoices, and R017 then demanded a ZATCA QR code
            # from a contract and R018 demanded invoice fields from a customer
            # statement. Every one of those is a false finding presented to an
            # auditor.
            #
            # Worse, document_classifier.py read this guess back and returned it
            # as a *structural determination at 0.90 confidence* — so the guess
            # was laundered into a measurement. See
            # docs/CLASSIFICATION_MEASUREMENT.md.
            #
            # "unknown" is not a Document.DocumentType choice, and it does not
            # need to be: _persist_result routes it through
            # type_map.get(ai_type, "other"), which stores "other". The value
            # exists to say "nobody determined this", which is true, and which
            # "invoice" was not.
            "document_type": self._clean_text(payload.get("document_type", "unknown")) or "unknown",
            "language": self._clean_text(payload.get("language", "unknown")) or "unknown",
        }

        if normalized["subtotal"] is None and normalized["total_amount"] is not None and normalized["vat_amount"] is not None:
            normalized["subtotal"] = normalized["total_amount"] - normalized["vat_amount"] + (normalized["discount"] or Decimal("0"))
            warnings.append("Subtotal inferred from total amount, VAT amount, and discount.")

        if not normalized["total_amount"] and normalized["subtotal"] is not None and normalized["vat_amount"] is not None:
            normalized["total_amount"] = normalized["subtotal"] + normalized["vat_amount"] - (normalized["discount"] or Decimal("0"))

        if normalized["vat_rate"] is None and normalized["subtotal"] and normalized["vat_amount"]:
            try:
                normalized["vat_rate"] = ((normalized["vat_amount"] / normalized["subtotal"]) * Decimal("100")).quantize(Decimal("0.01"))
            except InvalidOperation:
                warnings.append("Could not infer VAT rate from subtotal and VAT amount.")

        return NormalizationResult(
            normalized_data=normalized,
            raw_values=raw_values,
            warnings=warnings,
            aliases_applied=aliases_applied,
        )

    def _normalize_date(self, value: Any, warnings: list[str], field_name: str) -> str | None:
        if self._is_null_like(value):
            return None

        text = self._prepare_text(value)
        for ar_month, en_month in ARABIC_MONTHS.items():
            text = text.replace(ar_month, en_month)

        ambiguous_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
        if ambiguous_match:
            first = int(ambiguous_match.group(1))
            second = int(ambiguous_match.group(2))
            if first <= 12 and second <= 12 and first != second:
                warnings.append(f"Ambiguous date format for {field_name}: '{value}'. Assumed day-first.")

        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        warnings.append(f"Could not normalize {field_name}: '{value}'.")
        return text if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else None

    def _normalize_decimal(self, value: Any, warnings: list[str], field_name: str) -> Decimal | None:
        if self._is_null_like(value):
            return None

        text = self._prepare_text(value)
        text = (
            text.replace("SAR", "")
            .replace("AED", "")
            .replace("USD", "")
            .replace("QAR", "")
            .replace("KWD", "")
            .replace("ريال", "")
            .replace("ر.س", "")
            .replace("ر. س", "")
            .replace("%", "")
        )
        text = text.replace(",", "")
        text = re.sub(r"[^\d\.\-]", "", text)
        if not text:
            warnings.append(f"Could not normalize {field_name}: '{value}'.")
            return None

        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            warnings.append(f"Could not normalize {field_name}: '{value}'.")
            return None

    def _normalize_currency(self, value: Any, warnings: list[str], default: str) -> str:
        if self._is_null_like(value):
            return default
        text = self._prepare_text(value).lower()
        normalized = self.CURRENCY_ALIASES.get(text)
        if normalized:
            return normalized
        if len(text) == 3 and text.isalpha():
            return text.upper()
        warnings.append(f"Unsupported currency '{value}'. Defaulted to {default}.")
        return default

    def _normalize_line_items(self, value: Any, warnings: list[str]) -> list[dict[str, Any]]:
        if not value:
            return []
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            warnings.append("Line items payload was not a list and was ignored.")
            return []

        items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            quantity = self._normalize_decimal(item.get("quantity"), warnings, "line_item.quantity")
            unit_price = self._normalize_decimal(item.get("unit_price"), warnings, "line_item.unit_price")
            amount = self._normalize_decimal(
                item.get("total") or item.get("amount") or item.get("line_total"),
                warnings,
                "line_item.amount",
            )
            items.append(
                {
                    "description": self._clean_text(item.get("description", "")),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "amount": amount,
                }
            )
        return items

    def _normalize_flags(self, value: Any) -> list[str]:
        if self._is_null_like(value):
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, Iterable):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    def _normalize_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = self._prepare_text(value).lower()
        return text in {"1", "true", "yes", "y", "نعم", "موجود"}

    def _clean_text(self, value: Any, *, collapse: bool = True) -> str:
        if self._is_null_like(value):
            return ""
        text = self._prepare_text(value)
        return re.sub(r"\s+", " ", text).strip() if collapse else text.strip()

    def _prepare_text(self, value: Any) -> str:
        return str(value).translate(ARABIC_DIGIT_MAP).strip()

    def _is_null_like(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and value.strip().lower() in NULL_LIKE_VALUES:
            return True
        return False


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _make_json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_make_json_safe(item) for item in value]
    return value
