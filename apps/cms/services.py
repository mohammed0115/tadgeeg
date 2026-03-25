from __future__ import annotations

from typing import Optional

from django.utils import timezone

from apps.activity_logs.service import ActivityLogService

from .exceptions import ContentNotFoundError, DuplicateSlugError, MediaAssetError, PagePublishError
from .models import (
    AboutSection,
    CMSBlock,
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


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------

def update_homepage_content(data: dict, user) -> HomepageContent:
    obj, created = HomepageContent.objects.get_or_create(
        defaults={
            "hero_title": data.get("hero_title", ""),
            "is_active": True,
        }
    )
    allowed_fields = [
        "hero_title", "hero_title_ar", "hero_subtitle", "hero_subtitle_ar",
        "hero_cta_primary_text", "hero_cta_primary_url",
        "hero_cta_secondary_text", "hero_cta_secondary_url",
        "hero_image_url", "stats", "trusted_by_logos", "is_active",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.updated_by = user
    obj.save()
    ActivityLogService.log(
        action="cms.homepage.update",
        user=user,
        entity_type="HomepageContent",
        entity_id=str(obj.pk),
        description=f"Homepage content {'created' if created else 'updated'} by {user}",
    )
    return obj


# ---------------------------------------------------------------------------
# Intro Videos
# ---------------------------------------------------------------------------

def create_or_update_intro_video(video_id: Optional[int], data: dict, user) -> IntroVideo:
    if video_id:
        try:
            obj = IntroVideo.objects.get(pk=video_id)
        except IntroVideo.DoesNotExist:
            raise ContentNotFoundError(f"IntroVideo {video_id} not found")
        created = False
    else:
        obj = IntroVideo(created_by=user)
        created = True

    allowed_fields = [
        "title", "title_ar", "video_url", "thumbnail_url",
        "description", "description_ar", "is_active", "order",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.intro_video.create" if created else "cms.intro_video.update",
        user=user,
        entity_type="IntroVideo",
        entity_id=str(obj.pk),
        description=f"IntroVideo '{obj.title}' {'created' if created else 'updated'}",
    )
    return obj


def delete_intro_video(video_id: int, user) -> None:
    try:
        obj = IntroVideo.objects.get(pk=video_id)
    except IntroVideo.DoesNotExist:
        raise ContentNotFoundError(f"IntroVideo {video_id} not found")
    title = obj.title
    obj.delete()
    ActivityLogService.log(
        action="cms.intro_video.delete",
        user=user,
        entity_type="IntroVideo",
        entity_id=str(video_id),
        description=f"IntroVideo '{title}' deleted",
    )


# ---------------------------------------------------------------------------
# About Section
# ---------------------------------------------------------------------------

def update_about_section(data: dict, user) -> AboutSection:
    obj, created = AboutSection.objects.get_or_create(
        defaults={
            "title": data.get("title", ""),
            "is_active": True,
        }
    )
    allowed_fields = [
        "title", "title_ar", "subtitle", "subtitle_ar",
        "content", "content_ar", "image_url",
        "mission", "mission_ar", "vision", "vision_ar",
        "stats", "is_active",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.updated_by = user
    obj.save()
    ActivityLogService.log(
        action="cms.about.update",
        user=user,
        entity_type="AboutSection",
        entity_id=str(obj.pk),
        description=f"About section {'created' if created else 'updated'}",
    )
    return obj


# ---------------------------------------------------------------------------
# Core Values
# ---------------------------------------------------------------------------

def create_or_update_core_value(value_id: Optional[int], data: dict, user) -> CoreValue:
    if value_id:
        try:
            obj = CoreValue.objects.get(pk=value_id)
        except CoreValue.DoesNotExist:
            raise ContentNotFoundError(f"CoreValue {value_id} not found")
        created = False
    else:
        obj = CoreValue()
        created = True

    allowed_fields = ["title", "title_ar", "description", "description_ar", "icon", "order", "is_active"]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.core_value.create" if created else "cms.core_value.update",
        user=user,
        entity_type="CoreValue",
        entity_id=str(obj.pk),
        description=f"CoreValue '{obj.title}' {'created' if created else 'updated'}",
    )
    return obj


def delete_core_value(value_id: int, user) -> None:
    try:
        obj = CoreValue.objects.get(pk=value_id)
    except CoreValue.DoesNotExist:
        raise ContentNotFoundError(f"CoreValue {value_id} not found")
    title = obj.title
    obj.delete()
    ActivityLogService.log(
        action="cms.core_value.delete",
        user=user,
        entity_type="CoreValue",
        entity_id=str(value_id),
        description=f"CoreValue '{title}' deleted",
    )


# ---------------------------------------------------------------------------
# Competitive Advantages
# ---------------------------------------------------------------------------

def create_or_update_competitive_advantage(adv_id: Optional[int], data: dict, user) -> CompetitiveAdvantage:
    if adv_id:
        try:
            obj = CompetitiveAdvantage.objects.get(pk=adv_id)
        except CompetitiveAdvantage.DoesNotExist:
            raise ContentNotFoundError(f"CompetitiveAdvantage {adv_id} not found")
        created = False
    else:
        obj = CompetitiveAdvantage()
        created = True

    allowed_fields = ["title", "title_ar", "description", "description_ar", "icon", "order", "is_active"]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.competitive_advantage.create" if created else "cms.competitive_advantage.update",
        user=user,
        entity_type="CompetitiveAdvantage",
        entity_id=str(obj.pk),
        description=f"CompetitiveAdvantage '{obj.title}' {'created' if created else 'updated'}",
    )
    return obj


def delete_competitive_advantage(adv_id: int, user) -> None:
    try:
        obj = CompetitiveAdvantage.objects.get(pk=adv_id)
    except CompetitiveAdvantage.DoesNotExist:
        raise ContentNotFoundError(f"CompetitiveAdvantage {adv_id} not found")
    title = obj.title
    obj.delete()
    ActivityLogService.log(
        action="cms.competitive_advantage.delete",
        user=user,
        entity_type="CompetitiveAdvantage",
        entity_id=str(adv_id),
        description=f"CompetitiveAdvantage '{title}' deleted",
    )


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def create_or_update_service(service_id: Optional[int], data: dict, user) -> Service:
    if service_id:
        try:
            obj = Service.objects.get(pk=service_id)
        except Service.DoesNotExist:
            raise ContentNotFoundError(f"Service {service_id} not found")
        created = False
    else:
        obj = Service()
        created = True

    allowed_fields = [
        "title", "title_ar", "description", "description_ar",
        "icon", "features", "features_ar", "order", "is_active",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.service.create" if created else "cms.service.update",
        user=user,
        entity_type="Service",
        entity_id=str(obj.pk),
        description=f"Service '{obj.title}' {'created' if created else 'updated'}",
    )
    return obj


def delete_service(service_id: int, user) -> None:
    try:
        obj = Service.objects.get(pk=service_id)
    except Service.DoesNotExist:
        raise ContentNotFoundError(f"Service {service_id} not found")
    title = obj.title
    obj.delete()
    ActivityLogService.log(
        action="cms.service.delete",
        user=user,
        entity_type="Service",
        entity_id=str(service_id),
        description=f"Service '{title}' deleted",
    )


# ---------------------------------------------------------------------------
# Pricing Plans
# ---------------------------------------------------------------------------

def create_pricing_plan(data: dict, user) -> PricingPlan:
    slug = data.get("slug", "")
    if PricingPlan.objects.filter(slug=slug).exists():
        raise DuplicateSlugError(f"PricingPlan with slug '{slug}' already exists")

    allowed_fields = [
        "name", "name_ar", "slug", "description", "description_ar",
        "price_monthly", "price_annual", "currency",
        "max_users", "max_invoices", "max_storage_gb",
        "is_featured", "is_active", "cta_text", "cta_url", "order",
    ]
    kwargs = {f: data[f] for f in allowed_fields if f in data}
    obj = PricingPlan.objects.create(**kwargs)
    ActivityLogService.log(
        action="cms.pricing_plan.create",
        user=user,
        entity_type="PricingPlan",
        entity_id=str(obj.pk),
        description=f"PricingPlan '{obj.name}' created",
    )
    return obj


def update_pricing_plan(plan_id: int, data: dict, user) -> PricingPlan:
    try:
        obj = PricingPlan.objects.get(pk=plan_id)
    except PricingPlan.DoesNotExist:
        raise ContentNotFoundError(f"PricingPlan {plan_id} not found")

    new_slug = data.get("slug")
    if new_slug and new_slug != obj.slug and PricingPlan.objects.filter(slug=new_slug).exists():
        raise DuplicateSlugError(f"PricingPlan with slug '{new_slug}' already exists")

    allowed_fields = [
        "name", "name_ar", "slug", "description", "description_ar",
        "price_monthly", "price_annual", "currency",
        "max_users", "max_invoices", "max_storage_gb",
        "is_featured", "is_active", "cta_text", "cta_url", "order",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.pricing_plan.update",
        user=user,
        entity_type="PricingPlan",
        entity_id=str(obj.pk),
        description=f"PricingPlan '{obj.name}' updated",
    )
    return obj


def delete_pricing_plan(plan_id: int, user) -> None:
    try:
        obj = PricingPlan.objects.get(pk=plan_id)
    except PricingPlan.DoesNotExist:
        raise ContentNotFoundError(f"PricingPlan {plan_id} not found")
    name = obj.name
    obj.delete()
    ActivityLogService.log(
        action="cms.pricing_plan.delete",
        user=user,
        entity_type="PricingPlan",
        entity_id=str(plan_id),
        description=f"PricingPlan '{name}' deleted",
    )


def add_pricing_feature(plan_id: int, data: dict, user) -> PricingFeature:
    try:
        plan = PricingPlan.objects.get(pk=plan_id)
    except PricingPlan.DoesNotExist:
        raise ContentNotFoundError(f"PricingPlan {plan_id} not found")

    obj = PricingFeature.objects.create(
        plan=plan,
        text=data.get("text", ""),
        text_ar=data.get("text_ar", ""),
        is_included=data.get("is_included", True),
        order=data.get("order", 0),
    )
    ActivityLogService.log(
        action="cms.pricing_feature.add",
        user=user,
        entity_type="PricingFeature",
        entity_id=str(obj.pk),
        description=f"Feature '{obj.text}' added to plan '{plan.name}'",
    )
    return obj


def remove_pricing_feature(feature_id: int, user) -> None:
    try:
        obj = PricingFeature.objects.select_related("plan").get(pk=feature_id)
    except PricingFeature.DoesNotExist:
        raise ContentNotFoundError(f"PricingFeature {feature_id} not found")
    text = obj.text
    plan_name = obj.plan.name
    obj.delete()
    ActivityLogService.log(
        action="cms.pricing_feature.remove",
        user=user,
        entity_type="PricingFeature",
        entity_id=str(feature_id),
        description=f"Feature '{text}' removed from plan '{plan_name}'",
    )


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------

def create_faq_category(data: dict, user) -> FAQCategory:
    obj = FAQCategory.objects.create(
        name=data.get("name", ""),
        name_ar=data.get("name_ar", ""),
        order=data.get("order", 0),
        is_active=data.get("is_active", True),
    )
    ActivityLogService.log(
        action="cms.faq_category.create",
        user=user,
        entity_type="FAQCategory",
        entity_id=str(obj.pk),
        description=f"FAQCategory '{obj.name}' created",
    )
    return obj


def update_faq_category(cat_id: int, data: dict, user) -> FAQCategory:
    try:
        obj = FAQCategory.objects.get(pk=cat_id)
    except FAQCategory.DoesNotExist:
        raise ContentNotFoundError(f"FAQCategory {cat_id} not found")

    for field in ["name", "name_ar", "order", "is_active"]:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.faq_category.update",
        user=user,
        entity_type="FAQCategory",
        entity_id=str(obj.pk),
        description=f"FAQCategory '{obj.name}' updated",
    )
    return obj


def create_faq_item(data: dict, user) -> FAQItem:
    category = None
    cat_id = data.get("category")
    if cat_id:
        try:
            category = FAQCategory.objects.get(pk=cat_id)
        except FAQCategory.DoesNotExist:
            raise ContentNotFoundError(f"FAQCategory {cat_id} not found")

    obj = FAQItem.objects.create(
        category=category,
        question=data.get("question", ""),
        question_ar=data.get("question_ar", ""),
        answer=data.get("answer", ""),
        answer_ar=data.get("answer_ar", ""),
        order=data.get("order", 0),
        is_active=data.get("is_active", True),
    )
    ActivityLogService.log(
        action="cms.faq_item.create",
        user=user,
        entity_type="FAQItem",
        entity_id=str(obj.pk),
        description=f"FAQItem created: '{obj.question[:60]}'",
    )
    return obj


def update_faq_item(item_id: int, data: dict, user) -> FAQItem:
    try:
        obj = FAQItem.objects.get(pk=item_id)
    except FAQItem.DoesNotExist:
        raise ContentNotFoundError(f"FAQItem {item_id} not found")

    if "category" in data:
        cat_id = data["category"]
        if cat_id is None:
            obj.category = None
        else:
            try:
                obj.category = FAQCategory.objects.get(pk=cat_id)
            except FAQCategory.DoesNotExist:
                raise ContentNotFoundError(f"FAQCategory {cat_id} not found")

    for field in ["question", "question_ar", "answer", "answer_ar", "order", "is_active"]:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.faq_item.update",
        user=user,
        entity_type="FAQItem",
        entity_id=str(obj.pk),
        description=f"FAQItem updated: '{obj.question[:60]}'",
    )
    return obj


def delete_faq_item(item_id: int, user) -> None:
    try:
        obj = FAQItem.objects.get(pk=item_id)
    except FAQItem.DoesNotExist:
        raise ContentNotFoundError(f"FAQItem {item_id} not found")
    question = obj.question[:60]
    obj.delete()
    ActivityLogService.log(
        action="cms.faq_item.delete",
        user=user,
        entity_type="FAQItem",
        entity_id=str(item_id),
        description=f"FAQItem deleted: '{question}'",
    )


# ---------------------------------------------------------------------------
# SEO
# ---------------------------------------------------------------------------

def update_seo_setting(page_key: str, data: dict, user) -> SEOSetting:
    obj, created = SEOSetting.objects.get_or_create(
        page_key=page_key,
        defaults={"meta_title": data.get("meta_title", "")},
    )
    allowed_fields = [
        "meta_title", "meta_title_ar", "meta_description", "meta_description_ar",
        "keywords", "og_title", "og_description", "og_image_url", "canonical_url",
    ]
    for field in allowed_fields:
        if field in data:
            setattr(obj, field, data[field])
    obj.updated_by = user
    obj.save()
    ActivityLogService.log(
        action="cms.seo.update",
        user=user,
        entity_type="SEOSetting",
        entity_id=str(obj.pk),
        description=f"SEO setting for '{page_key}' {'created' if created else 'updated'}",
    )
    return obj


# ---------------------------------------------------------------------------
# Platform Settings
# ---------------------------------------------------------------------------

def update_platform_setting(key: str, value: str, user) -> PlatformSetting:
    try:
        obj = PlatformSetting.objects.get(key=key)
    except PlatformSetting.DoesNotExist:
        raise ContentNotFoundError(f"PlatformSetting '{key}' not found")
    obj.value = value
    obj.updated_by = user
    obj.save()
    ActivityLogService.log(
        action="cms.platform_setting.update",
        user=user,
        entity_type="PlatformSetting",
        entity_id=str(obj.pk),
        description=f"PlatformSetting '{key}' updated",
    )
    return obj


def bulk_update_platform_settings(settings_dict: dict, user) -> list:
    """Update multiple platform settings at once. Returns list of updated objects."""
    updated = []
    keys = list(settings_dict.keys())
    existing = {s.key: s for s in PlatformSetting.objects.filter(key__in=keys)}

    for key, value in settings_dict.items():
        if key not in existing:
            continue
        obj = existing[key]
        obj.value = str(value)
        obj.updated_by = user
        obj.save(update_fields=["value", "updated_by", "updated_at"])
        updated.append(obj)

    if updated:
        ActivityLogService.log(
            action="cms.platform_settings.bulk_update",
            user=user,
            entity_type="PlatformSetting",
            entity_id="",
            description=f"Bulk updated {len(updated)} platform settings: {', '.join(s.key for s in updated)}",
        )
    return updated


# ---------------------------------------------------------------------------
# Media Assets
# ---------------------------------------------------------------------------

def create_media_asset(data: dict, user) -> MediaAsset:
    allowed_fields = [
        "title", "alt_text", "file_type", "file_url", "file_size",
        "mime_type", "width", "height", "audit_file", "tags",
    ]
    kwargs = {f: data[f] for f in allowed_fields if f in data}
    kwargs["uploaded_by"] = user
    obj = MediaAsset.objects.create(**kwargs)
    ActivityLogService.log(
        action="cms.media_asset.create",
        user=user,
        entity_type="MediaAsset",
        entity_id=str(obj.pk),
        description=f"MediaAsset '{obj.title}' uploaded ({obj.file_type})",
    )
    return obj


def delete_media_asset(asset_id, user) -> None:
    try:
        obj = MediaAsset.objects.get(pk=asset_id)
    except MediaAsset.DoesNotExist:
        raise ContentNotFoundError(f"MediaAsset {asset_id} not found")
    title = obj.title
    obj.delete()
    ActivityLogService.log(
        action="cms.media_asset.delete",
        user=user,
        entity_type="MediaAsset",
        entity_id=str(asset_id),
        description=f"MediaAsset '{title}' deleted",
    )


# ---------------------------------------------------------------------------
# CMS Pages
# ---------------------------------------------------------------------------

def create_cms_page(data: dict, user) -> CMSPage:
    slug = data.get("slug", "")
    if CMSPage.objects.filter(slug=slug).exists():
        raise DuplicateSlugError(f"CMSPage with slug '{slug}' already exists")

    obj = CMSPage.objects.create(
        slug=slug,
        title=data.get("title", ""),
        title_ar=data.get("title_ar", ""),
        status=data.get("status", CMSPage.DRAFT),
        created_by=user,
    )
    ActivityLogService.log(
        action="cms.page.create",
        user=user,
        entity_type="CMSPage",
        entity_id=str(obj.pk),
        description=f"CMSPage '{obj.slug}' created",
    )
    return obj


def update_cms_page(slug: str, data: dict, user) -> CMSPage:
    try:
        obj = CMSPage.objects.get(slug=slug)
    except CMSPage.DoesNotExist:
        raise ContentNotFoundError(f"CMSPage '{slug}' not found")

    new_slug = data.get("slug")
    if new_slug and new_slug != slug and CMSPage.objects.filter(slug=new_slug).exists():
        raise DuplicateSlugError(f"CMSPage with slug '{new_slug}' already exists")

    for field in ["slug", "title", "title_ar", "status"]:
        if field in data:
            setattr(obj, field, data[field])
    obj.save()
    ActivityLogService.log(
        action="cms.page.update",
        user=user,
        entity_type="CMSPage",
        entity_id=str(obj.pk),
        description=f"CMSPage '{obj.slug}' updated",
    )
    return obj


def publish_cms_page(slug: str, user) -> CMSPage:
    try:
        obj = CMSPage.objects.get(slug=slug)
    except CMSPage.DoesNotExist:
        raise ContentNotFoundError(f"CMSPage '{slug}' not found")

    if obj.status == CMSPage.ARCHIVED:
        raise PagePublishError(f"Cannot publish archived page '{slug}'")

    obj.status = CMSPage.PUBLISHED
    obj.published_at = timezone.now()
    obj.published_by = user
    obj.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    ActivityLogService.log(
        action="cms.page.publish",
        user=user,
        entity_type="CMSPage",
        entity_id=str(obj.pk),
        description=f"CMSPage '{obj.slug}' published",
    )
    return obj


def archive_cms_page(slug: str, user) -> CMSPage:
    try:
        obj = CMSPage.objects.get(slug=slug)
    except CMSPage.DoesNotExist:
        raise ContentNotFoundError(f"CMSPage '{slug}' not found")

    obj.status = CMSPage.ARCHIVED
    obj.save(update_fields=["status", "updated_at"])
    ActivityLogService.log(
        action="cms.page.archive",
        user=user,
        entity_type="CMSPage",
        entity_id=str(obj.pk),
        description=f"CMSPage '{obj.slug}' archived",
    )
    return obj
