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
from apps.documents.typed_models_v2 import Contract, JournalEntry, SalesOrder


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
