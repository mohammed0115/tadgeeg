from django.urls import path

from apps.billing import views


app_name = "billing"

urlpatterns = [
    path("plans/",        views.PlansView.as_view(),               name="plans"),
    path("select-plan/",  views.SelectPlanView.as_view(),          name="select-plan"),
    path("subscription/", views.CurrentSubscriptionView.as_view(), name="subscription"),
]
