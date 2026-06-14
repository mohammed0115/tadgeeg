"""
Platform CRM URL configuration (CRM-1C, read-only).

Mounted under ``/platform-admin/crm/`` via apps.platform_management.urls, giving
the nested namespace ``platform_admin:crm``. All routes are GET-only views.
No create/update/delete routes exist.
"""

from django.urls import path

from apps.platform_admin import crm_views as views

app_name = "crm"

urlpatterns = [
    path("", views.crm_dashboard, name="dashboard"),
    path("customers/", views.customers_list, name="customers"),
    path("customers/<uuid:org_id>/", views.customer_detail, name="customer_detail"),
    path("tickets/", views.tickets_list, name="tickets"),
    path("tickets/<uuid:ticket_id>/", views.ticket_detail, name="ticket_detail"),
    path("notes/", views.notes_list, name="notes"),
    path("activities/", views.activities_list, name="activities"),
]
