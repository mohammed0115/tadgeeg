from __future__ import annotations

from typing import Optional

from apps.documents.profiles.base import DocumentTypeProfile
from apps.documents.profiles.bank_statement import BankStatementProfile
from apps.documents.profiles.contract import ContractProfile
from apps.documents.profiles.journal_entry import JournalEntryProfile
from apps.documents.profiles.payroll import PayrollProfile
from apps.documents.profiles.purchase_invoice import PurchaseInvoiceProfile
from apps.documents.profiles.purchase_order import PurchaseOrderProfile
from apps.documents.profiles.sales_invoice import SalesInvoiceProfile


PROFILE_REGISTRY: dict[str, DocumentTypeProfile] = {
    "purchase_order": PurchaseOrderProfile(),
    "purchase_invoice": PurchaseInvoiceProfile(),
    "sales_invoice": SalesInvoiceProfile(),
    "bank_statement": BankStatementProfile(),
    "journal_entry": JournalEntryProfile(),
    "payroll": PayrollProfile(),
    "contract": ContractProfile(),
}


def get_profile(doc_type: str) -> Optional[DocumentTypeProfile]:
    return PROFILE_REGISTRY.get(doc_type)


def get_required_fields(doc_type: str) -> list[str]:
    profile = get_profile(doc_type)
    return profile.get_required_fields() if profile else []


def get_blocking_rules(doc_type: str) -> list[str]:
    profile = get_profile(doc_type)
    return profile.blocking_rule_codes if profile else []