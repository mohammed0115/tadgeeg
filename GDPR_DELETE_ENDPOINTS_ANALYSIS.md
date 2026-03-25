# GDPR Compliance: DELETE/DESTROY Endpoints Analysis
**Tadgeeg Financial Audit System**  
**Date:** March 25, 2026  
**Status:** Analysis Complete

---

## Executive Summary

Tadgeeg currently has **incomplete DELETE endpoint coverage** for GDPR compliance. Out of **8 core business models exposed via REST API**, only **4 have destroy/delete capabilities**. This analysis identifies the **top 5-7 models requiring DELETE endpoints** with their current implementation status.

### Current State: 50% DELETE Coverage
- ✅ **4 models have DELETE:** Document, Transaction, User, CustomRuleDefinition
- ❌ **4 models missing DELETE:** Invoice, AuditSession, AuditCase, JournalEntry (+ VendorProfile, InvoiceBatch, AuditFinding)

---

## 1. TOP 5-7 MODELS REQUIRING DELETE ENDPOINTS

### **PRIORITY 1: INVOICE** [CRITICAL]
**File:** [apps/invoices/models.py](apps/invoices/models.py#L21)  
**Current Endpoint:** [apps/invoices/views.py](apps/invoices/views.py#L1005) `InvoiceDetailView`

#### Current Implementation
```python
# Line 1005: InvoiceDetailView
class InvoiceDetailView(generics.RetrieveUpdateAPIView):
    # ❌ MISSING: DestroyModelMixin
    # ✅ HAS: RetrieveModelMixin, UpdateModelMixin
    serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]
```

#### Why DELETE is Critical
- **Volume:** Core business entity - likely 100,000s of records per org
- **Sensitive Data:** Contains VAT#, vendor details, financial amounts
- **Audit Trail:** InvoiceAuditEvent tracks all changes (has 200+ audit events model)
- **References:** Linked to AuditSession, InvoiceBatch, InvoiceValidationResult
- **GDPR Right to Erasure:** Invoices must be deletable with audit evidence

#### Current Structure (for soft-delete compatibility)
```python
# models.py - Invoice has:
- organization (FK, cascade) 
- uploaded_by (FK, SET_NULL) 
- created_at, updated_at
- status field (PENDING, PROCESSING, VALIDATED, FLAGGED, APPROVED, REJECTED)
- is_duplicate (bool)
- extracted_data (JSONField - contains sensitive AI extraction)
```

#### Soft-Delete Fields Needed
```python
# Add to Invoice model:
is_deleted = models.BooleanField(default=False)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='deleted_invoices')
deletion_reason = models.CharField(max_length=255, blank=True)  # "GDPR request", "User deletion", etc.
```

#### Required Changes
- **View:** Change `generics.RetrieveUpdateAPIView` → `generics.RetrieveUpdateDestroyAPIView`
- **QuerySet:** Filter `is_deleted=False` in all queries
- **Serializer:** Mark deleted_at, deleted_by as read-only
- **Audit:** Log deletion with user, timestamp, reason in InvoiceAuditEvent

#### Endpoint
```
DELETE /api/invoices/<uuid:pk>/
```

#### Risk Level
**HIGH** - Largest volume, most sensitive, central to business logic

---

### **PRIORITY 2: AUDIT SESSION** [CRITICAL]
**File:** [apps/audit/models.py](apps/audit/models.py#L9)  
**Current Endpoint:** [apps/audit/views.py](apps/audit/views.py#L229) `AuditSessionDetailView`

#### Current Implementation
```python
# Line 229: AuditSessionDetailView
class AuditSessionDetailView(APIView):
    # ❌ NO DELETE - Custom APIView, not a generic
    # Only GET is implemented
```

#### Why DELETE is Critical
- **Sensitive Data:** Contains audit progress, invoice summaries, risk scores
- **Compliance Trail:** Tracks bulk invoice processing sessions
- **References:** Linked to Invoice, Document, AuditFinding (cascade delete issues)
- **Session Cleanup:** Organizations need to purge old audit sessions

#### Current Structure
```python
# models.py - AuditSession has:
- organization (FK, cascade)
- created_by (FK)
- status (RECEIVED, EXTRACTING, NORMALIZING, VALIDATING, COMPLETED, FAILED)
- total_count, processed_count, success_count, failed_count
- high_risk_count, duplicate_count, average_risk_score
- related_name="audit_sessions" on Organization
```

#### Soft-Delete Fields Needed
```python
is_deleted = models.BooleanField(default=False)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
deletion_notes = models.TextField(blank=True)
```

#### Required Changes
- **View:** Upgrade to `generics.RetrieveDestroyAPIView` or add destroy method to APIView
- **Cascade:** Related invoices can either soft-delete or set audit_session=None
- **Audit:** Log deletion to AuditLog model

#### Endpoint
```
DELETE /api/audit/sessions/<uuid:pk>/
```

#### Risk Level
**CRITICAL** - Audit sessions are central to compliance workflows

---

### **PRIORITY 3: AUDIT CASE** [CRITICAL]
**File:** [apps/audit/models.py](apps/audit/models.py#L165)  
**Current Endpoint:** [apps/audit/views.py](apps/audit/views.py#L115) `AuditCaseDetailView`

#### Current Implementation
```python
# Line 115: AuditCaseDetailView
class AuditCaseDetailView(generics.RetrieveUpdateAPIView):
    # ❌ MISSING: DestroyModelMixin
    # ✅ HAS: RetrieveModelMixin, UpdateModelMixin
    queryset = AuditCase.objects.all().select_related('assigned_to', 'created_by')
```

#### Why DELETE is Critical
- **Case Management:** Cases represent investigation items - must be erasable
- **Findings Linked:** AuditFinding.audit_case → cases are parents
- **Status Tracking:** Cases have status (OPEN, RESOLVED, IGNORED) - some need purging
- **Comments:** CaseComment records attached - cascade delete implications

#### Current Structure
```python
# models.py - AuditCase has:
- organization (FK, cascade)
- audit_session (FK)
- transaction, invoice (FKs, optional)
- created_by, assigned_to (User FKs)
- status (OPEN, RESOLVED, IGNORED)
- priority, case_type
- related_name="cases" on AuditSession
```

#### Soft-Delete Fields Needed
```python
is_deleted = models.BooleanField(default=False)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
```

#### Required Changes
- **View:** Add `mixins.DestroyModelMixin` to AuditCaseDetailView
- **QuerySet:** Filter `is_deleted=False`
- **Cascade:** Related CaseComment records soft-delete automatically
- **Findings:** Optional - keep findings but orphan them or mark as deleted_case

#### Endpoint
```
DELETE /api/audit/cases/<uuid:pk>/
```

#### URL Pattern
See [apps/audit/urls.py](apps/audit/urls.py#L13) - route already exists

#### Risk Level
**CRITICAL** - Direct investigation cases GDPR-deletable

---

### **PRIORITY 4: AUDIT FINDING** [HIGH]
**File:** [apps/audit/models.py](apps/audit/models.py#L77)  
**Current Endpoint:** [apps/audit/urls.py](apps/audit/urls.py) ⚠️ **NOT EXPOSED**

#### Current Status
- ✅ Model exists with audit trail fields
- ❌ **No REST API endpoint** - no views file exports AuditFindingViewSet
- ❌ No routes in audit/urls.py

#### Why DELETE is Needed
- **Sensitive Findings:** Represent compliance violations, risk assessments
- **Lifecycle:** Findings can be RESOLVED → should be deletable
- **Report Cleanup:** Old findings clutter reports

#### Current Structure
```python
# models.py - AuditFinding has:
- organization (FK, cascade)
- audit_session, audit_case (FK, cascade)
- severity (LOW, MEDIUM, HIGH, CRITICAL)
- status (OPEN, RESOLVED, IGNORED)
- description, impact_assessment
- remediation_steps
```

#### New ViewSet Required
```python
from rest_framework import viewsets, mixins

class AuditFindingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,  # ← DELETE support
    viewsets.GenericViewSet
):
    queryset = AuditFinding.objects.filter(is_deleted=False)
    serializer_class = AuditFindingSerializer
    permission_classes = [IsAuthenticated, IsOwnOrganization]
```

#### Soft-Delete Fields
```python
is_deleted = models.BooleanField(default=False)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
```

#### Endpoint (New)
```
DELETE /api/audit/findings/<uuid:pk>/
```

#### Risk Level
**HIGH** - Findings often confidential, must be erasable

---

### **PRIORITY 5: JOURNAL ENTRY** [HIGH]
**File:** [apps/transactions/models.py](apps/transactions/models.py#L84)  
**Current Endpoint:** [apps/transactions/views.py](apps/transactions/views.py) (Limited)

#### Current Implementation
```python
# No specific JournalEntry view - only listed
# Line 59: JournalEntryListView (ListAPIView) - READ ONLY
```

#### Why DELETE is Needed
- **Financial Records:** GL entries must be erasable (GDPRrequirement)
- **Manual Flag:** `is_manual` field indicates manually created entries (audit trail needed)
- **Reversal Logic:** Already has `is_reversed` field - delete should respect this

#### Current Structure
```python
# models.py - JournalEntry has:
- organization (FK, cascade)
- posted_by (FK, User)
- entry_date, entry_number
- is_manual, is_reversed
- is_suspicious
- lines (JSONField - GL line items)
```

#### Required View
```python
class JournalEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = JournalEntry.objects.filter(organization=request.user.organization)
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated]
    
    def destroy(self, request, *args, **kwargs):
        # Soft delete
        instance = self.get_object()
        instance.is_deleted = True
        instance.deleted_at = now()
        instance.save()
        log_action(request, AuditLog.Action.JOURNAL_ENTRY_DELETE, ...)
```

#### Soft-Delete Fields
```python
is_deleted = models.BooleanField(default=False)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
```

#### Endpoint (New)
```
DELETE /api/transactions/journal-entries/<uuid:pk>/
GET    /api/transactions/journal-entries/<uuid:pk>/
PATCH  /api/transactions/journal-entries/<uuid:pk>/
```

#### URL Pattern (New)
Add to [apps/transactions/urls.py](apps/transactions/urls.py):
```python
path("journal-entries/<uuid:pk>/", views.JournalEntryDetailView.as_view(), ...)
```

#### Risk Level
**HIGH** - Financial records GDPR-sensitive

---

### **PRIORITY 6: VENDOR PROFILE** [MEDIUM]
**File:** [apps/invoices/models.py](apps/invoices/models.py#L322)  
**Current Endpoint:** [apps/invoices/views.py](apps/invoices/views.py#L1366) `VendorListView`

#### Current Implementation
```python
# Line 1366: VendorListView
class VendorListView(APIView):
    # ❌ GET ONLY - no delete
    # Custom endpoint, not REST generic
```

#### Why DELETE is Helpful
- **Business Data:** Vendor profiles aggregate vendor risk analytics
- **Privacy:** Vendor contact/financial data should be erasable
- **Reference Cleanup:** When vendor master deleted, profile can be purged

#### Current Structure
```python
# models.py - VendorProfile has:
- organization (FK, cascade)
- vendor_name, vendor_vat_number, vendor_cr_number
- vendor_address, vendor_phone
- invoice_count, total_amount, avg_invoice_amount, max_invoice_amount
- flagged_count, duplicate_count
- is_new, first_seen, last_seen
```

#### Required Changes
- **View:** Create `VendorProfileDetailView(generics.RetrieveUpdateDestroyAPIView)`
- **Soft-Delete:** Add is_deleted, deleted_at, deleted_by fields
- **List View:** Filter by is_deleted=False

#### Endpoint (New)
```
DELETE /api/invoices/vendors/<uuid:pk>/
GET    /api/invoices/vendors/<uuid:pk>/
PATCH  /api/invoices/vendors/<uuid:pk>/
```

#### Risk Level
**MEDIUM** - Vendor data less sensitive than invoices, but still PII

---

### **PRIORITY 7: INVOICE BATCH** [MEDIUM]
**File:** [apps/invoices/models.py](apps/invoices/models.py#L196)  
**Current Endpoint:** [apps/invoices/views.py](apps/invoices/views.py#L1240) `InvoiceBatchDetailView`

#### Current Implementation
```python
# Line 1240: InvoiceBatchDetailView
class InvoiceBatchDetailView(APIView):
    # ❌ GET ONLY - no delete
    # Custom APIView
```

#### Why DELETE is Helpful
- **Grouping Entity:** Batches organize uploaded invoices
- **Cleanup:** Old batch metadata can accumulate
- **Cascade Question:** Deleting batch - what happens to child invoices?

#### Current Structure
```python
# models.py - InvoiceBatch has:
- organization (FK, cascade)
- uploaded_by (FK, User)
- audit_session (FK, optional)
- batch_name, status
- total_files, processed_files, failed_files
- total_amount, duplicate_count, high_risk_count
```

#### Required Changes
- **Soft-Delete:** Add is_deleted, deleted_at, deleted_by
- **Cascade Strategy:** SET invoices.batch = NULL (don't cascade delete children)
- **View:** Upgrade to `RetrieveUpdateDestroyAPIView`

#### Endpoint
```
DELETE /api/invoices/batches/<uuid:pk>/
```

#### Important Note
⚠️ **Deleting a batch should NOT delete child invoices** - only unlinks them

#### Risk Level
**MEDIUM** - Administrative cleanup, less sensitive

---

## 2. MODELS WITHOUT SUFFICIENT API EXPOSURE

### AuditFinding
- **Current:** Listed in models.py but no serializer/view exposed
- **Needed:** Full ViewSet implementation with CRUD + DELETE

### ComplianceViolation
- **Current:** Model exists [apps/compliance/models.py](apps/compliance/models.py#L27)
- **Needed:** Verify if API exposed; if yes, add DELETE

### ExtractedData
- **Current:** OneToOne with Document
- **Note:** Automatically deleted when Document deleted (CASCADE)

### DocumentPageResult, DocumentAnalysisResult
- **Current:** Auto-deleted with Document
- **Note:** Already have cascade delete via Document.delete()

---

## 3. IMPLEMENTATION ROADMAP

### Phase 1: High-Impact Models (Week 1-2)
1. **Invoice** - Add DestroyModelMixin + soft-delete fields
2. **AuditSession** - Convert APIView to generic with destroy
3. **AuditCase** - Add DestroyModelMixin

### Phase 2: Supporting Models (Week 2-3)
4. **AuditFinding** - Create full ViewSet from scratch
5. **JournalEntry** - Create RetrieveUpdateDestroyAPIView + add to URLs

### Phase 3: Lower Priority (Week 3-4)
6. **VendorProfile** - Add delete detail view
7. **InvoiceBatch** - Add destroy with referential integrity

### Phase 4: Verification
- Audit trail logging for all deletes
- Soft-delete testing
- GDPR compliance verification
- API documentation updates

---

## 4. SOFT-DELETE STRATEGY (RECOMMENDED)

### Standard Implementation Pattern
```python
# 1. Add fields to ALL models
class MyModel(models.Model):
    # ... existing fields ...
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL,
                                   related_name=f'deleted_{model_name}s')

# 2. Manager filter
class MyModelManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

class MyModel(models.Model):
    objects = MyModelManager()  # Default manager
    all_objects = models.Manager()  # Unfiltered manager
    
    class Meta:
        indexes = [
            models.Index(fields=['organization', 'is_deleted']),
        ]

# 3. View destroy method
def destroy(self, request, *args, **kwargs):
    instance = self.get_object()
    instance.is_deleted = True
    instance.deleted_at = timezone.now()
    instance.deleted_by = request.user
    instance.save()
    
    # Log to AuditLog
    log_action(request, AuditLog.Action.DELETE, 
               model_name, str(instance.id))
    
    return Response(status=status.HTTP_204_NO_CONTENT)

# 4. Serializer (read-only delete fields)
class MyModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MyModel
        fields = ['id', 'name', '...', 'deleted_at', 'deleted_by']
        read_only_fields = ['deleted_at', 'deleted_by']
```

---

## 5. AUDIT LOGGING REQUIREMENTS

All DELETE operations must log to `AuditLog` model:

```python
from apps.authentication.models import AuditLog
from core.utils.audit import log_action

# In destroy() method:
log_action(
    request=request,
    action=AuditLog.Action.DELETE,  # Or similar constant
    resource_type='invoice',  # or 'audit_session', etc.
    resource_id=str(instance.id),
    changes={'status': 'deleted', 'reason': 'user_initiated'}
)
```

View [apps/authentication/models.py](apps/authentication/models.py) for AuditLog action choices.

---

## 6. CURRENT DELETE COVERAGE TABLE

| Model | Endpoint | Current View | Status | Priority |
|-------|----------|--------------|--------|----------|
| **Invoice** | ✓ | RetrieveUpdateAPIView | ❌ NO DELETE | **CRITICAL** |
| **AuditSession** | ✓ | APIView (GET) | ❌ NO DELETE | **CRITICAL** |
| **AuditCase** | ✓ | RetrieveUpdateAPIView | ❌ NO DELETE | **CRITICAL** |
| **AuditFinding** | ❌ | None | ❌ NO API | **HIGH** |
| **JournalEntry** | ❌ | ListAPIView | ❌ NO DELETE | **HIGH** |
| **VendorProfile** | ✓ | APIView (GET) | ❌ NO DELETE | **MEDIUM** |
| **InvoiceBatch** | ✓ | APIView (GET) | ❌ NO DELETE | **MEDIUM** |
| **Document** | ✓ | RetrieveDestroyAPIView | ✅ HAS DELETE | ✅ DONE |
| **Transaction** | ✓ | RetrieveUpdateDestroyAPIView | ✅ HAS DELETE | ✅ DONE |
| **User** | ✓ | RetrieveUpdateDestroyAPIView | ✅ HAS DELETE | ✅ DONE |
| **CustomRuleDefinition** | ✓ | RetrieveUpdateDestroyAPIView | ✅ HAS DELETE | ✅ DONE |

---

## 7. REFERENCES

### Key Files for Implementation
- **Models:** [apps/invoices/models.py](apps/invoices/models.py), [apps/audit/models.py](apps/audit/models.py), [apps/transactions/models.py](apps/transactions/models.py)
- **Views:** [apps/invoices/views.py](apps/invoices/views.py), [apps/audit/views.py](apps/audit/views.py), [apps/documents/views.py](apps/documents/views.py)
- **URLs:** [apps/invoices/urls.py](apps/invoices/urls.py), [apps/audit/urls.py](apps/audit/urls.py), [apps/transactions/urls.py](apps/transactions/urls.py)
- **Audit:** [apps/authentication/models.py](apps/authentication/models.py#L200) - AuditLog model
- **Permissions:** [apps/authentication/permissions.py](apps/authentication/permissions.py)

### Existing Soft-Delete Example
- **Document:** Check [apps/documents/views.py](apps/documents/views.py#L149) for `RetrieveDestroyAPIView` implementation

---

## CONCLUSION

**Tadgeeg needs DELETE endpoints on 5-7 core models to be GDPR compliant.** Invoice and Audit models are critical. Implementation should follow the **soft-delete pattern** with audit logging to maintain data integrity and compliance trails.

**Estimated Implementation Effort:** 3-4 weeks  
**Complexity:** Medium (consistent CRUD pattern, complex CASCADE considerations for Audit relationships)  
**Business Impact:** HIGH (GDPR requirement, directly addresses user erasure rights)
