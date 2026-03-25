"""Frontend URL patterns for file management."""
from django.urls import path
from apps.file_management import frontend_views as views

urlpatterns = [
    path("", views.files, name="files"),
    path("folders/", views.folders, name="folders"),
]
