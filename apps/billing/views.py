"""Stage 2 endpoints — plan selection.

Two routes:
  GET  /billing/plans/         → list of purchasable plans
  POST /billing/select-plan/   → kick off either free_trial activation
                                  or a pending_payment subscription

Both routes are reachable WITHOUT a subscription (the
SubscriptionRequiredMiddleware whitelists them) — that's the entire
point of this stage.

Payment-integration glue is Stage 4. Until then, a paid-plan selection
returns a 200 with a ``next`` field pointing at where the user should
go once payments are wired up; the front-end can show "Payment
integration pending" or queue the redirect.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _


def _stringify_expired_message() -> str:
    return str(_("Your subscription has expired. Please renew to continue."))
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.choices import PlanCode, SubscriptionStatus
from apps.billing.models import OrganizationSubscription
from apps.billing.serializers import (
    PlanSerializer,
    SelectPlanSerializer,
    SubscriptionSerializer,
)
from apps.billing.services.plan_service import (
    PlanNotFound,
    get_active_plan,
    list_purchasable_plans,
)
from apps.billing.services.subscription_service import (
    FreeTrialAlreadyUsed,
    SubscriptionError,
    SubscriptionService,
)


# Within this window, repeatedly POSTing /select-plan/ with the same
# plan returns the existing pending subscription + checkout_url rather
# than creating a new payment. Stops accidental double-charging when a
# user double-clicks the button.
_PENDING_REUSE_WINDOW = timedelta(minutes=15)


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _initiate_payment(request, subscription, plan):
    """Create the PaymentTransaction for a pending subscription, link
    them, and return the gateway's checkout URL.

    Kept here (not in SubscriptionService) so that apps/billing has a
    soft dependency on apps/payments — billing is still importable
    without payments installed; the import only fires when the user
    actually hits the paid-plan path."""
    from apps.payments.services.payment_service import (
        PaymentService,
        PaymentValidationError,
    )
    from apps.payments.gateways.base import GatewayError

    callback_provider = (getattr(settings, "PAYMENT_PROVIDER", "") or "").strip().lower()
    success_url_tmpl = request.build_absolute_uri(
        f"/payments/callback/{callback_provider}/"
    ) + "?transaction_id={transaction_id}"

    try:
        txn = PaymentService().create_transaction(
            organization=subscription.organization,
            user=request.user,
            amount=plan.price,
            currency=plan.currency,
            purpose="subscription",
            reference_type="organization_subscription",
            reference_id=str(subscription.id),
            success_url=success_url_tmpl,
            cancel_url=request.build_absolute_uri("/billing/plans/"),
            failure_url=request.build_absolute_uri("/billing/plans/?failed=1"),
            idempotency_key=f"sub:{subscription.id}",
            metadata={"plan_code": plan.code, "subscription_id": str(subscription.id)},
            request_ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        )
    except (PaymentValidationError, GatewayError) as exc:
        return None, str(exc)

    # Link payment → subscription so future webhook receivers can find it.
    if subscription.payment_transaction != txn.id:
        subscription.payment_transaction = txn.id
        subscription.save(update_fields=["payment_transaction", "updated_at"])

    return txn, None


def _wants_html(request) -> bool:
    """Decide whether to render HTML or JSON for billing pages.

    JSON wins when an explicit Accept header asks for it (SPA/API), or
    when the request is to a path that lives under /api/. Otherwise we
    render the template so a browser GET works without extra config.
    """
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept and "text/html" not in accept:
        return False
    if request.path.startswith("/api/"):
        return False
    return True


class PlansView(APIView):
    """GET /billing/plans/

    Content negotiation:
    - HTML (browser)            → templates/billing/plans.html
    - JSON (SPA, ?format=json)  → {plans, has_used_free_trial}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = list_purchasable_plans()
        used_trial = self._has_used_free_trial(request.user.organization)
        if not _wants_html(request):
            return Response({
                "plans": PlanSerializer(plans, many=True).data,
                "has_used_free_trial": used_trial,
            })

        # Surface a friendly message when the user has been bounced here
        # because their previous subscription expired.
        expired_message = ""
        if OrganizationSubscription.objects.filter(
            organization=request.user.organization,
            status="expired",
        ).exists():
            expired_message = _stringify_expired_message()
        return render(request, "billing/plans.html", {
            "plans": plans,
            "has_used_free_trial": used_trial,
            "expired_message": expired_message,
            "active_nav": "plans",
        })

    @staticmethod
    def _has_used_free_trial(organization) -> bool:
        return OrganizationSubscription.objects.filter(
            organization=organization, plan__is_trial=True,
        ).exists()


class SelectPlanView(APIView):
    """POST /billing/select-plan/

    Body:  ``{"plan_code": "free_trial"|"starter"|"business"|"professional"}``

    For free_trial → creates a TRIALING subscription, returns dashboard URL.
    For paid plan  → creates a PENDING_PAYMENT subscription, returns the
                     URL where payment will be initiated (Stage 4 wires it).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = SelectPlanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan_code = ser.validated_data["plan_code"]

        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response(
                {"detail": "User is not attached to an organization."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            plan = get_active_plan(plan_code)
        except PlanNotFound as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_404_NOT_FOUND)

        svc = SubscriptionService()
        if plan_code == PlanCode.FREE_TRIAL.value:
            try:
                sub = svc.create_free_trial(organization)
            except FreeTrialAlreadyUsed as exc:
                return Response(
                    {"detail": str(exc), "code": "free_trial_already_used"},
                    status=drf_status.HTTP_409_CONFLICT,
                )
            return Response({
                "subscription": SubscriptionSerializer(sub).data,
                "next": "/dashboard/",
                "message": "Free trial activated.",
            }, status=drf_status.HTTP_201_CREATED)

        # Paid plan path — Stage 4 wires this through PaymentService.
        #
        # Idempotency: if the same org already has a PENDING_PAYMENT
        # subscription for the same plan, less than 15 minutes old, with
        # a usable checkout_url, return that one. Stops accidental
        # double-charging on retried form submissions.
        sub = self._reuse_recent_pending(organization, plan)
        if sub is None:
            try:
                sub = svc.create_pending_paid_subscription(organization, plan)
            except SubscriptionError as exc:
                return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)

        # Already have a fresh checkout URL? Return it without re-charging.
        if sub.payment_transaction:
            from apps.payments.models import PaymentTransaction
            existing_txn = PaymentTransaction.objects.filter(
                pk=sub.payment_transaction, organization=organization,
            ).first()
            if existing_txn and existing_txn.checkout_url and not existing_txn.is_terminal:
                return Response({
                    "subscription": SubscriptionSerializer(sub).data,
                    "next": existing_txn.checkout_url,
                    "transaction_id": str(existing_txn.id),
                    "message": "Existing pending payment reused.",
                }, status=drf_status.HTTP_200_OK)

        txn, error = _initiate_payment(request, sub, plan)
        if txn is None:
            return Response(
                {"detail": error or "Could not initiate payment with the configured gateway."},
                status=drf_status.HTTP_502_BAD_GATEWAY,
            )

        return Response({
            "subscription": SubscriptionSerializer(sub).data,
            "next": txn.checkout_url,
            "transaction_id": str(txn.id),
            "message": "Payment initiated. Redirect the user to next URL.",
        }, status=drf_status.HTTP_201_CREATED)

    @staticmethod
    def _reuse_recent_pending(organization, plan):
        cutoff = timezone.now() - _PENDING_REUSE_WINDOW
        return (
            OrganizationSubscription.objects
            .filter(
                organization=organization,
                plan=plan,
                status=SubscriptionStatus.PENDING_PAYMENT,
                created_at__gte=cutoff,
            )
            .order_by("-created_at")
            .first()
        )


class CurrentSubscriptionView(APIView):
    """GET /billing/subscription/

    HTML: render templates/billing/subscription.html.
    JSON: ``{"subscription": <SubscriptionSerializer>|null}``.

    Falls back to the most-recent (any status) subscription when there
    is no usable one, so a user whose plan just expired still lands on
    a meaningful page with renew/upgrade buttons instead of an empty
    'no subscription' card."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response(
                {"detail": "User is not attached to an organization."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        from apps.billing.services.quota_service import QuotaService
        sub = QuotaService().get_active_subscription(organization)
        if sub is None:
            # Show the most recent row (likely expired/payment_failed)
            # so the UI can render renew/retry buttons rather than a
            # bare "no subscription" empty state.
            sub = (
                OrganizationSubscription.objects
                .select_related("plan")
                .filter(organization=organization)
                .order_by("-created_at")
                .first()
            )

        if not _wants_html(request):
            if sub is None:
                return Response({"subscription": None})
            return Response({"subscription": SubscriptionSerializer(sub).data})

        # HTML render
        usage_pct = 0
        remaining = 0
        if sub is not None and sub.invoice_limit > 0:
            usage_pct = int(round(
                (sub.used_invoices + sub.reserved_invoices) * 100 / sub.invoice_limit
            ))
            remaining = sub.remaining_invoices
        return render(request, "billing/subscription.html", {
            "subscription": sub,
            "usage_pct":    usage_pct,
            "remaining":    remaining,
            "active_nav":   "subscription",
        })


class UsagePageView(APIView):
    """GET /billing/usage/?page=N

    Paginated ``UsageLedger`` table for the current organization.
    HTML by default; JSON when Accept asks for it.
    """
    permission_classes = [IsAuthenticated]

    PAGE_SIZE = 25

    def get(self, request):
        from apps.billing.models import UsageLedger
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response(
                {"detail": "User is not attached to an organization."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        qs = (
            UsageLedger.objects
            .filter(organization=organization)
            .order_by("-created_at")
            .values(
                "id", "action", "quantity", "reason",
                "document_id", "audit_run_id", "subscription_id",
                "created_at",
            )
        )
        try:
            page_num = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page_num = 1

        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj  = paginator.get_page(page_num)

        if not _wants_html(request):
            return Response({
                "results": list(page_obj.object_list),
                "page":     page_obj.number,
                "pages":    paginator.num_pages,
                "count":    paginator.count,
                "page_size": self.PAGE_SIZE,
            })

        return render(request, "billing/usage.html", {
            "page_obj":   page_obj,
            "active_nav": "usage",
        })
