"""Health check and monitoring views for OCR pipeline"""

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from core.services.monitoring import PipelineHealthCheck, get_health_check_report


class HealthCheckView(APIView):
    """Health check endpoint for OCR pipeline and dependencies"""

    permission_classes = [AllowAny]

    def get(self, request):
        """
        GET /api/v1/health/

        Returns health status of all pipeline components.
        Query params:
            - heavy=true: Include expensive checks (API calls, worker status)
            - cache=true: Use cached result if available (default: true)
        """
        include_heavy = request.query_params.get("heavy", "false").lower() in ("true", "1", "yes")
        use_cache = request.query_params.get("cache", "true").lower() in ("true", "1", "yes")

        report = get_health_check_report(use_cache=use_cache, include_heavy_checks=include_heavy)

        # Determine HTTP status code
        if report["status"] == "healthy":
            http_status = status.HTTP_200_OK
        elif report["status"] == "degraded":
            http_status = status.HTTP_200_OK  # Still 200, but check components
        else:  # unhealthy
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

        return Response(report, status=http_status)


class PipelineStatusView(APIView):
    """Quick status check - lightweight version of health check"""

    permission_classes = [AllowAny]

    def get(self, request):
        """
        GET /api/v1/status/

        Quick lightweight status check (no heavy API checks)
        """
        report = get_health_check_report(use_cache=True, include_heavy_checks=False)

        return Response(
            {
                "status": report["status"],
                "timestamp": report["timestamp"],
                "critical_components": {
                    "redis": report["components"].get("redis", {}).get("status"),
                    "database": report["components"].get("database", {}).get("status"),
                    "tesseract": report["components"].get("tesseract", {}).get("status"),
                },
            }
        )


class FullHealthCheckView(APIView):
    """Dedicated full health endpoint for external monitors.

    SRS §5.3 requires 99.9% availability — monitoring tools (UptimeRobot,
    Pingdom, load balancers) must be able to poll this without credentials.
    Heavy checks (OpenAI, Celery workers) are included for ops dashboards.
    """

    permission_classes = [AllowAny]  # SRS §5.3: public for uptime monitoring

    def get(self, request):
        report = get_health_check_report(use_cache=False, include_heavy_checks=True)
        http_status = status.HTTP_200_OK if report["status"] != "unhealthy" else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(report, status=http_status)


class OpenAIHealthView(APIView):
    """Focused OpenAI health endpoint so ops can distinguish AI degradation."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        checker = PipelineHealthCheck()
        component = checker.check_openai_api()
        payload = {
            "status": component.status,
            "configured": bool(getattr(settings, "OPENAI_API_KEY", "")),
            "component": component.to_dict(),
        }
        http_status = status.HTTP_200_OK if component.status != "unhealthy" else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=http_status)


class ExtendedHealthView(APIView):
    """Operational health: storage, migrations, cache, OpenAI key.

    Complements the OCR-pipeline-focused HealthCheckView. Used by ops
    dashboards and pre-deploy smoke tests.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from core.services.extra_health_checks import comprehensive_report
        report = comprehensive_report()
        bad = [k for k, v in report.items() if v.get("status") == "unhealthy"]
        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE if bad else status.HTTP_200_OK
        )
        return Response(
            {"status": "unhealthy" if bad else "healthy", "checks": report, "failed": bad},
            status=http_status,
        )
