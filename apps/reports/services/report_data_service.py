"""Centralized report data aggregation utilities for report views."""

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth

from apps.invoices.models import Invoice, InvoiceValidationResult


_BIG_FOUR_MAPPING = {
    "KPMG": {"label": "KPMG — Invoice Completeness", "groups": ["INV"], "standard": "ISA 500"},
    "Deloitte": {"label": "Deloitte — Risk & Anomaly Detection", "groups": ["ANO", "DUP"], "standard": "ISA 315"},
    "PwC": {"label": "PwC — Internal Control Testing", "groups": ["CTL"], "standard": "ISA 330"},
    "EY": {"label": "EY — Compliance Verification", "groups": ["VAT", "DOC"], "standard": "ISA 250"},
}

_INDUSTRY_BENCHMARKS = {
    "finance": {"label": "Financial Services & Banking", "compliance_rate_pct": 94.2, "duplicate_rate_pct": 0.8, "avg_risk_score": 18.5, "vat_compliance_rate_pct": 97.8},
    "retail": {"label": "Retail & E-Commerce", "compliance_rate_pct": 88.7, "duplicate_rate_pct": 1.9, "avg_risk_score": 24.1, "vat_compliance_rate_pct": 93.4},
    "construction": {"label": "Construction & Real Estate", "compliance_rate_pct": 85.3, "duplicate_rate_pct": 2.7, "avg_risk_score": 31.4, "vat_compliance_rate_pct": 89.2},
    "healthcare": {"label": "Healthcare & Pharmaceuticals", "compliance_rate_pct": 91.6, "duplicate_rate_pct": 1.1, "avg_risk_score": 20.8, "vat_compliance_rate_pct": 95.1},
    "manufacturing": {"label": "Manufacturing & Industry", "compliance_rate_pct": 87.9, "duplicate_rate_pct": 2.3, "avg_risk_score": 27.6, "vat_compliance_rate_pct": 91.7},
    "services": {"label": "Professional & Business Services", "compliance_rate_pct": 90.1, "duplicate_rate_pct": 1.5, "avg_risk_score": 22.3, "vat_compliance_rate_pct": 94.0},
}


class ReportDataService:
    """Shared aggregation service used by report endpoints and HTML/PDF views."""

    def compute_big_four(self, validation_results_queryset) -> dict:
        """Build Big Four compliance breakdown from a validation result queryset."""
        group_codes = ["INV", "DUP", "VAT", "ANO", "CTL", "DOC"]
        counters = {code: {"passed": 0, "failed": 0, "total": 0} for code in group_codes}

        for detail_payload in validation_results_queryset.values_list("validation_details", flat=True):
            if not isinstance(detail_payload, dict):
                continue
            for rule_code, detail in detail_payload.items():
                group_code = str(rule_code or "").split("-", 1)[0]
                if group_code not in counters:
                    continue
                counters[group_code]["total"] += 1
                if detail.get("passed") is True:
                    counters[group_code]["passed"] += 1
                elif detail.get("passed") is False:
                    counters[group_code]["failed"] += 1

        results = []
        for firm, meta in _BIG_FOUR_MAPPING.items():
            passed = failed = total = 0
            for code in meta["groups"]:
                stats = counters[code]
                passed += stats["passed"]
                failed += stats["failed"]
                total += stats["total"]
            pass_rate = round(passed / total * 100, 1) if total else 0.0
            results.append(
                {
                    "firm": firm,
                    "label": meta["label"],
                    "standard": meta["standard"],
                    "pass_rate": pass_rate,
                    "passed": passed,
                    "failed": failed,
                    "total": total,
                    "status": "compliant" if pass_rate >= 90 else "at_risk" if pass_rate >= 70 else "non_compliant",
                }
            )

        overall_passed = sum(result["passed"] for result in results)
        overall_total = sum(result["total"] for result in results)
        overall_rate = round(overall_passed / overall_total * 100, 1) if overall_total else 0.0
        return {
            "overall_pass_rate": overall_rate,
            "overall_status": "compliant" if overall_rate >= 90 else "at_risk" if overall_rate >= 70 else "non_compliant",
            "firms": results,
        }

    def compute_benchmark(self, org, invoices_queryset) -> dict:
        """Compare organization invoice metrics against built-in industry benchmarks."""
        industry_key = "services"
        org_industry = str(getattr(org, "industry", "") or "").lower()
        for key in _INDUSTRY_BENCHMARKS:
            if key in org_industry:
                industry_key = key
                break
        benchmark = _INDUSTRY_BENCHMARKS[industry_key]

        inv_stats = invoices_queryset.aggregate(
            total=Count("id"),
            compliant=Count("id", filter=Q(status="approved")),
            duplicate=Count("id", filter=Q(is_duplicate=True)),
            avg_risk=Avg("risk_score"),
        )
        total = inv_stats["total"] or 1
        org_compliance = round((inv_stats["compliant"] or 0) / total * 100, 1)
        org_duplicate = round((inv_stats["duplicate"] or 0) / total * 100, 1)
        org_risk = round(float(inv_stats["avg_risk"] or 0), 1)

        vat_qs = InvoiceValidationResult.objects.filter(invoice__in=invoices_queryset)
        vat_total = vat_qs.count() or 1
        org_vat = round(
            vat_qs.filter(
                vat_rate_correct=True,
                vat_calculation_correct=True,
                vat_subtotal_correct=True,
            ).count() / vat_total * 100,
            1,
        )

        def _delta(org_val, bench_val, higher_is_better=True):
            diff = round(org_val - bench_val, 1)
            if higher_is_better:
                status = "above" if diff > 0 else "below" if diff < 0 else "at"
            else:
                status = "below" if diff > 0 else "above" if diff < 0 else "at"
            return {"value": org_val, "benchmark": bench_val, "delta": diff, "status": status}

        metrics = {
            "compliance_rate_pct": _delta(org_compliance, benchmark["compliance_rate_pct"]),
            "duplicate_rate_pct": _delta(org_duplicate, benchmark["duplicate_rate_pct"], higher_is_better=False),
            "avg_risk_score": _delta(org_risk, benchmark["avg_risk_score"], higher_is_better=False),
            "vat_compliance_rate_pct": _delta(org_vat, benchmark["vat_compliance_rate_pct"]),
        }
        above = sum(1 for metric in metrics.values() if metric["status"] == "above")
        below = sum(1 for metric in metrics.values() if metric["status"] == "below")
        return {
            "industry": industry_key,
            "industry_label": benchmark["label"],
            "metrics": metrics,
            "overall_position": "above_average" if above > below else "below_average" if below > above else "average",
        }

    def collect_invoice_data(self, org, date_from=None, date_to=None, audit_session_id=None) -> dict:
        """Aggregate invoice audit data into a stable report contract."""
        inv_qs = Invoice.objects.filter(organization=org)
        if audit_session_id:
            inv_qs = inv_qs.filter(audit_session_id=audit_session_id)
        if date_from:
            inv_qs = inv_qs.filter(invoice_date__gte=date_from)
        if date_to:
            inv_qs = inv_qs.filter(invoice_date__lte=date_to)

        stats = inv_qs.aggregate(
            total_invoices=Count("id"),
            total_invoiced=Sum("total_amount"),
            total_vat=Sum("vat_amount"),
            avg_amount=Avg("total_amount"),
            avg_risk_score=Avg("risk_score"),
            flagged_count=Count("id", filter=Q(status="flagged")),
            approved_count=Count("id", filter=Q(status="approved")),
            rejected_count=Count("id", filter=Q(status="rejected")),
            pending_count=Count("id", filter=Q(status__in=["pending", "processing"])),
            duplicate_count=Count("id", filter=Q(is_duplicate=True)),
            critical_count=Count("id", filter=Q(risk_level="critical")),
            high_count=Count("id", filter=Q(risk_level="high")),
            medium_count=Count("id", filter=Q(risk_level="medium")),
            low_count=Count("id", filter=Q(risk_level="low")),
            new_vendor_count=Count("id", filter=Q(extracted_data__has_key="is_new_vendor")),
            missing_qr_count=Count("id", filter=Q(has_qr_code=False)),
            handwritten_count=Count("id", filter=Q(is_handwritten=True)),
        )
        total_invoices = stats["total_invoices"] or 1

        val_stats = InvoiceValidationResult.objects.filter(
            invoice__organization=org,
            invoice__in=inv_qs,
        ).aggregate(
            avg_score=Avg("validation_score"),
            perfect_score=Count("id", filter=Q(validation_score=100)),
            below_50=Count("id", filter=Q(validation_score__lt=50)),
            below_80=Count("id", filter=Q(validation_score__lt=80)),
        )

        rule_failures = {}
        for validation_result in InvoiceValidationResult.objects.filter(
            invoice__organization=org,
            invoice__in=inv_qs,
        ).only("failed_rule_codes"):
            for code in validation_result.failed_rule_codes or []:
                rule_failures[code] = rule_failures.get(code, 0) + 1

        from core.services.invoice_validator import RULES

        top_failures_detail = [
            {"rule_code": code, "failures": count, "description": RULES.get(code, code)}
            for code, count in sorted(rule_failures.items(), key=lambda item: -item[1])[:10]
        ]

        top_risk = list(
            inv_qs.filter(risk_level__in=["high", "critical"])
            .order_by("-risk_score")
            .values(
                "id",
                "invoice_number",
                "vendor_name",
                "total_amount",
                "currency",
                "invoice_date",
                "risk_level",
                "risk_score",
                "ai_summary",
                "status",
            )[:15]
        )
        for invoice in top_risk:
            invoice["id"] = str(invoice["id"])
            invoice["total_amount"] = float(invoice["total_amount"] or 0)
            invoice["invoice_date"] = str(invoice["invoice_date"]) if invoice["invoice_date"] else None

        duplicates = list(
            inv_qs.filter(is_duplicate=True).values(
                "id",
                "invoice_number",
                "vendor_name",
                "total_amount",
                "currency",
                "invoice_date",
                "status",
                "duplicate_of_id",
            )[:20]
        )
        for duplicate in duplicates:
            duplicate["id"] = str(duplicate["id"])
            duplicate["duplicate_of_id"] = str(duplicate["duplicate_of_id"]) if duplicate["duplicate_of_id"] else None
            duplicate["total_amount"] = float(duplicate["total_amount"] or 0)
            duplicate["invoice_date"] = str(duplicate["invoice_date"]) if duplicate["invoice_date"] else None

        vendor_stats = (
            inv_qs.values("vendor_name")
            .annotate(
                invoice_count=Count("id"),
                vendor_total=Sum("total_amount"),
                avg_amount=Avg("total_amount"),
                flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
                duplicates=Count("id", filter=Q(is_duplicate=True)),
            )
            .order_by("-vendor_total")[:15]
        )
        vendor_list = []
        total_spend = float(stats["total_invoiced"] or 0)
        for vendor in vendor_stats:
            vendor_total = float(vendor["vendor_total"] or 0)
            vendor_list.append(
                {
                    "vendor_name": vendor["vendor_name"],
                    "invoice_count": vendor["invoice_count"],
                    "total_amount": round(vendor_total, 2),
                    "avg_amount": round(float(vendor["avg_amount"] or 0), 2),
                    "spend_share_pct": round(vendor_total / total_spend * 100, 2) if total_spend else 0,
                    "flagged_invoices": vendor["flagged"],
                    "duplicate_invoices": vendor["duplicates"],
                }
            )

        monthly = list(
            inv_qs.annotate(month=TruncMonth("invoice_date"))
            .values("month")
            .annotate(
                total=Sum("total_amount"),
                count=Count("id"),
                flagged=Count("id", filter=Q(risk_level__in=["high", "critical"])),
                duplicates=Count("id", filter=Q(is_duplicate=True)),
            )
            .order_by("month")
        )
        monthly_clean = [
            {
                "month": str(item["month"])[:7] if item["month"] else None,
                "total_amount": round(float(item["total"] or 0), 2),
                "invoice_count": item["count"],
                "flagged_count": item["flagged"],
                "duplicate_count": item["duplicates"],
            }
            for item in monthly
        ]

        vat_compliant = InvoiceValidationResult.objects.filter(
            invoice__organization=org,
            invoice__in=inv_qs,
            vat_rate_correct=True,
            vat_calculation_correct=True,
            vat_subtotal_correct=True,
        ).count()
        vat_total = InvoiceValidationResult.objects.filter(invoice__organization=org, invoice__in=inv_qs).count()

        validation_results = InvoiceValidationResult.objects.filter(invoice__organization=org, invoice__in=inv_qs)
        total_validation_results = validation_results.count() or 1

        def _pct(field_name):
            return round(validation_results.filter(**{field_name: True}).count() / total_validation_results * 100, 1)

        rule_group_summary = {
            "group1_header_validation": {
                "has_invoice_number_pct": _pct("has_invoice_number"),
                "has_invoice_date_pct": _pct("has_invoice_date"),
                "has_vendor_name_pct": _pct("has_vendor_name"),
                "has_vendor_vat_pct": _pct("has_vendor_vat"),
                "has_total_amount_pct": _pct("has_total_amount"),
                "has_currency_pct": _pct("has_currency"),
                "total_greater_zero_pct": _pct("total_greater_zero"),
            },
            "group2_duplicate_detection": {
                "duplicate_invoice_number_pct": round(validation_results.filter(duplicate_invoice_number=True).count() / total_validation_results * 100, 1),
                "duplicate_vendor_amount_date_pct": round(validation_results.filter(duplicate_vendor_amount_date=True).count() / total_validation_results * 100, 1),
                "duplicate_file_hash_pct": round(validation_results.filter(duplicate_file_hash=True).count() / total_validation_results * 100, 1),
            },
            "group3_vat_validation": {
                "vat_rate_correct_pct": _pct("vat_rate_correct"),
                "vat_calculation_correct_pct": _pct("vat_calculation_correct"),
                "vat_subtotal_correct_pct": _pct("vat_subtotal_correct"),
                "vat_number_present_pct": _pct("vat_number_present"),
                "qr_code_valid_pct": _pct("qr_code_valid"),
            },
            "group4_anomaly_detection": {
                "amount_unusually_high_pct": round(validation_results.filter(amount_unusually_high=True).count() / total_validation_results * 100, 1),
                "new_unknown_vendor_pct": round(validation_results.filter(new_unknown_vendor=True).count() / total_validation_results * 100, 1),
                "many_invoices_same_day_pct": round(validation_results.filter(many_invoices_same_day=True).count() / total_validation_results * 100, 1),
                "vendor_dominates_pct": round(validation_results.filter(vendor_dominates_invoices=True).count() / total_validation_results * 100, 1),
            },
            "group5_financial_controls": {
                "has_cost_center_pct": _pct("has_cost_center"),
                "has_account_code_pct": _pct("has_account_code"),
                "has_approver_pct": _pct("has_approver"),
            },
            "group6_document_quality": {
                "document_clear_pct": _pct("document_is_clear"),
                "appears_genuine_pct": _pct("appears_genuine"),
                "no_alterations_pct": _pct("no_alterations"),
                "has_qr_code_pct": _pct("has_qr_code"),
            },
        }

        return {
            "overall_stats": {
                **stats,
                "total_amount": round(float(stats["total_invoiced"] or 0), 2),
                "total_vat": round(float(stats["total_vat"] or 0), 2),
                "avg_amount": round(float(stats["avg_amount"] or 0), 2),
                "avg_risk_score": round(float(stats["avg_risk_score"] or 0), 2),
                "flag_rate_pct": round(stats["flagged_count"] / total_invoices * 100, 2),
                "duplicate_rate_pct": round(stats["duplicate_count"] / total_invoices * 100, 2),
            },
            "validation_summary": {
                **val_stats,
                "avg_score": round(float(val_stats["avg_score"] or 0), 2),
                "vat_compliance_pct": round(vat_compliant / vat_total * 100, 2) if vat_total else 0,
            },
            "top_failed_rules": top_failures_detail,
            "rule_group_summary": rule_group_summary,
            "top_risk_invoices": top_risk,
            "duplicate_invoices": duplicates,
            "vendor_analysis": vendor_list,
            "monthly_trend": monthly_clean,
            "big_four": self.compute_big_four(validation_results),
            "benchmark": self.compute_benchmark(org, inv_qs),
        }
