# FI-01 live multiformat progress

Environment: `DEBUG=False`, SQLite measurement database rebuilt by migrations, ordinary FI-01 organization/user, proxy host `8005-iz1529wxmqo4iepf7c9uy-23d09a65.sg1.manus.computer`, secure proxy header enabled.

## Confirmed invoice-upload UI results

| Format | Upload route | User action | Network evidence | Displayed extracted fields | Notes |
|---|---|---:|---|---|---|
| JSON | `/invoices/upload/` | One `Upload 1` click | One POST to `/auditor/upload/` | `XFMT-2026-001`; `Cross Format Supplier Ltd`; VAT `310123456700003`; 2026-08-15; subtotal 1000.00; VAT 150.00; total 1150.00; SAR | Structured row; first invoice, non-duplicate. |
| XLSX | `/invoices/upload/` | One `Upload 1` click | One POST to `/auditor/upload/` | Same financial fields as JSON | `Duplicate Invoice` is expected because the same logical invoice was deliberately uploaded after JSON; it is not duplicate POST evidence. |
| PDF | `/invoices/upload/` | One `Upload 1` click | One POST to `/auditor/upload/` | Same financial fields as JSON | `PDF Text Layer`; OCR confidence is 0% because the PDF has extractable text, not an OCR failure. |

The earlier documents-upload JSON test before this cleanup found two POSTs, which identified the second duplicate Alpine source in `templates/documents/upload.html`. That source was removed before this fresh run.

Remaining live work: PNG via invoice upload, a post-fix documents-upload request, page checks, and final database reset/documentation.

Reference browser URLs were all on the temporary 8005 proxy; screenshots and browser HTML are saved under `/home/ubuntu/screenshots/` and `/home/ubuntu/browser_html/`.

## Post-fix live results

| Entry point | Format | POST count from one click | Visible result |
|---|---|---:|---|
| Invoice upload (`/invoices/upload/`) | JSON | 1 | All reference fields displayed: XFMT-2026-001, supplier, VAT ID, date, 1000.00 / 150.00 / 1150.00 SAR. |
| Invoice upload | XLSX `Field | Value` | 1 | Same reference fields displayed. Duplicate-rule findings are expected because it is the same logical invoice uploaded after JSON. |
| Invoice upload | PDF | 1 | Same reference fields displayed using `PDF Text Layer`; OCR confidence 0% correctly represents text-layer extraction, not blank fields. |
| Invoice upload | PNG | 1 | Same reference fields displayed using `OCR Fallback (Tesseract)` at 95% confidence. |
| Documents upload (`/documents/upload/`) | JSON | 1 | Same reference fields displayed. This is the direct regression check for the second removed Alpine include. |

The documents-upload JSON was intentionally a repeat of the prior JSON fixture, so its duplicate findings are data-duplicate findings (`DUP-*`), not repeat-POST evidence. The decisive evidence is one stored `/auditor/upload/` POST per click in each row.

## List and dashboard verification

The ordinary-user dashboard rendered successfully under `DEBUG=False`, showing five invoices after the five intentional single-click uploads (four via invoice upload and one via documents upload). The invoices list also rendered successfully with exactly five rows (`All 5`, `Flagged 5`), each showing the expected vendor, date, and 1,150.00 SAR. This is consistent with one persisted invoice per intentional upload click after both Alpine includes were removed.

## Additional page checks

The ordinary-user session rendered these pages under `DEBUG=False` after the five intentional uploads: dashboard, invoices list, invoice detail, invoice-audit report, documents management, invoice upload, and documents upload. The invoice-audit report rendered a five-invoice sample and showed the duplicate findings that correspond to intentionally reusing the same logical fixture across formats. The documents management page rendered and showed five invoices. No access denial, JavaScript-blocking error, or duplicate row beyond the five intentional submissions was observed in these views.
