from django.urls import path

from .views import APIKeyListCreateView, APIKeyRevokeView

urlpatterns = [
    path("keys/", APIKeyListCreateView.as_view(), name="api-key-list-create"),
    path("keys/<uuid:pk>/", APIKeyRevokeView.as_view(), name="api-key-revoke"),
]
