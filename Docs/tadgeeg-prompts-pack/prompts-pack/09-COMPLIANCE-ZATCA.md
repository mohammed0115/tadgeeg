# ✅ 09 — الامتثال (Compliance & ZATCA Phase 2)

> Prompts لتطوير `apps/compliance/` والامتثال للمعايير الخليجية

---

## 🎯 Prompt 9.1 — ZATCA Phase 2 Integration

```
في مشروع Tadgeeg AI، تحتاج المنصة دعم كامل لـ ZATCA Phase 2 (المرحلة الثانية).

# متطلبات ZATCA Phase 2:
1. **QR Code** بصيغة TLV-Base64
2. **UUID** فريد لكل فاتورة
3. **Cryptographic Stamp** (الختم التشفيري)
4. **Previous Invoice Hash (PIH)**
5. **Invoice Counter Value (ICV)** - متسلسل
6. **XML Format** متوافق مع UBL 2.1
7. **Digital Signature** (XAdES-B-B)
8. **Reporting/Clearance** to ZATCA

# المطلوب:

## 1. Service لإنشاء QR Code:
```python
# apps/compliance/services/zatca_qr.py
import base64
from datetime import datetime

class ZATCAQRGenerator:
    """
    إنشاء QR Code بصيغة TLV-Base64 وفق متطلبات ZATCA
    
    Tags:
    1: Seller Name
    2: VAT Registration Number
    3: Invoice Date (ISO 8601)
    4: Invoice Total (with VAT)
    5: VAT Total
    """
    
    def generate(self, invoice):
        tlv = b''
        tlv += self._tlv(1, invoice.organization.name)
        tlv += self._tlv(2, invoice.organization.vat_number)
        tlv += self._tlv(3, invoice.invoice_date.isoformat())
        tlv += self._tlv(4, str(invoice.total_amount))
        tlv += self._tlv(5, str(invoice.vat_amount))
        
        return base64.b64encode(tlv).decode('utf-8')
    
    def _tlv(self, tag, value):
        value_bytes = value.encode('utf-8')
        length = len(value_bytes)
        return bytes([tag, length]) + value_bytes
```

## 2. UUID + ICV + PIH:
```python
# apps/invoices/models.py - إضافة حقول
class Invoice(SoftDeleteModel):
    # ... الحقول السابقة
    
    # ZATCA Phase 2
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    icv = models.IntegerField(unique=True)  # Invoice Counter Value
    pih = models.CharField(max_length=64, blank=True)  # Previous Invoice Hash
    invoice_hash = models.CharField(max_length=64, blank=True)  # SHA-256 of THIS invoice
    qr_code = models.TextField(blank=True)  # Base64 TLV
    cryptographic_stamp = models.TextField(blank=True)
    xml_content = models.TextField(blank=True)
    
    # ZATCA submission
    zatca_status = models.CharField(max_length=20, default='pending')
    zatca_submitted_at = models.DateTimeField(null=True, blank=True)
    zatca_response = models.JSONField(default=dict, blank=True)
    zatca_uuid = models.CharField(max_length=100, blank=True)  # ZATCA's UUID
    
    def calculate_hash(self):
        """SHA-256 hash of invoice canonical XML"""
        import hashlib
        canonical = self.to_canonical_xml()
        return hashlib.sha256(canonical.encode()).hexdigest()
    
    def get_next_icv(self):
        """ICV must be sequential per organization"""
        last = Invoice.objects.filter(
            organization=self.organization
        ).order_by('-icv').first()
        return (last.icv + 1) if last else 1
```

## 3. XML Generator (UBL 2.1):
```python
# apps/compliance/services/zatca_xml.py
from lxml import etree

class ZATCAXMLGenerator:
    NS = {
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        '': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    }
    
    def generate(self, invoice):
        root = etree.Element('Invoice', nsmap=self.NS)
        
        # ID
        etree.SubElement(root, '{cbc}ID').text = invoice.invoice_number
        
        # UUID
        etree.SubElement(root, '{cbc}UUID').text = str(invoice.uuid)
        
        # Issue Date
        etree.SubElement(root, '{cbc}IssueDate').text = invoice.invoice_date.isoformat()
        
        # Issue Time
        etree.SubElement(root, '{cbc}IssueTime').text = invoice.invoice_time.isoformat()
        
        # Invoice Type Code
        etree.SubElement(root, '{cbc}InvoiceTypeCode', name='0100000').text = '388'
        
        # Document Currency
        etree.SubElement(root, '{cbc}DocumentCurrencyCode').text = invoice.currency
        
        # ICV (additional document reference)
        adr = etree.SubElement(root, '{cac}AdditionalDocumentReference')
        etree.SubElement(adr, '{cbc}ID').text = 'ICV'
        etree.SubElement(adr, '{cbc}UUID').text = str(invoice.icv)
        
        # PIH
        if invoice.pih:
            adr_pih = etree.SubElement(root, '{cac}AdditionalDocumentReference')
            etree.SubElement(adr_pih, '{cbc}ID').text = 'PIH'
            attachment = etree.SubElement(adr_pih, '{cac}Attachment')
            ebd = etree.SubElement(attachment, '{cbc}EmbeddedDocumentBinaryObject',
                                   mimeCode='text/plain')
            ebd.text = invoice.pih
        
        # Seller (Supplier)
        self._add_party(root, '{cac}AccountingSupplierParty', invoice.organization)
        
        # Buyer (Customer)
        self._add_party(root, '{cac}AccountingCustomerParty', invoice.customer)
        
        # Tax Total
        tax_total = etree.SubElement(root, '{cac}TaxTotal')
        etree.SubElement(tax_total, '{cbc}TaxAmount', currencyID=invoice.currency).text = str(invoice.vat_amount)
        
        # Legal Monetary Total
        lmt = etree.SubElement(root, '{cac}LegalMonetaryTotal')
        etree.SubElement(lmt, '{cbc}LineExtensionAmount', currencyID=invoice.currency).text = str(invoice.subtotal)
        etree.SubElement(lmt, '{cbc}TaxExclusiveAmount', currencyID=invoice.currency).text = str(invoice.subtotal)
        etree.SubElement(lmt, '{cbc}TaxInclusiveAmount', currencyID=invoice.currency).text = str(invoice.total_amount)
        etree.SubElement(lmt, '{cbc}PayableAmount', currencyID=invoice.currency).text = str(invoice.total_amount)
        
        # Invoice Lines
        for item in invoice.line_items.all():
            self._add_invoice_line(root, item)
        
        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')
```

## 4. Digital Signature (XAdES-B-B):
```python
# apps/compliance/services/zatca_sign.py
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ec

class ZATCASigner:
    def __init__(self, private_key_pem, certificate_pem):
        self.private_key = serialization.load_pem_private_key(
            private_key_pem, password=None
        )
        self.certificate = certificate_pem
    
    def sign(self, xml_content):
        # Hash the canonical XML
        digest = hashes.Hash(hashes.SHA256())
        digest.update(xml_content)
        hash_value = digest.finalize()
        
        # Sign with ECDSA
        signature = self.private_key.sign(
            hash_value,
            ec.ECDSA(hashes.SHA256())
        )
        
        return base64.b64encode(signature).decode()
```

## 5. Submission to ZATCA:
```python
# apps/compliance/services/zatca_api.py
import requests

class ZATCAClient:
    BASE_URL = 'https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal'
    
    def __init__(self, csid, secret):
        self.csid = csid
        self.secret = secret
    
    def submit_invoice(self, invoice):
        """Submit invoice for clearance/reporting"""
        endpoint = f'{self.BASE_URL}/invoices/clearance/single'
        
        payload = {
            'invoice': base64.b64encode(invoice.xml_content.encode()).decode(),
            'invoiceHash': invoice.invoice_hash,
            'uuid': str(invoice.uuid),
        }
        
        headers = {
            'accept': 'application/json',
            'accept-language': 'en',
            'Authorization': f'Basic {self._auth_header()}',
            'Clearance-Status': '1',
            'Content-Type': 'application/json',
        }
        
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        return response.json()
```

أعطني:
1. الـ models update مع migrations
2. الـ ZATCA QR generator
3. الـ XML generator
4. الـ Digital Signature service
5. الـ API client
6. Tests شاملة
7. Sample certificate handling
```

---

## 🎯 Prompt 9.2 — Compliance Dashboard

```
في `templates/compliance/index.html`:

# المطلوب:
صفحة Dashboard خاصة بالامتثال:

## Header:
- "لوحة الامتثال"
- زر "تشغيل فحص شامل"

## ZATCA Compliance Card (كبيرة):
- نسبة الامتثال (95%) - دائرة كبيرة
- شارة "Phase 2 Compliant" خضراء
- آخر فحص: قبل ساعة
- تفاصيل:
  • ✓ QR Code: 100%
  • ✓ Digital Signature: 100%
  • ⚠️ ICV Sequence: 95% (5 مفقودة)
  • ✓ XML Validation: 100%

## Compliance Categories Grid:
4 بطاقات:
1. ZATCA SA: 95% ✓
2. FTA UAE: 88%
3. GAZT KW: 92%
4. NBR BH: 90%

## Recent Issues:
جدول المشاكل المكتشفة:
- النوع، الفاتورة، الوصف، الخطورة، Actions

## Compliance Trends:
chart يعرض نسبة الامتثال على مدى 30 يوم

## Pending Submissions:
قائمة الفواتير في انتظار الإرسال لـ ZATCA:
- زر "إرسال الكل"
- progress bar للـ batch submission

# Backend:
```python
class ComplianceDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'compliance/index.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.user.organization
        invoices = Invoice.objects.filter(organization=org)
        
        ctx.update({
            'zatca_compliance': self.calc_zatca_compliance(invoices),
            'pending_submissions': invoices.filter(zatca_status='pending').count(),
            'recent_issues': self.get_recent_issues(invoices),
            'trends': self.get_trends(invoices),
        })
        return ctx
    
    def calc_zatca_compliance(self, invoices):
        total = invoices.count() or 1
        compliant = invoices.filter(zatca_status='cleared').count()
        return {
            'rate': (compliant / total) * 100,
            'qr_code_rate': self.calc_field_rate(invoices, 'qr_code'),
            'signature_rate': self.calc_field_rate(invoices, 'cryptographic_stamp'),
            'icv_rate': self.calc_icv_rate(invoices),
            'xml_rate': self.calc_field_rate(invoices, 'xml_content'),
        }
```

أعطني template كامل + view + helpers.
```

---

## 🎯 Prompt 9.3 — VAT Validation Service

```
في مشروع Tadgeeg AI، أحتاج خدمة شاملة للتحقق من VAT:

# المطلوب:

## 1. VAT Number Validation:
```python
# apps/compliance/services/vat_validator.py
class VATValidator:
    """
    التحقق من رقم VAT للسعودية والخليج
    """
    
    def validate(self, vat_number, country='SA'):
        if country == 'SA':
            return self._validate_saudi(vat_number)
        elif country == 'AE':
            return self._validate_uae(vat_number)
        # ... باقي الدول
    
    def _validate_saudi(self, vat):
        """
        VAT السعودي: 15 رقم
        - يبدأ بـ 3
        - الرقم الأخير check digit
        - 1-9: VAT registration
        - 10-12: ال group
        - 13-15: the branch
        """
        if not vat or len(vat) != 15:
            return {'valid': False, 'error': 'VAT must be 15 digits'}
        
        if not vat.isdigit():
            return {'valid': False, 'error': 'VAT must contain only digits'}
        
        if vat[0] != '3':
            return {'valid': False, 'error': 'Saudi VAT must start with 3'}
        
        if vat[2] != '0' or vat[-2] != '3':
            return {'valid': False, 'error': 'Invalid VAT format'}
        
        # Check digit validation (simplified)
        # Real algorithm uses Luhn-like check
        return {'valid': True, 'country': 'SA', 'type': 'company'}
    
    def _validate_uae(self, vat):
        """UAE VAT: 15 digits, starts with 100"""
        if not vat or len(vat) != 15:
            return {'valid': False, 'error': 'UAE VAT must be 15 digits'}
        if not vat.startswith('100'):
            return {'valid': False, 'error': 'UAE VAT must start with 100'}
        return {'valid': True, 'country': 'AE'}
```

## 2. VAT Calculation Validation:
```python
def validate_vat_calculation(invoice):
    """
    التحقق من حساب VAT:
    - VAT = Net × 0.15 (SA)
    - Total = Net + VAT
    - tolerance: ±0.01
    """
    expected_vat = (invoice.subtotal * Decimal('0.15')).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    
    if abs(invoice.vat_amount - expected_vat) > Decimal('0.01'):
        return {
            'valid': False,
            'expected': expected_vat,
            'actual': invoice.vat_amount,
            'diff': invoice.vat_amount - expected_vat,
        }
    
    expected_total = invoice.subtotal + invoice.vat_amount
    if abs(invoice.total_amount - expected_total) > Decimal('0.01'):
        return {
            'valid': False,
            'reason': 'Total mismatch',
            'expected': expected_total,
            'actual': invoice.total_amount,
        }
    
    return {'valid': True}
```

## 3. ZATCA Lookup API (اختياري):
```python
def lookup_zatca_taxpayer(vat_number):
    """
    ZATCA provides public API to verify a taxpayer
    https://zatca.gov.sa/Services/Pages/TaxPayerLookup.aspx
    """
    response = requests.get(
        'https://api.zatca.gov.sa/taxpayer/lookup',
        params={'vatNumber': vat_number},
        timeout=10
    )
    return response.json()
```

أعطني:
1. الـ Validator class كامل
2. Tests للأرقام الصحيحة والخاطئة
3. Integration في invoice processing
4. UI button لـ "تحقق من المورد"
```

---

## ✅ Checklist

- [ ] ZATCA Phase 2 fields في الـ Invoice model
- [ ] QR Code TLV generator يعمل
- [ ] XML generator UBL 2.1 يعمل
- [ ] Digital Signature يعمل (XAdES-B-B)
- [ ] ZATCA submission API integrated
- [ ] Compliance Dashboard يعرض الإحصائيات
- [ ] VAT Validation للسعودية والخليج
- [ ] Tests في `test_zatca_compliance.py` تنجح

---

**📌 انتقل لـ `10-SETTINGS-MFA.md`**
