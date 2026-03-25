"""Vendor dashboard API views for the split tenant console."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import OrganizationSettings
from apps.authentication.views import CurrentOrganizationView, ChangePasswordView
from apps.audit_engine.models import AuditJob, AuditResult
from apps.documents.models import Document
from apps.file_management.models import AuditFileProfile, Folder
from apps.file_management.serializers import AuditFileListSerializer, FolderSerializer
from apps.reports.models import Report
from core.permissions import IsOrganizationMember, is_org_admin, is_org_auditor


User = get_user_model()


def _human_size(size_bytes: int) -> str:
    size = float(size_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def _current_org(user):
    organization = getattr(user, "organization", None)
    if organization is None:
        raise Http404("Organization context is required.")
    return organization


def _storage_payload(organization) -> dict:
    documents = Document.objects.filter(organization=organization)
    total_files = documents.count()
    total_size = documents.aggregate(total=Sum("file_size")).get("total") or 0
    storage_limit_bytes = 1024 * 1024 * 1024
    breakdown = (
        documents.values("document_type")
        .annotate(size=Sum("file_size"), count=Count("id"))
        .order_by("-size")
    )

    color_map = {
        "invoice": "#3b82f6",
        "receipt": "#8b5cf6",
        "bank_statement": "#10b981",
        "purchase_order": "#f59e0b",
    }
    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "storage_used_human": _human_size(total_size),
        "storage_limit_human": _human_size(storage_limit_bytes),
        "storage_percent": round((total_size / storage_limit_bytes) * 100, 2) if storage_limit_bytes else 0,
        "storage_breakdown": [
            {
                "type": item["document_type"],
                "label_ar": item["document_type"],
                "size_bytes": item["size"] or 0,
                "size_human": _human_size(item["size"] or 0),
                "count": item["count"],
                "color": color_map.get(item["document_type"], "#64748b"),
            }
            for item in breakdown
        ],
    }


def _notification_key(kind: str) -> str:
    return f"vendor_dashboard_notifications_{kind}"


def _build_notifications(request) -> list[dict]:
    organization = _current_org(request.user)
    hidden_ids = set(request.session.get(_notification_key("hidden"), []))
    read_ids = set(request.session.get(_notification_key("read"), []))
    logs = ActivityLog.objects.filter(organization=organization).order_by("-created_at")[:50]

    def notification_type(item: ActivityLog) -> str:
        if item.action == ActivityLog.Action.AUDIT_COMPLETED:
            return "audit_complete"
        if item.action == ActivityLog.Action.AUDIT_FAILED:
            return "audit_failed"
        if item.action == ActivityLog.Action.STORAGE_CHANGED:
            return "storage_warning"
        if item.action == ActivityLog.Action.REPORT_GENERATED:
            return "system"
        return "system"

    payload = []
    for item in logs:
        item_id = str(item.id)
        if item_id in hidden_ids:
            continue
        payload.append(
            {
                "id": item_id,
                "title": item.get_action_display(),
                "message": item.description or item.get_action_display(),
                "notification_type": notification_type(item),
                "is_read": item_id in read_ids,
                "created_at": item.created_at,
            }
        )
    return payload


class VendorDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsOrganizationMember]


class VendorDashboardStatsView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        storage = _storage_payload(organization)
        jobs = AuditJob.objects.filter(organization=organization)
        return Response(
            {
                "total_files": storage["total_files"],
                "storage_used_human": storage["storage_used_human"],
                "storage_limit_human": storage["storage_limit_human"],
                "storage_percent": storage["storage_percent"],
                "storage_breakdown": storage["storage_breakdown"],
                "running_audits": jobs.filter(status__in=[AuditJob.Status.RUNNING, AuditJob.Status.QUEUED]).count(),
                "pending_audits": jobs.filter(status=AuditJob.Status.PENDING).count(),
                "total_reports": Report.objects.filter(organization=organization).count(),
                "team_members": User.objects.filter(organization=organization, is_active=True).count(),
            }
        )


class VendorActivityFeedView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        limit = max(1, min(int(request.query_params.get("limit", 8)), 50))
        queryset = ActivityLog.objects.filter(organization=organization).order_by("-created_at")[:limit]
        payload = []
        for item in queryset:
            activity_type = "activity"
            if item.action == ActivityLog.Action.FILE_UPLOADED:
                activity_type = "upload"
            elif item.action in {ActivityLog.Action.AUDIT_STARTED, ActivityLog.Action.AUDIT_COMPLETED, ActivityLog.Action.AUDIT_FAILED}:
                activity_type = "audit"
            elif item.action == ActivityLog.Action.REPORT_GENERATED:
                activity_type = "report"

            payload.append(
                {
                    "id": str(item.id),
                    "type": activity_type,
                    "description": item.description or item.get_action_display(),
                    "created_at": item.created_at,
                }
            )
        return Response(payload)


class VendorStorageStatsView(VendorDashboardAPIView):
    def get(self, request):
        return Response(_storage_payload(_current_org(request.user)))


class VendorFolderRootView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        folders = Folder.objects.filter(organization=organization, parent__isnull=True).annotate(
            children_count=Count("children"),
            files_count=Count("files"),
        )
        files = (
            AuditFileProfile.objects.filter(audit_file__organization=organization, folder__isnull=True, is_archived=False)
            .select_related("audit_file")
        )
        return Response(
            {
                "folders": FolderSerializer(folders, many=True).data,
                "files": AuditFileListSerializer([item.audit_file for item in files], many=True).data,
            }
        )

    def post(self, request):
        organization = _current_org(request.user)
        name = (request.data.get("name") or "").strip()
        parent_id = request.data.get("parent")
        if not name:
            return Response({"detail": "Folder name is required."}, status=status.HTTP_400_BAD_REQUEST)

        parent = None
        if parent_id:
            parent = Folder.objects.filter(organization=organization, pk=parent_id).first()
            if parent is None:
                return Response({"detail": "Parent folder was not found."}, status=status.HTTP_404_NOT_FOUND)

        folder = Folder.objects.create(
            organization=organization,
            parent=parent,
            name=name,
            created_by=request.user,
        )
        return Response(FolderSerializer(folder).data, status=status.HTTP_201_CREATED)


class VendorFolderContentsView(VendorDashboardAPIView):
    def get(self, request, pk):
        organization = _current_org(request.user)
        folder = Folder.objects.filter(organization=organization, pk=pk).first()
        if folder is None:
            return Response({"detail": "Folder not found."}, status=status.HTTP_404_NOT_FOUND)

        child_folders = folder.children.annotate(children_count=Count("children"), files_count=Count("files"))
        files = AuditFileProfile.objects.filter(audit_file__organization=organization, folder=folder, is_archived=False).select_related("audit_file")
        return Response(
            {
                "folders": FolderSerializer(child_folders, many=True).data,
                "files": AuditFileListSerializer([item.audit_file for item in files], many=True).data,
            }
        )


class VendorFolderDetailView(VendorDashboardAPIView):
    def delete(self, request, pk):
        organization = _current_org(request.user)
        folder = Folder.objects.filter(organization=organization, pk=pk).first()
        if folder is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class VendorAuditJobListView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        queryset = AuditJob.objects.filter(organization=organization).select_related("audit_file").order_by("-created_at")
        status_filter = request.query_params.get("status")
        search = request.query_params.get("search")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(audit_file__original_name__icontains=search)

        payload = []
        for job in queryset[:50]:
            result = getattr(job, "result", None)
            compliance_score = round(float(result.overall_score), 2) if result else None
            risk_score = round(max(0.0, min(100.0, 100.0 - float(result.overall_score))), 2) if result else None
            payload.append(
                {
                    "id": str(job.id),
                    "document_name": job.audit_file.original_name,
                    "document_type": job.audit_file.file_type,
                    "status": job.status,
                    "created_at": job.created_at,
                    "risk_score": risk_score,
                    "compliance_score": compliance_score,
                }
            )
        return Response(payload)


class VendorAuditJobStatsView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        queryset = AuditJob.objects.filter(organization=organization)
        return Response(
            {
                "total": queryset.count(),
                "running": queryset.filter(status__in=[AuditJob.Status.RUNNING, AuditJob.Status.QUEUED]).count(),
                "completed": queryset.filter(status=AuditJob.Status.COMPLETED).count(),
                "failed": queryset.filter(status=AuditJob.Status.FAILED).count(),
            }
        )


class VendorAuditResultListView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        queryset = (
            AuditResult.objects.filter(audit_job__organization=organization)
            .select_related("audit_job", "audit_job__audit_file")
            .prefetch_related("issues")
            .order_by("-created_at")[:50]
        )
        payload = []
        for result in queryset:
            findings = [
                {
                    "rule_id": issue.issue_code or issue.issue_type,
                    "title": issue.title,
                    "message": issue.description,
                    "severity": issue.severity,
                }
                for issue in result.issues.all()[:10]
            ]
            payload.append(
                {
                    "id": str(result.id),
                    "document_name": result.audit_job.audit_file.original_name,
                    "created_at": result.created_at,
                    "risk_level": result.risk_level,
                    "risk_score": round(max(0.0, min(100.0, 100.0 - float(result.overall_score))), 2),
                    "compliance_score": round(float(result.overall_score), 2),
                    "report_id": None,
                    "findings": findings,
                }
            )
        return Response(payload)


class VendorSessionListView(VendorDashboardAPIView):
    def get(self, request):
        return Response(
            [
                {
                    "id": request.session.session_key or "current",
                    "device": request.headers.get("User-Agent", "Current session")[:80],
                    "device_type": "desktop",
                    "ip": request.META.get("REMOTE_ADDR", ""),
                    "last_active": timezone.now(),
                    "is_current": True,
                }
            ]
        )


class VendorSessionDetailView(VendorDashboardAPIView):
    def delete(self, request, pk):
        return Response(status=status.HTTP_204_NO_CONTENT)


class VendorNotificationPreferencesView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        settings_obj, _ = OrganizationSettings.objects.get_or_create(organization=organization)
        return Response(settings_obj.notifications or {})

    def put(self, request):
        organization = _current_org(request.user)
        settings_obj, _ = OrganizationSettings.objects.get_or_create(organization=organization)
        settings_obj.notifications = request.data if isinstance(request.data, dict) else {}
        settings_obj.save(update_fields=["notifications", "updated_at"])
        return Response(settings_obj.notifications)


class VendorTeamMemberListView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        members = User.objects.filter(organization=organization, is_active=True).order_by("full_name", "email")

        def member_role(user) -> str:
            if is_org_admin(user):
                return "admin"
            if is_org_auditor(user):
                return "member"
            return "viewer"

        payload = [
            {
                "id": str(member.id),
                "full_name": member.full_name,
                "email": member.email,
                "role": member_role(member),
            }
            for member in members
        ]
        return Response(payload)


class VendorTeamMemberDetailView(VendorDashboardAPIView):
    def delete(self, request, pk):
        if not is_org_admin(request.user):
            return Response({"detail": "Organization admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        if str(request.user.id) == str(pk):
            return Response({"detail": "You cannot remove your own membership."}, status=status.HTTP_400_BAD_REQUEST)
        organization = _current_org(request.user)
        member = User.objects.filter(organization=organization, pk=pk).first()
        if member is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        member.organization = None
        member.save(update_fields=["organization"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class VendorInvitationListView(VendorDashboardAPIView):
    def get(self, request):
        return Response([])


class VendorInviteView(VendorDashboardAPIView):
    def post(self, request):
        return Response(
            {"detail": "Invitation workflow requires a dedicated membership model."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class VendorInvitationActionView(VendorDashboardAPIView):
    def post(self, request, pk):
        return Response(
            {"detail": "Invitation workflow requires a dedicated membership model."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    def delete(self, request, pk):
        return Response(
            {"detail": "Invitation workflow requires a dedicated membership model."},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class VendorNotificationsView(VendorDashboardAPIView):
    def get(self, request):
        notifications = _build_notifications(request)
        filter_value = request.query_params.get("is_read")
        notification_type = request.query_params.get("notification_type")
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = max(1, min(int(request.query_params.get("page_size", 20)), 100))

        if filter_value == "true":
            notifications = [item for item in notifications if item["is_read"]]
        elif filter_value == "false":
            notifications = [item for item in notifications if not item["is_read"]]

        if notification_type:
            notifications = [item for item in notifications if item["notification_type"] == notification_type]

        total = len(notifications)
        start = (page - 1) * page_size
        end = start + page_size
        return Response({"count": total, "results": notifications[start:end]})


class VendorNotificationsUnreadCountView(VendorDashboardAPIView):
    def get(self, request):
        notifications = _build_notifications(request)
        unread_count = sum(1 for item in notifications if not item["is_read"])
        return Response({"count": unread_count, "unread_count": unread_count})


class VendorNotificationMarkReadView(VendorDashboardAPIView):
    def post(self, request, pk):
        read_ids = set(request.session.get(_notification_key("read"), []))
        read_ids.add(str(pk))
        request.session[_notification_key("read")] = sorted(read_ids)
        request.session.modified = True
        return Response({"id": str(pk), "is_read": True})


class VendorNotificationMarkAllReadView(VendorDashboardAPIView):
    def post(self, request):
        notifications = _build_notifications(request)
        request.session[_notification_key("read")] = sorted(item["id"] for item in notifications)
        request.session.modified = True
        return Response({"updated": len(notifications)})


class VendorNotificationDeleteView(VendorDashboardAPIView):
    def delete(self, request, pk):
        hidden_ids = set(request.session.get(_notification_key("hidden"), []))
        hidden_ids.add(str(pk))
        request.session[_notification_key("hidden")] = sorted(hidden_ids)
        request.session.modified = True
        return Response(status=status.HTTP_204_NO_CONTENT)


class VendorBillingSubscriptionView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        team_size = User.objects.filter(organization=organization, is_active=True).count()
        return Response(
            {
                "plan_name": "Manual Plan",
                "status": "manual",
                "price": 0,
                "billing_period": "month",
                "next_billing_date": None,
                "storage_limit_human": "1.0 GB",
                "audit_limit": "Unlimited",
                "team_limit": team_size,
            }
        )


class VendorBillingUsageView(VendorDashboardAPIView):
    def get(self, request):
        organization = _current_org(request.user)
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        storage = _storage_payload(organization)
        return Response(
            {
                "files_this_month": Document.objects.filter(organization=organization, created_at__gte=month_start).count(),
                "files_percent": 0,
                "audits_this_month": AuditJob.objects.filter(organization=organization, created_at__gte=month_start).count(),
                "audits_percent": 0,
                "storage_used_human": storage["storage_used_human"],
                "storage_percent": storage["storage_percent"],
            }
        )


class VendorBillingInvoiceListView(VendorDashboardAPIView):
    def get(self, request):
        return Response([])


class VendorBillingCancelView(VendorDashboardAPIView):
    def post(self, request):
        return Response({"detail": "No recurring subscription is configured for this organization."})


class VendorOrganizationView(CurrentOrganizationView):
    permission_classes = [IsAuthenticated, IsOrganizationMember]


class VendorChangePasswordView(ChangePasswordView):
    permission_classes = [IsAuthenticated, IsOrganizationMember]
