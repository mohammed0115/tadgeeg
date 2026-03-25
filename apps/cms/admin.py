from django.contrib import admin

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


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ["key", "group", "label", "value_type", "is_public", "updated_at"]
    list_filter = ["group", "value_type", "is_public"]
    search_fields = ["key", "label", "description"]
    ordering = ["group", "key"]
    readonly_fields = ["updated_at"]


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ["title", "file_type", "mime_type", "file_size", "uploaded_by", "created_at"]
    list_filter = ["file_type"]
    search_fields = ["title", "alt_text", "mime_type"]
    readonly_fields = ["id", "created_at"]
    ordering = ["-created_at"]


@admin.register(HomepageContent)
class HomepageContentAdmin(admin.ModelAdmin):
    list_display = ["id", "hero_title", "is_active", "updated_by", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["hero_title", "hero_subtitle"]
    readonly_fields = ["updated_at"]


@admin.register(IntroVideo)
class IntroVideoAdmin(admin.ModelAdmin):
    list_display = ["title", "order", "is_active", "created_by", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "description"]
    ordering = ["order", "-created_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AboutSection)
class AboutSectionAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "is_active", "updated_by", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "subtitle", "content"]
    readonly_fields = ["updated_at"]


@admin.register(CoreValue)
class CoreValueAdmin(admin.ModelAdmin):
    list_display = ["title", "icon", "order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["title", "description"]
    ordering = ["order"]


@admin.register(CompetitiveAdvantage)
class CompetitiveAdvantageAdmin(admin.ModelAdmin):
    list_display = ["title", "icon", "order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["title", "description"]
    ordering = ["order"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["title", "icon", "order", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "description"]
    ordering = ["order"]
    readonly_fields = ["created_at"]


class PricingFeatureInline(admin.TabularInline):
    model = PricingFeature
    extra = 1
    fields = ["text", "text_ar", "is_included", "order"]
    ordering = ["order"]


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "price_monthly", "price_annual", "currency", "is_featured", "is_active", "order"]
    list_filter = ["is_active", "is_featured", "currency"]
    search_fields = ["name", "slug", "description"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["order"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [PricingFeatureInline]


@admin.register(PricingFeature)
class PricingFeatureAdmin(admin.ModelAdmin):
    list_display = ["plan", "text", "is_included", "order"]
    list_filter = ["is_included", "plan"]
    search_fields = ["text", "plan__name"]
    ordering = ["plan", "order"]


class FAQItemInline(admin.TabularInline):
    model = FAQItem
    extra = 1
    fields = ["question", "answer", "order", "is_active"]
    ordering = ["order"]


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    ordering = ["order"]
    inlines = [FAQItemInline]


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ["question_short", "category", "order", "is_active", "created_at"]
    list_filter = ["is_active", "category"]
    search_fields = ["question", "answer"]
    ordering = ["order"]
    readonly_fields = ["created_at"]

    def question_short(self, obj):
        return obj.question[:60]
    question_short.short_description = "Question"


@admin.register(SEOSetting)
class SEOSettingAdmin(admin.ModelAdmin):
    list_display = ["page_key", "meta_title", "updated_by", "updated_at"]
    list_filter = ["page_key"]
    search_fields = ["page_key", "meta_title", "meta_description", "keywords"]
    readonly_fields = ["updated_at"]


class CMSBlockInline(admin.TabularInline):
    model = CMSBlock
    extra = 0
    fields = ["block_type", "order", "is_active", "content"]
    ordering = ["order"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(CMSPage)
class CMSPageAdmin(admin.ModelAdmin):
    list_display = ["slug", "title", "status", "published_at", "created_by", "created_at"]
    list_filter = ["status"]
    search_fields = ["slug", "title"]
    readonly_fields = ["created_at", "updated_at", "published_at"]
    ordering = ["-created_at"]
    inlines = [CMSBlockInline]


@admin.register(CMSBlock)
class CMSBlockAdmin(admin.ModelAdmin):
    list_display = ["page", "block_type", "order", "is_active", "updated_at"]
    list_filter = ["block_type", "is_active"]
    search_fields = ["page__slug", "block_type"]
    ordering = ["page", "order"]
    readonly_fields = ["created_at", "updated_at"]
