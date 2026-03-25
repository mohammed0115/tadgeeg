"""API endpoints for accounting rules evaluation and management."""

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from apps.auditing.models import AccountingRuleEvaluation
from apps.auditing.serializers import (
    AccountingRuleEvaluationSerializer,
    AccountingRuleEvaluationDetailedSerializer,
    AccountingRulesEvaluationResponseSerializer,
    RuleStatsByCodeSerializer,
    AccountingFindingsSummarySerializer,
)
from apps.reports.models import Report
from apps.invoices.models import Invoice
from apps.auditing.accounting_rules.services import (
    evaluate_gaap_rules_for_invoice,
    evaluate_ifrs_rules_for_invoice,
    evaluate_rules_for_report,
    aggregate_failed_rules,
    build_accounting_findings_summary,
    compare_ifrs_vs_gaap_findings,
)


class StandardPagination(PageNumberPagination):
    """Standard pagination for API responses."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class AccountingRuleEvaluationListView(generics.ListAPIView):
    """
    List accounting rule evaluations with filtering by standard, status, category.
    
    GET /reports/{report_id}/accounting-rules/?standard=GAAP&status=failed
    GET /invoices/{invoice_id}/accounting-rules/?standard=IFRS
    """

    serializer_class = AccountingRuleEvaluationDetailedSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        """Filter evaluations by organization and optional filters."""
        user_org = self.request.user.organization
        queryset = AccountingRuleEvaluation.objects.filter(
            organization=user_org
        )

        standard = self.request.query_params.get("standard")
        if standard:
            queryset = queryset.filter(standard__iexact=standard)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(rule_status__iexact=status_param)

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(rule_category__iexact=category)

        rule_code = self.request.query_params.get("rule_code")
        if rule_code:
            queryset = queryset.filter(rule_code__icontains=rule_code)

        return queryset.select_related("report", "invoice", "audit_document")


class ReportAccountingRulesListView(generics.ListAPIView):
    """
    List accounting rule evaluations for a specific report.
    
    GET /reports/{report_id}/accounting-rules/
    """

    serializer_class = AccountingRuleEvaluationDetailedSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        """Filter by report and organization."""
        report_id = self.kwargs.get("report_id")
        user_org = self.request.user.organization
        report = get_object_or_404(Report, id=report_id, organization=user_org)
        return AccountingRuleEvaluation.objects.filter(
            report=report, organization=user_org
        ).select_related("invoice", "audit_document")


class InvoiceAccountingRulesListView(generics.ListAPIView):
    """
    List accounting rule evaluations for a specific invoice.
    
    GET /invoices/{invoice_id}/accounting-rules/
    """

    serializer_class = AccountingRuleEvaluationDetailedSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        """Filter by invoice and organization."""
        invoice_id = self.kwargs.get("invoice_id")
        user_org = self.request.user.organization
        invoice = get_object_or_404(Invoice, id=invoice_id, organization=user_org)
        return AccountingRuleEvaluation.objects.filter(
            invoice=invoice, organization=user_org
        ).select_related("report", "audit_document")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_gaap_evaluation_view(request, invoice_id):
    """
    Evaluate a single invoice against GAAP rules and return results.
    
    GET /invoices/{invoice_id}/evaluate/gaap/
    """
    user_org = request.user.organization
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=user_org)
    
    try:
        result = evaluate_gaap_rules_for_invoice(
            invoice_id=str(invoice.id),
            organization_id=str(user_org.id),
        )
        
        serializer = AccountingRulesEvaluationResponseSerializer({
            "summary": result.get("summary", {}),
            "results": result.get("results", []),
            "standard": "GAAP",
            "evaluated_at": None,
        })
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_ifrs_evaluation_view(request, invoice_id):
    """
    Evaluate a single invoice against IFRS rules and return results.
    
    GET /invoices/{invoice_id}/evaluate/ifrs/
    """
    user_org = request.user.organization
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=user_org)
    
    try:
        result = evaluate_ifrs_rules_for_invoice(
            invoice_id=str(invoice.id),
            organization_id=str(user_org.id),
        )
        
        serializer = AccountingRulesEvaluationResponseSerializer({
            "summary": result.get("summary", {}),
            "results": result.get("results", []),
            "standard": "IFRS",
            "evaluated_at": None,
        })
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_accounting_rules_summary_view(request, report_id):
    """
    Get accounting rules summary for a report (both GAAP and IFRS).
    
    GET /reports/{report_id}/accounting-rules-summary/?standard=GAAP,IFRS
    """
    user_org = request.user.organization
    report = get_object_or_404(Report, id=report_id, organization=user_org)
    
    standards = request.query_params.get("standard", "GAAP,IFRS").split(",")
    standards = [s.strip().upper() for s in standards]
    
    summaries = {}
    
    try:
        for standard in standards:
            if standard not in ["GAAP", "IFRS"]:
                continue
            
            summary_data = build_accounting_findings_summary(
                report_id=str(report.id),
                standard=standard,
                organization_id=str(user_org.id),
            )
            
            serializer = AccountingFindingsSummarySerializer(summary_data)
            summaries[standard] = serializer.data
        
        return Response(summaries, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def report_failed_rules_view(request, report_id):
    """
    Get aggregated list of failed rules for a report.
    
    GET /reports/{report_id}/failed-rules/?standard=GAAP
    """
    user_org = request.user.organization
    report = get_object_or_404(Report, id=report_id, organization=user_org)
    
    standard = request.query_params.get("standard", "GAAP").upper()
    
    if standard not in ["GAAP", "IFRS"]:
        return Response(
            {"error": "Standard must be GAAP or IFRS"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        failed_rules = aggregate_failed_rules(
            report_id=str(report.id),
            standard=standard,
            organization_id=str(user_org.id),
        )
        
        serializer = RuleStatsByCodeSerializer(failed_rules, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def compare_standards_view(request, invoice_id):
    """
    Compare GAAP vs IFRS compliance findings for an invoice.
    
    GET /invoices/{invoice_id}/compare-standards/
    """
    user_org = request.user.organization
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=user_org)
    
    try:
        comparison = compare_ifrs_vs_gaap_findings(
            record={"id": str(invoice.id), "entity_type": "invoice"},
            context={
                "organization_id": str(user_org.id),
                "evaluated_at": None,
            },
        )
        
        return Response(comparison, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
