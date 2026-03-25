from collections import Counter, defaultdict

from apps.reports.models import Report
from apps.rule_engine.normalizers import DocumentNormalizerFactory
from apps.rule_engine.rules.gaap.engine import GAAPRuleEngine


def evaluate_gaap_rules_for_invoice(
    invoice_id: str,
    organization_id: str,
    persist: bool = False,
) -> dict:
    """
    Evaluate GAAP rules for one invoice in a tenant-safe scope.

    When persist=True, executes the full audit pipeline then extracts GAAP rows.
    Otherwise executes standalone GAAP engine in-memory.
    """
    if persist:
        from apps.rule_engine.executors.audit_pipeline import AuditPipeline
        from apps.rule_engine.models import AuditResult

        run = AuditPipeline().run(
            document_id=str(invoice_id),
            document_type="sales_invoice",
            organization_id=str(organization_id),
            triggered_by="manual",
        )
        gaap_rows = list(
            AuditResult.objects.filter(audit_run=run, rule_code__startswith="GAAP-")
            .values(
                "rule_code",
                "status",
                "applied_severity",
                "explanation",
                "risk_contribution",
                "raw_output",
            )
            .order_by("rule_code")
        )
        return {
            "document_type": "sales_invoice",
            "document_id": str(invoice_id),
            "organization_id": str(organization_id),
            "mode": "persisted",
            "results": gaap_rows,
        }

    normalizer = DocumentNormalizerFactory.get("sales_invoice")
    normalized = normalizer.normalize(str(invoice_id), str(organization_id))
    engine = GAAPRuleEngine()
    results = engine.evaluate(normalized)
    return {
        "document_type": "sales_invoice",
        "document_id": str(invoice_id),
        "organization_id": str(organization_id),
        "mode": "in_memory",
        "summary": engine.build_summary(results),
        "results": [r.__dict__ for r in results],
    }


def evaluate_gaap_rules_for_report(report_id: str, organization_id: str | None = None) -> dict:
    """
    Evaluate GAAP rules for report-related invoices.
    Tenant safety: report is always filtered by organization if provided.
    """
    filters = {"id": report_id}
    if organization_id:
        filters["organization_id"] = organization_id
    report = Report.objects.get(**filters)

    invoice_ids = _extract_invoice_ids_from_report(report)
    if not invoice_ids:
        return {
            "report_id": str(report.id),
            "organization_id": str(report.organization_id),
            "results": [],
            "summary": {
                "total_rules": 0,
                "passed": 0,
                "failed": 0,
                "warning": 0,
                "not_applicable": 0,
                "total_score_impact": 0.0,
                "gaap_score": 100.0,
            },
        }

    engine = GAAPRuleEngine()
    all_results = []
    for invoice_id in invoice_ids:
        normalizer = DocumentNormalizerFactory.get("sales_invoice")
        normalized = normalizer.normalize(str(invoice_id), str(report.organization_id))
        all_results.extend(engine.evaluate(normalized))

    return {
        "report_id": str(report.id),
        "organization_id": str(report.organization_id),
        "summary": engine.build_summary(all_results),
        "results": [r.__dict__ for r in all_results],
    }


def aggregate_gaap_failures(report_id: str, organization_id: str | None = None) -> dict:
    evaluated = evaluate_gaap_rules_for_report(report_id, organization_id=organization_id)
    failures = [r for r in evaluated["results"] if r["status"] in ("failed", "warning")]

    by_rule = defaultdict(lambda: {"failed": 0, "warning": 0})
    severity_counter = Counter()
    for item in failures:
        by_rule[item["rule_code"]][item["status"]] += 1
        severity_counter[item.get("severity") or "medium"] += 1

    return {
        "report_id": evaluated["report_id"],
        "organization_id": evaluated["organization_id"],
        "summary": evaluated["summary"],
        "failed_or_warning_count": len(failures),
        "severity_distribution": dict(severity_counter),
        "top_failed_rules": [
            {"rule_code": code, **counts}
            for code, counts in sorted(
                by_rule.items(), key=lambda kv: kv[1]["failed"] + kv[1]["warning"], reverse=True
            )
        ],
    }


def build_gaap_findings_summary(report_id: str, organization_id: str | None = None) -> dict:
    aggregation = aggregate_gaap_failures(report_id, organization_id=organization_id)
    summary = aggregation["summary"]

    return {
        "report_id": aggregation["report_id"],
        "organization_id": aggregation["organization_id"],
        "gaap_score": summary.get("gaap_score", 100.0),
        "total_rules_evaluated": summary.get("total_rules", 0),
        "failed_rules": summary.get("failed", 0),
        "warning_rules": summary.get("warning", 0),
        "most_failed_rules": aggregation["top_failed_rules"][:10],
        "highest_risk_invoices": _extract_high_risk_invoices(report_id, organization_id=organization_id),
    }


def _extract_invoice_ids_from_report(report: Report) -> list[str]:
    data = report.data or {}
    ids = set()

    for row in data.get("high_risk_invoices", []):
        if isinstance(row, dict) and row.get("id"):
            ids.add(str(row["id"]))

    for row in data.get("invoices", []):
        if isinstance(row, dict) and row.get("id"):
            ids.add(str(row["id"]))

    return sorted(ids)


def _extract_high_risk_invoices(report_id: str, organization_id: str | None = None) -> list[dict]:
    filters = {"id": report_id}
    if organization_id:
        filters["organization_id"] = organization_id
    report = Report.objects.get(**filters)

    rows = []
    for row in (report.data or {}).get("high_risk_invoices", [])[:10]:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "id": str(row.get("id")) if row.get("id") else None,
                "invoice_number": row.get("invoice_number"),
                "risk_level": row.get("risk_level"),
                "risk_score": row.get("risk_score"),
            }
        )
    return rows
