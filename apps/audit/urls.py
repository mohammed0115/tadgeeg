from django.urls import path
from . import views
from . import views_evidence as ev
from . import views_evidence_lifecycle as evl
from . import views_evidence_assurance as eva
from . import views_journal_analytics as jan
from . import views_financial_statements as vfs
from . import views_confirmations as vcf
from . import views_management_letter as vml
from . import views_substantive as vst
from . import views_planning_records as vpr
from . import views_assessed_risk as var
from . import views_audit_procedure as vap
from . import views_signoff as vso
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
    # TADGEEG-FIN-AUDIT-6D — evidence assurance & reporting.
    path("evidence-assurance/sweep/", eva.EvidenceIntegritySweepView.as_view(), name="evidence-assurance-sweep"),
    path("evidence-assurance/integrity-report/", eva.EvidenceIntegrityReportView.as_view(), name="evidence-assurance-integrity"),
    path("evidence-assurance/coverage/", eva.EvidenceCoverageView.as_view(), name="evidence-assurance-coverage"),
    path("evidence-assurance/index/", eva.EvidenceIndexView.as_view(), name="evidence-assurance-index"),
    path("evidence-assurance/dashboard/", eva.EvidenceAssuranceDashboardView.as_view(), name="evidence-assurance-dashboard"),
    path("engagements/<uuid:pk>/retention-policy/", eva.EngagementRetentionPolicyView.as_view(), name="evidence-retention-policy"),
    # TADGEEG-FIN-AUDIT-7A — journal analytics foundation (advisory only).
    path("journal-analytics/runs/", jan.AnalyticsRunListCreateView.as_view(), name="journal-analytics-runs"),
    path("journal-analytics/runs/<uuid:pk>/", jan.AnalyticsRunDetailView.as_view(), name="journal-analytics-run-detail"),
    path("journal-analytics/runs/<uuid:pk>/results/", jan.AnalyticsRunResultsView.as_view(), name="journal-analytics-run-results"),
    path("journal-analytics/runs/<uuid:pk>/report/", jan.AnalyticsRunReportView.as_view(), name="journal-analytics-run-report"),
    path("journal-analytics/dashboard/", jan.AnalyticsDashboardView.as_view(), name="journal-analytics-dashboard"),
    path("journal-analytics/rules/", jan.AnalyticsRuleListView.as_view(), name="journal-analytics-rules"),
    # TADGEEG-FIN-AUDIT-9A — financial statements review (IAS 1, advisory).
    path("engagements/<uuid:pk>/financial-statements/", vfs.EngagementFinancialStatementsView.as_view(), name="financial-statements"),
    # TADGEEG-FIN-AUDIT-9C — external confirmations (ISA 505).
    path("confirmations/", vcf.ConfirmationListCreateView.as_view(), name="confirmation-list"),
    path("confirmations/<uuid:pk>/", vcf.ConfirmationDetailView.as_view(), name="confirmation-detail"),
    path("confirmations/<uuid:pk>/<str:action>/", vcf.ConfirmationActionView.as_view(), name="confirmation-action"),
    # TADGEEG-FIN-AUDIT-9B — control deficiencies + management letter (ISA 265).
    path("control-deficiencies/", vml.DeficiencyListCreateView.as_view(), name="deficiency-list"),
    path("control-deficiencies/<uuid:pk>/", vml.DeficiencyDetailView.as_view(), name="deficiency-detail"),
    path("engagements/<uuid:pk>/management-letter/", vml.EngagementManagementLetterView.as_view(), name="management-letter"),
    # TADGEEG-FIN-AUDIT-9D — substantive testing (ISA 501 / assets / payroll).
    path("substantive-items/", vst.SubstantiveItemListCreateView.as_view(), name="substantive-list"),
    path("substantive-items/<uuid:pk>/", vst.SubstantiveItemDetailView.as_view(), name="substantive-detail"),
    path("engagements/<uuid:pk>/substantive-summary/", vst.EngagementSubstantiveSummaryView.as_view(), name="substantive-summary"),
    # TADGEEG-FIN-AUDIT-9H — saved ISA 300/330/240 planning records.
    path("engagements/<uuid:pk>/planning-records/", vpr.EngagementPlanningRecordsView.as_view(), name="planning-records"),
    path("planning-records/<uuid:pk>/", vpr.PlanningRecordDetailView.as_view(), name="planning-record-detail"),
    # TADGEEG-G2 — assessed risks (ISA 315, traceability spine anchor).
    path("assessed-risks/", var.AssessedRiskListCreateView.as_view(), name="assessed-risk-list"),
    path("assessed-risks/<uuid:pk>/", var.AssessedRiskDetailView.as_view(), name="assessed-risk-detail"),
    path("engagements/<uuid:pk>/risk-summary/", var.EngagementRiskSummaryView.as_view(), name="assessed-risk-summary"),
    path("engagements/<uuid:pk>/findings-register/", var.EngagementFindingsRegisterView.as_view(), name="findings-register"),
    # TADGEEG-G2.2 — audit procedures (ISA 330, Risk->Procedure link).
    path("procedures/", vap.ProcedureListCreateView.as_view(), name="procedure-list"),
    path("procedures/<uuid:pk>/", vap.ProcedureDetailView.as_view(), name="procedure-detail"),
    path("engagements/<uuid:pk>/procedure-summary/", vap.EngagementProcedureSummaryView.as_view(), name="procedure-summary"),
    # TADGEEG-G3 — engagement review & sign-off (ISA 220/230).
    path("engagements/<uuid:pk>/signoffs/", vso.EngagementSignoffView.as_view(), name="engagement-signoffs"),
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
