"""
Validation Engine — Phase 2

Runs a set of financial validation rules against a NormalizedDocument.
Each rule is an independent Strategy (ABC) that returns a ValidationResult.

Built-in rules
--------------
  V001  — Amount consistency  (subtotal + tax ≈ total)
  V002  — Saudi Tax ID format (15 digits, starts with 3)
  V003  — Invoice date range  (not future, not older than 5 years)
  V004  — ZATCA QR code       (present on invoices ≥ 1000 SAR)
  V005  — Supported currency  (SAR, AED, KWD, USD, EUR, GBP …)

Usage::

    from core.services.normalization_service import NormalizationService
    from core.services.validation_engine import ValidationEngine

    doc = NormalizationService().normalize(raw_dict)
    report = ValidationEngine().validate(doc)

    for result in report.results:
        print(result.rule_id, result.passed, result.severity, result.message)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from core.services.normalization_service import NormalizedDocument

logger = logging.getLogger(__name__)


# ── ValidationResult ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    rule_id:   str
    rule_name: str
    passed:    bool
    severity:  str      # "critical" | "high" | "medium" | "low" | "info"
    message:   str
    details:   dict     = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.passed


# ── ValidationReport ──────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    results:          list[ValidationResult] = field(default_factory=list)

    @property
    def passed(self) -> list[ValidationResult]:
        return [r for r in self.results if r.passed]

    @property
    def failed(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.passed]

    @property
    def critical_failures(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.passed and r.severity == "critical"]

    @property
    def has_critical_failures(self) -> bool:
        return bool(self.critical_failures)

    @property
    def summary(self) -> dict:
        return {
            "total_rules":        len(self.results),
            "passed":             len(self.passed),
            "failed":             len(self.failed),
            "critical_failures":  len(self.critical_failures),
            "has_critical":       self.has_critical_failures,
        }

    def to_list(self) -> list[dict]:
        return [
            {
                "rule_id":   r.rule_id,
                "rule_name": r.rule_name,
                "passed":    r.passed,
                "severity":  r.severity,
                "message":   r.message,
                "details":   r.details,
            }
            for r in self.results
        ]


# ── Abstract Base Rule ────────────────────────────────────────────────────────

class ValidationRule(ABC):
    rule_id:   str
    rule_name: str
    severity:  str  # default severity when rule fails

    @abstractmethod
    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        ...

    def _pass(self, **details) -> ValidationResult:
        return ValidationResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            passed=True,
            severity="info",
            message="OK",
            details=details,
        )

    def _fail(self, message: str, **details) -> ValidationResult:
        return ValidationResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            passed=False,
            severity=self.severity,
            message=message,
            details=details,
        )

    def _skip(self, reason: str) -> ValidationResult:
        """Rule not applicable — treated as passed."""
        return ValidationResult(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            passed=True,
            severity="info",
            message=f"Skipped: {reason}",
        )


# ── Rule V001: Amount Consistency ─────────────────────────────────────────────

class AmountConsistencyRule(ValidationRule):
    """
    V001 — subtotal + tax_amount should equal total_amount (±1 SAR tolerance).
    Skipped if any component is missing.
    """

    rule_id   = "V001"
    rule_name = "Amount Consistency"
    severity  = "high"

    TOLERANCE = Decimal("1.00")

    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        if doc.subtotal is None or doc.tax_amount is None or doc.total_amount is None:
            return self._skip("One or more amount fields are absent")

        expected = doc.subtotal + doc.tax_amount
        diff = abs(expected - doc.total_amount)

        if diff <= self.TOLERANCE:
            return self._pass(
                subtotal=str(doc.subtotal),
                tax_amount=str(doc.tax_amount),
                total_amount=str(doc.total_amount),
            )

        return self._fail(
            f"Amount mismatch: subtotal ({doc.subtotal}) + tax ({doc.tax_amount}) "
            f"= {expected}, but total is {doc.total_amount} (diff={diff})",
            expected=str(expected),
            actual=str(doc.total_amount),
            difference=str(diff),
        )


# ── Rule V002: Saudi Tax ID Format ────────────────────────────────────────────

class SaudiTaxIdRule(ValidationRule):
    """
    V002 — Saudi Tax Registration Number must be exactly 15 digits and start with 3.
    Skipped if both vendor_vat_number and buyer_vat_number are absent.
    """

    rule_id   = "V002"
    rule_name = "Saudi Tax ID Format"
    severity  = "critical"

    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        ids_to_check = []
        if doc.vendor_vat_number:
            ids_to_check.append(("vendor", doc.vendor_vat_number))
        if doc.buyer_vat_number:
            ids_to_check.append(("buyer", doc.buyer_vat_number))

        if not ids_to_check:
            return self._skip("No VAT numbers present")

        invalid = []
        for party, tax_id in ids_to_check:
            digits = "".join(c for c in tax_id if c.isdigit())
            if len(digits) != 15 or not digits.startswith("3"):
                invalid.append({
                    "party": party,
                    "value": tax_id,
                    "reason": "Must be 15 digits starting with 3",
                })

        if not invalid:
            return self._pass(checked=[x[1] for x in ids_to_check])

        return self._fail(
            f"Invalid Saudi Tax ID(s): {[e['value'] for e in invalid]}",
            invalid_ids=invalid,
        )


# ── Rule V003: Invoice Date Range ─────────────────────────────────────────────

class InvoiceDateRangeRule(ValidationRule):
    """
    V003 — Invoice date must be:
      - Not in the future
      - Not more than 5 years in the past
    Skipped if invoice_date is absent.
    """

    rule_id   = "V003"
    rule_name = "Invoice Date Range"
    severity  = "medium"

    MAX_YEARS_PAST = 5

    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        if not doc.invoice_date:
            return self._skip("invoice_date is absent")

        try:
            inv_date = date.fromisoformat(doc.invoice_date)
        except ValueError:
            return self._fail(
                f"invoice_date '{doc.invoice_date}' is not a valid ISO date",
                value=doc.invoice_date,
            )

        today = date.today()
        if inv_date > today:
            return self._fail(
                f"Invoice date {inv_date} is in the future (today={today})",
                invoice_date=str(inv_date),
                today=str(today),
            )

        years_diff = (today - inv_date).days / 365.25
        if years_diff > self.MAX_YEARS_PAST:
            return self._fail(
                f"Invoice date {inv_date} is more than {self.MAX_YEARS_PAST} years old",
                invoice_date=str(inv_date),
                years_old=round(years_diff, 1),
            )

        return self._pass(invoice_date=str(inv_date))


# ── Rule V004: ZATCA QR Code Presence ────────────────────────────────────────

class ZatcaQrCodeRule(ValidationRule):
    """
    V004 — For Saudi invoices (SAR currency) with total ≥ 1000 SAR,
            a ZATCA QR code should be present.
    """

    rule_id   = "V004"
    rule_name = "ZATCA QR Code"
    severity  = "high"

    THRESHOLD = Decimal("1000.00")

    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        # Only applies to SAR-denominated invoices above threshold
        if doc.currency != "SAR":
            return self._skip(f"Currency is {doc.currency}, not SAR")

        if doc.total_amount is None:
            return self._skip("total_amount is absent")

        if doc.total_amount < self.THRESHOLD:
            return self._skip(f"Total ({doc.total_amount}) is below threshold ({self.THRESHOLD})")

        if doc.document_type and "invoice" not in str(doc.document_type).lower():
            return self._skip(f"Document type '{doc.document_type}' is not an invoice")

        if doc.qr_code:
            return self._pass(qr_length=len(doc.qr_code))

        return self._fail(
            f"ZATCA QR code is required for SAR invoices ≥ {self.THRESHOLD} but is missing",
            total_amount=str(doc.total_amount),
            currency=doc.currency,
        )


# ── Rule V005: Supported Currency ────────────────────────────────────────────

class SupportedCurrencyRule(ValidationRule):
    """
    V005 — Currency must be in the platform's supported list.
    """

    rule_id   = "V005"
    rule_name = "Supported Currency"
    severity  = "medium"

    SUPPORTED = {
        "SAR", "AED", "KWD", "BHD", "QAR", "OMR", "JOD", "EGP",
        "USD", "EUR", "GBP",
    }

    def evaluate(self, doc: NormalizedDocument) -> ValidationResult:
        if doc.currency in self.SUPPORTED:
            return self._pass(currency=doc.currency)

        return self._fail(
            f"Currency '{doc.currency}' is not supported. "
            f"Supported: {sorted(self.SUPPORTED)}",
            currency=doc.currency,
            supported=sorted(self.SUPPORTED),
        )


# ── ValidationEngine ─────────────────────────────────────────────────────────

class ValidationEngine:
    """
    Runs all registered ValidationRule strategies against a NormalizedDocument.

    Custom rules can be added via ``register_rule()``.
    """

    DEFAULT_RULES: list[type[ValidationRule]] = [
        AmountConsistencyRule,
        SaudiTaxIdRule,
        InvoiceDateRangeRule,
        ZatcaQrCodeRule,
        SupportedCurrencyRule,
    ]

    def __init__(self, extra_rules: Optional[list[ValidationRule]] = None):
        self._rules: list[ValidationRule] = [cls() for cls in self.DEFAULT_RULES]
        if extra_rules:
            self._rules.extend(extra_rules)

    def register_rule(self, rule: ValidationRule) -> None:
        """Append a custom rule at runtime."""
        self._rules.append(rule)

    def validate(self, doc: NormalizedDocument) -> ValidationReport:
        """
        Evaluate all rules against *doc*.

        :returns: ValidationReport with all results.
        """
        report = ValidationReport()
        for rule in self._rules:
            try:
                result = rule.evaluate(doc)
            except Exception as exc:
                logger.exception(
                    "ValidationEngine: rule %s raised an exception: %s",
                    rule.rule_id, exc,
                )
                result = ValidationResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    passed=False,
                    severity="critical",
                    message=f"Rule evaluation error: {exc}",
                )
            report.results.append(result)

        logger.debug(
            "ValidationEngine: %d rules evaluated, %d failed (%d critical)",
            len(report.results),
            len(report.failed),
            len(report.critical_failures),
        )
        return report
