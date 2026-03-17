"""Health check URLs and views — Phase 11"""

import time
import logging
from django.urls import path
from django.http import JsonResponse
from django.db import connection

logger = logging.getLogger("finai")


def health_check(request):
    """Basic health check — fast, always returns 200 unless DB is down."""
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


def full_health_check(request):
    """
    Full health check. Query ?heavy=true to include OCR and OpenAI checks.
    """
    t_start = time.monotonic()
    heavy = request.GET.get("heavy", "false").lower() == "true"
    components = {}
    overall_ok = True

    components["database"] = _check_database()
    if components["database"]["status"] != "ok":
        overall_ok = False

    components["redis"] = _check_redis()
    if components["redis"]["status"] not in ("ok", "skip"):
        overall_ok = False

    components["celery"]          = _check_celery()
    components["circuit_breaker"] = _check_circuit_breaker()

    if heavy:
        components["tesseract"] = _check_tesseract()
        components["openai"] = _check_openai()

    pipeline = _check_pipeline()

    overall = "healthy" if overall_ok else "degraded"
    if components["database"]["status"] != "ok":
        overall = "unhealthy"

    return JsonResponse({
        "status": overall,
        "components": components,
        "pipeline": pipeline,
        "timestamp": int(time.time()),
        "duration_ms": int((time.monotonic() - t_start) * 1000),
    }, status=200 if overall != "unhealthy" else 503)


def _check_database():
    t = time.monotonic()
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {"status": "ok", "latency_ms": int((time.monotonic() - t) * 1000)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _check_redis():
    t = time.monotonic()
    try:
        from django.conf import settings
        import redis as redis_lib
        url = getattr(settings, "CELERY_BROKER_URL", None) or "redis://localhost:6379/0"
        r = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        return {"status": "ok", "latency_ms": int((time.monotonic() - t) * 1000)}
    except ImportError:
        return {"status": "skip", "reason": "redis package not installed"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _check_celery():
    try:
        from finai_backend.celery import app as celery_app
        inspector = celery_app.control.inspect(timeout=2)
        active = inspector.active()
        if active is None:
            return {"status": "no_workers", "workers": 0}
        return {"status": "ok", "workers": len(active)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _check_tesseract():
    try:
        import subprocess
        r = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.split("\n")[0] if r.returncode == 0 else "unknown"
        return {"status": "ok", "version": version}
    except FileNotFoundError:
        return {"status": "error", "error": "tesseract not found"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _check_openai():
    try:
        from django.conf import settings
        key = getattr(settings, "OPENAI_API_KEY", "")
        if not key:
            return {"status": "unconfigured"}
        import openai
        client = openai.OpenAI(api_key=key)
        client.models.list()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:100]}


def _check_circuit_breaker():
    try:
        from core.services.ai.circuit_breaker import _openai_cb
        state = "open" if _openai_cb.is_open else ("half_open" if getattr(_openai_cb, "is_half_open", False) else "closed")
        return {"status": "ok", "state": state}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _check_pipeline():
    try:
        import datetime
        from apps.documents.models import Document
        now = datetime.datetime.utcnow()
        one_hour_ago = now - datetime.timedelta(hours=1)
        one_day_ago = now - datetime.timedelta(hours=24)
        stuck = Document.objects.filter(
            processing_status__in=["processing", "pending"],
            created_at__lt=one_hour_ago,
        ).count()
        total_24h = Document.objects.filter(created_at__gte=one_day_ago).count()
        ok_24h = Document.objects.filter(created_at__gte=one_day_ago, processing_status="completed").count()
        rate = round(ok_24h / total_24h, 3) if total_24h else 1.0
        return {
            "stuck_documents": stuck,
            "recent_total_24h": total_24h,
            "recent_success_24h": ok_24h,
            "success_rate_24h": rate,
        }
    except Exception as exc:
        return {"error": str(exc)}


urlpatterns = [
    path("", health_check, name="health"),
    path("ready/", readiness_check, name="ready"),
    path("full/", full_health_check, name="health-full"),
]
