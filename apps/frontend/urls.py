"""FinAI Frontend URL Configuration"""
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'frontend'

urlpatterns = [
    path('', views.landing, name='home'),
    path('pricing/', views.pricing, name='pricing'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('privacy/', views.privacy, name='privacy'),
    path('blog/', views.blog, name='blog'),
    path('integrations/', views.integrations, name='integrations'),
    path('api/', views.api_page, name='api_page'),
    path('careers/', views.careers, name='careers'),

    # Auth
    path('login/',   views.login_view,  name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/',  views.logout_view, name='logout'),
    path(
        'forgot-password/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset_form.html',
            email_template_name='auth/emails/password_reset_email.txt',
            subject_template_name='auth/emails/password_reset_subject.txt',
            success_url=reverse_lazy('frontend:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'forgot-password/sent/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html',
            success_url=reverse_lazy('frontend:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path('auth/google/login/', views.google_oauth_login, name='google_oauth_login'),
    path('auth/google/callback/', views.google_oauth_callback, name='google_oauth_callback'),
    path('verify-email/', views.otp_verify, name='otp_verify'),
    path('verify-email/resend/', views.otp_resend, name='otp_resend'),
    path('google-pending/', views.google_pending, name='google_pending'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Invoices
    path('invoices/',                   views.invoices,        name='invoices'),
    path('invoices/upload/',            views.upload,          name='upload'),
    path('invoices/batches/',           views.batches,         name='batches'),
    path('invoices/batches/<uuid:pk>/', views.batch_detail,    name='batch_detail'),
    path('invoices/sessions/<uuid:pk>/', views.audit_session_detail, name='audit_session_detail'),
    path('invoices/<uuid:pk>/',         views.invoice_detail,  name='invoice_detail'),

    # Reports
    path('reports/', views.reports, name='reports'),

    # Vendors
    path('vendors/', views.vendors, name='vendors'),

    # Analytics
    path('analytics/', views.analytics, name='analytics'),

    # Audit cases
    path('audit/', views.audit, name='audit'),
    path('audit/<uuid:pk>/', views.audit_detail, name='audit_detail'),

    # Compliance
    path('compliance/', views.compliance, name='compliance'),

    # Documents
    path('documents/', views.documents, name='documents'),

    # Transactions + admin pages
    path('transactions/', views.transactions, name='transactions'),
    path('users/', views.users, name='users'),
    path('settings/', views.settings, name='settings'),

    # Typed document pages
    path('documents/upload/', views.doc_upload, name='doc_upload'),
    path('documents/purchase-orders/', views.purchase_orders, name='purchase_orders'),
    path('documents/bank-statements/', views.bank_statements, name='bank_statements'),
    path('documents/payroll/', views.payroll, name='payroll'),
    path('documents/expense-reports/', views.expense_reports, name='expense_reports'),
    path('documents/vat-returns/', views.vat_returns, name='vat_returns'),
    path('documents/fixed-assets/', views.fixed_assets, name='fixed_assets'),
    path('documents/sales-receipts/', views.sales_receipts, name='sales_receipts'),

    # Typed document detail pages
    path('documents/purchase-orders/<uuid:pk>/', views.purchase_order_detail, name='purchase_order_detail'),
    path('documents/bank-statements/<uuid:pk>/', views.bank_statement_detail, name='bank_statement_detail'),
    path('documents/payroll/<uuid:pk>/', views.payroll_detail, name='payroll_detail'),
    path('documents/expense-reports/<uuid:pk>/', views.expense_report_detail, name='expense_report_detail'),
    path('documents/vat-returns/<uuid:pk>/', views.vat_return_detail, name='vat_return_detail'),
    path('documents/fixed-assets/<uuid:pk>/', views.fixed_asset_detail, name='fixed_asset_detail'),
    path('documents/sales-receipts/<uuid:pk>/', views.sales_receipt_detail, name='sales_receipt_detail'),
]
