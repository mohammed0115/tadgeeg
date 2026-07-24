from django.urls import path
from . import views
from . import views_evidence as ev
from . import views_evidence_lifecycle as evl
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
    # TADGEEG-FIN-AUDIT-3B — review workflow.
    path("general-ledger/risk-findings/<uuid:pk>/review/", tb.GeneralLedgerRiskFindingReviewView.as_view(), name="gl-risk-finding-review"),
    # TADGEEG-FIN-AUDIT-4A — Summary of Audit Differences (SAD).
    path("engagements/<uuid:pk>/sad/recalculate/", tb.EngagementSADRecalculateView.as_view(), name="sad-recalculate"),
    path("engagements/<uuid:pk>/sad/", tb.EngagementSADView.as_view(), name="sad-engagement"),
    path("sad/<uuid:pk>/", tb.SADDetailView.as_view(), name="sad-detail"),
    path("sad/<uuid:pk>/items/", tb.SADItemsView.as_view(), name="sad-items"),
    # TADGEEG-FIN-AUDIT-4B — management response + proposed adjustments.
    path("sad/items/<uuid:pk>/management-response/", tb.SADItemManagementResponseView.as_view(), name="sad-item-management-response"),
    path("sad/items/<uuid:pk>/responses/", tb.SADItemResponsesView.as_view(), name="sad-item-responses"),
    path("sad/items/<uuid:pk>/proposed-adjustment/", tb.SADItemProposedAdjustmentView.as_view(), name="sad-item-proposed-adjustment"),
    path("sad/items/<uuid:pk>/proposed-adjustments/", tb.SADItemProposedAdjustmentsView.as_view(), name="sad-item-proposed-adjustments"),
    # TADGEEG-FIN-AUDIT-5A — audit readiness / opinion preparation workpaper.
    path("engagements/<uuid:pk>/audit-readiness/generate/", tb.EngagementAuditReadinessGenerateView.as_view(), name="audit-readiness-generate"),
    path("engagements/<uuid:pk>/audit-readiness/", tb.EngagementAuditReadinessView.as_view(), name="audit-readiness-engagement"),
    path("audit-readiness/<uuid:pk>/", tb.AuditReadinessDetailView.as_view(), name="audit-readiness-detail"),
    # TADGEEG-FIN-AUDIT-5D — audit readiness export (JSON / HTML / PDF).
    path("engagements/<uuid:pk>/audit-readiness/export/", tb.EngagementAuditReadinessExportView.as_view(), name="audit-readiness-export-engagement"),
    path("audit-readiness/<uuid:pk>/export/", tb.AuditReadinessExportView.as_view(), name="audit-readiness-export-detail"),
    # TADGEEG-FIN-AUDIT-6A — evidence request workflow.
    path("evidence-requests/", ev.EvidenceRequestListCreateView.as_view(), name="evidence-request-list"),
    path("evidence-requests/<uuid:pk>/", ev.EvidenceRequestDetailView.as_view(), name="evidence-request-detail"),
    path("evidence-requests/<uuid:pk>/submit/", ev.EvidenceRequestSubmitView.as_view(), name="evidence-request-submit"),
    path("evidence-requests/<uuid:pk>/review/", ev.EvidenceRequestReviewView.as_view(), name="evidence-request-review"),
    path("evidence-requests/<uuid:pk>/attachments/", ev.EvidenceRequestAttachmentsView.as_view(), name="evidence-request-attachments"),
    path("evidence-requests/<uuid:pk>/events/", ev.EvidenceRequestEventsView.as_view(), name="evidence-request-events"),
    # TADGEEG-FIN-AUDIT-6B — assignment + client management explanation.
    path("evidence-requests/<uuid:pk>/assign/", ev.EvidenceRequestAssignView.as_view(), name="evidence-request-assign"),
    path("evidence-requests/<uuid:pk>/management-explanation/", ev.EvidenceRequestManagementExplanationView.as_view(), name="evidence-request-management-explanation"),
    # TADGEEG-FIN-AUDIT-6C — evidence delivery & lifecycle.
    path("evidence-attachments/<uuid:pk>/download/", evl.EvidenceAttachmentDownloadView.as_view(), name="evidence-attachment-download"),
    path("evidence-attachments/<uuid:pk>/verify/", evl.EvidenceAttachmentVerifyView.as_view(), name="evidence-attachment-verify"),
    path("evidence-attachments/<uuid:pk>/<str:action>/", evl.EvidenceAttachmentLifecycleView.as_view(), name="evidence-attachment-lifecycle"),
    path("evidence-requests/<uuid:pk>/versions/", evl.EvidenceRequestVersionsView.as_view(), name="evidence-request-versions"),
    path("evidence-queue/", evl.EvidenceQueueView.as_view(), name="evidence-queue"),
    path("evidence-requests/bulk-assign/", evl.EvidenceBulkAssignView.as_view(), name="evidence-bulk-assign"),
    path("evidence-dashboard/summary/", evl.EvidenceDashboardSummaryView.as_view(), name="evidence-dashboard-summary"),
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
