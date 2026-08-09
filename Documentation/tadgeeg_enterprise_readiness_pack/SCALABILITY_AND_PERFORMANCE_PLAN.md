# Tadgeeg Scalability and Performance Plan

## 1. Purpose
Define how Tadgeeg should scale for large enterprise clients with hundreds of branches, high invoice volume, and continuous audit processing.

## 2. Target Scenario
- 400+ branches.
- Hundreds of thousands of invoices per day.
- Millions of monthly transactions.
- Multiple ERP/POS integrations.
- Executive dashboards.
- Near-real-time findings.

## 3. Scalability Principles
- Upload accepts quickly; processing happens asynchronously.
- Celery/worker queues handle heavy jobs.
- Workers scale horizontally.
- Reports generate asynchronously.
- Dashboards use indexed and aggregated data.
- Failures are recoverable.

## 4. Recommended Architecture
```text
Client/Web/API
  → Load Balancer/Nginx
  → Django Web
  → PostgreSQL + Object Storage
  → Redis
  → Celery Workers
  → OCR / AI / Rule Engine / Reports / Integrations
  → Monitoring + Logs + Alerts
```

## 5. Queue Design
| Queue | Purpose |
|---|---|
| ingestion | File parsing |
| ocr | OCR processing |
| audit | Rule engine |
| ai | Anomaly/forecasting |
| reports | PDF/Excel generation |
| integrations | ERP/ZATCA |
| notifications | Emails/alerts |

## 6. Performance Targets
| Operation | Target |
|---|---|
| Login | < 1s |
| Dashboard load | < 3s |
| Upload response | < 2s after accepting file |
| Standard invoice processing | 10-15s target where feasible |
| Bulk job creation | < 5s |
| Report generation small | < 30s |
| Large report | Async |
| Simple API p95 | < 500ms |

## 7. Bulk Upload Strategy
Required:
- BulkUploadJob.
- BulkUploadItem.
- Row/file-level status.
- Batch processing.
- Retry failed only.
- Progress endpoint.
- Final summary report.

Recommended batch sizes:
| Type | Batch |
|---|---|
| CSV | 500 rows |
| Excel | 200-500 rows |
| JSONL | 500 rows |
| ZIP files | 20-100 files |
| OCR images | 10-50 files |

## 8. Database Scaling
Required indexes:
- organization_id.
- document_type.
- created_at.
- status.
- audit_status.
- supplier/customer.
- invoice_number.
- external_id.
- branch_id.
- severity.
- rule_id.

Rules:
- No unbounded dashboard queries.
- Always tenant-scope queries.
- Use pagination.
- Use select_related/prefetch_related.
- Pre-aggregate executive KPIs.

## 9. Storage Scaling
- Use private object storage.
- Separate raw, processed, reports, temp, quarantine.
- Use lifecycle retention.
- Store metadata in DB.
- Do not store sensitive financial files in public static paths.

## 10. Load Testing Plan
| Level | Volume |
|---|---|
| Smoke | 100 invoices |
| Small | 1,000 invoices |
| Medium | 10,000 invoices |
| Large | 100,000 invoices |
| Stress | 500,000+ invoices |

Metrics:
- Upload response time.
- Queue wait time.
- OCR time.
- Audit time.
- Error rate.
- DB latency.
- Worker memory.
- Report time.

## 11. Observability
Dashboards:
- Web latency.
- Error rate.
- Queue length.
- Worker health.
- DB performance.
- Storage errors.
- ERP failures.
- ZATCA failures.
- Audit backlog.

Alerts:
- Web down.
- DB down.
- Redis down.
- Worker down.
- Queue backlog high.
- Upload failures spike.
- ZATCA failures spike.

## 12. Failure Recovery
- OCR failure marks extraction_failed.
- Audit failure stores error and allows retry.
- Worker crash retries safely.
- Bulk job supports partial success.
- ERP sync resumes from cursor.
- ZATCA retry uses idempotency.

## 13. Production Capacity Minimum
| Component | Minimum |
|---|---|
| Web containers | 2 |
| Celery workers | 2-4 |
| Redis | Dedicated/managed |
| PostgreSQL | Production managed DB |
| Object storage | Private |
| Monitoring | Enabled |
| Backups | Automated |

## 14. Enterprise Readiness
Before large enterprise sale:
- Complete 10,000 invoice test.
- Complete 100,000 invoice simulation.
- Test worker scaling.
- Test large report generation.
- Test dashboard performance.
- Test ZATCA failure handling.
- Enable monitoring.
