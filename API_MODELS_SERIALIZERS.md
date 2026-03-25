# Tadgeeg API Models, Serializers & Response Schemas

## INVOICE MODELS & SERIALIZERS

### Invoice Model
```python
class Invoice(BaseModel):
    # Identity
    invoice_number: str
    invoice_date: date
    due_date: Optional[date]
    
    # Counterparty
    vendor_name: str
    vendor_name_ar: str
    vendor_vat_number: str
    vendor_cr_number: str
    vendor_address: str
    vendor_phone: str
    customer_name: str
    customer_vat_number: str
    
    # Financial
    currency: str = "SAR"
    subtotal: Decimal
    vat_rate: Decimal (default: 15)
    vat_amount: Decimal
    discount: Decimal
    total_amount: Decimal
    line_items: List[dict]
    
    # ZATCA Compliance
    has_qr_code: bool
    qr_code_valid: bool
    qr_code_image: Optional[bytes]
    qr_code_data: Optional[dict]
    
    # Document Quality
    is_handwritten: bool
    is_clear: bool
    has_alterations: bool
    language: str
    ocr_confidence: float
    
    # Status & Risk
    status: str (pending|processing|validated|flagged|approved|rejected)
    risk_level: str (low|medium|high|critical)
    risk_score: float (0-100)
    risk_level_reason: Optional[str]
    ai_recommendations: List[str]
    ai_summary: Optional[str]
    is_duplicate: bool
    duplicate_of: Optional[Invoice] (self-reference)
    
    # Data
    raw_text: Optional[str]
    extracted_data: dict (contains normalized, file_hash, etc.)
    processing_error: Optional[str]
    
    # Metadata
    file: FileField
    original_filename: str
    file_size: int
    mime_type: str
    
    # User & Org
    organization: Organization (FK)
    uploaded_by: User (FK)
    approved_by: Optional[User] (FK)
    approved_at: Optional[datetime]
    rejected_reason: Optional[str]
    
    # Soft Delete (GDPR)
    is_deleted: bool
    deleted_at: Optional[datetime]
    deleted_by: Optional[User] (FK)
    
    # Relationships
    audit_session: Optional[AuditSession] (FK)
    batch: Optional[InvoiceBatch] (FK)
    validation: InvoiceValidationResult (reverse OneToOne)
    audit_events: InvoiceAuditEvent (reverse ForeignKey)
    audit_findings: AuditFinding (reverse ForeignKey)
    
    # Timestamps
    created_at: datetime (auto_now_add)
    updated_at: datetime (auto_now)
```

### InvoiceListSerializer
**Used By:** `InvoiceListView`
```python
{
  "id": "uuid",
  "invoice_number": "INV-2026-001",
  "invoice_date": "2026-01-15",
  "vendor_name": "ACME Corp",
  "vendor_vat_number": "310123456700003",
  "total_amount": "5000.00",
  "vat_amount": "750.00",
  "currency": "SAR",
  "status": "approved",
  "risk_level": "low",
  "risk_score": 15.5,
  "is_duplicate": false,
  "ocr_confidence": 95.2,
  "language": "ar",
  "has_qr_code": true,
  "uploaded_by_name": "Ahmed Ali",
  "original_filename": "invoice_001.pdf",
  "created_at": "2026-01-15T10:30:00Z",
  "audit_session_id": "uuid"
}
```

### InvoiceDetailSerializer
**Used By:** `InvoiceDetailView`  
**Fields:** All Invoice model fields + computed fields (file_url, uploaded_by_name, approved_by_name)

**Read-Only Fields:**
- id, organization, uploaded_by, created_at, updated_at
- risk_score, risk_level, is_duplicate, ocr_confidence
- raw_text, extracted_data, ai_summary
- qr_code_image, qr_code_data

**Updatable Fields:**
- vendor_name, vendor_vat_number, customer_name
- total_amount, vat_amount, discount
- invoice_date, due_date
- status (restrictions: can't set APPROVED manually)
- notes

---

### InvoiceValidationResult Model
```python
class InvoiceValidationResult(BaseModel):
    invoice: Invoice (OneToOneField)
    validation_score: float (0-100)
    passed_rules: List[str]
    failed_rule_codes: List[str]
    
    # Details: {rule_code: {passed: bool, message: str, severity: str}}
    validation_details: dict
    
    # Rule group results
    inv_passed: int
    inv_failed: int
    dup_passed: int
    dup_failed: int
    vat_passed: int
    vat_failed: int
    ano_passed: int
    ano_failed: int
    ctl_passed: int
    ctl_failed: int
    doc_passed: int
    doc_failed: int
    
    # Specific validations
    vat_rate_correct: bool
    vat_calculation_correct: bool
    vat_subtotal_correct: bool
    
    created_by: User (FK)
    created_at: datetime
```

### InvoiceValidationResultSerializer
```python
{
  "validation_score": 92.5,
  "passed_rules": ["INV-001", "INV-002", ...],
  "failed_rule_codes": ["DUP-001"],
  "validation_details": {
    "INV-001": {"passed": true, "message": "...", "severity": "info"},
    "DUP-001": {"passed": false, "message": "...", "severity": "high"}
  },
  "inv_passed": 10,
  "inv_failed": 0,
  "dup_passed": 3,
  "dup_failed": 1,
  "vat_passed": 4,
  "vat_failed": 0,
  "ano_passed": 5,
  "ano_failed": 2,
  "ctl_passed": 3,
  "ctl_failed": 0,
  "doc_passed": 2,
  "doc_failed": 0,
  "vat_rate_correct": true,
  "vat_calculation_correct": true,
  "vat_subtotal_correct": true
}
```

---

### InvoiceBatch Model
```python
class InvoiceBatch(BaseModel):
    batch_name: str
    status: str (pending|processing|completed|partial|failed)
    
    organization: Organization (FK)
    uploaded_by: User (FK)
    audit_session: Optional[AuditSession] (FK)
    
    total_files: int
    processed_files: int
    failed_files: int
    
    processing_log: List[dict] (results + errors)
    
    created_at: datetime
    completed_at: Optional[datetime]
```

### InvoiceBatchSerializer
```python
{
  "id": "uuid",
  "batch_name": "Monthly Invoices - Feb 2026",
  "status": "completed|partial|failed",
  "total_files": 100,
  "processed_files": 98,
  "failed_files": 2,
  "uploaded_by_name": "Ahmed Ali",
  "created_at": "2026-02-01T09:00:00Z",
  "completed_at": "2026-02-01T09:45:00Z",
  "audit_session_id": "uuid",
  "audit_session_status": "completed"
}
```

---

### VendorProfile Model
```python
class VendorProfile(BaseModel):
    organization: Organization (FK)
    vendor_name: str
    vendor_vat_number: str
    vendor_cr_number: str
    
    invoice_count: int
    total_amount: Decimal
    avg_invoice_amount: Decimal
    max_invoice_amount: Decimal
    flagged_count: int
    duplicate_count: int
    
    is_new: bool
    first_seen: date
    last_seen: date
    
    created_at: datetime
    updated_at: datetime
```

### VendorProfileSerializer
```python
{
  "vendor_name": "ACME Corp",
  "vendor_vat_number": "310123456700003",
  "vendor_cr_number": "1010123456",
  "invoice_count": 45,
  "total_amount": "225000.00",
  "avg_invoice_amount": "5000.00",
  "max_invoice_amount": "25000.00",
  "flagged_count": 3,
  "duplicate_count": 2,
  "is_new": false,
  "first_seen": "2025-01-15",
  "last_seen": "2026-02-20"
}
```

---

### InvoiceAuditEvent Model
```python
class InvoiceAuditEvent(BaseModel):
    invoice: Invoice (FK)
    event_type: str (uploaded|processed|validated|edited|reprocessed|approved|rejected|deleted)
    
    user: User (FK)
    description: str
    before_data: dict
    after_data: dict
    ip_address: Optional[str]
    
    timestamp: datetime (auto_now_add)
```

### InvoiceAuditEventSerializer
```python
{
  "id": "uuid",
  "event_type": "uploaded",
  "description": "Uploaded: invoice_001.pdf",
  "user_name": "Ahmed Ali",
  "before_data": {},
  "after_data": {"status": "processing"},
  "ip_address": "192.168.1.1",
  "timestamp": "2026-01-15T10:30:00Z"
}
```

---

## AUDIT MODELS & SERIALIZERS

### AuditCase Model
```python
class AuditCase(BaseModel):
    organization: Organization (FK)
    case_number: str (auto-generated)
    case_type: str (fraud|duplicate|compliance|data_quality|other)
    priority: str (low|medium|high|critical)
    status: str (open|in_progress|resolved|closed)
    severity: str (low|medium|high|critical)
    
    title: str
    description: str
    
    invoice: Optional[Invoice] (FK)
    transaction: Optional[Transaction] (FK)
    
    assigned_to: Optional[User] (FK)
    created_by: User (FK)
    resolved_by: Optional[User] (FK)
    
    resolution_notes: Optional[str]
    
    created_at: datetime
    resolved_at: Optional[datetime]
    
    # Soft Delete
    is_deleted: bool
    deleted_at: Optional[datetime]
    
    # Relationships
    comments: CaseComment (reverse ForeignKey)
```

### AuditCaseSerializer
```python
{
  "id": "uuid",
  "case_number": "CASE-2026-001",
  "case_type": "duplicate",
  "priority": "high",
  "status": "open",
  "severity": "high",
  "title": "Duplicate invoice detected",
  "description": "Invoice INV-2026-001 is duplicate of INV-2026-001A",
  "assigned_to_id": "uuid",
  "assigned_to_name": "Ahmed Ali",
  "created_by_name": "System",
  "created_at": "2026-02-20T10:00:00Z",
  "resolved_at": null,
  "resolution_notes": null,
  "is_deleted": false
}
```

---

### AuditSession Model
```python
class AuditSession(BaseModel):
    organization: Organization (FK)
    name: str
    status: str (pending|processing|completed|review_required|action_required)
    
    created_by: User (FK)
    created_at: datetime
    
    total_count: int
    processed_count: int
    error_count: int
    
    summary_payload: dict
    context: dict (metadata)
    
    # Soft Delete
    is_deleted: bool
    deleted_at: Optional[datetime]
    
    # Relationships
    invoice_batches: InvoiceBatch (reverse FK)
    findings: AuditFinding (reverse FK)
```

### AuditSessionSerializer
```python
{
  "id": "uuid",
  "name": "Monthly Invoices - Feb 2026",
  "organization": "uuid",
  "created_by": "uuid",
  "created_at": "2026-02-01T09:00:00Z",
  "status": "completed",
  "total_count": 100,
  "processed_count": 100,
  "error_count": 2
}
```

---

### AuditFinding Model
```python
class AuditFinding(BaseModel):
    audit_session: AuditSession (FK)
    organization: Organization (FK)
    
    code: str (e.g., "INV-001", "DUP-001")
    invoice: Optional[Invoice] (FK)
    
    severity: str (critical|high|medium|low)
    status: str (open|resolved|dismissed)
    
    description: str
    recommendation: Optional[str]
    
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: Optional[datetime]
    resolution: Optional[str]
```

### AuditFindingSerializer
```python
{
  "id": "uuid",
  "code": "DUP-001",
  "invoice_id": "uuid",
  "invoice_number": "INV-2026-001",
  "severity": "high",
  "status": "open",
  "description": "Duplicate invoice with previous submission",
  "recommendation": "Contact vendor to verify",
  "first_detected_at": "2026-02-01T09:30:00Z",
  "last_detected_at": "2026-02-01T09:30:00Z",
  "resolved_at": null
}
```

---

### CaseComment Model
```python
class CaseComment(BaseModel):
    case: AuditCase (FK)
    author: User (FK)
    text: str
    is_internal: bool
    created_at: datetime
```

### CaseCommentSerializer
```python
{
  "id": "uuid",
  "case_id": "uuid",
  "author": "uuid",
  "author_name": "Ahmed Ali",
  "text": "Review this with accounting department",
  "is_internal": false,
  "created_at": "2026-02-20T11:00:00Z"
}
```

---

## DOCUMENT MODELS & SERIALIZERS

### Document Model
```python
class Document(BaseModel):
    organization: Organization (FK)
    uploaded_by: User (FK)
    
    file: FileField
    original_filename: str
    file_size: int
    mime_type: str
    
    document_type: str (invoice|purchase_order|bank_statement|payroll|...)
    processing_status: str (pending|processing|completed|needs_review|failed)
    
    language: Optional[str]
    page_count: int
    notes: Optional[str]
    
    created_at: datetime
    updated_at: datetime
    
    # Relationships
    extracted_data: ExtractedData (reverse OneToOne)
    page_results: DocumentPageResult (reverse FK)
    analysis_result: DocumentAnalysisResult (reverse OneToOne)
```

### DocumentListSerializer
```python
{
  "id": "uuid",
  "original_filename": "PO-2026-001.pdf",
  "document_type": "purchase_order",
  "processing_status": "completed",
  "file_size": 245632,
  "language": "en",
  "page_count": 2,
  "uploaded_by_name": "Ahmed Ali",
  "created_at": "2026-02-20T14:30:00Z"
}
```

### DocumentSerializer
```python
{
  "id": "uuid",
  "organization": "uuid",
  "uploaded_by": "uuid",
  "file": "/api/v1/documents/{id}/download/",
  "original_filename": "PO-2026-001.pdf",
  "file_size": 245632,
  "mime_type": "application/pdf",
  "document_type": "purchase_order",
  "processing_status": "completed",
  "language": "en",
  "page_count": 2,
  "notes": "Purchase order for office supplies",
  "created_at": "2026-02-20T14:30:00Z",
  "updated_at": "2026-02-20T14:35:00Z",
  "extracted": {...ExtractedData...},
  "page_count": 2,
  "pages": [
    {"page": 1, "confidence": 0.95},
    {"page": 2, "confidence": 0.92}
  ]
}
```

---

### DocumentAnalysisResult Model
```python
class DocumentAnalysisResult(BaseModel):
    document: Document (OneToOneField)
    
    # Classification
    predicted_type: str
    confidence: float (0-1)
    
    # Extracted fields (dynamic JSON based on document_type)
    extracted_fields: dict
    
    # Risk Assessment
    risk_level: str (low|medium|high|critical)
    risk_score: float (0-100)
    is_duplicate: bool
    
    findings: List[Finding]
    
    processing_time_ms: int
    created_at: datetime
```

### DocumentAnalysisResultSerializer
```python
{
  "id": "uuid",
  "document_id": "uuid",
  "document_type": "purchase_order",
  "extracted_fields": {
    "po_number": "PO-2026-001",
    "vendor_name": "ACME Corp",
    "total_amount": "5000.00",
    "currency": "SAR",
    "line_items": [...]
  },
  "classification": {
    "confidence": 0.95,
    "predicted_type": "purchase_order"
  },
  "risk_level": "low",
  "risk_score": 12.5,
  "is_duplicate": false,
  "findings": [...],
  "processing_time_ms": 2345
}
```

---

### Typed Document Models (PurchaseOrder, BankStatement, etc.)

**PurchaseOrder Model:**
```python
{
  "po_number": "string",
  "vendor_name": "string",
  "vendor_address": "string",
  "vendor_contact": "string",
  "ship_to_location": "string",
  "ordered_date": "date",
  "required_delivery_date": "date",
  "currency": "string",
  "line_items": [
    {
      "description": "string",
      "qty": float,
      "unit_price": "decimal",
      "subtotal": "decimal",
      "vat_amount": "decimal",
      "total": "decimal"
    }
  ],
  "subtotal": "decimal",
  "vat_rate": float,
  "vat_amount": "decimal",
  "total_amount": "decimal",
  "status": "draft|pending|approved|received|closed"
}
```

**BankStatement Model:**
```python
{
  "statement_period_from": "date",
  "statement_period_to": "date",
  "account_number": "string",
  "bank_name": "string",
  "currency": "string",
  "opening_balance": "decimal",
  "closing_balance": "decimal",
  "total_credits": "decimal",
  "total_debits": "decimal",
  "transaction_count": int,
  "transactions": [...]
}
```

---

## CUSTOM RULE DEFINITION

### CustomRuleDefinition Model
```python
class CustomRuleDefinition(BaseModel):
    organization: Organization (FK)
    created_by: User (FK)
    
    name: str (e.g., "Custom Vendor Limit Rule")
    description: str
    rule_code: str
    standard: str (ISA_700|ISA_701|ISA_500|...)
    
    severity: str (low|medium|high|critical)
    
    # Rule evaluation logic (JSON or Python expression)
    condition: str (JSON condition or expression)
    
    is_active: bool
    version: int (auto-incremented on update)
    
    created_at: datetime
    updated_at: datetime
```

### CustomRuleDefinitionSerializer
```python
{
  "id": "uuid",
  "name": "Custom Vendor Limit Rule",
  "description": "Check invoice is within vendor limit",
  "rule_code": "CUS-001",
  "standard": "ISA_700",
  "severity": "high",
  "condition": "{'total_amount': {'max': 10000}}",
  "is_active": true,
  "version": 2,
  "created_at": "2026-01-01T10:00:00Z"
}
```

---

## PAGINATION & FILTERING BACKENDS

### Backends Used
- **DjangoFilterBackend** - Field-level filtering
- **SearchFilter** - Full-text search across specified fields
- **OrderingFilter** - Sorting by specified fields

### Example: InvoiceListView
```
GET /api/v1/invoices/?status=approved&risk_level=low&search=ACME&ordering=-created_at
```

**Applied Filters:**
```
- status__exact: approved
- risk_level__exact: low
- vendor_name__icontains: ACME
- invoice_number__icontains: ACME
- notes__icontains: ACME
- vendor_vat_number__icontains: ACME
- ordering: -created_at
```

### Pagination
```
GET /api/v1/invoices/?limit=50&offset=100
```

**Response Structure:**
```json
{
  "count": 500,
  "next": "https://api.tadgeeg.com/api/v1/invoices/?limit=50&offset=150",
  "previous": "https://api.tadgeeg.com/api/v1/invoices/?limit=50&offset=50",
  "results": [...]
}
```

---

## VALIDATION RULES (30 Total)

### Group 1: Invoice Header Validation (INV)
- **INV-001:** Invoice number is present and unique
- **INV-002:** Invoice date is valid and not in future
- **INV-003:** Due date is after invoice date (if present)
- **INV-004:** Vendor name is present
- **INV-005:** Total amount is positive

### Group 2: Duplicate Detection (DUP)
- **DUP-001:** Invoice not duplicate of recent invoices (30 days)
- **DUP-002:** Invoice amount consistent with vendor history
- **DUP-003:** Invoice number not previously processed
- **DUP-004:** Exact match fingerprint not found

### Group 3: VAT Validation (VAT)
- **VAT-001:** VAT calculation correct (min variance)
- **VAT-002:** VAT rate compliant with ZATCA (0%, 5%, 15%)
- **VAT-003:** Subtotal + VAT = Total (with rounding tolerance)
- **VAT-004:** Currency matches organization default

### Group 4: Anomaly Detection (ANO)
- **ANO-001:** Amount within vendor typical range (± std dev)
- **ANO-002:** No suspicious patterns detected (frequency)
- **ANO-003:** Invoice date is recent (not too old)
- **ANO-004:** Vendor exists in master data

### Group 5: Financial Controls (CTL)
- **CTL-001:** All mandatory fields present
- **CTL-002:** Currency is supported
- **CTL-003:** Amount is non-zero
- **CTL-004:** Invoice not already approved
- **CTL-005:** User has approval permission

### Group 6: Document Quality (DOC)
- **DOC-001:** Document is clear and readable (OCR confidence > 60%)
- **DOC-002:** No visible alterations detected
- **DOC-003:** QR code valid (if present)
- **DOC-004:** Document format supported
- **DOC-005:** File size within limits (≤ 50 MB)
- **DOC-006:** Language detected correctly

---

**Total:** 30 Rules  
**Grouped:** 6 Categories (INV, DUP, VAT, ANO, CTL, DOC)

