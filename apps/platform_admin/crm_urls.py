"""
Platform CRM URL configuration.

Mounted under ``/platform-admin/crm/`` via apps.platform_management.urls, giving
the nested namespace ``platform_admin:crm``.

CRM-1C/1D routes are GET-only (read). CRM-1E adds guarded ticket-write routes:
``tickets/new/`` (GET form + POST) and three POST-only operations
(message/status/assign). No GET performs a mutation.
"""

from django.urls import path

from apps.platform_admin import crm_views as views

app_name = "crm"

urlpatterns = [
    path("", views.crm_dashboard, name="dashboard"),
    path("customers/", views.customers_list, name="customers"),
    path("customers/<uuid:org_id>/", views.customer_detail, name="customer_detail"),
    # Financial operations — POST-only
    path(
        "customers/<uuid:org_id>/subscription/<uuid:subscription_id>/extend/",
        views.subscription_extend,
        name="subscription_extend",
    ),
    # Customer suspend / reactivate (CRM-1F-2B) — POST-only
    path("customers/<uuid:org_id>/suspend/", views.customer_suspend, name="customer_suspend"),
    path("customers/<uuid:org_id>/reactivate/", views.customer_reactivate, name="customer_reactivate"),
    # Tickets — read
    path("tickets/", views.tickets_list, name="tickets"),
    # Tickets — write (CRM-1E). 'new/' must precede '<uuid>/'.
    path("tickets/new/", views.create_ticket, name="ticket_create"),
    path("tickets/<uuid:ticket_id>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<uuid:ticket_id>/message/", views.ticket_message, name="ticket_message"),
    path("tickets/<uuid:ticket_id>/status/", views.ticket_status, name="ticket_status"),
    path("tickets/<uuid:ticket_id>/assign/", views.ticket_assign, name="ticket_assign"),
    path("notes/", views.notes_list, name="notes"),
    path("activities/", views.activities_list, name="activities"),
]
