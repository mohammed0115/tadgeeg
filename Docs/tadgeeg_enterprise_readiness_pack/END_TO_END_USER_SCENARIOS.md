# Tadgeeg End-to-End User Scenarios

## 1. Purpose
Define user journeys to validate Tadgeeg from the user perspective.

## Scenario 1: Organization Setup
**Actor:** Organization Admin  
Steps:
1. Login.
2. Add company profile.
3. Add VAT number.
4. Add branches.
5. Invite users.
6. Assign roles.
7. Configure country/currency.
8. Save settings.
Expected:
- Organization ready.
- Tenant isolation active.
- Actions logged.

## Scenario 2: Single Invoice Upload and Audit
**Actor:** Accountant  
Steps:
1. Upload purchase invoice.
2. Validate file.
3. Extract data.
4. Normalize invoice.
5. Run rule engine.
6. Calculate VAT.
7. Check duplicates.
8. Create findings.
9. Generate report.
Expected:
- Audit runs once.
- Findings include evidence.
- Report protected.

## Scenario 3: Bulk Excel Upload
**Actor:** Accountant  
Steps:
1. Upload Excel with many invoices.
2. Create bulk job.
3. Create item per row.
4. Process batches.
5. Show progress.
6. List failed rows.
7. Retry failed rows.
8. Generate summary.
Expected:
- No timeout.
- Progress visible.
- Successful rows audited.

## Scenario 4: ZIP Upload
**Actor:** Accountant  
Steps:
1. Upload ZIP.
2. Validate size and security.
3. Extract files.
4. Route PDFs/images to OCR.
5. Route CSV/Excel/JSON to parser.
6. Audit all valid items.
Expected:
- No silent skipped files.
- Unsupported files reported.

## Scenario 5: Three-Way Matching
**Actor:** Auditor  
Steps:
1. Upload/sync PO.
2. Upload/sync GRN.
3. Upload invoice.
4. Match supplier, quantities, prices, totals.
5. Flag mismatch.
Expected:
- Missing PO/GRN flagged.
- Overbilling calculated.

## Scenario 6: Duplicate Detection
**Actor:** Auditor  
Steps:
1. Upload invoice.
2. Hash file.
3. Compare supplier+invoice number.
4. Compare amount/date.
5. Compare line items/text.
6. Produce duplicate score.
Expected:
- Matching documents linked.
- Decision logged.

## Scenario 7: VAT/ZATCA Validation
**Actor:** Compliance Officer  
Steps:
1. Extract VAT fields.
2. Recalculate VAT.
3. Validate mandatory fields.
4. Read QR/TLV.
5. Store evidence.
6. Generate compliance report.
Expected:
- Errors clear.
- Report generated.

## Scenario 8: Journal Entry Audit
**Actor:** Auditor  
Steps:
1. Import entries.
2. Validate account codes.
3. Check debit total.
4. Check credit total.
5. Verify balanced entry.
6. Check period.
Expected:
- Unbalanced entries flagged.

## Scenario 9: General Ledger Integrity
**Actor:** Finance Manager  
Steps:
1. Import ledger.
2. Read opening balance.
3. Read movements.
4. Read closing balance.
5. Validate rollforward.
Expected:
- Differences calculated.

## Scenario 10: Executive Dashboard
**Actor:** Executive  
Steps:
1. Login.
2. View documents processed.
3. View risk score.
4. View savings estimate.
5. View branch risk.
6. Download executive report.
Expected:
- Fast dashboard.
- Read-only access.

## Scenario 11: ERP API Integration
**Actor:** API Client  
Steps:
1. Create API key.
2. ERP sends invoice.
3. Validate key.
4. Check idempotency.
5. Queue audit.
6. Send webhook.
Expected:
- No duplicate retries.
- Logs visible.

## Scenario 12: Report Approval
**Actor:** Finance Manager  
Steps:
1. Generate report.
2. Auditor reviews.
3. Manager approves.
4. Version locked.
5. Download logged.
Expected:
- Approved report cannot silently change.

## Scenario 13: Unauthorized Access Prevention
**Actor:** Other organization user  
Steps:
1. Try direct document URL.
2. Try API report access.
3. Try download link.
Expected:
- 403/404.
- Attempt logged.
- No data leaked.

## Scenario 14: Failed Processing Recovery
**Actor:** Accountant  
Steps:
1. Upload poor scan.
2. OCR fails.
3. Status extraction_failed.
4. Retry with better copy.
Expected:
- Clear error.
- No duplicate findings.

## Scenario 15: Mobile Camera Upload
**Actor:** Accountant  
Steps:
1. Open mobile web.
2. Capture receipt.
3. Upload.
4. Validate quality.
5. Extract fields.
6. Correct low-confidence fields.
Expected:
- Mobile upload works.
- Corrections saved.

## UAT Checklist
| Area | Pass Criteria |
|---|---|
| Login | Secure |
| Upload | Supported files |
| OCR | Fields visible |
| Audit | Evidence-based |
| Reports | PDF/Excel |
| Permissions | Tenant isolation |
| Bulk | Progress/retry |
| Dashboard | Accurate KPIs |
| ERP API | Upload/webhook |
| ZATCA | Validation |
| Localization | Arabic/English |
