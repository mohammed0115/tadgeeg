"""Typed Document Serializers — list + detail for all 7 document types."""
from rest_framework import serializers
from .typed_models import (
    PurchaseOrder, BankStatement, PayrollSheet,
    ExpenseReport, VATReturn, FixedAsset, SalesReceipt,
)

# ── Shared fields ─────────────────────────────────────────────────────────────
AUDIT_FIELDS = ["id", "audit_status", "risk_level", "validation_score",
                "rules_passed", "rules_failed", "failed_rule_codes",
                "ai_summary", "created_at", "updated_at"]


# ══ Purchase Order ════════════════════════════════════════════════════════════
class PurchaseOrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = ["id", "po_number", "po_date", "vendor_name", "total_amount",
                  "currency", "approval_status", "audit_status", "risk_level",
                  "validation_score", "created_at"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = "__all__"


# ══ Bank Statement ════════════════════════════════════════════════════════════
class BankStatementListSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankStatement
        fields = ["id", "bank_name", "account_number", "iban",
                  "statement_period_from", "statement_period_to",
                  "closing_balance", "currency", "balance_matches",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class BankStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankStatement
        fields = "__all__"


# ══ Payroll Sheet ═════════════════════════════════════════════════════════════
class PayrollSheetListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollSheet
        fields = ["id", "payroll_period_from", "payroll_period_to",
                  "department", "company_name", "employee_count",
                  "total_gross_salary", "total_net_salary", "currency",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class PayrollSheetSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollSheet
        fields = "__all__"


# ══ Expense Report ════════════════════════════════════════════════════════════
class ExpenseReportListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseReport
        fields = ["id", "report_number", "employee_name", "department",
                  "report_period_from", "report_period_to", "total_claimed",
                  "currency", "audit_status", "risk_level", "validation_score", "created_at"]


class ExpenseReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseReport
        fields = "__all__"


# ══ VAT Return ════════════════════════════════════════════════════════════════
class VATReturnListSerializer(serializers.ModelSerializer):
    class Meta:
        model = VATReturn
        fields = ["id", "taxpayer_name", "vat_number", "period_from", "period_to",
                  "filing_status", "net_vat_payable", "is_late_filing",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class VATReturnSerializer(serializers.ModelSerializer):
    class Meta:
        model = VATReturn
        fields = "__all__"


# ══ Fixed Asset ═══════════════════════════════════════════════════════════════
class FixedAssetListSerializer(serializers.ModelSerializer):
    class Meta:
        model = FixedAsset
        fields = ["id", "fiscal_year", "department", "company_name",
                  "asset_count", "total_cost", "total_book_value",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class FixedAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = FixedAsset
        fields = "__all__"


# ══ Sales Receipt ═════════════════════════════════════════════════════════════
class SalesReceiptListSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesReceipt
        fields = ["id", "receipt_number", "receipt_date", "receipt_type",
                  "seller_name", "total_amount", "currency",
                  "has_qr_code", "qr_code_valid", "is_duplicate",
                  "audit_status", "risk_level", "validation_score", "created_at"]


class SalesReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesReceipt
        fields = "__all__"
