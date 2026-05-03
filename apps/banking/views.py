"""HTTP API for the Bank Connectors module — Phase 5."""

from __future__ import annotations

import logging

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import User
from apps.banking.connectors.registry import REGISTRY
from apps.banking.models import (
    BankAccount, BankConnection, BankTransaction, Reconciliation,
)
from apps.banking.services import (
    confirm_reconciliation, load_credentials, reject_reconciliation,
    run_reconciliation, store_credentials, sync_connection,
)

logger = logging.getLogger("finai.banking")


PUBLISH_ROLES = {User.Role.ADMIN, User.Role.CHIEF_AUDIT_OFFICER}


def _can_manage(user) -> bool:
    return user.is_superuser or user.role in PUBLISH_ROLES


def _serialise_connection(c: BankConnection) -> dict:
    return {
        "id":            str(c.id),
        "bank_code":     c.bank_code,
        "bank_name":     c.get_bank_code_display(),
        "display_name":  c.display_name,
        "environment":   c.environment,
        "status":        c.status,
        "last_sync_at":  c.last_sync_at.isoformat() if c.last_sync_at else None,
        "last_error":    c.last_error,
        "accounts":      list(c.accounts.values("id", "account_number", "iban",
                                                "currency", "balance_cached",
                                                "nickname")),
        "created_at":    c.created_at.isoformat(),
    }


def _serialise_transaction(t: BankTransaction) -> dict:
    return {
        "id":            str(t.id),
        "external_id":   t.external_id,
        "posted_at":     t.posted_at.isoformat(),
        "direction":     t.direction,
        "amount":        float(t.amount),
        "currency":      t.currency,
        "reference":     t.reference,
        "description":   t.description,
        "counterparty":  t.counterparty,
        "is_reconciled": t.is_reconciled,
        "account":       t.account.account_number,
    }


def _serialise_reconciliation(r: Reconciliation) -> dict:
    return {
        "id":            str(r.id),
        "score":         r.score,
        "status":        r.status,
        "reasons":       r.reasons,
        "transaction": {
            "id":           str(r.transaction_id),
            "amount":       float(r.transaction.amount) if r.transaction else 0,
            "posted_at":    r.transaction.posted_at.isoformat() if r.transaction else "",
            "counterparty": r.transaction.counterparty if r.transaction else "",
            "description":  r.transaction.description if r.transaction else "",
            "reference":    r.transaction.reference if r.transaction else "",
        } if r.transaction_id else None,
        "invoice": {
            "id":             str(r.invoice_id),
            "invoice_number": r.invoice.invoice_number if r.invoice else "",
            "vendor":         r.invoice.vendor_name if r.invoice else "",
            "total_amount":   float(r.invoice.total_amount) if (r.invoice and r.invoice.total_amount) else 0,
            "invoice_date":   r.invoice.invoice_date.isoformat() if (r.invoice and r.invoice.invoice_date) else "",
        } if r.invoice_id else None,
        "reconciled_by":  r.reconciled_by.full_name if r.reconciled_by else "",
        "reconciled_at":  r.reconciled_at.isoformat() if r.reconciled_at else None,
        "created_at":     r.created_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Connections
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": [], "available_banks": list(REGISTRY)})
        return Response({
            "results": [_serialise_connection(c)
                        for c in BankConnection.objects.filter(organization=org)
                        .prefetch_related("accounts")
                        .order_by("-updated_at")],
            "available_banks": [
                {"code": code, "name": cls.display_name}
                for code, cls in REGISTRY.items()
            ],
        })

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        bank_code   = (request.data.get("bank_code") or "").strip().lower()
        if bank_code not in REGISTRY and bank_code != "other":
            return Response({"error": f"unknown bank_code: {bank_code}"}, status=400)

        try:
            conn = BankConnection.objects.create(
                organization=org,
                bank_code=bank_code,
                display_name=request.data.get("display_name") or "",
                environment=request.data.get("environment") or "mock",
                status=BankConnection.Status.PENDING,
                created_by=request.user,
            )
        except Exception as exc:
            return Response({"error": str(exc)[:240]}, status=400)

        creds = request.data.get("credentials") or {}
        if creds:
            store_credentials(conn, creds)

        return Response(_serialise_connection(conn), status=201)


class ConnectionSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        conn = BankConnection.objects.filter(pk=pk, organization=org).first()
        if not conn:
            return Response({"error": "not found"}, status=404)

        summary = sync_connection(conn)
        return Response({"connection": _serialise_connection(conn), "summary": summary})


# ─────────────────────────────────────────────────────────────────────────────
# Transactions + Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = (
            BankTransaction.objects
            .filter(account__connection__organization=org)
            .select_related("account__connection")
            .order_by("-posted_at")
        )
        if request.GET.get("unreconciled") == "1":
            qs = qs.filter(is_reconciled=False)
        if request.GET.get("direction"):
            qs = qs.filter(direction=request.GET["direction"])
        return Response({"results": [_serialise_transaction(t) for t in qs[:200]]})


class ReconciliationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = (
            Reconciliation.objects.filter(organization=org)
            .select_related("transaction", "invoice", "reconciled_by")
            .order_by("-score", "-created_at")
        )
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        return Response({
            "results": [_serialise_reconciliation(r) for r in qs[:200]],
            "counts": {
                s: Reconciliation.objects.filter(organization=org, status=s).count()
                for s in ("suggested", "confirmed", "rejected", "manual")
            },
        })


class ReconciliationRunView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)
        summary = run_reconciliation(org)
        return Response(summary)


class ReconciliationActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = getattr(request.user, "organization", None)
        recon = Reconciliation.objects.filter(pk=pk, organization=org).first()
        if not recon:
            return Response({"error": "not found"}, status=404)
        action = request.data.get("action")
        if action == "confirm":
            confirm_reconciliation(recon, user=request.user)
        elif action == "reject":
            reject_reconciliation(recon, user=request.user,
                                  notes=request.data.get("notes") or "")
        else:
            return Response({"error": "action must be confirm or reject"}, status=400)
        return Response(_serialise_reconciliation(recon))


# ─────────────────────────────────────────────────────────────────────────────
# Statement upload (fallback)
# ─────────────────────────────────────────────────────────────────────────────

class StatementUploadView(APIView):
    """POST a CSV / XLSX / PDF statement to a specific account; persist
    every row as a BankTransaction so reconciliation can run against it."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        account = (
            BankAccount.objects
            .filter(pk=pk, connection__organization=org)
            .select_related("connection").first()
        )
        if not account:
            return Response({"error": "account not found"}, status=404)

        file_obj = request.FILES.get("statement")
        if not file_obj:
            return Response({"error": "missing 'statement' file"}, status=400)

        from apps.banking import parsers
        ext = (file_obj.name or "").lower().split(".")[-1]
        try:
            if ext == "csv":
                txs = parsers.parse_csv(file_obj.read())
            elif ext == "xlsx":
                # Save to a temp file because openpyxl needs a path.
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    for chunk in file_obj.chunks():
                        tmp.write(chunk)
                    txs = parsers.parse_xlsx(tmp.name)
            elif ext == "pdf":
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    for chunk in file_obj.chunks():
                        tmp.write(chunk)
                    txs = parsers.parse_pdf(tmp.name)
            else:
                return Response({"error": f"unsupported extension: {ext}"}, status=400)
        except Exception as exc:
            logger.exception("[banking.statement-upload] parse failed")
            return Response({"error": f"parse failed: {exc}"[:240]}, status=400)

        imported, skipped = 0, 0
        for tx in txs:
            _, created = BankTransaction.objects.update_or_create(
                account=account, external_id=tx.external_id,
                defaults={
                    "posted_at":    tx.posted_at,
                    "direction":    tx.direction,
                    "amount":       tx.amount,
                    "currency":     tx.currency,
                    "reference":    tx.reference,
                    "description":  tx.description,
                    "counterparty": tx.counterparty,
                    "raw_payload":  tx.raw,
                },
            )
            if created:
                imported += 1
            else:
                skipped += 1

        return Response({
            "ok":        True,
            "imported":  imported,
            "skipped":   skipped,
            "total":     len(txs),
        })
