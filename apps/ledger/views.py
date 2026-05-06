"""HTTP API for the General Ledger — Phase 7.1."""

from __future__ import annotations

from datetime import datetime

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import User
from apps.ledger import reports as gl_reports
from apps.ledger import services as gl
from apps.ledger.models import (
    Account, ExchangeRate, JournalEntry, JournalLine,
)


PUBLISH_ROLES = {User.Role.ADMIN, User.Role.CHIEF_AUDIT_OFFICER,
                 User.Role.FINANCE_MANAGER}


def _can_post(user) -> bool:
    return user.is_superuser or user.role in PUBLISH_ROLES


def _serialise_account(a: Account) -> dict:
    return {
        "id":           str(a.id),
        "code":         a.code,
        "name":         a.name,
        "account_type": a.account_type,
        "currency":     a.currency,
        "parent_id":    str(a.parent_id) if a.parent_id else None,
        "is_active":    a.is_active,
    }


def _serialise_entry(e: JournalEntry) -> dict:
    return {
        "id":              str(e.id),
        "entry_number":    e.entry_number,
        "entry_date":      e.entry_date.isoformat(),
        "description":     e.description,
        "reference":       e.reference,
        "source":          e.source,
        "source_object_id": e.source_object_id,
        "currency":        e.currency,
        "base_currency":   e.base_currency,
        "fx_rate":         float(e.fx_rate),
        "status":          e.status,
        "posted_at":       e.posted_at.isoformat() if e.posted_at else None,
        "voided_at":       e.voided_at.isoformat() if e.voided_at else None,
        "voided_by_entry": str(e.voided_by_entry_id) if e.voided_by_entry_id else None,
        "is_balanced":     e.is_balanced(),
        "total_debits":    float(e.total_debits()),
        "total_credits":   float(e.total_credits()),
        "lines": [
            {
                "line_number":  li.line_number,
                "account_code": li.account.code,
                "account_name": li.account.name,
                "debit":        float(li.debit),
                "credit":       float(li.credit),
                "description":  li.description,
                "cost_center":  li.cost_center,
            } for li in e.lines.select_related("account").all()
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chart of Accounts
# ─────────────────────────────────────────────────────────────────────────────

class AccountListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})

        # First call seeds the default chart so a new org isn't empty.
        gl.ensure_default_accounts(org)

        qs = Account.objects.filter(organization=org)
        if request.GET.get("type"):
            qs = qs.filter(account_type=request.GET["type"])
        return Response({
            "results": [_serialise_account(a) for a in qs.order_by("code")],
        })

    def post(self, request):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        for f in ("code", "name", "account_type"):
            if not request.data.get(f):
                return Response({"error": f"{f} is required"}, status=400)

        try:
            a = Account.objects.create(
                organization=org,
                code=request.data["code"],
                name=request.data["name"],
                account_type=request.data["account_type"],
                currency=request.data.get("currency") or "SAR",
                description=request.data.get("description") or "",
            )
        except Exception as exc:
            return Response({"error": str(exc)[:240]}, status=400)
        return Response(_serialise_account(a), status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Journal entries
# ─────────────────────────────────────────────────────────────────────────────

class JournalEntryListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = JournalEntry.objects.filter(organization=org).order_by("-entry_date", "-created_at")
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        if request.GET.get("source"):
            qs = qs.filter(source=request.GET["source"])
        return Response({
            "results": [_serialise_entry(e) for e in qs[:100]],
        })

    def post(self, request):
        """Manually post an entry. Body:

            {
              "entry_date":  "2026-05-04",
              "description": "...",
              "lines": [
                {"account_code": "1200", "debit":  "1150"},
                {"account_code": "4100", "credit": "1000"},
                {"account_code": "2200", "credit": "150"}
              ],
              "currency":         "SAR",
              "idempotency_key":  "manual-2026-05-04-001"
            }
        """
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        try:
            entry_date = datetime.strptime(request.data.get("entry_date") or "", "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "entry_date must be YYYY-MM-DD"}, status=400)

        try:
            entry = gl.post_entry(
                organization=org,
                entry_date=entry_date,
                description=request.data.get("description") or "",
                reference=request.data.get("reference") or "",
                source=request.data.get("source") or JournalEntry.Source.MANUAL,
                source_object_id=request.data.get("source_object_id") or "",
                currency=request.data.get("currency") or "SAR",
                base_currency=request.data.get("base_currency") or "SAR",
                idempotency_key=request.data.get("idempotency_key") or "",
                created_by=request.user,
                lines=request.data.get("lines") or [],
                post_immediately=bool(request.data.get("post", True)),
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_entry(entry), status=201)


class JournalEntryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        org = getattr(request.user, "organization", None)
        e = JournalEntry.objects.filter(pk=pk, organization=org).first()
        if not e:
            return Response({"error": "not found"}, status=404)
        return Response(_serialise_entry(e))


class JournalEntryVoidView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        e = JournalEntry.objects.filter(pk=pk, organization=org).first()
        if not e:
            return Response({"error": "not found"}, status=404)
        if e.status != JournalEntry.Status.POSTED:
            return Response({"error": "only POSTED entries can be voided"}, status=409)
        if e.voided_by_entry_id:
            return Response({"error": "entry is already voided"}, status=409)
        void = gl.void_entry(e, user=request.user,
                             reason=request.data.get("reason") or "")
        e.refresh_from_db()
        return Response({"voided_entry": _serialise_entry(e),
                         "void_compensation": _serialise_entry(void)})


# ─────────────────────────────────────────────────────────────────────────────
# Invoice → GL on demand
# ─────────────────────────────────────────────────────────────────────────────

class PostInvoiceToGLView(APIView):
    """POST /api/v1/ledger/post-invoice/   body: {invoice_id, direction}"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        from apps.invoices.models import Invoice
        invoice = Invoice.objects.filter(
            pk=request.data.get("invoice_id"), organization=org,
        ).first()
        if not invoice:
            return Response({"error": "invoice not found"}, status=404)

        direction = request.data.get("direction") or "purchase"
        if direction not in {"purchase", "sale"}:
            return Response({"error": "direction must be purchase|sale"}, status=400)

        try:
            entry = gl.post_invoice_to_gl(invoice, direction=direction,
                                          created_by=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_entry(entry), status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

class TrialBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"rows": [], "totals": {}})
        as_of = None
        if request.GET.get("as_of"):
            try:
                as_of = datetime.strptime(request.GET["as_of"], "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "as_of must be YYYY-MM-DD"}, status=400)
        result = gl_reports.trial_balance(org, as_of=as_of)
        # ``trial_balance`` returns a list with one dict for forward
        # compatibility (period stacks).
        return Response(result[0])


class GeneralLedgerView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, code):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"account": None, "lines": []})
        from_d = to_d = None
        if request.GET.get("from"):
            from_d = datetime.strptime(request.GET["from"], "%Y-%m-%d").date()
        if request.GET.get("to"):
            to_d = datetime.strptime(request.GET["to"], "%Y-%m-%d").date()
        return Response(gl_reports.general_ledger(
            org, account_code=code, from_date=from_d, to_date=to_d,
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Exchange rates
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeRateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = ExchangeRate.objects.filter(organization=org).order_by("-rate_date")
        return Response({
            "results": [
                {"id": r.id,
                 "from_currency": r.from_currency, "to_currency": r.to_currency,
                 "rate": float(r.rate), "rate_date": r.rate_date.isoformat(),
                 "source": r.source}
                for r in qs[:200]
            ],
        })

    def post(self, request):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        try:
            rate_date = datetime.strptime(request.data.get("rate_date") or "", "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "rate_date must be YYYY-MM-DD"}, status=400)
        try:
            rate = ExchangeRate.objects.update_or_create(
                organization=org,
                from_currency=request.data.get("from_currency") or "",
                to_currency=request.data.get("to_currency") or "",
                rate_date=rate_date,
                defaults={
                    "rate":   request.data.get("rate") or 0,
                    "source": request.data.get("source") or "manual",
                },
            )[0]
        except Exception as exc:
            return Response({"error": str(exc)[:240]}, status=400)
        return Response({
            "id": rate.id, "from_currency": rate.from_currency,
            "to_currency": rate.to_currency, "rate": float(rate.rate),
            "rate_date": rate.rate_date.isoformat(), "source": rate.source,
        }, status=201)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.2 — Accounting periods
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_period(p) -> dict:
    return {
        "id":            str(p.id),
        "name":          p.name,
        "fiscal_year":   p.fiscal_year,
        "period_number": p.period_number,
        "start_date":    p.start_date.isoformat(),
        "end_date":      p.end_date.isoformat(),
        "status":        p.status,
        "closed_at":     p.closed_at.isoformat() if p.closed_at else None,
        "closed_by":     p.closed_by.full_name if p.closed_by else "",
        "locked_at":     p.locked_at.isoformat() if p.locked_at else None,
        "notes":         p.notes,
    }


class PeriodListCreateView(APIView):
    """List periods · seed a fiscal year of 12 monthly periods."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ledger.models import AccountingPeriod
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = AccountingPeriod.objects.filter(organization=org)
        if request.GET.get("year"):
            try:
                qs = qs.filter(fiscal_year=int(request.GET["year"]))
            except ValueError:
                pass
        return Response({"results": [_serialise_period(p) for p in qs]})

    def post(self, request):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)
        try:
            year = int(request.data.get("fiscal_year") or 0)
            if year < 2000 or year > 2100:
                raise ValueError("fiscal_year out of range")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        out = gl.ensure_periods_for_year(org, year)
        return Response(out, status=201)


class PeriodCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        from apps.ledger.models import AccountingPeriod
        org = getattr(request.user, "organization", None)
        period = AccountingPeriod.objects.filter(pk=pk, organization=org).first()
        if not period:
            return Response({"error": "not found"}, status=404)
        try:
            summary = gl.close_period(
                period, user=request.user,
                fx_revaluation=bool(request.data.get("fx_revaluation", True)),
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(summary)


class PeriodReopenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        from apps.ledger.models import AccountingPeriod
        org = getattr(request.user, "organization", None)
        period = AccountingPeriod.objects.filter(pk=pk, organization=org).first()
        if not period:
            return Response({"error": "not found"}, status=404)
        try:
            gl.reopen_period(period, user=request.user,
                             reason=request.data.get("reason") or "")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        period.refresh_from_db()
        return Response(_serialise_period(period))


class PeriodLockView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_post(request.user):
            return Response({"error": "finance/admin role required"}, status=403)
        from apps.ledger.models import AccountingPeriod
        org = getattr(request.user, "organization", None)
        period = AccountingPeriod.objects.filter(pk=pk, organization=org).first()
        if not period:
            return Response({"error": "not found"}, status=404)
        try:
            gl.lock_period(period, user=request.user)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        period.refresh_from_db()
        return Response(_serialise_period(period))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.4 — Multi-jurisdiction tax engine
# ─────────────────────────────────────────────────────────────────────────────

class TaxJurisdictionsView(APIView):
    """List every jurisdiction the engine knows + their standard rates."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.ledger.tax_engine import supported_countries
        return Response({"results": supported_countries()})


class TaxValidateView(APIView):
    """Validate a tax-registration-number for a given country.

    POST {country: "SA", tax_id: "300000000000003"}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from apps.ledger.tax_engine import get_handler
        country = str(request.data.get("country") or "").strip()
        tax_id  = str(request.data.get("tax_id") or "").strip()
        if not country:
            return Response({"error": "country is required"}, status=400)
        handler = get_handler(country)
        result = handler.validate_tax_id(tax_id)
        return Response(result.to_dict())


class TaxComputeView(APIView):
    """Compute tax amount + GL routing for a (country, base_amount, category).

    POST {country: "SA", base_amount: 1000, category: "standard"}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from decimal import Decimal, InvalidOperation
        from apps.ledger.tax_engine import get_handler

        country  = str(request.data.get("country") or "").strip()
        category = str(request.data.get("category") or "standard").strip()
        try:
            base = Decimal(str(request.data.get("base_amount") or "0"))
        except (InvalidOperation, TypeError):
            return Response({"error": "base_amount must be a number"}, status=400)
        if base < 0:
            return Response({"error": "base_amount must be non-negative"}, status=400)

        kwargs = {}
        if "state_rate" in request.data:
            try:
                kwargs["state_rate"] = Decimal(str(request.data["state_rate"]))
            except (InvalidOperation, TypeError):
                return Response({"error": "state_rate must be a number"}, status=400)

        handler = get_handler(country, **kwargs)
        result  = handler.compute(base, category=category)
        return Response(result.to_dict())
