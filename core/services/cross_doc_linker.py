"""
Cross-document linker: resolve relationships between financial documents.

Builds the bridges of the audit trail: PO → GRN → Invoice → Payment.
Used by:
  - Detail pages — to show "linked documents" panel
  - AI Assistant — to ground answers like "did this invoice get a PO?"
  - 3-way match validator — to detect mismatches across the chain

Design
------
Each document type has a `find_links(doc, org)` strategy that returns the
related documents using:
  1. Explicit FK / UUID linkage fields (`linked_invoice_id`, `po_id`, ...)
  2. Identifier match (`po_number == po.po_number`, …)
  3. Vendor + nearest date fallback (when neither side has a stored link)

Output is the same shape for every doc type so callers can be generic:
    {
        "purchase_order":     {... or None},
        "goods_receipt_note": {...},
        "payment_voucher":    {...},
        "sales_order":        {...},
        ...
        "three_way_match": {
            "applicable": True,
            "is_clean": False,
            "issues": ["amount_mismatch_invoice_vs_po", ...],
            "vendor_match": True,
            "amount_diff": -25.00,
        },
    }

Match tolerances
----------------
* Amount: configurable absolute tolerance (default 1.00) — small rounding ok.
* Date proximity: 30 days for vendor+date fallback search.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Tolerances + URL helpers
# ──────────────────────────────────────────────────────────────────────────────
AMOUNT_TOLERANCE = Decimal("1.00")
DATE_PROXIMITY_DAYS = 30


_DETAIL_URLS = {
    "invoice":              "/invoices/{id}/",
    "purchase_order":       "/documents/purchase-orders/{id}/",
    "goods_receipt_note":   "/documents/grns/{id}/",
    "payment_voucher":      "/documents/payment-vouchers/{id}/",
    "journal_entry":        "/documents/journal-entries/{id}/",
    "sales_order":          "/documents/sales-orders/{id}/",
    "quotation":            "/documents/quotations/{id}/",
    "proforma_invoice":     "/documents/proforma-invoices/{id}/",
    "receipt_voucher":      "/documents/receipt-vouchers/{id}/",
    "cash_voucher":         "/documents/cash-vouchers/{id}/",
    "general_ledger":       "/documents/general-ledgers/{id}/",
    "ledger":               "/documents/ledgers/{id}/",
    "contract":             "/documents/contracts/{id}/",
    "supplier_statement":   "/documents/supplier-statements/{id}/",
    "customer_statement":   "/documents/customer-statements/{id}/",
    "bank_statement":       "/documents/bank-statements/{id}/",
    "vat_return":           "/documents/vat-returns/{id}/",
}


def _detail_url(doc_type: str, doc_id) -> str:
    pattern = _DETAIL_URLS.get(doc_type)
    return pattern.format(id=doc_id) if pattern else ""


def _amount_diff(a, b) -> Decimal:
    """Return Decimal(a) - Decimal(b), tolerating None / strings."""
    try:
        return Decimal(str(a or 0)) - Decimal(str(b or 0))
    except Exception:
        return Decimal("0")


def _amount_matches(a, b) -> bool:
    return abs(_amount_diff(a, b)) <= AMOUNT_TOLERANCE


def _within_days(d1, d2, days: int) -> bool:
    if not d1 or not d2:
        return False
    try:
        return abs((d1 - d2).days) <= days
    except Exception:
        return False


def _link(doc_type: str, doc, *, match_type: str, score: float = 1.0,
          issues: Optional[list] = None, ref_amount=None) -> dict:
    """Standardised link record. `ref_amount` is the amount we're comparing against."""
    primary_field, primary_value = _identifier_for(doc_type, doc)
    amount = getattr(doc, "total_amount", None) or getattr(doc, "amount", None) or 0
    date = (
        getattr(doc, "invoice_date", None)
        or getattr(doc, "po_date", None)
        or getattr(doc, "grn_date", None)
        or getattr(doc, "payment_date", None)
        or getattr(doc, "receipt_date", None)
        or getattr(doc, "voucher_date", None)
        or getattr(doc, "so_date", None)
        or getattr(doc, "quotation_date", None)
        or getattr(doc, "proforma_date", None)
    )
    return {
        "doc_type": doc_type,
        "id": str(doc.id),
        primary_field: primary_value,
        # `display_id` is the always-present human-friendly handle templates render.
        "display_id": primary_value or str(doc.id)[:8],
        "date": date.isoformat() if date else None,
        "amount": float(amount or 0),
        "currency": getattr(doc, "currency", "SAR"),
        "vendor": getattr(doc, "vendor_name", "") or getattr(doc, "payee_name", ""),
        "match_type": match_type,
        "match_score": score,
        "amount_diff": float(_amount_diff(amount, ref_amount)) if ref_amount is not None else None,
        "issues": issues or [],
        "url": _detail_url(doc_type, doc.id),
    }


def _identifier_for(doc_type: str, doc) -> tuple[str, str]:
    """Return (primary-id-field-name, value) used in the link record."""
    if doc_type == "invoice":
        return "number", getattr(doc, "invoice_number", "") or ""
    if doc_type == "purchase_order":
        return "number", getattr(doc, "po_number", "") or ""
    if doc_type == "goods_receipt_note":
        return "number", getattr(doc, "grn_number", "") or ""
    if doc_type == "payment_voucher":
        return "number", getattr(doc, "payment_number", "") or ""
    if doc_type == "sales_order":
        return "number", getattr(doc, "so_number", "") or ""
    if doc_type == "quotation":
        return "number", getattr(doc, "quotation_number", "") or ""
    if doc_type == "proforma_invoice":
        return "number", getattr(doc, "proforma_number", "") or ""
    if doc_type == "receipt_voucher":
        return "number", getattr(doc, "receipt_number", "") or ""
    if doc_type == "cash_voucher":
        return "number", getattr(doc, "voucher_number", "") or ""
    if doc_type == "contract":
        return "number", getattr(doc, "contract_number", "") or ""
    return "name", str(doc)


# ──────────────────────────────────────────────────────────────────────────────
# Resolver helpers — these load Phase-1 / Phase-2 models lazily so the linker
# stays import-safe even before all migrations are applied.
# ──────────────────────────────────────────────────────────────────────────────
def _models():
    from apps.invoices.models import Invoice
    from apps.documents.typed_models import (
        PurchaseOrder, GoodsReceiptNote, PaymentVoucher,
    )
    from apps.documents.typed_models_v2 import (
        SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
        Contract, SupplierStatement, CustomerStatement,
    )
    return {
        "invoice":            Invoice,
        "purchase_order":     PurchaseOrder,
        "goods_receipt_note": GoodsReceiptNote,
        "payment_voucher":    PaymentVoucher,
        "sales_order":        SalesOrder,
        "quotation":          Quotation,
        "proforma_invoice":   ProformaInvoice,
        "receipt_voucher":    ReceiptVoucher,
        "cash_voucher":       CashVoucher,
        "contract":           Contract,
        "supplier_statement": SupplierStatement,
        "customer_statement": CustomerStatement,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Per-doc-type strategies
# ──────────────────────────────────────────────────────────────────────────────
def _find_po_for_invoice(invoice, org) -> Optional[dict]:
    """PO matched by GRN.po_number → vendor+amount → vendor+date."""
    M = _models()
    PurchaseOrder = M["purchase_order"]
    GRN           = M["goods_receipt_note"]

    # 1. via GRN: GRN.invoice_number → GRN.po_number → PO
    if invoice.invoice_number:
        grn = GRN.objects.filter(
            organization=org, invoice_number=invoice.invoice_number,
        ).first()
        if grn and grn.po_id:
            po = PurchaseOrder.objects.filter(organization=org, id=grn.po_id).first()
            if po:
                return _link("purchase_order", po, match_type="via_grn",
                             ref_amount=invoice.total_amount)
        if grn and grn.po_number:
            po = PurchaseOrder.objects.filter(
                organization=org, po_number=grn.po_number,
            ).first()
            if po:
                return _link("purchase_order", po, match_type="via_grn",
                             ref_amount=invoice.total_amount)

    if not invoice.vendor_name:
        return None

    # 2. vendor + amount within tolerance
    for po in PurchaseOrder.objects.filter(
        organization=org, vendor_name=invoice.vendor_name,
    ).order_by("-po_date")[:20]:
        if _amount_matches(po.total_amount, invoice.total_amount):
            return _link("purchase_order", po, match_type="vendor_amount", score=0.9,
                         ref_amount=invoice.total_amount)

    # 3. vendor + nearest po_date (within 30 days before invoice_date)
    if invoice.invoice_date:
        po = (
            PurchaseOrder.objects.filter(
                organization=org, vendor_name=invoice.vendor_name,
                po_date__lte=invoice.invoice_date,
                po_date__gte=invoice.invoice_date - timedelta(days=DATE_PROXIMITY_DAYS),
            )
            .order_by("-po_date")
            .first()
        )
        if po:
            issues = []
            if not _amount_matches(po.total_amount, invoice.total_amount):
                issues.append("amount_mismatch")
            return _link("purchase_order", po, match_type="vendor_date", score=0.7,
                         issues=issues, ref_amount=invoice.total_amount)

    return None


def _find_grn_for_invoice(invoice, org) -> Optional[dict]:
    M = _models()
    GRN = M["goods_receipt_note"]

    # 1. by invoice_number
    if invoice.invoice_number:
        grn = GRN.objects.filter(
            organization=org, invoice_number=invoice.invoice_number,
        ).first()
        if grn:
            return _link("goods_receipt_note", grn, match_type="invoice_number",
                         ref_amount=invoice.total_amount)

    # 2. vendor + amount
    if invoice.vendor_name:
        for grn in GRN.objects.filter(
            organization=org, vendor_name=invoice.vendor_name,
        ).order_by("-grn_date")[:20]:
            if _amount_matches(grn.total_amount, invoice.total_amount):
                return _link("goods_receipt_note", grn, match_type="vendor_amount",
                             score=0.85, ref_amount=invoice.total_amount)

    return None


def _find_payment_for_invoice(invoice, org) -> Optional[dict]:
    M = _models()
    Payment = M["payment_voucher"]

    # 1. by linked_invoice_id
    pay = Payment.objects.filter(organization=org, linked_invoice_id=invoice.id).first()
    if pay:
        return _link("payment_voucher", pay, match_type="linked_invoice_id",
                     ref_amount=invoice.total_amount)

    # 2. by linked_invoice_number
    if invoice.invoice_number:
        pay = Payment.objects.filter(
            organization=org, linked_invoice_number=invoice.invoice_number,
        ).first()
        if pay:
            return _link("payment_voucher", pay, match_type="linked_invoice_number",
                         ref_amount=invoice.total_amount)

    # 3. payee + amount + date >= invoice_date
    if invoice.vendor_name and invoice.invoice_date:
        pay = Payment.objects.filter(
            organization=org, payee_name=invoice.vendor_name,
            payment_date__gte=invoice.invoice_date,
        ).order_by("payment_date").first()
        if pay and _amount_matches(pay.total_amount, invoice.total_amount):
            return _link("payment_voucher", pay, match_type="payee_amount", score=0.8,
                         ref_amount=invoice.total_amount)

    return None


def _find_contract_for_party(party_name: str, ref_date, org) -> Optional[dict]:
    if not party_name:
        return None
    M = _models()
    Contract = M["contract"]
    qs = Contract.objects.filter(organization=org, party_b__iexact=party_name)
    if ref_date:
        qs = qs.filter(start_date__lte=ref_date).filter(
            models.Q(end_date__gte=ref_date) | models.Q(end_date__isnull=True)
        )
    contract = qs.order_by("-start_date").first()
    if contract:
        return _link("contract", contract, match_type="party_active_at_date", score=0.9)
    return None


# Lazily imported `models.Q` for the contract resolver above.
from django.db import models  # noqa: E402  (used by _find_contract_for_party)


# ──────────────────────────────────────────────────────────────────────────────
# Public dispatch
# ──────────────────────────────────────────────────────────────────────────────
def _three_way_match(invoice, po_link: Optional[dict], grn_link: Optional[dict]) -> dict:
    """Compute 3-way match summary for an invoice ↔ PO ↔ GRN trio."""
    if not po_link and not grn_link:
        return {"applicable": False}

    issues: list[str] = []
    inv_amount = float(invoice.total_amount or 0)

    if po_link:
        if abs(po_link.get("amount_diff") or 0) > float(AMOUNT_TOLERANCE):
            issues.append("amount_mismatch_invoice_vs_po")
        if po_link.get("vendor") and invoice.vendor_name and \
                po_link["vendor"].strip().lower() != invoice.vendor_name.strip().lower():
            issues.append("vendor_mismatch_invoice_vs_po")
    else:
        issues.append("missing_po")

    if grn_link:
        if abs(grn_link.get("amount_diff") or 0) > float(AMOUNT_TOLERANCE):
            issues.append("amount_mismatch_invoice_vs_grn")
        if grn_link.get("vendor") and invoice.vendor_name and \
                grn_link["vendor"].strip().lower() != invoice.vendor_name.strip().lower():
            issues.append("vendor_mismatch_invoice_vs_grn")
    else:
        issues.append("missing_grn")

    return {
        "applicable": True,
        "is_clean": not issues,
        "issues": issues,
        "invoice_amount": inv_amount,
        "po_amount": po_link["amount"] if po_link else None,
        "grn_amount": grn_link["amount"] if grn_link else None,
    }


def _links_for_invoice(invoice, org) -> dict:
    po  = _find_po_for_invoice(invoice, org)
    grn = _find_grn_for_invoice(invoice, org)
    pay = _find_payment_for_invoice(invoice, org)
    contract = _find_contract_for_party(invoice.vendor_name, invoice.invoice_date, org)
    return {
        "purchase_order":     po,
        "goods_receipt_note": grn,
        "payment_voucher":    pay,
        "contract":           contract,
        "three_way_match":   _three_way_match(invoice, po, grn),
    }


def _links_for_po(po, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    GRN = M["goods_receipt_note"]
    Payment = M["payment_voucher"]

    # GRN → easiest, by po_number
    grn = None
    if po.po_number:
        g = GRN.objects.filter(organization=org, po_number=po.po_number).first()
        if g:
            grn = _link("goods_receipt_note", g, match_type="po_number",
                        ref_amount=po.total_amount)

    # Invoice → vendor + amount near po_date
    inv_link = None
    if po.vendor_name and po.po_date:
        invs = Invoice.objects.filter(
            organization=org, vendor_name=po.vendor_name,
            invoice_date__gte=po.po_date,
            invoice_date__lte=po.po_date + timedelta(days=90),
        ).order_by("invoice_date")[:10]
        for inv in invs:
            if _amount_matches(inv.total_amount, po.total_amount):
                inv_link = _link("invoice", inv, match_type="vendor_amount", score=0.9,
                                 ref_amount=po.total_amount)
                break
        if inv_link is None and invs:
            inv = invs[0]
            inv_link = _link("invoice", inv, match_type="vendor_date", score=0.6,
                             issues=["amount_mismatch"] if not _amount_matches(inv.total_amount, po.total_amount) else [],
                             ref_amount=po.total_amount)

    # Payment → linked_po_number
    pay = None
    if po.po_number:
        p = Payment.objects.filter(organization=org, linked_po_number=po.po_number).first()
        if p:
            pay = _link("payment_voucher", p, match_type="linked_po_number",
                        ref_amount=po.total_amount)

    contract = _find_contract_for_party(po.vendor_name, po.po_date, org)

    return {
        "invoice":            inv_link,
        "goods_receipt_note": grn,
        "payment_voucher":    pay,
        "contract":           contract,
    }


def _links_for_grn(grn, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    PurchaseOrder = M["purchase_order"]

    po = None
    if grn.po_id:
        p = PurchaseOrder.objects.filter(organization=org, id=grn.po_id).first()
        if p:
            po = _link("purchase_order", p, match_type="po_id",
                       ref_amount=grn.total_amount)
    if po is None and grn.po_number:
        p = PurchaseOrder.objects.filter(organization=org, po_number=grn.po_number).first()
        if p:
            po = _link("purchase_order", p, match_type="po_number",
                       ref_amount=grn.total_amount)

    inv = None
    if grn.invoice_number:
        i = Invoice.objects.filter(organization=org, invoice_number=grn.invoice_number).first()
        if i:
            inv = _link("invoice", i, match_type="invoice_number",
                        ref_amount=grn.total_amount)

    return {"purchase_order": po, "invoice": inv}


def _links_for_payment(pay, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    PurchaseOrder = M["purchase_order"]

    inv = None
    if pay.linked_invoice_id:
        i = Invoice.objects.filter(organization=org, id=pay.linked_invoice_id).first()
        if i:
            inv = _link("invoice", i, match_type="linked_invoice_id",
                        ref_amount=pay.total_amount)
    if inv is None and pay.linked_invoice_number:
        i = Invoice.objects.filter(
            organization=org, invoice_number=pay.linked_invoice_number,
        ).first()
        if i:
            inv = _link("invoice", i, match_type="linked_invoice_number",
                        ref_amount=pay.total_amount)

    po = None
    if pay.linked_po_number:
        p = PurchaseOrder.objects.filter(
            organization=org, po_number=pay.linked_po_number,
        ).first()
        if p:
            po = _link("purchase_order", p, match_type="linked_po_number",
                       ref_amount=pay.total_amount)

    return {"invoice": inv, "purchase_order": po}


def _links_for_sales_order(so, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    Quotation = M["quotation"]

    inv = None
    if so.linked_invoice_id:
        i = Invoice.objects.filter(organization=org, id=so.linked_invoice_id).first()
        if i:
            inv = _link("invoice", i, match_type="linked_invoice_id",
                        ref_amount=so.total_amount)

    quo = None
    if so.linked_quotation_id:
        q = Quotation.objects.filter(organization=org, id=so.linked_quotation_id).first()
        if q:
            quo = _link("quotation", q, match_type="linked_quotation_id")

    return {"invoice": inv, "quotation": quo}


def _links_for_quotation(quote, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    SalesOrder = M["sales_order"]

    so = None
    if quote.converted_to_order_id:
        s = SalesOrder.objects.filter(organization=org, id=quote.converted_to_order_id).first()
        if s:
            so = _link("sales_order", s, match_type="converted_to_order_id")

    inv = None
    if quote.converted_to_invoice_id:
        i = Invoice.objects.filter(organization=org, id=quote.converted_to_invoice_id).first()
        if i:
            inv = _link("invoice", i, match_type="converted_to_invoice_id",
                        ref_amount=quote.total_amount)

    return {"sales_order": so, "invoice": inv}


def _links_for_proforma(pf, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    inv = None
    if pf.converted_invoice_id:
        i = Invoice.objects.filter(organization=org, id=pf.converted_invoice_id).first()
        if i:
            inv = _link("invoice", i, match_type="converted_invoice_id",
                        ref_amount=pf.total_amount)
    return {"invoice": inv}


def _links_for_receipt_voucher(rv, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    inv = None
    if rv.linked_invoice_id:
        i = Invoice.objects.filter(organization=org, id=rv.linked_invoice_id).first()
        if i:
            inv = _link("invoice", i, match_type="linked_invoice_id",
                        ref_amount=rv.amount)
    if inv is None and rv.linked_invoice_number:
        i = Invoice.objects.filter(
            organization=org, invoice_number=rv.linked_invoice_number,
        ).first()
        if i:
            inv = _link("invoice", i, match_type="linked_invoice_number",
                        ref_amount=rv.amount)
    return {"invoice": inv}


def _links_for_contract(contract, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    invoices = []
    if contract.party_b:
        qs = Invoice.objects.filter(
            organization=org, vendor_name__iexact=contract.party_b,
        )
        if contract.start_date:
            qs = qs.filter(invoice_date__gte=contract.start_date)
        if contract.end_date:
            qs = qs.filter(invoice_date__lte=contract.end_date)
        for i in qs.order_by("invoice_date")[:25]:
            invoices.append(
                _link("invoice", i, match_type="party_within_period",
                      ref_amount=contract.contract_value)
            )
    return {"invoices": invoices}


def _links_for_supplier_statement(stmt, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    PaymentVoucher = M["payment_voucher"]
    invoices = []
    payments = []
    if stmt.supplier_name and stmt.period_from and stmt.period_to:
        qs_inv = Invoice.objects.filter(
            organization=org, vendor_name__iexact=stmt.supplier_name,
            invoice_date__range=(stmt.period_from, stmt.period_to),
        ).order_by("invoice_date")[:50]
        invoices = [_link("invoice", i, match_type="vendor_period",
                          ref_amount=None) for i in qs_inv]
        qs_pay = PaymentVoucher.objects.filter(
            organization=org, payee_name__iexact=stmt.supplier_name,
            payment_date__range=(stmt.period_from, stmt.period_to),
        ).order_by("payment_date")[:50]
        payments = [_link("payment_voucher", p, match_type="payee_period")
                    for p in qs_pay]
    return {"invoices": invoices, "payments": payments}


def _links_for_customer_statement(stmt, org) -> dict:
    M = _models()
    Invoice = M["invoice"]
    ReceiptVoucher = M["receipt_voucher"]
    invoices = []
    receipts = []
    if stmt.customer_name and stmt.period_from and stmt.period_to:
        qs_inv = Invoice.objects.filter(
            organization=org, customer_name__iexact=stmt.customer_name,
            invoice_date__range=(stmt.period_from, stmt.period_to),
        ).order_by("invoice_date")[:50]
        invoices = [_link("invoice", i, match_type="customer_period")
                    for i in qs_inv]
        qs_rec = ReceiptVoucher.objects.filter(
            organization=org, payer_name__iexact=stmt.customer_name,
            receipt_date__range=(stmt.period_from, stmt.period_to),
        ).order_by("receipt_date")[:50]
        receipts = [_link("receipt_voucher", r, match_type="payer_period")
                    for r in qs_rec]
    return {"invoices": invoices, "receipts": receipts}


_DISPATCH = {
    "invoice":            _links_for_invoice,
    "purchase_order":     _links_for_po,
    "goods_receipt_note": _links_for_grn,
    "payment_voucher":    _links_for_payment,
    "sales_order":        _links_for_sales_order,
    "quotation":          _links_for_quotation,
    "proforma_invoice":   _links_for_proforma,
    "receipt_voucher":    _links_for_receipt_voucher,
    "contract":           _links_for_contract,
    "supplier_statement": _links_for_supplier_statement,
    "customer_statement": _links_for_customer_statement,
}


def find_links(doc_type: str, doc, org) -> dict:
    """
    Return cross-doc linkage info for any supported document.

    `doc_type` should be one of the keys in `_DISPATCH`. Unknown types
    return an empty dict so callers can stay generic.
    """
    if not doc or not org:
        return {}
    fn = _DISPATCH.get(doc_type)
    if fn is None:
        return {}
    try:
        return fn(doc, org) or {}
    except Exception as exc:
        logger.warning("[cross_doc_linker] %s failed: %s", doc_type, exc)
        return {}


def link_summary_counts(doc_type: str, doc, org) -> dict[str, int]:
    """Compact int summary used by templates that just want a "linked: N" badge."""
    links = find_links(doc_type, doc, org)
    out: dict[str, int] = {}
    for k, v in links.items():
        if k == "three_way_match":
            continue
        if v is None:
            out[k] = 0
        elif isinstance(v, list):
            out[k] = len(v)
        else:
            out[k] = 1
    return out
