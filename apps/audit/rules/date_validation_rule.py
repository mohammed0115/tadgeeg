"""
R005 — Date Validation Rule

Validates document dates for anomalies:
  D01 — Date is in the future
  D02 — Date is before organisation registration
  D03 — Date is more than 2 years in the past (stale invoice)
  D04 — Invoice date is after the due date
  D05 — Year-end concentration (>30% of invoices in last 5 days of fiscal year)

Severity: HIGH (future/pre-registration) → MEDIUM (stale/year-end)
Applies to: all document types
"""

import logging
from datetime import date, timedelta
from typing import Optional

from .base_rule import AuditRule, RuleResult, Severity

logger = logging.getLogger("finai")

STALE_INVOICE_YEARS = 2          # Invoices older than this are flagged
YEAR_END_DAYS = 5                 # Last N days of fiscal year
YEAR_END_CONCENTRATION_THRESHOLD = 0.30   # 30% of invoices


class DateValidationRule(AuditRule):
    """
    Multi-check document date validator.
    """

    rule_id = "R005"
    rule_name = "Date Anomaly Detection"
    severity = Severity.HIGH
    applies_to = set()   # All document types
    description = (
        "Detects date-related anomalies including future dates, "
        "pre-registration dates, stale invoices, and year-end concentrations."
    )

    def evaluate(
        self,
        document: dict,
        organization_id: int = None,
        context: dict = None,
    ) -> RuleResult:
        context = context or {}

        date_str = document.get("date")
        if not date_str:
            return self._skip("No date found in document")

        try:
            doc_date = date.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            return self._fail(
                explanation=f"Document date '{date_str}' is not a valid date format",
                details={"invalid_date": date_str},
            )

        today = date.today()
        anomalies: list[str] = []
        details: dict = {"document_date": str(doc_date), "today": str(today)}

        # ── D01: Future date ──────────────────────────────────────────────────
        if doc_date > today:
            self.severity = Severity.HIGH
            days_ahead = (doc_date - today).days
            anomalies.append(f"Document date {doc_date} is {days_ahead} day(s) in the future")

        # ── D02: Before organisation registration ─────────────────────────────
        # A pre-registration date is only suspicious for *recent* documents.
        # When importing legacy data from an old ERP into a freshly-created org
        # tenant, every historical invoice is necessarily older than the org
        # record — flagging that as HIGH gives false positives on every imported
        # row. We skip D02 for documents older than the stale threshold (D03
        # already covers them as MEDIUM); D02 fires only when a recent document
        # claims a date that pre-dates the org, which is the real forgery signal.
        org_reg_date = self._get_org_registration_date(organization_id)
        if org_reg_date:
            details["org_registration_date"] = str(org_reg_date)
            stale_cutoff = today - timedelta(days=STALE_INVOICE_YEARS * 365)
            is_stale = doc_date < stale_cutoff
            # Allow 30 days grace (invoices issued just before registration are ok)
            if (not is_stale) and doc_date < org_reg_date - timedelta(days=30):
                self.severity = Severity.HIGH
                anomalies.append(
                    f"Document date {doc_date} is before organisation "
                    f"registration date {org_reg_date}"
                )

        # ── D03: Stale invoice ────────────────────────────────────────────────
        stale_cutoff = today - timedelta(days=STALE_INVOICE_YEARS * 365)
        if doc_date < stale_cutoff:
            self.severity = Severity.MEDIUM
            years_old = (today - doc_date).days // 365
            anomalies.append(
                f"Document date {doc_date} is {years_old} year(s) old (stale)"
            )

        # ── D04: Invoice date after due date ──────────────────────────────────
        due_date_str = document.get("due_date")
        if due_date_str:
            try:
                due_date = date.fromisoformat(str(due_date_str))
                if doc_date > due_date:
                    self.severity = Severity.MEDIUM
                    anomalies.append(
                        f"Invoice date {doc_date} is after the due date {due_date}"
                    )
                details["due_date"] = str(due_date)
            except (ValueError, TypeError):
                pass

        # ── D05: Year-end concentration ───────────────────────────────────────
        ye_result = self._check_year_end_concentration(doc_date, organization_id)
        if ye_result:
            self.severity = min(self.severity, Severity.MEDIUM)
            anomalies.append(ye_result)

        if anomalies:
            return self._fail(
                explanation="; ".join(anomalies),
                details=details,
            )

        return self._pass(details=details)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_org_registration_date(self, organization_id: int) -> Optional[date]:
        if not organization_id:
            return None
        try:
            from apps.authentication.models import Organization
            org = Organization.objects.get(pk=organization_id)
            created = getattr(org, "created_at", None)
            if created:
                return created.date() if hasattr(created, "date") else created
        except Exception as exc:
            logger.debug("[DateValidationRule] org reg date error: %s", exc)
        return None

    def _check_year_end_concentration(self, doc_date: date, organization_id: int) -> str:
        """Check if this document falls in the last days of the fiscal year."""
        if not organization_id:
            return ""
        try:
            from apps.authentication.models import Organization
            from apps.invoices.models import Invoice
            from datetime import datetime

            org = Organization.objects.get(pk=organization_id)
            fiscal_start = getattr(org, "fiscal_year_start", 1)  # Default January
            fiscal_start = int(fiscal_start or 1)

            # Compute fiscal year end date
            year = doc_date.year
            fiscal_end_month = (fiscal_start - 1) % 12 or 12
            fiscal_end_year = year if fiscal_start == 1 else year
            if fiscal_end_month == 12:
                fiscal_end = date(fiscal_end_year, 12, 31)
            else:
                fiscal_end = date(fiscal_end_year, fiscal_end_month + 1, 1) - timedelta(days=1)

            year_end_start = fiscal_end - timedelta(days=YEAR_END_DAYS)

            if year_end_start <= doc_date <= fiscal_end:
                # Count invoices in this window
                window_count = Invoice.objects.filter(
                    organization_id=organization_id,
                    invoice_date__range=(year_end_start, fiscal_end),
                ).count()
                total_year = Invoice.objects.filter(
                    organization_id=organization_id,
                    invoice_date__year=fiscal_end.year,
                ).count()
                if total_year > 10:
                    concentration = window_count / total_year
                    if concentration >= YEAR_END_CONCENTRATION_THRESHOLD:
                        return (
                            f"Year-end invoice concentration: {window_count} invoices "
                            f"in last {YEAR_END_DAYS} days of fiscal year "
                            f"({concentration:.0%} of annual total)"
                        )
        except Exception as exc:
            logger.debug("[DateValidationRule] year-end check error: %s", exc)
        return ""
