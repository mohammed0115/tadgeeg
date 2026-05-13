from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status as drf_status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.authentication.permissions import IsAdminUser
from apps.payments.gateways.base import GatewayError
from apps.payments.models import PaymentTransaction
from apps.payments.serializers import (
    CreatePaymentRequestSerializer,
    CreatePaymentResponseSerializer,
    PaymentTransactionSerializer,
)
from apps.payments.services.payment_service import (
    PaymentService,
    PaymentValidationError,
)
from apps.payments.services.webhook_service import process_webhook


logger = logging.getLogger("payments.views")


def _client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class CreatePaymentView(APIView):
    """POST /api/v1/payments/create/

    Creates a PaymentTransaction and calls the configured gateway.
    Returns the checkout_url the frontend should redirect to.
    """
    permission_classes  = [IsAuthenticated]
    throttle_classes    = [ScopedRateThrottle]
    throttle_scope      = "payments_create"

    def post(self, request):
        ser = CreatePaymentRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        organization = getattr(request.user, "organization", None)
        if organization is None:
            return Response(
                {"detail": "User is not attached to an organization."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            txn = PaymentService().create_transaction(
                organization=organization,
                user=request.user,
                amount=data["amount"],
                currency=data["currency"],
                purpose=data["purpose"],
                reference_type=data.get("reference_type", ""),
                reference_id=data.get("reference_id", ""),
                # NOTE: `provider` is NOT taken from the request — it
                # comes from settings.PAYMENT_PROVIDER inside the factory.
                success_url=data.get("success_url", ""),
                cancel_url=data.get("cancel_url", ""),
                failure_url=data.get("failure_url", ""),
                idempotency_key=data.get("idempotency_key"),
                metadata=data.get("metadata") or {},
                request_ip=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            )
        except PaymentValidationError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)
        except GatewayError as exc:
            logger.exception("Gateway error creating payment")
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)

        out = CreatePaymentResponseSerializer({
            "transaction_id": txn.id,
            "provider":       txn.provider,
            "status":         txn.status,
            "checkout_url":   txn.checkout_url,
            "amount":         txn.amount,
            "currency":       txn.currency,
        })
        return Response(out.data, status=drf_status.HTTP_201_CREATED)


class PaymentDetailView(APIView):
    """GET /api/v1/payments/<id>/ — scoped to the requester's organization."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        organization = getattr(request.user, "organization", None)
        txn = get_object_or_404(
            PaymentTransaction, pk=pk, organization=organization,
        )
        return Response(PaymentTransactionSerializer(txn).data)


class PaymentSyncView(APIView):
    """POST /api/v1/payments/<id>/sync/ — re-query the provider."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        organization = getattr(request.user, "organization", None)
        txn = get_object_or_404(
            PaymentTransaction, pk=pk, organization=organization,
        )
        try:
            PaymentService().sync_status(txn)
        except GatewayError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)
        except PaymentValidationError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)
        return Response(PaymentTransactionSerializer(txn).data)


class PaymentRefundView(APIView):
    """POST /api/v1/payments/<id>/refund/

    Admin-only (``can_manage_users`` capability). Body may optionally
    include ``{"amount": "..."}`` for a partial refund; missing/null
    means full refund.
    """
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, pk):
        organization = getattr(request.user, "organization", None)
        txn = get_object_or_404(
            PaymentTransaction, pk=pk, organization=organization,
        )

        # Segregation of Duties (F-1): the user who initiated a payment
        # cannot also refund it. Four-eyes principle on the financial
        # exit path matches what we enforce on invoice approval.
        from core.audit.sod import SoDViolation, enforce_sod
        try:
            enforce_sod(
                actor=request.user,
                object_=txn,
                stage="approve",
                maker_field="user",     # PaymentTransaction.user holds the maker
            )
        except SoDViolation as exc:
            return Response(
                {"detail": exc.user_message, "code": "sod_violation",
                 "conflicting_with": exc.conflicts_with},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        amount = request.data.get("amount") if isinstance(request.data, dict) else None
        try:
            PaymentService().refund(txn, amount=amount)
        except PaymentValidationError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_400_BAD_REQUEST)
        except GatewayError as exc:
            return Response({"detail": str(exc)}, status=drf_status.HTTP_502_BAD_GATEWAY)
        return Response(PaymentTransactionSerializer(txn).data)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def webhook_moyasar(request):
    code, http_status = process_webhook("moyasar", request)
    return Response({"result": code}, status=http_status)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def webhook_tap(request):
    code, http_status = process_webhook("tap", request)
    return Response({"result": code}, status=http_status)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def webhook_telr(request):
    code, http_status = process_webhook("telr", request)
    return Response({"result": code}, status=http_status)


class PaymentCallbackView(APIView):
    """GET /payments/callback/<provider>/?transaction_id=<uuid>

    A user-facing landing page after the gateway redirects them back.
    Critically: this NEVER marks a transaction paid by itself — it
    triggers a sync (which queries the provider) and renders a thin
    'verifying' page. The webhook remains the source of truth."""
    permission_classes = [AllowAny]  # callback is hit from external redirect
    authentication_classes = []

    def get(self, request, provider):
        transaction_id = request.GET.get("transaction_id") or request.GET.get("id")
        if not transaction_id:
            return Response({"detail": "Missing transaction_id"}, status=400)
        try:
            txn = PaymentTransaction.objects.get(pk=transaction_id, provider=provider)
        except PaymentTransaction.DoesNotExist:
            return Response({"detail": "Transaction not found"}, status=404)
        # Best-effort sync — failures are non-fatal here.
        try:
            PaymentService().sync_status(txn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Callback sync failed for %s: %s", txn.id, exc)
        return Response({
            "transaction_id": str(txn.id),
            "status":         txn.status,
            "provider":       txn.provider,
            "message":        "verifying" if not txn.is_terminal else txn.status,
        })
