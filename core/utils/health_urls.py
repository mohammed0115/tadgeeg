"""Health check URLs and views"""

from django.urls import path
from django.http import JsonResponse
from django.db import connection
import time

from core.services.monitoring import get_health_check_report


def health_check(request):
    """Basic health check."""
    report = get_health_check_report(use_cache=True, include_heavy_checks=False)
    return JsonResponse(
        {
            "status": report.get("status", "degraded"),
            "database": report.get("components", {}).get("database", {}).get("status", "unknown"),
            "redis": report.get("components", {}).get("redis", {}).get("status", "unknown"),
            "tesseract": report.get("components", {}).get("tesseract", {}).get("status", "unknown"),
            "timestamp": int(time.time()),
        },
        status=200 if report.get("status") != "unhealthy" else 503,
    )


def readiness_check(request):
    """Readiness check for K8s."""
    try:
        connection.ensure_connection()
        return JsonResponse({"status": "ready"})
    except Exception:
        return JsonResponse({"status": "not_ready"}, status=503)


def full_health_check(request):
    include_heavy = request.GET.get("heavy", "true").lower() in {"1", "true", "yes"}
    report = get_health_check_report(use_cache=False, include_heavy_checks=include_heavy)
    return JsonResponse(report, status=200 if report.get("status") != "unhealthy" else 503)


urlpatterns = [
    path("", health_check, name="health"),
    path("ready/", readiness_check, name="ready"),
    path("full/", full_health_check, name="health-full"),
]
