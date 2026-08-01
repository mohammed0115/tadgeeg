from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.feature_flags import JOBS_DISABLED_COUNT, jobs_enabled
from core.permissions import is_platform_user

from .exceptions import (
    CMSError,
    ContentNotFoundError,
    DuplicateSlugError,
    PagePublishError,
)
from .models import CMSPage, CompetitiveAdvantage, CoreValue, SEOSetting
from .selectors import (
    get_about_section,
    get_cms_page_by_slug,
    get_cms_pages,
    get_competitive_advantages,
    get_core_values,
    get_faq_categories,
    get_faq_items,
    get_homepage_content,
    get_intro_videos,
    get_media_assets,
    get_platform_settings,
    get_pricing_plans,
    get_seo_setting,
    get_services,
)
from .serializers import (
    AboutSectionSerializer,
    CMSBlockSerializer,
    CMSPageSerializer,
    CompetitiveAdvantageSerializer,
    CoreValueSerializer,
    FAQCategorySerializer,
    FAQItemSerializer,
    HomepageContentSerializer,
    IntroVideoSerializer,
    MediaAssetSerializer,
    PlatformSettingSerializer,
    PricingFeatureSerializer,
    PricingPlanSerializer,
    SEOSettingSerializer,
    ServiceSerializer,
)
from .services import (
    add_pricing_feature,
    archive_cms_page,
    bulk_update_platform_settings,
    create_cms_page,
    create_faq_category,
    create_faq_item,
    create_media_asset,
    create_or_update_competitive_advantage,
    create_or_update_core_value,
    create_or_update_intro_video,
    create_or_update_service,
    create_pricing_plan,
    delete_competitive_advantage,
    delete_core_value,
    delete_faq_item,
    delete_intro_video,
    delete_media_asset,
    delete_pricing_plan,
    delete_service,
    publish_cms_page,
    remove_pricing_feature,
    update_about_section,
    update_cms_page,
    update_faq_category,
    update_faq_item,
    update_homepage_content,
    update_platform_setting,
    update_pricing_plan,
    update_seo_setting,
)


def _is_cms_admin(user) -> bool:
    """Platform authority check for the CMS admin surface.

    This used to accept ``user.role == "admin"`` as well as ``is_staff``. That
    was a privilege-escalation hole: ``User.Role.ADMIN`` is an *organization*
    role, not platform authority, and every self-service registrant is granted
    it (apps/authentication/serializers.py — ``validated_data["role"] =
    User.Role.ADMIN``). ``CMSAdminPermission`` was therefore equivalent to
    ``IsAuthenticated`` for any customer who signed up.

    The project already draws the org/platform line in core.permissions:
    ``is_org_member`` is explicitly "has an organization AND is NOT a platform
    user", and ``LEGACY_ORG_ADMIN_ROLES`` classifies "admin" as an org role.
    So we defer to ``is_platform_user`` (is_staff or is_superuser) — the same
    predicate ``IsPlatformAdmin`` uses, which keeps the whole
    ``/api/platform-admin/`` surface on one consistent rule.

    Registration is NOT changed: granting the org owner ``Role.ADMIN`` is
    correct and load-bearing for owner detection, ``effective_role`` and
    ``is_org_admin``.
    """
    return is_platform_user(user)


class CMSAdminPermission(IsAuthenticated):
    """Allow access only to platform staff (is_staff or is_superuser)."""

    def has_permission(self, request, view) -> bool:
        return bool(
            super().has_permission(request, view)
            and _is_cms_admin(request.user)
        )


# ---------------------------------------------------------------------------
# Admin — Homepage
# ---------------------------------------------------------------------------

class HomepageContentView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        obj = get_homepage_content()
        if obj is None:
            return Response({}, status=status.HTTP_200_OK)
        return Response(HomepageContentSerializer(obj).data)

    def put(self, request):
        obj = update_homepage_content(request.data, request.user)
        return Response(HomepageContentSerializer(obj).data)


# ---------------------------------------------------------------------------
# Admin — Intro Videos
# ---------------------------------------------------------------------------

class IntroVideoListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_intro_videos(active_only=False)
        return Response(IntroVideoSerializer(qs, many=True).data)

    def post(self, request):
        obj = create_or_update_intro_video(None, request.data, request.user)
        return Response(IntroVideoSerializer(obj).data, status=status.HTTP_201_CREATED)


class IntroVideoDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request, pk):
        from .models import IntroVideo
        try:
            obj = IntroVideo.objects.get(pk=pk)
        except IntroVideo.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(IntroVideoSerializer(obj).data)

    def put(self, request, pk):
        try:
            obj = create_or_update_intro_video(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(IntroVideoSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_intro_video(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — About Section
# ---------------------------------------------------------------------------

class AboutSectionView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        obj = get_about_section()
        if obj is None:
            return Response({}, status=status.HTTP_200_OK)
        return Response(AboutSectionSerializer(obj).data)

    def put(self, request):
        obj = update_about_section(request.data, request.user)
        return Response(AboutSectionSerializer(obj).data)


# ---------------------------------------------------------------------------
# Admin — Core Values
# ---------------------------------------------------------------------------

class CoreValueListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_core_values(active_only=False)
        return Response(CoreValueSerializer(qs, many=True).data)

    def post(self, request):
        obj = create_or_update_core_value(None, request.data, request.user)
        return Response(CoreValueSerializer(obj).data, status=status.HTTP_201_CREATED)


class CoreValueDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def put(self, request, pk):
        try:
            obj = create_or_update_core_value(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(CoreValueSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_core_value(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — Competitive Advantages
# ---------------------------------------------------------------------------

class CompetitiveAdvantageListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_competitive_advantages(active_only=False)
        return Response(CompetitiveAdvantageSerializer(qs, many=True).data)

    def post(self, request):
        obj = create_or_update_competitive_advantage(None, request.data, request.user)
        return Response(CompetitiveAdvantageSerializer(obj).data, status=status.HTTP_201_CREATED)


class CompetitiveAdvantageDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def put(self, request, pk):
        try:
            obj = create_or_update_competitive_advantage(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(CompetitiveAdvantageSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_competitive_advantage(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — Services
# ---------------------------------------------------------------------------

class ServiceListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_services(active_only=False)
        return Response(ServiceSerializer(qs, many=True).data)

    def post(self, request):
        obj = create_or_update_service(None, request.data, request.user)
        return Response(ServiceSerializer(obj).data, status=status.HTTP_201_CREATED)


class ServiceDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def put(self, request, pk):
        try:
            obj = create_or_update_service(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(ServiceSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_service(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — Pricing Plans
# ---------------------------------------------------------------------------

class PricingPlanListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_pricing_plans(active_only=False)
        return Response(PricingPlanSerializer(qs, many=True).data)

    def post(self, request):
        try:
            obj = create_pricing_plan(request.data, request.user)
        except DuplicateSlugError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(PricingPlanSerializer(obj).data, status=status.HTTP_201_CREATED)


class PricingPlanDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request, pk):
        from .models import PricingPlan
        try:
            obj = PricingPlan.objects.prefetch_related("features").get(pk=pk)
        except PricingPlan.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PricingPlanSerializer(obj).data)

    def put(self, request, pk):
        try:
            obj = update_pricing_plan(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DuplicateSlugError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(PricingPlanSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_pricing_plan(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PricingFeatureCreateView(APIView):
    """POST /admin/pricing-plans/<plan_id>/features/"""
    permission_classes = [CMSAdminPermission]

    def post(self, request, plan_id):
        try:
            obj = add_pricing_feature(plan_id, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(PricingFeatureSerializer(obj).data, status=status.HTTP_201_CREATED)


class PricingFeatureDeleteView(APIView):
    """DELETE /admin/pricing-features/<pk>/"""
    permission_classes = [CMSAdminPermission]

    def delete(self, request, pk):
        try:
            remove_pricing_feature(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — FAQ
# ---------------------------------------------------------------------------

class FAQCategoryListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = get_faq_categories(active_only=False)
        return Response(FAQCategorySerializer(qs, many=True).data)

    def post(self, request):
        obj = create_faq_category(request.data, request.user)
        return Response(FAQCategorySerializer(obj).data, status=status.HTTP_201_CREATED)


class FAQCategoryDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def put(self, request, pk):
        try:
            obj = update_faq_category(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(FAQCategorySerializer(obj).data)

    def delete(self, request, pk):
        from .models import FAQCategory
        try:
            obj = FAQCategory.objects.get(pk=pk)
        except FAQCategory.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FAQItemListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        category_id = request.query_params.get("category")
        qs = get_faq_items(
            category_id=int(category_id) if category_id else None,
            active_only=False,
        )
        return Response(FAQItemSerializer(qs, many=True).data)

    def post(self, request):
        try:
            obj = create_faq_item(request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(FAQItemSerializer(obj).data, status=status.HTTP_201_CREATED)


class FAQItemDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def put(self, request, pk):
        try:
            obj = update_faq_item(pk, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(FAQItemSerializer(obj).data)

    def delete(self, request, pk):
        try:
            delete_faq_item(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — SEO Settings
# ---------------------------------------------------------------------------

class SEOSettingListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        qs = SEOSetting.objects.all().order_by("page_key")
        return Response(SEOSettingSerializer(qs, many=True).data)


class SEOSettingDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request, page_key):
        obj = get_seo_setting(page_key)
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SEOSettingSerializer(obj).data)

    def put(self, request, page_key):
        obj = update_seo_setting(page_key, request.data, request.user)
        return Response(SEOSettingSerializer(obj).data)


# ---------------------------------------------------------------------------
# Admin — Platform Settings
# ---------------------------------------------------------------------------

class PlatformSettingListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        group = request.query_params.get("group")
        qs = get_platform_settings(group=group)
        return Response(PlatformSettingSerializer(qs, many=True).data)

    def put(self, request):
        """Bulk update: expects {"settings": {"key": "value", ...}}"""
        settings_dict = request.data.get("settings", {})
        if not isinstance(settings_dict, dict):
            return Response(
                {"detail": "Expected {'settings': {key: value, ...}}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            updated = bulk_update_platform_settings(settings_dict, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(PlatformSettingSerializer(updated, many=True).data)


# ---------------------------------------------------------------------------
# Admin — Media Assets
# ---------------------------------------------------------------------------

class MediaAssetListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        file_type = request.query_params.get("file_type")
        qs = get_media_assets(file_type=file_type)
        return Response(MediaAssetSerializer(qs, many=True).data)

    def post(self, request):
        obj = create_media_asset(request.data, request.user)
        return Response(MediaAssetSerializer(obj).data, status=status.HTTP_201_CREATED)


class MediaAssetDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def delete(self, request, pk):
        try:
            delete_media_asset(pk, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin — CMS Pages
# ---------------------------------------------------------------------------

class CMSPageListView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        page_status = request.query_params.get("status")
        qs = get_cms_pages(status=page_status)
        return Response(CMSPageSerializer(qs, many=True).data)

    def post(self, request):
        try:
            obj = create_cms_page(request.data, request.user)
        except DuplicateSlugError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(CMSPageSerializer(obj).data, status=status.HTTP_201_CREATED)


class CMSPageDetailView(APIView):
    permission_classes = [CMSAdminPermission]

    def get(self, request, slug):
        obj = get_cms_page_by_slug(slug)
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CMSPageSerializer(obj).data)

    def put(self, request, slug):
        try:
            obj = update_cms_page(slug, request.data, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DuplicateSlugError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(CMSPageSerializer(obj).data)

    def delete(self, request, slug):
        obj = get_cms_page_by_slug(slug)
        if obj is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CMSPagePublishView(APIView):
    permission_classes = [CMSAdminPermission]

    def post(self, request, slug):
        try:
            obj = publish_cms_page(slug, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except PagePublishError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CMSPageSerializer(obj).data)


class CMSPageArchiveView(APIView):
    permission_classes = [CMSAdminPermission]

    def post(self, request, slug):
        try:
            obj = archive_cms_page(slug, request.user)
        except ContentNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(CMSPageSerializer(obj).data)


# ---------------------------------------------------------------------------
# Public Views
# ---------------------------------------------------------------------------

class PublicHomepageView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        obj = get_homepage_content()
        if obj is None:
            return Response({"detail": "Homepage content not configured."}, status=status.HTTP_404_NOT_FOUND)
        serializer = HomepageContentSerializer(obj)
        data = serializer.data
        # Expose only public-facing fields
        return Response({
            "hero_title": data.get("hero_title"),
            "hero_title_ar": data.get("hero_title_ar"),
            "hero_subtitle": data.get("hero_subtitle"),
            "hero_subtitle_ar": data.get("hero_subtitle_ar"),
            "hero_cta_primary_text": data.get("hero_cta_primary_text"),
            "hero_cta_primary_url": data.get("hero_cta_primary_url"),
            "hero_cta_secondary_text": data.get("hero_cta_secondary_text"),
            "hero_cta_secondary_url": data.get("hero_cta_secondary_url"),
            "hero_image_url": data.get("hero_image_url"),
            "stats": data.get("stats"),
            "trusted_by_logos": data.get("trusted_by_logos"),
        })


class PublicServicesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = get_services(active_only=True)
        return Response(ServiceSerializer(qs, many=True).data)


class PublicPricingView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = get_pricing_plans(active_only=True)
        return Response(PricingPlanSerializer(qs, many=True).data)


class PublicFAQView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        categories = get_faq_categories(active_only=True)
        data = []
        for cat in categories:
            items = get_faq_items(category_id=cat.pk, active_only=True)
            data.append({
                "id": cat.pk,
                "name": cat.name,
                "name_ar": cat.name_ar,
                "order": cat.order,
                "items": FAQItemSerializer(items, many=True).data,
            })
        # Also include uncategorized items
        uncategorized = get_faq_items(category_id=None, active_only=True).filter(category__isnull=True)
        if uncategorized.exists():
            data.append({
                "id": None,
                "name": "General",
                "name_ar": "عام",
                "order": 9999,
                "items": FAQItemSerializer(uncategorized, many=True).data,
            })
        return Response(data)


class PublicAboutView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        about = get_about_section()
        core_values = get_core_values(active_only=True)
        advantages = get_competitive_advantages(active_only=True)
        return Response({
            "about": AboutSectionSerializer(about).data if about else None,
            "core_values": CoreValueSerializer(core_values, many=True).data,
            "competitive_advantages": CompetitiveAdvantageSerializer(advantages, many=True).data,
        })


class PublicSEOView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        page_key = request.query_params.get("page", "home")
        obj = get_seo_setting(page_key)
        if obj is None:
            return Response({"detail": f"No SEO settings for page '{page_key}'."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SEOSettingSerializer(obj).data)


class PublicPlatformSettingsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = get_platform_settings(public_only=True)
        return Response(PlatformSettingSerializer(qs, many=True).data)


# ---------------------------------------------------------------------------
# Admin — Dashboard Stats
# ---------------------------------------------------------------------------

class CMSDashboardStatsView(APIView):
    """Aggregate stats for the CMS admin dashboard overview."""
    permission_classes = [CMSAdminPermission]

    def get(self, request):
        from apps.cms.models import (
            CMSPage, MediaAsset, PricingPlan, Service, FAQItem,
        )
        from apps.leads.models import ContactLead

        # apps.jobs is quarantined (not in INSTALLED_APPS). Importing its
        # models raises RuntimeError, so we must not import them at all — not
        # even lazily. Keys stay in the payload so the response shape is
        # unchanged for existing clients; values are None (not 0) because
        # "unknown, feature off" is not the same claim as "zero jobs".
        jobs_on = jobs_enabled()

        pages_qs = CMSPage.objects.all()
        return Response({
            "total_pages": pages_qs.count(),
            "published_pages": pages_qs.filter(status="published").count(),
            "draft_pages": pages_qs.filter(status="draft").count(),
            "archived_pages": pages_qs.filter(status="archived").count(),
            "jobs_feature_enabled": jobs_on,
            "active_jobs": JOBS_DISABLED_COUNT,
            "total_applications": JOBS_DISABLED_COUNT,
            "new_leads": ContactLead.objects.filter(status="new").count(),
            "unread_leads": ContactLead.objects.filter(is_read=False).count(),
            "total_leads": ContactLead.objects.count(),
            "media_assets": MediaAsset.objects.count(),
            "active_services": Service.objects.filter(is_active=True).count(),
            "active_pricing_plans": PricingPlan.objects.filter(is_active=True).count(),
            "active_faq_items": FAQItem.objects.filter(is_active=True).count(),
        })
