"""HTTP API for managing AlertRules + the events log + acknowledgement.

  GET  /api/v1/alerts/rules/                  — list rules in the user's org
  POST /api/v1/alerts/rules/                  — create
  GET  /api/v1/alerts/rules/<pk>/             — detail
  PUT  /api/v1/alerts/rules/<pk>/             — update
  DEL  /api/v1/alerts/rules/<pk>/             — delete
  POST /api/v1/alerts/rules/<pk>/test/        — fire a synthetic alert (admin)
  GET  /api/v1/alerts/events/                 — event log (filterable)
  POST /api/v1/alerts/events/<pk>/ack/        — mark as acknowledged
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.dispatcher import dispatch_for_anomaly
from apps.alerts.models import AlertEvent, AlertRule
from apps.authentication.models import User


PUBLISH_ROLES = {User.Role.ADMIN, User.Role.CHIEF_AUDIT_OFFICER}


def _can_manage(user) -> bool:
    return user.is_superuser or user.role in PUBLISH_ROLES


def _serialise_rule(rule: AlertRule) -> dict:
    return {
        "id":                str(rule.id),
        "name":              rule.name,
        "description":       rule.description,
        "trigger_type":      rule.trigger_type,
        "trigger_detector":  rule.trigger_detector,
        "min_severity":      rule.min_severity,
        "channels":          rule.channels or [],
        "cooldown_minutes":  rule.cooldown_minutes,
        "is_active":         rule.is_active,
        "created_at":        rule.created_at.isoformat(),
        "updated_at":        rule.updated_at.isoformat(),
    }


def _serialise_event(ev: AlertEvent) -> dict:
    return {
        "id":            str(ev.id),
        "rule_id":       str(ev.rule_id) if ev.rule_id else None,
        "channel_type":  ev.channel_type,
        "channel_target": ev.channel_target,
        "status":        ev.status,
        "severity":      ev.severity,
        "summary":       ev.summary,
        "source_type":   ev.source_type,
        "source_id":     ev.source_id,
        "dedup_key":     ev.dedup_key,
        "error_message": ev.error_message,
        "sent_at":       ev.sent_at.isoformat(),
        "acknowledged_at": ev.acknowledged_at.isoformat() if ev.acknowledged_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────────────────────────────────────

class AlertRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = AlertRule.objects.filter(organization=org).order_by("-updated_at")
        return Response({
            "results": [_serialise_rule(r) for r in qs],
            "counts": {
                "active":   AlertRule.objects.filter(organization=org, is_active=True).count(),
                "inactive": AlertRule.objects.filter(organization=org, is_active=False).count(),
            },
        })

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required"}, status=400)

        channels = request.data.get("channels") or []
        if not isinstance(channels, list):
            return Response({"error": "channels must be a list"}, status=400)
        for cfg in channels:
            if not isinstance(cfg, dict) or not cfg.get("type"):
                return Response({"error": "each channel must have a 'type'"}, status=400)

        try:
            rule = AlertRule.objects.create(
                organization=org,
                name=name,
                description=request.data.get("description") or "",
                trigger_type=request.data.get("trigger_type") or "anomaly",
                trigger_detector=request.data.get("trigger_detector") or "",
                min_severity=request.data.get("min_severity") or "medium",
                channels=channels,
                cooldown_minutes=int(request.data.get("cooldown_minutes") or 30),
                is_active=bool(request.data.get("is_active", True)),
                created_by=request.user,
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(_serialise_rule(rule), status=201)


class AlertRuleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        org = getattr(request.user, "organization", None)
        if not org:
            return None
        return AlertRule.objects.filter(pk=pk, organization=org).first()

    def get(self, request, pk):
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)
        return Response(_serialise_rule(rule))

    def put(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)

        for f in ("name", "description", "trigger_type", "trigger_detector",
                  "min_severity", "channels", "cooldown_minutes", "is_active"):
            if f in request.data:
                setattr(rule, f, request.data[f])
        rule.save()
        return Response(_serialise_rule(rule))

    def delete(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)
        rule.delete()
        return Response(status=204)


class AlertRuleTestView(APIView):
    """POST /api/v1/alerts/rules/<pk>/test/ — fire a synthetic AnomalyHit through
    the dispatcher so the user can verify the channel config is correct."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_manage(request.user):
            return Response({"error": "admin/CAO role required"}, status=403)

        org = getattr(request.user, "organization", None)
        rule = AlertRule.objects.filter(pk=pk, organization=org).first()
        if not rule:
            return Response({"error": "not found"}, status=404)

        # Synthesise a hit that matches this rule's filters so the dispatcher
        # actually fires it (subject to cooldown).
        from types import SimpleNamespace
        synthetic = SimpleNamespace(
            id=None,
            organization_id=str(org.id),
            detector=rule.trigger_detector or "test",
            severity=(rule.min_severity if rule.min_severity != "low" else "medium"),
            invoice_id="",
            vendor_name="(synthetic test)",
            explanation=f"Synthetic test of alert rule '{rule.name}'",
            details={"synthetic": True, "rule_id": str(rule.id)},
        )
        result = dispatch_for_anomaly(synthetic)
        return Response({"ok": True, "dispatch": result})


# ─────────────────────────────────────────────────────────────────────────────
# Events
# ─────────────────────────────────────────────────────────────────────────────

class AlertEventListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})
        qs = AlertEvent.objects.filter(organization=org)
        status_filter = request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        rule_id = request.GET.get("rule_id")
        if rule_id:
            qs = qs.filter(rule_id=rule_id)
        return Response({
            "results": [_serialise_event(e) for e in qs[:200]],
            "counts": {
                s: AlertEvent.objects.filter(organization=org, status=s).count()
                for s in ("sent", "failed", "suppressed", "acknowledged")
            },
        })


class AlertEventAckView(APIView):
    """POST /api/v1/alerts/events/<pk>/ack/ — mark this event as acknowledged."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = getattr(request.user, "organization", None)
        ev = AlertEvent.objects.filter(pk=pk, organization=org).first()
        if not ev:
            return Response({"error": "not found"}, status=404)
        if ev.acknowledged_at:
            return Response({"ok": True, "already_acknowledged": True})

        ev.status = AlertEvent.Status.ACKNOWLEDGED
        ev.acknowledged_at = timezone.now()
        ev.acknowledged_by = request.user
        ev.save(update_fields=["status", "acknowledged_at", "acknowledged_by"])
        return Response(_serialise_event(ev))
