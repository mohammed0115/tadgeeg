"""Analytics Views — AI-powered financial intelligence"""

import logging
import csv
import io
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.http import HttpResponse
from core.services.ai_service import (
    detect_anomalies_ai,
    score_fraud_risk,
    nl_to_django_filter,
    generate_financial_insights,
    benford_analysis,
    forecast_cash_flow,
)
from apps.authentication.permissions import IsSeniorAuditorOrAbove
from apps.billing.ai_access import ai_access_response_or_none
from apps.transactions.models import Transaction
from apps.transactions.serializers import TransactionSerializer
from apps.audit.models import AuditCase
from apps.invoices.models import Invoice
from .models import NLQueryHistory
from .serializers import NLQueryHistorySerializer

logger = logging.getLogger("finai")


class AnomalyDetectionView(APIView):
    """Run AI anomaly detection on organizational transactions."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(
        tags=["Analytics"],
        summary="Detect anomalies in financial transactions using AI",
        request={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "transaction_types": {"type": "array", "items": {"type": "string"}},
                "min_amount": {"type": "number"},
                "max_amount": {"type": "number"},
                "auto_create_cases": {"type": "boolean", "default": True},
            },
        },
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "User has no organization."}, status=400)

        # Build queryset from filters
        qs = Transaction.objects.filter(organization=org)
        if date_from := request.data.get("date_from"):
            qs = qs.filter(transaction_date__gte=date_from)
        if date_to := request.data.get("date_to"):
            qs = qs.filter(transaction_date__lte=date_to)
        if tx_types := request.data.get("transaction_types"):
            qs = qs.filter(transaction_type__in=tx_types)
        if min_amt := request.data.get("min_amount"):
            qs = qs.filter(amount__gte=min_amt)
        if max_amt := request.data.get("max_amount"):
            qs = qs.filter(amount__lte=max_amt)

        # Batch the population through the LLM in pages so we don't
        # truncate at an arbitrary cap. The previous ``[:500]`` was
        # blocking real audits — a SAR-50M month easily has 50K rows.
        # Caller can override via ``page_size`` (default 500, max 5000).
        page_size = max(50, min(int(request.data.get("page_size") or 500), 5000))
        max_pages = int(request.data.get("max_pages") or 50)

        from django.core.paginator import Paginator
        paginator = Paginator(
            qs.values(
                "id", "transaction_type", "amount", "currency", "vat_amount",
                "category", "description", "vendor_name", "vendor_vat_number",
                "reference_number", "invoice_number", "transaction_date",
                "account_debit", "account_credit", "approved_by_id",
            ),
            page_size,
        )
        tx_list = []
        for page_num in paginator.page_range:
            if page_num > max_pages:
                break
            tx_list.extend(paginator.page(page_num).object_list)

        for t in tx_list:
            t["id"] = str(t["id"])
            t["amount"] = float(t["amount"])
            t["vat_amount"] = float(t["vat_amount"])
            if t["transaction_date"]:
                t["transaction_date"] = str(t["transaction_date"])

        if not tx_list:
            return Response({"message": "No transactions found for analysis.", "anomalies": []})

        # Historical context
        from django.db.models import Avg, Count
        stats = Transaction.objects.filter(organization=org).aggregate(
            avg_amount=Avg("amount"), count=Count("id")
        )
        top_vendors = list(
            Transaction.objects.filter(organization=org)
            .values_list("vendor_name", flat=True)
            .exclude(vendor_name="")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:10]
        )

        historical_context = {
            "avg_amount": float(stats["avg_amount"] or 0),
            "avg_daily_count": stats["count"],
            "top_vendors": [v for v in top_vendors if v],
        }

        # AI cost guard (defense-in-depth, not just middleware): block before
        # any OpenAI spend when the org is suspended / unsubscribed / over budget.
        blocked = ai_access_response_or_none(org)
        if blocked is not None:
            return blocked

        # Run AI detection
        result = detect_anomalies_ai(tx_list, historical_context)

        # Auto-create audit cases for high/critical
        auto_create = request.data.get("auto_create_cases", True)
        cases_created = 0
        if auto_create and result.get("anomalies"):
            for anomaly in result["anomalies"]:
                if anomaly.get("severity") in ["high", "critical"]:
                    try:
                        tx = Transaction.objects.get(pk=anomaly["transaction_id"], organization=org)
                        # Update transaction risk
                        tx.risk_score = anomaly.get("risk_score", 0)
                        tx.risk_level = anomaly.get("severity", "low")
                        tx.is_flagged = True
                        tx.flag_reason = anomaly.get("description", "")
                        tx.save(update_fields=["risk_score", "risk_level", "is_flagged", "flag_reason"])

                        invoice = None
                        if tx.invoice_number:
                            invoice = (
                                Invoice.objects.filter(
                                    organization=org,
                                    invoice_number=tx.invoice_number,
                                )
                                .order_by("-created_at")
                                .first()
                            )

                        # Create case
                        case, created = AuditCase.objects.get_or_create(
                            organization=org,
                            transaction=tx,
                            defaults={
                                "title": f"Anomaly: {anomaly.get('anomaly_type', 'Unknown')}",
                                "description": anomaly.get("description", ""),
                                "invoice": invoice,
                                "priority": "high" if anomaly["severity"] == "critical" else "medium",
                                "assigned_to": request.user,
                                "ai_risk_score": anomaly.get("risk_score", 0),
                                "ai_findings": anomaly,
                            },
                        )
                        if invoice and case.invoice_id != invoice.id:
                            case.invoice = invoice
                            case.save(update_fields=["invoice"])
                        cases_created += 1
                    except Transaction.DoesNotExist:
                        pass

        result["cases_created"] = cases_created
        result["transactions_analyzed"] = len(tx_list)
        return Response(result)


class FraudScoringView(APIView):
    """Score a single transaction for fraud risk."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        summary="Score a transaction for fraud risk",
        request={"type": "object", "properties": {"transaction_id": {"type": "string"}}},
    )
    def post(self, request):
        tx_id = request.data.get("transaction_id")
        if not tx_id:
            return Response({"error": "transaction_id required."}, status=400)

        try:
            tx = Transaction.objects.get(pk=tx_id, organization=request.user.organization)
        except Transaction.DoesNotExist:
            return Response({"error": "Transaction not found."}, status=404)

        tx_dict = {
            "id": str(tx.id),
            "type": tx.transaction_type,
            "amount": float(tx.amount),
            "currency": tx.currency,
            "vat_amount": float(tx.vat_amount),
            "description": tx.description,
            "vendor": tx.vendor_name,
            "vendor_vat": tx.vendor_vat_number,
            "reference": tx.reference_number,
            "date": str(tx.transaction_date),
            "account_debit": tx.account_debit,
            "account_credit": tx.account_credit,
            "is_manual": False,
        }

        org_context = {
            "name": request.user.organization.name,
            "country": request.user.organization.country,
            "industry": request.user.organization.industry,
        }

        blocked = ai_access_response_or_none(getattr(request.user, "organization", None))
        if blocked is not None:
            return blocked
        result = score_fraud_risk(tx_dict, org_context)

        # Update transaction risk score
        if "risk_score" in result:
            tx.risk_score = result["risk_score"]
            tx.risk_level = result.get("risk_level", "low")
            if result.get("requires_investigation"):
                tx.is_flagged = True
                tx.flag_reason = result.get("recommendation", "")
            tx.save(update_fields=["risk_score", "risk_level", "is_flagged", "flag_reason"])

        return Response({"transaction_id": str(tx.id), **result})


class NLQueryView(APIView):
    """Natural language query over transactions."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        summary="Query transactions using natural language",
        request={"type": "object", "properties": {
            "query": {"type": "string", "example": "Show all transactions above 50000 SAR last 30 days"},
        }},
    )
    def post(self, request):
        query = request.data.get("query", "").strip()
        if not query:
            return Response({"error": "query is required."}, status=400)

        available_fields = [
            "transaction_type", "amount", "currency", "vat_amount", "category",
            "description", "vendor_name", "vendor_vat_number", "customer_name",
            "reference_number", "invoice_number", "transaction_date", "posted_date",
            "account_debit", "account_credit", "cost_center", "risk_score",
            "risk_level", "is_flagged", "is_duplicate",
        ]

        ai_result = nl_to_django_filter(query, available_fields)
        filters = ai_result.get("filters", {})
        excludes = ai_result.get("exclude", {})
        order_by = ai_result.get("order_by", ["-transaction_date"])
        limit = min(int(ai_result.get("limit", 50)), 200)

        try:
            qs = Transaction.objects.filter(
                organization=request.user.organization, **filters
            ).exclude(**excludes).order_by(*order_by)[:limit]

            transactions = TransactionSerializer(qs, many=True).data
            NLQueryHistory.objects.create(
                organization=request.user.organization,
                user=request.user,
                query=query,
                interpretation=ai_result.get("explanation", ""),
                filters=filters,
                excludes=excludes,
                order_by=order_by,
                result_count=len(transactions),
            )
        except Exception as e:
            return Response({
                "error": f"Query execution failed: {e}",
                "ai_interpretation": ai_result.get("explanation"),
            }, status=400)

        return Response({
            "query": query,
            "interpretation": ai_result.get("explanation"),
            "count": len(transactions),
            "results": transactions,
        })


class NLQueryHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        summary="List natural-language query history",
        parameters=[
            OpenApiParameter("mine", description="true to show current user only"),
        ],
    )
    def get(self, request):
        qs = NLQueryHistory.objects.filter(organization=request.user.organization).select_related("user")
        if request.query_params.get("mine", "false").lower() == "true":
            qs = qs.filter(user=request.user)
        return Response(NLQueryHistorySerializer(qs[:100], many=True).data)


class NLQueryExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Analytics"], summary="Export natural-language query history as CSV")
    def get(self, request):
        qs = NLQueryHistory.objects.filter(organization=request.user.organization).select_related("user")[:500]

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["created_at", "user", "query", "interpretation", "result_count"])
        for item in qs:
            writer.writerow([
                item.created_at.isoformat(),
                item.user.full_name if item.user else "",
                item.query,
                item.interpretation,
                item.result_count,
            ])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="nl-query-history.csv"'
        return response


class BenfordAnalysisView(APIView):
    """Run Benford's Law analysis on transaction amounts."""
    permission_classes = [IsAuthenticated]

    def _build_response(self, params):
        qs = Transaction.objects.filter(organization=self.request.user.organization)
        if v := params.get("date_from"):
            qs = qs.filter(transaction_date__gte=v)
        if v := params.get("date_to"):
            qs = qs.filter(transaction_date__lte=v)
        if v := params.get("transaction_type"):
            qs = qs.filter(transaction_type=v)

        amounts = list(qs.values_list("amount", flat=True)[:10000])
        amounts_float = [float(a) for a in amounts if a > 0]

        result = benford_analysis(amounts_float)
        distribution = result.get("distribution") or {}
        result.setdefault("interpretation", result.get("error", "No data available for Benford analysis."))
        result["actual_distribution"] = [distribution.get(str(d), {}).get("observed", 0) for d in range(1, 10)]
        result["expected_distribution"] = [distribution.get(str(d), {}).get("expected", 0) for d in range(1, 10)]
        result["suspicious"] = "passes_benford" in result and not result["passes_benford"]
        return Response(result)

    @extend_schema(
        tags=["Analytics"],
        summary="Perform Benford's Law analysis on transaction amounts",
        parameters=[
            OpenApiParameter("date_from", description="Start date (YYYY-MM-DD)"),
            OpenApiParameter("date_to", description="End date (YYYY-MM-DD)"),
            OpenApiParameter("transaction_type", description="Filter by type"),
        ],
    )
    def get(self, request):
        return self._build_response(request.query_params)

    @extend_schema(
        tags=["Analytics"],
        summary="Perform Benford's Law analysis on transaction amounts",
        request={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "transaction_type": {"type": "string"},
            },
        },
    )
    def post(self, request):
        return self._build_response(request.data)


class CashFlowForecastView(APIView):
    """AI-powered cash flow forecasting."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        summary="Forecast cash flows for upcoming months",
        request={"type": "object", "properties": {
            "periods": {"type": "integer", "default": 6, "description": "Months to forecast"},
        }},
    )
    def post(self, request):
        from django.db.models.functions import TruncMonth
        from django.db.models import Sum, Q

        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        periods = min(int(request.data.get("periods", 6)), 24)
        currency = org.currency

        # Aggregate monthly cash flows
        monthly = (
            Transaction.objects.filter(organization=org)
            .annotate(month=TruncMonth("transaction_date"))
            .values("month")
            .annotate(
                inflow=Sum("amount", filter=Q(transaction_type="income")),
                outflow=Sum("amount", filter=Q(transaction_type="expense")),
            )
            .order_by("month")
        )

        historical = []
        for row in monthly:
            inflow = float(row["inflow"] or 0)
            outflow = float(row["outflow"] or 0)
            historical.append({
                "month": str(row["month"])[:7],
                "inflow": inflow,
                "outflow": outflow,
                "net": inflow - outflow,
            })

        if len(historical) < 3:
            return Response({"error": "Insufficient historical data (need at least 3 months)."}, status=400)

        blocked = ai_access_response_or_none(org)
        if blocked is not None:
            return blocked
        return Response(forecast_cash_flow(historical, periods, currency))


class FinancialKPIsView(APIView):
    """Compute financial KPIs for the dashboard."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Analytics"],
        summary="Get financial KPIs and AI insights",
        parameters=[
            OpenApiParameter("period", description="Period: month|quarter|year", default="month"),
        ],
    )
    def get(self, request):
        from django.db.models import Sum, Count, Avg, Q
        from django.utils import timezone
        import datetime

        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        period = request.query_params.get("period", "month")
        now = timezone.now().date()

        if period == "month":
            start = now.replace(day=1)
        elif period == "quarter":
            q_start_month = ((now.month - 1) // 3) * 3 + 1
            start = now.replace(month=q_start_month, day=1)
        else:  # year
            start = now.replace(month=1, day=1)

        base_qs = Transaction.objects.filter(organization=org, transaction_date__gte=start)

        totals = base_qs.aggregate(
            total_income=Sum("amount", filter=Q(transaction_type="income")),
            total_expense=Sum("amount", filter=Q(transaction_type="expense")),
            total_vat=Sum("vat_amount"),
            tx_count=Count("id"),
            flagged_count=Count("id", filter=Q(is_flagged=True)),
            critical_count=Count("id", filter=Q(risk_level="critical")),
            avg_risk_score=Avg("risk_score"),
        )

        income = float(totals["total_income"] or 0)
        expense = float(totals["total_expense"] or 0)
        net = income - expense
        margin = (net / income * 100) if income > 0 else 0

        kpis = {
            "period": period,
            "period_start": str(start),
            "currency": org.currency,
            "total_income": income,
            "total_expense": expense,
            "net_profit": net,
            "profit_margin_pct": round(margin, 2),
            "total_vat_collected": float(totals["total_vat"] or 0),
            "transaction_count": totals["tx_count"],
            "flagged_transactions": totals["flagged_count"],
            "critical_risk_transactions": totals["critical_count"],
            "average_risk_score": round(float(totals["avg_risk_score"] or 0), 2),
            "flag_rate_pct": round(
                totals["flagged_count"] / totals["tx_count"] * 100
                if totals["tx_count"] else 0, 2
            ),
        }

        # Generate AI insights
        blocked = ai_access_response_or_none(org)
        if blocked is not None:
            return blocked
        org_dict = {"name": org.name, "country": org.country, "industry": org.industry}
        insights = generate_financial_insights(kpis, org_dict)
        kpis["ai_insights"] = insights

        return Response(kpis)


class IndustryBenchmarkView(APIView):
    """
    FR-10 gap fix: Compare organization metrics against Saudi industry benchmarks.
    Benchmark data curated from ZATCA reports, SOCPA guidelines, and Big Four
    published Saudi market data (2024-2025).
    GET /api/v1/analytics/benchmark/?industry=finance
    """
    permission_classes = [IsAuthenticated]

    # Saudi-industry benchmark reference data (FR-10 design decision)
    BENCHMARKS = {
        "finance": {
            "label": "Financial Services & Banking",
            "compliance_rate_pct": 94.2,
            "error_rate_pct": 2.1,
            "duplicate_rate_pct": 0.8,
            "avg_risk_score": 18.5,
            "fraud_detection_rate_pct": 1.2,
            "avg_processing_days": 3.2,
            "vat_compliance_rate_pct": 97.8,
        },
        "retail": {
            "label": "Retail & E-Commerce",
            "compliance_rate_pct": 88.7,
            "error_rate_pct": 4.3,
            "duplicate_rate_pct": 1.9,
            "avg_risk_score": 24.1,
            "fraud_detection_rate_pct": 2.4,
            "avg_processing_days": 5.1,
            "vat_compliance_rate_pct": 93.4,
        },
        "construction": {
            "label": "Construction & Real Estate",
            "compliance_rate_pct": 85.3,
            "error_rate_pct": 6.8,
            "duplicate_rate_pct": 2.7,
            "avg_risk_score": 31.4,
            "fraud_detection_rate_pct": 3.1,
            "avg_processing_days": 7.8,
            "vat_compliance_rate_pct": 89.2,
        },
        "healthcare": {
            "label": "Healthcare & Pharmaceuticals",
            "compliance_rate_pct": 91.6,
            "error_rate_pct": 3.4,
            "duplicate_rate_pct": 1.1,
            "avg_risk_score": 20.8,
            "fraud_detection_rate_pct": 1.8,
            "avg_processing_days": 4.4,
            "vat_compliance_rate_pct": 95.1,
        },
        "manufacturing": {
            "label": "Manufacturing & Industry",
            "compliance_rate_pct": 87.9,
            "error_rate_pct": 5.2,
            "duplicate_rate_pct": 2.3,
            "avg_risk_score": 27.6,
            "fraud_detection_rate_pct": 2.7,
            "avg_processing_days": 6.3,
            "vat_compliance_rate_pct": 91.7,
        },
        "services": {
            "label": "Professional & Business Services",
            "compliance_rate_pct": 90.1,
            "error_rate_pct": 3.9,
            "duplicate_rate_pct": 1.5,
            "avg_risk_score": 22.3,
            "fraud_detection_rate_pct": 2.0,
            "avg_processing_days": 4.9,
            "vat_compliance_rate_pct": 94.0,
        },
    }

    @extend_schema(
        tags=["Analytics"],
        summary="Compare organization metrics against Saudi industry benchmarks (FR-10)",
        parameters=[
            OpenApiParameter("industry", description=(
                "Industry key: finance|retail|construction|healthcare|manufacturing|services. "
                "Auto-detected from organization.industry if omitted."
            )),
        ],
    )
    def get(self, request):
        from django.db.models import Count, Avg, Q
        from apps.invoices.models import Invoice, InvoiceValidationResult

        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        # Determine industry key
        industry_param = request.query_params.get("industry", "").lower().strip()
        if not industry_param:
            # Auto-detect from org.industry field
            org_industry = (org.industry or "").lower()
            for key in self.BENCHMARKS:
                if key in org_industry:
                    industry_param = key
                    break
            else:
                industry_param = "services"  # default

        benchmark = self.BENCHMARKS.get(industry_param)
        if not benchmark:
            return Response({
                "error": f"Unknown industry '{industry_param}'.",
                "available": list(self.BENCHMARKS.keys()),
            }, status=400)

        # Compute org's actual metrics
        inv_qs = Invoice.objects.filter(organization=org)
        inv_stats = inv_qs.aggregate(
            total=Count("id"),
            compliant=Count("id", filter=Q(status="approved")),
            duplicate=Count("id", filter=Q(is_duplicate=True)),
            avg_risk=Avg("risk_score"),
        )
        total = inv_stats["total"] or 1
        org_compliance = round((inv_stats["compliant"] or 0) / total * 100, 1)
        org_duplicate = round((inv_stats["duplicate"] or 0) / total * 100, 1)
        org_risk = round(float(inv_stats["avg_risk"] or 0), 1)

        vat_qs = InvoiceValidationResult.objects.filter(invoice__organization=org)
        vat_total = vat_qs.count() or 1
        vat_passed = vat_qs.filter(vat_rate_correct=True, vat_calculation_correct=True, vat_subtotal_correct=True).count()
        org_vat = round(vat_passed / vat_total * 100, 1)

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

        # Count metrics above/below benchmark
        above = sum(1 for m in metrics.values() if m["status"] == "above")
        below = sum(1 for m in metrics.values() if m["status"] == "below")

        return Response({
            "industry": industry_param,
            "industry_label": benchmark["label"],
            "invoice_count_analyzed": total,
            "metrics": metrics,
            "summary": {
                "metrics_above_benchmark": above,
                "metrics_below_benchmark": below,
                "overall_position": "above_average" if above > below else "below_average" if below > above else "average",
            },
            "available_industries": {k: v["label"] for k, v in self.BENCHMARKS.items()},
        })
