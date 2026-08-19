"""
OCR Pipeline Health Check & Monitoring
======================================
Monitor system health status and component availability.
"""

import logging
import time
from typing import Optional
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.core.cache import cache

logger = logging.getLogger("finai")


class HealthStatus:
    """Health check status codes"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Individual component health"""

    def __init__(self, name: str, status: str, message: str = "", response_time_ms: float = 0):
        self.name = name
        self.status = status
        self.message = message
        self.response_time_ms = response_time_ms
        self.timestamp = timezone.now()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "response_time_ms": round(self.response_time_ms, 2),
            "timestamp": self.timestamp.isoformat(),
        }


class PipelineHealthCheck:
    """Health check for OCR pipeline"""

    def __init__(self):
        self.components = {}
        self.overall_status = HealthStatus.HEALTHY
        self.last_check = None

    def check_redis(self) -> ComponentHealth:
        """Check Redis/Celery broker connection"""
        start = time.time()
        try:
            import redis

            redis_url = settings.CELERY_BROKER_URL or "redis://localhost:6379/0"
            conn = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
            conn.ping()
            elapsed = (time.time() - start) * 1000

            return ComponentHealth("redis", HealthStatus.HEALTHY, "Connected", elapsed)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            status = HealthStatus.UNHEALTHY if getattr(settings, "HEALTH_REDIS_REQUIRED", False) else HealthStatus.DEGRADED
            message = f"Unavailable: {str(e)}"
            if status == HealthStatus.DEGRADED:
                message += " (running in degraded mode without Redis)"
            return ComponentHealth("redis", status, message, elapsed)

    def check_tesseract(self) -> ComponentHealth:
        """Check Tesseract OCR installation"""
        start = time.time()
        try:
            import pytesseract
            from core.services.ocr_service import _resolve_tesseract_cmd

            cmd = _resolve_tesseract_cmd()
            # Try a simple version check
            pytesseract.pytesseract.tesseract_cmd = cmd
            version = pytesseract.get_tesseract_version()
            elapsed = (time.time() - start) * 1000

            return ComponentHealth(
                "tesseract",
                HealthStatus.HEALTHY,
                f"Tesseract {version} ready",
                elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            # CI intentionally runs without the OCR binary in some jobs.  It
            # must remain observable in the report, but a test environment is
            # not an unavailable production service.  Production still returns
            # UNHEALTHY/503 for an OCR dependency failure.
            health = (
                HealthStatus.DEGRADED
                if getattr(settings, "TESTING", False)
                else HealthStatus.UNHEALTHY
            )
            return ComponentHealth("tesseract", health, f"Failed: {str(e)}", elapsed)

    def check_openai_api(self) -> ComponentHealth:
        """Check OpenAI API connection"""
        start = time.time()
        try:
            if not settings.OPENAI_API_KEY:
                elapsed = (time.time() - start) * 1000
                return ComponentHealth(
                    "openai_api",
                    HealthStatus.DEGRADED,
                    "API key not configured",
                    elapsed,
                )

            # Do not make an unowned provider request from a health check.
            # Tenant-scoped gateway calls record their own success/failure in
            # AIUsageRecord; this component reports configuration only.
            elapsed = (time.time() - start) * 1000
            return ComponentHealth(
                "openai_api",
                HealthStatus.DEGRADED,
                "Provider configured; tenant-scoped gateway evidence required",
                elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            error_msg = str(e)
            # Check for specific error types
            if "rate_limit" in error_msg.lower():
                status = HealthStatus.DEGRADED
            elif "auth" in error_msg.lower():
                status = HealthStatus.UNHEALTHY
            else:
                status = HealthStatus.DEGRADED
            return ComponentHealth("openai_api", status, f"Failed: {error_msg}", elapsed)

    def check_celery_workers(self) -> ComponentHealth:
        """Check if Celery workers are active"""
        start = time.time()
        try:
            from celery.app.control import Inspect
            from finai_backend.celery import app

            insp = Inspect(app=app)
            active_workers = insp.active()
            elapsed = (time.time() - start) * 1000

            if not active_workers:
                return ComponentHealth(
                    "celery_workers",
                    HealthStatus.DEGRADED,
                    "No workers currently active",
                    elapsed,
                )

            worker_count = len(active_workers)
            return ComponentHealth(
                "celery_workers",
                HealthStatus.HEALTHY,
                f"{worker_count} worker(s) active",
                elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return ComponentHealth("celery_workers", HealthStatus.DEGRADED, f"Failed: {str(e)}", elapsed)

    def check_database(self) -> ComponentHealth:
        """Check database connectivity"""
        start = time.time()
        try:
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            elapsed = (time.time() - start) * 1000

            return ComponentHealth("database", HealthStatus.HEALTHY, "Connected", elapsed)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return ComponentHealth("database", HealthStatus.UNHEALTHY, f"Failed: {str(e)}", elapsed)

    def check_stuck_documents(self) -> ComponentHealth:
        """Check for stuck documents in processing"""
        try:
            from apps.documents.models import Document
            from django.utils import timezone

            stuck_docs = Document.objects.filter(
                processing_status=Document.ProcessingStatus.PROCESSING,
                updated_at__lt=timezone.now() - timedelta(minutes=30),
            ).count()

            if stuck_docs > 0:
                message = f"{stuck_docs} documents stuck in processing"
                status = HealthStatus.DEGRADED if stuck_docs < 10 else HealthStatus.UNHEALTHY
            else:
                message = "No stuck documents"
                status = HealthStatus.HEALTHY

            return ComponentHealth("stuck_documents", status, message, 0)
        except Exception as e:
            return ComponentHealth("stuck_documents", HealthStatus.DEGRADED, f"Failed: {str(e)}", 0)

    def check_document_processing_rate(self) -> ComponentHealth:
        """Check recent document processing rate"""
        try:
            from apps.documents.models import Document

            one_hour_ago = timezone.now() - timedelta(hours=1)
            recent_docs = Document.objects.filter(created_at__gte=one_hour_ago)

            completed = recent_docs.filter(processing_status=Document.ProcessingStatus.COMPLETED).count()
            failed = recent_docs.filter(processing_status=Document.ProcessingStatus.FAILED).count()
            total = recent_docs.count()

            if total == 0:
                message = "No documents processed in last hour"
                status = HealthStatus.HEALTHY
            else:
                success_rate = (completed / total) * 100
                if success_rate >= 95:
                    status = HealthStatus.HEALTHY
                    message = f"{success_rate:.1f}% success rate (1h)"
                elif success_rate >= 80:
                    status = HealthStatus.DEGRADED
                    message = f"{success_rate:.1f}% success rate (1h)"
                else:
                    status = HealthStatus.UNHEALTHY
                    message = f"{success_rate:.1f}% success rate (1h) - {failed} failures"

            return ComponentHealth("processing_rate", status, message, 0)
        except Exception as e:
            return ComponentHealth("processing_rate", HealthStatus.DEGRADED, f"Failed: {str(e)}", 0)

    def check_stuck_audit_sessions(self) -> ComponentHealth:
        """Check for audit sessions stuck in workflow states."""
        try:
            from apps.audit.models import AuditSession

            stuck_sessions = AuditSession.objects.filter(
                status__in=[
                    AuditSession.Status.EXTRACTING,
                    AuditSession.Status.NORMALIZING,
                    AuditSession.Status.VALIDATING,
                ],
                updated_at__lt=timezone.now() - timedelta(minutes=30),
            ).count()

            if stuck_sessions > 0:
                status = HealthStatus.DEGRADED if stuck_sessions < 5 else HealthStatus.UNHEALTHY
                message = f"{stuck_sessions} audit sessions stuck in workflow"
            else:
                status = HealthStatus.HEALTHY
                message = "No stuck audit sessions"
            return ComponentHealth("stuck_audit_sessions", status, message, 0)
        except Exception as e:
            return ComponentHealth("stuck_audit_sessions", HealthStatus.DEGRADED, f"Failed: {str(e)}", 0)

    def run_full_check(self, include_heavy_checks: bool = True) -> dict:
        """
        Run full health check across all components

        Args:
            include_heavy_checks: Include expensive checks (API calls, DB queries)

        Returns:
            Health report dict
        """
        self.components = {}
        start_time = time.time()

        # Light checks (always run)
        self.components["redis"] = self.check_redis()
        self.components["database"] = self.check_database()
        self.components["tesseract"] = self.check_tesseract()
        self.components["stuck_documents"] = self.check_stuck_documents()
        self.components["stuck_audit_sessions"] = self.check_stuck_audit_sessions()

        # Heavy checks (optional)
        if include_heavy_checks:
            self.components["openai_api"] = self.check_openai_api()
            self.components["celery_workers"] = self.check_celery_workers()
            self.components["processing_rate"] = self.check_document_processing_rate()

        # Determine overall status
        statuses = [c.status for c in self.components.values()]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            self.overall_status = HealthStatus.HEALTHY
        elif HealthStatus.UNHEALTHY in statuses:
            self.overall_status = HealthStatus.UNHEALTHY
        else:
            self.overall_status = HealthStatus.DEGRADED

        elapsed = (time.time() - start_time) * 1000
        self.last_check = timezone.now()

        return {
            "status": self.overall_status,
            "timestamp": self.last_check.isoformat(),
            "check_duration_ms": round(elapsed, 2),
            "components": {name: comp.to_dict() for name, comp in self.components.items()},
        }

    def get_cached_health(self, max_age_seconds: int = 30) -> Optional[dict]:
        """Get cached health status if available"""
        cached = cache.get("ocr_pipeline_health")
        if cached:
            cached_time = cached.get("timestamp")
            if cached_time:
                try:
                    from django.utils.dateparse import parse_datetime

                    dt = parse_datetime(cached_time)
                    age = (timezone.now() - dt).total_seconds()
                    if age < max_age_seconds:
                        return cached
                except Exception:
                    pass
        return None

    def get_health_report(self, use_cache: bool = True, include_heavy_checks: bool = True) -> dict:
        """Get health report with optional caching"""
        if use_cache:
            cached = self.get_cached_health()
            if cached:
                cached["cached"] = True
                return cached

        report = self.run_full_check(include_heavy_checks=include_heavy_checks)
        report["cached"] = False

        # Cache for 30 seconds
        cache.set("ocr_pipeline_health", report, 30)

        return report


def get_health_check_report(**kwargs) -> dict:
    """Convenience function for health check"""
    checker = PipelineHealthCheck()
    return checker.get_health_report(**kwargs)
