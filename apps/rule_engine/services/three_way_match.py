"""
ThreeWayMatchService — PO ↔ Invoice ↔ GRN procurement validation.

Purpose
-------
Performs a 3-way match across all three procurement documents:
  - Purchase Order (PO)   — what was authorised to buy
  - Invoice               — what the vendor billed
  - Goods Receipt Note    — what was physically received

Validates four axes, each independently:
  1. Quantity      PO ordered qty ≈ Invoice qty ≈ GRN received qty
  2. Unit Price    PO unit price ≈ Invoice unit price ≈ GRN unit price
  3. Total Amount  PO total ≈ Invoice total ≈ GRN total amount
  4. Vendor        Same vendor name / VAT number on all three documents

Public API
----------
    from apps.rule_engine.services.three_way_match import ThreeWayMatchService

    # Explicit — caller provides all three documents
    result = ThreeWayMatchService().match(
        po=po_doc, invoice=inv_doc, grn=grn_doc, organization_id="..."
    )

    # Auto-discovery — service finds linked docs from NormalizedDocument
    result = ThreeWayMatchService().match_from_document(normalized_doc)

    # From pipeline context (called by ThreeWayMatchStage)
    result = ThreeWayMatchService().match_from_context(context)

Output
------
    result.status           MatchStatus.MATCH | PARTIAL | MISMATCH
    result.match_score      0.0–1.0
    result.checks           list[MatchCheck]  — per-axis detail
    result.discrepancies    list[str]         — human-readable failures
    result.explanation      English summary
    result.explanation_ar   Arabic summary
    result.to_dict()        JSON-serialisable output for pipeline/report
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("rule_engine.three_way_match")

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_TOLERANCE_PCT: float = 5.0     # % tolerance for numeric comparisons
LINE_ITEM_TOLERANCE_PCT: float = 5.0   # per-line item tolerance


# ── Enums ──────────────────────────────────────────────────────────────────────

class MatchStatus(str, Enum):
    MATCH    = "match"     # All critical checks pass within tolerance
    PARTIAL  = "partial"   # Some checks pass, some non-critical checks fail
    MISMATCH = "mismatch"  # One or more critical checks fail

class CheckStatus(str, Enum):
    MATCH    = "match"
    PARTIAL  = "partial"
    MISMATCH = "mismatch"
    SKIPPED  = "skipped"   # Insufficient data to evaluate


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class MatchCheck:
    """
    Result of a single validation axis (quantity / price / total / vendor).

    Fields
    ------
    name            Axis identifier.
    status          MATCH | PARTIAL | MISMATCH | SKIPPED
    po_value        Value from the Purchase Order.
    invoice_value   Value from the Invoice.
    grn_value       Value from the Goods Receipt Note.
    variance_po_inv  % difference between PO and Invoice values.
    variance_po_grn  % difference between PO and GRN values.
    variance_inv_grn % difference between Invoice and GRN values.
    explanation     English-language explanation of the result.
    explanation_ar  Arabic-language explanation.
    is_critical     True when a MISMATCH on this check triggers MISMATCH overall.
    """
    name:             str
    status:           CheckStatus
    po_value:         Any = None
    invoice_value:    Any = None
    grn_value:        Any = None
    variance_po_inv:  Optional[float] = None
    variance_po_grn:  Optional[float] = None
    variance_inv_grn: Optional[float] = None
    explanation:      str = ""
    explanation_ar:   str = ""
    is_critical:      bool = True

    def to_dict(self) -> dict:
        return {
            "name":             self.name,
            "status":           self.status.value if isinstance(self.status, CheckStatus) else self.status,
            "po_value":         self.po_value,
            "invoice_value":    self.invoice_value,
            "grn_value":        self.grn_value,
            "variance_po_inv":  round(self.variance_po_inv, 2) if self.variance_po_inv is not None else None,
            "variance_po_grn":  round(self.variance_po_grn, 2) if self.variance_po_grn is not None else None,
            "variance_inv_grn": round(self.variance_inv_grn, 2) if self.variance_inv_grn is not None else None,
            "explanation":      self.explanation,
            "explanation_ar":   self.explanation_ar,
            "is_critical":      self.is_critical,
        }


@dataclass
class LineItemMatch:
    """Per-line-item 3-way match result (joined by item_code or description)."""
    item_code:           str   = ""
    description:         str   = ""
    po_qty:              float = 0.0
    invoice_qty:         float = 0.0
    grn_qty:             float = 0.0
    po_unit_price:       float = 0.0
    invoice_unit_price:  float = 0.0
    grn_unit_price:      float = 0.0
    qty_status:          CheckStatus = CheckStatus.SKIPPED
    price_status:        CheckStatus = CheckStatus.SKIPPED

    def to_dict(self) -> dict:
        return {
            "item_code":          self.item_code,
            "description":        self.description,
            "po_qty":             self.po_qty,
            "invoice_qty":        self.invoice_qty,
            "grn_qty":            self.grn_qty,
            "po_unit_price":      self.po_unit_price,
            "invoice_unit_price": self.invoice_unit_price,
            "grn_unit_price":     self.grn_unit_price,
            "qty_status":   self.qty_status.value if isinstance(self.qty_status, CheckStatus) else self.qty_status,
            "price_status": self.price_status.value if isinstance(self.price_status, CheckStatus) else self.price_status,
        }


@dataclass
class MatchResult:
    """
    Holistic 3-way match output.

    Attributes
    ----------
    status          Overall MATCH / PARTIAL / MISMATCH verdict.
    match_score     Fraction of critical checks that passed (0.0–1.0).
    checks          One MatchCheck per validation axis.
    line_item_matches  Per-line comparison (empty when line items unavailable).
    discrepancies   Ordered list of human-readable failure messages.
    po_id           UUID of the matched PurchaseOrder (string, may be None).
    invoice_id      UUID of the matched Invoice (string, may be None).
    grn_id          UUID of the matched GoodsReceiptNote (string, may be None).
    po_number       PO reference number.
    invoice_number  Invoice reference number.
    grn_number      GRN reference number.
    vendor_name     Consensus vendor name (PO value preferred).
    currency        Transaction currency.
    tolerance_pct   Numeric tolerance used for this run.
    explanation     English summary.
    explanation_ar  Arabic summary.
    """
    status:             MatchStatus
    match_score:        float
    checks:             list[MatchCheck]           = field(default_factory=list)
    line_item_matches:  list[LineItemMatch]         = field(default_factory=list)
    discrepancies:      list[str]                   = field(default_factory=list)
    po_id:              Optional[str]               = None
    invoice_id:         Optional[str]               = None
    grn_id:             Optional[str]               = None
    po_number:          str                         = ""
    invoice_number:     str                         = ""
    grn_number:         str                         = ""
    vendor_name:        str                         = ""
    currency:           str                         = ""
    tolerance_pct:      float                       = DEFAULT_TOLERANCE_PCT
    explanation:        str                         = ""
    explanation_ar:     str                         = ""

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_matched(self) -> bool:
        return self.status == MatchStatus.MATCH

    @property
    def has_critical_mismatch(self) -> bool:
        return any(
            c.is_critical and c.status == CheckStatus.MISMATCH
            for c in self.checks
        )

    @property
    def failed_checks(self) -> list[MatchCheck]:
        return [c for c in self.checks if c.status == CheckStatus.MISMATCH]

    def to_dict(self) -> dict:
        return {
            "status":            self.status.value if isinstance(self.status, MatchStatus) else self.status,
            "match_score":       round(self.match_score, 3),
            "checks":            [c.to_dict() for c in self.checks],
            "line_item_matches": [l.to_dict() for l in self.line_item_matches],
            "discrepancies":     self.discrepancies,
            "po_id":             self.po_id,
            "invoice_id":        self.invoice_id,
            "grn_id":            self.grn_id,
            "po_number":         self.po_number,
            "invoice_number":    self.invoice_number,
            "grn_number":        self.grn_number,
            "vendor_name":       self.vendor_name,
            "currency":          self.currency,
            "tolerance_pct":     self.tolerance_pct,
            "explanation":       self.explanation,
            "explanation_ar":    self.explanation_ar,
        }


# ── Service ────────────────────────────────────────────────────────────────────

class ThreeWayMatchService:
    """
    Stateless service that performs the PO ↔ Invoice ↔ GRN 3-way match.

    Each public method returns a ``MatchResult`` or None when the required
    documents cannot be discovered (caller should treat None as "not applicable").
    """

    # Document types this service handles
    APPLICABLE_TYPES = frozenset({"purchase_order", "sales_invoice", "grn"})

    def __init__(self, tolerance_pct: float = DEFAULT_TOLERANCE_PCT) -> None:
        self.tolerance_pct = tolerance_pct

    # ── Public entry points ───────────────────────────────────────────────────

    def match(
        self,
        *,
        po,           # PurchaseOrder ORM instance
        invoice,      # Invoice ORM instance
        grn,          # GoodsReceiptNote ORM instance
        organization_id: str,
    ) -> MatchResult:
        """
        Core matching logic. All three ORM objects must be provided.
        Tenant safety is the caller's responsibility.
        """
        checks: list[MatchCheck] = [
            self._check_total_amount(po, invoice, grn),
            self._check_quantity(po, invoice, grn),
            self._check_unit_price(po, invoice, grn),
            self._check_vendor(po, invoice, grn),
        ]

        line_items = self._match_line_items(po, invoice, grn)
        discrepancies = self._collect_discrepancies(checks)
        status, score = self._compute_overall_status(checks)
        explanation, explanation_ar = self._build_explanation(
            status, checks, po, invoice, grn
        )

        result = MatchResult(
            status=status,
            match_score=score,
            checks=checks,
            line_item_matches=line_items,
            discrepancies=discrepancies,
            po_id=str(getattr(po, "id", "") or ""),
            invoice_id=str(getattr(invoice, "id", "") or ""),
            grn_id=str(getattr(grn, "id", "") or ""),
            po_number=str(getattr(po, "po_number", "") or ""),
            invoice_number=str(getattr(invoice, "invoice_number", "") or ""),
            grn_number=str(getattr(grn, "grn_number", "") or ""),
            vendor_name=str(getattr(po, "vendor_name", "") or ""),
            currency=str(getattr(po, "currency", "") or ""),
            tolerance_pct=self.tolerance_pct,
            explanation=explanation,
            explanation_ar=explanation_ar,
        )

        self._persist_links(result, organization_id)
        return result

    def match_from_document(
        self,
        doc,   # NormalizedDocument
    ) -> Optional[MatchResult]:
        """
        Auto-discovers the linked PO + Invoice + GRN from the NormalizedDocument,
        then runs the match. Returns None when discovery fails.
        """
        if doc.document_type not in self.APPLICABLE_TYPES:
            return None

        triplet = self._discover_triplet(doc)
        if triplet is None:
            logger.debug(
                "[3wm] Could not discover full PO+Invoice+GRN triplet for "
                "%s/%s — skipping match.", doc.document_type, doc.document_id
            )
            return None

        po, invoice, grn = triplet
        return self.match(
            po=po, invoice=invoice, grn=grn,
            organization_id=str(doc.organization_id),
        )

    # ── Triplet discovery ─────────────────────────────────────────────────────

    def _discover_triplet(self, doc):
        """Return (PurchaseOrder, Invoice, GoodsReceiptNote) or None."""
        try:
            if doc.document_type == "sales_invoice":
                return self._discover_from_invoice(doc)
            if doc.document_type == "purchase_order":
                return self._discover_from_po(doc)
            if doc.document_type == "grn":
                return self._discover_from_grn(doc)
        except Exception as exc:
            logger.debug("[3wm] Triplet discovery failed: %s", exc)
        return None

    def _discover_from_invoice(self, doc):
        from apps.invoices.models import Invoice
        from apps.documents.typed_models import PurchaseOrder, GoodsReceiptNote
        from apps.rule_engine.models import CrossDocumentLink

        invoice = Invoice.objects.filter(
            id=doc.document_id,
            organization_id=doc.organization_id,
        ).first()
        if not invoice:
            return None

        # PO: via CrossDocumentLink or invoice_number
        po = None
        link = CrossDocumentLink.objects.filter(
            organization_id=doc.organization_id,
            link_type="po_to_invoice",
            target_document_id=doc.document_id,
        ).first()
        if link:
            po = PurchaseOrder.objects.filter(
                id=link.source_document_id,
                organization_id=doc.organization_id,
            ).first()
        if not po and invoice.invoice_number:
            # Fallback: find PO that has this invoice linked
            po = PurchaseOrder.objects.filter(
                linked_invoice_id=invoice.id,
                organization_id=doc.organization_id,
            ).first()

        # GRN: via invoice_number or po FK
        grn = None
        if invoice.invoice_number:
            grn = GoodsReceiptNote.objects.filter(
                invoice_number=invoice.invoice_number,
                organization_id=doc.organization_id,
            ).first()
        if not grn and po:
            grn = GoodsReceiptNote.objects.filter(
                po_id=po.id,
                organization_id=doc.organization_id,
            ).first()

        if po and grn:
            return po, invoice, grn
        return None

    def _discover_from_po(self, doc):
        from apps.documents.typed_models import PurchaseOrder, GoodsReceiptNote
        from apps.invoices.models import Invoice

        po = PurchaseOrder.objects.filter(
            id=doc.document_id,
            organization_id=doc.organization_id,
        ).first()
        if not po:
            return None

        invoice = None
        if po.linked_invoice_id:
            invoice = Invoice.objects.filter(
                id=po.linked_invoice_id,
                organization_id=doc.organization_id,
            ).first()

        grn = GoodsReceiptNote.objects.filter(
            po_id=po.id,
            organization_id=doc.organization_id,
        ).first()

        if invoice and grn:
            return po, invoice, grn
        return None

    def _discover_from_grn(self, doc):
        from apps.documents.typed_models import PurchaseOrder, GoodsReceiptNote
        from apps.invoices.models import Invoice

        grn = GoodsReceiptNote.objects.filter(
            id=doc.document_id,
            organization_id=doc.organization_id,
        ).first()
        if not grn:
            return None

        po = None
        if grn.po_id:
            po = PurchaseOrder.objects.filter(
                id=grn.po_id,
                organization_id=doc.organization_id,
            ).first()

        invoice = None
        if grn.invoice_number:
            invoice = Invoice.objects.filter(
                invoice_number=grn.invoice_number,
                organization_id=doc.organization_id,
            ).first()
        if not invoice and po and po.linked_invoice_id:
            invoice = Invoice.objects.filter(
                id=po.linked_invoice_id,
                organization_id=doc.organization_id,
            ).first()

        if po and invoice:
            return po, invoice, grn
        return None

    # ── Validation axes ───────────────────────────────────────────────────────

    def _check_total_amount(self, po, invoice, grn) -> MatchCheck:
        """Axis 1 — Total amount: PO ≈ Invoice ≈ GRN."""
        po_amt  = self._d(getattr(po, "total_amount", None))
        inv_amt = self._d(getattr(invoice, "total_amount", None))
        grn_amt = self._d(getattr(grn, "total_amount", None))

        if not any([po_amt, inv_amt, grn_amt]):
            return MatchCheck(
                name="total_amount", status=CheckStatus.SKIPPED,
                explanation="No amount data available on any document.",
                explanation_ar="لا توجد بيانات مبلغ على أي من المستندات.",
                is_critical=True,
            )

        tol = Decimal(str(self.tolerance_pct))
        v_pi = self._pct_diff(po_amt, inv_amt)
        v_pg = self._pct_diff(po_amt, grn_amt)
        v_ig = self._pct_diff(inv_amt, grn_amt)

        fails = [v for v in [v_pi, v_pg, v_ig] if v is not None and v > tol]

        if not fails:
            status = CheckStatus.MATCH
            en = (
                f"Total amounts reconcile: PO={po_amt:,.2f}, "
                f"Invoice={inv_amt:,.2f}, GRN={grn_amt:,.2f}."
            )
            ar = (
                f"المبالغ الإجمالية متطابقة: أمر الشراء={po_amt:,.2f}، "
                f"الفاتورة={inv_amt:,.2f}، إشعار الاستلام={grn_amt:,.2f}."
            )
        elif len(fails) < len([v for v in [v_pi, v_pg, v_ig] if v is not None]):
            status = CheckStatus.PARTIAL
            en = (
                f"Partial amount match. PO={po_amt:,.2f}, Invoice={inv_amt:,.2f}, "
                f"GRN={grn_amt:,.2f}. Max variance: {max(fails):.1f}%."
            )
            ar = (
                f"تطابق جزئي للمبالغ. الحد الأقصى للتباين: {max(fails):.1f}%."
            )
        else:
            status = CheckStatus.MISMATCH
            en = (
                f"Amount mismatch: PO={po_amt:,.2f}, Invoice={inv_amt:,.2f}, "
                f"GRN={grn_amt:,.2f}. Variance exceeds {self.tolerance_pct}% tolerance."
            )
            ar = (
                f"تعارض في المبالغ: أمر الشراء={po_amt:,.2f}، فاتورة={inv_amt:,.2f}، "
                f"إشعار الاستلام={grn_amt:,.2f}. يتجاوز حد التفاوت {self.tolerance_pct}%."
            )

        return MatchCheck(
            name="total_amount",
            status=status,
            po_value=float(po_amt) if po_amt else None,
            invoice_value=float(inv_amt) if inv_amt else None,
            grn_value=float(grn_amt) if grn_amt else None,
            variance_po_inv=float(v_pi) if v_pi is not None else None,
            variance_po_grn=float(v_pg) if v_pg is not None else None,
            variance_inv_grn=float(v_ig) if v_ig is not None else None,
            explanation=en,
            explanation_ar=ar,
            is_critical=True,
        )

    def _check_quantity(self, po, invoice, grn) -> MatchCheck:
        """Axis 2 — Quantity: PO ordered qty ≈ GRN received qty."""
        po_qty  = self._d(getattr(po, "total_ordered_qty", None)
                          or self._sum_line_qty(getattr(po, "line_items", [])))
        grn_qty = self._d(getattr(grn, "total_received_qty", None)
                          or self._sum_line_qty(getattr(grn, "line_items", [])))
        inv_qty = self._d(self._sum_line_qty(getattr(invoice, "line_items", [])))

        # GRN qty vs PO ordered qty is the primary quantity check
        if not po_qty and not grn_qty:
            return MatchCheck(
                name="quantity", status=CheckStatus.SKIPPED,
                explanation="Quantity data unavailable.",
                explanation_ar="بيانات الكمية غير متوفرة.",
                is_critical=True,
            )

        tol = Decimal(str(self.tolerance_pct))
        v_pg = self._pct_diff(po_qty, grn_qty)
        v_pi = self._pct_diff(po_qty, inv_qty) if inv_qty else None
        v_ig = self._pct_diff(inv_qty, grn_qty) if inv_qty else None

        primary_fail = v_pg is not None and v_pg > tol

        if not primary_fail:
            status = CheckStatus.MATCH
            en = (
                f"Quantities reconcile: PO ordered={po_qty}, "
                f"GRN received={grn_qty}."
            )
            ar = (
                f"الكميات متطابقة: مطلوب={po_qty}، مستلم={grn_qty}."
            )
        elif v_pg is not None and v_pg > tol * 2:
            status = CheckStatus.MISMATCH
            en = (
                f"Critical quantity mismatch: PO ordered={po_qty}, "
                f"GRN received={grn_qty} ({v_pg:.1f}% variance)."
            )
            ar = (
                f"تعارض حرج في الكميات: مطلوب={po_qty}، مستلم={grn_qty} "
                f"(تباين {v_pg:.1f}%)."
            )
        else:
            status = CheckStatus.PARTIAL
            en = (
                f"Quantity variance within extended range: PO={po_qty}, "
                f"GRN={grn_qty} ({v_pg:.1f}% variance)."
            )
            ar = (
                f"تباين الكمية ضمن نطاق موسع: المطلوب={po_qty}، المستلم={grn_qty}."
            )

        return MatchCheck(
            name="quantity",
            status=status,
            po_value=float(po_qty) if po_qty else None,
            invoice_value=float(inv_qty) if inv_qty else None,
            grn_value=float(grn_qty) if grn_qty else None,
            variance_po_inv=float(v_pi) if v_pi is not None else None,
            variance_po_grn=float(v_pg) if v_pg is not None else None,
            variance_inv_grn=float(v_ig) if v_ig is not None else None,
            explanation=en,
            explanation_ar=ar,
            is_critical=True,
        )

    def _check_unit_price(self, po, invoice, grn) -> MatchCheck:
        """Axis 3 — Unit price: compare first matching line item across docs."""
        po_items  = getattr(po, "line_items", []) or []
        inv_items = getattr(invoice, "line_items", []) or []
        grn_items = getattr(grn, "line_items", []) or []

        if not po_items:
            return MatchCheck(
                name="unit_price", status=CheckStatus.SKIPPED,
                explanation="No line items on PO — unit price check skipped.",
                explanation_ar="لا توجد بنود في أمر الشراء — تخطّي فحص سعر الوحدة.",
                is_critical=False,
            )

        tol = Decimal(str(self.tolerance_pct))
        deviations: list[str] = []
        checked = 0

        for po_item in po_items[:20]:  # cap at 20 items
            code = str(po_item.get("item_code") or po_item.get("description") or "").strip().lower()
            po_price = self._d(po_item.get("unit_price") or po_item.get("total", 0))

            inv_price = self._find_item_price(inv_items, code)
            grn_price = self._find_item_price(grn_items, code)

            if po_price == 0:
                continue
            checked += 1

            if inv_price:
                v = self._pct_diff(po_price, inv_price)
                if v and v > tol:
                    deviations.append(
                        f"'{code}': PO={po_price:,.2f} vs Invoice={inv_price:,.2f} ({v:.1f}%)"
                    )
            if grn_price:
                v = self._pct_diff(po_price, grn_price)
                if v and v > tol:
                    deviations.append(
                        f"'{code}': PO={po_price:,.2f} vs GRN={grn_price:,.2f} ({v:.1f}%)"
                    )

        if checked == 0:
            return MatchCheck(
                name="unit_price", status=CheckStatus.SKIPPED,
                explanation="Unit prices not comparable (missing item codes).",
                explanation_ar="لا يمكن مقارنة أسعار الوحدات — رموز البنود مفقودة.",
                is_critical=False,
            )

        if not deviations:
            status = CheckStatus.MATCH
            en = f"Unit prices match across {checked} line item(s)."
            ar = f"أسعار الوحدات متطابقة عبر {checked} بند."
        elif len(deviations) < checked:
            status = CheckStatus.PARTIAL
            en = f"{len(deviations)} of {checked} line item(s) have price deviations: {'; '.join(deviations[:2])}"
            ar = f"{len(deviations)} من {checked} بند تتجاوز حد التفاوت السعري."
        else:
            status = CheckStatus.MISMATCH
            en = f"Unit price mismatch on all checked items: {'; '.join(deviations[:3])}"
            ar = f"تعارض في أسعار الوحدات على جميع البنود المفحوصة."

        return MatchCheck(
            name="unit_price",
            status=status,
            explanation=en,
            explanation_ar=ar,
            is_critical=False,  # Price deviation is high-severity but not blocking alone
        )

    def _check_vendor(self, po, invoice, grn) -> MatchCheck:
        """Axis 4 — Vendor consistency: same vendor on all three documents."""
        po_name  = self._norm_str(getattr(po, "vendor_name", ""))
        inv_name = self._norm_str(getattr(invoice, "vendor_name", ""))
        grn_name = self._norm_str(getattr(grn, "vendor_name", ""))

        po_vat   = self._norm_str(getattr(po, "vendor_vat_number", ""))
        inv_vat  = self._norm_str(getattr(invoice, "vendor_vat_number", ""))

        # Primary match: VAT numbers (if available)
        vat_ok = po_vat and inv_vat and po_vat == inv_vat

        # Name match (case/space normalised)
        name_ok = po_name and inv_name and po_name == inv_name
        name_grn_ok = grn_name and (grn_name == po_name or grn_name == inv_name)

        if not po_name and not inv_name:
            return MatchCheck(
                name="vendor",
                status=CheckStatus.SKIPPED,
                explanation="Vendor name missing from PO or Invoice.",
                explanation_ar="اسم المورد مفقود في أمر الشراء أو الفاتورة.",
                is_critical=False,
            )

        if vat_ok or name_ok:
            if grn_name and not name_grn_ok:
                status = CheckStatus.PARTIAL
                en = (
                    f"PO and Invoice vendor match ('{getattr(po, 'vendor_name', '')}') "
                    f"but GRN shows different vendor '{getattr(grn, 'vendor_name', '')}'."
                )
                ar = "مورد أمر الشراء والفاتورة متطابقان لكن إشعار الاستلام يُظهر مورداً مختلفاً."
            else:
                status = CheckStatus.MATCH
                en = f"Vendor consistent across all documents: '{getattr(po, 'vendor_name', '')}'."
                ar = f"المورد متسق عبر جميع المستندات: '{getattr(po, 'vendor_name', '')}'."
        else:
            status = CheckStatus.MISMATCH
            en = (
                f"Vendor mismatch: PO='{getattr(po, 'vendor_name', '')}', "
                f"Invoice='{getattr(invoice, 'vendor_name', '')}'."
            )
            ar = (
                f"تعارض في المورد: أمر الشراء='{getattr(po, 'vendor_name', '')}'، "
                f"الفاتورة='{getattr(invoice, 'vendor_name', '')}'."
            )

        return MatchCheck(
            name="vendor",
            status=status,
            po_value=getattr(po, "vendor_name", ""),
            invoice_value=getattr(invoice, "vendor_name", ""),
            grn_value=getattr(grn, "vendor_name", ""),
            explanation=en,
            explanation_ar=ar,
            is_critical=True,
        )

    # ── Line items ────────────────────────────────────────────────────────────

    def _match_line_items(self, po, invoice, grn) -> list[LineItemMatch]:
        """Join line items from all three documents by item_code / description."""
        po_items  = {self._item_key(i): i for i in (getattr(po, "line_items", []) or [])}
        inv_items = {self._item_key(i): i for i in (getattr(invoice, "line_items", []) or [])}
        grn_items = {self._item_key(i): i for i in (getattr(grn, "line_items", []) or [])}

        all_keys = set(po_items) | set(inv_items) | set(grn_items)
        tol = Decimal(str(self.tolerance_pct))
        results: list[LineItemMatch] = []

        for key in sorted(all_keys)[:50]:  # cap at 50 items
            po_i  = po_items.get(key, {})
            inv_i = inv_items.get(key, {})
            grn_i = grn_items.get(key, {})

            po_qty  = self._d(po_i.get("qty") or po_i.get("quantity", 0))
            inv_qty = self._d(inv_i.get("qty") or inv_i.get("quantity", 0))
            grn_qty = self._d(grn_i.get("received_qty") or grn_i.get("qty", 0))

            po_price  = self._d(po_i.get("unit_price", 0))
            inv_price = self._d(inv_i.get("unit_price", 0))
            grn_price = self._d(grn_i.get("unit_price", 0))

            qty_v = self._pct_diff(po_qty, grn_qty)
            price_v = self._pct_diff(po_price, inv_price)

            qty_status   = self._threshold_status(qty_v, tol)
            price_status = self._threshold_status(price_v, tol)

            results.append(LineItemMatch(
                item_code=str(po_i.get("item_code") or inv_i.get("item_code") or key or ""),
                description=str(
                    po_i.get("description") or inv_i.get("description") or grn_i.get("description") or key
                ),
                po_qty=float(po_qty),
                invoice_qty=float(inv_qty),
                grn_qty=float(grn_qty),
                po_unit_price=float(po_price),
                invoice_unit_price=float(inv_price),
                grn_unit_price=float(grn_price),
                qty_status=qty_status,
                price_status=price_status,
            ))

        return results

    # ── Overall status & score ─────────────────────────────────────────────────

    def _compute_overall_status(
        self, checks: list[MatchCheck]
    ) -> tuple[MatchStatus, float]:
        """
        Compute overall MatchStatus and match_score from individual checks.

        Score = (passing critical checks) / (total critical checks).
        Status:
          MATCH    — all critical checks pass
          PARTIAL  — ≥1 non-critical fail, all critical pass  OR
                     exactly 1 critical fails with others passing
          MISMATCH — ≥2 critical checks fail OR any critical is MISMATCH
        """
        critical = [c for c in checks if c.is_critical and c.status != CheckStatus.SKIPPED]
        non_critical = [c for c in checks if not c.is_critical and c.status != CheckStatus.SKIPPED]

        if not critical:
            return MatchStatus.PARTIAL, 0.5  # no data — neutral

        passing_critical = sum(1 for c in critical if c.status == CheckStatus.MATCH)
        failing_critical = sum(1 for c in critical if c.status == CheckStatus.MISMATCH)
        score = passing_critical / len(critical)

        if failing_critical >= 2:
            return MatchStatus.MISMATCH, score
        if failing_critical == 1 or any(
            c.status == CheckStatus.PARTIAL for c in critical
        ):
            return MatchStatus.PARTIAL, score
        if any(c.status == CheckStatus.MISMATCH for c in non_critical):
            return MatchStatus.PARTIAL, score

        return MatchStatus.MATCH, score

    # ── Explanation builders ───────────────────────────────────────────────────

    @staticmethod
    def _build_explanation(
        status: MatchStatus,
        checks: list[MatchCheck],
        po, invoice, grn,
    ) -> tuple[str, str]:
        po_num  = getattr(po, "po_number", "?")
        inv_num = getattr(invoice, "invoice_number", "?")
        grn_num = getattr(grn, "grn_number", "?")
        header  = f"PO {po_num} | Invoice {inv_num} | GRN {grn_num}"

        if status == MatchStatus.MATCH:
            en = f"{header}: All checks passed. Procurement 3-way match confirmed."
            ar = f"{header}: اجتاز جميع الفحوصات. تم تأكيد المطابقة الثلاثية."
        elif status == MatchStatus.PARTIAL:
            failed = [c.name for c in checks if c.status != CheckStatus.MATCH and c.status != CheckStatus.SKIPPED]
            en = f"{header}: Partial match. Review required on: {', '.join(failed)}."
            ar = f"{header}: مطابقة جزئية. مراجعة مطلوبة على: {', '.join(failed)}."
        else:
            failed = [c.explanation for c in checks if c.status == CheckStatus.MISMATCH]
            en = f"{header}: MISMATCH detected. {' | '.join(failed[:2])}"
            ar = f"{header}: تم اكتشاف تعارض. {' | '.join(c.explanation_ar for c in checks if c.status == CheckStatus.MISMATCH)[:200]}"

        return en, ar

    # ── Link persistence ───────────────────────────────────────────────────────

    @staticmethod
    def _persist_links(result: MatchResult, organization_id: str) -> None:
        """
        Upsert CrossDocumentLink records for all three document pairs:
          PO → Invoice (po_to_invoice)
          GRN → PO     (grn_to_po)
          GRN → Invoice (grn_to_invoice)
        """
        if not (result.po_id and result.invoice_id and result.grn_id):
            return

        try:
            from apps.rule_engine.models import CrossDocumentLink

            match_status_map = {
                MatchStatus.MATCH:    CrossDocumentLink.MatchStatus.MATCHED,
                MatchStatus.PARTIAL:  CrossDocumentLink.MatchStatus.PARTIAL,
                MatchStatus.MISMATCH: CrossDocumentLink.MatchStatus.CONFLICT,
            }
            cdl_status = match_status_map.get(
                result.status if isinstance(result.status, MatchStatus)
                else MatchStatus(result.status),
                CrossDocumentLink.MatchStatus.UNMATCHED,
            )

            common = {
                "match_status": cdl_status,
                "match_score":  result.match_score,
                "auto_detected": True,
                "match_details": {
                    "three_way_match": True,
                    "score":      result.match_score,
                    "discrepancies": result.discrepancies,
                    "checks":     {c.name: c.status.value for c in result.checks},
                },
            }

            # PO → Invoice
            CrossDocumentLink.objects.update_or_create(
                organization_id=organization_id,
                link_type="po_to_invoice",
                source_document_id=result.po_id,
                target_document_id=result.invoice_id,
                defaults={
                    **common,
                    "source_document_type": "purchase_order",
                    "target_document_type": "sales_invoice",
                    "match_details": {
                        **common["match_details"],
                        "po_amount": next(
                            (c.po_value for c in result.checks if c.name == "total_amount"), None
                        ),
                    },
                },
            )
            # GRN → PO
            CrossDocumentLink.objects.update_or_create(
                organization_id=organization_id,
                link_type="grn_to_po",
                source_document_id=result.grn_id,
                target_document_id=result.po_id,
                defaults={
                    **common,
                    "source_document_type": "grn",
                    "target_document_type": "purchase_order",
                },
            )
            # GRN → Invoice
            CrossDocumentLink.objects.update_or_create(
                organization_id=organization_id,
                link_type="grn_to_invoice",
                source_document_id=result.grn_id,
                target_document_id=result.invoice_id,
                defaults={
                    **common,
                    "source_document_type": "grn",
                    "target_document_type": "sales_invoice",
                },
            )
        except Exception as exc:
            logger.warning("[3wm] Failed to persist cross-document links: %s", exc)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _d(value) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal("0")

    @staticmethod
    def _pct_diff(a: Decimal, b: Decimal) -> Optional[Decimal]:
        if not a or not b:
            return None
        try:
            return abs(a - b) / max(abs(a), abs(b)) * 100
        except (InvalidOperation, ZeroDivisionError):
            return None

    @staticmethod
    def _norm_str(value: str) -> str:
        return " ".join(str(value or "").lower().split())

    @staticmethod
    def _sum_line_qty(items: list) -> Decimal:
        total = Decimal("0")
        for item in items or []:
            qty = item.get("qty") or item.get("quantity") or item.get("received_qty") or 0
            try:
                total += Decimal(str(qty))
            except (InvalidOperation, TypeError):
                pass
        return total

    @staticmethod
    def _item_key(item: dict) -> str:
        code = str(item.get("item_code") or "").strip().lower()
        if code:
            return code
        return str(item.get("description") or "").strip().lower()[:50]

    @staticmethod
    def _find_item_price(items: list, key: str) -> Optional[Decimal]:
        for item in items:
            if (str(item.get("item_code") or "").strip().lower() == key or
                    str(item.get("description") or "").strip().lower()[:50] == key):
                price = item.get("unit_price")
                if price is not None:
                    try:
                        return Decimal(str(price))
                    except (InvalidOperation, TypeError):
                        pass
        return None

    @staticmethod
    def _threshold_status(variance: Optional[Decimal], tol: Decimal) -> CheckStatus:
        if variance is None:
            return CheckStatus.SKIPPED
        if variance <= tol:
            return CheckStatus.MATCH
        if variance <= tol * 2:
            return CheckStatus.PARTIAL
        return CheckStatus.MISMATCH

    @staticmethod
    def _collect_discrepancies(checks: list[MatchCheck]) -> list[str]:
        return [
            c.explanation
            for c in checks
            if c.status in (CheckStatus.MISMATCH, CheckStatus.PARTIAL)
        ]
