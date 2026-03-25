# GDPR DELETE Endpoints - Quick Reference

## TOP 5-7 MODELS NEEDING DELETE ENDPOINTS

| # | Model | Current View | Has DELETE? | Priority | Volume | Sensitivity | Notes |
|---|-------|--------------|-------------|----------|--------|-------------|-------|
| **1** | **Invoice** | RetrieveUpdateAPIView | ❌ NO | 🔴 CRITICAL | 100K+ | 🔴 HIGH | Core entity, VAT data, financial amounts |
| **2** | **AuditSession** | APIView (GET) | ❌ NO | 🔴 CRITICAL | 10K+ | 🔴 HIGH | Audit trails, processing batches |
| **3** | **AuditCase** | RetrieveUpdateAPIView | ❌ NO | 🔴 CRITICAL | 10K+ | 🔴 HIGH | Investigation cases, linked to findings |
| **4** | **AuditFinding** | *(no API)* | ❌ NO | 🟠 HIGH | 50K+ | 🔴 HIGH | Compliance violations - currently no ViewSet |
| **5** | **JournalEntry** | ListAPIView | ❌ NO | 🟠 HIGH | 50K+ | 🟠 MEDIUM | GL entries, manual flag for audit |
| **6** | **VendorProfile** | APIView (GET) | ❌ NO | 🟡 MEDIUM | 1K+ | 🟠 MEDIUM | Vendor PII, contact info, VAT# |
| **7** | **InvoiceBatch** | APIView (GET) | ❌ NO | 🟡 MEDIUM | 100 | 🟢 LOW | Batch metadata, cleanup helper |

---

## CURRENT DELETE COVERAGE (ALREADY DONE)

| Model | View | Status |
|-------|------|--------|
| ✅ Document | RetrieveDestroyAPIView | Complete |
| ✅ Transaction | RetrieveUpdateDestroyAPIView | Complete |
| ✅ User | RetrieveUpdateDestroyAPIView | Complete |
| ✅ CustomRuleDefinition | RetrieveUpdateDestroyAPIView | Complete |

---

## IMPLEMENTATION CHECKLIST

### For Each Model Add:

#### 1. **Model Changes** (apps/*/models.py)
```python
is_deleted = models.BooleanField(default=False, db_index=True)
deleted_at = models.DateTimeField(null=True, blank=True)
deleted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
```

#### 2. **View Changes** (apps/*/views.py)
- Change `RetrieveUpdateAPIView` → `RetrieveUpdateDestroyAPIView`
- Or add `mixins.DestroyModelMixin` to existing ViewSet
- Filter queryset: `.filter(is_deleted=False)`
- Implement `destroy()` method with audit logging

#### 3. **Serializer Changes** (if needed)
- Mark deleted fields as read-only
- Update allowed_fields tuple

#### 4. **URL Changes** (apps/*/urls.py)
- DELETE is auto-supported on detail routes
- No URL pattern changes needed

#### 5. **Audit Logging**
```python
from core.utils.audit import log_action
log_action(request, AuditLog.Action.DELETE, 'model_name', str(instance.id))
```

---

## SOFT-DELETE IMPACT ANALYSIS

### What Gets Soft-Deleted?
✅ Invoice  
✅ AuditSession  
✅ AuditCase  
✅ AuditFinding  
✅ JournalEntry  
✅ VendorProfile  
✅ InvoiceBatch  

### Cascade Implications
- **Invoice → AuditSession:** SET invoice.audit_session = NULL
- **AuditSession → AuditCase:** Soft-delete cases OR set case.audit_session = NULL
- **AuditCase → AuditFinding:** Soft-delete findings (CASCADE)
- **AuditCase → CaseComment:** Soft-delete comments
- **Document → ExtractedData:** Hard-delete (OneToOne, no soft-delete needed)

### QuerySet Management
Every model needs:
```python
objects = ActiveManager()  # Default - filters is_deleted=False
all_objects = models.Manager()  # Unfiltered - for admin/backup
```

---

## TESTING REQUIREMENTS

- [ ] DELETE request returns 204 No Content
- [ ] Record marked is_deleted=True, deleted_at set, deleted_by set
- [ ] AuditLog entry created
- [ ] Soft-deleted records excluded from LIST endpoints
- [ ] GET on deleted record returns 404
- [ ] Permissions enforced (org isolation, role-based)
- [ ] Cascade deletes work correctly
- [ ] Related records handle orphaning gracefully

---

## GDPR COMPLIANCE NOTES

**User Erasure Request Workflow:**
1. User requests deletion via support
2. Admin initiates DELETE on all user's records:
   - Invoices uploaded_by this user
   - AuditSessions created_by this user
   - AuditCases created_by/assigned_to this user
3. System logs all deletes to AuditLog
4. Downloaded reports show deletion trail (deleted_by, deleted_at)
5. Retention policy = Never (soft-delete is permanent)

**Data Residency:**
- Soft-deleted records remain in DB for backup/recovery
- Consider GDPR right to erasure = hard delete after retention period
- Recommend: Soft-delete on demand, hard-delete after 90 days (configurable)

---

## Files to Modify (Summary)

### High Priority (Week 1-2)
```
apps/invoices/models.py         — Add soft-delete fields
apps/invoices/views.py          — Change RetrieveUpdateAPIView → RetrieveUpdateDestroyAPIView
apps/invoices/serializers.py    — Mark deleted fields read-only

apps/audit/models.py            — Add soft-delete fields (AuditSession, AuditCase)
apps/audit/views.py             — Add DestroyModelMixin or generics updates

apps/transactions/models.py      — Add JournalEntry soft-delete fields
apps/transactions/views.py       — Add JournalEntryDetailView
apps/transactions/urls.py        — Add journal-entries/<pk>/ routes
apps/transactions/serializers.py — Handle deletion fields
```

### Medium Priority (Week 2-3)
```
apps/audit/models.py            — Add AuditFinding soft-delete
apps/audit/views.py             — Create AuditFindingViewSet
apps/audit/serializers.py       — Create AuditFindingSerializer
apps/audit/urls.py              — Add findings/<pk>/ routes
```

### Lower Priority (Week 3-4)
```
apps/invoices/models.py         — Add VendorProfile, InvoiceBatch soft-delete
apps/invoices/views.py          — Add VendorProfileDetailView, update InvoiceBatchDetailView
apps/invoices/urls.py           — Add vendor/<pk>/, batch/<pk>/ detail routes
```

---

## Command: Generate Implementation Stubs

The detailed analysis document [GDPR_DELETE_ENDPOINTS_ANALYSIS.md](GDPR_DELETE_ENDPOINTS_ANALYSIS.md) contains:
- Full code examples
- Implementation patterns
- Cascade delete strategies
- URL routing patterns
- Audit logging requirements
- Serializer templates

👉 **Next Step:** Use this checklist to implement changes across the 7 models.
