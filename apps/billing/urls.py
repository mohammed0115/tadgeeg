from django.urls import path

from apps.billing import views


app_name = "billing"

urlpatterns = [
    path("plans/",        views.PlansView.as_view(),               name="plans"),
    path("select-plan/",  views.SelectPlanView.as_view(),          name="select-plan"),
    path("subscription/", views.CurrentSubscriptionView.as_view(), name="subscription"),
    path("usage/",        views.UsagePageView.as_view(),           name="usage"),
    path("payments/",     views.PaymentHistoryView.as_view(),      name="payments"),
    path("bulk-upload/",  views.BulkUploadPageView.as_view(),      name="bulk-upload"),
    # §K calculator. Public and throttled: it answers a question a prospect
    # asks before signing up, and exposes nothing beyond the public catalogue.
    path("recommend/",    views.pricing_recommendation,            name="recommend"),
]
