# ZATCA Phase 2 Technical Compliance Plan

## 1. Purpose
This document converts Tadgeeg's ZATCA Phase 2 promise into technical requirements, test cases, and evidence needed before enterprise claims.

## 2. Compliance Disclaimer
Do not claim full ZATCA production certification unless sandbox/production onboarding, signing, submission, certificate, and compliance evidence are complete.

Recommended public wording until evidence is complete:
> Tadgeeg is designed to support ZATCA Phase 2 validation and e-invoicing compliance workflows.

## 3. Required Components
1. Invoice data model.
2. Mandatory field validator.
3. VAT calculation validator.
4. QR/TLV reader and validator.
5. XML/UBL validation where applicable.
6. CSR generation.
7. Certificate onboarding.
8. Cryptographic signing.
9. Clearance/reporting integration.
10. Evidence storage.

## 4. Invoice Field Validation
| Field | Requirement |
|---|---|
| Invoice number | Required |
| Issue date/time | Required |
| Seller name | Required |
| Seller VAT number | Required |
| Buyer details | Required/conditional |
| Line items | Required |
| VAT rate | Required |
| VAT amount | Required |
| Total amount | Required |
| QR code | Required where applicable |
| XML/UBL payload | Required where applicable |

## 5. QR/TLV Validation
Checks:
- QR exists.
- QR readable.
- TLV tags complete.
- Seller name matches.
- VAT number matches.
- Timestamp matches.
- Total amount matches.
- VAT amount matches.
- Cryptographic stamp exists where applicable.

Example output:
```json
{
  "status": "failed",
  "errors": [
    {
      "field": "qr_total_amount",
      "message": "QR total does not match invoice total",
      "expected": "1150.00",
      "actual": "1100.00"
    }
  ]
}
```

## 6. CSR and Certificate Onboarding
Required flow:
1. Generate CSR.
2. Submit to ZATCA environment.
3. Receive compliance certificate.
4. Store certificate securely.
5. Associate certificate with organization/branch/device.
6. Validate signing.
7. Rotate certificates before expiry.

Security:
- Private keys must be encrypted.
- Keys must not be stored in plain text.
- Key usage must be logged.
- Access restricted to signing service.

## 7. Clearance and Reporting
Standard invoices may require clearance; simplified invoices may require reporting.  
The system must:
- Generate compliant payload.
- Sign invoice.
- Submit safely.
- Store response.
- Track accepted/rejected status.
- Retry only safe failures.

## 8. Status Model
| Status | Meaning |
|---|---|
| pending_validation | Waiting for validation |
| validation_failed | Local validation failed |
| ready_for_signing | Valid data |
| signing_failed | Signature issue |
| ready_for_submission | Signed |
| submitted | Sent |
| accepted | Accepted |
| rejected | Rejected |
| retry_pending | Temporary failure |
| manual_review | Needs review |

## 9. API Examples
`POST /api/v1/compliance/zatca/invoices/{id}/validate/`

`POST /api/v1/compliance/zatca/invoices/{id}/submit/`

Both endpoints must be tenant-scoped, permission-controlled, idempotent, and logged.

## 10. Evidence Storage
For each invoice:
- Original file.
- Extracted data.
- Normalized data.
- Validation result.
- QR/TLV result.
- XML/UBL payload.
- Signature/hash.
- ZATCA request.
- ZATCA response.
- Final status.
- Timestamp.

## 11. Required Tests
P0:
- Valid standard invoice.
- Valid simplified invoice.
- Missing VAT number.
- VAT mismatch.
- QR mismatch.
- Invalid TLV.
- Signing failure.
- Expired certificate.
- API timeout and retry.
- Duplicate submission prevention.

## 12. Readiness Checklist
| Item | Required |
|---|---|
| Sandbox configured | Yes |
| CSR tested | Yes |
| Certificate onboarding tested | Yes |
| Signing tested | Yes |
| QR/TLV tested | Yes |
| XML/UBL tested | Where applicable |
| Submission tested | Yes |
| Retry tested | Yes |
| Evidence stored | Yes |
| Compliance sign-off | Yes |
