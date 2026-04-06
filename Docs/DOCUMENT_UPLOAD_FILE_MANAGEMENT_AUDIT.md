# Document Upload & File Management System Audit

**Date:** March 29, 2026  
**Scope:** Complete analysis of document/invoice uploads, file validation, storage, and malware scanning

---

## 1. UPLOAD HANDLING ENDPOINTS & VIEWS

### 1.1 Primary Upload Handlers

| Endpoint | Location | Type | Purpose |
|----------|----------|------|---------|
| `POST /api/documents/upload/` | [apps/documents/views.py](../apps/documents/views.py#L48) | `DocumentUploadView` | Generic document upload (any type) |
| `POST /api/invoices/upload/` | [apps/invoices/views.py](../apps/invoices/views.py#L878) | `InvoiceUploadView` | Invoice batch upload with full 30-rule validation |
| `POST /files/files/` | [apps/file_management/views.py](../apps/file_management/views.py#L175) | `AuditFileViewSet.create()` | Generic file upload to organized file system |
| `/auditor/upload/` (HTML Form) | [apps/auditing/views/upload.py](../apps/auditing/views/upload.py#L25) | `AuditDocumentUploadView` | Multi-file & ZIP upload for auditors |

### 1.2 Upload Router (Central Dispatcher)

**Location:** [core/services/upload_router.py](../core/services/upload_router.py)

```python
class DocumentUploadRouter:
    def route(
        uploaded_file, 
        document_type: str,  # "invoice", "purchase_order", etc.
        user,
        language: str = "auto",
        organization=None
    ) -> UploadRouterResult
```

**Routes to:**
- **Invoice types** (sales_invoice, purchase_order, etc.) → `InvoiceUploadView` → Full 30-rule validation
- **All other types** → `DocumentUploadView` → Generic document pipeline

---

## 2. FILE VALIDATION LOGIC

### 2.1 Extension Whitelist

**Allowed Extensions** (defined in multiple locations):

```python
ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",  # Image formats
    ".xlsx", ".xls", ".csv", ".json",                    # Data formats
    ".zip"                                                # Archive
}

# Suspicious extensions (flagged but not blocked):
SUSPICIOUS_EXTENSIONS = {'.exe', '.bat', '.cmd', '.sh', '.dll', '.so', '.app'}
```

**Locations:**
- [apps/auditing/forms.py](../apps/auditing/forms.py#L10-L14) - AuditDocumentUploadForm
- [apps/documents/serializers.py](../apps/documents/serializers.py#L19-L26) - DocumentUploadSerializer
- [apps/invoices/views.py](../apps/invoices/views.py) - _ALLOWED_EXT constant

### 2.2 MIME Type Validation

**Defined in:**
- [apps/storage_management/models.py](../apps/storage_management/models.py#L129-L135) - `StoragePolicy.allowed_mime_types`
- Each upload serializer validates `content_type` field

**Default acceptance:** application/pdf, image/jpeg, image/png, application/vnd.ms-excel, application/json, application/zip, etc.

### 2.3 File Size Limits

| Limit | Context | Location |
|-------|---------|----------|
| **50 MB** | Default document upload | [apps/documents/serializers.py](../apps/documents/serializers.py#L30-L35) |
| **50 MB** | Audit form upload | [apps/auditing/forms.py](../apps/auditing/forms.py#L17) |
| **200 MB** | ZIP archives | [AUDITOR_UPLOAD_ENHANCEMENTS.md](../AUDITOR_UPLOAD_ENHANCEMENTS.md#L29) |
| **Configurable** | Via StoragePolicy | [apps/storage_management/models.py](../apps/storage_management/models.py#L130) |

### 2.4 ZIP Bomb Protection ✅ (MVP Implemented)

**Status:** ✅ **COMPLETE** - Comprehensive decompression bomb protection

**Location:** [core/services/zip_validator.py](../core/services/zip_validator.py)

#### Protection Mechanisms:

| Check | Limit | Purpose | Evidence |
|-------|-------|---------|----------|
| Corrupt ZIP detection | N/A | Blocks malformed ZIPs using `zipfile.testzip()` | Lines 104-107 |
| Per-file size limit | 500 MB | Prevents oversized individual files | Lines 120-126 |
| Total uncompressed | 1 GB | Prevents memory exhaustion | Lines 128-133 |
| Compression ratio | 100:1 | Detects zip bombs | Lines 134-138 |
| File count limit | 500 | Prevents slowness DoS | Lines 110-114 |
| Path traversal | N/A | Blocks `../` directory escape | Lines 139-144 |
| Nested ZIP depth | 2 levels | Prevents ZIP-in-ZIP bombs | Lines 145-149 |

#### API:

```python
# Raising API (for strict validation)
validate_zip_bomb(
    file_obj_or_path,
    max_file_size=500MB,
    max_total_size=1GB,
    max_files=500,
    max_ratio=100,
    allow_nesting=True
) -> dict  # Returns {"valid": bool, "errors": [...], "metadata": {...}}
# Raises: ZipValidationError

# Non-raising API (for safe contexts)
is_valid, error_msg = validate_zip_bomb_silent(file_obj)  # Returns (bool, str)
```

#### Integration Points:

1. **Forms:** [apps/auditing/forms.py#L33-L40](../apps/auditing/forms.py#L33-L40) - `validate_zip_contents()`
2. **Invoice Upload:** [apps/invoices/views.py#L821-L830](../apps/invoices/views.py#L821-L830) - `_process_zip()`
3. **ZIP Parser:** [core/services/parsers/zip_parser.py#L118-L130](../core/services/parsers/zip_parser.py#L118-L130) - `_is_safe_zip()`

#### Testing:

Comprehensive test suite in [tests/test_zip_bomb_protection.py](../tests/test_zip_bomb_protection.py):
- ✅ Normal ZIP passes
- ✅ Corrupt ZIP rejected
- ✅ High compression ratio rejected
- ✅ Oversized files rejected
- ✅ Path traversal blocked
- ✅ Too many files rejected
- ✅ Silent validation API works

---

## 3. FILE STORAGE STRUCTURE

### 3.1 Media Directory Layout

```
media/
├── documents/           # Document app uploads
│   └── YYYY/MM/         # Date-based subdirectories
│       └── *.pdf, *.jpg, etc.
├── invoices/            # Invoice app uploads
│   └── YYYY/MM/
├── auditing/            # Auditing app files
├── storage/             # File management system
│   ├── Folder1/
│   ├── Folder2/
│   └── ...
└── tmp_ocr/             # Temporary OCR processing files
```

### 3.2 Storage System Architecture

**Multi-provider storage system** defined in [apps/storage_management/models.py](../apps/storage_management/models.py):

| Component | Purpose | Key Fields |
|-----------|---------|-----------|
| `StorageProvider` | Pluggable storage backends | type: LOCAL / S3 / MINIO / AZURE |
| `StorageConfig` | Per-provider configuration | bucket_name, region, endpoint_url, base_path |
| `StoragePolicy` | Organization-level policy | max_file_size_mb, allowed_extensions, antivirus_scan_enabled, retention_days |
| `AuditFile` | Core file record | original_name, file_size, checksum, content_type, status |
| `FileStorageMapping` | Storage location tracking | storage_provider, storage_path, version_number, checksum |

### 3.3 File Upload Flow

```
POST /api/documents/upload/ (DocumentUploadView)
    ↓
DocumentUploadSerializer.validate_file()
    • Check extension
    • Check size
    ↓
Document.objects.create()
    • Save file to media/documents/YYYY/MM/
    • Save mime_type, file_size, original_filename
    ↓
process_document_task.delay()  (Celery async)
    • DocumentEngine.ingest()
    • FinancialAIEngine.analyse()
    • AuditEngine.evaluate()
    ↓
Update Document.processing_status = "completed"|"failed"
```

---

## 4. MALWARE SCANNING CAPABILITIES

### 4.1 Current Status

**State:** ❌ **NOT IMPLEMENTED** - Only infrastructure exists

**Evidence:**
- [COMPREHENSIVE_GAP_ANALYSIS.json](../COMPREHENSIVE_GAP_ANALYSIS.json#L168) identifies "Gap #5: No Malware Scanning"
- [RULE_VALIDATION_REPORT.json](../RULE_VALIDATION_REPORT.json#L200): `"malware_scanning": false`

### 4.2 MalwareScanResultRule ✅ (Defined but Unused)

**Location:** [apps/rule_engine/rules/security/security_rules.py#L301](../apps/rule_engine/rules/security/security_rules.py#L301)

```python
class MalwareScanResultRule(AuditRuleBase):
    rule_code = "SEC-010"
    rule_name_en = "Malware Scan Result Enforcement"
    rule_name_ar = "تطبيق نتيجة فحص البرمجيات الخبيثة"
    default_severity = "critical"
    
    def execute(self, doc: NormalizedDocument) -> RuleResult:
        scan_performed = doc.get("malware_scan_performed", None)
        scan_result = doc.get("malware_scan_result", None)
        
        # Checks:
        if scan_performed is False:
            return self._fail("Malware scan was not performed")
        if scan_result == "infected" or scan_result == "threat_detected":
            return self._fail(f"Malware detected: {threat}")
```

**Expected Fields (not yet implemented):**
```python
NormalizedDocument expected dict structure:
{
    "malware_scan_performed": bool,  # Was scan executed?
    "malware_scan_result": str,      # "clean" | "infected" | "threat_detected" | None
    "malware_threat_name": str,      # Name of detected threat (if any)
}
```

### 4.3 Storage Policy Configuration

**Location:** [apps/storage_management/models.py#L134](../apps/storage_management/models.py#L134)

```python
class StoragePolicy(models.Model):
    antivirus_scan_enabled = models.BooleanField(default=False)
```

**Admin UI:** [templates/storage_management/file_policies.html#L143](../templates/storage_management/file_policies.html#L143)

**Current behavior:** Checkbox exists in admin but logic not implemented

### 4.4 Recommended Implementation Options

From [COMPREHENSIVE_GAP_ANALYSIS.json](../COMPREHENSIVE_GAP_ANALYSIS.json#L168):

#### Option A: ClamAV (Local Daemon)
```python
# pip install pyclamd
# apt-get install clamav-daemon (Linux)

class MalwareScannerService:
    def __init__(self):
        self.clam = clamd.ClamdUnixSocket()
    
    def scan_file(self, file_obj) -> bool:
        file_obj.seek(0)
        scan_result = self.clam.scan_stream(file_obj.read())
        if scan_result and 'FOUND' in scan_result:
            raise ValidationError("Malware detected")
```

#### Option B: VirusTotal API (Cloud)
- External API calls for scanning
- Higher accuracy but external dependency
- Cost per scan

---

## 5. MODEL FIELD DEFINITIONS

### 5.1 Document Model

**Location:** [apps/documents/models.py](../apps/documents/models.py)

```python
class Document(models.Model):
    # File metadata
    file = models.FileField(upload_to="documents/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=100)
    
    # Processing
    processing_status = models.CharField(
        choices=["pending", "processing", "completed", "needs_review", "failed"]
    )
    language = models.CharField(
        choices=["ar", "en", "mixed", "unknown"], default="unknown"
    )
    
    # Quality metrics
    ocr_confidence = models.FloatField(null=True)
    page_count = models.PositiveIntegerField(default=1)
    is_handwritten = models.BooleanField(default=False)
    
    # No malware scan fields yet
```

### 5.2 Invoice Model

**Location:** [apps/invoices/models.py](../apps/invoices/models.py)

```python
class Invoice(models.Model):
    # File metadata
    file = models.FileField(upload_to="invoices/%Y/%m/", null=True, blank=True)
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True)
    
    # Extracted data (includes all parsing results)
    extracted_data = models.JSONField(
        default=dict,
        help_text="Contains file_hash, parsing metadata, AI extraction, etc."
    )
    
    # No dedicated malware_scan_performed or malware_scan_result fields
    # These would need to be added to extracted_data or as separate fields
```

### 5.3 AuditFile Model (File Management System)

**Location:** [apps/storage_management/models.py#L147-L175](../apps/storage_management/models.py#L147-L175)

```python
class AuditFile(models.Model):
    # Identity
    id = UUIDField(primary_key=True)
    original_name = models.CharField(max_length=255)
    
    # File properties
    file_type = models.CharField(max_length=50)  # Extension
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveBigIntegerField()
    
    # Integrity
    checksum = models.CharField(max_length=64, db_index=True)  # SHA256
    
    # Status
    status = models.CharField(
        choices=["uploaded", "processing", "stored", "failed", "archived"]
    )
    
    # Metadata
    uploaded_by = ForeignKey(User)
    organization = ForeignKey(Organization)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 5.4 FileVersion Model (Immutable audit trail)

**Location:** [apps/storage_management/models.py](../apps/storage_management/models.py)

```python
class FileVersion(models.Model):
    """Immutable record of a single stored version."""
    
    audit_file = ForeignKey(AuditFile)
    version_number = models.PositiveIntegerField()
    storage_provider = ForeignKey(StorageProvider)
    storage_path = models.TextField()
    checksum = models.CharField(max_length=64)  # SHA256
    file_size = models.PositiveBigIntegerField()
    created_by = ForeignKey(User)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## 6. AUDIT LOG ENTRIES

### 6.1 Upload-Related Actions

**Location:** [apps/authentication/models.py#L289-L315](../apps/authentication/models.py#L289-L315)

```python
class AuditLog(models.Model):
    class Action(models.TextChoices):
        DOCUMENT_UPLOAD = "document_upload", _("Document Upload")
        DOCUMENT_PROCESS = "document_process", _("Document Processed")
        # ... other actions (LOGIN, LOGOUT, etc.)
```

### 6.2 Upload Logging Integration

**Locations:**

| Event | Logged At | Details Logged |
|-------|-----------|-----------------|
| Document upload | [apps/documents/views.py#L108](../apps/documents/views.py#L108) | doc_id, filename, org_id |
| Invoice upload | [apps/invoices/views.py](../apps/invoices/views.py) | batch_id, file_count, validation_score |
| File upload (FM) | [apps/file_management/views.py](../apps/file_management/views.py) | file_id, folder_id, purpose |
| Audit document upload | [apps/auditing/views/upload.py](../apps/auditing/views/upload.py) | Via DocumentUploadRouter |

### 6.3 Storage Activity Log

**Location:** [apps/storage_management/models.py#L217-L250](../apps/storage_management/models.py#L217-L250)

```python
class StorageActivityLog(models.Model):
    class Action(models.TextChoices):
        FILE_UPLOADED = "file_uploaded", "File Uploaded"
        FILE_DELETED = "file_deleted", "File Deleted"
        FILE_MOVED = "file_moved", "File Moved"
        # ... others
    
    user = ForeignKey(User)
    organization = ForeignKey(Organization)
    action = models.CharField(max_length=30, choices=Action.choices)
    entity_type = models.CharField(max_length=50)  # "document", "invoice", etc.
    entity_id = models.CharField(max_length=100)
    metadata = models.JSONField()
    success = models.BooleanField()
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## 7. MODEL RELATIONSHIPS

### 7.1 Document Upload Flow

```
┌─────────────────────────────────────────┐
│         AuditLog                        │
│  (action: DOCUMENT_UPLOAD)              │
└─────────────────────────────────────────┘
              ↓ references
┌─────────────────────────────────────────┐
│         Document                        │
│  • file: FileField                      │
│  • original_filename                    │
│  • file_size, mime_type                 │
│  • processing_status: "pending"         │
│  • extracted_data: JSON                 │
└─────────────────────────────────────────┘
              ↓ contains
┌─────────────────────────────────────────┐
│      ExtractedData (OneToOne)           │
│  • raw_text                             │
│  • structured_data: JSON                │
│  • validation_status                    │
└─────────────────────────────────────────┘
```

### 7.2 Invoice Upload Flow

```
┌──────────────────────────┐
│      InvoiceBatch        │
│  (tracks upload session) │
└──────────────────────────┘
         ↓ contains
    ┌────────────┐
    │  Invoice   │
    │  (x files) │
    └────────────┘
         ↓
┌──────────────────────────┐
│  InvoiceValidationResult │
│  (30 rules validation)   │
└──────────────────────────┘
         ↓
┌──────────────────────────┐
│      AuditLog            │
│  (action: upload)        │
└──────────────────────────┘
```

### 7.3 File Management System

```
Organization (1)
    ↓
    ├─→ Folder (N) - Tree structure
    │       ↓
    │   AuditFileProfile (N) - Organizes files into folders
    │       ↓
    │   AuditFile (N) - Core file record
    │       ↓
    │   FileVersion (N) - Immutable version history
    │       ↓
    │   FileStorageMapping (N) - Storage location on provider
    │
    └─→ StoragePolicy - File validation rules
         ├─ max_file_size_mb
         ├─ allowed_extensions
         ├─ antivirus_scan_enabled
         └─ retention_days
```

### 7.4 MalwareScanResultRule Dependency

```
Invoice / Document
    ↓
NormalizedDocument (dict)
    ├─ malware_scan_performed: bool
    ├─ malware_scan_result: str
    └─ malware_threat_name: str
        ↓
    MalwareScanResultRule (SEC-010)
        ↓
    RuleResult
        ├─ status: PASS | FAIL | WARNING
        ├─ evidence: list
        └─ severity: CRITICAL
```

---

## 8. UPLOAD SERIALIZERS

### 8.1 DocumentUploadSerializer

**Location:** [apps/documents/serializers.py#L19-L40](../apps/documents/serializers.py#L19-L40)

```python
class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    document_type = serializers.ChoiceField(
        choices=Document.DocumentType.choices,
        default=Document.DocumentType.OTHER,
        required=False,
    )
    notes = serializers.CharField(required=False, max_length=1000)
    
    def validate_file(self, value):
        # Extension check
        # Size check
        return value
```

### 8.2 FileUploadSerializer (File Management)

**Location:** [apps/file_management/serializers.py#L186-L208](../apps/file_management/serializers.py#L186-L208)

```python
class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    folder_id = serializers.UUIDField(required=False, allow_null=True)
    purpose = serializers.CharField(
        required=False,
        default="uploads",
        max_length=50,
        help_text="uploads|backup|archive|temp"
    )
```

---

## 9. SECURITY SUMMARY

### 9.1 Implemented Controls ✅

| Control | Status | Location |
|---------|--------|----------|
| Extension whitelist | ✅ Done | serializers.py, forms.py |
| MIME type validation | ✅ Done | DocumentUploadSerializer.validate_file() |
| File size limits | ✅ Done | Per-endpoint configuration |
| ZIP bomb detection | ✅ Done | core/services/zip_validator.py |
| Path traversal protection | ✅ Done | ZIP validator + folder validation |
| File integrity (checksum) | ✅ Done | SHA256 in FileVersion |
| Audit logging | ✅ Done | AuditLog + StorageActivityLog |
| Soft delete support | ✅ Done | Invoice.is_deleted / AuditFile.status=archived |

### 9.2 Missing Controls ❌

| Control | Status | Priority | Gap |
|---------|--------|----------|-----|
| Malware scanning | ❌ Missing | **CRITICAL** | No ClamAV/VirusTotal integration |
| Antivirus on upload | ❌ Missing | **HIGH** | Policy flag exists but not used |
| File content validation | ⚠️ Partial | HIGH | Only MIME type, not content verification |
| Rate limiting on uploads | ❌ Missing | MEDIUM | No per-user/org upload throttling |
| Quarantine system | ❌ Missing | HIGH | Suspicious files not isolated |

### 9.3 Recommendations

**Phase 1 (Critical):**
1. Implement ClamAV integration for malware scanning
2. Add `malware_scan_performed` and `malware_scan_result` fields to Invoice/Document models
3. Wire MalwareScanResultRule to actual scan results
4. Implement quarantine storage for infected files

**Phase 2 (High Priority):**
1. Add file content validation (magic bytes verification)
2. Implement upload rate limiting per organization
3. Add encryption at rest for sensitive files
4. Implement automated threat feeds for ClamAV

---

## 10. KEY FILES REFERENCE

### Core Components
- [DocumentUploadView](../apps/documents/views.py#L48) - Generic document upload
- [InvoiceUploadView](../apps/invoices/views.py#L878) - Invoice batch upload
- [DocumentUploadRouter](../core/services/upload_router.py) - Central dispatcher
- [AuditFileViewSet](../apps/file_management/views.py#L175) - File management uploads

### Models
- [Document](../apps/documents/models.py) - Document record
- [Invoice](../apps/invoices/models.py) - Invoice record
- [AuditFile](../apps/storage_management/models.py#L147) - File management file
- [FileVersion](../apps/storage_management/models.py) - Version tracking

### Validation & Security
- [DocumentUploadSerializer](../apps/documents/serializers.py#L19) - Document validation
- [AuditDocumentUploadForm](../apps/auditing/forms.py) - Auditor upload form
- [zip_validator.py](../core/services/zip_validator.py) - ZIP bomb protection
- [MalwareScanResultRule](../apps/rule_engine/rules/security/security_rules.py#L301) - Malware rule

### Tests
- [test_zip_bomb_protection.py](../tests/test_zip_bomb_protection.py) - ZIP validation tests
- [test_upload_pipeline.py](../tests/test_upload_pipeline.py) - Upload pipeline tests

### Documentation
- [AUDITOR_UPLOAD_ENHANCEMENTS.md](../AUDITOR_UPLOAD_ENHANCEMENTS.md) - Upload feature summary
- [ZIP_HARDENING_IMPLEMENTATION.md](../ZIP_HARDENING_IMPLEMENTATION.md) - ZIP protection details
- [COMPREHENSIVE_GAP_ANALYSIS.json](../COMPREHENSIVE_GAP_ANALYSIS.json) - Gap #5 malware scanning

---

**END OF AUDIT DOCUMENT**
