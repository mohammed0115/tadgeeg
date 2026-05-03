from django.urls import path

from . import views as v


urlpatterns = [
    path("rules/",                v.AlertRuleListCreateView.as_view(), name="alert-rule-list"),
    path("rules/<uuid:pk>/",      v.AlertRuleDetailView.as_view(),     name="alert-rule-detail"),
    path("rules/<uuid:pk>/test/", v.AlertRuleTestView.as_view(),       name="alert-rule-test"),
    path("events/",               v.AlertEventListView.as_view(),      name="alert-event-list"),
    path("events/<uuid:pk>/ack/", v.AlertEventAckView.as_view(),       name="alert-event-ack"),
]
