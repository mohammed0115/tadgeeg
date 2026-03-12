"""Compliance Views — Regulatory rule checking"""

import logging
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.db.models import Count, Q
from core.services.ai_service import check_compliance_ai
from apps.authentication.permissions import IsComplianceOrAbove
from apps.transactions.models import Transaction
from apps.invoices.models import Invoice
from .models import ComplianceRule, ComplianceViolation
from .serializers import ComplianceRuleSerializer, ComplianceViolationSerializer

logger = logging.getLogger("finai")


class ComplianceCheckView(APIView):
    """Run AI compliance check on transactions."""
    permission_classes = [IsAuthenticated, IsComplianceOrAbove]

    @extend_schema(
        tags=["Compliance"],
        summary="Run regulatory compliance check on transactions",
        request={"type": "object", "properties": {
            "date_from": {"type": "string", "format": "date"},
            "date_to": {"type": "string", "format": "date"},
            "rule_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional specific rules"},
        }},
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        qs = Transaction.objects.filter(organization=org)
        if date_from := request.data.get("date_from"):
            qs = qs.filter(transaction_date__gte=date_from)
        if date_to := request.data.get("date_to"):
            qs = qs.filter(transaction_date__lte=date_to)

        tx_list = list(qs.values(
            "id", "transaction_type", "amount", "currency", "vat_amount",
            "vendor_name", "vendor_vat_number", "invoice_number",
            "transaction_date", "description",
        )[:200])

        for t in tx_list:
            t["id"] = str(t["id"])
            t["amount"] = float(t["amount"])
            t["vat_amount"] = float(t["vat_amount"])
            t["transaction_date"] = str(t["transaction_date"])

        # Load compliance rules
        rule_qs = ComplianceRule.objects.filter(is_active=True)
        if rule_ids := request.data.get("rule_ids"):
            rule_qs = rule_qs.filter(id__in=rule_ids)
        rules = list(rule_qs.values("id", "name", "description", "standard"))
        for r in rules:
            r["id"] = str(r["id"])

        result = check_compliance_ai(tx_list, rules, org.country)

        # Persist violations
        violations_created = 0
        for v in result.get("violations", []):
            try:
                tx = Transaction.objects.get(pk=v["transaction_id"], organization=org)
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

                violation, created = ComplianceViolation.objects.get_or_create(
                    organization=org,
                    transaction=tx,
                    rule_description=v.get("rule_violated", ""),
                    defaults={
                        "invoice": invoice,
                        "standard": v.get("standard", "INTERNAL"),
                        "severity": v.get("severity", "medium"),
                        "description": v.get("description", ""),
                        "corrective_action": v.get("corrective_action", ""),
                    },
                )
                if invoice and violation.invoice_id != invoice.id:
                    violation.invoice = invoice
                    violation.save(update_fields=["invoice"])
                violations_created += 1
            except Transaction.DoesNotExist:
                pass

        result["violations_saved"] = violations_created
        return Response(result)


class ComplianceRuleListView(APIView):
    """List and manage compliance rules."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Compliance"], summary="List compliance rules")
    def get(self, request):
        rules = ComplianceRule.objects.filter(is_active=True).order_by("standard", "name")
        return Response(ComplianceRuleSerializer(rules, many=True).data)

    @extend_schema(tags=["Compliance"], summary="Create a compliance rule")
    def post(self, request):
        serializer = ComplianceRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save(organization=request.user.organization)
        return Response(ComplianceRuleSerializer(rule).data, status=201)


class ComplianceViolationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Compliance"],
        summary="List compliance violations",
        parameters=[
            OpenApiParameter("severity", description="Filter by severity"),
            OpenApiParameter("resolved", description="true|false"),
            OpenApiParameter("standard", description="Filter by standard"),
        ],
    )
    def get(self, request):
        qs = ComplianceViolation.objects.filter(organization=request.user.organization).select_related("transaction", "invoice")
        if severity := request.query_params.get("severity"):
            qs = qs.filter(severity=severity)
        if standard := request.query_params.get("standard"):
            qs = qs.filter(standard=standard)
        if resolved := request.query_params.get("resolved"):
            qs = qs.filter(is_resolved=resolved.lower() == "true")
        return Response(ComplianceViolationSerializer(qs.order_by("-created_at"), many=True).data)


class ResolveComplianceViolationView(APIView):
    permission_classes = [IsAuthenticated, IsComplianceOrAbove]

    @extend_schema(
        tags=["Compliance"],
        summary="Resolve a compliance violation",
        request={"type": "object", "properties": {
            "corrective_action": {"type": "string"},
        }},
    )
    def post(self, request, pk):
        try:
            violation = ComplianceViolation.objects.get(pk=pk, organization=request.user.organization)
        except ComplianceViolation.DoesNotExist:
            return Response({"error": "Violation not found."}, status=404)

        violation.is_resolved = True
        if corrective_action := request.data.get("corrective_action"):
            violation.corrective_action = corrective_action
        violation.save(update_fields=["is_resolved", "corrective_action"])
        return Response(ComplianceViolationSerializer(violation).data)


class VatComplianceView(APIView):
    """Quick VAT compliance summary."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Compliance"],
        summary="VAT compliance summary",
        parameters=[
            OpenApiParameter("month", description="Month YYYY-MM"),
        ],
    )
    def get(self, request):
        import re
        from decimal import Decimal

        org = request.user.organization
        qs = Transaction.objects.filter(organization=org)

        if month := request.query_params.get("month"):
            if re.match(r"^\d{4}-\d{2}$", month):
                qs = qs.filter(transaction_date__startswith=month)

        # Check VAT calculations
        expected_vat_rate = org.vat_rate / 100

        issues = []
        correct = 0
        incorrect = 0

        for tx in qs.filter(transaction_type__in=["income", "expense"])[:500]:
            expected_vat = tx.amount * expected_vat_rate
            actual_vat = tx.vat_amount
            diff = abs(float(expected_vat) - float(actual_vat))

            if diff > 1.0:  # Tolerance of 1 currency unit
                incorrect += 1
                issues.append({
                    "transaction_id": str(tx.id),
                    "amount": float(tx.amount),
                    "expected_vat": round(float(expected_vat), 2),
                    "actual_vat": float(actual_vat),
                    "difference": round(diff, 2),
                    "date": str(tx.transaction_date),
                    "vendor": tx.vendor_name,
                })
            else:
                correct += 1

        total = correct + incorrect
        compliance_rate = round(correct / total * 100, 2) if total else 100.0

        return Response({
            "vat_rate": float(org.vat_rate),
            "currency": org.currency,
            "transactions_checked": total,
            "compliant": correct,
            "non_compliant": incorrect,
            "compliance_rate_pct": compliance_rate,
            "total_vat_discrepancy": sum(i["difference"] for i in issues),
            "issues": issues[:50],
        })
