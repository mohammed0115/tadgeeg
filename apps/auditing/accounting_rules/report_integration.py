"""Utilities for integrating accounting rules into reports."""

from apps.auditing.accounting_rules.services import (
    evaluate_rules_for_report,
    build_accounting_findings_summary,
    aggregate_failed_rules,
)
from apps.auditing.accounting_rules.enums import AccountingStandard
from apps.auditing.models import AccountingRuleEvaluation


def get_report_accounting_rules_summary(report_id: str, organization_id: str) -> dict:
    """
    Get accounting rules compliance summary for a report.
    
    Returns both GAAP and IFRS assessments with key metrics.
    """
    summaries = {}
    
    for standard in ["GAAP", "IFRS"]:
        try:
            summary = build_accounting_findings_summary(
                report_id=report_id,
                standard=standard,
                organization_id=organization_id,
            )
            summaries[standard] = summary
        except Exception as e:
            summaries[standard] = {"error": str(e)}
    
    return summaries


def get_report_persistent_rule_evaluations(report_id: str, organization_id: str, limit: int = 50) -> dict:
    """
    Get persisted rule evaluation results for a report from database.
    
    Returns failed and warning rules with full details.
    """
    evaluations = AccountingRuleEvaluation.objects.filter(
        report_id=report_id,
        organization_id=organization_id,
    ).select_related("invoice")
    
    failed_rules = evaluations.filter(rule_status__in=["failed", "warning"]).order_by(
        "-rule_severity", "-evaluated_at"
    )[:limit]
    
    gaap_score = evaluations.filter(
        standard="gaap", rule_status="passed"
    ).count() / max(evaluations.filter(standard="gaap").count(), 1)
    
    ifrs_score = evaluations.filter(
        standard="ifrs", rule_status="passed"
    ).count() / max(evaluations.filter(standard="ifrs").count(), 1)
    
    return {
        "gaap_compliance_score": round(gaap_score * 100, 2),
        "ifrs_compliance_score": round(ifrs_score * 100, 2),
        "total_evaluations": evaluations.count(),
        "failed_and_warning_rules": [
            {
                "standard": rule.standard.upper(),
                "rule_code": rule.rule_code,
                "title": rule.rule_title,
                "status": rule.rule_status,
                "severity": rule.rule_severity,
                "invoice_id": str(rule.invoice_id) if rule.invoice_id else None,
                "observation": rule.observation,
                "recommendation": rule.recommendation,
            }
            for rule in failed_rules
        ],
    }


def get_dashboard_accounting_summary(organization_id: str) -> dict:
    """
    Get organization-wide accounting rules compliance summary for dashboard.
    
    Shows high-level compliance metrics across all reports.
    """
    all_evaluations = AccountingRuleEvaluation.objects.filter(
        organization_id=organization_id
    )
    
    gaap_evals = all_evaluations.filter(standard="gaap")
    ifrs_evals = all_evaluations.filter(standard="ifrs")
    
    failed_counts = {
        "gaap": gaap_evals.filter(rule_status="failed").count(),
        "ifrs": ifrs_evals.filter(rule_status="failed").count(),
        "gaap_warning": gaap_evals.filter(rule_status="warning").count(),
        "ifrs_warning": ifrs_evals.filter(rule_status="warning").count(),
    }
    
    gaap_compliance = (
        (gaap_evals.count() - failed_counts["gaap"] - failed_counts["gaap_warning"])
        / max(gaap_evals.count(), 1)
        * 100
    )
    
    ifrs_compliance = (
        (ifrs_evals.count() - failed_counts["ifrs"] - failed_counts["ifrs_warning"])
        / max(ifrs_evals.count(), 1)
        * 100
    )
    
    high_severity_failed = all_evaluations.filter(
        rule_severity="critical", rule_status="failed"
    ).count()
    
    return {
        "organization_id": str(organization_id),
        "gaap_compliance_score": round(gaap_compliance, 2),
        "ifrs_compliance_score": round(ifrs_compliance, 2),
        "total_evaluations": all_evaluations.count(),
        "failed_rules_count": failed_counts["gaap"] + failed_counts["ifrs"],
        "warning_rules_count": failed_counts["gaap_warning"] + failed_counts["ifrs_warning"],
        "critical_failures": high_severity_failed,
        "last_evaluation": all_evaluations.latest("evaluated_at").evaluated_at
        if all_evaluations.exists()
        else None,
    }


def export_rule_evaluations_to_csv(report_id: str, organization_id: str) -> str:
    """
    Export accounting rule evaluations for a report as CSV format.
    
    Returns CSV string that can be written to file or response.
    """
    import csv
    from io import StringIO
    
    evaluations = AccountingRuleEvaluation.objects.filter(
        report_id=report_id,
        organization_id=organization_id,
    ).select_related("invoice")
    
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "standard",
            "rule_code",
            "title",
            "category",
            "status",
            "severity",
            "invoice_id",
            "observation",
            "failure_reason",
            "recommendation",
            "evaluated_at",
        ],
    )
    
    writer.writeheader()
    for rule in evaluations:
        writer.writerow({
            "standard": rule.standard.upper(),
            "rule_code": rule.rule_code,
            "title": rule.rule_title,
            "category": rule.rule_category,
            "status": rule.rule_status,
            "severity": rule.rule_severity,
            "invoice_id": str(rule.invoice_id) if rule.invoice_id else "",
            "observation": rule.observation,
            "failure_reason": rule.failure_reason,
            "recommendation": rule.recommendation,
            "evaluated_at": rule.evaluated_at.isoformat() if rule.evaluated_at else "",
        })
    
    return output.getvalue()
