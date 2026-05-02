from django.urls import path
from .views import (
    WebhookEndpointListView, WebhookEndpointDetailView,
    WebhookDeliveryListView, WebhookTestView,
)

urlpatterns = [
    path("",                   WebhookEndpointListView.as_view(),  name="webhook-list"),
    path("<uuid:pk>/",         WebhookEndpointDetailView.as_view(), name="webhook-detail"),
    path("<uuid:pk>/deliveries/", WebhookDeliveryListView.as_view(), name="webhook-deliveries"),
    path("<uuid:pk>/test/",    WebhookTestView.as_view(),           name="webhook-test"),
]
