"""
HTTP endpoints for the Custom Rule Builder — Phase 2.2.

  GET  /api/v1/rules/                 — list rules in the user's org
  POST /api/v1/rules/                 — create a draft rule
  GET  /api/v1/rules/<pk>/            — fetch one
  PUT  /api/v1/rules/<pk>/            — update a draft rule
  POST /api/v1/rules/<pk>/test/       — sandbox-run against a sample of invoices
  POST /api/v1/rules/<pk>/publish/    — admin-only; flip status to PUBLISHED
  POST /api/v1/rules/<pk>/archive/    — admin-only; flip status to ARCHIVED
  GET  /api/v1/rules/dsl-schema/      — return the spec/operators for the UI
"""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import CustomRuleDefinition
from apps.audit.services.rule_dsl import (
    ALL_OPS, COMPARISON_OPS, EXISTENCE_OPS, LIST_OPS, STRING_OPS,
    DSLValidationError, sandbox_run, validate_dsl,
)
from apps.authentication.models import User

logger = logging.getLogger("finai")


# ─────────────────────────────────────────────────────────────────────────────
# Authorisation
# ─────────────────────────────────────────────────────────────────────────────

PUBLISH_ROLES = {User.Role.ADMIN, User.Role.CHIEF_AUDIT_OFFICER}


def _can_publish(user) -> bool:
    return user.is_superuser or user.role in PUBLISH_ROLES


def _serialise(rule: CustomRuleDefinition) -> dict:
    return {
        "id":             str(rule.id),
        "name":           rule.name,
        "description":    rule.description,
        "standard":       rule.standard,
        "severity":       rule.severity,
        "condition_type": rule.condition_type,
        "condition_params": rule.condition_params or {},
        "expression_dsl": rule.expression_dsl or {},
        "remediation":    rule.remediation_suggestion,
        "status":         rule.status,
        "is_active":      rule.is_active,
        "version":        rule.version,
        "published_at":   rule.published_at.isoformat() if rule.published_at else None,
        "published_by":   str(rule.published_by_id) if rule.published_by_id else None,
        "created_by":     str(rule.created_by_id) if rule.created_by_id else None,
        "created_at":     rule.created_at.isoformat(),
        "updated_at":     rule.updated_at.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

class RuleListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"results": []})

        qs = CustomRuleDefinition.objects.filter(organization=org).order_by("-updated_at")

        status_filter = (request.GET.get("status") or "").strip().lower()
        if status_filter and status_filter in {"draft", "published", "archived"}:
            qs = qs.filter(status=status_filter)

        return Response({
            "results": [_serialise(r) for r in qs[:200]],
            "counts": {
                "draft":     CustomRuleDefinition.objects.filter(organization=org, status="draft").count(),
                "published": CustomRuleDefinition.objects.filter(organization=org, status="published").count(),
                "archived":  CustomRuleDefinition.objects.filter(organization=org, status="archived").count(),
            },
        })

    def post(self, request):
        """Create a new rule. Always starts in DRAFT — must be published explicitly."""
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required"}, status=400)

        condition_type = request.data.get("condition_type") or "dsl"
        dsl = request.data.get("expression_dsl") or {}

        if condition_type == "dsl":
            try:
                validate_dsl(dsl)
            except DSLValidationError as exc:
                return Response({"error": f"invalid DSL: {exc}"}, status=400)

        try:
            rule = CustomRuleDefinition.objects.create(
                organization=org,
                name=name,
                description=request.data.get("description") or "",
                standard=request.data.get("standard") or "custom",
                severity=request.data.get("severity") or "medium",
                condition_type=condition_type,
                condition_params=request.data.get("condition_params") or {},
                expression_dsl=dsl,
                remediation_suggestion=request.data.get("remediation") or "",
                status=CustomRuleDefinition.Status.DRAFT,
                created_by=request.user,
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=400)

        return Response(_serialise(rule), status=201)


class RuleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk) -> CustomRuleDefinition | None:
        org = getattr(request.user, "organization", None)
        if not org:
            return None
        return CustomRuleDefinition.objects.filter(pk=pk, organization=org).first()

    def get(self, request, pk):
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)
        return Response(_serialise(rule))

    def put(self, request, pk):
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)
        # Editing a published rule auto-clones to a fresh DRAFT — published
        # rules are intentionally immutable to keep the audit trail honest.
        if rule.status == CustomRuleDefinition.Status.PUBLISHED:
            return Response(
                {"error": "published rules cannot be edited; archive and create a new version"},
                status=409,
            )

        for field in ("name", "description", "standard", "severity", "remediation"):
            if field in request.data:
                target = "remediation_suggestion" if field == "remediation" else field
                setattr(rule, target, request.data[field])

        if "condition_type" in request.data:
            rule.condition_type = request.data["condition_type"]
        if "condition_params" in request.data:
            rule.condition_params = request.data["condition_params"] or {}
        if "expression_dsl" in request.data:
            dsl = request.data["expression_dsl"] or {}
            if rule.condition_type == "dsl":
                try:
                    validate_dsl(dsl)
                except DSLValidationError as exc:
                    return Response({"error": f"invalid DSL: {exc}"}, status=400)
            rule.expression_dsl = dsl

        rule.save()
        return Response(_serialise(rule))

    def delete(self, request, pk):
        rule = self._get(request, pk)
        if not rule:
            return Response({"error": "not found"}, status=404)
        if rule.status == CustomRuleDefinition.Status.PUBLISHED:
            return Response(
                {"error": "archive published rules instead of deleting"},
                status=409,
            )
        rule.delete()
        return Response(status=204)


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox / Publish / Archive
# ─────────────────────────────────────────────────────────────────────────────

class RuleSandboxView(APIView):
    """POST /api/v1/rules/<pk>/test/

    Body: optionally ``{"sample_size": 100}``.

    Runs the rule's DSL against the most-recent ``sample_size`` invoices in
    the user's org and returns per-row pass/fail. Any role can call this —
    it's read-only, sandboxed, and bounded.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        org = getattr(request.user, "organization", None)
        if not org:
            return Response({"error": "user has no organization"}, status=400)

        rule = CustomRuleDefinition.objects.filter(pk=pk, organization=org).first()
        if not rule:
            return Response({"error": "not found"}, status=404)
        if not rule.expression_dsl:
            return Response({"error": "rule has no DSL — only DSL rules can be sandbox-tested"},
                            status=400)

        size = max(1, min(500, int(request.data.get("sample_size") or 100)))

        from apps.invoices.models import Invoice
        sample_qs = (Invoice.objects.filter(organization=org)
                     .order_by("-created_at")[:size])

        sample = []
        for inv in sample_qs:
            sample.append({
                "id":             str(inv.id),
                "invoice_id":     str(inv.id),
                "invoice_number": inv.invoice_number or "",
                "vendor_name":    inv.vendor_name or "",
                "vendor_vat_number": inv.vendor_vat_number or "",
                "currency":       inv.currency or "",
                "subtotal":       float(inv.subtotal or 0),
                "vat_amount":     float(inv.vat_amount or 0),
                "total_amount":   float(inv.total_amount or 0),
                "vat_rate":       float(inv.vat_rate or 0),
                "invoice_date":   inv.invoice_date.isoformat() if inv.invoice_date else "",
                "due_date":       inv.due_date.isoformat() if inv.due_date else "",
                "status":         inv.status,
                "risk_level":     inv.risk_level,
                "risk_score":     float(inv.risk_score or 0),
                "is_duplicate":   bool(inv.is_duplicate),
                "has_qr_code":    bool(inv.has_qr_code),
                "qr_code_valid":  bool(inv.qr_code_valid),
            })

        result = sandbox_run(rule.expression_dsl, sample)
        return Response(result)


class RulePublishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_publish(request.user):
            return Response({"error": "admin / CAO role required to publish rules"}, status=403)

        org = getattr(request.user, "organization", None)
        rule = CustomRuleDefinition.objects.filter(pk=pk, organization=org).first()
        if not rule:
            return Response({"error": "not found"}, status=404)
        if rule.status == CustomRuleDefinition.Status.PUBLISHED:
            return Response({"error": "already published"}, status=409)

        # If DSL — validate one last time before letting it loose on real audits.
        if rule.condition_type == "dsl":
            try:
                validate_dsl(rule.expression_dsl or {})
            except DSLValidationError as exc:
                return Response({"error": f"DSL invalid: {exc}"}, status=400)

        rule.status = CustomRuleDefinition.Status.PUBLISHED
        rule.published_at = timezone.now()
        rule.published_by = request.user
        rule.save(update_fields=["status", "published_at", "published_by",
                                 "version", "updated_at"])
        return Response(_serialise(rule))


class RuleArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_publish(request.user):
            return Response({"error": "admin / CAO role required to archive rules"}, status=403)
        org = getattr(request.user, "organization", None)
        rule = CustomRuleDefinition.objects.filter(pk=pk, organization=org).first()
        if not rule:
            return Response({"error": "not found"}, status=404)

        rule.status = CustomRuleDefinition.Status.ARCHIVED
        rule.save(update_fields=["status", "version", "updated_at"])
        return Response(_serialise(rule))


# ─────────────────────────────────────────────────────────────────────────────
# UI helper — the schema the visual builder reads
# ─────────────────────────────────────────────────────────────────────────────

class DSLSchemaView(APIView):
    """GET /api/v1/rules/dsl-schema/ — describe the DSL for the UI to render forms."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "operators": {
                "comparison": sorted(COMPARISON_OPS),
                "string":     sorted(STRING_OPS),
                "list":       sorted(LIST_OPS),
                "existence":  sorted(EXISTENCE_OPS),
            },
            "fields": [
                # Common Invoice fields the UI offers as drop-down options.
                {"key": "invoice_number",     "label": "Invoice number", "type": "string"},
                {"key": "vendor_name",        "label": "Vendor name",    "type": "string"},
                {"key": "vendor_vat_number",  "label": "Vendor VAT",     "type": "string"},
                {"key": "currency",           "label": "Currency",       "type": "string"},
                {"key": "subtotal",           "label": "Subtotal",       "type": "number"},
                {"key": "vat_amount",         "label": "VAT amount",     "type": "number"},
                {"key": "total_amount",       "label": "Total amount",   "type": "number"},
                {"key": "vat_rate",           "label": "VAT rate %",     "type": "number"},
                {"key": "invoice_date",       "label": "Invoice date",   "type": "date"},
                {"key": "due_date",           "label": "Due date",       "type": "date"},
                {"key": "status",             "label": "Workflow status","type": "enum"},
                {"key": "risk_level",         "label": "Risk level",     "type": "enum"},
                {"key": "risk_score",         "label": "Risk score",     "type": "number"},
                {"key": "is_duplicate",       "label": "Is duplicate",   "type": "boolean"},
                {"key": "has_qr_code",        "label": "Has QR code",    "type": "boolean"},
                {"key": "qr_code_valid",      "label": "QR code valid",  "type": "boolean"},
            ],
            "actions":    ["flag", "block", "warn"],
            "severities": ["low", "medium", "high", "critical"],
            "sample": {
                "when": {
                    "all": [
                        {"field": "total_amount", "op": ">",  "value": 100000},
                        {"field": "vendor_vat_number", "op": "is_empty"},
                    ],
                },
                "then": {"action": "flag", "severity": "high",
                         "message": "Large invoice with missing vendor VAT"},
            },
        })
