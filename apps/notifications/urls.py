from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.list_notifications, name="list"),
    path("unread-count/", views.unread_count, name="unread-count"),
    path("<uuid:pk>/read/", views.mark_read, name="mark-read"),
    path("mark-all-read/", views.mark_all_read_view, name="mark-all-read"),
]
