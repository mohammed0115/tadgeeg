"""
Formal JSON Schemas for Tadgeeg Audit Report System.

Each schema describes the complete JSON structure returned by the report API.
Schemas are expressed as Python dicts compatible with JSON Schema Draft-07.

Usage:
    from apps.reports.schemas import DOCUMENT_REPORT_SCHEMA, EXECUTIVE_REPORT_SCHEMA
    import jsonschema
    jsonschema.validate(report_data, DOCUMENT_REPORT_SCHEMA)

These schemas are the single source of truth for:
- API response validation
- Frontend TypeScript type generation (via json-schema-to-typescript)
- Documentation generation
- Contract testing between backend and frontend
"""

from __future__ import annotations

# ─── Shared sub-schemas ───────────────────────────────────────────────────────

_EVIDENCE_SCHEMA = {
    "type": "object",
    "required": ["type", "field_name", "expected", "actual", "description"],
    "properties": {
        "type":           {"type": "string", "enum": ["field_value", "calculation", "comparison", "reference", "cross_document", "statistical"]},
        "field_name":     {"type": "string"},
        "field_name_ar":  {"type": "string"},
        "expected":       {},
        "actual":         {},
        "description":    {"type": "string"},
        "description_ar": {"type": "string"},
        "linked_document_type": {"type": ["string", "null"]},
        "linked_document_id":   {"type": ["string", "null"]},
    },
}

_RULE_EVALUATION_ROW_SCHEMA = {
    "type": "object",
    "required": ["rule_code", "rule_name_en", "rule_name_ar", "status", "severity", "risk_contribution"],
    "properties": {
        "rule_code":           {"type": "string", "example": "VAT-01"},
        "rule_name_en":        {"type": "string"},
        "rule_name_ar":        {"type": "string"},
        "status":              {"type": "string", "enum": ["pass", "fail", "warning", "skipped", "not_applicable", "error"]},
        "status_ar":           {"type": "string"},
        "severity":            {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
        "severity_ar":         {"type": "string"},
        "explanation_en":      {"type": "string"},
        "explanation_ar":      {"type": "string"},
        "risk_contribution":   {"type": "number", "minimum": 0, "maximum": 1},
        "blocks_approval":     {"type": "boolean"},
        "execution_time_ms":   {"type": "integer"},
        "suggested_action_ar": {"type": "string"},
        "evidence":            {"type": "array", "items": _EVIDENCE_SCHEMA},
    },
}

_VIOLATION_SCHEMA = {
    "type": "object",
    "required": ["rule_code", "severity", "title_en", "title_ar"],
    "properties": {
        "rule_code":         {"type": "string"},
        "severity":          {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "severity_ar":       {"type": "string"},
        "title_en":          {"type": "string"},
        "title_ar":          {"type": "string"},
        "blocks_approval":   {"type": "boolean"},
        "risk_contribution": {"type": "number"},
        "recommendation_ar": {"type": "string"},
        "recommendation_en": {"type": "string"},
        "financial_impact":  {"type": "number"},
    },
}

_RECOMMENDATION_SCHEMA = {
    "type": "object",
    "required": ["priority", "rule_code", "action_en", "action_ar"],
    "properties": {
        "priority":         {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "rule_code":        {"type": "string"},
        "action_en":        {"type": "string"},
        "action_ar":        {"type": "string"},
        "impact_ar":        {"type": "string"},
        "impact_en":        {"type": "string"},
        "financial_impact": {"type": "number"},
    },
}

_REPORT_META_SCHEMA = {
    "type": "object",
    "required": ["report_type", "document_type", "document_id", "organization_id", "status", "generated_at"],
    "properties": {
        "report_id":               {"type": ["string", "null"], "format": "uuid"},
        "report_type":             {"type": "string", "enum": ["document_audit", "invoice_audit", "executive"]},
        "document_type":           {"type": "string", "enum": ["sales_invoice", "purchase_order", "bank_statement", "payroll", "expense_report", "vat_return", "fixed_asset", "sales_receipt"]},
        "document_id":             {"type": "string", "format": "uuid"},
        "organization_id":         {"type": "string", "format": "uuid"},
        "organization_name":       {"type": "string"},
        "generated_at":            {"type": "string", "format": "date-time"},
        "generated_by":            {"type": "string"},
        "language":                {"type": "string", "enum": ["ar", "en"]},
        "audit_run_id":            {"type": ["string", "null"], "format": "uuid"},
        "status":                  {"type": "string", "enum": ["clean", "issues_found", "critical", "not_audited"]},
        "status_ar":               {"type": "string"},
        "engine_version":          {"type": "string"},
        "document_type_label_ar":  {"type": "string"},
        "document_type_label_en":  {"type": "string"},
    },
}

_REPORT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "total_amount":           {"type": "number"},
        "currency":               {"type": "string"},
        "item_count":             {"type": "integer"},
        "total_rules":            {"type": "integer"},
        "rules_passed":           {"type": "integer"},
        "rules_failed":           {"type": "integer"},
        "rules_warning":          {"type": "integer"},
        "rules_skipped":          {"type": "integer"},
        "rules_error":            {"type": "integer"},
        "pass_rate":              {"type": "number", "minimum": 0, "maximum": 100},
        "risk_score":             {"type": "number", "minimum": 0, "maximum": 100},
        "risk_level":             {"type": "string", "enum": ["critical", "high", "medium", "low", "unknown"]},
        "risk_level_ar":          {"type": "string"},
        "blocking_failures":      {"type": "integer"},
        "requires_manual_review": {"type": "boolean"},
        "blocks_approval":        {"type": "boolean"},
        "error_rate":             {"type": "number"},
        "processing_time_ms":     {"type": "integer"},
    },
}

_AI_INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {
        "anomalies":       {"type": "array", "items": {"type": "string"}},
        "patterns":        {"type": "array", "items": {"type": "string"}},
        "risk_factors":    {"type": "array", "items": {"type": "string"}},
        "vendor_behavior": {"type": "object"},
        "ai_summary_ar":   {"type": "string"},
        "ai_summary_en":   {"type": "string"},
        "has_insights":    {"type": "boolean"},
    },
}

_COMPLIANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "zatca_compliant":  {"type": "boolean"},
        "compliance_score": {"type": "number", "minimum": 0, "maximum": 100},
        "checks":           {"type": "object", "description": "Dict of check_name → bool|null"},
        "missing_fields":   {"type": "array", "items": {"type": "string"}},
        "failed_rules":     {"type": "array", "items": {"type": "string"}},
        "warning_rules":    {"type": "array", "items": {"type": "string"}},
    },
}

_AUDIT_TRAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "auditor":            {"type": "string"},
        "audit_date":         {"type": ["string", "null"], "format": "date-time"},
        "audit_type":         {"type": "string", "enum": ["automatic", "manual"]},
        "triggered_by":       {"type": "string", "enum": ["upload", "manual", "scheduled", "reprocess"]},
        "engine_version":     {"type": "string"},
        "processing_time_ms": {"type": "integer"},
    },
}


# ─── Document-specific section schemas ───────────────────────────────────────

_LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "item_code":   {"type": ["string", "null"]},
        "description": {"type": "string"},
        "quantity":    {"type": "number"},
        "unit_price":  {"type": "number"},
        "vat_rate":    {"type": "number"},
        "total":       {"type": "number"},
    },
}

DOCUMENT_SPECIFIC_SCHEMAS: dict[str, dict] = {
    "sales_invoice": {
        "type": "object",
        "properties": {
            "vat_breakdown": {
                "type": "object",
                "properties": {
                    "subtotal":     {"type": "number"},
                    "vat_rate":     {"type": "number"},
                    "vat_amount":   {"type": "number"},
                    "total":        {"type": "number"},
                    "expected_vat": {"type": "number"},
                },
            },
            "qr_validation": {
                "type": "object",
                "properties": {
                    "has_qr": {"type": "boolean"},
                    "valid":  {"type": "boolean"},
                },
            },
            "zatca_compliance": {
                "type": "object",
                "properties": {
                    "e_invoice_type": {"type": "string"},
                    "vendor_cr":      {"type": ["string", "null"]},
                    "buyer_vat":      {"type": ["string", "null"]},
                },
            },
            "line_items":   {"type": "array", "items": _LINE_ITEM_SCHEMA},
            "is_duplicate": {"type": "boolean"},
            "duplicate_of": {"type": ["string", "null"]},
        },
    },

    "purchase_order": {
        "type": "object",
        "properties": {
            "vendor_validation": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": ["string", "null"]},
                    "vendor_vat":  {"type": ["string", "null"]},
                    "vendor_cr":   {"type": ["string", "null"]},
                },
            },
            "budget_check": {
                "type": "object",
                "properties": {
                    "budget_limit":  {"type": "number"},
                    "total_amount":  {"type": "number"},
                    "within_budget": {"type": "boolean"},
                },
            },
            "approval_workflow": {
                "type": "object",
                "properties": {
                    "approved_by": {"type": ["string", "null"]},
                    "approved_at": {"type": ["string", "null"]},
                    "cost_center": {"type": ["string", "null"]},
                },
            },
            "line_items": {"type": "array", "items": _LINE_ITEM_SCHEMA},
        },
    },

    "bank_statement": {
        "type": "object",
        "properties": {
            "reconciliation": {
                "type": "object",
                "properties": {
                    "opening_balance":    {"type": "number"},
                    "total_credits":      {"type": "number"},
                    "total_debits":       {"type": "number"},
                    "closing_balance":    {"type": "number"},
                    "calculated_closing": {"type": "number"},
                },
            },
            "duplicate_transactions":  {"type": "integer"},
            "suspicious_transactions": {"type": "integer"},
            "suspicious_list": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date":        {"type": "string"},
                        "description": {"type": "string"},
                        "amount":      {"type": "number"},
                    },
                },
            },
            "transaction_summary": {
                "type": "object",
                "properties": {
                    "count":      {"type": "integer"},
                    "max_credit": {"type": "number"},
                    "max_debit":  {"type": "number"},
                },
            },
        },
    },

    "payroll": {
        "type": "object",
        "properties": {
            "salary_breakdown": {
                "type": "object",
                "properties": {
                    "total_gross":      {"type": "number"},
                    "total_allowances": {"type": "number"},
                    "total_deductions": {"type": "number"},
                    "total_net":        {"type": "number"},
                    "employee_count":   {"type": "integer"},
                },
            },
            "employee_validation": {
                "type": "object",
                "properties": {
                    "ghost_flags":      {"type": "integer"},
                    "duplicate_ids":    {"type": "integer"},
                    "missing_id_count": {"type": "integer"},
                },
            },
            "gosi_summary": {
                "type": "object",
                "properties": {"total_gosi": {"type": "number"}},
            },
            "top_salaries": {"type": "array", "items": {"type": "object"}},
        },
    },

    "expense_report": {
        "type": "object",
        "properties": {
            "receipt_validation": {
                "type": "object",
                "properties": {
                    "total_lines":     {"type": "integer"},
                    "with_receipt":    {"type": "integer"},
                    "without_receipt": {"type": "integer"},
                },
            },
            "category_breakdown": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "total":    {"type": "number"},
                    },
                },
            },
            "policy_violations": {
                "type": "object",
                "properties": {
                    "over_limit_count": {"type": "integer"},
                    "self_approval":    {"type": "boolean"},
                },
            },
            "total_claimed": {"type": "number"},
        },
    },

    "vat_return": {
        "type": "object",
        "properties": {
            "vat_calculation": {
                "type": "object",
                "properties": {
                    "output_vat":     {"type": "number"},
                    "input_vat":      {"type": "number"},
                    "calculated_net": {"type": "number"},
                    "declared_net":   {"type": "number"},
                    "arithmetic_ok":  {"type": "boolean"},
                    "discrepancy":    {"type": "number"},
                },
            },
            "filing_details": {
                "type": "object",
                "properties": {
                    "filing_status":   {"type": ["string", "null"]},
                    "filing_date":     {"type": ["string", "null"]},
                    "due_date":        {"type": ["string", "null"]},
                    "zatca_reference": {"type": ["string", "null"]},
                    "is_late":         {"type": "boolean"},
                },
            },
            "taxable_amounts": {
                "type": "object",
                "properties": {
                    "standard_rated_sales":     {"type": "number"},
                    "standard_rated_purchases": {"type": "number"},
                    "zero_rated_sales":         {"type": "number"},
                    "exempt_sales":             {"type": "number"},
                },
            },
        },
    },

    "fixed_asset": {
        "type": "object",
        "properties": {
            "depreciation_summary": {
                "type": "object",
                "properties": {
                    "total_cost":                {"type": "number"},
                    "total_accumulated":         {"type": "number"},
                    "total_book_value":          {"type": "number"},
                    "fully_depreciated":         {"type": "integer"},
                    "negative_book_value_count": {"type": "integer"},
                },
            },
            "asset_lifecycle": {
                "type": "object",
                "properties": {
                    "total_assets": {"type": "integer"},
                    "by_category":  {"type": "array", "items": {"type": "object"}},
                },
            },
            "assets_preview": {"type": "array", "items": {"type": "object"}},
        },
    },

    "sales_receipt": {
        "type": "object",
        "properties": {
            "payment_validation": {
                "type": "object",
                "properties": {
                    "payment_method":    {"type": ["string", "null"]},
                    "within_cash_limit": {"type": "boolean"},
                },
            },
            "zatca_reference": {
                "type": "object",
                "properties": {
                    "receipt_number":    {"type": ["string", "null"]},
                    "zatca_invoice_ref": {"type": ["string", "null"]},
                    "has_qr":           {"type": "boolean"},
                    "qr_valid":         {"type": "boolean"},
                },
            },
            "line_items": {"type": "array", "items": _LINE_ITEM_SCHEMA},
        },
    },
}


# ─── Full Document Audit Report Schema ───────────────────────────────────────

DOCUMENT_REPORT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://tadgeeg.com/schemas/document-audit-report/v2",
    "title": "Tadgeeg Document Audit Report",
    "description": "Unified audit report for all 8 Tadgeeg document types.",
    "type": "object",
    "required": ["report_meta", "summary", "key_fields", "rule_evaluation", "violations",
                 "ai_insights", "compliance", "recommendations", "audit_trail"],
    "properties": {
        "report_meta":       _REPORT_META_SCHEMA,
        "summary":           _REPORT_SUMMARY_SCHEMA,
        "key_fields":        {"type": "object", "description": "Common + type-specific display fields"},
        "rule_evaluation":   {"type": "array", "items": _RULE_EVALUATION_ROW_SCHEMA},
        "violations":        {"type": "array", "items": _VIOLATION_SCHEMA},
        "ai_insights":       _AI_INSIGHTS_SCHEMA,
        "compliance":        _COMPLIANCE_SCHEMA,
        "recommendations":   {"type": "array", "items": _RECOMMENDATION_SCHEMA, "maxItems": 10},
        "audit_trail":       _AUDIT_TRAIL_SCHEMA,
        "document_specific": {
            "type": "object",
            "description": "Document-type-specific structured sections. See DOCUMENT_SPECIFIC_SCHEMAS.",
        },
    },
}


# ─── Executive Report Schema ──────────────────────────────────────────────────

EXECUTIVE_REPORT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://tadgeeg.com/schemas/executive-report/v2",
    "title": "Tadgeeg Executive Audit Report",
    "description": "Organisation-wide executive audit report aggregating all document types.",
    "type": "object",
    "required": ["report_header", "executive_summary", "financial_overview", "audit_overview",
                 "risk_analysis", "compliance_overview", "top_issues", "ai_insights",
                 "recommendations", "document_breakdown"],
    "properties": {
        "report_header": {
            "type": "object",
            "properties": {
                "report_id":        {"type": ["string", "null"], "format": "uuid"},
                "title":            {"type": "string"},
                "organization":     {"type": "string"},
                "generated_at":     {"type": "string", "format": "date-time"},
                "generated_by":     {"type": "string"},
                "period_from":      {"type": ["string", "null"]},
                "period_to":        {"type": ["string", "null"]},
                "language":         {"type": "string"},
            },
        },
        "executive_summary": {
            "type": "object",
            "properties": {
                "overall_score":    {"type": "number", "minimum": 0, "maximum": 100},
                "risk_level":       {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "risk_level_ar":    {"type": "string"},
                "compliance_rate":  {"type": "number"},
                "avg_risk_score":   {"type": "number"},
                "total_documents":  {"type": "integer"},
                "top_issues_count": {"type": "integer"},
                "summary_ar":       {"type": "string"},
                "summary_en":       {"type": "string"},
                "auditor_opinion":  {"type": ["object", "null"]},
                "key_risks":        {"type": "array", "items": {"type": "string"}},
            },
        },
        "financial_overview": {
            "type": "object",
            "properties": {
                "total_revenue":    {"type": "number"},
                "total_expenses":   {"type": "number"},
                "net_profit":       {"type": "number"},
                "total_vat_payable":{"type": "number"},
                "currency":         {"type": "string"},
            },
        },
        "audit_overview": {
            "type": "object",
            "properties": {
                "total_documents_audited": {"type": "integer"},
                "clean_documents":         {"type": "integer"},
                "documents_with_issues":   {"type": "integer"},
                "blocking_documents":      {"type": "integer"},
                "pass_rate":               {"type": "number"},
                "failure_rate":            {"type": "number"},
                "total_rules_evaluated":   {"type": "integer"},
                "total_rules_passed":      {"type": "integer"},
                "total_rules_failed":      {"type": "integer"},
                "top_failed_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_code":     {"type": "string"},
                            "rule_name_ar":  {"type": "string"},
                            "rule_name_en":  {"type": "string"},
                            "failure_count": {"type": "integer"},
                        },
                    },
                },
            },
        },
        "risk_analysis": {
            "type": "object",
            "properties": {
                "distribution": {
                    "type": "object",
                    "properties": {
                        "critical": {"type": "integer"},
                        "high":     {"type": "integer"},
                        "medium":   {"type": "integer"},
                        "low":      {"type": "integer"},
                    },
                },
                "high_risk_docs": {"type": "array", "items": {"type": "object"}},
                "total_critical": {"type": "integer"},
                "total_high":     {"type": "integer"},
            },
        },
        "compliance_overview": {
            "type": "object",
            "properties": {
                "zatca_compliance_rate": {"type": "number"},
                "vat_failures":          {"type": "integer"},
                "vat_total_checks":      {"type": "integer"},
            },
        },
        "top_issues": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "rank":            {"type": "integer"},
                    "rule_code":       {"type": "string"},
                    "title_ar":        {"type": "string"},
                    "title_en":        {"type": "string"},
                    "occurrence":      {"type": "integer"},
                    "financial_impact":{"type": "number"},
                    "severity":        {"type": "string"},
                },
            },
        },
        "ai_insights": {
            "type": "object",
            "properties": {
                "fraud_indicator_count": {"type": "integer"},
                "structuring_alerts":    {"type": "integer"},
                "ghost_employee_alerts": {"type": "integer"},
                "duplicate_alerts":      {"type": "integer"},
                "self_approval_alerts":  {"type": "integer"},
                "anomaly_patterns":      {"type": "string"},
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority":    {"type": "string"},
                    "rule_code":   {"type": "string"},
                    "occurrence":  {"type": "integer"},
                    "action_ar":   {"type": "string"},
                    "action_en":   {"type": "string"},
                    "ai_rationale":{"type": ["string", "null"]},
                },
            },
        },
        "document_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "document_type":    {"type": "string"},
                    "label_ar":         {"type": "string"},
                    "label_en":         {"type": "string"},
                    "total":            {"type": "integer"},
                    "clean":            {"type": "integer"},
                    "with_issues":      {"type": "integer"},
                    "critical":         {"type": "integer"},
                    "avg_risk_score":   {"type": "number"},
                    "compliance_rate":  {"type": "number"},
                },
            },
        },
        "key_audit_matters": {
            "type": "array",
            "description": "ISA 701 Key Audit Matters — only present when material issues found",
            "items": {
                "type": "object",
                "properties": {
                    "kam_id":           {"type": "string"},
                    "isa_reference":    {"type": "string"},
                    "severity":         {"type": "string", "enum": ["critical", "high", "medium"]},
                    "title_ar":         {"type": "string"},
                    "title_en":         {"type": "string"},
                    "description_ar":   {"type": "string"},
                    "description_en":   {"type": "string"},
                    "root_cause_ar":    {"type": "string"},
                    "root_cause_en":    {"type": "string"},
                    "financial_impact": {"type": "string"},
                    "recommendation_ar":{"type": "string"},
                    "recommendation_en":{"type": "string"},
                    "evidence":         {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "isa700_opinion": {
            "type": "object",
            "description": "ISA 700 / ISA 705 formal auditor opinion",
            "properties": {
                "opinion_type":    {"type": "string", "enum": ["unqualified", "qualified", "adverse", "disclaimer"]},
                "opinion_type_ar": {"type": "string"},
                "opinion_type_en": {"type": "string"},
                "basis_ar":        {"type": "string"},
                "basis_en":        {"type": "string"},
                "standard":        {"type": "string"},
            },
        },
        "root_cause_analysis": {
            "type": "object",
            "description": "ISA 315 root cause analysis",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category":      {"type": "string"},
                            "failure_count": {"type": "integer"},
                            "root_cause_ar": {"type": "string"},
                            "root_cause_en": {"type": "string"},
                            "isa_reference": {"type": "string"},
                            "severity":      {"type": "string"},
                        },
                    },
                },
                "dominant_risk_areas": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


# ─── API Response wrappers ────────────────────────────────────────────────────

API_RESPONSE_SCHEMAS = {
    "generate_document_report": {
        "POST /api/v1/reports/document/": {
            "request": {
                "document_id":   "UUID — required",
                "document_type": "Enum[sales_invoice|purchase_order|bank_statement|payroll|expense_report|vat_return|fixed_asset|sales_receipt] — required",
                "language":      "Enum[ar|en] — default: ar",
                "save":          "bool — persist to DB — default: false",
            },
            "response_201": "DocumentAuditReport (see DOCUMENT_REPORT_SCHEMA)",
            "response_400": '{"error": "validation error message"}',
            "response_403": '{"detail": "Authentication credentials were not provided."}',
            "response_500": '{"error": "Internal error message"}',
        },
    },
    "get_document_report": {
        "GET /api/v1/reports/document/{report_id}/": {
            "response_200": "DocumentAuditReport JSON",
            "response_404": '{"detail": "Not found."}',
        },
    },
    "generate_executive_report": {
        "POST /api/v1/reports/executive/": {
            "permission": "IsSeniorAuditorOrAbove",
            "request": {
                "date_from": "date string YYYY-MM-DD — optional",
                "date_to":   "date string YYYY-MM-DD — optional",
                "language":  "Enum[ar|en] — default: ar",
                "save":      "bool — default: false",
            },
            "response_200": "ExecutiveReport (see EXECUTIVE_REPORT_SCHEMA)",
        },
    },
    "get_pdf": {
        "GET /api/v1/reports/document/{report_id}/pdf/": {
            "response_200": "application/pdf — attachment download",
            "response_500": '{"error": "PDF generation failed: <detail>"}',
        },
    },
    "get_html": {
        "GET /api/v1/reports/document/{report_id}/html/": {
            "response_200": "text/html — inline rendering",
        },
    },
}
