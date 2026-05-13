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

from django.shortcuts import redirect, render
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.choices import PlanCode
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


class PlansView(APIView):
    """GET /billing/plans/

    Returns the four canonical plans. Content negotiation:
    - ``Accept: application/json`` (or any /api/ caller) → JSON.
    - Browser → renders the ``billing/plans.html`` template
      (Stage 7 will style it; for now we ship a minimal template).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = list_purchasable_plans()
        if request.accepted_renderer.format == "json" or "application/json" in request.headers.get("Accept", ""):
            return Response({
                "plans": PlanSerializer(plans, many=True).data,
                "has_used_free_trial": self._has_used_free_trial(request.user.organization),
            })
        return render(request, "billing/plans.html", {
            "plans": plans,
            "has_used_free_trial": self._has_used_free_trial(request.user.organization),
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

        # Paid plan path.
        try:
            sub = svc.create_pending_paid_subscription(organization, plan)
        except SubscriptionError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)

        # Stage 4 hooks this in. For now, surface a stable URL the
        # frontend can use to kick off the payment flow once it lands.
        return Response({
            "subscription": SubscriptionSerializer(sub).data,
            "next": f"/billing/checkout/{sub.id}/",
            "message": "Payment integration pending — pay via /api/v1/payments/create/ "
                       "with purpose=subscription, reference_id=<subscription.id>.",
        }, status=drf_status.HTTP_201_CREATED)


class CurrentSubscriptionView(APIView):
    """GET /billing/subscription/ — what the current org is paying for now."""
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
            return Response({"subscription": None}, status=drf_status.HTTP_200_OK)
        return Response({"subscription": SubscriptionSerializer(sub).data})
