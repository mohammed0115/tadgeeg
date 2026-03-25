# Accounting Rules Engine - Implementation Guide (Tasks 1-3: Complete)

## Overview

This document summarizes the implementation of **Tasks 1-3** from the Accounting Rules Engine continuation plan:
1. ✅ HTTP Endpoint Integration
2. ✅ Report UI Integration  
3. ✅ Persistence Layer

## Phase 2 Recap

The comprehensive IFRS + GAAP standards engine was previously built in `apps/auditing/accounting_rules/` with:
- 8 GAAP rules + 9 IFRS rules (16 total)
- Registry system with lazy loading
- Policy layer for configuration
- Scoring engine for aggregation
- Service layer with tenant isolation

## What's New (Tasks 1-3)

### Task 1: HTTP Endpoint Integration ✅

Created REST API endpoints for rule evaluation and retrieval in `apps/auditing/views/accounting_rules_api.py`:

#### Key Endpoints

```
# List all rule evaluations with filters
GET /auditor/accounting-rules/
  ?standard=GAAP&status=failed&category=completeness

# Evaluate single invoice against GAAP
GET /auditor/invoices/{invoice_id}/evaluate/gaap/

# Evaluate single invoice against IFRS
GET /auditor/invoices/{invoice_id}/evaluate/ifrs/

# Get rule evaluations for a specific report
GET /auditor/reports/{report_id}/accounting-rules/

# Get accounting rules summary for report
GET /auditor/reports/{report_id}/accounting-rules-summary/
  ?standard=GAAP,IFRS

# Get failed rules for a report
GET /auditor/reports/{report_id}/failed-rules/
  ?standard=GAAP

# Compare GAAP vs IFRS for an invoice
GET /auditor/invoices/{invoice_id}/compare-standards/
```

#### API Features

- **Authentication**: All endpoints require `IsAuthenticated` permission
- **Pagination**: Standard pagination with 20 items per page, configurable via `page_size` parameter
- **Filtering**: Support for standard, status, category, and rule_code filters
- **Serialization**: Full nested serializer support with related object references

#### Example Requests

```bash
# Evaluate invoice against GAAP and persist
curl -H "Authorization: Bearer TOKEN" \
  "http://api/auditor/invoices/550e8400-e29b-41d4-a716-446655440000/evaluate/gaap/"

# Get failed rules for report (showing top 10)
curl -H "Authorization: Bearer TOKEN" \
  "http://api/auditor/reports/550e8400-e29b-41d4-a716-446655440001/failed-rules/?standard=IFRS"

# Compare standards for invoice
curl -H "Authorization: Bearer TOKEN" \
  "http://api/auditor/invoices/550e8400-e29b-41d4-a716-446655440000/compare-standards/"
```

### Task 2: Report UI Integration ✅

Created report integration utilities in `apps/auditing/accounting_rules/report_integration.py`:

#### Integration Functions

1. **`get_report_accounting_rules_summary(report_id, organization_id)`**
   - Returns GAAP and IFRS compliance scores
   - Shows top failed rules
   - Includes risk metrics
   - Perfect for executive dashboard display

2. **`get_report_persistent_rule_evaluations(report_id, organization_id)`**
   - Retrieves stored evaluations from database
   - Returns failed/warning rules with details
   - Calculates compliance scores based on persisted data
   - Useful for audit detail pages

3. **`get_dashboard_accounting_summary(organization_id)`**
   - Organization-wide compliance metrics
   - Total evaluations and failure counts
   - Critical failure count for alerting
   - Last evaluation timestamp

4. **`export_rule_evaluations_to_csv(report_id, organization_id)`**
   - Export evaluations as CSV
   - All key fields included
   - Ready for Excel/BI tools

#### Django Template Usage

```html
<!-- In your report detail template -->
{% load auditing_tags %}

<div class="accounting-compliance-section">
  {% accounting_rules_summary report.id as rules_summary %}
  
  <div class="compliance-scores">
    <h3>Accounting Standards Compliance</h3>
    
    <div class="gaap-score">
      <h4>GAAP</h4>
      <p>Compliance: {{ rules_summary.gaap.compliance_score }}%</p>
      <p>Failed Rules: {{ rules_summary.gaap|length }}</p>
    </div>
    
    <div class="ifrs-score">
      <h4>IFRS</h4>
      <p>Compliance: {{ rules_summary.ifrs.compliance_score }}%</p>
      <p>Failed Rules: {{ rules_summary.ifrs|length }}</p>
    </div>
  </div>
  
  <div class="top-findings">
    <h4>Top Failed Rules</h4>
    {% for rule in rules_summary.gaap.top_failed_rules %}
      <p>{{ rule.rule_code }}: {{ rule.rule_title }}</p>
    {% endfor %}
  </div>
</div>
```

### Task 3: Persistence Layer ✅

Created `AccountingRuleEvaluation` ORM model in `apps/auditing/models.py`:

#### Model Features

- **Fields**: 20 fields including standard, rule code, status, severity, observations, recommendations
- **Relationships**: FK to Organization, Report, Invoice, AuditDocument
- **Indexes**: 5 strategic indexes for fast querying by organization, standard, report, invoice
- **DB Table**: `accounting_rule_evaluations` with proper naming

#### Persistence Functions

New service functions in `apps/auditing/accounting_rules/services.py`:

1. **`persist_rule_evaluation(rule_result, organization_id, ...)`**
   - Saves a single rule evaluation to database
   - Links to organization, report, invoice

2. **`persist_evaluation_results(evaluation_result, organization_id, ...)`**
   - Saves all results from evaluation batch
   - Returns list of created objects

3. **`evaluate_and_persist_invoice_rules(invoice_id, organization_id, standard, persist=True)`**
   - Evaluates invoice and optionally saves
   - Returns summary + results + persisted_count

4. **`evaluate_and_persist_report_rules(report_id, organization_id, standard, persist=True)`**
   - Evaluates all invoices in report
   - Optionally saves all results
   - Returns aggregated summary

#### Manual Persistence

```python
from apps.auditing.accounting_rules.services import (
    evaluate_and_persist_invoice_rules,
    evaluate_and_persist_report_rules,
)

# Evaluate and save GAAP rules for an invoice
result = evaluate_and_persist_invoice_rules(
    invoice_id="550e8400-e29b-41d4-a716-446655440000",
    organization_id="org-uuid",
    standard="GAAP",
    persist=True,  # Save to database
)
print(f"Persisted {result['persisted_count']} rule evaluations")

# Evaluate and save IFRS rules for entire report
result = evaluate_and_persist_report_rules(
    report_id="550e8400-e29b-41d4-a716-446655440001",
    organization_id="org-uuid",
    standard="IFRS",
    persist=True,
)
print(f"Persisted {result['persisted_count']} rule evaluations")
```

#### Database Queries

```python
from apps.auditing.models import AccountingRuleEvaluation

# Get all failed GAAP rules for a report
failed = AccountingRuleEvaluation.objects.filter(
    report_id="report-uuid",
    standard="gaap",
    rule_status="failed",
)

# Get compliance score for invoice
invoice_results = AccountingRuleEvaluation.objects.filter(
    invoice_id="invoice-uuid",
    standard="ifrs",
)
passed = invoice_results.filter(rule_status="passed").count()
total = invoice_results.count()
score = (passed / total * 100) if total > 0 else 100

# Find critical failures
critical = AccountingRuleEvaluation.objects.filter(
    organization_id="org-uuid",
    rule_severity="critical",
    rule_status="failed",
)
```

## Management Command

Batch evaluation and persistence via Django management command:

```bash
# Evaluate single invoice (both GAAP and IFRS)
python manage.py evaluate_accounting_rules \
  --organization-id "org-uuid" \
  --invoice-id "invoice-uuid" \
  --standard BOTH

# Evaluate single report
python manage.py evaluate_accounting_rules \
  --organization-id "org-uuid" \
  --report-id "report-uuid" \
  --standard GAAP

# Evaluate all invoices in organization
python manage.py evaluate_accounting_rules \
  --organization-id "org-uuid" \
  --all-invoices \
  --standard IFRS

# Evaluate all reports
python manage.py evaluate_accounting_rules \
  --organization-id "org-uuid" \
  --all-reports \
  --standard BOTH
```

## Implementation Summary

### Files Created

**Models & Serializers:**
- `apps/auditing/models.py` — Added `AccountingRuleEvaluation` model (20 fields, 5 indexes)
- `apps/auditing/serializers.py` — 5 serializer classes for API responses

**API Layer:**
- `apps/auditing/views/accounting_rules_api.py` — 8 API views and function-based views
- `apps/auditing/views/__init__.py` — Updated with new view exports
- `apps/auditing/urls.py` — 8 new URL patterns

**Services & Integration:**
- `apps/auditing/accounting_rules/services.py` — Added 4 persistence functions
- `apps/auditing/accounting_rules/report_integration.py` — 4 report integration utilities

**Management:**
- `apps/auditing/management/commands/evaluate_accounting_rules.py` — Batch evaluation CLI

**Database:**
- `apps/auditing/migrations/0005_accountingruleevaluation.py` — Applied ✅

### Key Architecture Decisions

1. **Separate Persistence Functions**: Don't force persistence during evaluation — make it optional via `persist=True` parameter
2. **Organization Scoping**: All queries filtered by organization_id for tenant safety
3. **Lazy Evaluation**: Don't pre-calculate all scores — compute on-demand
4. **Denormalized Storage**: Store rule details directly (not just rule_id) for reporting speed
5. **CSV Export**: Built-in export for BI tools integration

## Next Steps (Tasks 4-5)

### Task 4: Direct Comparison Feature
- Implement frontend for `compare_ifrs_vs_gaap_findings()`
- Show side-by-side compliance scores
- Highlight stricter standard for each rule category

### Task 5: Configuration UI
- Django admin forms for policy overrides
- Tenant-specific materiality thresholds
- Per-rule enable/disable toggles

## Testing the Implementation

```bash
# Run existing accounting rules tests
pytest apps/auditing/tests/test_accounting_rules_engine.py -v
pytest apps/auditing/tests/test_accounting_rules_services.py -v

# Manual API test (using curl or Postman)
curl -X GET \
  "http://localhost:8000/auditor/invoices/550e8400-e29b-41d4-a716-446655440000/evaluate/gaap/" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Batch evaluation
python manage.py evaluate_accounting_rules \
  --organization-id "550e8400-e29b-41d4-a716-446655440002" \
  --all-invoices \
  --standard BOTH
```

## Troubleshooting

### Migration Issues
```bash
# If migration fails, check status
python manage.py showmigrations auditing

# Rollback if needed
python manage.py migrate auditing 0004_previous_migration
```

### API Permission Errors
- Ensure user is authenticated with valid JWT/session token
- Check `IsAuthenticated` permission classes
- Verify organization association via `request.user.organization`

### Persistence Issues
- Check organization_id is string UUID, not object
- Ensure invoice/report belongs to correct organization
- Verify all ForeignKey relationships exist before persist

## Performance Notes

- **Indexes**: 5 database indexes optimize common query patterns
- **Lazy Loading**: Rules are loaded on-demand via registry
- **Pagination**: Default 20 items per page to prevent OOM
- **Batch Operations**: Management command uses transactions for consistency
- **CSV Export**: Streams to StringIO, not in-memory list

## Security

- All endpoints require authentication
- Organization-scoped queries prevent cross-tenant access
- No raw SQL in services — uses ORM queryset
- Rule evaluation context doesn't leak sensitive data
- CSV export respects organization boundaries
