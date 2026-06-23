"""Trial Balance upload/list/detail + Account Mapping API (TADGEEG-FIN-AUDIT-1B).

Minimal, organization-scoped DRF endpoints over the 1A staging tables. Every
query is scoped to ``request.user.organization`` via the engagement, so a user
can never read or import into another organization's engagement. Uploads call
the existing ``parse_and_validate`` service; nothing is written to the ledger.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.authentication.permissions import IsSeniorAuditorOrAbove

from .engagement_models import AuditEngagement
from .general_ledger_models import GeneralLedgerImport, GeneralLedgerRiskFinding
from .serializers import (
    AccountMappingSerializer,
    GeneralLedgerImportSerializer,
    GeneralLedgerRiskFindingSerializer,
    TrialBalanceImportSerializer,
)
from .services import account_mapping as mapping_service
from .services import general_ledger_import as gl_service
from .services import general_ledger_risk_analysis as gl_risk_service
from .services import trial_balance_import as tb_service
from .trial_balance_models import AccountMapping, TrialBalanceImport

_EXT_TO_FORMAT = {"csv": "csv", "xlsx": "xlsx", "xls": "xls"}


def _user_org(request):
    return getattr(request.user, "organization", None)


def _scoped_engagement(request, engagement_id):
    """Return the engagement IFF it belongs to the user's org, else None.

    This is the cross-tenant guard: an engagement in another org simply isn't
    found, so the caller returns 404 and never leaks existence.
    """
    org = _user_org(request)
    if not org or not engagement_id:
        return None
    return AuditEngagement.objects.filter(pk=engagement_id, organization=org).first()


class TrialBalanceImportListCreateView(APIView):
    """GET: list imports in the user's org. POST: upload a TB file to an engagement."""
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        # Reading is any authenticated org member; uploading is auditor+.
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSeniorAuditorOrAbove()]
        return [IsAuthenticated()]

    @extend_schema(tags=["Audit · Trial Balance"], summary="List trial balance imports")
    def get(self, request):
        org = _user_org(request)
        if not org:
            return Response({"error": "No organization."}, status=400)
        qs = TrialBalanceImport.objects.filter(organization=org).select_related("engagement")
        if eng_id := request.query_params.get("engagement"):
            qs = qs.filter(engagement_id=eng_id)
        data = TrialBalanceImportSerializer(qs, many=True).data
        return Response(data)

    @extend_schema(tags=["Audit · Trial Balance"], summary="Upload a trial balance file")
    def post(self, request):
        eng_id = request.data.get("engagement")
        engagement = _scoped_engagement(request, eng_id)
        if engagement is None:
            # Either missing or belongs to another org → do not disclose which.
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("uploaded_file")
        if not upload:
            return Response({"error": "uploaded_file is required."}, status=400)

        ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        source_format = _EXT_TO_FORMAT.get(ext)
        if not source_format:
            return Response(
                {"error": f"unsupported file type '.{ext}'. Use csv, xlsx, or xls."},
                status=400,
            )

        imp = TrialBalanceImport.objects.create(
            engagement=engagement,
            organization=engagement.organization,
            uploaded_file=upload,
            original_filename=upload.name[:255],
            source_format=source_format,
            period_start=request.data.get("period_start") or None,
            period_end=request.data.get("period_end") or None,
            fiscal_year=request.data.get("fiscal_year") or None,
            currency=(request.data.get("currency") or "")[:8],
            created_by=request.user,
        )
        try:
            tb_service.parse_and_validate(imp)
        except tb_service.TrialBalanceImportError as exc:
            imp.refresh_from_db()
            return Response(
                {"error": str(exc), "import": TrialBalanceImportSerializer(imp).data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        imp.refresh_from_db()
        return Response(TrialBalanceImportSerializer(imp).data,
                        status=status.HTTP_201_CREATED)


class TrialBalanceImportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Trial Balance"], summary="Trial balance import detail")
    def get(self, request, pk):
        org = _user_org(request)
        imp = (TrialBalanceImport.objects
               .filter(pk=pk, organization=org)
               .select_related("engagement")
               .first())
        if imp is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TrialBalanceImportSerializer(imp).data)


class AccountMappingListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · Trial Balance"], summary="List account mappings")
    def get(self, request):
        org = _user_org(request)
        if not org:
            return Response({"error": "No organization."}, status=400)
        qs = AccountMapping.objects.filter(organization=org)
        if eng_id := request.query_params.get("engagement"):
            qs = qs.filter(engagement_id=eng_id)
        return Response(AccountMappingSerializer(qs, many=True).data)


class GenerateAccountMappingsView(APIView):
    """POST {import_id}: deterministically suggest mappings for an import."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · Trial Balance"],
                   summary="Generate account mappings from an import")
    def post(self, request):
        org = _user_org(request)
        import_id = request.data.get("import_id")
        imp = (TrialBalanceImport.objects
               .filter(pk=import_id, organization=org)
               .select_related("engagement")
               .first())
        if imp is None:
            return Response({"error": "import not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        summary = mapping_service.generate_mappings_from_import(imp, created_by=request.user)
        return Response(summary, status=status.HTTP_201_CREATED)


# ── TADGEEG-FIN-AUDIT-2A — General Ledger import (same safe pattern) ───────────
class GeneralLedgerImportListCreateView(APIView):
    """GET: list GL imports in the user's org. POST: upload a GL file."""
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSeniorAuditorOrAbove()]
        return [IsAuthenticated()]

    @extend_schema(tags=["Audit · General Ledger"], summary="List general ledger imports")
    def get(self, request):
        org = _user_org(request)
        if not org:
            return Response({"error": "No organization."}, status=400)
        qs = GeneralLedgerImport.objects.filter(organization=org).select_related("engagement")
        if eng_id := request.query_params.get("engagement"):
            qs = qs.filter(engagement_id=eng_id)
        return Response(GeneralLedgerImportSerializer(qs, many=True).data)

    @extend_schema(tags=["Audit · General Ledger"], summary="Upload a general ledger file")
    def post(self, request):
        engagement = _scoped_engagement(request, request.data.get("engagement"))
        if engagement is None:
            return Response({"error": "engagement not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("uploaded_file")
        if not upload:
            return Response({"error": "uploaded_file is required."}, status=400)

        ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        source_format = _EXT_TO_FORMAT.get(ext)
        if not source_format:
            return Response(
                {"error": f"unsupported file type '.{ext}'. Use csv, xlsx, or xls."},
                status=400,
            )

        # Optional link to a TB import — must belong to the same engagement/org.
        tb_import = None
        if tb_id := request.data.get("related_trial_balance_import"):
            tb_import = TrialBalanceImport.objects.filter(
                pk=tb_id, organization=engagement.organization, engagement=engagement,
            ).first()
            if tb_import is None:
                return Response(
                    {"error": "related_trial_balance_import not found in this engagement."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        imp = GeneralLedgerImport.objects.create(
            engagement=engagement,
            organization=engagement.organization,
            related_trial_balance_import=tb_import,
            uploaded_file=upload,
            original_filename=upload.name[:255],
            source_format=source_format,
            period_start=request.data.get("period_start") or None,
            period_end=request.data.get("period_end") or None,
            fiscal_year=request.data.get("fiscal_year") or None,
            currency=(request.data.get("currency") or "")[:8],
            created_by=request.user,
        )
        try:
            gl_service.parse_and_validate(imp)
        except gl_service.GeneralLedgerImportError as exc:
            imp.refresh_from_db()
            return Response(
                {"error": str(exc), "import": GeneralLedgerImportSerializer(imp).data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        imp.refresh_from_db()
        return Response(GeneralLedgerImportSerializer(imp).data,
                        status=status.HTTP_201_CREATED)


class GeneralLedgerImportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · General Ledger"], summary="General ledger import detail")
    def get(self, request, pk):
        org = _user_org(request)
        imp = (GeneralLedgerImport.objects
               .filter(pk=pk, organization=org)
               .select_related("engagement")
               .first())
        if imp is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(GeneralLedgerImportSerializer(imp).data)


# ── TADGEEG-FIN-AUDIT-2B — GL risk analysis & candidate findings ──────────────
class GeneralLedgerAnalyzeRisksView(APIView):
    """POST: run deterministic risk analysis for one GL import (org-scoped)."""
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

    @extend_schema(tags=["Audit · General Ledger"], summary="Analyze GL risks")
    def post(self, request, pk):
        org = _user_org(request)
        imp = (GeneralLedgerImport.objects
               .filter(pk=pk, organization=org)
               .select_related("engagement")
               .first())
        if imp is None:
            return Response({"error": "GL import not found in your organization."},
                            status=status.HTTP_404_NOT_FOUND)
        summary = gl_risk_service.analyze_import(imp, created_by=request.user)
        return Response(summary, status=status.HTTP_201_CREATED)


class GeneralLedgerRiskFindingListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · General Ledger"], summary="List GL risk findings")
    def get(self, request):
        org = _user_org(request)
        if not org:
            return Response({"error": "No organization."}, status=400)
        qs = GeneralLedgerRiskFinding.objects.filter(organization=org)
        if imp_id := request.query_params.get("import"):
            qs = qs.filter(general_ledger_import_id=imp_id)
        if eng_id := request.query_params.get("engagement"):
            qs = qs.filter(engagement_id=eng_id)
        if sev := request.query_params.get("severity"):
            qs = qs.filter(severity=sev)
        return Response(GeneralLedgerRiskFindingSerializer(qs, many=True).data)


class GeneralLedgerRiskFindingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Audit · General Ledger"], summary="GL risk finding detail")
    def get(self, request, pk):
        org = _user_org(request)
        f = GeneralLedgerRiskFinding.objects.filter(pk=pk, organization=org).first()
        if f is None:
            return Response({"error": "not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(GeneralLedgerRiskFindingSerializer(f).data)
