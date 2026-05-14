"""``FinancialDocument`` bridge — single contract over Invoice + Transaction.

The BIG4 audit flagged finding A-4: ``apps/transactions/models.Transaction``
and ``apps/invoices/models.Invoice`` are parallel schemas with no
explicit bridge, allowing double-counting and missing-from-one-side bugs.

This module is the contract that lets code (analytics, rule engine,
exports, reconciliation) consume both via a single abstraction. It is
duck-typed — there is no inheritance requirement — so existing models
satisfy it without migration.

Usage::

    from core.audit.financial_document import as_financial_document

    fd = as_financial_document(invoice_or_transaction)
    print(fd.amount, fd.vendor_name, fd.kind)

A real "merge into one table" is a multi-quarter project. The bridge is
the safe intermediate step that unblocks cross-cutting features (export,
risk scoring, ERP reconciliation) without forcing a schema rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional


@dataclass(slots=True, frozen=True)
class FinancialDocument:
    """Vendor-agnostic snapshot of an Invoice or Transaction row."""
    kind:            str              # "invoice" | "transaction" | "journal_entry"
    source_pk:       str
    organization_id: str
    reference:       str              # invoice_number or transaction.reference_number
    vendor_name:     str
    vendor_vat:      str
    currency:        str
    amount:          Decimal
    vat_amount:      Decimal
    document_date:   Optional[date]
    risk_score:      float
    risk_level:      str
    external_source: str = ""         # ERP provider when from sync
    external_id:     str = ""
    raw:             Any = None       # original row, for callers that need full fidelity

    def to_dict(self) -> dict:
        return {
            "kind":             self.kind,
            "source_pk":        self.source_pk,
            "organization_id":  self.organization_id,
            "reference":        self.reference,
            "vendor_name":      self.vendor_name,
            "vendor_vat":       self.vendor_vat,
            "currency":         self.currency,
            "amount":           str(self.amount),
            "vat_amount":       str(self.vat_amount),
            "document_date":    self.document_date.isoformat() if self.document_date else "",
            "risk_score":       self.risk_score,
            "risk_level":       self.risk_level,
            "external_source":  self.external_source,
            "external_id":      self.external_id,
        }


def as_financial_document(obj) -> FinancialDocument:
    """Adapt an Invoice or Transaction to a FinancialDocument."""
    model_name = obj.__class__.__name__

    if model_name == "Invoice":
        return FinancialDocument(
            kind="invoice",
            source_pk=str(obj.pk),
            organization_id=str(getattr(obj, "organization_id", "") or ""),
            reference=getattr(obj, "invoice_number", "") or "",
            vendor_name=getattr(obj, "vendor_name", "") or "",
            vendor_vat=getattr(obj, "vendor_vat_number", "") or "",
            currency=getattr(obj, "currency", "SAR") or "SAR",
            amount=Decimal(str(getattr(obj, "total_amount", 0) or 0)),
            vat_amount=Decimal(str(getattr(obj, "vat_amount", 0) or 0)),
            document_date=getattr(obj, "invoice_date", None),
            risk_score=float(getattr(obj, "risk_score", 0) or 0),
            risk_level=str(getattr(obj, "risk_level", "low") or "low"),
            external_source=getattr(obj, "external_source", "") or "",
            external_id=getattr(obj, "external_id", "") or "",
            raw=obj,
        )

    if model_name == "Transaction":
        return FinancialDocument(
            kind="transaction",
            source_pk=str(obj.pk),
            organization_id=str(getattr(obj, "organization_id", "") or ""),
            reference=(
                getattr(obj, "reference_number", "")
                or getattr(obj, "invoice_number", "")
                or ""
            ),
            vendor_name=getattr(obj, "vendor_name", "") or "",
            vendor_vat=getattr(obj, "vendor_vat_number", "") or "",
            currency=getattr(obj, "currency", "SAR") or "SAR",
            amount=Decimal(str(getattr(obj, "amount", 0) or 0)),
            vat_amount=Decimal(str(getattr(obj, "vat_amount", 0) or 0)),
            document_date=getattr(obj, "transaction_date", None),
            risk_score=float(getattr(obj, "risk_score", 0) or 0),
            risk_level=str(getattr(obj, "risk_level", "low") or "low"),
            raw=obj,
        )

    if model_name == "JournalEntry":
        return FinancialDocument(
            kind="journal_entry",
            source_pk=str(obj.pk),
            organization_id=str(getattr(obj, "organization_id", "") or ""),
            reference=getattr(obj, "entry_number", "") or getattr(obj, "reference", "") or "",
            vendor_name="",
            vendor_vat="",
            currency=getattr(obj, "currency", "SAR") or "SAR",
            amount=obj.total_debits() if hasattr(obj, "total_debits") else Decimal("0"),
            vat_amount=Decimal("0"),
            document_date=getattr(obj, "entry_date", None),
            risk_score=0.0,
            risk_level="low",
            raw=obj,
        )

    raise TypeError(
        f"{model_name} cannot be adapted to FinancialDocument — "
        f"add a branch in core.audit.financial_document.as_financial_document"
    )
