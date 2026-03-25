from django.urls import path

from .views import (
    # Admin — Dashboard Stats
    CMSDashboardStatsView,
    # Admin — Homepage
    HomepageContentView,
    # Admin — Intro Videos
    IntroVideoListView,
    IntroVideoDetailView,
    # Admin — About
    AboutSectionView,
    # Admin — Core Values
    CoreValueListView,
    CoreValueDetailView,
    # Admin — Competitive Advantages
    CompetitiveAdvantageListView,
    CompetitiveAdvantageDetailView,
    # Admin — Services
    ServiceListView,
    ServiceDetailView,
    # Admin — Pricing
    PricingPlanListView,
    PricingPlanDetailView,
    PricingFeatureCreateView,
    PricingFeatureDeleteView,
    # Admin — FAQ
    FAQCategoryListView,
    FAQCategoryDetailView,
    FAQItemListView,
    FAQItemDetailView,
    # Admin — SEO
    SEOSettingListView,
    SEOSettingDetailView,
    # Admin — Platform Settings
    PlatformSettingListView,
    # Admin — Media Assets
    MediaAssetListView,
    MediaAssetDetailView,
    # Admin — CMS Pages
    CMSPageListView,
    CMSPageDetailView,
    CMSPagePublishView,
    CMSPageArchiveView,
    # Public
    PublicHomepageView,
    PublicServicesView,
    PublicPricingView,
    PublicFAQView,
    PublicAboutView,
    PublicSEOView,
    PublicPlatformSettingsView,
)

app_name = "cms"

urlpatterns = [
    # -----------------------------------------------------------------------
    # Admin endpoints
    # -----------------------------------------------------------------------
    path("admin/stats/", CMSDashboardStatsView.as_view(), name="admin-stats"),
    path("admin/homepage/", HomepageContentView.as_view(), name="admin-homepage"),

    path("admin/intro-videos/", IntroVideoListView.as_view(), name="admin-intro-video-list"),
    path("admin/intro-videos/<int:pk>/", IntroVideoDetailView.as_view(), name="admin-intro-video-detail"),

    path("admin/about/", AboutSectionView.as_view(), name="admin-about"),

    path("admin/core-values/", CoreValueListView.as_view(), name="admin-core-value-list"),
    path("admin/core-values/<int:pk>/", CoreValueDetailView.as_view(), name="admin-core-value-detail"),

    path("admin/competitive-advantages/", CompetitiveAdvantageListView.as_view(), name="admin-advantage-list"),
    path("admin/competitive-advantages/<int:pk>/", CompetitiveAdvantageDetailView.as_view(), name="admin-advantage-detail"),

    path("admin/services/", ServiceListView.as_view(), name="admin-service-list"),
    path("admin/services/<int:pk>/", ServiceDetailView.as_view(), name="admin-service-detail"),

    path("admin/pricing-plans/", PricingPlanListView.as_view(), name="admin-pricing-plan-list"),
    path("admin/pricing-plans/<int:pk>/", PricingPlanDetailView.as_view(), name="admin-pricing-plan-detail"),
    path("admin/pricing-plans/<int:plan_id>/features/", PricingFeatureCreateView.as_view(), name="admin-pricing-feature-create"),
    path("admin/pricing-features/<int:pk>/", PricingFeatureDeleteView.as_view(), name="admin-pricing-feature-delete"),

    path("admin/faq/categories/", FAQCategoryListView.as_view(), name="admin-faq-category-list"),
    path("admin/faq/categories/<int:pk>/", FAQCategoryDetailView.as_view(), name="admin-faq-category-detail"),
    path("admin/faq/items/", FAQItemListView.as_view(), name="admin-faq-item-list"),
    path("admin/faq/items/<int:pk>/", FAQItemDetailView.as_view(), name="admin-faq-item-detail"),

    path("admin/seo/", SEOSettingListView.as_view(), name="admin-seo-list"),
    path("admin/seo/<str:page_key>/", SEOSettingDetailView.as_view(), name="admin-seo-detail"),

    path("admin/platform-settings/", PlatformSettingListView.as_view(), name="admin-platform-settings"),

    path("admin/media-assets/", MediaAssetListView.as_view(), name="admin-media-asset-list"),
    path("admin/media-assets/<uuid:pk>/", MediaAssetDetailView.as_view(), name="admin-media-asset-detail"),

    path("admin/pages/", CMSPageListView.as_view(), name="admin-cms-page-list"),
    path("admin/pages/<slug:slug>/", CMSPageDetailView.as_view(), name="admin-cms-page-detail"),
    path("admin/pages/<slug:slug>/publish/", CMSPagePublishView.as_view(), name="admin-cms-page-publish"),
    path("admin/pages/<slug:slug>/archive/", CMSPageArchiveView.as_view(), name="admin-cms-page-archive"),

    # -----------------------------------------------------------------------
    # Public endpoints
    # -----------------------------------------------------------------------
    path("public/homepage/", PublicHomepageView.as_view(), name="public-homepage"),
    path("public/services/", PublicServicesView.as_view(), name="public-services"),
    path("public/pricing/", PublicPricingView.as_view(), name="public-pricing"),
    path("public/faq/", PublicFAQView.as_view(), name="public-faq"),
    path("public/about/", PublicAboutView.as_view(), name="public-about"),
    path("public/seo/", PublicSEOView.as_view(), name="public-seo"),
    path("public/platform-settings/", PublicPlatformSettingsView.as_view(), name="public-platform-settings"),
]
