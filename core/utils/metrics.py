"""
FinAI Prometheus Metrics — Phase 6

Exposes a /metrics/ endpoint (prometheus-client) that Prometheus scrapes.

Metric categories:
  HTTP layer     — request duration histogram, active requests gauge
  Document pipeline — processing counts, duration, stuck-document gauge
  AI layer       — OpenAI call duration, circuit-breaker state
  Celery         — task success/failure counters
  Audit sessions — session state distribution

Usage:
  Mount in urls.py:
    path("metrics/", include("core.utils.metrics_urls"))

  Or call get_metrics_view() directly:
    path("metrics/", get_metrics_view())

Environment variables:
  METRICS_TOKEN — if set, require "Bearer <token>" on requests to /metrics/
                  Leave empty to allow unauthenticated access (internal network only).
"""

import time
import logging
import os

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)
from django.http import HttpResponse

logger = logging.getLogger("finai")

# ── Registry ──────────────────────────────────────────────────────────────────
# Use the global default REGISTRY — avoids duplicate-registration errors when
# Django's autoreloader restarts the process in dev mode.

# ── HTTP Metrics ──────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "finai_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "finai_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

http_active_requests = Gauge(
    "finai_http_active_requests",
    "Number of currently in-flight HTTP requests",
)

# ── Document Pipeline Metrics ─────────────────────────────────────────────────

documents_processed_total = Counter(
    "finai_documents_processed_total",
    "Total documents processed by the pipeline",
    ["status"],   # completed | failed | needs_review
)

document_processing_seconds = Histogram(
    "finai_document_processing_seconds",
    "Full pipeline processing time per document",
    buckets=[1, 5, 15, 30, 60, 120, 300],
)

documents_stuck_gauge = Gauge(
    "finai_documents_stuck",
    "Documents stuck in processing/pending state for >1 hour",
)

documents_queued_gauge = Gauge(
    "finai_documents_queued",
    "Documents currently in pending state",
)

# ── AI / OpenAI Metrics ───────────────────────────────────────────────────────

openai_calls_total = Counter(
    "finai_openai_calls_total",
    "Total OpenAI API calls",
    ["operation", "result"],    # result: success | error | circuit_open
)

openai_call_duration_seconds = Histogram(
    "finai_openai_call_duration_seconds",
    "OpenAI API call duration",
    ["operation"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

openai_circuit_breaker_state = Gauge(
    "finai_openai_circuit_breaker_open",
    "1 if the OpenAI circuit breaker is OPEN (requests rejected), 0 otherwise",
)

# ── Celery Task Metrics ────────────────────────────────────────────────────────

celery_tasks_total = Counter(
    "finai_celery_tasks_total",
    "Total Celery task executions",
    ["task_name", "result"],    # result: success | failure | retry
)

celery_task_duration_seconds = Histogram(
    "finai_celery_task_duration_seconds",
    "Celery task duration",
    ["task_name"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)

# ── Audit Session Metrics ──────────────────────────────────────────────────────

audit_sessions_total = Counter(
    "finai_audit_sessions_total",
    "Total audit sessions created",
)

audit_session_state_gauge = Gauge(
    "finai_audit_sessions_by_state",
    "Number of audit sessions in each state",
    ["state"],
)


# ── Prometheus HTTP endpoint ──────────────────────────────────────────────────

def metrics_view(request):
    """
    Expose Prometheus metrics.  Optionally gated by a Bearer token.

    Scrape target config (prometheus.yml):
      - job_name: finai
        static_configs:
          - targets: [finai-web:8000]
        metrics_path: /metrics/
        bearer_token: <value-of-METRICS_TOKEN>
    """
    token = os.environ.get("METRICS_TOKEN", "")
    if token:
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth != f"Bearer {token}":
            return HttpResponse("Unauthorized", status=401)

    # Refresh gauges that reflect current DB state
    _refresh_pipeline_gauges()
    _refresh_session_gauges()
    _refresh_circuit_breaker_gauge()

    data = generate_latest(REGISTRY)
    return HttpResponse(data, content_type=CONTENT_TYPE_LATEST)


# ── Gauge refreshers (called on each scrape) ──────────────────────────────────

def _refresh_pipeline_gauges():
    """Refresh stuck/queued document gauges from DB."""
    try:
        import datetime
        from django.utils import timezone
        from apps.documents.models import Document

        now = timezone.now()
        one_hour_ago = now - datetime.timedelta(hours=1)

        stuck = Document.objects.filter(
            processing_status__in=["processing", "pending"],
            created_at__lt=one_hour_ago,
        ).count()
        queued = Document.objects.filter(processing_status="pending").count()

        documents_stuck_gauge.set(stuck)
        documents_queued_gauge.set(queued)
    except Exception as exc:
        logger.debug("metrics: pipeline gauge refresh failed: %s", exc)


def _refresh_session_gauges():
    """Refresh audit session state distribution from DB."""
    try:
        from django.db.models import Count
        from apps.audit.models import AuditSession

        rows = (
            AuditSession.objects
            .values("state")
            .annotate(n=Count("id"))
        )
        # Reset all known states to 0 first
        for state in AuditSession.State.values:
            audit_session_state_gauge.labels(state=state).set(0)
        for row in rows:
            audit_session_state_gauge.labels(state=row["state"]).set(row["n"])
    except Exception as exc:
        logger.debug("metrics: session gauge refresh failed: %s", exc)


def _refresh_circuit_breaker_gauge():
    """Reflect current circuit breaker state in the gauge."""
    try:
        from core.services.ai.circuit_breaker import _openai_cb
        openai_circuit_breaker_state.set(1 if _openai_cb.is_open else 0)
    except Exception:
        pass  # circuit breaker may not be initialised yet
