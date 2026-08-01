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

from apps.billing.choices import PlanCode, SubscriptionStatus, USABLE_STATUSES
from apps.billing.models import OrganizationSubscription, Plan
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

# A same-plan re-purchase is only allowed as a RENEWAL within this many days of
# the current period ending (or once expired). Mirrors the subscription page's
# Renew-button visibility.
_RENEWAL_WINDOW_DAYS = 7


def _is_renewal_window(sub, now) -> bool:
    """True if ``sub`` is close enough to expiry (or expired) that buying the
    same plan again counts as a renewal rather than a duplicate purchase."""
    if sub is None:
        return False
    if sub.status == SubscriptionStatus.EXPIRED:
        return True
    return sub.ends_at is not None and sub.ends_at <= now + timedelta(days=_RENEWAL_WINDOW_DAYS)


def plan_action(plan, active_sub, *, used_trial, now):
    """The action a given plan offers relative to the org's current state.

    Plan rank is by ``price`` (Plan has no explicit rank field; free/trial
    plans are excluded from up/down comparison). Returns one of:
      subscribe | subscribe_trial | trial_unavailable | current |
      renew | upgrade | downgrade_unavailable
    Shared by the plans page (button rendering) AND SelectPlanView (backend
    enforcement) so UI and server can never disagree.
    """
    # Custom-quote plans are never purchasable through self-service: they have
    # no list price, so there is nothing to charge. Checked FIRST so the branch
    # below never compares a NULL price.
    if getattr(plan, "is_custom_quote", False):
        return "contact_sales"

    if getattr(plan, "is_trial", False):
        # A free trial cannot be started while any usable subscription exists,
        # nor if this org has already used its trial.
        if active_sub is not None or used_trial:
            return "trial_unavailable"
        return "subscribe_trial"
    if active_sub is None:
        return "subscribe"
    current = active_sub.plan
    if plan.pk == current.pk or plan.code == current.code:
        return "renew" if _is_renewal_window(active_sub, now) else "current"

    # ── Cross-family moves are not a self-service upgrade path ──────────
    # Accounting-firm plans address a different buyer, and their headline
    # capability — many client companies under one subscription — is NOT
    # implemented (see docs/adr/0006-plan-limit-dimensions.md). Ranking purely
    # by sort_order would put them "above" Professional and offer them as an
    # Upgrade button to an ordinary business customer, selling a capability
    # that does not exist. Route those to sales instead.
    from apps.billing.choices import ACCOUNTING_PLAN_CODES

    plan_is_accounting = plan.code in ACCOUNTING_PLAN_CODES
    current_is_accounting = current.code in ACCOUNTING_PLAN_CODES
    if plan_is_accounting != current_is_accounting:
        return "contact_sales"

    # Rank by sort_order, not price. Price became nullable when custom-quote
    # plans landed, and `None > Decimal` raises TypeError. sort_order is the
    # explicit commercial ladder and is always populated, so it ranks plans
    # without a comparison that can blow up.
    plan_rank = plan.sort_order
    current_rank = getattr(current, "sort_order", 0)
    if plan_rank > current_rank:
        return "upgrade"
    if plan_rank < current_rank:
        return "downgrade_unavailable"
    return "upgrade"


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
    if subscription.payment_transaction_id != txn.id:
        subscription.payment_transaction = txn
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
        from apps.billing.services.quota_service import QuotaService
        organization = getattr(request.user, "organization", None)
        plans = list_purchasable_plans()
        used_trial = self._has_used_free_trial(organization) if organization else False
        active_sub = (
            QuotaService().get_active_subscription(organization) if organization else None
        )
        now = timezone.now()
        # Annotate each plan with the action it offers for THIS org so the
        # template (and JSON) render the correct button instead of a blanket
        # "Subscribe".
        for plan in plans:
            plan.action = plan_action(plan, active_sub, used_trial=used_trial, now=now)
        current_code = active_sub.plan.code if active_sub else ""

        if not _wants_html(request):
            data = PlanSerializer(plans, many=True).data
            for item, plan in zip(data, plans):
                item["action"] = plan.action
            return Response({
                "plans": data,
                "has_used_free_trial": used_trial,
                "current_plan_code": current_code,
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
            "current_plan_code": current_code,
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

        # Backend enforcement of the plan action matrix — never trust the UI.
        from apps.billing.services.quota_service import QuotaService
        active_sub = QuotaService().get_active_subscription(organization)
        used_trial = OrganizationSubscription.objects.filter(
            organization=organization, plan__is_trial=True,
        ).exists()
        action = plan_action(plan, active_sub, used_trial=used_trial, now=timezone.now())
        if action == "current":
            return Response(
                {"detail": _("You are already subscribed to this plan."),
                 "code": "already_subscribed"},
                status=drf_status.HTTP_409_CONFLICT,
            )
        if action == "downgrade_unavailable":
            return Response(
                {"detail": _("Downgrade is not available during the active billing "
                             "period. Please contact support."),
                 "code": "downgrade_unavailable"},
                status=drf_status.HTTP_409_CONFLICT,
            )
        if action == "trial_unavailable":
            return Response(
                {"detail": _("A free trial is not available for this organization."),
                 "code": "trial_unavailable"},
                status=drf_status.HTTP_409_CONFLICT,
            )
        if action == "contact_sales":
            # Custom-quote plans carry no list price. Letting one through would
            # reach apps/payments/pricing.py with a NULL amount — at best a 500,
            # at worst an unlimited plan sold for nothing. Refused server-side,
            # not merely hidden in the UI.
            return Response(
                {"detail": _("This plan is priced by quotation. Please contact our "
                             "sales team to arrange it."),
                 "code": "contact_sales"},
                status=drf_status.HTTP_409_CONFLICT,
            )

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
        # payment_transaction is now a real FK (Stage-9 D-2); reuse the
        # linked instance directly when present.
        existing_txn = sub.payment_transaction if sub.payment_transaction_id else None
        if existing_txn is not None and existing_txn.organization_id == organization.id:
            if existing_txn.checkout_url and not existing_txn.is_terminal:
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
        active_sub = QuotaService().get_active_subscription(organization)
        # Truth source for "is the subscription usable right now" — used to
        # gate the success banner so ?payment=success can never fake a success.
        is_active = active_sub is not None
        sub = active_sub
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

        # Post-payment banner. We NEVER trust ?payment=success on its own —
        # "success" only renders when the subscription is genuinely active.
        payment_param = (request.GET.get("payment") or "").lower()
        if payment_param == "success" and is_active:
            payment_banner = "success"
        elif payment_param == "failed":
            payment_banner = "failed"
        elif payment_param in ("pending", "verifying") or (
            payment_param == "success" and not is_active
        ):
            # Paid-but-not-yet-active → honest "verifying", not a false success.
            payment_banner = "pending"
        else:
            payment_banner = ""

        # Safe, non-sensitive payment summary (no raw provider JSON, no card
        # data — only our stored status / reference / paid date).
        payment_info = self._safe_payment_info(sub, organization)

        # Button visibility:
        #  - Renew: only when expired or within the last 7 days before ends_at.
        #    A fresh active subscription does NOT show Renew (avoids confusion).
        #  - Upgrade: only when a higher-priced active plan exists.
        from django.utils import timezone as _tz
        from datetime import timedelta as _td
        now = _tz.now()
        show_renew = False
        if sub is not None:
            if sub.status == SubscriptionStatus.EXPIRED:
                show_renew = True
            elif (
                sub.status in USABLE_STATUSES
                and sub.ends_at is not None
                and sub.ends_at <= now + _td(days=7)
            ):
                show_renew = True
        # Reuse plan_action rather than re-deriving "is there something better".
        # The old rule was `price__gt=sub.plan.price`, a SECOND ranking rule that
        # now diverges from the one on the plans page: it would offer
        # accounting-firm plans as an upgrade to an ordinary business customer,
        # and `price__gt=None` is a broken query once the current plan is a
        # custom-quote one. plan_action already encodes family and custom-quote
        # rules, so asking it keeps both surfaces in agreement — which is the
        # property it was written for.
        show_upgrade = False
        if sub is not None and sub.plan_id is not None:
            used_trial = OrganizationSubscription.objects.filter(
                organization=organization, plan__is_trial=True,
            ).exists()
            show_upgrade = any(
                plan_action(candidate, sub, used_trial=used_trial, now=now) == "upgrade"
                for candidate in Plan.objects.filter(is_active=True)
            )

        return render(request, "billing/subscription.html", {
            "subscription":   sub,
            "usage_pct":      usage_pct,
            "remaining":      remaining,
            "active_nav":     "subscription",
            "payment_banner": payment_banner,
            "payment_info":   payment_info,
            "show_renew":     show_renew,
            "show_upgrade":   show_upgrade,
        })

    @staticmethod
    def _safe_payment_info(sub, organization):
        """Return only safe fields of the latest subscription payment for
        display: status, a reference (provider_reference/invoice id), and the
        paid timestamp. Never raw_request/raw_response/raw_webhook or card data."""
        from apps.payments.models import PaymentTransaction

        txn = None
        if sub is not None and getattr(sub, "payment_transaction_id", None):
            txn = sub.payment_transaction
        if txn is None:
            txn = (
                PaymentTransaction.objects
                .filter(organization=organization, purpose="subscription")
                .order_by("-created_at")
                .first()
            )
        if txn is None:
            return None
        return {
            "status":    txn.status,
            "reference": txn.provider_reference or txn.provider_payment_id or "",
            "paid_at":   txn.paid_at,
        }


class BulkUploadPageView(APIView):
    """GET /billing/bulk-upload/

    Renders the bulk-upload page. Stage 9's H-3 fix — surfaces the
    backend's 402 ``QUOTA_NOT_ENOUGH`` response with a friendly dialog
    that lets the user either upgrade or re-submit with
    ``accept_partial=true``. The POST itself goes to the existing
    /api/v1/documents/bulk-upload-jobs/ endpoint via fetch.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return render(request, "billing/bulk_upload.html", {
            "active_nav": "bulk_upload",
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


class PaymentHistoryView(APIView):
    """GET /billing/payments/?page=N

    The customer's own payment receipts. Org-scoped (a customer can only see
    their organization's payments). Renders ONLY safe fields — never
    raw_request/raw_response/raw_webhook, secrets, or card data.
    HTML by default; JSON when Accept asks for it.
    """
    permission_classes = [IsAuthenticated]
    PAGE_SIZE = 25

    def get(self, request):
        from apps.payments.models import PaymentTransaction
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response(
                {"detail": "User is not attached to an organization."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        qs = (
            PaymentTransaction.objects
            .filter(organization=organization)   # org isolation
            .order_by("-created_at")
        )
        try:
            page_num = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page_num = 1
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_obj  = paginator.get_page(page_num)

        # Resolve plan names for subscription payments in one batched query.
        sub_ids = [
            t.reference_id for t in page_obj.object_list
            if t.reference_type == "organization_subscription" and t.reference_id
        ]
        plan_by_sub = {}
        if sub_ids:
            for s in (OrganizationSubscription.objects
                      .filter(pk__in=sub_ids).select_related("plan")):
                plan_by_sub[str(s.pk)] = s.plan

        def _row(t):
            plan = plan_by_sub.get(str(t.reference_id))
            return {
                "created_at": t.created_at,
                "paid_at":    t.paid_at,
                "plan":       plan,                       # may be None
                "amount":     t.amount,
                "currency":   t.currency,
                "provider":   t.provider,
                "status":     t.status,
                # Safe reference only — provider_reference or invoice id.
                "reference":  t.provider_reference or t.provider_payment_id or "",
            }

        rows = [_row(t) for t in page_obj.object_list]

        if not _wants_html(request):
            return Response({
                "results": [
                    {**r, "plan": (r["plan"].code if r["plan"] else None)}
                    for r in rows
                ],
                "page":      page_obj.number,
                "pages":     paginator.num_pages,
                "count":     paginator.count,
                "page_size": self.PAGE_SIZE,
            })

        return render(request, "billing/payments.html", {
            "rows":       rows,
            "page_obj":   page_obj,
            "active_nav": "payments",
        })
