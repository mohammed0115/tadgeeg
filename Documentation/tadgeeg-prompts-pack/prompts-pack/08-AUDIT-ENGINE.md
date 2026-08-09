# 🔍 08 — محرك التدقيق و30 قاعدة (Audit Engine)

> Prompts لتطوير `apps/audit_engine/` و `apps/rule_engine/` و30 قاعدة تدقيق

---

## 🎯 Prompt 8.1 — فهم الـ 30 Audit Rules الموجودة

```
في مشروع Tadgeeg AI، الملف `Docs/SYSTEM_AUDIT_RULES_VALIDATION.json` يحتوي على 
30 قاعدة تدقيق رسمية. الـ apps/invoices/ يطبّقها.

المطلوب: قم بمراجعة شاملة للقواعد الـ 30 وأعد تنظيمها في 6 فئات:

# الفئات:

## 1. سلامة الترويسة (Header Integrity) - 5 قواعد:
- R01: وجود رقم الفاتورة
- R02: وجود تاريخ الفاتورة
- R03: وجود اسم المورد
- R04: وجود VAT Registration Number
- R05: وجود اسم العميل

## 2. التحقق المالي (Financial Validation) - 6 قواعد:
- R06: المبلغ الصافي > 0
- R07: VAT = Net × 0.15 (مع tolerance ±0.01)
- R08: الإجمالي = الصافي + VAT
- R09: العملة معرّفة (SAR افتراضياً)
- R10: لا توجد أرقام سالبة
- R11: التطابق مع الـ line items

## 3. كشف التكرار (Duplicate Detection) - 4 قواعد:
- R12: عدم وجود فاتورة بنفس رقم وتاريخ ومورد
- R13: SHA-256 hash unique
- R14: لا يوجد فواتير مماثلة (fuzzy match)
- R15: invoice number sequence check

## 4. الامتثال ZATCA (Compliance) - 7 قواعد:
- R16: QR Code موجود (Phase 2)
- R17: Digital Signature صحيح
- R18: UUID موجود
- R19: VAT format صحيح (15 رقم)
- R20: ICV (Invoice Counter Value) متسلسل
- R21: PIH (Previous Invoice Hash) متطابق
- R22: ZATCA-compatible XML structure

## 5. كشف الشذوذ (Anomaly Detection) - 4 قواعد:
- R23: المبلغ ضمن النطاق الطبيعي للمورد
- R24: التاريخ ليس مستقبلي ولا قديم جداً
- R25: Benford's Law check للأرقام
- R26: عدم وجود أنماط مشبوهة

## 6. جودة المستند (Document Quality) - 4 قواعد:
- R27: OCR confidence > 80%
- R28: حدة الصورة كافية
- R29: لا يوجد scratching/tampering
- R30: جميع الحقول مقروءة

# المطلوب:
1. أنشئ ملف `apps/audit_engine/rules.py` فيه class لكل قاعدة:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    severity: str  # 'low', 'medium', 'high', 'critical'
    message: str
    details: dict = None

class BaseRule(ABC):
    rule_id: str
    name: str
    category: str
    severity: str
    
    @abstractmethod
    def check(self, invoice) -> RuleResult:
        pass

class R01_InvoiceNumberPresent(BaseRule):
    rule_id = 'R01'
    name = 'رقم الفاتورة موجود'
    category = 'header_integrity'
    severity = 'critical'
    
    def check(self, invoice):
        if not invoice.invoice_number or len(invoice.invoice_number.strip()) == 0:
            return RuleResult(
                rule_id=self.rule_id,
                passed=False,
                severity=self.severity,
                message='رقم الفاتورة مفقود أو فارغ'
            )
        return RuleResult(self.rule_id, True, self.severity, 'OK')

# ... باقي الـ 30 قاعدة
```

2. ملف `apps/audit_engine/runner.py`:
```python
class AuditRunner:
    def __init__(self):
        self.rules = self._load_rules()
    
    def run_all(self, invoice):
        results = []
        for rule in self.rules:
            try:
                result = rule.check(invoice)
                results.append(result)
            except Exception as e:
                results.append(RuleResult(
                    rule.rule_id, False, 'critical',
                    f'Rule failed with error: {e}'
                ))
        
        # Save results
        for r in results:
            AuditResult.objects.create(
                invoice=invoice,
                rule_id=r.rule_id,
                passed=r.passed,
                severity=r.severity,
                message=r.message,
                details=r.details or {}
            )
        
        # Calculate score
        invoice.audit_score = self.calculate_score(results)
        invoice.risk_level = self.determine_risk_level(invoice.audit_score)
        invoice.save()
        
        return results
    
    def calculate_score(self, results):
        weights = {
            'critical': 10,
            'high': 5,
            'medium': 2,
            'low': 1,
        }
        total = sum(weights.values()) * 30  # max possible
        deducted = sum(
            weights[r.severity] for r in results if not r.passed
        )
        return max(0, 100 - (deducted / total * 100))
    
    def determine_risk_level(self, score):
        if score >= 90: return 'low'
        if score >= 75: return 'medium'
        if score >= 60: return 'high'
        return 'critical'
```

أعطني الـ 30 قاعدة كاملة + الـ runner + integration with invoice processing.
```

---

## 🎯 Prompt 8.2 — إضافة قاعدة جديدة للمحرك

```
في مشروع Tadgeeg AI، أريد إضافة قاعدة جديدة للـ audit engine:

# المطلوب:
أنشئ قاعدة جديدة "R31: Vendor Blacklist Check" تتحقق:
- المورد ليس في قائمة الموردين المحظورين
- المورد ليس في قائمة UN/OFAC للعقوبات

# الخطوات:

## 1. أنشئ Model للقائمة السوداء:
```python
# apps/compliance/models.py
class BlacklistedVendor(SoftDeleteModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        null=True, blank=True  # null = global blacklist
    )
    vendor_name = models.CharField(max_length=200)
    vendor_vat_id = models.CharField(max_length=15, blank=True)
    reason = models.TextField()
    source = models.CharField(max_length=50)  # 'internal', 'ofac', 'un'
    blocked_until = models.DateField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['vendor_vat_id']),
            models.Index(fields=['vendor_name']),
        ]
```

## 2. أنشئ القاعدة:
```python
# apps/audit_engine/rules.py
class R31_VendorBlacklistCheck(BaseRule):
    rule_id = 'R31'
    name = 'فحص القائمة السوداء للموردين'
    category = 'compliance'
    severity = 'critical'
    
    def check(self, invoice):
        # تحقق من القائمة السوداء العامة + الخاصة بالمنظمة
        blacklisted = BlacklistedVendor.objects.filter(
            Q(organization=invoice.organization) |
            Q(organization__isnull=True),
        ).filter(
            Q(vendor_vat_id=invoice.vendor_vat_id) |
            Q(vendor_name__iexact=invoice.vendor_name)
        ).first()
        
        if blacklisted:
            return RuleResult(
                rule_id=self.rule_id,
                passed=False,
                severity='critical',
                message=f'المورد محظور: {blacklisted.reason}',
                details={
                    'source': blacklisted.source,
                    'blocked_until': str(blacklisted.blocked_until) if blacklisted.blocked_until else None,
                }
            )
        return RuleResult(self.rule_id, True, self.severity, 'OK')
```

## 3. سجّل القاعدة في الـ runner:
```python
# apps/audit_engine/runner.py
def _load_rules(self):
    return [
        R01_InvoiceNumberPresent(),
        # ... باقي القواعد
        R31_VendorBlacklistCheck(),  # جديد
    ]
```

## 4. اكتب اختبار:
```python
# tests/test_audit_rules.py
@pytest.mark.django_db
def test_R31_vendor_blacklist():
    org = OrganizationFactory()
    BlacklistedVendor.objects.create(
        organization=org,
        vendor_name='Bad Corp',
        reason='Fraud'
    )
    invoice = InvoiceFactory(
        organization=org,
        vendor_name='Bad Corp'
    )
    
    rule = R31_VendorBlacklistCheck()
    result = rule.check(invoice)
    
    assert result.passed is False
    assert result.severity == 'critical'
    assert 'محظور' in result.message
```

## 5. Migration:
```bash
python manage.py makemigrations compliance
python manage.py migrate
```

أعطني:
1. الـ Model
2. الـ Rule class
3. الـ Migration
4. الـ Tests
5. UI لإدارة القائمة السوداء (`templates/compliance/blacklist.html`)
```

---

## 🎯 Prompt 8.3 — عرض نتائج التدقيق في الـ UI

```
في `templates/invoices/detail.html`، قسم "30 Audit Rules":

# المطلوب:
عرض جميل ومفيد لنتائج التدقيق:

## Summary Bar:
- نجحت: 27 / 30 (شريط أخضر)
- فشلت: 3 / 30 (شريط أحمر)
- نسبة النجاح: 90%

## Categories:
شبكة من البطاقات لكل فئة من الـ 6:
- اسم الفئة + عدد القواعد
- نسبة النجاح + progress bar
- لون: أخضر إذا 100%، أصفر < 100%، أحمر إذا حرج

## Detailed List:
لكل قاعدة:
- ✓ أو ✗ أو ⚠️
- رقم القاعدة (R01)
- الاسم
- الحالة (passed/failed)
- خطورة (severity)
- زر "تفاصيل" → modal

## Modal "تفاصيل القاعدة":
- اسم القاعدة كامل + الوصف
- ما هي القاعدة؟
- لماذا هذه القاعدة مهمة؟
- ما الذي وجده النظام؟
- التوصية لإصلاح المشكلة
- إذا فشلت: زر "إعادة فحص" أو "تجاوز يدوياً"

## Filter Bar:
أزرار filter:
- الكل
- نجحت
- فشلت
- حرجة فقط
- حسب الفئة

# Component HTML:
```html
<div x-data="auditRules({{ audit_results_json|safe }})" class="audit-rules-section">
  <!-- Summary -->
  <div class="summary">
    <div class="passed">{{ passed_count }} نجحت</div>
    <div class="failed">{{ failed_count }} فشلت</div>
  </div>
  
  <!-- Categories Grid -->
  <div class="categories">
    <template x-for="cat in categories" :key="cat.id">
      <div class="category-card">
        <h3 x-text="cat.name"></h3>
        <div class="progress">
          <div :style="`width: ${cat.passRate}%`"></div>
        </div>
        <span x-text="`${cat.passed} / ${cat.total}`"></span>
      </div>
    </template>
  </div>
  
  <!-- Filter -->
  <div class="filters">
    <button @click="filter = 'all'" :class="{ active: filter === 'all' }">الكل</button>
    <button @click="filter = 'passed'">نجحت</button>
    <button @click="filter = 'failed'">فشلت</button>
    <button @click="filter = 'critical'">حرجة</button>
  </div>
  
  <!-- Rules List -->
  <div class="rules-list">
    <template x-for="rule in filteredRules" :key="rule.rule_id">
      <div class="rule-item" :class="rule.passed ? 'passed' : 'failed'">
        <div class="icon" x-html="rule.passed ? '✓' : '✗'"></div>
        <div class="content">
          <span class="rule-id" x-text="rule.rule_id"></span>
          <span class="rule-name" x-text="rule.name"></span>
        </div>
        <span class="severity" x-text="rule.severity"></span>
        <button @click="showDetails(rule)">تفاصيل</button>
      </div>
    </template>
  </div>
</div>
```

أعطني الـ component HTML + CSS + Alpine.js + integration مع invoice/detail.html.
```

---

## ✅ Checklist

- [ ] الـ 30 قاعدة محدّدة في `apps/audit_engine/rules.py`
- [ ] الـ runner يشغّل القواعد ويحسب الـ score
- [ ] إضافة قواعد جديدة سهلة (extensible)
- [ ] الـ UI يعرض النتائج بوضوح
- [ ] Modal تفاصيل القاعدة يعمل
- [ ] Tests في `test_rule_engine.py` تنجح
- [ ] Tests في `test_invoice_and_rules.py` تنجح

---

**📌 انتقل لـ `09-COMPLIANCE-ZATCA.md`**
