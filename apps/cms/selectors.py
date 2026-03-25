from __future__ import annotations

from typing import Optional

from django.db.models import Prefetch, QuerySet

from .models import (
    AboutSection,
    CMSPage,
    CompetitiveAdvantage,
    CoreValue,
    FAQCategory,
    FAQItem,
    HomepageContent,
    IntroVideo,
    MediaAsset,
    PlatformSetting,
    PricingFeature,
    PricingPlan,
    SEOSetting,
    Service,
)


def get_homepage_content() -> Optional[HomepageContent]:
    """Return the active homepage content singleton, or None if not configured."""
    return HomepageContent.objects.filter(is_active=True).order_by("-id").first()


def get_intro_videos(active_only: bool = True) -> QuerySet:
    """Return intro videos ordered by their display order."""
    qs = IntroVideo.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order", "-created_at")


def get_about_section() -> Optional[AboutSection]:
    """Return the active about section singleton, or None if not configured."""
    return AboutSection.objects.filter(is_active=True).order_by("-id").first()


def get_core_values(active_only: bool = True) -> QuerySet:
    """Return core values ordered by display order."""
    qs = CoreValue.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order")


def get_competitive_advantages(active_only: bool = True) -> QuerySet:
    """Return competitive advantages ordered by display order."""
    qs = CompetitiveAdvantage.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order")


def get_services(active_only: bool = True) -> QuerySet:
    """Return services ordered by display order."""
    qs = Service.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order")


def get_pricing_plans(active_only: bool = True) -> QuerySet:
    """Return pricing plans with prefetched features."""
    qs = PricingPlan.objects.prefetch_related(
        Prefetch("features", queryset=PricingFeature.objects.order_by("order"))
    )
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order")


def get_faq_categories(active_only: bool = True) -> QuerySet:
    """Return FAQ categories ordered by display order."""
    qs = FAQCategory.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order")


def get_faq_items(
    category_id: Optional[int] = None, active_only: bool = True
) -> QuerySet:
    """Return FAQ items, optionally filtered by category."""
    qs = FAQItem.objects.select_related("category")
    if active_only:
        qs = qs.filter(is_active=True)
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    return qs.order_by("order")


def get_seo_setting(page_key: str) -> Optional[SEOSetting]:
    """Return SEO settings for the given page key, or None."""
    return SEOSetting.objects.filter(page_key=page_key).first()


def get_cms_pages(status: Optional[str] = None) -> QuerySet:
    """Return CMS pages, optionally filtered by status."""
    qs = CMSPage.objects.select_related("created_by", "published_by")
    if status is not None:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def get_cms_page_by_slug(slug: str) -> Optional[CMSPage]:
    """Return a CMS page by its slug with prefetched blocks."""
    from .models import CMSBlock
    return (
        CMSPage.objects.prefetch_related(
            Prefetch("blocks", queryset=CMSBlock.objects.order_by("order"))
        )
        .select_related("created_by", "published_by")
        .filter(slug=slug)
        .first()
    )


def get_platform_settings(
    group: Optional[str] = None, public_only: bool = False
) -> QuerySet:
    """Return platform settings, optionally filtered by group or public flag."""
    qs = PlatformSetting.objects.all()
    if group is not None:
        qs = qs.filter(group=group)
    if public_only:
        qs = qs.filter(is_public=True)
    return qs.order_by("group", "key")


def get_media_assets(file_type: Optional[str] = None) -> QuerySet:
    """Return media assets ordered by creation date, optionally filtered by type."""
    qs = MediaAsset.objects.select_related("uploaded_by")
    if file_type is not None:
        qs = qs.filter(file_type=file_type)
    return qs.order_by("-created_at")
