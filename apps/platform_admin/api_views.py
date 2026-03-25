"""Platform admin API views for the split admin console."""

from __future__ import annotations

import os
import shutil

from django.conf import settings
from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import Organization
from apps.authentication.serializers import OrganizationSerializer
from apps.cms.models import CMSPage, FAQCategory, FAQItem, IntroVideo, MediaAsset, PlatformSetting, SEOSetting
from apps.cms.serializers import IntroVideoSerializer, PlatformSettingSerializer, SEOSettingSerializer
from apps.cms.services import update_platform_setting, update_seo_setting
from apps.jobs.models import JobPost
from apps.leads.models import ContactLead
from core.permissions import IsPlatformAdmin
from core.services.monitoring import get_health_check_report


class PlatformAdminAPIView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]


class PlatformDashboardStatsView(PlatformAdminAPIView):
    def get(self, request):
        pages = CMSPage.objects.all()
        return Response(
            {
                "total_organizations": Organization.objects.count(),
                "active_jobs": JobPost.objects.filter(status=JobPost.Status.PUBLISHED).count(),
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
