"""
Phase-2 doc-type API endpoints — Contract / JournalEntry / SalesOrder.

Closes the "13 model-only types" gap for the three highest-value
phase-2 models. Follows the established pattern in `typed_views.py`:
  • _TypedListView   →  GET /<type>/      paginated, tenant-scoped
  • _TypedDetailView →  GET /<type>/<id>/ + PUT/PATCH/DELETE

Remaining 8 phase-2 types (Quotation, ProformaInvoice, ReceiptVoucher,
CashVoucher, GeneralLedger, Ledger, SupplierStatement, CustomerStatement)
can follow the same pattern when product priorities call for them.
The audit signals + normalizers already cover all 11 phase-2 types,
so adding their HTTP surfaces is repetitive work — not architectural.
"""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers

# Re-use the generic base classes from typed_views.
from apps.documents.typed_views import _TypedListView, _TypedDetailView
from apps.documents.typed_models_v2 import (
    Contract, JournalEntry, SalesOrder,
    Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
    GeneralLedger, Ledger, SupplierStatement, CustomerStatement,
)


# ── Serializers ───────────────────────────────────────────────────────────────

class ContractListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = [
            "id", "contract_number", "title", "party_a", "party_b",
            "party_b_type", "party_b_vat_number", "start_date", "end_date",
            "signing_date", "audit_status", "risk_level", "validation_score",
            "created_at",
        ]


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = "__all__"


class JournalEntryListSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntry
        fields = [
            "id", "entry_number", "entry_date", "description", "fiscal_period",
            "currency", "total_debit", "total_credit", "lines_count",
            "is_balanced", "audit_status", "risk_level", "validation_score",
            "created_at",
        ]


class JournalEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntry
        fields = "__all__"


class SalesOrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrder
        fields = [
            "id", "so_number", "so_date", "expected_delivery_date",
            "customer_name", "customer_vat_number", "department", "status",
            "currency", "subtotal", "vat_amount", "total_amount",
            "audit_status", "risk_level", "validation_score", "created_at",
        ]


class SalesOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrder
        fields = "__all__"


# ── Views ─────────────────────────────────────────────────────────────────────

class ContractListView(_TypedListView):
    model = Contract
    list_serializer_class = ContractListSerializer
    search_fields = ["contract_number", "title", "party_a", "party_b"]

    @extend_schema(tags=["Contracts"], summary="List contracts")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ContractDetailView(_TypedDetailView):
    model = Contract
    detail_serializer_class = ContractSerializer

    @extend_schema(tags=["Contracts"], summary="Get/update/delete a contract")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class JournalEntryListView(_TypedListView):
    model = JournalEntry
    list_serializer_class = JournalEntryListSerializer
    search_fields = ["entry_number", "description", "fiscal_period"]

    @extend_schema(tags=["Journal Entries"], summary="List journal entries")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class JournalEntryDetailView(_TypedDetailView):
    model = JournalEntry
    detail_serializer_class = JournalEntrySerializer

    @extend_schema(tags=["Journal Entries"], summary="Get/update/delete a journal entry")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SalesOrderListView(_TypedListView):
    model = SalesOrder
    list_serializer_class = SalesOrderListSerializer
    search_fields = ["so_number", "customer_name", "customer_vat_number"]

    @extend_schema(tags=["Sales Orders"], summary="List sales orders")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SalesOrderDetailView(_TypedDetailView):
    model = SalesOrder
    detail_serializer_class = SalesOrderSerializer

    @extend_schema(tags=["Sales Orders"], summary="Get/update/delete a sales order")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# ── Remaining 8 phase-2 types — same pattern as above ─────────────────────────

class QuotationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quotation
        fields = ["id", "quotation_number", "quotation_date", "expiry_date",
                  "party_type", "party_name", "party_vat_number", "status",
                  "currency", "subtotal", "vat_amount", "total_amount",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class QuotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quotation
        fields = "__all__"


class QuotationListView(_TypedListView):
    model = Quotation
    list_serializer_class = QuotationListSerializer
    search_fields = ["quotation_number", "party_name", "party_vat_number"]

    @extend_schema(tags=["Quotations"], summary="List quotations")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class QuotationDetailView(_TypedDetailView):
    model = Quotation
    detail_serializer_class = QuotationSerializer

    @extend_schema(tags=["Quotations"], summary="Get/update/delete a quotation")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ProformaInvoiceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProformaInvoice
        fields = ["id", "proforma_number", "proforma_date", "validity_date",
                  "customer_name", "customer_vat_number", "status",
                  "currency", "subtotal", "vat_amount", "total_amount",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class ProformaInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProformaInvoice
        fields = "__all__"


class ProformaInvoiceListView(_TypedListView):
    model = ProformaInvoice
    list_serializer_class = ProformaInvoiceListSerializer
    search_fields = ["proforma_number", "customer_name", "customer_vat_number"]

    @extend_schema(tags=["Proforma Invoices"], summary="List proforma invoices")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ProformaInvoiceDetailView(_TypedDetailView):
    model = ProformaInvoice
    detail_serializer_class = ProformaInvoiceSerializer

    @extend_schema(tags=["Proforma Invoices"], summary="Get/update/delete a proforma invoice")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ReceiptVoucherListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptVoucher
        fields = ["id", "receipt_number", "receipt_date", "payer_name",
                  "payer_vat_number", "receipt_method", "currency", "amount",
                  "linked_invoice_number", "audit_status", "risk_level",
                  "validation_score", "created_at"]


class ReceiptVoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptVoucher
        fields = "__all__"


class ReceiptVoucherListView(_TypedListView):
    model = ReceiptVoucher
    list_serializer_class = ReceiptVoucherListSerializer
    search_fields = ["receipt_number", "payer_name", "linked_invoice_number"]

    @extend_schema(tags=["Receipt Vouchers"], summary="List receipt vouchers")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ReceiptVoucherDetailView(_TypedDetailView):
    model = ReceiptVoucher
    detail_serializer_class = ReceiptVoucherSerializer

    @extend_schema(tags=["Receipt Vouchers"], summary="Get/update/delete a receipt voucher")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CashVoucherListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashVoucher
        fields = ["id", "voucher_number", "voucher_date", "movement_type",
                  "counterparty_name", "reason", "currency", "amount",
                  "has_attachment", "requires_approval", "audit_status",
                  "risk_level", "validation_score", "created_at"]


class CashVoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashVoucher
        fields = "__all__"


class CashVoucherListView(_TypedListView):
    model = CashVoucher
    list_serializer_class = CashVoucherListSerializer
    search_fields = ["voucher_number", "counterparty_name", "reason"]

    @extend_schema(tags=["Cash Vouchers"], summary="List cash vouchers")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CashVoucherDetailView(_TypedDetailView):
    model = CashVoucher
    detail_serializer_class = CashVoucherSerializer

    @extend_schema(tags=["Cash Vouchers"], summary="Get/update/delete a cash voucher")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class GeneralLedgerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralLedger
        fields = ["id", "period_from", "period_to", "fiscal_year",
                  "total_debit", "total_credit", "accounts_count",
                  "movements_count", "audit_status", "risk_level",
                  "validation_score", "created_at"]


class GeneralLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralLedger
        fields = "__all__"


class GeneralLedgerListView(_TypedListView):
    model = GeneralLedger
    list_serializer_class = GeneralLedgerListSerializer
    search_fields = ["fiscal_year"]

    @extend_schema(tags=["General Ledger"], summary="List general-ledger snapshots")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class GeneralLedgerDetailView(_TypedDetailView):
    model = GeneralLedger
    detail_serializer_class = GeneralLedgerSerializer

    @extend_schema(tags=["General Ledger"], summary="Get/update/delete a general-ledger snapshot")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class LedgerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ledger
        fields = ["id", "account_number", "account_name", "account_type",
                  "period_from", "period_to", "currency",
                  "opening_balance", "closing_balance", "total_debit",
                  "audit_status", "risk_level", "validation_score",
                  "created_at"]


class LedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ledger
        fields = "__all__"


class LedgerListView(_TypedListView):
    model = Ledger
    list_serializer_class = LedgerListSerializer
    search_fields = ["account_number", "account_name", "account_type"]

    @extend_schema(tags=["Ledger"], summary="List per-account ledgers")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class LedgerDetailView(_TypedDetailView):
    model = Ledger
    detail_serializer_class = LedgerSerializer

    @extend_schema(tags=["Ledger"], summary="Get/update/delete a per-account ledger")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SupplierStatementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierStatement
        fields = ["id", "supplier_name", "supplier_id", "supplier_vat_number",
                  "period_from", "period_to", "currency",
                  "opening_balance", "closing_balance", "total_invoiced",
                  "audit_status", "risk_level", "validation_score",
                  "created_at"]


class SupplierStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierStatement
        fields = "__all__"


class SupplierStatementListView(_TypedListView):
    model = SupplierStatement
    list_serializer_class = SupplierStatementListSerializer
    search_fields = ["supplier_name", "supplier_id", "supplier_vat_number"]

    @extend_schema(tags=["Supplier Statements"], summary="List supplier statements")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SupplierStatementDetailView(_TypedDetailView):
    model = SupplierStatement
    detail_serializer_class = SupplierStatementSerializer

    @extend_schema(tags=["Supplier Statements"], summary="Get/update/delete a supplier statement")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CustomerStatementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerStatement
        fields = ["id", "customer_name", "customer_id", "customer_vat_number",
                  "period_from", "period_to", "currency",
                  "opening_balance", "closing_balance", "total_invoiced",
                  "audit_status", "risk_level", "validation_score",
                  "created_at"]


class CustomerStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerStatement
        fields = "__all__"


class CustomerStatementListView(_TypedListView):
    model = CustomerStatement
    list_serializer_class = CustomerStatementListSerializer
    search_fields = ["customer_name", "customer_id", "customer_vat_number"]

    @extend_schema(tags=["Customer Statements"], summary="List customer statements")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CustomerStatementDetailView(_TypedDetailView):
    model = CustomerStatement
    detail_serializer_class = CustomerStatementSerializer

    @extend_schema(tags=["Customer Statements"], summary="Get/update/delete a customer statement")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
