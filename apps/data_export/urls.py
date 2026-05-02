from django.urls import path
from .views import DataExportRequestView, DataExportDownloadView

urlpatterns = [
    path("request/",          DataExportRequestView.as_view(),  name="data-export-request"),
    path("<str:job_id>/",     DataExportDownloadView.as_view(), name="data-export-download"),
]
