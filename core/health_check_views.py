"""Health check and monitoring views for OCR pipeline"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from core.services.monitoring import get_health_check_report


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
