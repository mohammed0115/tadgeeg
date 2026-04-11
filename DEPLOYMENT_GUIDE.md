# Tadgeeg UAT Fix Deployment Guide
Generated: April 11, 2026

## Files Changed (12 files)

### Backend Python
| File | Bugs Fixed |
|------|-----------|
| apps/auditing/views/upload.py | F-01 (ZIP crash), F-04 (null name), F-14/15 (stuck state) |
| apps/auditing/repositories/document_repository.py | F-04 (null name guard) |
| apps/auditing/forms.py | F-12/13 (language field rename) |
| core/services/ocr_service.py | F-09 (TRN extraction), F-10 (QR prompt) |
| core/services/detection/duplicate_detector.py | F-11 (key aliasing, file_hash path) |
| core/services/qr_scanner.py | F-10 (NEW: pyzbar QR scanner service) |
| finai_backend/settings.py | F-12/13 (language cookie persistence) |

### Templates
| File | Bugs Fixed |
|------|-----------|
| templates/auditing/result.html | F-04 (null name display) |
| templates/auditing/upload.html | F-12/13 (doc_language field), F-14/15 (state machine), F-19 (upload toast) |
| templates/dashboard/index.html | F-02, F-03, F-07, F-16, F-22, F-23, F-24, F-25 |
| templates/invoices/detail.html | F-05, F-06, F-21 |
| templates/base.html | F-20, F-26 |

## Deployment Steps

1. Back up current files before replacing
2. Copy files to their respective paths in your project root
3. For qr_scanner.py (NEW file): install dependency if not present:
   pip install pyzbar
4. Restart the application server:
   sudo systemctl restart gunicorn
5. Verify with smoke tests:
   bash scripts/smoke_tests.sh

## Testing Checklist

### Sprint 1 — Critical
- [ ] F-01: Upload a ZIP file → should not crash, returns success
- [ ] F-02: Dashboard compliance % matches invoice sections
- [ ] F-03: Dashboard growth shows "No baseline data" when 0 invoices
- [ ] F-04: Upload a file → name shows correctly, not "- null"
- [ ] F-05: Invoice with empty fields → score shows "Pending extraction"
- [ ] F-06: Invoice with critical errors → Approve button is disabled
- [ ] F-07: Dashboard with 0 invoices → Industry Benchmark section hidden

### Sprint 2 — High
- [ ] F-09: Invoice PDF with TRN → TRN extracted correctly
- [ ] F-11: Upload same invoice twice → flagged as duplicate
- [ ] F-12: Switch to English → stays English after uploading
- [ ] F-14: Upload form submitting → button resets after 90s timeout
- [ ] F-19: After upload → green confirmation toast appears

### Sprint 3 — Medium
- [ ] F-16: After upload → dashboard metrics refresh within 30s
- [ ] F-20: Navigate between sections → sidebar highlights correctly
- [ ] F-21: Approve invoice → no false error message
- [ ] F-22: Dashboard → SAR 0 replaced with em-dash when no data
- [ ] F-23: Empty cash flow chart → shows "No data available" message
- [ ] F-24: No alerts → shows "No alerts at this time" message
- [ ] F-25: Big Four 0% → shows upload guidance message
- [ ] F-26: Long email in sidebar → full text with tooltip, no clipping
