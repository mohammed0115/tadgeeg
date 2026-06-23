from django.urls import path
from . import views
from . import views_rule_builder as rb
from . import views_trial_balance as tb

urlpatterns = [
    # TADGEEG-FIN-AUDIT-1B — Trial Balance upload/list/detail + account mapping.
    path("trial-balance/imports/", tb.TrialBalanceImportListCreateView.as_view(), name="tb-import-list"),
    path("trial-balance/imports/<uuid:pk>/", tb.TrialBalanceImportDetailView.as_view(), name="tb-import-detail"),
    path("trial-balance/account-mappings/", tb.AccountMappingListView.as_view(), name="tb-account-mapping-list"),
    path("trial-balance/account-mappings/generate/", tb.GenerateAccountMappingsView.as_view(), name="tb-account-mapping-generate"),
    # TADGEEG-FIN-AUDIT-2A — General Ledger import staging.
    path("general-ledger/imports/", tb.GeneralLedgerImportListCreateView.as_view(), name="gl-import-list"),
    path("general-ledger/imports/<uuid:pk>/", tb.GeneralLedgerImportDetailView.as_view(), name="gl-import-detail"),
    # TADGEEG-FIN-AUDIT-2B — GL risk analysis & candidate findings.
    path("general-ledger/imports/<uuid:pk>/analyze-risks/", tb.GeneralLedgerAnalyzeRisksView.as_view(), name="gl-analyze-risks"),
    # TADGEEG-FIN-AUDIT-3A — materiality classification for GL findings.
    path("general-ledger/imports/<uuid:pk>/apply-materiality/", tb.GeneralLedgerApplyMaterialityView.as_view(), name="gl-apply-materiality"),
    path("general-ledger/risk-findings/", tb.GeneralLedgerRiskFindingListView.as_view(), name="gl-risk-finding-list"),
    path("general-ledger/risk-findings/<uuid:pk>/", tb.GeneralLedgerRiskFindingDetailView.as_view(), name="gl-risk-finding-detail"),
    path("dashboard/overview/", views.AuditDashboardOverviewView.as_view(), name="dashboard-overview"),
    path("big-four/", views.BigFourComplianceView.as_view(), name="big-four-compliance"),
    # Phase 2.2 — visual rule builder. The DSL-driven endpoints sit under
    # /rule-builder/ so the legacy /rules/ surface (Phase-1 fixed-schema rules)
    # stays untouched for existing integrations.
    path("rule-builder/dsl-schema/",          rb.DSLSchemaView.as_view(),       name="rb-dsl-schema"),
    path("rule-builder/",                     rb.RuleListCreateView.as_view(),  name="rb-list"),
    path("rule-builder/<uuid:pk>/",           rb.RuleDetailView.as_view(),      name="rb-detail"),
    path("rule-builder/<uuid:pk>/test/",      rb.RuleSandboxView.as_view(),     name="rb-sandbox"),
    path("rule-builder/<uuid:pk>/publish/",   rb.RulePublishView.as_view(),     name="rb-publish"),
    path("rule-builder/<uuid:pk>/archive/",   rb.RuleArchiveView.as_view(),     name="rb-archive"),
    # Legacy fixed-schema rules — kept for backward compat.
    path("rules/", views.CustomRuleListCreateView.as_view(), name="custom-rule-list"),
    path("rules/<uuid:pk>/", views.CustomRuleDetailView.as_view(), name="custom-rule-detail"),
    path("rules/<uuid:pk>/test/", views.CustomRuleTestView.as_view(), name="custom-rule-test"),
    path("sessions/<uuid:pk>/", views.AuditSessionDetailView.as_view(), name="session-detail"),
    path("sessions/<uuid:pk>/progress/", views.AuditSessionProgressView.as_view(), name="session-progress"),
    path("sessions/<uuid:pk>/findings/", views.AuditSessionFindingsView.as_view(), name="session-findings"),
    path("cases/", views.AuditCaseListCreateView.as_view(), name="case-list"),
    path("cases/bulk/", views.BulkCaseActionView.as_view(), name="case-bulk"),
    path("cases/<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail"),
    path("cases/<uuid:pk>/comments/", views.CaseCommentView.as_view(), name="case-comments"),
    path("cases/<uuid:pk>/status/", views.UpdateCaseStatusView.as_view(), name="case-status"),
    path("cases/<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign"),
    path("<uuid:pk>/", views.AuditCaseDetailView.as_view(), name="case-detail-compat"),
    path("<uuid:pk>/update-status/", views.UpdateCaseStatusView.as_view(), name="case-status-compat"),
    path("<uuid:pk>/assign/", views.AssignCaseView.as_view(), name="case-assign-compat"),
]
