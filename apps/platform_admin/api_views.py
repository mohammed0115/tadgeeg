"""Platform admin API views for the split admin console."""

from __future__ import annotations

import os
import shutil

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import Organization
from apps.authentication.serializers import OrganizationSerializer
from apps.leads.trial_selectors import (
    build_summary,
    get_dashboard_queryset,
    row_values,
)
from apps.cms.models import CMSPage, FAQCategory, FAQItem, IntroVideo, MediaAsset, PlatformSetting, SEOSetting
from apps.cms.serializers import IntroVideoSerializer, PlatformSettingSerializer, SEOSettingSerializer
from apps.cms.services import update_platform_setting, update_seo_setting
from apps.leads.models import ContactLead
from core.feature_flags import JOBS_DISABLED_COUNT, jobs_enabled
from core.permissions import IsPlatformAdmin
from core.services.monitoring import get_health_check_report


class PlatformAdminAPIView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]


class PlatformDashboardStatsView(PlatformAdminAPIView):
    def get(self, request):
        pages = CMSPage.objects.all()
        # apps.jobs is quarantined — see core.feature_flags. The key is kept
        # so the response shape is stable; the value is None rather than 0
        # because the honest statement is "feature off", not "no jobs".
        return Response(
            {
                "total_organizations": Organization.objects.count(),
                "jobs_feature_enabled": jobs_enabled(),
                "active_jobs": JOBS_DISABLED_COUNT,
                "new_leads": ContactLead.objects.filter(status=ContactLead.Status.NEW).count(),
                "total_leads": ContactLead.objects.count(),
                "total_pages": pages.count(),
                "published_pages": pages.filter(status=CMSPage.PUBLISHED).count(),
                "total_media": MediaAsset.objects.count(),
            }
        )


class PlatformCMSPageStatsView(PlatformAdminAPIView):
    def get(self, request):
        pages = CMSPage.objects.all()
        return Response(
            {
                "total_pages": pages.count(),
                "published_pages": pages.filter(status=CMSPage.PUBLISHED).count(),
                "draft_pages": pages.filter(status=CMSPage.DRAFT).count(),
                "archived_pages": pages.filter(status=CMSPage.ARCHIVED).count(),
            }
        )


class PlatformOrganizationListView(PlatformAdminAPIView):
    def get(self, request):
        queryset = Organization.objects.all().order_by("name")
        return Response(OrganizationSerializer(queryset, many=True).data)

    def post(self, request):
        serializer = OrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = serializer.save()
        return Response(
            OrganizationSerializer(organization).data,
            status=status.HTTP_201_CREATED,
        )


class PlatformOrganizationDetailView(PlatformAdminAPIView):
    def get_object(self, pk):
        return Organization.objects.get(pk=pk)

    def get(self, request, pk):
        return Response(OrganizationSerializer(self.get_object(pk)).data)

    def patch(self, request, pk):
        organization = self.get_object(pk)
        serializer = OrganizationSerializer(organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def put(self, request, pk):
        organization = self.get_object(pk)
        serializer = OrganizationSerializer(organization, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PlatformSettingDetailView(PlatformAdminAPIView):
    def patch(self, request, key):
        value = request.data.get("value", "")
        setting = update_platform_setting(key, value, request.user)
        return Response(PlatformSettingSerializer(setting).data)


class PlatformMarkAllLeadsReadView(PlatformAdminAPIView):
    def post(self, request):
        updated = ContactLead.objects.filter(is_read=False).update(
            is_read=True,
            status=ContactLead.Status.IN_PROGRESS,
        )
        return Response({"updated": updated})


class PlatformMonitoringHealthView(PlatformAdminAPIView):
    def get(self, request):
        report = get_health_check_report(use_cache=True, include_heavy_checks=False)
        components = report.get("components", {})

        def component_status(name: str, fallback: str = "healthy") -> dict:
            item = components.get(name, {})
            return {
                "status": item.get("status", fallback),
                "latency_ms": item.get("latency_ms"),
            }

        payload = {
            "web": {"status": report.get("status", "healthy"), "latency_ms": None},
            "database": component_status("database"),
            "cache": component_status("redis"),
            "celery": component_status("celery"),
            "storage": component_status("storage", "healthy"),
            "email": component_status("email", "healthy"),
            "ai": component_status("openai", "healthy"),
            "ocr": component_status("tesseract", "healthy"),
        }
        return Response(payload)


class PlatformMonitoringMetricsView(PlatformAdminAPIView):
    def get(self, request):
        cpu_percent = 0
        memory_percent = 0
        memory_total_gb = 0
        memory_used_gb = 0

        try:
            import psutil  # type: ignore

            cpu_percent = round(float(psutil.cpu_percent(interval=0.05)), 2)
            virtual_memory = psutil.virtual_memory()
            memory_percent = round(float(virtual_memory.percent), 2)
            memory_total_gb = round(float(virtual_memory.total) / (1024**3), 2)
            memory_used_gb = round(float(virtual_memory.used) / (1024**3), 2)
        except Exception:
            pass

        disk = shutil.disk_usage(settings.BASE_DIR)
        disk_total_gb = round(float(disk.total) / (1024**3), 2)
        disk_used_gb = round(float(disk.used) / (1024**3), 2)
        disk_percent = round((disk.used / disk.total) * 100, 2) if disk.total else 0

        return Response(
            {
                "cpu_percent": cpu_percent,
                "cpu_cores": os.cpu_count() or 0,
                "memory_percent": memory_percent,
                "memory_total_gb": memory_total_gb,
                "memory_used_gb": memory_used_gb,
                "disk_percent": disk_percent,
                "disk_total_gb": disk_total_gb,
                "disk_used_gb": disk_used_gb,
            }
        )


class PlatformMonitoringErrorsView(PlatformAdminAPIView):
    def get(self, request):
        limit = max(1, min(int(request.query_params.get("limit", 10)), 50))
        error_actions = {
            ActivityLog.Action.AUDIT_FAILED,
            ActivityLog.Action.FILE_DELETED,
        }
        queryset = ActivityLog.objects.filter(action__in=error_actions).order_by("-created_at")[:limit]
        payload = [
            {
                "id": str(item.id),
                "level": "error" if item.action == ActivityLog.Action.AUDIT_FAILED else "warning",
                "message": item.description or item.get_action_display(),
                "path": f"{item.entity_type}:{item.entity_id}" if item.entity_type else "",
                "timestamp": item.created_at,
            }
            for item in queryset
        ]
        return Response(payload)


class PlatformActivityLogStatsView(PlatformAdminAPIView):
    def get(self, request):
        queryset = ActivityLog.objects.all()
        by_action = queryset.values("action").annotate(total=Count("id")).order_by("-total")[:5]
        return Response(
            {
                "total_logs": queryset.count(),
                "unique_users": queryset.exclude(user_id=None).values("user_id").distinct().count(),
                "top_actions": list(by_action),
            }
        )


class PlatformSettingListView(PlatformAdminAPIView):
    def get(self, request):
        queryset = PlatformSetting.objects.all().order_by("group", "key")
        return Response(PlatformSettingSerializer(queryset, many=True).data)


class PlatformIntroVideoCompatView(PlatformAdminAPIView):
    """Compat endpoint for the intro video editor shell."""

    FIELDS = (
        "title",
        "title_ar",
        "video_url",
        "thumbnail_url",
        "description",
        "description_ar",
        "is_active",
        "order",
    )

    def _serialize(self, obj):
        if obj is None:
            return {
                "title": "",
                "title_ar": "",
                "video_url": "",
                "thumbnail_url": "",
                "description": "",
                "description_ar": "",
                "is_active": True,
                "order": 0,
                "duration": "",
                "cta_text_ar": "",
            }

        payload = IntroVideoSerializer(obj).data
        payload.setdefault("duration", "")
        payload.setdefault("cta_text_ar", "")
        return payload

    def get(self, request):
        intro_video = IntroVideo.objects.order_by("order", "-created_at").first()
        return Response(self._serialize(intro_video))

    def put(self, request):
        intro_video = IntroVideo.objects.order_by("order", "-created_at").first() or IntroVideo(created_by=request.user)

        for field in self.FIELDS:
            if field in request.data:
                setattr(intro_video, field, request.data.get(field))

        if not intro_video.created_by_id:
            intro_video.created_by = request.user
        intro_video.save()
        return Response(self._serialize(intro_video))


class PlatformFAQCompatView(PlatformAdminAPIView):
    """Compat endpoint that keeps the current FAQ editor working under /api/platform-admin/."""

    def _serialize_item(self, item):
        return {
            "id": item.id,
            "question": item.question,
            "question_ar": item.question_ar,
            "answer": item.answer,
            "answer_ar": item.answer_ar,
            "category": item.category.name if item.category else "General",
            "order": item.order,
            "is_active": item.is_active,
        }

    def get(self, request):
        items = FAQItem.objects.select_related("category").order_by("order", "created_at")
        return Response([self._serialize_item(item) for item in items])

    def put(self, request):
        payload = request.data if isinstance(request.data, list) else []
        seen_ids = []

        for index, item in enumerate(payload, start=1):
            faq_item = FAQItem.objects.filter(pk=item.get("id")).first() if item.get("id") else FAQItem()
            category_name = str(item.get("category") or "General").strip()
            category = None

            if category_name:
                category, _ = FAQCategory.objects.get_or_create(
                    name=category_name,
                    defaults={"name_ar": category_name, "order": index, "is_active": True},
                )

            faq_item.category = category
            faq_item.question = item.get("question", "")
            faq_item.question_ar = item.get("question_ar", "")
            faq_item.answer = item.get("answer", "")
            faq_item.answer_ar = item.get("answer_ar", "")
            faq_item.order = item.get("order", index) or index
            faq_item.is_active = bool(item.get("is_active", True))
            faq_item.save()
            seen_ids.append(faq_item.id)

        queryset = FAQItem.objects.all()
        if seen_ids:
            queryset.exclude(pk__in=seen_ids).delete()
        else:
            queryset.delete()

        items = FAQItem.objects.select_related("category").order_by("order", "created_at")
        return Response([self._serialize_item(item) for item in items])


class PlatformSEOCompatView(PlatformAdminAPIView):
    """Compat endpoint that adapts the current SEO editor payload shape."""

    def _serialize(self, setting):
        if setting is None:
            return {
                "meta_title": "",
                "meta_title_ar": "",
                "meta_description": "",
                "meta_description_ar": "",
                "keywords": "",
                "og_title": "",
                "og_type": "website",
                "og_image": "",
                "canonical_url": "",
            }

        payload = SEOSettingSerializer(setting).data
        return {
            "meta_title": payload.get("meta_title", ""),
            "meta_title_ar": payload.get("meta_title_ar", ""),
            "meta_description": payload.get("meta_description", ""),
            "meta_description_ar": payload.get("meta_description_ar", ""),
            "keywords": payload.get("keywords", ""),
            "og_title": payload.get("og_title", ""),
            "og_type": "website",
            "og_image": payload.get("og_image_url", ""),
            "canonical_url": payload.get("canonical_url", ""),
        }

    def get(self, request):
        page_key = request.query_params.get("page", "home")
        setting = SEOSetting.objects.filter(page_key=page_key).first()
        return Response(self._serialize(setting))

    def post(self, request):
        page_key = request.data.get("page") or request.data.get("page_key") or "home"
        payload = {
            "meta_title": request.data.get("meta_title", ""),
            "meta_title_ar": request.data.get("meta_title_ar", ""),
            "meta_description": request.data.get("meta_description", ""),
            "meta_description_ar": request.data.get("meta_description_ar", ""),
            "keywords": request.data.get("keywords", ""),
            "og_title": request.data.get("og_title", ""),
            "og_description": request.data.get("meta_description", ""),
            "og_image_url": request.data.get("og_image") or request.data.get("og_image_url", ""),
            "canonical_url": request.data.get("canonical_url", ""),
        }
        setting = update_seo_setting(page_key, payload, request.user)
        return Response(self._serialize(setting))


# ─── Trial Users Dashboard (Phase 1, spec §B) ────────────────────────────────
#
# Every view below is staff-only via PlatformAdminAPIView (IsAuthenticated +
# IsPlatformAdmin). There is NO middleware fronting /api/platform-admin/ —
# core/namespace_access.py defines matching prefixes but is not installed in
# MIDDLEWARE — so these permission classes are the only control. Each endpoint
# has a matching permission test in tests/test_trial_dashboard.py.
#
# No endpoint here returns TrialLeadProfile.registered_ip (ADR 0004 §2).

def _trial_filters(request):
    """Read dashboard filters off the query string.

    Values are handed to apply_filters(), which validates each against a known
    set and ignores anything unrecognised — so this does no trusting of its own.
    """
    return {
        "country": request.query_params.get("country"),
        "primary_benefit": request.query_params.get("client_type"),
        "trial_status": request.query_params.get("trial_status"),
        "activity": request.query_params.get("activity"),
        "registered_from": parse_date(request.query_params.get("from") or ""),
        "registered_to": parse_date(request.query_params.get("to") or ""),
    }


class TrialUsersSummaryView(PlatformAdminAPIView):
    """The six dashboard cards. Aggregated in SQL, never in Python."""

    def get(self, request):
        queryset = get_dashboard_queryset(**_trial_filters(request))
        summary = build_summary(queryset)
        summary["filters_applied"] = {
            key: value for key, value in _trial_filters(request).items() if value
        }
        return Response(summary)


class TrialUsersListView(PlatformAdminAPIView):
    """Paginated registrant list backing the dashboard table."""

    PAGE_SIZE = 25
    MAX_PAGE_SIZE = 100

    def get(self, request):
        queryset = get_dashboard_queryset(**_trial_filters(request))

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size", self.PAGE_SIZE))
        except (TypeError, ValueError):
            page_size = self.PAGE_SIZE
        page_size = max(1, min(page_size, self.MAX_PAGE_SIZE))

        total = queryset.count()
        start = (page - 1) * page_size
        rows = [row_values(profile) for profile in queryset[start:start + page_size]]

        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": rows,
        })


class TrialUserConvertView(PlatformAdminAPIView):
    """POST — move a trial registrant onto a paid plan.

    Delegates to apps.leads.trial_conversion, which wraps the official
    SubscriptionService. No subscription field is written here.
    """

    def post(self, request, pk):
        from apps.leads.models import TrialLeadProfile
        from apps.leads.trial_conversion import (
            TrialConversionError,
            convert_trial_to_paid,
        )

        try:
            profile = TrialLeadProfile.objects.select_related(
                "user", "user__organization"
            ).get(pk=pk)
        except (TrialLeadProfile.DoesNotExist, ValidationError, ValueError):
            return Response({"detail": "Trial user not found."}, status=status.HTTP_404_NOT_FOUND)

        plan_code = (request.data.get("plan_code") or "").strip()
        if not plan_code:
            return Response(
                {"detail": "plan_code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            subscription = convert_trial_to_paid(
                actor=request.user, profile=profile,
                plan_code=plan_code, request=request,
            )
        except TrialConversionError as exc:
            # Domain refusal (already paid, no organisation) — 409, not 400:
            # the request was well-formed, the state disallows it.
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as exc:
            return Response(
                {"detail": "; ".join(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "subscription_id": str(subscription.id),
            "plan": subscription.plan.code,
            "status": subscription.status,
            "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
        }, status=status.HTTP_201_CREATED)


class TrialUsersExportXlsxView(PlatformAdminAPIView):
    """Excel export of the CURRENTLY FILTERED registrants."""

    def get(self, request):
        from apps.leads.trial_exports import export_xlsx

        return export_xlsx(get_dashboard_queryset(**_trial_filters(request)))


class TrialUsersExportPdfView(PlatformAdminAPIView):
    """PDF export of the CURRENTLY FILTERED registrants.

    503 when the renderer is unavailable — a missing system library is not a
    server fault and must not surface as a 500.
    """

    def get(self, request):
        from apps.leads.trial_exports import export_pdf

        queryset = get_dashboard_queryset(**_trial_filters(request))
        response = export_pdf(queryset, summary=build_summary(queryset))
        if response is None:
            return Response(
                {"detail": "PDF rendering is unavailable on this deployment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return response


# ─── Partner administration (Phase 2A, spec §C/§F) ───────────────────────────
#
# Staff-only via PlatformAdminAPIView. There is NO middleware on
# /api/platform-admin/ — these permission classes are the only control, and each
# endpoint has its matching permission test in tests/test_partners.py.
#
# Publish/hide are audited through log_crm_action, the same hash-chained
# AuditLog path Phase 1's trial conversion uses. No second audit mechanism.

def _partner_filters(request):
    return {
        "q": request.query_params.get("q"),
        "country": request.query_params.get("country"),
        "partner_type": request.query_params.get("partner_type"),
        "partner_tier": request.query_params.get("partner_tier"),
        "status": request.query_params.get("status"),
    }


class PartnerListCreateView(PlatformAdminAPIView):
    """GET a filtered partner list · POST a new partner (Draft by default)."""

    def get(self, request):
        from apps.partners.selectors import admin_row, list_partners_for_admin

        queryset = list_partners_for_admin(**_partner_filters(request))
        return Response({
            "count": queryset.count(),
            "results": [admin_row(p) for p in queryset],
        })

    def post(self, request):
        from apps.partners.serializers import PartnerAdminSerializer

        serializer = PartnerAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner = serializer.save()
        return Response(
            PartnerAdminSerializer(partner).data, status=status.HTTP_201_CREATED
        )


class PartnerDetailView(PlatformAdminAPIView):
    """GET / PATCH a single partner. Status is not editable here — use the
    publish and hide endpoints, which are audited."""

    def _get(self, pk):
        from apps.partners.models import Partner

        try:
            return Partner.objects.get(pk=pk)
        except (Partner.DoesNotExist, ValidationError, ValueError):
            return None

    def get(self, request, pk):
        from apps.partners.serializers import PartnerAdminSerializer

        partner = self._get(pk)
        if partner is None:
            return Response({"detail": "Partner not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PartnerAdminSerializer(partner).data)

    def patch(self, request, pk):
        from apps.partners.serializers import PartnerAdminSerializer

        partner = self._get(pk)
        if partner is None:
            return Response({"detail": "Partner not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PartnerAdminSerializer(partner, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PartnerPublishView(PlatformAdminAPIView):
    """POST — make a partner public. Audited."""

    def post(self, request, pk):
        from apps.partners.services import PartnerVisibilityError, publish_partner

        try:
            partner = publish_partner(pk=pk, actor=request.user, request=request)
        except PartnerVisibilityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "id": str(partner.id),
            "status": partner.status,
            "published_at": partner.published_at.isoformat() if partner.published_at else None,
        })


class PartnerHideView(PlatformAdminAPIView):
    """POST — remove a partner from public surfaces. Audited.

    Does NOT clear published_at: the first-publication date stays available.
    """

    def post(self, request, pk):
        from apps.partners.services import PartnerVisibilityError, hide_partner

        try:
            partner = hide_partner(pk=pk, actor=request.user, request=request)
        except PartnerVisibilityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "id": str(partner.id),
            "status": partner.status,
            "published_at": partner.published_at.isoformat() if partner.published_at else None,
        })


class PartnerReorderView(PlatformAdminAPIView):
    """POST — set display_order for several partners at once."""

    def post(self, request):
        from apps.partners.services import reorder_partners

        entries = request.data.get("order")
        if not isinstance(entries, list) or not entries:
            return Response(
                {"detail": "order must be a non-empty list of {id, display_order}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            updated = reorder_partners(entries)
        except (ValidationError, ValueError, TypeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"updated": updated})


# ─── Partner application review (Phase 2B, §E.7/§F) ──────────────────────────
#
# Staff-only, like everything on this prefix. Applications have NO public read
# surface — this is the only way to see one.

def _application_filters(request):
    return {
        "q": request.query_params.get("q"),
        "country": request.query_params.get("country"),
        "requested_partner_type": request.query_params.get("requested_partner_type"),
        "status": request.query_params.get("status"),
    }


class PartnerApplicationListView(PlatformAdminAPIView):
    """GET applications with search and filters."""

    def get(self, request):
        from apps.partners.selectors import application_row, list_applications_for_admin

        queryset = list_applications_for_admin(**_application_filters(request))
        return Response({
            "count": queryset.count(),
            "results": [application_row(a) for a in queryset],
        })


class PartnerApplicationDetailView(PlatformAdminAPIView):
    """GET one application, with attachment metadata and internal notes."""

    def get(self, request, pk):
        from apps.partners.models import PartnerApplication
        from apps.partners.serializers import PartnerApplicationAdminSerializer

        try:
            application = PartnerApplication.objects.prefetch_related(
                "attachments", "notes"
            ).get(pk=pk)
        except (PartnerApplication.DoesNotExist, ValidationError, ValueError):
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(PartnerApplicationAdminSerializer(application).data)


class PartnerApplicationTransitionView(PlatformAdminAPIView):
    """POST a state transition. Legality is enforced in the service layer."""

    def post(self, request, pk, action):
        from apps.partners.services import (
            ApplicationTransitionError,
            PartnerVisibilityError,
            approve_application,
            reject_application,
            start_review,
        )

        try:
            if action == "review":
                application = start_review(pk=pk, actor=request.user, request=request)
                payload = {"status": application.status}
            elif action == "approve":
                application, partner = approve_application(
                    pk=pk, actor=request.user,
                    partner_tier=request.data.get("partner_tier"),
                    partner_type=request.data.get("partner_type"),
                    request=request,
                )
                payload = {
                    "status": application.status,
                    "partner_id": str(partner.id),
                    "partner_slug": partner.slug,
                    "partner_status": partner.status,
                }
            elif action == "reject":
                application = reject_application(
                    pk=pk, actor=request.user,
                    reason=request.data.get("reason", ""), request=request,
                )
                payload = {"status": application.status}
            else:
                return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
        except PartnerVisibilityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ApplicationTransitionError as exc:
            # Well-formed request, illegal in the current state → 409.
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as exc:
            return Response(
                {"detail": "; ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(payload)


class PartnerApplicationNoteView(PlatformAdminAPIView):
    """POST an internal reviewer note. Never served publicly."""

    def post(self, request, pk):
        from apps.partners.services import PartnerVisibilityError, add_note

        try:
            note = add_note(pk=pk, actor=request.user, note=request.data.get("note", ""))
        except PartnerVisibilityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response(
                {"detail": "; ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"id": str(note.id), "note": note.note,
             "created_at": note.created_at.isoformat()},
            status=status.HTTP_201_CREATED,
        )


class PartnerApplicationExportXlsxView(PlatformAdminAPIView):
    """Excel export of the CURRENTLY FILTERED applications."""

    def get(self, request):
        from apps.partners.exports import export_applications_xlsx
        from apps.partners.selectors import list_applications_for_admin

        return export_applications_xlsx(
            list_applications_for_admin(**_application_filters(request))
        )


class PartnerApplicationExportPdfView(PlatformAdminAPIView):
    """PDF export of the CURRENTLY FILTERED applications."""

    def get(self, request):
        from apps.partners.exports import export_applications_pdf
        from apps.partners.selectors import list_applications_for_admin

        response = export_applications_pdf(
            list_applications_for_admin(**_application_filters(request))
        )
        if response is None:
            return Response(
                {"detail": "PDF rendering is unavailable on this deployment."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return response


# ── Billing policy (Phase 3B D3) ────────────────────────────────────────────
class BillingPolicyView(APIView):
    """Read and change the platform's rollover policy.

    Staff-only and never publicly readable: this governs what happens to credit
    customers have paid for, which is why it is not a `cms.PlatformSetting`
    (that table carries an `is_public` flag). Every change is audited through
    `log_crm_action`.
    """

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.billing.choices import RolloverPolicy
        from apps.billing.services.rollover import RolloverService

        policy = RolloverService().get_policy()
        return Response({
            "invoice_credit_rollover": policy.invoice_credit_rollover,
            "effective_from": policy.effective_from,
            "updated_by": getattr(policy.updated_by, "email", None),
            "choices": [
                {"value": v, "label": str(l)} for v, l in RolloverPolicy.choices
            ],
        })

    def patch(self, request):
        from apps.billing.services.rollover import RolloverService

        value = (request.data or {}).get("invoice_credit_rollover")
        if not value:
            return Response(
                {"detail": "invoice_credit_rollover is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            policy = RolloverService().set_policy(
                value=value,
                actor=request.user,
                request=request,
                reason=(request.data or {}).get("reason", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "invoice_credit_rollover": policy.invoice_credit_rollover,
            "effective_from": policy.effective_from,
        })
