"""Health check URLs and views"""

from django.urls import path
from django.http import JsonResponse
from django.db import connection
import time


def health_check(request):
    """Basic health check."""
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    healthy = db_ok
    return JsonResponse({
        "status": "healthy" if healthy else "degraded",
        "database": "ok" if db_ok else "error",
        "timestamp": int(time.time()),
    }, status=200 if healthy else 503)


def readiness_check(request):
    """Readiness check for K8s."""
    return JsonResponse({"status": "ready"})


urlpatterns = [
    path("", health_check, name="health"),
    path("ready/", readiness_check, name="ready"),
]
