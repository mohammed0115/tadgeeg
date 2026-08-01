"""Public partner API — the application submission endpoint.

Mounted at /api/v1/partners/. The submission endpoint is the product's only
unauthenticated file-accepting write path; its throttle scope and validation
live in apps/partners/views.py.
"""

from django.urls import path

from . import views

app_name = "partners"

urlpatterns = [
    path(
        "applications/",
        views.PartnerApplicationSubmitView.as_view(),
        name="application-submit",
    ),
]
