from django.urls import path
from . import views
urlpatterns = [
    path("anomalies/detect/", views.AnomalyDetectionView.as_view(), name="anomaly-detect"),
    path("fraud/score/", views.FraudScoringView.as_view(), name="fraud-score"),
    path("query/", views.NLQueryView.as_view(), name="nl-query"),
    path("query/history/", views.NLQueryHistoryView.as_view(), name="nl-query-history"),
    path("query/export/", views.NLQueryExportView.as_view(), name="nl-query-export"),
    path("benford/", views.BenfordAnalysisView.as_view(), name="benford"),
    path("forecast/cashflow/", views.CashFlowForecastView.as_view(), name="cashflow-forecast"),
    path("kpis/", views.FinancialKPIsView.as_view(), name="kpis"),
]
