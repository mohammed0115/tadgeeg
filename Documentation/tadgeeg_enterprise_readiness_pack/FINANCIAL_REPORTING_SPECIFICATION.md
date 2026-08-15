# Tadgeeg Financial Reporting Specification

## 1. Purpose
Define required financial and audit reports, calculation logic, data sources, workflow, export formats, and validation expectations.

## 2. Reporting Principles
- Reports trace to source documents.
- Reports include evidence.
- Reports support Arabic and English.
- Calculations are rule-based and testable.
- AI summaries do not change numbers.
- Downloads are protected and logged.

## 3. Required Reports
| Report | Priority |
|---|---|
| Audit Summary | P0 |
| Detailed Findings | P0 |
| VAT Compliance | P0 |
| Duplicate Invoice | P0 |
| ZATCA Compliance | P0 |
| Three-Way Matching | P0 |
| General Ledger Integrity | P0 |
| Vendor Risk | P1 |
| Customer Risk | P1 |
| Branch KPI | P1 |
| P&L | P1 |
| Balance Sheet | P1 |
| Cash Flow Forecast | P1 |
| Bank Reconciliation | P1 |

## 4. Audit Summary Report
Sections:
- Executive summary.
- Period.
- Documents processed.
- Risk score.
- Findings by severity.
- Duplicate count.
- VAT/ZATCA exceptions.
- Estimated exposure.
- Recommendations.

KPIs:
- Total processed.
- Passed/failed.
- Critical/high findings.
- Estimated exposure.
- Compliance rate.
- Manual review count.

## 5. Detailed Findings Report
Fields:
- Finding ID.
- Document ID.
- Document type.
- Rule ID.
- Severity.
- Status.
- Description.
- Evidence.
- Financial impact.
- Recommendation.
- Reviewer.
- Resolution.

## 6. VAT Compliance Report
Sections:
- VAT summary.
- Taxable sales.
- Taxable purchases.
- VAT collected.
- VAT paid.
- Net VAT.
- VAT mismatches.
- Missing VAT numbers.
- ZATCA validation.

Formula:
```text
Net VAT = Output VAT - Input VAT
```

## 7. Duplicate Invoice Report
Evidence:
- Same supplier + invoice number.
- Same file hash.
- Same amount + date proximity.
- Similar line items.
- Similar OCR text.

## 8. Three-Way Matching Report
Checks:
- Supplier match.
- PO exists.
- GRN exists.
- Quantity match.
- Unit price match.
- Date sequence.
- Overbilling.

Statuses:
- matched.
- partial_match.
- failed.
- missing_po.
- missing_grn.

## 9. General Ledger Integrity Report
Checks:
- Debit equals credit.
- Opening + movements = closing.
- Valid account codes.
- Period posting rules.
- Unusual manual entries.
- Ledger reconciles with reports.

## 10. P&L Statement
Sections:
- Revenue.
- Cost of goods sold.
- Gross profit.
- Operating expenses.
- Operating income.
- Other income/expenses.
- Net profit.

Validation:
- Revenue reconciles with sales invoices.
- Expenses reconcile with purchase invoices.
- Payroll reconciles with payroll sheets.
- Journal adjustments documented.

## 11. Balance Sheet
Sections:
- Assets.
- Liabilities.
- Equity.

Validation:
- Assets = liabilities + equity.
- Bank balances reconcile.
- Receivables reconcile.
- Payables reconcile.
- Fixed assets reconcile.

## 12. Cash Flow Forecast
Sections:
- Current cash.
- Expected inflows.
- Expected outflows.
- 3/6/12-month forecast.
- Confidence interval.
- Risk warnings.
- Scenarios.

## 13. Approval Workflow
Statuses:
- draft.
- under_review.
- approved.
- rejected.
- exported.
- archived.

Approved reports should be locked or versioned.

## 14. Export Requirements
Formats:
- PDF.
- Excel.
- HTML.
- CSV.
- JSON API.

PDF:
- Branding.
- Page numbers.
- Timestamp.
- Confidentiality notice.
- Approval block.

Excel:
- Sheets.
- Filters.
- Totals.
- Currency formatting.
- Severity columns.

## 15. Test Requirements
- PDF Arabic renders correctly.
- PDF English renders correctly.
- Excel totals match DB.
- VAT report reconciles.
- Duplicate report catches known duplicates.
- Unauthorized user cannot download.
- Large report runs async.
