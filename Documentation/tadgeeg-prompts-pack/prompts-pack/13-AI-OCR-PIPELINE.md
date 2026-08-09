# 🤖 13 — الذكاء الاصطناعي + OCR Pipeline

> Prompts لتطوير `apps/auditing/` والـ AI/OCR pipeline (GPT-4o + Tesseract)

---

## 🎯 Prompt 13.1 — OCR Service مع Tesseract

```
في مشروع Tadgeeg AI، الـ OCR pipeline يستخدم Tesseract:

# المطلوب: Service موحّد للـ OCR

```python
# apps/auditing/services/ocr.py
import pytesseract
from PIL import Image
import cv2
import numpy as np
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class TesseractOCRService:
    """OCR using Tesseract with Arabic + English support"""
    
    SUPPORTED_LANGS = 'ara+eng'  # Arabic + English
    
    def __init__(self, lang=None):
        self.lang = lang or self.SUPPORTED_LANGS
    
    def extract_text(self, image_path: str, preprocess: bool = True) -> dict:
        """
        Extract text from image with confidence scores
        Returns: {
            'text': str,
            'confidence': float (0-100),
            'words': [{text, conf, bbox}, ...],
            'lang_detected': str,
        }
        """
        try:
            if preprocess:
                image = self._preprocess(image_path)
            else:
                image = Image.open(image_path)
            
            # Get text
            text = pytesseract.image_to_string(image, lang=self.lang)
            
            # Get detailed data with confidence
            data = pytesseract.image_to_data(
                image, lang=self.lang,
                output_type=pytesseract.Output.DICT
            )
            
            # Filter and structure words
            words = []
            for i in range(len(data['text'])):
                conf = int(data['conf'][i])
                if conf > 0 and data['text'][i].strip():
                    words.append({
                        'text': data['text'][i],
                        'conf': conf,
                        'bbox': {
                            'x': data['left'][i],
                            'y': data['top'][i],
                            'w': data['width'][i],
                            'h': data['height'][i],
                        }
                    })
            
            avg_conf = sum(w['conf'] for w in words) / len(words) if words else 0
            
            return {
                'text': text.strip(),
                'confidence': avg_conf,
                'words': words,
                'word_count': len(words),
                'lang_detected': self._detect_language(text),
            }
        except Exception as e:
            logger.error(f"OCR error: {e}", exc_info=True)
            raise
    
    def _preprocess(self, image_path: str) -> np.ndarray:
        """Preprocess image for better OCR accuracy"""
        img = cv2.imread(image_path)
        
        # 1. Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. Denoise
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        
        # 3. Adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            denoised, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        
        # 4. Deskew (rotation correction)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) > 0:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            
            (h, w) = thresh.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            thresh = cv2.warpAffine(
                thresh, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
        
        return thresh
    
    def _detect_language(self, text: str) -> str:
        """Simple language detection based on script"""
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        latin_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
        
        if arabic_chars > latin_chars:
            return 'ar'
        return 'en'
    
    def extract_from_pdf(self, pdf_path: str) -> list:
        """Extract text from each page of PDF"""
        from pdf2image import convert_from_path
        
        images = convert_from_path(pdf_path, dpi=300)
        results = []
        
        for i, img in enumerate(images):
            tmp_path = f'/tmp/pdf_page_{i}.png'
            img.save(tmp_path, 'PNG')
            
            result = self.extract_text(tmp_path)
            result['page'] = i + 1
            results.append(result)
            
            Path(tmp_path).unlink()
        
        return results
```

# Tests:
```python
# tests/test_ocr_service.py
import pytest
from apps.auditing.services.ocr import TesseractOCRService

@pytest.fixture
def ocr():
    return TesseractOCRService()

def test_extract_arabic_text(ocr):
    result = ocr.extract_text('tests/fixtures/arabic_invoice.png')
    assert result['confidence'] > 80
    assert 'فاتورة' in result['text']
    assert result['lang_detected'] == 'ar'

def test_extract_english_text(ocr):
    result = ocr.extract_text('tests/fixtures/english_invoice.png')
    assert result['confidence'] > 80
    assert 'Invoice' in result['text']
```

أعطني:
1. الـ OCR Service الكامل
2. Helpers للـ preprocessing
3. PDF support
4. Tests
5. انظر `Docs/OCR_AI_PIPELINE.md` للمرجع
```

---

## 🎯 Prompt 13.2 — GPT-4o Vision Extraction Service

```
في مشروع Tadgeeg AI، استخراج البيانات من الفواتير يستخدم GPT-4o Vision.

# المطلوب:

```python
# apps/auditing/services/gpt_extractor.py
import base64
import json
from openai import OpenAI
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class GPT4oVisionExtractor:
    """Extract structured data from invoices using GPT-4o Vision"""
    
    SYSTEM_PROMPT = """أنت مساعد متخصص في استخراج البيانات من الفواتير العربية والإنجليزية.

مهمتك:
1. تحليل صورة الفاتورة بدقة عالية
2. استخراج جميع الحقول المطلوبة
3. إرجاع الإجابة بصيغة JSON صحيحة فقط (بدون أي نص إضافي)
4. عدم تخمين أي قيمة - إذا غير متوفرة استخدم null
5. إذا الحقل غامض، أرفق confidence score

كن دقيقاً جداً مع:
- الأرقام (الفواتير، VAT)
- التواريخ (استخدم ISO 8601: YYYY-MM-DD)
- المبالغ (decimal، فصل العشري بنقطة)
- الأسماء (انسخها حرفياً كما تظهر)
"""
    
    USER_PROMPT_TEMPLATE = """استخرج البيانات التالية من الفاتورة:

```json
{{
  "vendor_name": "اسم المورد كما يظهر",
  "vendor_vat_number": "الرقم الضريبي للمورد (15 رقم)",
  "vendor_address": "عنوان المورد",
  "customer_name": "اسم العميل",
  "customer_vat_number": "الرقم الضريبي للعميل",
  "invoice_number": "رقم الفاتورة",
  "invoice_date": "YYYY-MM-DD",
  "invoice_time": "HH:MM:SS أو null",
  "currency": "SAR/AED/USD/EUR/etc",
  "subtotal": 100.00,
  "vat_amount": 15.00,
  "total_amount": 115.00,
  "vat_rate": 0.15,
  "payment_method": "cash/card/transfer/null",
  "qr_code_present": true,
  "language": "ar/en/mixed",
  "line_items": [
    {{
      "description": "الوصف",
      "quantity": 1,
      "unit_price": 100.00,
      "total": 100.00
    }}
  ],
  "confidence": {{
    "overall": 95,
    "vendor_name": 100,
    "amounts": 98,
    "dates": 100
  }},
  "warnings": [
    "تحذيرات إن وجدت"
  ],
  "language_detected": "ar"
}}
```

النص المستخرج بـ OCR (للمساعدة):
{ocr_text}

OCR Confidence: {ocr_confidence}%
"""
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
    
    def extract(self, image_path: str, ocr_text: str = '', ocr_confidence: float = 0) -> dict:
        """
        Extract structured data from invoice image
        """
        try:
            # Encode image
            with open(image_path, 'rb') as f:
                image_b64 = base64.b64encode(f.read()).decode('utf-8')
            
            # Determine MIME type
            ext = image_path.lower().split('.')[-1]
            mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'webp': 'webp'}.get(ext, 'jpeg')
            
            # Build prompt
            user_prompt = self.USER_PROMPT_TEMPLATE.format(
                ocr_text=ocr_text[:2000],  # truncate
                ocr_confidence=int(ocr_confidence)
            )
            
            # Call GPT-4o
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/{mime};base64,{image_b64}",
                            "detail": "high"
                        }}
                    ]}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2000,
            )
            
            # Parse response
            raw = response.choices[0].message.content
            data = json.loads(raw)
            
            # Add metadata
            data['_meta'] = {
                'model': self.model,
                'tokens_used': response.usage.total_tokens,
                'finish_reason': response.choices[0].finish_reason,
            }
            
            return data
        
        except json.JSONDecodeError as e:
            logger.error(f"GPT response not valid JSON: {raw}")
            raise ValueError(f"Invalid GPT response: {e}")
        except Exception as e:
            logger.error(f"GPT extraction error: {e}", exc_info=True)
            raise
    
    def extract_with_retry(self, image_path: str, ocr_text: str = '', max_retries: int = 3) -> dict:
        """Extract with automatic retry on failure"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return self.extract(image_path, ocr_text)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)  # exponential backoff
        raise last_error
```

# Tests:
```python
# tests/test_gpt_extractor.py
@pytest.mark.django_db
def test_extract_invoice():
    extractor = GPT4oVisionExtractor()
    result = extractor.extract('tests/fixtures/sample_invoice.png')
    
    assert 'vendor_name' in result
    assert 'invoice_number' in result
    assert isinstance(result['total_amount'], (int, float))
    assert result['confidence']['overall'] > 80
```

أعطني الـ Service الكامل + Tests + integration with invoice processing.
```

---

## 🎯 Prompt 13.3 — Full Pipeline (OCR + GPT + Audit)

```
في مشروع Tadgeeg AI، أحتاج Pipeline كامل من رفع الملف لاكتمال التدقيق:

# المطلوب:

```python
# apps/auditing/services/pipeline.py
from celery import shared_task
import logging

logger = logging.getLogger(__name__)

class InvoiceProcessingPipeline:
    """Full pipeline: OCR → GPT-4o → Validation → Audit Rules → Risk Score"""
    
    def __init__(self):
        self.ocr_service = TesseractOCRService()
        self.gpt_service = GPT4oVisionExtractor()
        self.audit_runner = AuditRunner()
    
    def process(self, invoice):
        """Process an invoice through all stages"""
        try:
            # Stage 1: Update status
            invoice.status = 'processing'
            invoice.processing_started_at = timezone.now()
            invoice.save()
            
            self._send_progress(invoice, 'ocr_started', 10)
            
            # Stage 2: OCR
            ocr_result = self.run_ocr(invoice)
            invoice.ocr_text = ocr_result['text']
            invoice.ocr_confidence = ocr_result['confidence']
            invoice.save()
            
            self._send_progress(invoice, 'ocr_completed', 30)
            
            # Stage 3: GPT-4o Extraction
            self._send_progress(invoice, 'ai_extraction_started', 40)
            
            extracted = self.gpt_service.extract_with_retry(
                image_path=invoice.original_file.path,
                ocr_text=ocr_result['text'],
                ocr_confidence=ocr_result['confidence']
            )
            
            self._populate_invoice(invoice, extracted)
            self._send_progress(invoice, 'ai_extraction_completed', 60)
            
            # Stage 4: Validation
            self._send_progress(invoice, 'validation_started', 70)
            self.validate_data(invoice)
            
            # Stage 5: Audit Rules (30 rules)
            self._send_progress(invoice, 'audit_started', 80)
            audit_results = self.audit_runner.run_all(invoice)
            
            # Stage 6: Risk Score
            self._send_progress(invoice, 'risk_calculation', 90)
            invoice.audit_score = self._calculate_score(audit_results)
            invoice.risk_level = self._determine_risk(invoice.audit_score)
            
            # Stage 7: Compliance Check
            self.run_compliance_checks(invoice)
            
            # Stage 8: Fraud Detection
            invoice.fraud_score = self._calculate_fraud_score(invoice)
            
            # Stage 9: Generate Summary
            self.generate_audit_summary(invoice)
            
            # Stage 10: Final Status
            if invoice.ocr_confidence < 80:
                invoice.status = 'pending_review'  # needs human review
            elif invoice.risk_level in ['high', 'critical']:
                invoice.status = 'flagged'
            else:
                invoice.status = 'validated'
            
            invoice.processing_completed_at = timezone.now()
            invoice.save()
            
            self._send_progress(invoice, 'completed', 100)
            self._send_notification(invoice)
            
            return invoice
        
        except Exception as e:
            logger.error(f"Pipeline failed for invoice {invoice.id}: {e}", exc_info=True)
            invoice.status = 'error'
            invoice.error_message = str(e)
            invoice.save()
            raise
    
    def run_ocr(self, invoice):
        """Run OCR based on file type"""
        file_path = invoice.original_file.path
        
        if file_path.lower().endswith('.pdf'):
            results = self.ocr_service.extract_from_pdf(file_path)
            # Combine pages
            text = '\n'.join(r['text'] for r in results)
            avg_conf = sum(r['confidence'] for r in results) / len(results)
            return {'text': text, 'confidence': avg_conf}
        else:
            return self.ocr_service.extract_text(file_path)
    
    def _populate_invoice(self, invoice, data):
        """Populate invoice fields from GPT extraction"""
        invoice.vendor_name = data.get('vendor_name', '')
        invoice.vendor_vat_number = data.get('vendor_vat_number', '')
        invoice.invoice_number = data.get('invoice_number', '')
        
        if data.get('invoice_date'):
            invoice.invoice_date = data['invoice_date']
        
        invoice.subtotal = data.get('subtotal', 0)
        invoice.vat_amount = data.get('vat_amount', 0)
        invoice.total_amount = data.get('total_amount', 0)
        invoice.currency = data.get('currency', 'SAR')
        
        invoice.extracted_data = data  # store full JSON
        invoice.ai_confidence = data.get('confidence', {}).get('overall', 0)
        invoice.save()
        
        # Save line items
        if data.get('line_items'):
            from apps.invoices.models import InvoiceLineItem
            InvoiceLineItem.objects.filter(invoice=invoice).delete()
            for item in data['line_items']:
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description=item.get('description', ''),
                    quantity=item.get('quantity', 1),
                    unit_price=item.get('unit_price', 0),
                    total=item.get('total', 0),
                )
    
    def validate_data(self, invoice):
        """Basic validation"""
        validator = VATValidator()
        result = validator.validate_vat_calculation(invoice)
        if not result['valid']:
            logger.warning(f"VAT calculation issue for {invoice.id}: {result}")
    
    def run_compliance_checks(self, invoice):
        """ZATCA + other compliance"""
        from apps.compliance.services import ZATCAValidator
        ZATCAValidator().validate(invoice)
    
    def _calculate_score(self, audit_results):
        """Calculate audit score 0-100"""
        # ... (see 08-AUDIT-ENGINE.md)
        pass
    
    def _determine_risk(self, score):
        if score >= 90: return 'low'
        if score >= 75: return 'medium'
        if score >= 60: return 'high'
        return 'critical'
    
    def _calculate_fraud_score(self, invoice):
        """Calculate fraud probability 0-100"""
        score = 0
        # Check for round numbers (fraud indicator)
        if invoice.total_amount % 100 == 0: score += 5
        # Check Benford's Law
        # Check vendor history
        # Check duplicates
        # ... etc
        return score
    
    def generate_audit_summary(self, invoice):
        """Generate AI narrative summary"""
        from openai import OpenAI
        client = OpenAI()
        
        # Generate Arabic summary
        prompt_ar = f"""اكتب ملخص قصير (3-5 جمل) لتدقيق هذه الفاتورة:
- المورد: {invoice.vendor_name}
- المبلغ: {invoice.total_amount} {invoice.currency}
- الـ Score: {invoice.audit_score}
- المستوى: {invoice.risk_level}
- عدد المشاكل: {invoice.audit_results.filter(passed=False).count()}

اذكر النقاط المهمة بشكل احترافي."""
        
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{"role": "user", "content": prompt_ar}],
            max_tokens=300,
        )
        invoice.summary_ar = response.choices[0].message.content
        invoice.save(update_fields=['summary_ar'])
    
    def _send_progress(self, invoice, stage, percent):
        """Send WebSocket progress update"""
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'invoice_{invoice.id}',
            {
                'type': 'progress',
                'stage': stage,
                'percent': percent,
            }
        )
    
    def _send_notification(self, invoice):
        """Send completion notification"""
        from apps.notifications.services import send_notification
        send_notification(
            user=invoice.uploaded_by,
            type='success' if invoice.status == 'validated' else 'warning',
            title='تم تحليل الفاتورة',
            message=f'الفاتورة {invoice.invoice_number} - مستوى المخاطر: {invoice.get_risk_level_display()}',
            link=f'/invoices/{invoice.id}/'
        )

# Celery task:
@shared_task(bind=True, max_retries=3, time_limit=600)
def process_invoice_task(self, invoice_id):
    from apps.invoices.models import Invoice
    invoice = Invoice.objects.get(id=invoice_id)
    
    pipeline = InvoiceProcessingPipeline()
    try:
        return str(pipeline.process(invoice).id)
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        raise
```

أعطني الـ Pipeline الكامل + Celery integration + WebSocket updates.
```

---

## ✅ Checklist

- [ ] OCR Service يعمل على Arabic + English
- [ ] GPT-4o Vision extractor يعمل
- [ ] Pipeline متكاملة من البداية للنهاية
- [ ] WebSocket progress updates
- [ ] Notifications على الإنجاز
- [ ] Error handling + retry logic
- [ ] Tests في `test_extraction_manager.py` تنجح
- [ ] Tests في `test_upload_pipeline.py` تنجح

---

**📌 انتقل لـ `14-TESTING.md`**
