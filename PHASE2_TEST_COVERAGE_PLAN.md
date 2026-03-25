# Phase 2: Test Coverage Expansion Plan
**Objective:** Expand from 45% → 60%+ coverage (blocker for 90+ score)  
**Duration:** 40 hours over 2 weeks  
**Target Date:** April 8, 2026

---

## Coverage Breakdown

### Current State (45%)
- ✅ Rule engine unit tests (1103 lines) — apps/rule_engine/tests/
- ✅ ISA 700 opinion tests (27 test cases) — tests/test_isa700_opinion.py
- ✅ IAS 7 cash flow tests (25+ test cases) — tests/test_ias7_cashflow.py
- ❌ API endpoint integration tests — **MISSING**
- ❌ File upload pipeline tests — **MISSING**
- ❌ Report generation tests — **MISSING**
- ❌ Auth flow tests — **MISSING**
- ❌ Soft-delete operation tests — **MISSING**

### Target State (60%+)
- All of above ✅
- Plus integration tests for 5 core pipelines (below)

---

## Test Files to Create (5 Integration Suites)

### 1. **test_upload_pipeline.py** (8 hours)
**Testing:** Invoice file upload → validation → storage → report readiness

Requirements:
- [ ] PDF upload with OCR success path
- [ ] Image (JPG/PNG/TIFF) upload with Tesseract
- [ ] Excel (XLSX) upload with pandas parsing
- [ ] ZIP batch upload with bomb protection
- [ ] JSON structured data upload
- [ ] CSV bulk upload
- [ ] File size validation (max limits)
- [ ] MIME type validation
- [ ] Duplicate file detection
- [ ] Storage path creation
- [ ] Database transaction rollback on failure
- [ ] Error handling for corrupted files
- [ ] Permission checks (user can only upload to own org)

**Sample Test Class:**
```python
class TestInvoiceUploadPipeline:
    def test_pdf_upload_with_ocr(invoice_factory, org, user):
        # Create PDF, upload, verify OCR extraction
        pass
    
    def test_zip_bomb_rejected(org, user):
        # Create zip bomb, verify rejection
        pass
    
    def test_batch_upload_partial_failure(org, user):
        # Upload 3 files, 1 invalid, verify rollback
        pass
```

### 2. **test_report_generation.py** (10 hours)
**Testing:** Invoice audit report building → PDF export → bilingual output

Requirements:
- [ ] Report generation with 0 invoices (disclaimer opinion)
- [ ] Report with 1 invoice (basic sections)
- [ ] Report with 100+ invoices (performance + accuracy)
- [ ] All 15 report sections present:
  - report_header, summary, executive_summary
  - compliance_engine, high_risk_invoices, failed_rules_analysis
  - supplier_analysis, risk_analysis, anomalies
  - root_cause_analysis, key_audit_matters, isa700_auditor_opinion
  - ias7_cashflow_classification, ias7_cashflow_statement
  - actions_and_recommendations
- [ ] Bilingual output (Arabic + English)
- [ ] PDF export with WeasyPrint
- [ ] HTML export
- [ ] JSON structure validation
- [ ] DateTime serialization
- [ ] Decimal precision for amounts
- [ ] Risk score calculation accuracy
- [ ] ISA 700 opinion type determination (all 4 types)
- [ ] IAS 7 classification inclusion
- [ ] KAMs integration

**Sample Test Class:**
```python
class TestInvoiceAuditReportGeneration:
    def test_empty_report_generates_disclaimer(org, user):
        # 0 invoices → disclaimer opinion
        pass
    
    def test_all_sections_present(invoice_factory, org, user):
        # Create invoices, generate report, verify all 15 sections
        pass
    
    def test_pdf_export_without_errors(report_data):
        # Generate PDF, verify file size > 0, no corrupted output
        pass
```

### 3. **test_auth_flows.py** (8 hours)
**Testing:** Login → token issuance → permission checks → logout

Requirements:
- [ ] User registration with email verification
- [ ] Login success with valid credentials
- [ ] Login failure with invalid password
- [ ] Account lockout after 5 failed attempts
- [ ] Password reset flow
- [ ] JWT token generation
- [ ] Token refresh endpoint
- [ ] Token expiry validation
- [ ] Permission checks per role (7 roles):
  - admin, cao, senior_auditor, junior_auditor
  - compliance_officer, finance_manager, external_auditor
- [ ] Multi-tenant isolation (user can't see other org data)
- [ ] MFA verification (if enabled)
- [ ] Session management
- [ ] CSRF token validation
- [ ] Logout invalidates tokens

**Sample Test Class:**
```python
class TestAuthenticationFlows:
    def test_login_success_returns_jwt_tokens(user):
        # POST /auth/login, verify access + refresh tokens
        pass
    
    def test_permission_denied_for_wrong_role(invoice_factory, org, junior_auditor):
        # junior_auditor tries to approve invoice
        # Should return 403 Forbidden
        pass
    
    def test_cross_tenant_isolation(user_org1, user_org2, invoice_org1):
        # user_org2 tries to access invoice from org1
        # Should return 403 or 404
        pass
```

### 4. **test_api_endpoints.py** (10 hours)
**Testing:** REST API CRUD operations, filtering, pagination, soft-delete

Core Resources to Test:
- **Invoice Endpoints:** LIST, GET, UPDATE, DELETE (soft), APPROVE, REVALIDATE, DOWNLOAD
- **AuditSession Endpoints:** LIST, GET, UPDATE, DELETE (soft), PROGRESS
- **AuditCase Endpoints:** LIST, CREATE, GET, UPDATE, DELETE (soft), STATUS, ASSIGN
- **Document Endpoints:** LIST, GET, DELETE (soft)
- **Report Endpoints:** GENERATE, GET, DOWNLOAD, LIST

Requirements:
- [ ] GET /api/invoices/ with pagination
- [ ] GET /api/invoices/ with filters (status, risk_level, vendor_name)
- [ ] GET /api/invoices/ with search (invoice_number, vendor_name)
- [ ] GET /api/invoices/{id}/ returns 200
- [ ] GET /api/invoices/{id}/ returns 404 if soft-deleted
- [ ] PUT /api/invoices/{id}/ updates fields
- [ ] DELETE /api/invoices/{id}/ performs soft-delete
- [ ] GET /api/invoices/{id}/status shows is_deleted=true after delete
- [ ] POST /api/invoices/{id}/approve changes status
- [ ] GET /api/invoices/{id}/download returns file
- [ ] POST /api/invoices/upload with multipart file
- [ ] Similar for AuditSession, AuditCase, Document, Report endpoints
- [ ] Error responses (400, 403, 404, 409)
- [ ] Request validation (invalid JSON, missing required fields)
- [ ] Rate limiting on endpoints

**Sample Test Class:**
```python
class TestInvoiceAPIEndpoints:
    def test_list_invoices_with_pagination(org, invoice_factory):
        # GET /api/invoices/?page=1&page_size=20
        # Verify count, next, previous links
        pass
    
    def test_delete_invoice_soft_deletes(invoice_factory, org, user):
        # DELETE /api/invoices/{id}/ → 204 No Content
        # Verify is_deleted=True, deleted_by set, deleted_at set
        pass
    
    def test_deleted_invoice_not_in_list(invoice_factory, org, user):
        # Create invoice, delete, GET /api/invoices/
        # Verify deleted invoice not in list
        pass
```

### 5. **test_compliance_rules_engine.py** (4 hours)
**Testing:** All 30+ validation rules fire correctly

Requirements:
- [ ] INV-001: Invoice number present
- [ ] INV-002: Invoice date valid
- [ ] INV-003: Invoice date not in future
- [ ] VAT-001: VAT amount calculated correctly
- [ ] VAT-002: VAT rate valid (5%, 15%)
- [ ] DUP-001: Exact duplicate detection
- [ ] DUP-002: Fuzzy duplicate detection
- [ ] ANO-001: Amount anomalies (3x above average)
- [ ] ANO-002: Price anomalies (50% change)
- [ ] CTL-001: Vendor concentration (>40%)
- [ ] CTL-002: Account code exists
- [ ] CTL-003: Cost center exists
- [ ] DOC-001: Document is clear (not blurry)
- [ ] DOC-002: No alterations detected
- And all remaining 16+ rules...

**Sample Test Class:**
```python
class TestComplianceRulesEngine:
    def test_dup_exact_duplicate_detected(invoice_factory, org):
        # Create 2 identical invoices
        # DUP-001 should flag both
        pass
    
    def test_ano_amount_anomaly_flagged(invoice_factory, org):
        # Base: 1000, 1100, 900
        # New: 6000 (3x above average)
        # ANO-001 should flag
        pass
```

---

## Implementation Timeline

| Week | Task | Hours | Owner |
|------|------|-------|-------|
| 1 | test_upload_pipeline.py | 8h | Backend |
| 1 | test_report_generation.py | 10h | Backend/Reports |
| 2 | test_auth_flows.py | 8h | Backend/Auth |
| 2 | test_api_endpoints.py | 10h | API/Backend |
| 2 | test_compliance_rules_engine.py | 4h | Rules/BI |
| **Total** | | **40h** | |

---

## Coverage Targets by Dimension

| Dimension | Target | Method |
|-----------|--------|--------|
| **apps/** modules | 70%+ | Integration tests |
| **core/services/** | 75%+ | Unit + integration |
| **API endpoints** | 85%+ | Endpoint tests |
| **Models** | 80%+ | ORM operation tests |
| **Rule engine** | 95%+ | (Already achieved) |
| **Auth/RBAC** | 85%+ | Permission tests |
| **Overall** | **60%+** | Combined |

---

## Success Criteria

- ✅ All 40 hours of tests written and passing
- ✅ Coverage report shows 60%+ overall
- ✅ Coverage by file shows no file below 50% (except migrations)
- ✅ CI/CD pipeline runs all tests passing (pytest with --cov)
- ✅ No test flakiness (all tests pass consistently)
- ✅ Production score increases: 83 → 85

---

## Dependencies & Prerequisites

- [ ] pytest fixtures finalized (conftest.py complete)
- [ ] Test database configured (SQLite test DB)
- [ ] Coverage reporting setup (pytest-cov)
- [ ] CI/CD pipeline ready to run tests
- [ ] All Phase 1 code stable (no breaking changes)

---

## Risk Mitigation

**Risk:** Test code becomes code smell  
**Mitigation:** Use helper functions, factory patterns, fixtures to keep tests DRY

**Risk:** Long test execution time  
**Mitigation:** Mark slow tests with @pytest.mark.slow, run in parallel with pytest-xdist

**Risk:** Test data inconsistency  
**Mitigation:** Use database transactions to reset state between tests, use factories

**Risk:** External service dependencies (OpenAI, ZATCA)  
**Mitigation:** Mock all external calls (monkeypatch, unittest.mock)
