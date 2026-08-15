# Tadgeeg Security and Compliance Architecture

## 1. Purpose
Define the security architecture required for Tadgeeg because it processes sensitive financial documents and audit evidence.

## 2. Security Objectives
- Protect financial documents.
- Enforce tenant isolation.
- Secure uploads/downloads/APIs.
- Maintain audit trails.
- Protect credentials, certificates, and encryption keys.
- Support enterprise security review.
- Prevent public exposure of media files.

## 3. Threat Model
| Threat | Severity |
|---|---|
| Cross-tenant access | Critical |
| Public financial files | Critical |
| Malicious uploads | High |
| API credential leakage | Critical |
| Unauthorized report downloads | High |
| ZATCA key compromise | Critical |
| Audit log tampering | High |
| Insider misuse | High |

## 4. Identity and Access
Required:
- RBAC.
- Organization-based tenant isolation.
- Branch-level access.
- MFA for enterprise admins.
- Scoped API keys.
- Session expiration.
- Admin action logging.

## 5. Tenant Isolation
Rules:
- Every financial query filters by organization.
- Every background job includes organization_id.
- Every file download validates ownership.
- Reports are generated in tenant scope.
- Cross-tenant attempts return 403/404 and are logged.

## 6. File Security
Upload controls:
- Extension validation.
- MIME validation.
- Magic-byte validation.
- Size limit.
- Malware scan.
- Password-protected file handling.
- Macro detection for Excel.
- ZIP-slip protection.
- Decompression bomb protection.

Storage controls:
- Financial files must be private.
- No public `/media/` for sensitive documents.
- Use protected download endpoints or signed URLs.
- Download events must be logged.

## 7. Encryption
In transit:
- HTTPS only.
- TLS 1.2+.
- HSTS.
- Secure cookies.

At rest:
- Database encryption where available.
- Object storage encryption.
- Encrypted backups.
- Encrypted certificates and secrets.

## 8. Secrets Management
Never store secrets in code or Docker image.  
Secrets include:
- Django secret key.
- DB password.
- ERP credentials.
- API keys.
- ZATCA certificates.
- S3 credentials.
- JWT signing keys.

Use environment variables for small deployments and Secrets Manager/Vault/KMS for enterprise.

## 9. Audit Logging
Log:
- Login/logout.
- Failed login.
- Upload.
- Download.
- Audit run.
- Finding status change.
- Report generation/download.
- API key creation.
- ERP sync.
- ZATCA submission.
- Admin settings change.

Fields:
- actor.
- organization.
- action.
- object_type.
- object_id.
- IP address.
- user agent.
- timestamp.
- metadata.

## 10. API Security
- Authentication for all financial endpoints.
- API rate limiting.
- Input validation.
- Request size limit.
- Webhook signature validation.
- Replay protection.
- Mask sensitive errors.
- CORS restriction.

## 11. Compliance Alignment
ISO 27001 evidence:
- Access control.
- Cryptography.
- Operations security.
- Incident management.
- Business continuity.

SOC 2 evidence:
- Security controls.
- Availability monitoring.
- Confidentiality safeguards.
- Processing integrity.
- Privacy controls.

## 12. Data Residency
If claiming Saudi data residency:
- DB must be hosted in Saudi-approved region.
- Object storage in approved region.
- Backups remain in approved region.
- Logs must not export sensitive data outside policy.

## 13. Backup and Disaster Recovery
Required:
- Daily DB backups.
- Object storage backup/versioning.
- Encrypted backups.
- Restore tests.
- RPO/RTO targets.
- Quarterly DR drill.

## 14. Incident Response
Steps:
1. Detect.
2. Contain.
3. Investigate.
4. Eradicate.
5. Recover.
6. Notify if required.
7. Post-incident review.

## 15. Security Testing
Required tests:
- Cross-tenant access.
- Broken object-level authorization.
- File upload attacks.
- ZIP-slip.
- Malware simulation.
- API rate limits.
- SQL injection.
- XSS.
- CSRF.
- Sensitive file exposure.

## 16. Production Checklist
| Item | Required |
|---|---|
| DEBUG disabled | Yes |
| Media private | Yes |
| HTTPS enabled | Yes |
| Secrets externalized | Yes |
| Tenant tests pass | Yes |
| Audit logs enabled | Yes |
| Backups encrypted | Yes |
| Malware scanning enabled | Yes |
| Vulnerability scan complete | Yes |
