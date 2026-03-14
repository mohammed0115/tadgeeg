# OCR Pipeline API Reference

**Date:** March 13, 2026  
**Version:** 1.0  
**Base URL:** `http://localhost:8000` or `https://api.finai.sa`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Health Check Endpoints](#health-check-endpoints)
3. [Document Upload & Processing](#document-upload--processing)
4. [Error Responses](#error-responses)
5. [Rate Limiting](#rate-limiting)

---

## Authentication

All API endpoints (except health checks) require JWT Bearer token authentication.

```bash
# Get token
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"user@finai.sa","password":"password"}'

# Use token in requests
curl http://localhost:8000/api/v1/documents/ \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

## Health Check Endpoints

### GET /health/

**Description:** Full OCR pipeline health check

**Query Parameters:**
- `heavy` (boolean, default: false): Include expensive checks (API calls, worker status)
- `cache` (boolean, default: true): Use cached result if available (max age: 30s)

**Example Request:**
```bash
curl http://localhost:8000/health/?heavy=true
```

**Response (Healthy):**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-13T04:31:00Z",
  "check_duration_ms": 245.3,
  "cached": false,
  "components": {
    "redis": {
      "name": "redis",
      "status": "healthy",
      "message": "Connected",
      "response_time_ms": 1.2,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "database": {
      "name": "database",
      "status": "healthy",
      "message": "Connected",
      "response_time_ms": 3.5,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "tesseract": {
      "name": "tesseract",
      "status": "healthy",
      "message": "Tesseract 5.0.0-alpha ready",
      "response_time_ms": 125.0,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "openai_api": {
      "name": "openai_api",
      "status": "healthy",
      "message": "Model gpt-4o-2024-08-06 available",
      "response_time_ms": 85.3,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "celery_workers": {
      "name": "celery_workers",
      "status": "healthy",
      "message": "8 worker(s) active",
      "response_time_ms": 5.1,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "stuck_documents": {
      "name": "stuck_documents",
      "status": "healthy",
      "message": "No stuck documents",
      "response_time_ms": 0,
      "timestamp": "2026-03-13T04:31:00Z"
    },
    "processing_rate": {
      "name": "processing_rate",
      "status": "healthy",
      "message": "98.5% success rate (1h)",
      "response_time_ms": 0,
      "timestamp": "2026-03-13T04:31:00Z"
    }
  }
}
```

**Status Codes:**
- `200 OK`: Healthy or Degraded
- `503 Service Unavailable`: Unhealthy

**HTTP Headers:**
```
Content-Type: application/json
X-Health-Status: healthy|degraded|unhealthy
```

---

### GET /health/status/

**Description:** Quick lightweight status check (no expensive operations)

**Example Request:**
```bash
curl http://localhost:8000/health/status/
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-13T04:31:00Z",
  "critical_components": {
    "redis": "healthy",
    "database": "healthy",
    "tesseract": "healthy"
  }
}
```

**Use Case:** For quick load balancer health checks (Kubernetes, HAProxy, etc.)

---

### GET /health/pipeline/

**Description:** Alias for `/health/` - comprehensive OCR pipeline check

Same as `/health/` endpoint.

---

## Document Upload & Processing

### POST /api/v1/documents/upload/

**Description:** Upload a document for OCR processing

**Required Headers:**
```
Authorization: Bearer {token}
Content-Type: multipart/form-data
```

**Request Body:**
```
file: (binary) Document file (.pdf, .jpg, .png, .tiff, .xlsx, .csv)
document_type: (string) Type: invoice, receipt, bank_statement, etc.
notes: (string, optional) Additional context
```

**Example Request:**
```bash
curl -X POST http://localhost:8000/api/v1/documents/upload/ \
  -H "Authorization: Bearer {token}" \
  -F "file=@invoice.pdf" \
  -F "document_type=invoice" \
  -F "notes=Q1 2026 invoice"
```

**Response (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "invoice.pdf",
  "status": "pending",
  "processing_status": "pending",
  "created_at": "2026-03-13T04:31:00Z",
  "document_type": "invoice",
  "file_size": 245120,
  "message": "Document queued for processing"
}
```

### GET /api/v1/documents/{id}/

**Description:** Get document details and processing status

**Example Request:**
```bash
curl http://localhost:8000/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/ \
  -H "Authorization: Bearer {token}"
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "invoice.pdf",
  "document_type": "invoice",
  "processing_status": "completed",
  "language": "ar",
  "ocr_confidence": 87.5,
  "is_handwritten": false,
  "processing_duration_ms": 3450,
  "created_at": "2026-03-13T04:31:00Z",
  "updated_at": "2026-03-13T04:35:30Z",
  "tags": ["needs_review"],
  "extracted_data": {
    "vendor_name": "شركة النور التجارية",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-03-13",
    "total_amount": 15750.00,
    "currency": "SAR",
    "extraction_method": "gpt4o-vision",
    "ai_model_used": "gpt-4o-2024-08-06"
  },
  "quality_score": {
    "final_score": 87.5,
    "component_scores": {
      "ocr_confidence": 87.5,
      "validation_score": 90.0,
      "quality_score": 78.0
    },
    "risk_level": "low",
    "auto_processable": true,
    "flags": []
  }
}
```

### GET /api/v1/documents/{id}/extraction/

**Description:** Get extracted data with detailed validation results

**Example Request:**
```bash
curl http://localhost:8000/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/extraction/ \
  -H "Authorization: Bearer {token}"
```

**Response:**
```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "extraction_method": "gpt4o-vision",
  "ai_model_used": "gpt-4o-2024-08-06",
  "confidence": 87.5,
  "language": "ar",
  "raw_text": "... full OCR text ...",
  "structured_data": {
    "vendor_name": "شركة النور التجارية",
    "vendor_vat_number": "300123456780003",
    "invoice_number": "INV-2026-001",
    "invoice_date": "2026-03-13",
    "total_amount": 15750.00,
    "currency": "SAR",
    "line_items": [
      {
        "description": "Product A",
        "quantity": 2,
        "unit_price": 5000,
        "total": 10000
      }
    ]
  },
  "validation_results": {
    "vat_number_format": {"passed": true, "description": "Valid Saudi VAT number"},
    "invoice_number_format": {"passed": true},
    "amount_consistency": {"passed": true},
    "required_fields": {"passed": true, "missing": []}
  },
  "validation_status": "validated"
}
```

---

## Error Responses

### 400 Bad Request

```json
{
  "error": "validation_failed",
  "message": "File upload validation failed",
  "details": {
    "file": ["File too large (51MB). Max: 50MB"]
  },
  "timestamp": "2026-03-13T04:31:00Z"
}
```

### 401 Unauthorized

```json
{
  "detail": "Authentication credentials were not provided.",
  "code": "not_authenticated"
}
```

### 403 Forbidden

```json
{
  "detail": "You do not have permission to perform this action.",
  "code": "permission_denied"
}
```

### 404 Not Found

```json
{
  "error": "not_found",
  "message": "Document not found",
  "document_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 422 Unprocessable Entity

```json
{
  "error": "ocr_processing_failed",
  "message": "Document could not be processed",
  "detail": "All OCR methods failed: GPT-4o timeout, Tesseract error",
  "extraction_method": "failed",
  "timestamp": "2026-03-13T04:31:00Z"
}
```

### 429 Too Many Requests

```json
{
  "error": "rate_limit_exceeded",
  "message": "تجاوزت الحد المسموح (20 طلب / 60 ثانية). حاول لاحقاً.",
  "retry_after": 45
}
```

### 503 Service Unavailable

```json
{
  "error": "service_unavailable",
  "message": "OCR service temporarily unavailable",
  "status": "degraded",
  "retry_after": 60
}
```

---

## Rate Limiting

### Limits by Endpoint Type

| Endpoint Type | Limit | Window |
|---------------|-------|--------|
| Document Upload | 20 requests | 60 seconds |
| OCR API | 10 requests | 60 seconds |
| General API | 300 requests | 60 seconds |

**Applied per Organization, not per IP**

### Rate Limit Headers

All responses include:
```
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 15
X-RateLimit-Window: 60
```

### Handling Rate Limits

```python
import time

response = requests.post(url, headers=headers, files=files)

if response.status_code == 429:
    retry_after = int(response.headers.get('Retry-After', 60))
    print(f"Rate limited. Retry after {retry_after} seconds")
    time.sleep(retry_after)
    response = requests.post(url, headers=headers, files=files)
```

---

## Processing Status

### Document States

```
PENDING → PROCESSING → COMPLETED
                    ↓
                NEEDS_REVIEW
                    ↓
                VALIDATED
                    
PROCESSING → FAILED → PENDING (on retry)
```

### Status Meanings

- **PENDING**: Queued for processing, not yet started
- **PROCESSING**: Currently being processed by Celery worker
- **COMPLETED**: Processing finished successfully
- **NEEDS_REVIEW**: Very low confidence (<60%), needs manual review
- **VALIDATED**: Human validation complete
- **FAILED**: Processing failed (check processing_error field)

---

## Code Examples

### Python

```python
import requests
import time

BASE_URL = "http://localhost:8000"
TOKEN = "eyJhbGciOiJIUzI1NiIs..."

# Check health
response = requests.get(f"{BASE_URL}/health/")
print(f"Pipeline Status: {response.json()['status']}")

# Upload document
with open("invoice.pdf", "rb") as f:
    files = {"file": f}
    data = {
        "document_type": "invoice",
        "notes": "Monthly invoice"
    }
    response = requests.post(
        f"{BASE_URL}/api/v1/documents/upload/",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    doc_id = response.json()["id"]

# Poll for completion
processing = True
while processing:
    response = requests.get(
        f"{BASE_URL}/api/v1/documents/{doc_id}/",
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    status = response.json()["processing_status"]
    
    if status in ["completed", "failed", "needs_review"]:
        processing = False
    else:
        print(f"Status: {status}... waiting")
        time.sleep(2)

# Get results
extracted = requests.get(
    f"{BASE_URL}/api/v1/documents/{doc_id}/extraction/",
    headers={"Authorization": f"Bearer {TOKEN}"}
).json()

print(f"Vendor: {extracted['structured_data']['vendor_name']}")
print(f"Amount: {extracted['structured_data']['total_amount']}")
```

### JavaScript/Node.js

```javascript
const API_URL = "http://localhost:8000";
const token = "eyJhbGciOiJIUzI1NiIs...";

// Check health
const health = await fetch(`${API_URL}/health/`).then(r => r.json());
console.log(`Status: ${health.status}`);

// Upload document
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("document_type", "invoice");

const uploadResponse = await fetch(`${API_URL}/api/v1/documents/upload/`, {
  method: "POST",
  headers: { "Authorization": `Bearer ${token}` },
  body: formData
});

const docId = (await uploadResponse.json()).id;

// Poll for status
let status = "processing";
while (status === "processing") {
  await new Promise(r => setTimeout(r, 2000)); // Wait 2s
  
  const response = await fetch(`${API_URL}/api/v1/documents/${docId}/`, {
    headers: { "Authorization": `Bearer ${token}` }
  });
  
  status = (await response.json()).processing_status;
  console.log(`Status: ${status}`);
}

// Get extraction results
const results = await fetch(`${API_URL}/api/v1/documents/${docId}/extraction/`, {
  headers: { "Authorization": `Bearer ${token}` }
}).then(r => r.json());

console.log(`Extracted: ${JSON.stringify(results.structured_data, null, 2)}`);
```

---

## Appendix: Common Workflows

### Batch Upload & Process

```python
import concurrent.futures
import requests

docs = ["invoice1.pdf", "invoice2.pdf", "invoice3.pdf"]

def process_document(filename):
    with open(filename, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/api/v1/documents/upload/",
            files={"file": f},
            data={"document_type": "invoice"},
            headers={"Authorization": f"Bearer {TOKEN}"}
        )
    return response.json()["id"]

# Upload all in parallel
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    doc_ids = list(executor.map(process_document, docs))

print(f"Uploaded {len(doc_ids)} documents")
# Poll for completion...
```

---

**Last Updated:** March 13, 2026  
**Status:** Ready for Integration ✅
