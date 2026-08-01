"""Tadgeeg AI frontend URL configuration."""
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from apps.authentication.forms import ExistingEmailPasswordResetForm
from . import views
from . import evidence_views
from . import client_portal_views
from . import audit_host_views
from . import evidence_queue_views
from . import evidence_assurance_views
from . import journal_analytics_views
from . import engagement_workspace_views
from . import audit_governance_views
from . import audit_modules_views
from . import isa_assessment_views
from . import financial_statements_views
from . import confirmation_views
from . import management_letter_views
from . import substantive_views
from . import risk_register_views

app_name = 'frontend'

urlpatterns = [
    path('', views.landing, name='home'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
    path('pricing/', views.pricing, name='pricing'),
    path('partners/', views.partners, name='partners'),
    path('partners/apply/', views.partner_apply, name='partner_apply'),
    path('partners/<slug:slug>/', views.partner_detail, name='partner_detail'),
    path('about/', views.about, name='about'),
    path('services/', views.services, name='services'),
    path('contact/', views.contact, name='contact'),
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),
    path('refund-policy/', views.refund_policy, name='refund_policy'),
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
            form_class=ExistingEmailPasswordResetForm,
            email_template_name='auth/emails/password_reset_email.txt',
            subject_template_name='auth/emails/password_reset_subject.txt',
            extra_email_context={
                "product_name": settings.PRODUCT_NAME,
                "company_name": settings.COMPANY_NAME,
                "company_name_ar": settings.COMPANY_NAME_AR,
            },
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
    path('mfa-login/verify/', views.mfa_login_verify, name='mfa-login-verify'),  # ✅ PHASE 1: MFA verification endpoint
    path('google-pending/', views.google_pending, name='google_pending'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Invoices
    path('invoices/',                          views.invoices,        name='invoices'),
    path('invoices/upload/',                   views.upload,          name='upload'),
    path('invoices/export.csv',                views.invoices_export, {'fmt': 'csv'},  name='invoices_export_csv'),
    path('invoices/export.xlsx',               views.invoices_export, {'fmt': 'xlsx'}, name='invoices_export_xlsx'),
    path('invoices/reports/<str:kind>/',       views.invoice_subreport, name='invoice_subreport'),
    path('invoices/batches/',                  views.batches,         name='batches'),
    path('invoices/batches/<uuid:pk>/',        views.batch_detail,    name='batch_detail'),
    path('invoices/sessions/<uuid:pk>/',       views.audit_session_detail, name='audit_session_detail'),
    path('invoices/<uuid:pk>/',                views.invoice_detail,  name='invoice_detail'),
    path('invoices/<uuid:pk>/pdf/',            views.invoice_pdf,     name='invoice_pdf'),

    # Re-run audit on any document type
    path('documents/<str:doc_type>/<uuid:pk>/run-audit/', views.run_audit, name='run_audit'),

    # Excel export per doc-type list
    path('documents/<str:doc_type>/export.xlsx', views.doc_list_export_excel, name='doc_list_export_excel'),

    # Demo data loader (one-shot, idempotent)
    path('demo/load/', views.load_demo_data, name='load_demo_data'),

    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/invoice-audit/', views.invoice_audit_report, name='invoice_audit_report'),

    # TADGEEG-FIN-AUDIT-8A — Engagement Workspace (unified hub)
    path('audit/engagements/', engagement_workspace_views.engagement_list, name='engagement_list'),
    path('audit/engagements/<uuid:pk>/', engagement_workspace_views.engagement_workspace, name='engagement_workspace'),

    # TADGEEG-FIN-AUDIT-8B/8C/8D/8G — audit module pages (surface existing engines)
    path('audit/trial-balance/', audit_modules_views.trial_balance, name='trial_balance'),
    path('audit/general-ledger/', audit_modules_views.general_ledger, name='general_ledger'),
    path('audit/sad/', audit_modules_views.sad_dashboard, name='sad_dashboard'),
    path('audit/readiness-generate/', audit_modules_views.readiness_generate, name='readiness_generate'),

    # TADGEEG-FIN-AUDIT-8E/8F — ISA assessment engines (form-driven)
    path('audit/isa/risk/', isa_assessment_views.risk_assessment, name='isa_risk'),
    path('audit/isa/going-concern/', isa_assessment_views.going_concern, name='isa_going_concern'),
    path('audit/isa/estimates/', isa_assessment_views.estimates, name='isa_estimates'),
    # TADGEEG-FIN-AUDIT-8H — ISA 300 planning + 330 responses + 240 fraud (list-builders)
    path('audit/isa/planning/', isa_assessment_views.planning, name='isa_planning'),
    path('audit/isa/responses/', isa_assessment_views.responses, name='isa_responses'),
    path('audit/isa/fraud/', isa_assessment_views.fraud, name='isa_fraud'),

    # TADGEEG-FIN-AUDIT-9A — Financial Statements review (IAS 1)
    path('audit/financial-statements/', financial_statements_views.financial_statements, name='financial_statements'),

    # TADGEEG-FIN-AUDIT-9C — External Confirmations (ISA 505)
    path('audit/confirmations/', confirmation_views.confirmations, name='confirmations'),
    # PUBLIC token-gated response page (no login; not subscription gated).
    path('confirm/<uuid:token>/', confirmation_views.confirmation_respond, name='confirmation_respond'),

    # TADGEEG-FIN-AUDIT-9B — Management Letter (ISA 265)
    path('audit/management-letter/', management_letter_views.management_letter, name='management_letter'),

    # TADGEEG-FIN-AUDIT-9D — Substantive Testing (ISA 501 / assets / payroll)
    path('audit/substantive-testing/', substantive_views.substantive_testing, name='substantive_testing'),

    # TADGEEG-G2 — Risk Register (ISA 315/330 traceability spine)
    path('audit/risk-register/', risk_register_views.risk_register, name='risk_register'),

    # TADGEEG-G2.3/G3.2/G3.3/G6 — engagement governance pages (surface API-only modules)
    path('audit/findings-register/', audit_governance_views.findings_register, name='findings_register'),
    path('audit/issues/', audit_governance_views.issues, name='issues'),
    path('audit/reports/', audit_governance_views.reports, name='engagement_reports'),
    path('audit/team/', audit_governance_views.team, name='engagement_team'),

    # Audit tools (ISA 320 materiality, ISA 530 sampling)
    path('audit/tools/', views.audit_tools, name='audit_tools'),

    # TADGEEG-FIN-AUDIT-6A — Evidence Request workflow pages
    path('audit/evidence/', evidence_views.evidence_list, name='evidence_list'),
    path('audit/evidence/new/', evidence_views.evidence_create, name='evidence_create'),
    # TADGEEG-FIN-AUDIT-6C — auditor evidence queue
    path('audit/evidence/queue/', evidence_queue_views.evidence_queue, name='evidence_queue'),

    # TADGEEG-FIN-AUDIT-6D — Evidence Assurance & Reporting
    path('audit/assurance/', evidence_assurance_views.assurance_overview, name='assurance_overview'),
    path('audit/assurance/integrity/', evidence_assurance_views.integrity_report, name='assurance_integrity'),
    path('audit/assurance/coverage/', evidence_assurance_views.coverage_report, name='assurance_coverage'),
    path('audit/assurance/index/', evidence_assurance_views.evidence_index_page, name='assurance_index'),
    path('audit/assurance/retention/', evidence_assurance_views.retention_policy_page, name='assurance_retention'),

    # TADGEEG-FIN-AUDIT-7A — Journal Analytics
    path('audit/analytics/', journal_analytics_views.analytics_dashboard, name='analytics_dashboard'),
    path('audit/analytics/runs/', journal_analytics_views.analytics_runs, name='analytics_runs'),
    path('audit/analytics/runs/<uuid:pk>/', journal_analytics_views.analytics_run_detail, name='analytics_run_detail'),
    path('audit/analytics/rules/', journal_analytics_views.analytics_rules, name='analytics_rules'),
    path('audit/evidence/<uuid:pk>/', evidence_views.evidence_detail, name='evidence_detail'),

    # TADGEEG-FIN-AUDIT-6B — Client Evidence Portal (client-side pages)
    path('audit/client-evidence/', client_portal_views.client_evidence_list, name='client_evidence_list'),
    path('audit/client-evidence/<uuid:pk>/', client_portal_views.client_evidence_detail, name='client_evidence_detail'),

    # TADGEEG-FIN-AUDIT-6B — auditor host pages for evidence integration
    path('audit/findings/<uuid:pk>/', audit_host_views.gl_finding_detail, name='gl_finding_detail'),
    path('audit/sad-items/<uuid:pk>/', audit_host_views.sad_item_detail, name='sad_item_detail'),
    path('audit/readiness/<uuid:pk>/', audit_host_views.readiness_evidence_summary, name='readiness_evidence_summary'),

    # Hash-chain integrity (tamper-evident audit trail)
    path('audit/integrity/', views.audit_integrity, name='audit_integrity'),

    # Custom rule builder (Phase 2.2)
    path('audit/rule-builder/', views.rule_builder, name='rule_builder'),

    # Continuous auditing live ops (Phase 3.1)
    path('audit/streaming/',     views.streaming_ops, name='streaming_ops'),

    # Alert routing (Phase 3.2)
    path('audit/alerts/',        views.alerts_dashboard, name='alerts_dashboard'),

    # ZATCA Phase 2 dashboard (Phase 4)
    path('compliance/zatca/',    views.zatca_dashboard,  name='zatca_dashboard'),

    # Bank Connectors dashboard (Phase 5)
    path('banking/',             views.banking_dashboard, name='banking_dashboard'),

    # General Ledger dashboard (Phase 7.1)
    path('ledger/',              views.ledger_dashboard,  name='ledger_dashboard'),

    # Working papers (ISA 230 — preparer → reviewer → partner sign-off)
    path('working-papers/',                   views.working_papers,         name='working_papers'),
    path('working-papers/new/',               views.working_paper_create,   name='working_paper_create'),
    path('working-papers/<uuid:pk>/',         views.working_paper_detail,   name='working_paper_detail'),
    path('working-papers/<uuid:pk>/action/',  views.working_paper_action,   name='working_paper_action'),

    # Vendors
    path('vendors/', views.vendors, name='vendors'),
    path('vendors/<path:vendor_name>/', views.vendor_detail, name='vendor_detail'),

    # Analytics
    path('analytics/', views.analytics, name='analytics'),

    # Audit cases
    path('audit/', views.audit, name='audit'),
    path('audit/inbox/', views.audit_inbox, name='audit_inbox'),
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

    # Phase 4 — typed document list pages
    path('documents/sales-orders/', views.sales_orders, name='sales_orders'),
    path('documents/quotations/', views.quotations, name='quotations'),
    path('documents/proforma-invoices/', views.proforma_invoices, name='proforma_invoices'),
    path('documents/receipt-vouchers/', views.receipt_vouchers, name='receipt_vouchers'),
    path('documents/cash-vouchers/', views.cash_vouchers, name='cash_vouchers'),
    path('documents/general-ledgers/', views.general_ledgers, name='general_ledgers'),
    path('documents/ledgers/', views.ledgers, name='ledgers'),
    path('documents/contracts/', views.contracts, name='contracts'),
    path('documents/supplier-statements/', views.supplier_statements, name='supplier_statements'),
    path('documents/customer-statements/', views.customer_statements, name='customer_statements'),

    # Phase 4 — typed document detail pages
    path('documents/sales-orders/<uuid:pk>/', views.sales_order_detail, name='sales_order_detail'),
    path('documents/quotations/<uuid:pk>/', views.quotation_detail, name='quotation_detail'),
    path('documents/proforma-invoices/<uuid:pk>/', views.proforma_invoice_detail, name='proforma_invoice_detail'),
    path('documents/receipt-vouchers/<uuid:pk>/', views.receipt_voucher_detail, name='receipt_voucher_detail'),
    path('documents/cash-vouchers/<uuid:pk>/', views.cash_voucher_detail, name='cash_voucher_detail'),
    path('documents/general-ledgers/<uuid:pk>/', views.general_ledger_detail, name='general_ledger_detail'),
    path('documents/ledgers/<uuid:pk>/', views.ledger_detail, name='ledger_detail'),
    path('documents/contracts/<uuid:pk>/', views.contract_detail, name='contract_detail'),
    path('documents/supplier-statements/<uuid:pk>/', views.supplier_statement_detail, name='supplier_statement_detail'),
    path('documents/customer-statements/<uuid:pk>/', views.customer_statement_detail, name='customer_statement_detail'),

    # GRN, Payment Voucher, Journal Entry — completes the 20-doc-type catalog
    path('documents/grns/',                   views.goods_receipt_notes,       name='goods_receipt_notes'),
    path('documents/grns/<uuid:pk>/',         views.goods_receipt_note_detail, name='goods_receipt_note_detail'),
    path('documents/payment-vouchers/',       views.payment_vouchers,          name='payment_vouchers'),
    path('documents/payment-vouchers/<uuid:pk>/', views.payment_voucher_detail, name='payment_voucher_detail'),
    path('documents/journal-entries/',        views.journal_entries,           name='journal_entries'),
    path('documents/journal-entries/<uuid:pk>/', views.journal_entry_detail,    name='journal_entry_detail'),
]
