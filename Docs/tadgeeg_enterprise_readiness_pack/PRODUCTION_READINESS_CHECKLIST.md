# Tadgeeg Production Readiness Checklist

## 1. Purpose
Minimum checklist before Tadgeeg is used in enterprise pilot or production.

## 2. Readiness Levels
| Level | Meaning |
|---|---|
| Not Ready | Critical gaps remain |
| Pilot Ready | Controlled pilot only |
| Enterprise Ready | Production client use |
| Regulated Enterprise Ready | Strong compliance/security evidence |

## 3. Application
| Item | Required | Status |
|---|---|---|
| DEBUG disabled | Yes | TBD |
| Secrets externalized | Yes | TBD |
| Allowed hosts configured | Yes | TBD |
| CORS restricted | Yes | TBD |
| Media private | Yes | TBD |
| Error pages configured | Yes | TBD |
| Admin restricted | Yes | TBD |

## 4. Database
| Item | Required | Status |
|---|---|---|
| PostgreSQL production DB | Yes | TBD |
| Migrations clean | Yes | TBD |
| No destructive startup SQL | Yes | TBD |
| Backups enabled | Yes | TBD |
| Restore tested | Yes | TBD |
| Indexes exist | Yes | TBD |
| Tenant isolation enforced | Yes | TBD |

## 5. Celery/Redis
| Item | Required | Status |
|---|---|---|
| Redis configured | Yes | TBD |
| Worker running | Yes | TBD |
| Beat configured | If scheduled | TBD |
| Retry policy | Yes | TBD |
| Failed task visibility | Yes | TBD |
| Idempotent audit jobs | Yes | TBD |
| Worker monitoring | Yes | TBD |

## 6. File Upload Security
| Item | Required | Status |
|---|---|---|
| Extension validation | Yes | TBD |
| MIME validation | Yes | TBD |
| Magic-byte validation | Yes | TBD |
| Malware scan | Yes | TBD |
| ZIP-slip protection | Yes | TBD |
| Decompression protection | Yes | TBD |
| Password file handling | Yes | TBD |
| Macro detection | Recommended | TBD |

## 7. Audit Engine
| Item | Required | Status |
|---|---|---|
| One canonical pipeline | Yes | TBD |
| Rule catalog validation | Yes | TBD |
| No missing active implementation | Yes | TBD |
| No fake active stub | Yes | TBD |
| Evidence per finding | Yes | TBD |
| Rule tests | Yes | TBD |
| Duplicate audit prevention | Yes | TBD |

## 8. Document Coverage
| Type | Upload | Normalize | Audit | Report | API |
|---|---|---|---|---|---|
| Sales invoice | TBD | TBD | TBD | TBD | TBD |
| Purchase invoice | TBD | TBD | TBD | TBD | TBD |
| Purchase order | TBD | TBD | TBD | TBD | TBD |
| GRN | TBD | TBD | TBD | TBD | TBD |
| Payment voucher | TBD | TBD | TBD | TBD | TBD |
| Receipt voucher | TBD | TBD | TBD | TBD | TBD |
| Cash voucher | TBD | TBD | TBD | TBD | TBD |
| Bank statement | TBD | TBD | TBD | TBD | TBD |
| Journal entry | TBD | TBD | TBD | TBD | TBD |
| General ledger | TBD | TBD | TBD | TBD | TBD |
| Ledger | TBD | TBD | TBD | TBD | TBD |
| Contract | TBD | TBD | TBD | TBD | TBD |
| Supplier statement | TBD | TBD | TBD | TBD | TBD |
| Customer statement | TBD | TBD | TBD | TBD | TBD |

## 9. Security
| Item | Required | Status |
|---|---|---|
| RBAC | Yes | TBD |
| Tenant tests | Yes | TBD |
| API auth | Yes | TBD |
| Rate limiting | Yes | TBD |
| Audit logs | Yes | TBD |
| HTTPS | Yes | TBD |
| Vulnerability scan | Yes | TBD |
| Pen test | Recommended | TBD |

## 10. ZATCA
| Item | Required | Status |
|---|---|---|
| VAT validation | Yes | TBD |
| Mandatory fields | Yes | TBD |
| QR/TLV validation | Yes | TBD |
| XML/UBL validation | If applicable | TBD |
| CSR generation | If integrating | TBD |
| Certificate onboarding | If integrating | TBD |
| Signing | If integrating | TBD |
| Sandbox evidence | Yes before claim | TBD |

## 11. AI Validation
| Item | Required | Status |
|---|---|---|
| OCR dataset | Yes | TBD |
| Field accuracy report | Yes | TBD |
| Handwriting dataset | If claimed | TBD |
| Fraud dataset | If claimed | TBD |
| Forecast backtesting | If claimed | TBD |
| False positive analysis | Yes | TBD |
| False negative analysis | Yes | TBD |
| Approval sign-off | Yes | TBD |

## 12. Performance
| Item | Required | Status |
|---|---|---|
| 1,000 invoice test | Yes | TBD |
| 10,000 invoice test | Recommended | TBD |
| 100,000 simulation | Enterprise | TBD |
| Dashboard performance | Yes | TBD |
| Report generation | Yes | TBD |
| Worker scaling | Yes | TBD |
| Monitoring | Yes | TBD |

## 13. Reporting
| Item | Required | Status |
|---|---|---|
| Audit summary | Yes | TBD |
| Detailed findings | Yes | TBD |
| VAT report | Yes | TBD |
| Duplicate report | Yes | TBD |
| ZATCA report | Yes | TBD |
| PDF export | Yes | TBD |
| Excel export | Yes | TBD |
| Arabic rendering | Yes | TBD |
| English rendering | Yes | TBD |

## 14. Localization
| Item | Required | Status |
|---|---|---|
| Arabic UI | Yes | TBD |
| English UI | Yes | TBD |
| Dynamic RTL/LTR | Yes | TBD |
| Translated reports | Yes | TBD |
| Translated errors | Yes | TBD |

## 15. Pilot Ready When
- Tenant isolation passes.
- Secure upload works.
- Invoice audit works end-to-end.
- Reports generate.
- Audit logs exist.
- Celery/Redis work.
- No public media exposure.
- Backup enabled.
- Limitations documented.

## 16. Enterprise Ready When
- All P0 document types supported.
- Rule engine validated.
- ZATCA sandbox evidence exists.
- Security review complete.
- Load test complete.
- AI claims validated.
- API contracts documented.
- ERP path tested.
- Monitoring live.
- Backup/restore tested.

## 17. Risk Register
| Risk | Severity | Mitigation |
|---|---|---|
| Public files | Critical | Private storage |
| Missing rules | Critical | Catalog validation |
| Celery absent | Critical | Docker services |
| AI claims unvalidated | High | Validation report |
| ZATCA without evidence | High | Sandbox pack |
| Bulk timeout | High | Async jobs |
| Cross-tenant access | Critical | Permission tests |
| Report errors | High | Reconciliation tests |
