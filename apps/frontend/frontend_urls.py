"""FinAI Frontend URL Configuration"""
from django.urls import path
from . import views

app_name = 'frontend'

urlpatterns = [
    path('login/',   views.login_view,  name='login'),
    path('auth/google/login/', views.google_oauth_login, name='google_oauth_login'),
    path('auth/google/callback/', views.google_oauth_callback, name='google_oauth_callback'),
    path('verify-email/', views.otp_verify, name='otp_verify'),
    path('verify-email/resend/', views.otp_resend, name='otp_resend'),
    path('logout/',  views.logout_view, name='logout'),
    path('',          views.dashboard,  name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('invoices/',               views.invoices,       name='invoices'),
    path('invoices/upload/',        views.upload,         name='upload'),
    path('invoices/batches/',       views.batches,        name='batches'),
    path('invoices/<uuid:pk>/',     views.invoice_detail, name='invoice_detail'),
    path('reports/',                views.reports,        name='reports'),
    path('vendors/',                views.vendors,        name='vendors'),
    path('analytics/',              views.analytics,      name='analytics'),
    path('audit/',                  views.audit,          name='audit'),
    path('audit/sessions/<uuid:pk>/', views.audit_session_detail, name='audit_session_detail'),
    path('compliance/',             views.compliance,     name='compliance'),
    path('documents/',              views.documents,      name='documents'),
    # Typed document pages
    path('documents/upload/',                views.doc_upload,       name='doc_upload'),
    path('documents/purchase-orders/',       views.purchase_orders,  name='purchase_orders'),
    path('documents/bank-statements/',       views.bank_statements,  name='bank_statements'),
    path('documents/payroll/',               views.payroll,          name='payroll'),
    path('documents/expense-reports/',       views.expense_reports,  name='expense_reports'),
    path('documents/vat-returns/',           views.vat_returns,      name='vat_returns'),
    path('documents/fixed-assets/',          views.fixed_assets,     name='fixed_assets'),
    path('documents/sales-receipts/',        views.sales_receipts,   name='sales_receipts'),
]
