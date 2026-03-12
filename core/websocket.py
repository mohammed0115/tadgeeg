"""
WebSocket Real-time Alerts — Django Channels
============================================
Sends real-time notifications to connected browsers when:
  - Invoice is flagged
  - Audit case is created/escalated
  - Batch processing completes
  - Anomaly detected

Setup:
  pip install channels channels-redis

settings.py:
  INSTALLED_APPS += ["channels"]
  ASGI_APPLICATION = "finai_backend.asgi.application"
  CHANNEL_LAYERS = {
      "default": {
          "BACKEND": "channels_redis.core.RedisChannelLayer",
          "CONFIG": {"hosts": [("redis", 6379)]},
      }
  }
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = logging.getLogger("finai")


# ── Consumer ───────────────────────────────────────────────────────────────────

class AlertConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time alerts.
    Connected clients join a group keyed by their organization ID.
    """

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return

        org = getattr(user, "organization", None)
        if not org:
            await self.close()
            return

        self.org_id   = str(org.id)
        self.user_id  = str(user.id)
        self.group_name = f"alerts_{self.org_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            "type":    "connected",
            "message": "متصل بنظام التنبيهات الفورية",
            "org_id":  self.org_id,
        }))

        logger.info(f"WS connected: user={self.user_id} org={self.org_id}")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"WS disconnected: user={getattr(self,'user_id','?')} code={close_code}")

    async def receive(self, text_data=None, bytes_data=None):
        """Handle ping from client."""
        try:
            data = json.loads(text_data or "{}")
            if data.get("type") == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
        except Exception:
            pass

    # ── Group message handlers ────────────────────────────────────────────────

    async def alert_invoice_flagged(self, event):
        await self.send(text_data=json.dumps({
            "type":       "invoice_flagged",
            "title":      "فاتورة مُعلَّقة",
            "message":    event.get("message", ""),
            "risk_level": event.get("risk_level", ""),
            "invoice_id": event.get("invoice_id", ""),
            "url":        event.get("url", ""),
            "timestamp":  event.get("timestamp", ""),
        }))

    async def alert_case_created(self, event):
        await self.send(text_data=json.dumps({
            "type":       "case_created",
            "title":      "قضية تدقيق جديدة",
            "message":    event.get("message", ""),
            "priority":   event.get("priority", ""),
            "case_id":    event.get("case_id", ""),
            "url":        event.get("url", ""),
            "timestamp":  event.get("timestamp", ""),
        }))

    async def alert_batch_complete(self, event):
        await self.send(text_data=json.dumps({
            "type":      "batch_complete",
            "title":     "اكتمل رفع الدفعة",
            "message":   event.get("message", ""),
            "batch_id":  event.get("batch_id", ""),
            "processed": event.get("processed", 0),
            "failed":    event.get("failed", 0),
            "url":       event.get("url", ""),
            "timestamp": event.get("timestamp", ""),
        }))

    async def alert_anomaly_detected(self, event):
        await self.send(text_data=json.dumps({
            "type":      "anomaly_detected",
            "title":     "شذوذ مكتشف",
            "message":   event.get("message", ""),
            "severity":  event.get("severity", ""),
            "url":       event.get("url", ""),
            "timestamp": event.get("timestamp", ""),
        }))

    async def alert_generic(self, event):
        await self.send(text_data=json.dumps(event.get("payload", {})))


# ── Broadcaster functions (call from anywhere) ─────────────────────────────────

def _broadcast(org_id: str, event_type: str, data: dict):
    """Send a message to all WebSocket clients of an organization."""
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"alerts_{org_id}",
            {"type": event_type, **data}
        )
    except Exception as e:
        logger.warning(f"WebSocket broadcast failed: {e}")


def broadcast_invoice_flagged(invoice):
    from django.utils import timezone
    _broadcast(str(invoice.organization_id), "alert.invoice_flagged", {
        "message":    f"فاتورة مُعلَّقة: {invoice.vendor_name} — {invoice.total_amount} {invoice.currency}",
        "risk_level": invoice.risk_level,
        "invoice_id": str(invoice.id),
        "url":        f"/invoices/{invoice.id}/",
        "timestamp":  timezone.now().isoformat(),
    })


def broadcast_case_created(case):
    from django.utils import timezone
    _broadcast(str(case.organization_id), "alert.case_created", {
        "message":   f"قضية جديدة: {case.case_number} — {case.title[:60]}",
        "priority":  case.priority,
        "case_id":   str(case.id),
        "url":       f"/audit/{case.id}/",
        "timestamp": timezone.now().isoformat(),
    })


def broadcast_batch_complete(batch):
    from django.utils import timezone
    _broadcast(str(batch.organization_id), "alert.batch_complete", {
        "message":   f"اكتملت الدفعة: {batch.batch_name} — {batch.processed_files}/{batch.total_files} ملف",
        "batch_id":  str(batch.id),
        "processed": batch.processed_files,
        "failed":    batch.failed_files,
        "url":       f"/invoices/batches/",
        "timestamp": timezone.now().isoformat(),
    })


# ── URL routing (add to routing.py) ──────────────────────────────────────────
ROUTING_SNIPPET = """
# finai_backend/routing.py
from django.urls import re_path
from core.websocket import AlertConsumer

websocket_urlpatterns = [
    re_path(r"^ws/alerts/$", AlertConsumer.as_asgi()),
]
"""

# ── ASGI application (replace wsgi.py usage) ─────────────────────────────────
ASGI_SNIPPET = """
# finai_backend/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from finai_backend.routing import websocket_urlpatterns

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")

application = ProtocolTypeRouter({
    "http":      get_asgi_application(),
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
"""
