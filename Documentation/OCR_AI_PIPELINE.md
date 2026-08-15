# FinAI OCR & AI Processing Pipeline Documentation

**Date:** March 13, 2026  
**Version:** 1.0  
**Status:** Complete Guide

---

## Table of Contents

1. [Overview](#overview)
2. [End-to-End Workflow](#end-to-end-workflow)
3. [Supported File Formats](#supported-file-formats)
4. [Tesseract OCR Configuration](#tesseract-ocr-configuration)
5. [GPT-4o Vision API Integration](#gpt-4o-vision-api-integration)
6. [Celery Task Queue Setup](#celery-task-queue-setup)
7. [Error Handling & Retry Logic](#error-handling--retry-logic)
8. [Quality Metrics & Thresholds](#quality-metrics--thresholds)
9. [Performance Optimization](#performance-optimization)
10. [Monitoring & Debugging](#monitoring--debugging)

---

## Overview

The FinAI document processing pipeline automatically:
- **Extracts** text and structured data from financial documents
- **Validates** against 30 rules for invoice quality
- **Scores** documents 0–100 based on quality & risk
- **Detects** duplicates and anomalies
- **Generates** audit narratives in Arabic/English

### Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER UPLOAD                              │
│          (Web UI or API: /documents/upload/)                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │  1. FILE VALIDATION        │
        │  - Size check (≤50MB)      │
        │  - Extension check         │
        │  - Mime type verify        │
        └────────────────┬───────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  2. DOCUMENT STORAGE               │
        │  - Save to /media/documents/       │
        │  - Generate SHA256 hash            │
        │  - Create DB record                │
        │  - Status: PENDING                 │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  3. QUEUE ASYNC TASK              │
        │  - Celery task enqueued            │
        │  - process_document_task.delay()   │
        │  - Status: PROCESSING              │
        └────────────────┬───────────────────┘
                         │
                         ▼ (Background Worker)
        ┌────────────────────────────────────┐
        │  4. CONVERT TO IMAGE               │
        │  - PDF → PNG (all pages)           │
        │  - TIFF → PNG                      │
        │  - Images → already ready          │
        │  - Multi-page handling             │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  5. TESSERACT OCR                 │
        │  - Extract raw text               │
        │  - Language detection             │
        │  - Confidence scores              │
        │  - Bounding boxes (optional)      │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  6. GPT-4o PROCESSING             │
        │  - Structured data extraction     │
        │  - Field validation               │
        │  - Format normalization           │
        │  - JSON structured output         │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  7. VALIDATION ENGINE             │
        │  - Apply 30 rules                 │
        │  - Calculate risk score           │
        │  - Assign risk level              │
        │  - Generate audit notes           │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  8. DUPLICATE DETECTION           │
        │  - SHA256 hash comparison          │
        │  - Business logic check            │
        │  - Flag duplicates                 │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  9. DATABASE PERSISTENCE          │
        │  - Save extracted data            │
        │  - Store validation results       │
        │  - Store audit trail              │
        │  - Status: COMPLETED/FAILED       │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  10. USER NOTIFICATION            │
        │  - Email alert                    │
        │  - WebSocket real-time update     │
        │  - Dashboard refresh              │
        └────────────────────────────────────┘
```

---

## End-to-End Workflow

### Step 1: File Upload & Validation

**Location:** `apps/documents/views.py` → `DocumentUploadView`

```python
@extend_schema(summary="Upload a financial document")
def post(self, request):
    serializer = DocumentUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    uploaded_file = serializer.validated_data["file"]
    doc_type = serializer.validated_data.get("document_type", "other")
    
    # Validate size: max 50MB (configurable via MAX_UPLOAD_SIZE)
    if uploaded_file.size > settings.MAX_UPLOAD_SIZE:
        return Response(
            {"error": f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    
    # Validate extension
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        return Response(
            {"error": f"Unsupported file type. Allowed: {settings.ALLOWED_UPLOAD_EXTENSIONS}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
```

**Validation Rules:**
- File size: ≤ 50MB (configurable)
- Extensions: `.pdf`, `.xlsx`, `.csv`, `.jpg`, `.jpeg`, `.png`, `.tiff`
- Organization context required (user.organization)
- File must have name & content type

### Step 2: Document Model Creation

**Location:** `apps/documents/models.py`

```python
doc = Document.objects.create(
    organization=request.user.organization,
    uploaded_by=request.user,
    file=uploaded_file,
    original_filename=uploaded_file.name,
    file_size=uploaded_file.size,
    mime_type=uploaded_file.content_type or f"application/{ext[1:]}",
    document_type=doc_type,
    processing_status=Document.ProcessingStatus.PENDING,
    notes=serializer.validated_data.get("notes", ""),
)
```

**Key Fields:**
- `processing_status`: PENDING → PROCESSING → COMPLETED/FAILED/NEEDS_REVIEW
- `language`: AUTO-DETECTED during OCR (ar, en, mixed, unknown)
- `ocr_confidence`: 0-100 score from Tesseract
- `processing_error`: Error message if processing fails

### Step 3: Async Task Enqueue

**Location:** `apps/documents/tasks.py`

```python
from celery import shared_task
from core.services.ocr_service import process_document_hybrid

@shared_task(bind=True, max_retries=3)
def process_document_task(self, doc_id):
    """
    Background task: Process document with OCR + AI
    
    Retries 3 times with exponential backoff on failure
    """
    try:
        doc = Document.objects.get(pk=doc_id)
        doc.processing_status = Document.ProcessingStatus.PROCESSING
        doc.save(update_fields=["processing_status"])
        
        # Call hybrid OCR + AI processing
        result = process_document_hybrid(doc)
        
        # Save extracted data
        extracted_data, created = ExtractedData.objects.get_or_create(
            document=doc,
            defaults={
                "raw_text": result["raw_text"],
                "structured_data": result["structured_data"],
                "extraction_method": "hybrid",
                "ai_model_used": "tesseract+gpt4o-vision",
            }
        )
        
        # Update document status
        doc.processing_status = Document.ProcessingStatus.COMPLETED
        doc.save()
        
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
```

**Task Configuration:**
- Max retries: 3
- Retry backoff: 2^attempt seconds (2s, 4s, 8s)
- Timeout: 600 seconds (10 minutes)
- Queue: `default` (use `priority` queue for urgent documents)

### Step 4: File Conversion

**Location:** `core/services/ocr_service.py`

```python
def convert_to_images(file_path: str) -> List[str]:
    """Convert PDF/TIFF to PNG images for OCR processing"""
    
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        # PDF → PNG (all pages)
        return convert_pdf_to_images(file_path)
    
    elif ext == ".tiff" or ext == ".tif":
        # TIFF → PNG
        return convert_tiff_to_images(file_path)
    
    elif ext in [".jpg", ".jpeg", ".png"]:
        # Already image format
        return [file_path]
    
    elif ext == ".xlsx":
        # Excel → Images (render as PDF first)
        return convert_excel_to_images(file_path)
    
    raise ValueError(f"Unsupported format: {ext}")

def convert_pdf_to_images(pdf_path: str) -> List[str]:
    """Convert multi-page PDF to individual PNG files"""
    import fitz  # PyMuPDF
    
    doc = fitz.open(pdf_path)
    images = []
    
    for page_num, page in enumerate(doc):
        # Render page at 150 DPI for OCR
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        
        img_path = f"{pdf_path}_page_{page_num}.png"
        pix.save(img_path)
        images.append(img_path)
    
    doc.close()
    return images
```

**Supported Conversions:**
- PDF (multi-page) → PNG per page
- TIFF → PNG
- XLSX (Excel) → PDF → PNG
- JPG, PNG → Direct OCR (no conversion)

---

## Supported File Formats

### Detailed Format Support

| Format | Extension | Max Size | Pages | Confidence |
|--------|-----------|----------|-------|------------|
| PDF | `.pdf` | 50MB | Multi | High |
| XLSX | `.xlsx` | 50MB | Single | Medium |
| JPG/JPEG | `.jpg`, `.jpeg` | 50MB | Single | High |
| PNG | `.png` | 50MB | Single | High |
| TIFF | `.tiff`, `.tif` | 50MB | Multi | High |
| CSV | `.csv` | 50MB | N/A | N/A (direct parsing) |

### Format-Specific Notes

**PDF:**
- Automatically splits multi-page documents
- Renders at 150 DPI for optimal OCR quality
- Handles embedded images and scanned PDFs

**XLSX (Excel):**
- Converts to PDF first, then to images
- Single sheet processing (sheet1 default)
- Numbers formatted as currency recognized

**JPG/PNG/TIFF:**
- Direct OCR without conversion
- Recommended minimum 200 DPI for scanned documents
- Color images OK (auto-converted to grayscale for OCR)

**CSV:**
- Direct parsing (no OCR needed)
- Used for bulk invoice imports
- Format: tab-separated or comma-separated values

---

## Tesseract OCR Configuration

### Installation

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-ara

# macOS
brew install tesseract

# Docker (included in Dockerfile)
RUN apt-get install -y tesseract-ocr tesseract-ocr-ara
```

### Python Configuration

**Location:** `core/services/ocr_service.py`

```python
import pytesseract
from PIL import Image

# Configure Tesseract path (if custom installation)
pytesseract.pytesseract.pytesseract_cmd = r'/usr/bin/tesseract'

# Advanced configuration
TESSERACT_CONFIG = '--psm 3 --oem 1'
# PSM (Page Segmentation Mode):
#   3 = Fully automatic page segmentation (default)
#   6 = Uniform block of text
#   11 = Sparse text
#   13 = Raw line text
#
# OEM (OCR Engine Mode):
#   0 = Legacy engine
#   1 = Neural net engine (better accuracy)
#   2 = Both engines
#   3 = Default (auto-select)

def extract_text_with_tesseract(image_path: str, language: str = "ara+eng") -> dict:
    """
    Extract text from image using Tesseract OCR
    
    Args:
        image_path: Path to image file
        language: OCR language(s) ['ara', 'eng', 'ara+eng']
    
    Returns:
        {
            "text": "extracted text",
            "confidence": 87.5,  # 0-100
            "language": "mixed",
            "details": {}  # per-word confidence if requested
        }
    """
    
    img = Image.open(image_path)
    
    # Pre-processing for better OCR
    img = preprocess_image_for_ocr(img)
    
    # Extract with configuration
    text = pytesseract.image_to_string(
        img,
        lang=language,
        config=TESSERACT_CONFIG
    )
    
    # Get detailed information
    data = pytesseract.image_to_data(
        img,
        lang=language,
        output_type=pytesseract.Output.DICT
    )
    
    # Calculate average confidence
    confidences = [int(c) for c in data['conf'] if int(c) > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
    
    return {
        "text": text.strip(),
        "confidence": avg_confidence,
        "language": detect_language(text),
        "word_count": len(data['text']),
        "details": data
    }

def preprocess_image_for_ocr(img: Image) -> Image:
    """Preprocess image for better OCR accuracy"""
    from PIL import ImageEnhance, ImageFilter
    
    # Convert to grayscale
    if img.mode != 'L':
        img = img.convert('L')
    
    # Enhance contrast
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2)
    
    # Enhance sharpness
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(2)
    
    # Remove noise using median filter
    img = img.filter(ImageFilter.MedianFilter(size=3))
    
    # Optional: Denoise using bilateral filter (slower but better quality)
    # img = cv2.bilateralFilter(np.array(img), 9, 75, 75)
    # img = Image.fromarray(img)
    
    return img

def detect_language(text: str) -> str:
    """Detect if text contains Arabic, English, or both"""
    import re
    
    arabic_pattern = re.compile(r'[\u0600-\u06FF]')
    english_pattern = re.compile(r'[a-zA-Z]')
    
    has_arabic = bool(arabic_pattern.search(text))
    has_english = bool(english_pattern.search(text))
    
    if has_arabic and has_english:
        return "mixed"
    elif has_arabic:
        return "ar"
    elif has_english:
        return "en"
    else:
        return "unknown"
```

### Language Detection

**Supported Languages:**
- Arabic: `ara`
- English: `eng`
- Mixed: `ara+eng`

**Auto-Detection:**
```python
# Tesseract can auto-detect if language code is omitted
text = pytesseract.image_to_string(img)  # Auto-detect
```

### Confidence Scoring

- **0-50:** Low confidence (manual review recommended)
- **50-75:** Medium confidence (acceptable with caveats)
- **75-100:** High confidence (use as-is)

---

## GPT-4o Vision API Integration

### Configuration

**Location:** `.env`

```env
OPENAI_API_KEY=sk-proj-xxxxx
GPT_MODEL=gpt-4o-2024-08-06
GPT_TEMPERATURE=0.2
GPT_MAX_TOKENS=2000
```

**Location:** `finai_backend/settings.py`

```python
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GPT_MODEL = os.environ.get("GPT_MODEL", "gpt-4o-2024-08-06")
GPT_TEMPERATURE = float(os.environ.get("GPT_TEMPERATURE", "0.2"))
GPT_MAX_TOKENS = int(os.environ.get("GPT_MAX_TOKENS", "2000"))
```

### API Integration

**Location:** `core/services/invoice_ai_service.py`

```python
from openai import OpenAI
import base64

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def extract_invoice_data_gpt4o(image_path: str, raw_text: str = "") -> dict:
    """
    Use GPT-4o Vision to extract structured invoice data
    
    Args:
        image_path: Path to invoice image
        raw_text: Raw text from Tesseract (optional context)
    
    Returns:
        {
            "vendor_name": "...",
            "invoice_number": "...",
            "invoice_date": "2026-03-13",
            "amount_before_tax": 1000.00,
            "tax_rate": 15,
            "tax_amount": 150.00,
            "amount_total": 1150.00,
            "currency": "SAR",
            "vat_number": "300012345600003",
            "qr_code_present": true,
            "payment_terms": "Net 30",
            "purchase_order": "PO-2026-001",
            "line_items": [
                {
                    "description": "Product X",
                    "quantity": 2,
                    "unit_price": 500,
                    "amount": 1000
                }
            ]
        }
    """
    
    # Encode image to base64
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    # Build prompt for structured extraction
    prompt = f"""You are an expert financial document analyst specializing in invoice processing.
    
Analyze this invoice image and extract ALL financial data into a structured JSON format.

IMPORTANT: Return ONLY valid JSON, no markdown code blocks or explanations.

{f"Raw OCR text for reference: {raw_text[:500]}" if raw_text else ""}

Extract the following fields:
{{
    "vendor_name": "Full company name of the service provider",
    "vendor_vat": "Tax ID/VAT number if visible",
    "invoice_number": "Invoice reference number",
    "invoice_date": "YYYY-MM-DD format",
    "due_date": "YYYY-MM-DD format if present",
    "amount_before_tax": "Subtotal as decimal number",
    "tax_rate": "Tax percentage (e.g., 15 for 15%)",
    "tax_amount": "Tax as decimal number",
    "amount_total": "Total including tax",
    "currency": "Currency code (SAR, AED, etc.)",
    "qr_code_present": true or false,
    "payment_terms": "Payment terms if present",
    "purchase_order": "PO number if referenced",
    "line_items": [
        {{
            "description": "Item description",
            "quantity": 1,
            "unit_price": 0.00,
            "amount": 0.00
        }}
    ],
    "confidence": 85.5,
    "warnings": ["Any data quality issues"]
}}

Guidelines:
- Use null for missing fields
- Dates must be YYYY-MM-DD format
- Currency should be 3-letter code
- Confidence score 0-100
- Report any data quality issues in warnings"""

    response = client.messages.create(
        model=settings.GPT_MODEL,
        max_tokens=settings.GPT_MAX_TOKENS,
        temperature=settings.GPT_TEMPERATURE,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    }
                ],
            }
        ],
    )
    
    # Parse response
    response_text = response.content[0].text
    
    try:
        import json
        extracted_data = json.loads(response_text)
        extracted_data["extraction_method"] = "gpt4o-vision"
        extracted_data["model_used"] = settings.GPT_MODEL
        return extracted_data
    except json.JSONDecodeError:
        # Fallback: try to extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        raise ValueError(f"Failed to parse GPT response: {response_text[:200]}")

def validate_extracted_data(data: dict) -> dict:
    """Validate and normalize extracted data"""
    
    # Type conversions
    try:
        if data.get("amount_before_tax"):
            data["amount_before_tax"] = float(data["amount_before_tax"])
        if data.get("tax_rate"):
            data["tax_rate"] = float(data["tax_rate"])
        if data.get("tax_amount"):
            data["tax_amount"] = float(data["tax_amount"])
        if data.get("amount_total"):
            data["amount_total"] = float(data["amount_total"])
    except (ValueError, TypeError):
        pass
    
    # Data quality checks
    warnings = data.get("warnings", [])
    
    if not data.get("vendor_name"):
        warnings.append("Vendor name missing")
    if not data.get("invoice_number"):
        warnings.append("Invoice number missing")
    if not data.get("invoice_date"):
        warnings.append("Invoice date missing")
    if not data.get("amount_total"):
        warnings.append("Total amount missing")
    
    data["warnings"] = warnings
    data["validated"] = len(warnings) == 0
    
    return data
```

### Cost Optimization

**GPT-4o Vision Pricing (as of March 2026):**
- Input: $10/million tokens
- Output: $30/million tokens

**Optimization Strategies:**

```python
def optimize_for_cost(image_path: str) -> str:
    """Reduce image size before sending to GPT-4o"""
    from PIL import Image
    
    img = Image.open(image_path)
    
    # Resize to max 1024x1024 (GPT-4o optimal size)
    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    
    # Compress JPEG: 80% quality
    optimized_path = image_path.replace(".png", "_optimized.jpg")
    img.save(optimized_path, "JPEG", quality=80)
    
    return optimized_path
```

**Cost per Invoice:**
- Average tokens: ~500 input + 300 output = 800 total
- Cost: ~$0.008 per invoice
- Budget for 10,000 invoices: ~$80/month

---

## Celery Task Queue Setup

### Configuration

**Location:** `finai_backend/celery.py`

```python
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finai_backend.settings')

app = Celery('finai_backend')

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure Celery settings
app.conf.update(
    # Broker settings
    broker_url=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Performance tuning
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # Task timeouts
    task_soft_time_limit=600,  # 10 minutes
    task_time_limit=900,  # 15 minutes
    
    # Retry configuration
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        'cleanup-old-documents': {
            'task': 'apps.documents.tasks.cleanup_old_documents',
            'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
        },
        'generate-daily-reports': {
            'task': 'apps.reports.tasks.generate_daily_reports',
            'schedule': crontab(hour=6, minute=0),  # Daily at 6 AM
        },
    },
)
```

**Location:** `finai_backend/settings.py`

```python
# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_QUEUES = {
    'default': {'exchange': 'default', 'binding_key': 'default'},
    'priority': {'exchange': 'priority', 'binding_key': 'priority'},
    'background': {'exchange': 'background', 'binding_key': 'background'},
}

CELERY_TASK_ROUTES = {
    'apps.documents.tasks.process_document_task': {'queue': 'default', 'priority': 10},
    'apps.reports.tasks.generate_report_task': {'queue': 'default', 'priority': 5},
    'apps.analytics.tasks.*': {'queue': 'background', 'priority': 1},
}
```

### Starting Workers

```bash
# Single worker (development)
celery -A finai_backend worker -l info

# Multiple workers with concurrency
celery -A finai_backend worker -l info -c 4 --queues=default,priority

# Separate workers by queue
celery -A finai_backend worker -l info -Q default,priority
celery -A finai_backend worker -l info -Q background

# Beat scheduler (periodic tasks)
celery -A finai_backend beat -l info

# Combined (for development only)
celery -A finai_backend worker -l info -B
```

### Docker Compose Setup

```yaml
# docker-compose.yml
version: '3.9'

services:
  web:
    image: finai:latest
    command: python manage.py runserver 0.0.0.0:8000
    depends_on:
      - redis
      - db
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0

  celery_worker:
    image: finai:latest
    command: celery -A finai_backend worker -l info -c 4
    depends_on:
      - redis
      - db
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0

  celery_beat:
    image: finai:latest
    command: celery -A finai_backend beat -l info
    depends_on:
      - redis
      - db
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=finai_db
      - POSTGRES_USER=finai_user
      - POSTGRES_PASSWORD=finai_password
```

### Task Monitoring

```python
# Monitor task status
from celery.result import AsyncResult

def get_task_status(task_id):
    task_result = AsyncResult(task_id, app=app)
    
    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": task_result.result,
        "current": task_result.info.get("current", 0) if isinstance(task_result.info, dict) else 0,
        "total": task_result.info.get("total", 100) if isinstance(task_result.info, dict) else 100,
    }

# Flower web UI for monitoring
# pip install flower
# celery -A finai_backend flower
# Access: http://localhost:5555
```

---

## Error Handling & Retry Logic

### Retry Configuration

```python
@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # Initial delay: 60 seconds
    autoretry_for=(Exception,),  # Autoretry on any exception
)
def process_document_task(self, doc_id):
    """
    Process document with automatic retries
    
    Retry schedule:
    1. Attempt 1 (immediate)
    2. Fail → Retry after 60 seconds
    3. Attempt 2 (60s)
    4. Fail → Retry after 120 seconds (2 * 60)
    5. Attempt 3 (120s)
    6. Fail → Dead letter queue
    """
    try:
        doc = Document.objects.get(pk=doc_id)
        
        # Processing logic
        result = process_document_hybrid(doc)
        
        return result
        
    except TemporaryError as exc:
        # Temporary errors: retry with exponential backoff
        retry_count = self.request.retries
        countdown = 60 * (2 ** retry_count)  # 60s, 120s, 240s
        
        logger.warning(f"Retrying task {self.request.id} (attempt {retry_count+1}/3) after {countdown}s")
        raise self.retry(exc=exc, countdown=countdown)
        
    except PermanentError as exc:
        # Permanent errors: don't retry
        logger.error(f"Permanent error in task {self.request.id}: {exc}")
        
        doc = Document.objects.get(pk=doc_id)
        doc.processing_status = Document.ProcessingStatus.FAILED
        doc.processing_error = str(exc)
        doc.save()
        
        return False
        
    except Exception as exc:
        # Unexpected errors: log and move to dead letter queue
        logger.critical(f"Unexpected error in task {self.request.id}: {exc}")
        raise
```

### Error Classification

```python
class TemporaryError(Exception):
    """Errors that might resolve on retry (network, timeout, etc)"""
    pass

class PermanentError(Exception):
    """Errors that won't resolve by retrying (validation, data errors)"""
    pass

# Examples
class GPTAPITimeoutError(TemporaryError):
    """OpenAI API timeout - retry"""
    pass

class InvalidDocumentFormatError(PermanentError):
    """Document format not supported - don't retry"""
    pass

class RedisConnectionError(TemporaryError):
    """Redis unavailable - retry"""
    pass
```

### Error Logging

```python
import logging

logger = logging.getLogger(__name__)

# Configure logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} - {name} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/ocr_errors.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'celery': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/celery.log',
            'maxBytes': 1024 * 1024 * 50,  # 50MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file', 'celery'],
        'level': 'INFO',
    },
}
```

---

## Quality Metrics & Thresholds

### Scoring System

**Total Score Calculation:**
```
Score = (OCR_Confidence × 0.3) + (Validation_Score × 0.5) + (Quality_Score × 0.2)

OCR_Confidence: 0-100 from Tesseract
Validation_Score: Based on 30 rules passed (0-100)
Quality_Score: Image quality, legibility (0-100)

Final Score Range: 0-100
```

### Score Thresholds

| Score | Risk Level | Action |
|-------|-----------|--------|
| 80-100 | ✅ Low | Auto-approve, process immediately |
| 60-79 | ⚠️ Medium | Review suggested, process with caution |
| 40-59 | 🔴 High | Manual review required before processing |
| 0-39 | 🚫 Critical | Flag for manual intervention, may reject |

### Quality Metrics

```python
class QualityMetrics:
    """Calculate document quality metrics"""
    
    def calculate_ocr_confidence(self, tesseract_result: dict) -> float:
        """Average word-level confidence from Tesseract"""
        confidences = [int(c) for c in tesseract_result.get('conf', []) if int(c) > 0]
        return sum(confidences) / len(confidences) if confidences else 0
    
    def calculate_image_quality(self, image_path: str) -> float:
        """Score image based on contrast, sharpness, noise"""
        from PIL import ImageStat, Image
        
        img = Image.open(image_path).convert('L')
        stat = ImageStat.Stat(img)
        
        # Calculate metrics
        mean = stat.mean[0]  # Average brightness
        stddev = stat.stddev[0]  # Contrast (higher = better)
        
        # Score: 0-100
        # Good contrast: 30-50 standard deviation
        contrast_score = min(100, (stddev / 50) * 100)
        
        # Good brightness: 50-200 mean value
        brightness_score = 100 - abs(mean - 125) / 125 * 100
        
        # Combined score
        quality_score = (contrast_score * 0.6) + (brightness_score * 0.4)
        return min(100, max(0, quality_score))
    
    def calculate_validation_score(self, validation_results: dict) -> float:
        """Score based on 30 rules passed"""
        total_rules = 30
        passed_rules = sum(1 for r in validation_results.values() if r.get('passed', False))
        
        return (passed_rules / total_rules) * 100
    
    def calculate_final_score(
        self,
        ocr_confidence: float,
        validation_score: float,
        quality_score: float
    ) -> float:
        """Calculate weighted final score"""
        final = (ocr_confidence * 0.3) + (validation_score * 0.5) + (quality_score * 0.2)
        return min(100, max(0, final))
```

### Risk Level Assignment

```python
def assign_risk_level(score: float, validation_results: dict) -> str:
    """
    Assign risk level based on score and specific rule failures
    
    Rules that automatically trigger HIGH/CRITICAL:
    - VAT calculation mismatch
    - Duplicate invoice detected
    - Invalid tax number format
    - Handwritten without OCR confidence
    - Missing critical fields
    """
    
    critical_rules_failed = [
        validation_results.get('vat_calculation', {}).get('passed', True),
        validation_results.get('duplicate_check', {}).get('passed', True),
        validation_results.get('vat_number_format', {}).get('passed', True),
    ]
    
    # If any critical rule failed, minimum HIGH risk
    if not all(critical_rules_failed):
        return "CRITICAL"
    
    if score >= 80:
        return "LOW"
    elif score >= 60:
        return "MEDIUM"
    elif score >= 40:
        return "HIGH"
    else:
        return "CRITICAL"
```

---

## Performance Optimization

### Batch Processing

```python
def process_documents_batch(doc_ids: list, batch_size: int = 10):
    """Process multiple documents efficiently"""
    
    for i in range(0, len(doc_ids), batch_size):
        batch = doc_ids[i:i+batch_size]
        
        # Distribute across priority queue
        for doc_id in batch:
            if i % 3 == 0:  # Every 3rd document gets priority
                process_document_task.apply_async(
                    (doc_id,),
                    queue='priority',
                    priority=10
                )
            else:
                process_document_task.delay(doc_id)
```

### Caching Strategy

```python
from django.core.cache import cache

def get_processed_document_data(doc_id: str, use_cache: bool = True):
    """Get document data with caching"""
    
    cache_key = f"doc_data:{doc_id}"
    
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached
    
    # Fetch from DB
    extracted_data = ExtractedData.objects.get(document_id=doc_id)
    data = {
        "structured": extracted_data.structured_data,
        "text": extracted_data.raw_text,
        "status": extracted_data.validation_status,
    }
    
    # Cache for 1 hour
    cache.set(cache_key, data, 3600)
    
    return data
```

### Query Optimization

```python
# Inefficient: N+1 queries
documents = Document.objects.filter(organization=org)
for doc in documents:
    extracted = doc.extracted_data  # Extra query per document

# Optimized: Single query with select_related
documents = Document.objects.filter(
    organization=org
).select_related('extracted_data', 'uploaded_by').only(
    'id', 'original_filename', 'processing_status', 'created_at'
)
```

### Parallel Processing

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def process_multi_page_document(image_paths: list) -> list:
    """Process multiple pages in parallel"""
    
    results = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(process_single_page, path): path
            for path in image_paths
        }
        
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                logger.error(f"Error processing page: {exc}")
    
    return results

def process_single_page(image_path: str) -> dict:
    """Process single page OCR"""
    tesseract_result = extract_text_with_tesseract(image_path)
    return tesseract_result
```

---

## Monitoring & Debugging

### Health Checks

```python
def check_ocr_pipeline_health() -> dict:
    """Check overall pipeline health"""
    
    from django.core.cache import cache
    import redis
    
    health = {
        "status": "healthy",
        "components": {}
    }
    
    # Check Redis
    try:
        redis_conn = redis.StrictRedis.from_url(settings.CELERY_BROKER_URL)
        redis_conn.ping()
        health["components"]["redis"] = "✅"
    except Exception as e:
        health["components"]["redis"] = f"❌ {str(e)}"
        health["status"] = "degraded"
    
    # Check Celery workers
    from celery.app.control import Inspect
    insp = Inspect()
    active_workers = insp.active()
    
    if active_workers:
        health["components"]["celery_workers"] = f"✅ {len(active_workers)} active"
    else:
        health["components"]["celery_workers"] = "⚠️ No workers active"
        health["status"] = "degraded"
    
    # Check recent document processing
    recent_docs = Document.objects.filter(
        created_at__gte=timezone.now() - timedelta(hours=1)
    ).values('processing_status').annotate(count=Count('id'))
    
    health["components"]["recent_documents"] = {r["processing_status"]: r["count"] for r in recent_docs}
    
    # Check for stuck processing
    stuck = Document.objects.filter(
        processing_status=Document.ProcessingStatus.PROCESSING,
        updated_at__lt=timezone.now() - timedelta(minutes=30)
    ).count()
    
    if stuck > 0:
        health["components"]["stuck_documents"] = f"⚠️ {stuck} documents stuck"
        health["status"] = "degraded"
    else:
        health["components"]["stuck_documents"] = "✅"
    
    return health
```

### Debugging Tools

```bash
# Monitor Celery tasks in real-time
celery -A finai_backend events

# Inspect active tasks
from celery.app.control import Inspect
insp = Inspect()
print(insp.active())

# View task queue stats
print(insp.stats())

# Look at task history
from celery import current_app
current_app.control.pool.collect_replies(timeout=1, callback=print)
```

### Logs

**Location:** `logs/`
- `ocr_errors.log` - OCR/AI processing errors
- `celery.log` - Task queue logs
- `django.log` - Application errors

**Log Levels:**
- `DEBUG` - Detailed information for debugging
- `INFO` - General informational messages
- `WARNING` - Warning messages for potential issues
- `ERROR` - Error messages when something fails
- `CRITICAL` - Critical errors requiring immediate attention

---

## Troubleshooting

### Common Issues & Solutions

**Issue: "Tesseract not found"**
```
Solution: Install Tesseract or set path in pytesseract.pytesseract_cmd
```

**Issue: "GPT-4o API rate limit exceeded"**
```
Solution: Implement exponential backoff, use cheaper gpt-4-turbo model
```

**Issue: "Celery task stuck in PROCESSING"**
```
Solution: 
1. Check if worker is running: celery -A finai_backend inspect active
2. Restart stuck task: celery -A finai_backend control shutdown
3. Requeue stuck documents: 
   Document.objects.filter(
       processing_status=ProcessingStatus.PROCESSING,
       updated_at__lt=timezone.now()-timedelta(hours=1)
   ).update(processing_status=ProcessingStatus.PENDING)
```

**Issue: "Low OCR confidence on scanned images"**
```
Solution:
1. Increase DPI in PDF conversion (currently 150)
2. Improve image preprocessing (contrast, sharpness)
3. Try different Tesseract PSM modes (currently 3)
4. Use GPT-4o fallback for difficult documents
```

---

**Last Updated:** March 13, 2026  
**Version:** 1.0 - Complete  
**Status:** Production Ready ✅

