# API Error Handling & Implementation Patterns

## ERROR RESPONSE CODES & PATTERNS

### Success Codes

| Code | Status | Use Case |
|------|--------|----------|
| **200** | OK | GET, PATCH requests successful |
| **201** | Created | POST requests successful (resource created) |
| **202** | Accepted | Async request queued (e.g., document analysis) |
| **204** | No Content | DELETE successful, no body to return |

---

### Client Error Codes (4xx)

#### 400 Bad Request
**When:** Invalid input, missing required fields, validation failure

**Response Format:**
```json
{
  "error": "Required field missing or invalid",
  "detail": "Field 'vendor_name' is required",
  "fields": {
    "vendor_name": ["This field may not be blank."],
    "total_amount": ["Ensure this value is greater than or equal to 0."]
  }
}
```

**Examples:**
- Missing required field in request body
- Invalid query parameter value
- Malformed JSON in request
- Date format invalid (expected YYYY-MM-DD)
- Amount format invalid (should be numeric)

---

#### 401 Unauthorized
**When:** No valid authentication token provided

**Response:**
```json
{
  "detail": "Authentication credentials were not provided."
}
```

**Solution:**
- Include `Authorization: Bearer <token>` header
- Request new token via login endpoint

---

#### 403 Forbidden
**When:** Authenticated user lacks permission

**Response:**
```json
{
  "detail": "You do not have permission to perform this action."
}
```

**Common Cases:**
- User not IsSeniorAuditorOrAbove (trying to approve)
- User not IsOwnOrganization (accessing other org's data)
- User trying to edit approved invoice (CTL-004)

**Permissions Matrix:**

| Endpoint | Required Permission | Note |
|----------|-------------------|------|
| POST /invoices/upload/ | IsAuthenticated | Any authenticated user |
| PATCH /invoices/{id}/ | IsAuthenticated, IsOwnOrganization | Can't edit if APPROVED |
| DELETE /invoices/{id}/ | IsAuthenticated, IsOwnOrganization | Soft-delete |
| POST /invoices/{id}/approve/ | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| PATCH /invoices/{id}/review/ | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| PATCH /audit/cases/{id}/status/ | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |
| POST /audit/cases/bulk/ | IsAuthenticated, IsSeniorAuditorOrAbove | Senior Auditor+ |

---

#### 404 Not Found
**When:** Resource doesn't exist or is soft-deleted

**Response:**
```json
{
  "error": "Invoice not found.",
  "detail": "No resource found with ID: <uuid>"
}
```

**Note:** Soft-deleted resources return 404 (not visible in normal queries)

---

#### 409 Conflict
**When:** Request conflicts with current state

**Response:**
```json
{
  "error": "Document is already being processed.",
  "status": "processing"
}
```

**Examples:**
- Document already processing
- Cannot modify approved invoice
- Conflicting state transition

---

#### 422 Unprocessable Entity
**When:** Validation fails at business logic level

**Response:**
```json
{
  "error": "Validation failed",
  "errors": {
    "date_comparison": "Due date must be after invoice date",
    "amount_consistency": "Total amount exceeds vendor limit by 250%"
  }
}
```

**Validation Examples:**
- Date validation: due_date < invoice_date
- Amount validation: amount exceeds vendor history range
- Currency mismatch
- Invoice already approved

---

### Server Error Codes (5xx)

#### 500 Internal Server Error
**When:** Unexpected server error

**Response:**
```json
{
  "error": "An error occurred while processing your request",
  "request_id": "uuid"
}
```

**Action:** Contact support with request_id

---

#### 503 Service Unavailable
**When:** Service temporarily down (async processor failed)

**Response:**
```json
{
  "error": "Document processing service temporarily unavailable",
  "retry_after": 60
}
```

---

## SOFT-DELETE IMPLEMENTATION

### Pattern Overview

**Soft-delete** = logical delete (mark as deleted) without hard delete  
**Reason:** GDPR Article 17 compliance, audit trail preservation, data recovery

### Models with Soft-Delete

```python
# Invoice, AuditCase, AuditSession, Document

class SoftDeletableModel(models.Model):
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True)
    
    class Meta:
        abstract = True
```

### Soft-Delete in Views

**Example: InvoiceDetailView.perform_destroy()**
```python
def perform_destroy(self, instance):
    """Soft delete: mark as deleted with audit trail (GDPR Article 17)."""
    instance.is_deleted = True
    instance.deleted_at = timezone.now()
    instance.deleted_by = self.request.user
    instance.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'updated_at'])
    
    # Log deletion in audit trail
    _save_audit_event(
        instance, 
        self.request.user, 
        InvoiceAuditEvent.EventType.DELETED,
        f"Invoice soft-deleted by {self.request.user.full_name} (GDPR Article 17)",
        request=self.request
    )
```

### Filtering Soft-Deleted Records

**In QuerySets (all views):**
```python
def get_queryset(self):
    return Invoice.objects.filter(
        organization=self.request.user.organization,
        is_deleted=False  # Exclude soft-deleted
    )
```

**Result:** Deleted invoices return 404 when accessed directly

### Audit Trail Entry

**Event Type:** DELETED  
**Description:** "Invoice soft-deleted by <user> (GDPR Article 17)"

**Preserved Data:**
- Original invoice ID (UUID)
- User who deleted (with name, email)
- Deletion timestamp
- Before/after data
- IP address
- All original fields remain in database

---

## VALIDATION RULE ENGINE

### 30 Rules Organized by Group

**Processing Flow:**
```
Invoice Upload
    ↓
1. File Parsing & OCR
    ↓
2. AI Extraction (vendor, amount, date)
    ↓
3. Normalization (canonical format)
    ↓
4. Run All 30 Rules (Groups below)
    ↓
5. Calculate Validation Score (pass % + penalties)
    ↓
6. Persist InvoiceValidationResult
    ↓
7. Risk Assessment (AI score merge)
    ↓
8. Final Status Assignment
```

### Group 1: INV (Invoice Header) - 5 Rules
```python
"INV-001": "Invoice number is present and unique within 90 days",
"INV-002": "Invoice date is valid and not in the future",
"INV-003": "Due date is after or equal to invoice date",
"INV-004": "Vendor name is present and non-empty",
"INV-005": "Total amount is present and greater than zero",
```

### Group 2: DUP (Duplicate Detection) - 4 Rules
```python
"DUP-001": "Invoice not flagged as duplicate within 30 days",
"DUP-002": "Invoice amount within vendor history range (±50%)",
"DUP-003": "Invoice number not previously processed by org",
"DUP-004": "File hash checksum doesn't match recent invoices",
```

### Group 3: VAT (VAT Compliance) - 4 Rules
```python
"VAT-001": "VAT amount = Subtotal × Rate (with tolerance)",
"VAT-002": "VAT rate is ZATCA-compliant (0%, 5%, 15%)",
"VAT-003": "Subtotal + VAT = Total (rounding tolerance ±1)",
"VAT-004": "Currency matches organization default (SAR)",
```

### Group 4: ANO (Anomaly Detection) - 4 Rules
```python
"ANO-001": "Amount within vendor typical range (mean ± 3σ)",
"ANO-002": "Invoice frequency not abnormally high (> 10/day)",
"ANO-003": "Invoice date recent (not older than 6 months)",
"ANO-004": "Vendor exists in master data (known vendor)",
```

### Group 5: CTL (Financial Controls) - 3 Rules
```python
"CTL-001": "All mandatory fields present (vendor, amount, date)",
"CTL-002": "Currency is on organization's supported list",
"CTL-003": "Invoice not already approved/rejected",
```

### Group 6: DOC (Document Quality) - 6 Rules
```python
"DOC-001": "Document is clear and readable (OCR confidence > 60%)",
"DOC-002": "No visible alterations or tampering detected",
"DOC-003": "QR code present and valid (if required)",
"DOC-004": "Supported file format (PDF, image, etc.)",
"DOC-005": "File size within limits (≤ 50 MB)",
"DOC-006": "Language correctly detected",
```

### Scoring Calculation

**Formula:**
```
validation_score = (passed_rules / total_rules) × 100
                 - penalty_multiplier

where:
  total_rules = 30
  penalty_multiplier = severity_weight × failed_count
  
severity levels:
  - low: 0.5 points
  - medium: 1.0 points
  - high: 2.0 points
  - critical: 5.0 points
```

**Examples:**
- All passed: 100%
- 28/30 passed (2 low severity): 93% - (2 × 0.5) = 92%
- 25/30 passed (5 medium): 83% - (5 × 1.0) = 78%

### Response Format

**ValidationResult Payload:**
```json
{
  "validation_score": 92.5,
  "passed_rules": ["INV-001", "INV-002", "VAT-001"],
  "failed_rule_codes": ["DUP-001", "DOC-001"],
  "validation_details": {
    "INV-001": {
      "passed": true,
      "message": "Invoice number INV-2026-001 is unique",
      "severity": "info"
    },
    "DUP-001": {
      "passed": false,
      "message": "Invoice matches 1 recent submission (80% similarity)",
      "severity": "high",
      "duplicate_id": "uuid"
    }
  },
  "inv_passed": 4,
  "inv_failed": 1,
  "dup_passed": 3,
  "dup_failed": 1,
  "vat_passed": 4,
  "vat_failed": 0,
  "ano_passed": 4,
  "ano_failed": 0,
  "ctl_passed": 3,
  "ctl_failed": 0,
  "doc_passed": 5,
  "doc_failed": 1,
  "findings_summary": {
    "critical": 0,
    "high": 1,
    "medium": 0,
    "low": 1
  }
}
```

---

## RISK SCORING MODEL

### Risk Levels
| Level | Score Range | Meaning |
|-------|-------------|---------|
| **Low** | 0-40 | Safe to approve |
| **Medium** | 40-70 | Review recommended |
| **High** | 70-85 | Manual review required |
| **Critical** | 85-100 | Block and investigate |

### Score Calculation

**Inputs:**
1. **Validation Score** (0-100) - Rules compliance
2. **AI Risk Score** (0-100) - ML anomaly detection
3. **Fraud Score** (0-100) - Financial AI fraud detection
4. **Vendor Risk** (0-100) - Vendor history factors

**Formula:**
```python
# Max score from multiple sources
final_risk_score = max(
    validation_risk,     # 100 - validation_score
    ai_risk_score,       # ML model output
    fraud_score,         # Fraud detection output
    vendor_risk_score    # Vendor history analysis
)

# Apply multipliers based on invoice characteristics
if is_new_vendor:
    final_risk_score *= 1.3  # 30% penalty for new vendors
if is_large_amount:  # > vendor avg × 2
    final_risk_score *= 1.2  # 20% penalty
if has_alterations:
    final_risk_score *= 1.5  # 50% penalty
if is_handwritten:
    final_risk_score *= 1.1  # 10% penalty

# Cap at 100
final_risk_score = min(final_risk_score, 100)
```

### Risk Level Assignment

```python
if final_risk_score >= 85:
    risk_level = "critical"
elif final_risk_score >= 70:
    risk_level = "high"
elif final_risk_score >= 40:
    risk_level = "medium"
else:
    risk_level = "low"
```

### Response Example

```json
{
  "risk_score": 72.5,
  "risk_level": "high",
  "risk_level_reason": "High amount (200% of vendor avg) + New vendor",
  "contributing_factors": {
    "validation_risk": 25.0,
    "ai_risk": 45.5,
    "fraud_score": 15.0,
    "vendor_risk": 20.0,
    "new_vendor_multiplier": 1.3,
    "large_amount_multiplier": 1.2
  },
  "ai_recommendations": [
    "Contact vendor to verify amount",
    "Check purchase order matches",
    "Review with budget owner"
  ]
}
```

---

## IMPLEMENTATION PATTERNS

### Pattern 1: List Operations with Filters

**Endpoint:** `GET /api/v1/invoices/?status=approved&risk_level=low&search=ACME`

**Implementation:**
```python
class InvoiceListView(generics.ListAPIView):
    serializer_class = InvoiceListSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        qs = Invoice.objects.filter(
            organization=self.request.user.organization,
            is_deleted=False
        )
        p = self.request.query_params
        if v := p.get("status"):
            qs = qs.filter(status=v)
        if v := p.get("risk_level"):
            qs = qs.filter(risk_level=v)
        if v := p.get("search"):
            qs = qs.filter(
                Q(vendor_name__icontains=v) |
                Q(invoice_number__icontains=v) |
                Q(notes__icontains=v)
            )
        return qs.order_by("-created_at")
```

**Best Practices:**
- Always filter by `organization` (multi-tenant)
- Always exclude soft-deleted (`is_deleted=False`)
- Use `Q` objects for complex filters
- Order by most relevant (typically `-created_at`)
- Select related fields to avoid N+1 queries

---

### Pattern 2: Detail with Related Data

**Endpoint:** `GET /api/v1/invoices/{id}/`

**Implementation:**
```python
class InvoiceDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]
    
    def get_queryset(self):
        return Invoice.objects.filter(
            organization=self.request.user.organization,
            is_deleted=False
        ).select_related(
            "validation",
            "approved_by",
            "duplicate_of",
        ).prefetch_related(
            "audit_events",
            "audit_findings",
        )
    
    def get(self, request, *args, **kwargs):
        invoice = self.get_object()
        data = InvoiceDetailSerializer(invoice).data
        
        # Add nested data
        try:
            data["validation"] = InvoiceValidationResultSerializer(
                invoice.validation
            ).data
        except InvoiceValidationResult.DoesNotExist:
            data["validation"] = None
        
        return Response(data)
```

**Best Practices:**
- Use `select_related()` for ForeignKey relations
- Use `prefetch_related()` for reverse relations
- Build custom response with additional nested data
- Handle missing related objects gracefully

---

### Pattern 3: Soft-Delete on Destroy

**Method:** `DELETE /api/v1/invoices/{id}/`

**Implementation:**
```python
class InvoiceDetailView(generics.RetrieveUpdateAPIView):
    
    def perform_destroy(self, instance):
        """Soft delete with audit trail."""
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save(update_fields=[
            'is_deleted', 'deleted_at', 'deleted_by', 'updated_at'
        ])
        
        # Log audit event
        _save_audit_event(
            instance,
            self.request.user,
            InvoiceAuditEvent.EventType.DELETED,
            f"Soft-deleted by {self.request.user.full_name}",
            request=self.request
        )
```

**Best Practices:**
- Always update `deleted_at` and `deleted_by`
- Create audit event immediately
- Use `update_fields` for efficiency
- Never hard delete from API

---

### Pattern 4: Bulk Actions

**Endpoint:** `POST /api/v1/audit/cases/bulk/`

**Implementation:**
```python
class BulkCaseActionView(APIView):
    permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]
    
    def post(self, request):
        ids = request.data.get("ids", [])
        action = request.data.get("action")
        
        if not ids or not action:
            return Response(
                {"error": "ids and action required"},
                status=400
            )
        
        qs = AuditCase.objects.filter(
            id__in=ids,
            organization=request.user.organization
        )
        count = qs.count()
        
        if action == "resolve":
            qs.update(
                status=AuditCase.Status.RESOLVED,
                resolved_by=request.user,
                resolved_at=timezone.now(),
            )
        elif action == "assign":
            assignee_id = request.data.get("assigned_to")
            # ... validation ...
            qs.update(assigned_to_id=assignee_id)
        
        return Response({"updated": count, "action": action})
```

**Best Practices:**
- Validate action enum
- Use bulk_update for efficiency
- Return count of updated records
- Validate related data (assignee exists, etc.)

---

### Pattern 5: Async Operations with Status Polling

**Endpoint Pattern:**
```
POST   /api/v1/documents/{id}/analyse/     → Returns 202 + task ID
GET    /api/v1/documents/{id}/analysis/    → Returns 200 with result (if ready)
```

**Implementation:**
```python
class DocumentAnalyseView(APIView):
    permission_classes = [IsAuthenticated, RequiresOrganization]
    
    def post(self, request, pk):
        doc = Document.objects.get(pk=pk)
        
        if doc.processing_status == Document.ProcessingStatus.PROCESSING:
            return Response(
                {"message": "Already processing"},
                status=202
            )
        
        # Queue async task
        process_document_task.delay(str(doc.id))
        
        return Response({
            "message": "Analysis queued",
            "document_id": str(doc.id),
            "status": "queued"
        }, status=202)

class DocumentAnalysisResultView(APIView):
    def get(self, request, pk):
        doc = Document.objects.get(pk=pk)
        
        if doc.processing_status == Document.ProcessingStatus.PROCESSING:
            return Response({
                "status": "processing",
                "progress": "..."
            }, status=202)
        
        if doc.processing_status == Document.ProcessingStatus.COMPLETED:
            return Response({
                "status": "completed",
                "analysis": DocumentAnalysisResultSerializer(
                    doc.analysis_result
                ).data
            })
        
        return Response({
            "status": "failed",
            "error": doc.processing_error
        }, status=500)
```

**Best Practices:**
- Return 202 Accepted for async operations
- Include task ID for polling
- Provide status endpoint
- Include estimated completion time if possible

---

## COMMON ERROR SCENARIOS & SOLUTIONS

### Scenario 1: User Tries to Edit Approved Invoice

**Error Code:** 403 Forbidden  
**Message:** "Cannot edit an approved invoice (Rule CTL-004)"

**Root Cause:** Invoice.status == "APPROVED"  
**Solution:** Contact accounting to ask for reversal

**Implementation:**
```python
def perform_update(self, serializer):
    invoice = self.get_object()
    if invoice.status == Invoice.Status.APPROVED:
        raise PermissionDenied(
            "Cannot edit an approved invoice. (Rule CTL-004)"
        )
    serializer.save()
```

---

### Scenario 2: Duplicate Invoice Detected

**Error Code:** 409 Conflict  
**Message:** "Invoice flagged as duplicate"

**Root Cause:** DUP-001 or DUP-002 rule failed  
**Solution:** Review the duplicate_of_id, verify with vendor

**Implementation:**
```python
# In validation pipeline
if is_duplicate:
    invoice.status = Invoice.Status.FLAGGED
    invoice.is_duplicate = True
    invoice.duplicate_of_id = matching_invoice.id
```

---

### Scenario 3: Document Processing Timeout

**Error Code:** 500 Internal Server Error  
**Message:** "Document processing service temporarily unavailable"

**Root Cause:** OCR or AI service failed  
**Solution:** Check service health, retry after 60 seconds

**Implementation:**
```python
try:
    ai_data = extract_invoice_with_ai(image_path, raw_text)
except Exception as e:
    logger.warning(f"AI extraction failed: {e}")
    from core.services.invoice_ai_service import _fallback_extraction
    ai_data = _fallback_extraction(raw_text)  # Use basic extraction
```

---

### Scenario 4: Missing Required Field

**Error Code:** 400 Bad Request  
**Message:** "vendor_name: This field may not be blank"

**Root Cause:** Validation failure in manual review  
**Solution:** Provide the required field

**Implementation:**
```python
corrections = request.data.get("corrections")
for field_name, _, _ in REVIEW_FIELD_META:
    if field_name not in corrections:
        continue
    try:
        coerced_value = _coerce_review_value(field_name, corrections[field_name])
    except ValueError as exc:
        return Response({"errors": {field_name: str(exc)}}, status=400)
```

---

### Scenario 5: User Lacks Permission

**Error Code:** 403 Forbidden  
**Message:** "You do not have permission to perform this action"

**Root Cause:** User not IsSeniorAuditorOrAbove  
**Solution:** Ask organization admin to upgrade role

**Implementation:**
```python
permission_classes = [IsAuthenticated, IsSeniorAuditorOrAbove]

@extend_schema(
    summary="Approve invoice",
    description="Owner/Admin role required to approve invoices"
)
def post(self, request, pk):
    # Permission check done by DRF automatically
    # If user lacks permission, 403 returned before method executes
    pass
```

---

## TESTING CHECKLIST

### Unit Tests
- [ ] Test each validation rule (30 total)
- [ ] Test risk score calculation
- [ ] Test soft-delete logic
- [ ] Test serializers (to_representation, to_internal_value)
- [ ] Test permission classes

### Integration Tests
- [ ] Test full invoice upload pipeline
- [ ] Test list/filter operations
- [ ] Test detail views with related data
- [ ] Test bulk operations
- [ ] Test soft-delete with audit trail

### API Tests
- [ ] Test all success responses (200, 201, 202)
- [ ] Test all error responses (400, 403, 404, 409)
- [ ] Test pagination
- [ ] Test filtering
- [ ] Test search
- [ ] Test ordering

### End-to-End Tests
- [ ] Upload batch of invoices
- [ ] Verify validation scores
- [ ] Manually review and correct
- [ ] Approve or reject
- [ ] Verify audit trail
- [ ] Soft-delete and verify 404

---

