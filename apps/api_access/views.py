from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api_access.service import APIAccessError, issue_key, revoke_key
from apps.api_access.selectors import get_api_key_for_organization, list_safe_api_keys


class APIKeyIssueSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)


class APIKeyListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.organization_id:
            return Response({"detail": "Organization membership is required."}, status=403)
        rows = list_safe_api_keys(request.user.organization)
        return Response({"results": list(rows)})

    def post(self, request):
        if not request.user.organization_id:
            return Response({"detail": "Organization membership is required."}, status=403)
        serializer = APIKeyIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            raw, key = issue_key(organization=request.user.organization, name=serializer.validated_data["name"], actor=request.user)
        except APIAccessError as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response({"id": str(key.id), "name": key.name, "key": raw, "scopes": key.scopes, "monthly_limit": key.monthly_limit}, status=status.HTTP_201_CREATED)


class APIKeyRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        key = get_api_key_for_organization(request.user.organization, pk)
        if not key:
            return Response({"detail": "API key not found."}, status=404)
        try:
            revoke_key(key=key, actor=request.user)
        except APIAccessError as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(status=status.HTTP_204_NO_CONTENT)
