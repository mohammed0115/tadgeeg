"""
Phase-2 doc-type normalizers — 11 typed models from typed_models_v2.

Each normalizer reads its Django row and returns a NormalizedDocument that
the rule engine can run rules against without caring about per-type schema.

Models covered:
  • SalesOrder           • Quotation            • ProformaInvoice
  • ReceiptVoucher       • CashVoucher          • GeneralLedger
  • Ledger               • Contract             • SupplierStatement
  • CustomerStatement    • JournalEntry

Convention follows the existing `purchase_order_normalizer.py`:
  - Subclass `BaseNormalizer`.
  - Set `document_type` class attr matching the rule-engine catalog code.
  - `normalize(document_id, organization_id) -> NormalizedDocument`.
  - Register via `DocumentNormalizerFactory.register(...)` at module import.

The normalizer is intentionally tolerant: a missing row returns an empty
NormalizedDocument with just the IDs, so the pipeline can still emit a
"not found" finding without raising.
"""

from __future__ import annotations

import logging

from apps.rule_engine.rules.base import NormalizedDocument
from apps.rule_engine.normalizers import BaseNormalizer, DocumentNormalizerFactory

logger = logging.getLogger("rule_engine")


def _empty(document_id, document_type, organization_id) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=str(document_id),
        document_type=document_type,
        organization_id=str(organization_id),
    )


def _f(value):
    """Decimal/None -> float helper."""
    return float(value) if value is not None else None


def _s(value):
    """date/None -> str helper."""
    return str(value) if value is not None else None


# ── 1. Sales Order ────────────────────────────────────────────────────────────
class SalesOrderNormalizer(BaseNormalizer):
    document_type = "sales_order"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import SalesOrder
        try:
            so = SalesOrder.objects.get(id=document_id)
        except SalesOrder.DoesNotExist:
            logger.warning("SalesOrder %s not found", document_id)
            return _empty(document_id, "sales_order", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="sales_order",
            organization_id=str(organization_id),
            document_number=so.so_number,
            document_date=so.so_date,
            total_amount=_f(so.total_amount),
            currency=so.currency,
            counterparty_name=so.customer_name,
            tax_id=so.customer_vat_number,
            typed_data={
                "so_number":             so.so_number,
                "expected_delivery_date": _s(so.expected_delivery_date),
                "customer_id_number":    so.customer_id_number,
                "department":            so.department,
                "status":                so.status,
                "subtotal":              _f(so.subtotal),
                "vat_amount":            _f(so.vat_amount),
                "line_items":            so.line_items or [],
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 2. Quotation ──────────────────────────────────────────────────────────────
class QuotationNormalizer(BaseNormalizer):
    document_type = "quotation"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import Quotation
        try:
            q = Quotation.objects.get(id=document_id)
        except Quotation.DoesNotExist:
            return _empty(document_id, "quotation", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="quotation",
            organization_id=str(organization_id),
            document_number=q.quotation_number,
            document_date=q.quotation_date,
            total_amount=_f(q.total_amount),
            currency=q.currency,
            counterparty_name=q.party_name,
            tax_id=q.party_vat_number,
            typed_data={
                "quotation_number": q.quotation_number,
                "expiry_date":     _s(q.expiry_date),
                "party_type":      q.party_type,
                "status":          q.status,
                "subtotal":        _f(q.subtotal),
                "vat_amount":      _f(q.vat_amount),
                "line_items":      q.line_items or [],
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 3. Proforma Invoice ───────────────────────────────────────────────────────
class ProformaInvoiceNormalizer(BaseNormalizer):
    document_type = "proforma_invoice"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import ProformaInvoice
        try:
            pi = ProformaInvoice.objects.get(id=document_id)
        except ProformaInvoice.DoesNotExist:
            return _empty(document_id, "proforma_invoice", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="proforma_invoice",
            organization_id=str(organization_id),
            document_number=pi.proforma_number,
            document_date=pi.proforma_date,
            total_amount=_f(pi.total_amount),
            currency=pi.currency,
            counterparty_name=pi.customer_name,
            tax_id=pi.customer_vat_number,
            typed_data={
                "proforma_number": pi.proforma_number,
                "validity_date":   _s(pi.validity_date),
                "status":          pi.status,
                "subtotal":        _f(pi.subtotal),
                "vat_amount":      _f(pi.vat_amount),
                "line_items":      pi.line_items or [],
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 4. Receipt Voucher ────────────────────────────────────────────────────────
class ReceiptVoucherNormalizer(BaseNormalizer):
    document_type = "receipt_voucher"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import ReceiptVoucher
        try:
            rv = ReceiptVoucher.objects.get(id=document_id)
        except ReceiptVoucher.DoesNotExist:
            return _empty(document_id, "receipt_voucher", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="receipt_voucher",
            organization_id=str(organization_id),
            document_number=rv.receipt_number,
            document_date=rv.receipt_date,
            total_amount=_f(rv.amount),
            currency=rv.currency,
            counterparty_name=rv.payer_name,
            tax_id=rv.payer_vat_number,
            typed_data={
                "receipt_number":        rv.receipt_number,
                "receipt_method":        rv.receipt_method,
                "amount":                _f(rv.amount),
                "linked_invoice_number": rv.linked_invoice_number,
                "linked_invoice_id":     str(rv.linked_invoice_id) if rv.linked_invoice_id else None,
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 5. Cash Voucher ───────────────────────────────────────────────────────────
class CashVoucherNormalizer(BaseNormalizer):
    document_type = "cash_voucher"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import CashVoucher
        try:
            cv = CashVoucher.objects.get(id=document_id)
        except CashVoucher.DoesNotExist:
            return _empty(document_id, "cash_voucher", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="cash_voucher",
            organization_id=str(organization_id),
            document_number=cv.voucher_number,
            document_date=cv.voucher_date,
            total_amount=_f(cv.amount),
            currency=cv.currency,
            counterparty_name=cv.counterparty_name,
            typed_data={
                "voucher_number":     cv.voucher_number,
                "movement_type":      cv.movement_type,
                "reason":             cv.reason,
                "amount":             _f(cv.amount),
                "has_attachment":     bool(cv.has_attachment),
                "requires_approval":  bool(cv.requires_approval),
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 6. General Ledger ─────────────────────────────────────────────────────────
class GeneralLedgerNormalizer(BaseNormalizer):
    document_type = "general_ledger"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import GeneralLedger
        try:
            gl = GeneralLedger.objects.get(id=document_id)
        except GeneralLedger.DoesNotExist:
            return _empty(document_id, "general_ledger", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="general_ledger",
            organization_id=str(organization_id),
            document_number=gl.fiscal_year,
            document_date=gl.period_to,
            total_amount=_f(gl.total_debit),
            typed_data={
                "period_from":       _s(gl.period_from),
                "period_to":         _s(gl.period_to),
                "fiscal_year":       gl.fiscal_year,
                "total_debit":       _f(gl.total_debit),
                "total_credit":      _f(gl.total_credit),
                "accounts_count":    gl.accounts_count,
                "movements_count":   gl.movements_count,
                "accounts":          gl.accounts or [],
                "abnormal_balances": gl.abnormal_balances or [],
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 7. Ledger (single-account) ────────────────────────────────────────────────
class LedgerNormalizer(BaseNormalizer):
    document_type = "ledger"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import Ledger
        try:
            ld = Ledger.objects.get(id=document_id)
        except Ledger.DoesNotExist:
            return _empty(document_id, "ledger", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="ledger",
            organization_id=str(organization_id),
            document_number=ld.account_number,
            document_date=ld.period_to,
            total_amount=_f(ld.closing_balance),
            currency=ld.currency,
            typed_data={
                "account_number":  ld.account_number,
                "account_name":    ld.account_name,
                "account_type":    ld.account_type,
                "period_from":     _s(ld.period_from),
                "period_to":       _s(ld.period_to),
                "opening_balance": _f(ld.opening_balance),
                "closing_balance": _f(ld.closing_balance),
                "total_debit":     _f(ld.total_debit),
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 8. Contract ───────────────────────────────────────────────────────────────
class ContractNormalizer(BaseNormalizer):
    document_type = "contract"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import Contract
        try:
            ct = Contract.objects.get(id=document_id)
        except Contract.DoesNotExist:
            return _empty(document_id, "contract", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="contract",
            organization_id=str(organization_id),
            document_number=ct.contract_number,
            document_date=ct.signing_date or ct.start_date,
            total_amount=_f(getattr(ct, "contract_value", None)),
            counterparty_name=ct.party_b,
            tax_id=ct.party_b_vat_number,
            typed_data={
                "title":            ct.title,
                "party_a":          ct.party_a,
                "party_b":          ct.party_b,
                "party_b_type":     ct.party_b_type,
                "start_date":       _s(ct.start_date),
                "end_date":         _s(ct.end_date),
                "signing_date":     _s(ct.signing_date),
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 9. Supplier Statement ─────────────────────────────────────────────────────
class SupplierStatementNormalizer(BaseNormalizer):
    document_type = "supplier_statement"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import SupplierStatement
        try:
            ss = SupplierStatement.objects.get(id=document_id)
        except SupplierStatement.DoesNotExist:
            return _empty(document_id, "supplier_statement", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="supplier_statement",
            organization_id=str(organization_id),
            document_number=ss.supplier_id,
            document_date=ss.period_to,
            total_amount=_f(ss.closing_balance),
            currency=ss.currency,
            counterparty_name=ss.supplier_name,
            tax_id=ss.supplier_vat_number,
            typed_data={
                "supplier_id":      ss.supplier_id,
                "period_from":      _s(ss.period_from),
                "period_to":        _s(ss.period_to),
                "opening_balance":  _f(ss.opening_balance),
                "closing_balance":  _f(ss.closing_balance),
                "total_invoiced":   _f(ss.total_invoiced),
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 10. Customer Statement ────────────────────────────────────────────────────
class CustomerStatementNormalizer(BaseNormalizer):
    document_type = "customer_statement"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import CustomerStatement
        try:
            cs = CustomerStatement.objects.get(id=document_id)
        except CustomerStatement.DoesNotExist:
            return _empty(document_id, "customer_statement", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="customer_statement",
            organization_id=str(organization_id),
            document_number=cs.customer_id,
            document_date=cs.period_to,
            total_amount=_f(cs.closing_balance),
            currency=cs.currency,
            counterparty_name=cs.customer_name,
            tax_id=cs.customer_vat_number,
            typed_data={
                "customer_id":      cs.customer_id,
                "period_from":      _s(cs.period_from),
                "period_to":        _s(cs.period_to),
                "opening_balance":  _f(cs.opening_balance),
                "closing_balance":  _f(cs.closing_balance),
                "total_invoiced":   _f(cs.total_invoiced),
            },
            org_context=self._get_org_context(organization_id),
        )


# ── 11. Journal Entry ─────────────────────────────────────────────────────────
class JournalEntryNormalizer(BaseNormalizer):
    document_type = "journal_entry"

    def normalize(self, document_id, organization_id):
        from apps.documents.typed_models_v2 import JournalEntry
        try:
            je = JournalEntry.objects.get(id=document_id)
        except JournalEntry.DoesNotExist:
            return _empty(document_id, "journal_entry", organization_id)
        return NormalizedDocument(
            document_id=str(document_id),
            document_type="journal_entry",
            organization_id=str(organization_id),
            document_number=je.entry_number,
            document_date=je.entry_date,
            total_amount=_f(je.total_debit),
            currency=je.currency,
            typed_data={
                "entry_number":  je.entry_number,
                "description":   je.description,
                "fiscal_period": je.fiscal_period,
                "total_debit":   _f(je.total_debit),
                "total_credit":  _f(je.total_credit),
                "lines_count":   je.lines_count,
                "is_balanced":   bool(je.is_balanced),
                "lines":         getattr(je, "lines", []) or [],
            },
            org_context=self._get_org_context(organization_id),
        )


# ── Registration ──────────────────────────────────────────────────────────────
DocumentNormalizerFactory.register("sales_order",          SalesOrderNormalizer)
DocumentNormalizerFactory.register("quotation",            QuotationNormalizer)
DocumentNormalizerFactory.register("proforma_invoice",     ProformaInvoiceNormalizer)
DocumentNormalizerFactory.register("receipt_voucher",      ReceiptVoucherNormalizer)
DocumentNormalizerFactory.register("cash_voucher",         CashVoucherNormalizer)
DocumentNormalizerFactory.register("general_ledger",       GeneralLedgerNormalizer)
DocumentNormalizerFactory.register("ledger",               LedgerNormalizer)
DocumentNormalizerFactory.register("contract",             ContractNormalizer)
DocumentNormalizerFactory.register("supplier_statement",   SupplierStatementNormalizer)
DocumentNormalizerFactory.register("customer_statement",   CustomerStatementNormalizer)
DocumentNormalizerFactory.register("journal_entry",        JournalEntryNormalizer)
