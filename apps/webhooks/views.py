"""Webhook subscription management API."""
from __future__ import annotations

import secrets

from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WebhookEndpoint, WebhookDelivery


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = [
            "id", "url", "events", "is_active", "description",
            "failure_count", "last_success_at", "last_failure_at",
            "last_response_status", "created_at",
        ]
        read_only_fields = [
            "id", "failure_count", "last_success_at", "last_failure_at",
            "last_response_status", "created_at",
        ]


class WebhookEndpointListView(generics.ListCreateAPIView):
    """GET → list this org's webhook subscriptions.
    POST → create a new subscription (server generates the HMAC secret)."""
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WebhookEndpoint.objects.filter(organization=self.request.user.organization)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        secret = secrets.token_urlsafe(32)
        endpoint = WebhookEndpoint.objects.create(
            organization=request.user.organization,
            url=serializer.validated_data["url"],
            events=serializer.validated_data.get("events", []),
            is_active=serializer.validated_data.get("is_active", True),
            description=serializer.validated_data.get("description", ""),
            secret=secret,
            created_by=request.user,
        )
        # Return the secret ONCE (and only once) so the customer can save it.
        out = WebhookEndpointSerializer(endpoint).data
        out["secret"] = secret
        return Response(out, status=status.HTTP_201_CREATED)


class WebhookEndpointDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WebhookEndpoint.objects.filter(organization=self.request.user.organization)


class WebhookDeliveryListView(generics.ListAPIView):
    """Recent dispatch attempts for one endpoint — useful for debugging."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        ep = WebhookEndpoint.objects.filter(
            organization=request.user.organization, id=pk,
        ).first()
        if not ep:
            return Response({"error": "endpoint not found"}, status=404)
        rows = ep.deliveries.all()[:50].values(
            "id", "event_type", "status", "attempt_count",
            "last_response_status", "created_at", "completed_at",
        )
        return Response({"deliveries": list(rows)})


class WebhookTestView(APIView):
    """Send a synthetic test event so the customer can verify their endpoint."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        ep = WebhookEndpoint.objects.filter(
            organization=request.user.organization, id=pk,
        ).first()
        if not ep:
            return Response({"error": "endpoint not found"}, status=404)
        from .services import emit
        emit("webhook.test", request.user.organization, {
            "message": "This is a test event from Tadgeeg.",
            "endpoint_id": str(ep.id),
        })
        return Response({"queued": True})
