from __future__ import annotations

from rest_framework import serializers

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


class PlatformSettingSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PlatformSetting
        fields = [
            "id", "key", "value", "group", "label", "description",
            "is_public", "value_type", "updated_by", "updated_by_name", "updated_at",
        ]
        read_only_fields = ["id", "updated_at", "updated_by", "updated_by_name"]

    def get_updated_by_name(self, obj) -> str:
        return obj.updated_by.full_name if obj.updated_by else ""


class MediaAssetSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = MediaAsset
        fields = [
            "id", "title", "alt_text", "file_type", "file_url",
            "file_size", "mime_type", "width", "height",
            "audit_file", "uploaded_by", "uploaded_by_name", "created_at", "tags",
        ]
        read_only_fields = ["id", "created_at", "uploaded_by", "uploaded_by_name"]

    def get_uploaded_by_name(self, obj) -> str:
        return obj.uploaded_by.full_name if obj.uploaded_by else ""


class HomepageContentSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = HomepageContent
        fields = [
            "id",
            "hero_title", "hero_title_ar",
            "hero_subtitle", "hero_subtitle_ar",
            "hero_cta_primary_text", "hero_cta_primary_url",
            "hero_cta_secondary_text", "hero_cta_secondary_url",
            "hero_image_url",
            "stats", "trusted_by_logos",
            "is_active",
            "updated_by", "updated_by_name", "updated_at",
        ]
        read_only_fields = ["id", "updated_at", "updated_by", "updated_by_name"]

    def get_updated_by_name(self, obj) -> str:
        return obj.updated_by.full_name if obj.updated_by else ""


class IntroVideoSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = IntroVideo
        fields = [
            "id",
            "title", "title_ar",
            "video_url", "thumbnail_url",
            "description", "description_ar",
            "is_active", "order",
            "created_by", "created_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "created_by_name"]

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.full_name if obj.created_by else ""


class AboutSectionSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AboutSection
        fields = [
            "id",
            "title", "title_ar",
            "subtitle", "subtitle_ar",
            "content", "content_ar",
            "image_url",
            "mission", "mission_ar",
            "vision", "vision_ar",
            "stats",
            "is_active",
            "updated_by", "updated_by_name", "updated_at",
        ]
        read_only_fields = ["id", "updated_at", "updated_by", "updated_by_name"]

    def get_updated_by_name(self, obj) -> str:
        return obj.updated_by.full_name if obj.updated_by else ""


class CoreValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoreValue
        fields = [
            "id",
            "title", "title_ar",
            "description", "description_ar",
            "icon", "order", "is_active",
        ]
        read_only_fields = ["id"]


class CompetitiveAdvantageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetitiveAdvantage
        fields = [
            "id",
            "title", "title_ar",
            "description", "description_ar",
            "icon", "order", "is_active",
        ]
        read_only_fields = ["id"]


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "title", "title_ar",
            "description", "description_ar",
            "icon",
            "features", "features_ar",
            "order", "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class PricingFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingFeature
        fields = ["id", "plan", "text", "text_ar", "is_included", "order"]
        read_only_fields = ["id", "plan"]


class PricingPlanSerializer(serializers.ModelSerializer):
    features = PricingFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = PricingPlan
        fields = [
            "id",
            "name", "name_ar",
            "slug",
            "description", "description_ar",
            "price_monthly", "price_annual", "currency",
            "max_users", "max_invoices", "max_storage_gb",
            "is_featured", "is_active",
            "cta_text", "cta_url",
            "order",
            "features",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class FAQItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQItem
        fields = [
            "id",
            "category",
            "question", "question_ar",
            "answer", "answer_ar",
            "order", "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FAQCategorySerializer(serializers.ModelSerializer):
    items = FAQItemSerializer(many=True, read_only=True)

    class Meta:
        model = FAQCategory
        fields = ["id", "name", "name_ar", "order", "is_active", "items"]
        read_only_fields = ["id"]


class SEOSettingSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SEOSetting
        fields = [
            "id",
            "page_key",
            "meta_title", "meta_title_ar",
            "meta_description", "meta_description_ar",
            "keywords",
            "og_title", "og_description", "og_image_url",
            "canonical_url",
            "updated_by", "updated_by_name", "updated_at",
        ]
        read_only_fields = ["id", "page_key", "updated_at", "updated_by", "updated_by_name"]

    def get_updated_by_name(self, obj) -> str:
        return obj.updated_by.full_name if obj.updated_by else ""


class CMSBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = CMSBlock
        fields = [
            "id", "page", "block_type", "order",
            "content", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CMSPageSerializer(serializers.ModelSerializer):
    blocks = CMSBlockSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    published_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CMSPage
        fields = [
            "id",
            "slug",
            "title", "title_ar",
            "status",
            "published_at", "published_by", "published_by_name",
            "created_by", "created_by_name",
            "created_at", "updated_at",
            "blocks",
        ]
        read_only_fields = [
            "id", "created_at", "updated_at",
            "published_at", "published_by", "published_by_name",
            "created_by", "created_by_name",
        ]

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.full_name if obj.created_by else ""

    def get_published_by_name(self, obj) -> str:
        return obj.published_by.full_name if obj.published_by else ""
