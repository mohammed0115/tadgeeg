"""URL routes for the Procurement app — Phase 7.3."""

from django.urls import path

from apps.procurement import views

app_name = "procurement"

urlpatterns = [
    path("requisitions/", views.RequisitionListCreateView.as_view(),
         name="requisition-list"),
    path("requisitions/<uuid:pr_id>/", views.RequisitionDetailView.as_view(),
         name="requisition-detail"),
    path("requisitions/<uuid:pr_id>/submit/", views.RequisitionSubmitView.as_view(),
         name="requisition-submit"),
    path("requisitions/<uuid:pr_id>/approve/", views.RequisitionApproveView.as_view(),
         name="requisition-approve"),
    path("requisitions/<uuid:pr_id>/reject/", views.RequisitionRejectView.as_view(),
         name="requisition-reject"),
    path("requisitions/<uuid:pr_id>/convert-to-po/",
         views.RequisitionConvertView.as_view(), name="requisition-convert"),

    path("threeway/", views.ThreeWayListView.as_view(), name="threeway-list"),
    path("threeway/run/", views.ThreeWayRunView.as_view(), name="threeway-run"),
]
