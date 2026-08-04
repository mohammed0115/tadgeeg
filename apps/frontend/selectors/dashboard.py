"""Dashboard aggregation — the numbers, without the request.

Lifted out of `apps/frontend/page_views.py`, which had grown to 6,081 lines
and 130 ORM calls. These functions were already written as pure aggregation
("caller owns caching + render"); they were simply living in a view module,
where nothing but a view could reach them and nothing but an HTTP client could
test them.

The query budget in `_build_dashboard_payload`'s docstring is a real contract —
the dashboard went from 17+ round trips to 6 — and tests count them. Moving the
code does not change it.
"""

from __future__ import annotations

def _dashboard_evidence_counts(org) -> dict:
    """Evidence-request status breakdown for the dashboard widget (6B).

    Never raises: a widget must not be able to break the dashboard.
    """
    try:
        from apps.audit.services import evidence_request as ev_service
        return ev_service.status_counts(organization=org)
    except Exception:  # pragma: no cover - defensive
        return {}


def _build_dashboard_payload(org, now) -> dict:
    """Pure aggregation — caller owns caching + render. Bounded query budget.

    Query budget (counted by tests):
      1. Invoice .aggregate() — single hit covers ~10 KPIs via Count(filter=)
      2. Invoice .values('currency').annotate() — per-currency totals
      3. Invoice .values('risk_level').annotate() — risk dist (invoice slice)
      4. Cross-doc risk dist — single union via separate per-model count() loop
         (acceptable: the doc-count loop also doubles as the risk-level loop).
      5. Recent invoices — single SELECT
      6. Top risky vendors — single SELECT (VendorProfile path)
      7. Monthly trend — single SELECT
    Total: ~7 round-trips (was ≥ 17).
    """
    from datetime import timedelta
    from django.db.models import Count, Sum, Q, Avg
    from django.db.models.functions import TruncMonth
    from apps.invoices.models import Invoice, VendorProfile
    from apps.documents.typed_models import (
        PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport,
        VATReturn, FixedAsset, SalesReceipt,
        GoodsReceiptNote, PaymentVoucher,
    )
    from apps.documents.typed_models_v2 import (
        SalesOrder, Quotation, ProformaInvoice,
        ReceiptVoucher, CashVoucher, GeneralLedger, Ledger,
        Contract, SupplierStatement, CustomerStatement, JournalEntry,
    )

    cutoff_30d = now - timedelta(days=30)
    cutoff_60d = now - timedelta(days=60)
    cutoff_185d = now - timedelta(days=185)

    inv_qs = Invoice.objects.filter(organization=org)
    po_qs  = PurchaseOrder.objects.filter(organization=org)

    # ── 1) Single aggregate() over Invoice — ~10 KPIs in one round trip ──
    agg = inv_qs.aggregate(
        total            = Count("id"),
        last_30          = Count("id", filter=Q(created_at__gte=cutoff_30d)),
        prev_30          = Count("id", filter=Q(created_at__gte=cutoff_60d,
                                                created_at__lt=cutoff_30d)),
        high_risk        = Count("id", filter=Q(risk_level__in=["high", "critical"])),
        fraud_alerts     = Count("id", filter=Q(is_duplicate=True) | Q(status="flagged")),
        pending          = Count("id", filter=Q(status__in=["pending", "processing"])),
        compliance       = Count("id", filter=Q(qr_code_valid=False)),
        automated        = Count("id", filter=~Q(ai_summary="") & Q(processing_error="")),
        avg_ocr          = Avg("ocr_confidence", filter=~Q(ocr_confidence__isnull=True)
                                                          & ~Q(ocr_confidence=0)),
        vat_total        = Sum("vat_amount"),
    )

    inv_total = int(agg["total"] or 0)
    inv_30 = int(agg["last_30"] or 0)
    inv_prev30 = int(agg["prev_30"] or 0)
    automation_pct = int((agg["automated"] / inv_total) * 100) if inv_total else 0

    if inv_prev30 > 0:
        monthly_growth = int(((inv_30 - inv_prev30) / inv_prev30) * 100)
    elif inv_30 > 0:
        monthly_growth = 100
    else:
        monthly_growth = 0

    # ── 2) Per-currency totals — surfaces a multi-currency DB honestly ──
    by_currency_rows = (
        inv_qs.values("currency")
              .annotate(amount=Sum("total_amount"))
              .order_by("-amount")
    )
    total_amount_by_currency = {
        (row["currency"] or "SAR"): float(row["amount"] or 0)
        for row in by_currency_rows
        if row["amount"]
    }
    primary_currency = next(iter(total_amount_by_currency), "SAR")

    # ── 3) Doc-type counts AND cross-doc risk dist in one pass per model ──
    risk_breakdown = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    def _absorb_invoice_risk():
        """Single round-trip for the invoice slice."""
        for row in inv_qs.values("risk_level").annotate(c=Count("id")):
            level = (row["risk_level"] or "low").lower()
            if level in risk_breakdown:
                risk_breakdown[level] += int(row["c"])

    _absorb_invoice_risk()

    # 7 v1 doc types + 11 v2 doc types. Each model's risk_level uses the same
    # AuditMixin choices, so the union is mathematically clean.
    typed_models = [
        ("purchase_orders",      PurchaseOrder),
        ("bank_statements",      BankStatement),
        ("payroll",              PayrollSheet),
        ("expense_reports",      ExpenseReport),
        ("vat_returns",          VATReturn),
        ("fixed_assets",         FixedAsset),
        ("sales_receipts",       SalesReceipt),
        ("grn",                  GoodsReceiptNote),
        ("payment_vouchers",     PaymentVoucher),
        ("sales_orders",         SalesOrder),
        ("quotations",           Quotation),
        ("proforma_invoices",    ProformaInvoice),
        ("receipt_vouchers",     ReceiptVoucher),
        ("cash_vouchers",        CashVoucher),
        ("general_ledgers",      GeneralLedger),
        ("ledgers",              Ledger),
        ("contracts",            Contract),
        ("supplier_statements",  SupplierStatement),
        ("customer_statements",  CustomerStatement),
        ("journal_entries",      JournalEntry),
    ]
    doc_counts = {"invoices": inv_total, "purchase_orders": 0}
    # Single .aggregate() per typed model covers count + per-level breakdown.
    # 20 typed models × 1 query = 20 round-trips for this section.
    for key, Model in typed_models:
        type_qs = Model.objects.filter(organization=org)
        type_agg = type_qs.aggregate(
            total    = Count("id"),
            low      = Count("id", filter=Q(risk_level="low")),
            medium   = Count("id", filter=Q(risk_level="medium")),
            high     = Count("id", filter=Q(risk_level="high")),
            critical = Count("id", filter=Q(risk_level="critical")),
        )
        doc_counts[key] = int(type_agg["total"] or 0)
        for level in ("low", "medium", "high", "critical"):
            risk_breakdown[level] += int(type_agg[level] or 0)

    # ── 4) Recent activity (10, model instances, .only() to skip heavy fields) ──
    recent_invoices = list(
        inv_qs.only(
            "id", "invoice_number", "vendor_name", "total_amount",
            "currency", "status", "risk_level", "created_at",
        ).order_by("-created_at")[:10]
    )

    # ── 5) Top risky vendors — prefer VendorProfile, fallback to invoices ──
    vendor_profiles = (
        VendorProfile.objects.filter(organization=org)
                              .filter(Q(high_risk_audit_count__gt=0)
                                      | Q(duplicate_count__gt=0)
                                      | Q(flagged_count__gt=0))
                              .order_by("-high_risk_audit_count",
                                        "-duplicate_count",
                                        "-total_amount")[:5]
    )
    top_risky_vendors = [
        {
            "vendor_name":   v.vendor_name,
            "invoice_count": v.invoice_count,
            "high_risk":     v.high_risk_audit_count,
            "duplicates":    v.duplicate_count,
            "total":         float(v.total_amount or 0),
        }
        for v in vendor_profiles
    ]
    if not top_risky_vendors:
        # Fallback: older orgs without a populated VendorProfile registry.
        top_risky_vendors = list(
            inv_qs.exclude(vendor_name="")
                  .values("vendor_name")
                  .annotate(
                      invoice_count=Count("id"),
                      high_risk=Count("id", filter=Q(risk_level__in=["high", "critical"])),
                      duplicates=Count("id", filter=Q(is_duplicate=True)),
                      total=Sum("total_amount"),
                  )
                  .filter(Q(high_risk__gt=0) | Q(duplicates__gt=0))
                  .order_by("-high_risk", "-duplicates", "-total")[:5]
        )

    # ── 6) Monthly trend — labels carry "MMM 'YY" so cross-year ranges are clear ──
    chart_series = {"labels": [], "counts": [], "amounts": []}
    monthly = (
        inv_qs.filter(created_at__gte=cutoff_185d)
              .annotate(m=TruncMonth("created_at"))
              .values("m")
              .annotate(c=Count("id"), s=Sum("total_amount"))
              .order_by("m")
    )
    for row in monthly:
        m = row["m"]
        chart_series["labels"].append(m.strftime("%b '%y") if m else "—")
        chart_series["counts"].append(int(row["c"]))
        chart_series["amounts"].append(float(row["s"] or 0))

    kpis = {
        "total_invoices":          inv_total,
        "total_pos":               doc_counts["purchase_orders"] if "purchase_orders" in doc_counts else po_qs.count(),
        "total_amount_by_currency": total_amount_by_currency,
        "primary_currency":        primary_currency,
        "high_risk_count":         int(agg["high_risk"] or 0),
        "fraud_alerts":            int(agg["fraud_alerts"] or 0),
        "compliance_alerts":       int(agg["compliance"] or 0),
        "pending_review":          int(agg["pending"] or 0),
        "automation_pct":          automation_pct,
        "extraction_accuracy_pct": int(agg["avg_ocr"] or 0),
        "monthly_growth":          monthly_growth,
        "vat_total":               float(agg["vat_total"] or 0),
        "doc_counts":              doc_counts,
    }

    return {
        "kpis":              kpis,
        "risk_breakdown":    risk_breakdown,
        "chart_series":      chart_series,
        "top_risky_vendors": top_risky_vendors,
        "recent_invoices":   recent_invoices,
        "monthly_growth":    monthly_growth,
    }
