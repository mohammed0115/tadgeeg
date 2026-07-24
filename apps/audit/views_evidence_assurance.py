"""Evidence assurance & reporting API (TADGEEG-FIN-AUDIT-6D).

ADDITIVE endpoints only. Every endpoint is organization-scoped and auditor-only
(assurance is an internal quality function — clients never see these reports).
Reporting only: nothing here deletes, repairs, or purges evidence, changes a
readiness conclusion, or writes to the ledger.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .evidence_models import AuditEvidenceRetentionPolicy
from .services import evidence_assurance as assurance


def _user_org(request):
    return getattr(request.user, "organization", None)


def _scoped_engagement(request, engagement_id):
    org = _user_org(request)
    if not org or not engagement_id:
        return None
    return AuditEngagement.objects.filter(pk=engagement_id, organization=org).first()


class _AuditorScopedView(APIView):
    """Base: authenticated + auditor+, with an organization guard."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    def _org_or_error(self, request):
        org = _user_org(request)
        if org is None:
            return None, Response({"error": "no organization."},
                                  status=status.HTTP_400_BAD_REQUEST)
        return org, None

    def _optional_engagement(self, request):
        """Resolve ?engagement=<uuid>; returns (engagement, error_response)."""
        eid = request.query_params.get("engagement") or request.data.get("engagement") \
            if hasattr(request, "data") else request.query_params.get("engagement")
        if not eid:
            return None, None
        engagement = _scoped_engagement(request, eid)
        if engagement is None:
            return None, Response({"error": "engagement not found in your organization."},
                                  status=status.HTTP_404_NOT_FOUND)
        return engagement, None


class EvidenceIntegritySweepView(_AuditorScopedView):
    """POST: run a deterministic integrity sweep (report only, no repair)."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Run integrity sweep")
    def post(self, request):
        org, err = self._org_or_error(request)
        if err:
            return err
        engagement, err = self._optional_engagement(request)
        if err:
            return err
        limit = request.data.get("limit")
        stats = assurance.sweep_attachments(
            organization=org, engagement=engagement, actor=request.user,
            limit=int(limit) if limit else None)
        return Response(stats)


class EvidenceIntegrityReportView(_AuditorScopedView):
    """GET: organization-scoped integrity exception report."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Integrity exception report")
    def get(self, request):
        org, err = self._org_or_error(request)
        if err:
            return err
        engagement, err = self._optional_engagement(request)
        if err:
            return err
        return Response(assurance.integrity_exception_report(
            organization=org, engagement=engagement))


class EvidenceCoverageView(_AuditorScopedView):
    """GET: evidence coverage per GL finding and SAD item."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Evidence coverage analysis")
    def get(self, request):
        org, err = self._org_or_error(request)
        if err:
            return err
        engagement, err = self._optional_engagement(request)
        if err:
            return err
        return Response(assurance.evidence_coverage(
            organization=org, engagement=engagement))


class EvidenceIndexView(_AuditorScopedView):
    """GET: the immutable evidence index (contains NO download URLs)."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Evidence index")
    def get(self, request):
        org, err = self._org_or_error(request)
        if err:
            return err
        engagement, err = self._optional_engagement(request)
        if err:
            return err
        return Response({"index": assurance.evidence_index(
            organization=org, engagement=engagement)})


class EvidenceAssuranceDashboardView(_AuditorScopedView):
    """GET: assurance dashboard aggregates (integrity %, coverage %, counters)."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Assurance dashboard")
    def get(self, request):
        org, err = self._org_or_error(request)
        if err:
            return err
        engagement, err = self._optional_engagement(request)
        if err:
            return err
        return Response(assurance.assurance_dashboard(
            organization=org, engagement=engagement))


class EngagementRetentionPolicyView(_AuditorScopedView):
    """GET/POST the engagement's evidence retention policy (metadata only)."""

    @extend_schema(tags=["Audit · Evidence Assurance"], summary="Get retention policy")
    def get(self, request, pk):
        engagement = _scoped_engagement(request, pk)
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        policy = AuditEvidenceRetentionPolicy.objects.filter(
            engagement=engagement).first()
        if policy is None:
            return Response({"policy": None,
                             "choices": AuditEvidenceRetentionPolicy.Policy.choices})
        return Response(_policy_payload(policy))

    @extend_schema(tags=["Audit · Evidence Assurance"],
                   summary="Set (and optionally apply) the retention policy")
    def post(self, request, pk):
        engagement = _scoped_engagement(request, pk)
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            policy = assurance.set_retention_policy(
                engagement=engagement, actor=request.user,
                policy=request.data.get("policy",
                                        AuditEvidenceRetentionPolicy.Policy.YEARS_7),
                custom_years=request.data.get("custom_years") or None,
                reason=request.data.get("reason", ""))
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        result = None
        if request.data.get("apply"):
            result = assurance.apply_retention_policy(
                policy_obj=policy, actor=request.user)
        return Response({**_policy_payload(policy), "applied": result})


def _policy_payload(policy) -> dict:
    return {
        "id": str(policy.id),
        "engagement": str(policy.engagement_id),
        "policy": policy.policy,
        "policy_display": policy.get_policy_display(),
        "custom_years": policy.custom_years,
        "years": policy.years,
        "reason": policy.reason,
        "applied_at": policy.applied_at.isoformat() if policy.applied_at else None,
        "attachments_marked": policy.attachments_marked,
        "note": "Retention is metadata only — evidence is never deleted or purged.",
    }
