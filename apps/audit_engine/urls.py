from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.audit_engine.views import AuditJobViewSet, AuditResultViewSet

router = DefaultRouter()
router.register("jobs", AuditJobViewSet, basename="audit-job")
router.register("results", AuditResultViewSet, basename="audit-result")

urlpatterns = [
    path("", include(router.urls)),
]
