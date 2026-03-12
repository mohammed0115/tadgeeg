"""Transactions Views"""

import csv
import io
import logging
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.db.models import Sum, Count, Avg, Q
from .models import Transaction, JournalEntry
from .serializers import TransactionSerializer, JournalEntrySerializer

logger = logging.getLogger("finai")


class TransactionListCreateView(generics.ListCreateAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Transactions"],
        summary="List or create financial transactions",
        parameters=[
            OpenApiParameter("transaction_type"),
            OpenApiParameter("risk_level"),
            OpenApiParameter("is_flagged", type=bool),
            OpenApiParameter("vendor_name"),
            OpenApiParameter("date_from"),
            OpenApiParameter("date_to"),
            OpenApiParameter("min_amount", type=float),
            OpenApiParameter("max_amount", type=float),
            OpenApiParameter("search"),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Transaction.objects.filter(organization=self.request.user.organization)
        p = self.request.query_params
        if v := p.get("transaction_type"):
            qs = qs.filter(transaction_type=v)
        if v := p.get("risk_level"):
            qs = qs.filter(risk_level=v)
        if v := p.get("is_flagged"):
            qs = qs.filter(is_flagged=v.lower() == "true")
        if v := p.get("vendor_name"):
            qs = qs.filter(vendor_name__icontains=v)
        if v := p.get("date_from"):
            qs = qs.filter(transaction_date__gte=v)
        if v := p.get("date_to"):
            qs = qs.filter(transaction_date__lte=v)
        if v := p.get("min_amount"):
            qs = qs.filter(amount__gte=v)
        if v := p.get("max_amount"):
            qs = qs.filter(amount__lte=v)
        if v := p.get("search"):
            qs = qs.filter(
                Q(description__icontains=v) | Q(vendor_name__icontains=v) |
                Q(reference_number__icontains=v) | Q(invoice_number__icontains=v)
            )
        return qs.order_by("-transaction_date")

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class TransactionDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Transactions"], summary="Get, update, or delete a transaction")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return Transaction.objects.filter(organization=self.request.user.organization)


class BulkImportView(APIView):
    """Import transactions from CSV or JSON."""
    parser_classes = [MultiPartParser, JSONParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Transactions"],
        summary="Bulk import transactions from CSV or JSON",
        request={"type": "object", "properties": {
            "file": {"type": "string", "format": "binary"},
            "transactions": {"type": "array"},
        }},
    )
    def post(self, request):
        org = request.user.organization
        if not org:
            return Response({"error": "No organization."}, status=400)

        created = []
        errors = []

        # JSON array import
        if transactions := request.data.get("transactions"):
            for i, tx_data in enumerate(transactions):
                try:
                    tx_data["organization"] = org.id
                    s = TransactionSerializer(data=tx_data)
                    s.is_valid(raise_exception=True)
                    tx = s.save(organization=org)
                    created.append(str(tx.id))
                except Exception as e:
                    errors.append({"index": i, "error": str(e)})

        # CSV file import
        elif file := request.FILES.get("file"):
            try:
                decoded = file.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(decoded))
                for i, row in enumerate(reader):
                    try:
                        tx = Transaction.objects.create(
                            organization=org,
                            transaction_type=row.get("type", "expense").strip(),
                            amount=float(row.get("amount", 0)),
                            currency=row.get("currency", "SAR").strip(),
                            vat_amount=float(row.get("vat_amount", 0)),
                            description=row.get("description", "").strip(),
                            vendor_name=row.get("vendor_name", "").strip(),
                            vendor_vat_number=row.get("vendor_vat_number", "").strip(),
                            reference_number=row.get("reference_number", "").strip(),
                            invoice_number=row.get("invoice_number", "").strip(),
                            transaction_date=row.get("date") or row.get("transaction_date"),
                            category=row.get("category", "").strip(),
                            account_debit=row.get("account_debit", "").strip(),
                            account_credit=row.get("account_credit", "").strip(),
                        )
                        created.append(str(tx.id))
                    except Exception as e:
                        errors.append({"row": i + 2, "error": str(e), "data": dict(row)})
            except Exception as e:
                return Response({"error": f"CSV parsing failed: {e}"}, status=400)
        else:
            return Response({"error": "Provide 'file' (CSV) or 'transactions' (JSON array)."}, status=400)

        return Response({
            "imported": len(created),
            "errors": len(errors),
            "created_ids": created[:100],
            "error_details": errors[:20],
        }, status=status.HTTP_201_CREATED)


class JournalEntryListView(generics.ListCreateAPIView):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Transactions"], summary="List journal entries — manual entries are auto-flagged")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = JournalEntry.objects.filter(organization=self.request.user.organization)
        p = self.request.query_params
        if v := p.get("is_manual"):
            qs = qs.filter(is_manual=v.lower() == "true")
        if v := p.get("is_suspicious"):
            qs = qs.filter(is_suspicious=v.lower() == "true")
        return qs

    def perform_create(self, serializer):
        entry = serializer.save(
            organization=self.request.user.organization,
            posted_by=self.request.user,
        )
        # Auto-flag manual journal entries
        if entry.is_manual:
            entry.is_suspicious = True
            entry.save(update_fields=["is_suspicious"])


class TransactionStatsView(APIView):
    """Quick aggregation stats for dashboard."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Transactions"], summary="Get transaction statistics summary")
    def get(self, request):
        org = request.user.organization
        qs = Transaction.objects.filter(organization=org)
        stats = qs.aggregate(
            total=Count("id"),
            flagged=Count("id", filter=Q(is_flagged=True)),
            duplicates=Count("id", filter=Q(is_duplicate=True)),
            total_income=Sum("amount", filter=Q(transaction_type="income")),
            total_expense=Sum("amount", filter=Q(transaction_type="expense")),
            avg_risk=Avg("risk_score"),
            critical=Count("id", filter=Q(risk_level="critical")),
            high=Count("id", filter=Q(risk_level="high")),
        )
        for key in ["total_income", "total_expense", "avg_risk"]:
            if stats[key] is not None:
                stats[key] = round(float(stats[key]), 2)
        return Response(stats)
