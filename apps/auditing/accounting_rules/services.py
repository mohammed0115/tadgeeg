from apps.auditing.accounting_rules.engine import AccountingRulesEngine
from apps.auditing.accounting_rules.enums import AccountingStandard
from apps.auditing.models import AccountingRuleEvaluation
from django.utils import timezone
from datetime import datetime


def persist_rule_evaluation(
    rule_result: dict,
    organization_id: str,
    report_id: str | None = None,
    invoice_id: str | None = None,
    audit_document_id: str | None = None,
) -> AccountingRuleEvaluation:
    """
    Persist a single rule evaluation result to the database.
    
    Args:
        rule_result: Dictionary from RuleResult.to_dict()
        organization_id: Organization UUID
        report_id: Optional report UUID
        invoice_id: Optional invoice UUID
        audit_document_id: Optional audit document UUID
        
    Returns:
        AccountingRuleEvaluation instance
    """
    evaluation = AccountingRuleEvaluation.objects.create(
        organization_id=organization_id,
        report_id=report_id,
        invoice_id=invoice_id,
        audit_document_id=audit_document_id,
        standard=rule_result.get("standard", "").lower(),
        rule_code=rule_result.get("code", ""),
        rule_title=rule_result.get("title", ""),
        rule_category=rule_result.get("category", "").lower(),
        rule_status=rule_result.get("status", "").lower(),
        rule_severity=rule_result.get("severity", "").lower(),
        observation=rule_result.get("observation", ""),
        failure_reason=rule_result.get("failure_reason", ""),
        recommendation=rule_result.get("recommendation", ""),
        score_impact=rule_result.get("score_impact", 0.0),
        confidence=rule_result.get("confidence", 1.0),
        related_fields=rule_result.get("related_fields", []),
        metadata_json=rule_result.get("metadata_json", {}),
    )
    return evaluation


def persist_evaluation_results(
    evaluation_result,
    organization_id: str,
    standard: str,
    report_id: str | None = None,
    invoice_id: str | None = None,
    audit_document_id: str | None = None,
) -> list[AccountingRuleEvaluation]:
    """
    Persist all results from an evaluation to the database.
    
    Args:
        evaluation_result: EvaluationResult instance from engine
        organization_id: Organization UUID
        standard: 'GAAP' or 'IFRS'
        report_id: Optional report UUID
        invoice_id: Optional invoice UUID
        audit_document_id: Optional audit document UUID
        
    Returns:
        List of created AccountingRuleEvaluation instances
    """
    created_evaluations = []
    
    for rule_result in evaluation_result.results:
        result_dict = rule_result.to_dict()
        evaluation = persist_rule_evaluation(
            rule_result=result_dict,
            organization_id=organization_id,
            report_id=report_id,
            invoice_id=invoice_id,
            audit_document_id=audit_document_id,
        )
        created_evaluations.append(evaluation)
    
    return created_evaluations


def evaluate_and_persist_invoice_rules(
    invoice_id: str,
    organization_id: str,
    standard: str,
    persist: bool = True,
) -> dict:
    """
    Evaluate a single invoice against accounting rules and optionally persist results.
    
    Args:
        invoice_id: Invoice UUID
        organization_id: Organization UUID
        standard: 'GAAP' or 'IFRS'
        persist: If True, save results to database
        
    Returns:
        Dictionary with 'summary', 'results', and 'persisted_count' keys
    """
    if standard.upper() == "GAAP":
        result = evaluate_gaap_rules_for_invoice(invoice_id, organization_id)
    elif standard.upper() == "IFRS":
        result = evaluate_ifrs_rules_for_invoice(invoice_id, organization_id)
    else:
        raise ValueError(f"Unknown standard: {standard}")
    
    persisted_count = 0
    
    if persist:
        # Get the engine result object for persistence
        invoice = _fetch_invoice(invoice_id=invoice_id, organization_id=organization_id)
        if invoice:
            record = _invoice_to_record(invoice)
            eval_obj = AccountingRulesEngine().evaluate(
                record=record,
                standard=AccountingStandard[standard.upper()],
                context={"organization_id": organization_id},
            )
            persisted = persist_evaluation_results(
                evaluation_result=eval_obj,
                organization_id=organization_id,
                standard=standard.upper(),
                invoice_id=invoice_id,
            )
            persisted_count = len(persisted)
    
    return {
        "summary": result.get("summary", {}),
        "results": result.get("results", []),
        "persisted_count": persisted_count,
    }


def evaluate_and_persist_report_rules(
    report_id: str,
    organization_id: str,
    standard: str,
    persist: bool = True,
) -> dict:
    """
    Evaluate a report against accounting rules and optionally persist results.
    
    Args:
        report_id: Report UUID
        organization_id: Organization UUID
        standard: 'GAAP' or 'IFRS'
        persist: If True, save results to database
        
    Returns:
        Dictionary with 'summary', 'results', and 'persisted_count' keys
    """
    result = evaluate_rules_for_report(
        report_id=report_id,
        standard=AccountingStandard[standard.upper()],
        organization_id=organization_id,
    )
    
    persisted_count = 0
    
    if persist:
        # Extract invoice IDs from report and evaluate each
        report = _fetch_report(report_id=report_id, organization_id=organization_id)
        if report:
            invoice_ids = _extract_invoice_ids(report.data or {})
            for invoice_id in invoice_ids:
                invoice = _fetch_invoice(invoice_id=invoice_id, organization_id=organization_id)
                if invoice:
                    record = _invoice_to_record(invoice)
                    eval_obj = AccountingRulesEngine().evaluate(
                        record=record,
                        standard=AccountingStandard[standard.upper()],
                        context={"organization_id": organization_id},
                    )
                    persisted = persist_evaluation_results(
                        evaluation_result=eval_obj,
                        organization_id=organization_id,
                        standard=standard.upper(),
                        report_id=report_id,
                        invoice_id=invoice_id,
                    )
                    persisted_count += len(persisted)
    
    return {
        "summary": result.get("summary", {}),
        "results": result.get("results", []),
        "persisted_count": persisted_count,
    }


def evaluate_accounting_rules(record: dict, standard: AccountingStandard, context: dict | None = None) -> dict:
    return AccountingRulesEngine().evaluate(record=record, standard=standard, context=context).to_dict()


def evaluate_gaap_rules_for_invoice(invoice_id: str, organization_id: str, context: dict | None = None) -> dict:
    invoice = _fetch_invoice(invoice_id=invoice_id, organization_id=organization_id)
    if invoice is None:
        return _not_found_payload("invoice", invoice_id, AccountingStandard.GAAP)
    record = _invoice_to_record(invoice)
    return evaluate_accounting_rules(record, AccountingStandard.GAAP, context=context)


def evaluate_ifrs_rules_for_invoice(invoice_id: str, organization_id: str, context: dict | None = None) -> dict:
    invoice = _fetch_invoice(invoice_id=invoice_id, organization_id=organization_id)
    if invoice is None:
        return _not_found_payload("invoice", invoice_id, AccountingStandard.IFRS)
    record = _invoice_to_record(invoice)
    return evaluate_accounting_rules(record, AccountingStandard.IFRS, context=context)


def evaluate_rules_for_report(report_id: str, standard: AccountingStandard, organization_id: str) -> dict:
    report = _fetch_report(report_id=report_id, organization_id=organization_id)
    if report is None:
        return {
            "report_id": str(report_id),
            "standard": standard.value,
            "summary": {"total_rules": 0, "passed": 0, "failed": 0, "warning": 0, "not_applicable": 0, "insufficient_data": 0, "compliance_score": 100.0, "risk_impact": 0.0, "high_severity_findings": 0},
            "results": [],
        }

    invoice_ids = _extract_invoice_ids(report.data or {})
    rows = []
    for invoice_id in invoice_ids:
        rows.append(
            evaluate_gaap_rules_for_invoice(invoice_id, organization_id)
            if standard == AccountingStandard.GAAP
            else evaluate_ifrs_rules_for_invoice(invoice_id, organization_id)
        )

    all_results = []
    aggregate = {"total_rules": 0, "passed": 0, "failed": 0, "warning": 0, "not_applicable": 0, "insufficient_data": 0, "compliance_score": 0.0, "risk_impact": 0.0, "high_severity_findings": 0}

    for item in rows:
        summary = item.get("summary", {})
        for key in ("total_rules", "passed", "failed", "warning", "not_applicable", "insufficient_data", "risk_impact", "high_severity_findings"):
            aggregate[key] += summary.get(key, 0)
        all_results.extend(item.get("results", []))

    aggregate["compliance_score"] = round(sum(r.get("summary", {}).get("compliance_score", 100.0) for r in rows) / max(len(rows), 1), 2)

    return {
        "report_id": str(report.id),
        "standard": standard.value,
        "summary": aggregate,
        "results": all_results,
    }


def aggregate_failed_rules(report_id: str, standard: AccountingStandard, organization_id: str) -> dict:
    payload = evaluate_rules_for_report(report_id=report_id, standard=standard, organization_id=organization_id)
    failures = [item for item in payload.get("results", []) if item.get("status") in ("failed", "warning")]
    by_rule = {}
    for item in failures:
        code = item.get("rule_code")
        if code not in by_rule:
            by_rule[code] = {"rule_code": code, "standard": item.get("standard"), "failed": 0, "warning": 0}
        by_rule[code][item.get("status")] += 1

    return {
        "report_id": payload.get("report_id"),
        "standard": standard.value,
        "failed_rules": sorted(by_rule.values(), key=lambda row: row["failed"] + row["warning"], reverse=True),
    }


def build_accounting_findings_summary(report_id: str, standard: AccountingStandard, organization_id: str) -> dict:
    aggregate = aggregate_failed_rules(report_id=report_id, standard=standard, organization_id=organization_id)
    eval_result = evaluate_rules_for_report(report_id=report_id, standard=standard, organization_id=organization_id)
    return {
        "report_id": str(report_id),
        "standard": standard.value,
        "compliance_score": eval_result.get("summary", {}).get("compliance_score", 100.0),
        "risk_impact": eval_result.get("summary", {}).get("risk_impact", 0.0),
        "high_severity_findings": eval_result.get("summary", {}).get("high_severity_findings", 0),
        "top_failed_rules": aggregate.get("failed_rules", [])[:10],
    }


def compare_ifrs_vs_gaap_findings(record: dict, context: dict | None = None) -> dict:
    gaap = evaluate_accounting_rules(record, AccountingStandard.GAAP, context=context)
    ifrs = evaluate_accounting_rules(record, AccountingStandard.IFRS, context=context)
    return {
        "record_id": record.get("record_id"),
        "gaap_summary": gaap.get("summary", {}),
        "ifrs_summary": ifrs.get("summary", {}),
        "score_delta": round((gaap.get("summary", {}).get("compliance_score", 100.0) - ifrs.get("summary", {}).get("compliance_score", 100.0)), 2),
    }


def _fetch_invoice(invoice_id: str, organization_id: str):
    from apps.invoices.models import Invoice

    return Invoice.objects.filter(id=invoice_id, organization_id=organization_id).first()


def _fetch_report(report_id: str, organization_id: str):
    from apps.reports.models import Report

    return Report.objects.filter(id=report_id, organization_id=organization_id).first()


def _extract_invoice_ids(report_data: dict) -> list[str]:
    ids: set[str] = set()
    for row in report_data.get("high_risk_invoices", []):
        if isinstance(row, dict) and row.get("id"):
            ids.add(str(row["id"]))
    for row in report_data.get("invoices", []):
        if isinstance(row, dict) and row.get("id"):
            ids.add(str(row["id"]))
    return sorted(ids)


def _invoice_to_record(invoice) -> dict:
    return {
        "record_type": "invoice",
        "record_id": str(invoice.id),
        "date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "posting_date": invoice.created_at.date().isoformat() if getattr(invoice, "created_at", None) else None,
        "amount": float(invoice.total_amount or 0),
        "currency": invoice.currency,
        "account": invoice.account_code,
        "counterparty": invoice.vendor_name,
        "reference": invoice.invoice_number,
        "line_items": invoice.line_items or [],
        "supporting_document": bool(invoice.file),
        "delivery_date": (invoice.extracted_data or {}).get("delivery_date"),
        "service_date": (invoice.extracted_data or {}).get("service_date"),
        "category": (invoice.extracted_data or {}).get("category"),
        "description": (invoice.extracted_data or {}).get("description"),
        "expected_account_code": (invoice.extracted_data or {}).get("expected_account_code"),
        "classification_justification": (invoice.extracted_data or {}).get("classification_justification"),
        "duplicate_flag": bool(invoice.is_duplicate),
        "materiality_flag": float(invoice.total_amount or 0) >= 10000,
        "approved": invoice.status == "approved",
    }


def _not_found_payload(record_type: str, record_id: str, standard: AccountingStandard) -> dict:
    return {
        "record_type": record_type,
        "record_id": str(record_id),
        "standard": standard.value,
        "summary": {
            "total_rules": 0,
            "passed": 0,
            "failed": 0,
            "warning": 0,
            "not_applicable": 0,
            "insufficient_data": 0,
            "compliance_score": 100.0,
            "risk_impact": 0.0,
            "high_severity_findings": 0,
        },
        "results": [],
    }
