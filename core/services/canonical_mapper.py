"""
CanonicalMapper — translates raw AI/OCR extraction → canonical field dict.

This is the central translation layer between raw extraction and rule execution.
All document types pass through here after AI extraction.
"""
from __future__ import annotations
import logging
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger("canonical_mapper")


class Transform:
    """Registry of named value transforms."""

    @staticmethod
    def direct(value: Any, args: dict = {}, raw: dict = {}) -> Any:
        return value

    @staticmethod
    def to_string(value: Any, args: dict = {}, raw: dict = {}) -> Optional[str]:
        if value is None:
            return None
        result = str(value).strip()
        return result if result else None

    @staticmethod
    def to_decimal(value: Any, args: dict = {}, raw: dict = {}) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            cleaned = str(value).replace(",", "").strip()
            return Decimal(cleaned) if cleaned else None
        except InvalidOperation:
            return None

    @staticmethod
    def to_integer(value: Any, args: dict = {}, raw: dict = {}) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def to_date(value: Any, args: dict = {}, raw: dict = {}) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        formats = args.get("formats", [
            "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
            "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y",
        ])
        raw_str = str(value).strip()
        for fmt in formats:
            try:
                return datetime.strptime(raw_str, fmt).date()
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def to_bool(value: Any, args: dict = {}, raw: dict = {}) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "نعم", "y")

    @staticmethod
    def to_uppercase(value: Any, args: dict = {}, raw: dict = {}) -> Optional[str]:
        if value is None:
            return None
        result = str(value).strip().upper()
        return result if result else None

    @staticmethod
    def first_non_null(value: Any, args: dict = {}, raw: dict = {}) -> Any:
        """Try primary value first, then fallback keys from raw_data."""
        if value is not None and str(value).strip():
            return value
        for key in args.get("fallback_keys", []):
            v = raw.get(key)
            if v is not None and str(v).strip():
                return v
        return None

    _REGISTRY = {
        "direct":         direct.__func__,
        "string":         to_string.__func__,
        "decimal":        to_decimal.__func__,
        "integer":        to_integer.__func__,
        "date_parse":     to_date.__func__,
        "bool":           to_bool.__func__,
        "uppercase":      to_uppercase.__func__,
        "first_non_null": first_non_null.__func__,
    }

    @classmethod
    def apply(cls, name: str, value: Any, args: dict = {}, raw: dict = {}) -> Any:
        fn = cls._REGISTRY.get(name, cls.direct.__func__)
        try:
            return fn(value, args, raw)
        except Exception as exc:
            logger.warning("Transform '%s' failed for value %r: %s", name, value, exc)
            return None


class CanonicalMapper:
    """
    Maps raw AI/OCR output dict → canonical field dict.

    All canonical fields are present in output; unmapped fields are None.
    Reads mappings from DB (DocumentTypeFieldMapping) if available,
    falls back to FALLBACK_MAPPING for bootstrapping.
    """

    # In-memory fallback — used until DB mappings are seeded
    FALLBACK_MAPPING: dict[str, dict[str, list[dict]]] = {
        "invoice": {
            "document_number":    [{"source": "invoice_number",     "transform": "string"}],
            "document_date":      [{"source": "invoice_date",       "transform": "date_parse"}],
            "due_date":           [{"source": "due_date",           "transform": "date_parse"}],
            "vendor_name":        [{"source": "vendor_name",        "transform": "first_non_null",
                                    "args": {"fallback_keys": ["supplier_name", "merchant_name", "vendor_name_ar"]}}],
            "vendor_tax_number":  [{"source": "vendor_vat_number",  "transform": "string"}],
            "vendor_cr_number":   [{"source": "vendor_cr_number",   "transform": "string"}],
            "customer_name":      [{"source": "customer_name",      "transform": "string"}],
            "customer_tax_number":[{"source": "customer_vat_number","transform": "string"}],
            "currency_code":      [{"source": "currency",           "transform": "uppercase"}],
            "subtotal_amount":    [{"source": "subtotal",           "transform": "decimal"}],
            "tax_rate":           [{"source": "vat_rate",           "transform": "decimal"}],
            "tax_amount":         [{"source": "vat_amount",         "transform": "decimal"}],
            "discount_amount":    [{"source": "discount",           "transform": "decimal"}],
            "net_amount":         [{"source": "total_amount",       "transform": "decimal"}],
            "qr_code_valid":      [{"source": "qr_code_valid",      "transform": "bool"}],
            "cost_center":        [{"source": "cost_center",        "transform": "string"}],
            "department":         [{"source": "department",         "transform": "string"}],
            "account_code":       [{"source": "account_code",       "transform": "string"}],
        },
        "purchase_order": {
            "document_number":    [{"source": "po_number",          "transform": "string"}],
            "document_date":      [{"source": "po_date",            "transform": "date_parse"}],
            "issue_date":         [{"source": "po_date",            "transform": "date_parse"}],
            "delivery_date":      [{"source": "delivery_date",      "transform": "date_parse"}],
            "vendor_name":        [{"source": "vendor_name",        "transform": "string"}],
            "vendor_tax_number":  [{"source": "vendor_vat_number",  "transform": "string"}],
            "vendor_cr_number":   [{"source": "vendor_cr_number",   "transform": "string"}],
            "employee_name":      [{"source": "requester_name",     "transform": "string"}],
            "department":         [{"source": "department",         "transform": "string"}],
            "cost_center":        [{"source": "cost_center",        "transform": "string"}],
            "account_code":       [{"source": "account_code",       "transform": "string"}],
            "currency_code":      [{"source": "currency",           "transform": "uppercase"}],
            "subtotal_amount":    [{"source": "subtotal",           "transform": "decimal"}],
            "tax_amount":         [{"source": "vat_amount",         "transform": "decimal"}],
            "net_amount":         [{"source": "total_amount",       "transform": "decimal"}],
            "budget_limit":       [{"source": "budget_limit",       "transform": "decimal"}],
            "approval_status":    [{"source": "approval_status",    "transform": "string"}],
        },
        "bank_statement": {
            "bank_name":          [{"source": "bank_name",               "transform": "string"}],
            "bank_account_number":[{"source": "account_number",          "transform": "string"}],
            "vendor_name":        [{"source": "account_name",            "transform": "string"}],
            "iban":               [{"source": "iban",                    "transform": "uppercase"}],
            "currency_code":      [{"source": "currency",                "transform": "uppercase"}],
            "period_from":        [{"source": "statement_period_from",   "transform": "date_parse"}],
            "period_to":          [{"source": "statement_period_to",     "transform": "date_parse"}],
            "balance_amount":     [{"source": "closing_balance",         "transform": "decimal"}],
            "credit_amount":      [{"source": "total_credits",           "transform": "decimal"}],
            "debit_amount":       [{"source": "total_debits",            "transform": "decimal"}],
        },
        "payroll": {
            "company_name":       [{"source": "company_name",            "transform": "string"}],
            "department":         [{"source": "department",              "transform": "string"}],
            "period_from":        [{"source": "payroll_period_from",     "transform": "date_parse"}],
            "period_to":          [{"source": "payroll_period_to",       "transform": "date_parse"}],
            "payment_date":       [{"source": "payment_date",            "transform": "date_parse"}],
            "currency_code":      [{"source": "currency",                "transform": "uppercase"}],
            "employee_count":     [{"source": "employee_count",          "transform": "integer"}],
            "gross_salary":       [{"source": "total_gross_salary",      "transform": "decimal"}],
            "net_salary":         [{"source": "total_net_salary",        "transform": "decimal"}],
            "total_allowances":   [{"source": "total_allowances",        "transform": "decimal"}],
            "total_deductions":   [{"source": "total_deductions",        "transform": "decimal"}],
            "gosi_amount":        [{"source": "total_gosi",              "transform": "decimal"}],
        },
        "expense_report": {
            "document_number":    [{"source": "report_number",           "transform": "string"}],
            "employee_name":      [{"source": "employee_name",           "transform": "string"}],
            "employee_id":        [{"source": "employee_id",             "transform": "string"}],
            "department":         [{"source": "department",              "transform": "string"}],
            "period_from":        [{"source": "report_period_from",      "transform": "date_parse"}],
            "period_to":          [{"source": "report_period_to",        "transform": "date_parse"}],
            "submission_date":    [{"source": "submitted_date",          "transform": "date_parse"}],
            "currency_code":      [{"source": "currency",                "transform": "uppercase"}],
            "net_amount":         [{"source": "total_claimed",           "transform": "decimal"}],
            "tax_amount":         [{"source": "vat_included",            "transform": "decimal"}],
        },
        "tax_declaration": {
            "company_name":            [{"source": "taxpayer_name",      "transform": "string"}],
            "vat_registration_number": [{"source": "vat_number",         "transform": "string"}],
            "vendor_cr_number":        [{"source": "cr_number",          "transform": "string"}],
            "period_from":             [{"source": "period_from",        "transform": "date_parse"}],
            "period_to":               [{"source": "period_to",          "transform": "date_parse"}],
            "submission_date":         [{"source": "filing_date",        "transform": "date_parse"}],
            "due_date":                [{"source": "due_date",           "transform": "date_parse"}],
            "zatca_reference":         [{"source": "zatca_reference",    "transform": "string"}],
            "payment_amount":          [{"source": "net_vat_payable",    "transform": "decimal"}],
            "filing_status":           [{"source": "filing_status",      "transform": "string"}],
        },
        "vat_return": {
            "company_name":            [{"source": "taxpayer_name",      "transform": "string"}],
            "vat_registration_number": [{"source": "vat_number",         "transform": "string"}],
            "vendor_cr_number":        [{"source": "cr_number",          "transform": "string"}],
            "period_from":             [{"source": "period_from",        "transform": "date_parse"}],
            "period_to":               [{"source": "period_to",          "transform": "date_parse"}],
            "submission_date":         [{"source": "filing_date",        "transform": "date_parse"}],
            "due_date":                [{"source": "due_date",           "transform": "date_parse"}],
            "zatca_reference":         [{"source": "zatca_reference",    "transform": "string"}],
            "payment_amount":          [{"source": "net_vat_payable",    "transform": "decimal"}],
            "filing_status":           [{"source": "filing_status",      "transform": "string"}],
        },
        "fixed_asset": {
            "company_name":   [{"source": "company_name",                "transform": "string"}],
            "department":     [{"source": "department",                  "transform": "string"}],
            "tax_period":     [{"source": "fiscal_year",                 "transform": "string"}],
            "document_date":  [{"source": "register_date",               "transform": "date_parse"}],
            "net_amount":     [{"source": "total_book_value",            "transform": "decimal"}],
            "balance_amount": [{"source": "total_accumulated_depreciation", "transform": "decimal"}],
        },
        "sales_receipt": {
            "document_number":     [{"source": "receipt_number",         "transform": "string"}],
            "document_date":       [{"source": "receipt_date",           "transform": "date_parse"}],
            "vendor_name":         [{"source": "seller_name",            "transform": "string"}],
            "vendor_tax_number":   [{"source": "seller_vat_number",      "transform": "string"}],
            "customer_name":       [{"source": "customer_name",          "transform": "string"}],
            "customer_tax_number": [{"source": "customer_vat_number",    "transform": "string"}],
            "currency_code":       [{"source": "currency",               "transform": "uppercase"}],
            "subtotal_amount":     [{"source": "subtotal",               "transform": "decimal"}],
            "tax_rate":            [{"source": "vat_rate",               "transform": "decimal"}],
            "tax_amount":          [{"source": "vat_amount",             "transform": "decimal"}],
            "net_amount":          [{"source": "total_amount",           "transform": "decimal"}],
            "zatca_invoice_number":[{"source": "zatca_uuid",             "transform": "string"}],
            "qr_code_valid":       [{"source": "qr_code_valid",          "transform": "bool"}],
        },
    }

    def map(self, raw_data: dict, document_type: str) -> dict:
        """
        Map raw AI/OCR extraction → canonical field dict.
        All defined canonical fields for this type are present; unmapped = None.
        """
        mapping = self._load_mapping(document_type)
        canonical: dict = {}

        for field_code, sources in mapping.items():
            value = None
            for source_def in sources:
                raw_value = raw_data.get(source_def["source"])
                value = Transform.apply(
                    source_def.get("transform", "direct"),
                    raw_value,
                    source_def.get("args", {}),
                    raw_data,
                )
                if value is not None:
                    break
            canonical[field_code] = value

        # Always ensure currency_code has a default
        if not canonical.get("currency_code"):
            canonical["currency_code"] = raw_data.get("currency") or "SAR"

        return canonical

    def _load_mapping(self, document_type: str) -> dict:
        """Load from DB if seeded, else fall back to FALLBACK_MAPPING."""
        try:
            from apps.documents.canonical_models import DocumentTypeFieldMapping
            qs = (
                DocumentTypeFieldMapping.objects
                .filter(document_type=document_type, is_active=True)
                .select_related("canonical_field")
                .order_by("-priority")
            )
            if qs.exists():
                result: dict = {}
                for m in qs:
                    code = m.canonical_field.field_code
                    result.setdefault(code, []).append({
                        "source":    m.source_column,
                        "transform": m.transform,
                        "args":      m.transform_args or {},
                    })
                return result
        except Exception:
            pass
        return self.FALLBACK_MAPPING.get(document_type, {})

    def save_canonical(
        self,
        raw_data: dict,
        document_type: str,
        typed_model_name: str,
        typed_object_id,
    ):
        """
        Run mapping and persist result as DocumentCanonicalData.
        Idempotent — updates existing record if one exists.
        """
        from apps.documents.canonical_models import DocumentCanonicalData
        canonical = self.map(raw_data, document_type)

        obj, created = DocumentCanonicalData.objects.get_or_create(
            typed_model_name=typed_model_name,
            typed_object_id=str(typed_object_id),
            defaults={
                "document_type": document_type,
                "canonical_data": canonical,
                "raw_ai_output":  raw_data,
            },
        )
        if not created:
            obj.canonical_data = canonical
            obj.raw_ai_output  = raw_data
            obj.version       += 1
            obj.save(update_fields=["canonical_data", "raw_ai_output", "version", "updated_at"])
        return obj
