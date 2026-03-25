from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class PlatformSetting(models.Model):
    GROUPS = [
        ("general", "General"),
        ("seo", "SEO"),
        ("social", "Social Media"),
        ("contact", "Contact"),
        ("features", "Features"),
    ]
    VALUE_TYPES = [
        ("text", "Text"),
        ("url", "URL"),
        ("email", "Email"),
        ("number", "Number"),
        ("boolean", "Boolean"),
        ("json", "JSON"),
    ]

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True)
    group = models.CharField(max_length=50, choices=GROUPS, default="general")
    label = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    is_public = models.BooleanField(default=False)
    value_type = models.CharField(max_length=20, choices=VALUE_TYPES, default="text")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_platform_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_platform_setting"
        ordering = ["group", "key"]
        verbose_name = "Platform Setting"
        verbose_name_plural = "Platform Settings"

    def __str__(self) -> str:
        return f"{self.key} ({self.group})"


class MediaAsset(models.Model):
    FILE_TYPES = [
        ("image", "Image"),
        ("video", "Video"),
        ("document", "Document"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    alt_text = models.CharField(max_length=200, blank=True)
    file_type = models.CharField(max_length=20, choices=FILE_TYPES)
    file_url = models.URLField(max_length=1000)
    file_size = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    audit_file = models.ForeignKey(
        "storage_management.AuditFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cms_media_assets",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_media_assets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    tags = models.JSONField(default=list)

    class Meta:
        db_table = "cms_media_asset"
        ordering = ["-created_at"]
        verbose_name = "Media Asset"
        verbose_name_plural = "Media Assets"

    def __str__(self) -> str:
        return f"{self.title} ({self.file_type})"


class HomepageContent(models.Model):
    hero_title = models.CharField(max_length=200)
    hero_title_ar = models.CharField(max_length=200, blank=True)
    hero_subtitle = models.TextField(blank=True)
    hero_subtitle_ar = models.TextField(blank=True)
    hero_cta_primary_text = models.CharField(max_length=100, blank=True)
    hero_cta_primary_url = models.CharField(max_length=200, blank=True)
    hero_cta_secondary_text = models.CharField(max_length=100, blank=True)
    hero_cta_secondary_url = models.CharField(max_length=200, blank=True)
    hero_image_url = models.URLField(blank=True)
    stats = models.JSONField(default=list)
    trusted_by_logos = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_homepage_contents",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_homepage_content"
        verbose_name = "Homepage Content"
        verbose_name_plural = "Homepage Contents"

    def __str__(self) -> str:
        return f"Homepage Content (id={self.pk})"


class IntroVideo(models.Model):
    title = models.CharField(max_length=200)
    title_ar = models.CharField(max_length=200, blank=True)
    video_url = models.URLField(max_length=500)
    thumbnail_url = models.URLField(blank=True, max_length=500)
    description = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_intro_videos",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_intro_video"
        ordering = ["order", "-created_at"]
        verbose_name = "Intro Video"
        verbose_name_plural = "Intro Videos"

    def __str__(self) -> str:
        return self.title


class AboutSection(models.Model):
    title = models.CharField(max_length=200)
    title_ar = models.CharField(max_length=200, blank=True)
    subtitle = models.TextField(blank=True)
    subtitle_ar = models.TextField(blank=True)
    content = models.TextField(blank=True)
    content_ar = models.TextField(blank=True)
    image_url = models.URLField(blank=True, max_length=500)
    mission = models.TextField(blank=True)
    mission_ar = models.TextField(blank=True)
    vision = models.TextField(blank=True)
    vision_ar = models.TextField(blank=True)
    stats = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_about_sections",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_about_section"
        verbose_name = "About Section"
        verbose_name_plural = "About Sections"

    def __str__(self) -> str:
        return self.title


class CoreValue(models.Model):
    title = models.CharField(max_length=100)
    title_ar = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default="star")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cms_core_value"
        ordering = ["order"]
        verbose_name = "Core Value"
        verbose_name_plural = "Core Values"

    def __str__(self) -> str:
        return self.title


class CompetitiveAdvantage(models.Model):
    title = models.CharField(max_length=200)
    title_ar = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default="check-circle")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cms_competitive_advantage"
        ordering = ["order"]
        verbose_name = "Competitive Advantage"
        verbose_name_plural = "Competitive Advantages"

    def __str__(self) -> str:
        return self.title


class Service(models.Model):
    title = models.CharField(max_length=200)
    title_ar = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default="zap")
    features = models.JSONField(default=list)
    features_ar = models.JSONField(default=list)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cms_service"
        ordering = ["order"]
        verbose_name = "Service"
        verbose_name_plural = "Services"

    def __str__(self) -> str:
        return self.title


class PricingPlan(models.Model):
    BILLING = [
        ("monthly", "Monthly"),
        ("annual", "Annual"),
    ]

    name = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100, blank=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_annual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="SAR")
    max_users = models.PositiveIntegerField(null=True, blank=True)
    max_invoices = models.PositiveIntegerField(null=True, blank=True)
    max_storage_gb = models.PositiveIntegerField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    cta_text = models.CharField(max_length=100, blank=True)
    cta_url = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_pricing_plan"
        ordering = ["order"]
        verbose_name = "Pricing Plan"
        verbose_name_plural = "Pricing Plans"

    def __str__(self) -> str:
        return f"{self.name} ({self.currency} {self.price_monthly}/mo)"


class PricingFeature(models.Model):
    plan = models.ForeignKey(
        PricingPlan, on_delete=models.CASCADE, related_name="features"
    )
    text = models.CharField(max_length=200)
    text_ar = models.CharField(max_length=200, blank=True)
    is_included = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "cms_pricing_feature"
        ordering = ["order"]
        verbose_name = "Pricing Feature"
        verbose_name_plural = "Pricing Features"

    def __str__(self) -> str:
        included = "included" if self.is_included else "excluded"
        return f"{self.plan.name} — {self.text} ({included})"


class FAQCategory(models.Model):
    name = models.CharField(max_length=100)
    name_ar = models.CharField(max_length=100, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "cms_faq_category"
        ordering = ["order"]
        verbose_name = "FAQ Category"
        verbose_name_plural = "FAQ Categories"

    def __str__(self) -> str:
        return self.name


class FAQItem(models.Model):
    category = models.ForeignKey(
        FAQCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )
    question = models.TextField()
    question_ar = models.TextField(blank=True)
    answer = models.TextField()
    answer_ar = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cms_faq_item"
        ordering = ["order"]
        verbose_name = "FAQ Item"
        verbose_name_plural = "FAQ Items"

    def __str__(self) -> str:
        return self.question[:80]


class SEOSetting(models.Model):
    PAGE_KEYS = [
        ("home", "Home"),
        ("about", "About"),
        ("services", "Services"),
        ("pricing", "Pricing"),
        ("faq", "FAQ"),
        ("contact", "Contact"),
        ("jobs", "Careers"),
    ]

    page_key = models.CharField(max_length=50, unique=True, choices=PAGE_KEYS)
    meta_title = models.CharField(max_length=200, blank=True)
    meta_title_ar = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(blank=True)
    meta_description_ar = models.TextField(blank=True)
    keywords = models.TextField(blank=True)
    og_title = models.CharField(max_length=200, blank=True)
    og_description = models.TextField(blank=True)
    og_image_url = models.URLField(blank=True)
    canonical_url = models.URLField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_seo_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_seo_setting"
        verbose_name = "SEO Setting"
        verbose_name_plural = "SEO Settings"

    def __str__(self) -> str:
        return f"SEO: {self.page_key}"


class CMSPage(models.Model):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
        ("archived", "Archived"),
    ]

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    title_ar = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cms_published_pages",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cms_created_pages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_page"
        ordering = ["-created_at"]
        verbose_name = "CMS Page"
        verbose_name_plural = "CMS Pages"

    def __str__(self) -> str:
        return f"{self.title} [{self.status}]"


class CMSBlock(models.Model):
    TYPES = [
        ("hero", "Hero"),
        ("text", "Text"),
        ("image", "Image"),
        ("cta", "Call to Action"),
        ("features", "Features"),
        ("stats", "Stats"),
        ("video", "Video"),
        ("testimonial", "Testimonial"),
    ]

    page = models.ForeignKey(CMSPage, on_delete=models.CASCADE, related_name="blocks")
    block_type = models.CharField(max_length=30, choices=TYPES)
    order = models.PositiveSmallIntegerField(default=0)
    content = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cms_block"
        ordering = ["order"]
        verbose_name = "CMS Block"
        verbose_name_plural = "CMS Blocks"

    def __str__(self) -> str:
        return f"{self.page.slug} — {self.block_type} (order={self.order})"
