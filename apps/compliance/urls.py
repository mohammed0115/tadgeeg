from django.urls import path
from . import views
urlpatterns = [
    path("check/", views.ComplianceCheckView.as_view(), name="compliance-check"),
    path("rules/", views.ComplianceRuleListView.as_view(), name="compliance-rules"),
    path("vat/", views.VatComplianceView.as_view(), name="vat-compliance"),
    path("violations/", views.ComplianceViolationListView.as_view(), name="compliance-violations"),
    path("violations/<uuid:pk>/resolve/", views.ResolveComplianceViolationView.as_view(), name="compliance-violation-resolve"),
]
