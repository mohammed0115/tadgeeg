"""Financial Statements API (TADGEEG-FIN-AUDIT-9A · IAS 1).

Additive, organization-scoped, auditor-only endpoint that returns the derived
Balance Sheet / Income Statement + ratios + YoY + anomalies for an engagement.
Advisory only — no persistence, no ledger writes, no opinion.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .services import financial_statements as fs


def _jsonable(value):
    """Recursively convert Decimals to str so the payload is JSON-safe."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class EngagementFinancialStatementsView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Financial Statements"],
                   summary="Derived financial statements (IAS 1)")
    def get(self, request, pk):
        org = getattr(request.user, "organization", None)
        engagement = AuditEngagement.objects.filter(pk=pk, organization=org).first()
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            payload = fs.build_financial_statements(engagement)
        except fs.FinancialStatementError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_jsonable(payload))
