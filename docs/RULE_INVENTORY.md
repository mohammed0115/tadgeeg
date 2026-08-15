# Tadgeeg — الجرد الواحد للقواعد

> **المسار الثاني · الحلقة ٢** · مُنفَّذ 2026-08-08 على `main @ 3d29066`
> **الطريقة:** عدّ آلي من الشيفرة (AST + grep)، لا من الوثائق
> **الموضع المقترح:** `docs/RULE_INVENTORY.md`

---

## ١. الخلاصة: **ست** منظومات قواعد، لا أربع

الجرد السابق أحصى أربعًا. العدّ الشامل كشف اثنتين أخريين.

| # | المنظومة | المسار | العدد | صيغة الرمز | حيّ في الإنتاج؟ |
|---|---|---|---|---|---|
| 1 | المدقق القديم | `core/services/invoice_validator.py` | **34** | `INV/DUP/VAT/ANO/CTL/DOC-###` | ✅ متزامن على مسار الفواتير |
| 2 | المحرك النشط | `apps/rule_engine/rules/` | **131** | 22 بادئة مختلفة | ✅ Celery على مسار الفواتير |
| 3 | **تحليلات القيود** | `apps/audit/services/journal_analytics.py` | **8** | `JA-*` | ✅ مسار دفتر الأستاذ |
| 4 | **المحرك القديم `AuditEngine`** | `apps/audit/audit_engine.py` | **18** | `R001`–`R018` | ⚠️ **حيّ على مسار المستندات** (§4) |
| 5 | الكتالوج القانوني | `apps/rule_engine/catalog/document_rules.py` | **236** | `SI/PI/PO/BS/JE/GL…` | ⚠️ مبذور نحو عنصر نائب |
| 6 | الرقم المعلن | `README.md` | **30** | — | ❌ لا أساس له |

**المجموع الحقيقي للقواعد المنفَّذة والحيّة: 34 + 131 + 8 + 18 = 191**، موزّعة على أربع منظومات لا يعرف أي منها الأخرى.

### ١.١🔴 وأربعة مخططات ترجيح مختلفة

| المنظومة | الترجيح | مستويات الخطر |
|---|---|---|
| المدقق القديم | **لا ترجيح** — `ناجحة / 34 × 100` | 4 محسوبة · تُهمَل |
| `merge_risk_assessment` (الكاتب الفعلي) | `100 − validation_score` + قيعان 78/72/58 | **3** — لا `critical` |
| المحرك النشط `RiskEngine` | 5 مكوّنات 0.40/0.20/0.20/0.10/0.10 · عوامل 1.0/0.75/0.50/0.25/0.10 | 4 — ≥75/50/25 |
| `AuditEngine` القديم | **CRITICAL 40 · HIGH 25 · MEDIUM 10 · LOW 5** | — |
| `journal_analytics` | `base_score` لكل قاعدة: 25–50 | — |

وأوزان README (25/15/8/3) **لا تطابق أيًّا منها**.

---

## ٢. جرد قائمة الثلاثين

**المفتاح:** ✅ موجود · 🟡 جزئي · ❌ مفقود

| # | القاعدة المطلوبة | الحالة | التنفيذ الموجود | المنظومة |
|---|---|---|---|---|
| 1 | Duplicate Invoice | ✅ **×6** | `DUP-02` Duplicate Invoice · `DUP-01` Duplicate Document Number · `DUP-04` Duplicate File Hash · `AI-R08` Content Fingerprint · `DUP-001..005` · `R001` DuplicateInvoiceRule | 1·2·4 |
| 2 | Duplicate Payment | ✅ | `PMT-M04` Duplicate Payment Detected · `BNK-M06` Duplicate Bank Transactions | 2 |
| 3 | Weekend Transaction | ✅ **×3** | `BNK-M04` · `SEC-M04` Weekend/Off-Hours Submission · `JA-WEEKEND` | 2·3 |
| 4 | Round Amount | ✅ **×5** | `ANO-003` · `BNK-M03` Round-Amount Cluster · `JA-ROUND` · `R010` RoundNumberAnomalyRule · `RiskEngine.round_amount_granularity` | 1·2·3·4 |
| 5 | End-of-Period Journal Entry | ✅ | `JA-PERIODEND` · `IFRS-ACC` Accrual Cut-Off | 2·3 |
| 6 | Manual Journal Entry | ✅ | `JA-MANUAL` | 3 |
| 7 | **Negative Inventory** | ❌ | لا شيء. `AST-M02` Negative Book Value للأصول الثابتة لا للمخزون · `R012` NegativeAmountRule للمبالغ | — |
| 8 | Missing Invoice Sequence | ✅ | `INV-M06` Invoice Sequence Gap Detected | 2 |
| 9 | Benford Analysis | ✅ **×3** | `AI-R05` · `BNK-M02` · `apps/rule_engine/anomaly/detector.py` | 2 |
| 10 | Vendor Bank Account Match | 🟡 | `PMT-M07` و`BNK-M08` تتحقّقان من **صيغة** IBAN فقط. لا مطابقة مع سجل الموردين | 2 |
| 11 | Employee Bank Account Match | 🟡 | `PAY-M01` Ghost Employee · `CDR-03` Payroll–Bank Reconciliation. لا مطابقة حساب موظف بحساب مورد | 2 |
| 12 | **Unusual Revenue Growth** | ❌ | لا شيء. `apps/analytics/risk_forecast_service.py` أساس محتمل | — |
| 13 | Revenue Cut-off | ✅ | `IFRS-15` Revenue Recognition Timing · `IFRS-2` Expense Matching/Cut-off · `GL-CUTOFF` | 2 |
| 14 | Large Journal Entry | ✅ | `JA-HIGHVALUE` (عتبة مبنيّة على الأهمية النسبية) | 3 |
| 15 | Dormant Account Activity | ✅ | `JA-DORMANT` | 3 |
| 16 | Missing Supporting Document | ✅ | `EXP-M01` Missing Receipt · `SOCPA-500` Sufficient Audit Evidence · `JA-DESC` | 2·3 |
| 17 | Payment Before Approval | ✅ | `PMT-M05` Payment Missing Approval · `PO-M08` Retroactive PO | 2 |
| 18 | Three-Way Match Failure | ✅ **×3** | `CDR-02` · `ThreeWayMatchService` (974 سطرًا) · `R007` ThreeWayMatchRule | 2·4 |
| 19 | **Credit Note Spike** | ❌ | لا شيء. صفر ذكر لـ`credit_note` في المستودع | — |
| 20 | Suspicious Tax Rate | ✅ | `VAT-01` VAT Rate 15% · `R009` VATRateValidityRule (0/5/15) · `TAX-M01` | 1·2·4 |
| 21 | Cash Balance Anomaly | 🟡 | `BNK-M01` Balance Reconciliation موجود. لا كشف شذوذ في الرصيد نفسه | 2 |
| 22 | **Aging Outlier** | ❌ | لا شيء. `PMT-M09` Late Payment أقرب موجود لكنه ليس تحليل أعمار | — |
| 23 | Related Party Indicator | 🟡 | `risk_decomposition.py::related_party_density` — **مُدخَل تقييم يدوي (0–25)** لا قاعدة كشف | 3 |
| 24 | Unusual User Activity | 🟡 | `SEC-M04` · `BNK-M05` Late-Night · `RiskEngine.off_hours_start/end` + `high_frequency_threshold` | 2 |
| 25 | Approval Override | ✅ **×4** | `CTL-004` Post-Approval Modification · `CTL-04` No Edit After Approval · `SEC-M05` Document Edited After Approval · `SEC-M01` Self-Approval | 1·2 |
| 26 | Threshold Splitting | ✅ **×4** | `PO-M04` PO Splitting · `EXP-M05` Expense Split · `BNK-M07` Structuring (AML) · `RiskEngine.just_below_threshold_pct` | 2 |
| 27 | Reversed Entry Pattern | ❌ | لا شيء. `revers` في `anomaly_engine.py` هو `sorted(reverse=True)` لا كشف قيود عكسية | — |
| 28 | Late Adjusting Entry | 🟡 | `JA-PERIODEND` و`EXP-M04` Late Submission يغطّيان جزءًا. لا قاعدة لقيود التسوية المتأخرة | 2·3 |
| 29 | Trial Balance Imbalance | ✅ | `IFRS-CON` Σ debits = Σ credits · `apps/audit/general_ledger_models.py` (جداول تمهيد) | 2 |
| 30 | High-Risk Account Movement | ✅ | `JA-SENSITIVE` Sensitive Account Usage | 3 |

### ٢.١ الحصيلة

| الحالة | العدد | البنود |
|---|---|---|
| ✅ موجود | **19** | 1·2·3·4·5·6·8·9·13·14·15·16·17·18·20·25·26·29·30 |
| 🟡 جزئي | **6** | 10·11·21·23·24·28 |
| ❌ مفقود | **5** | 7 Negative Inventory · 12 Unusual Revenue Growth · 19 Credit Note Spike · 22 Aging Outlier · 27 Reversed Entry Pattern |

**63% مبنيّ بالكامل، و20% مبنيّ جزئيًا، و17% فقط مفقود.** فمشروع «بناء ثلاثين قاعدة» هو في الحقيقة مشروع **توفيق تسعة عشر تنفيذًا مكرّرًا** وإكمال خمسة.

### ٢.٢ 🔴 التكرار هو المشكلة لا النقص

| القاعدة | تنفيذات | الخطر |
|---|---|---|
| Round Amount | **5** في 4 منظومات | المستند الواحد قد يُخصم عليه خمس مرات |
| Duplicate Invoice | **6** | كما أعلاه |
| Approval Override | **4** | `CTL-004` و`CTL-04` رمزان مستقلان لمفهوم واحد |
| Threshold Splitting | **4** | — |
| Three-Way Match | **3** | — |
| Weekend Transaction | **3** | — |
| Benford | **3** | — |

**السؤال المهني المفتوح:** إذا فشل مستند في `JA-ROUND` و`ANO-003` و`BNK-M03` و`R010` — هل هذه أربع ملاحظات أم ملاحظة واحدة؟ الجواب اليوم يعتمد على أي محرّك عمل، ولا يوجد توفيق.

---

## ٣. تصادمات الهوية المؤكَّدة

```
CTL-004  Post-Approval Modification      ┐ رمزان مستقلان
CTL-04   No Edit After Approval          ┘ لمفهوم واحد

CTL-005  Segregation of Duties Violation ┐
CTL-05   Has Approver                    ┘ مفهومان مختلفان برمز متشابه ← الأخطر

CTL-006  Incomplete Audit Trail          ┐
CTL-06   Has Audit Trail                 ┘ نفس المفهوم، منطق معاكس

ANO-01   Amount Unusually High           ┐
ANO-002  First-Time Vendor               ┘ صيغتان متجاورتان
ANO-003  Round-Number Amount

IFRS-1 / IFRS-2 / IFRS-15               صيغتان بعدد خانات مختلف
```

> **`CTL-005` / `CTL-05` هو أخطرها**: مفهومان مهنيان مختلفان تمامًا (فصل المهام مقابل وجود معتمِد) تحت رمز يختلف بصفر واحد. أي تقرير أو تصفية أو تسمية ML مبنيّة على `rule_code` تخلطهما.

---

## ٤. 🔴 اكتشاف جديد: المحرك القديم حيّ على مسار المستندات

`apps/audit/audit_engine.py` يوثّق نفسه بأنه مخرج طوارئ:

> «This function is no longer called from production upload paths when `settings.USE_NEW_RULE_ENGINE` is True (the default).»

**وهذا صحيح لمسار الفواتير فقط.** `apps/invoices/services/processor.py:411` يفحص الراية فعلًا.

**لكن `core/services/pipeline.py:203, 222` ينشئ `AuditEngine` مباشرة بلا أي فحص للراية:**

```
grep -c "USE_NEW_RULE_ENGINE" core/services/pipeline.py   →  0
```

ويُستدعى `run_full_pipeline` من:
- `apps/documents/views.py:263`
- `apps/documents/tasks.py:47`

**فالمحرك الذي «لم يُعد يُستدعى» يعمل على كل مستند غير الفواتير**، بأوزانه الخاصة (CRITICAL 40 · HIGH 25 · MEDIUM 10 · LOW 5) و18 قاعدته. و«خطة الإزالة» المكتوبة في الملف (احذفه بعد دورتَي إصدار نظيفتين) لا يمكن تنفيذها لأن الحذف سيكسر مسار المستندات.

**هذا نفس نمط `apps/reporting`** المُصلَح في `124c9df` — كود يُقرأ كأنه متقاعد وهو يعمل.

---

## ٥. الفراغات الخمسة — مواصفة أوّلية

| البند | البيانات المتوفّرة | الأساس المقترح | ملاحظة مهنية |
|---|---|---|---|
| 7 Negative Inventory | لا جدول مخزون · `Dataset/07_Fixed_Assets` للأصول | يحتاج نموذج مخزون أولًا | **ليس فراغ قاعدة — فراغ نموذج بيانات** |
| 12 Unusual Revenue Growth | `apps/analytics/risk_forecast_service.py` (246 سطرًا) | تحليل اتجاه على الإيرادات المُرحَّلة | ISA 520 — إجراءات تحليلية |
| 19 Credit Note Spike | لا نوع مستند «إشعار دائن» | يحتاج `credit_note` في `SupportedDocumentType` | فراغ نموذج بيانات أيضًا |
| 22 Aging Outlier | `PMT-M09` + جداول دفتر الأستاذ | تحليل أعمار الذمم/الدائنين | ISA 540 — التقديرات |
| 27 Reversed Entry Pattern | `journal_analytics` عنده القيود والسياق | مطابقة قيد بقيد معاكس داخل نافذة | ISA 240 — أقوى مؤشر احتيال في القائمة |

> **البند 27 هو أعلى قيمة مهنية من الخمسة**، وأرخصها: السياق والقيود موجودة في `journal_analytics`، والنمط (سجل + دوال نقية) جاهز. يُضاف كـ`JA-REVERSAL` في نفس السجل.
> **والبندان 7 و19 ليسا قواعد ناقصة بل نماذج بيانات ناقصة** — لا تُدرجهما في دفعة القواعد.

---

## ٦. الحلقات المتبقية في المسار الثاني

| الحلقة | الحالة | العائق |
|---|---|---|
| ١ معايرة المقياس | 🟡 جزئي — `C1ب`/`C2ب` قيست · عدّ الاختبارات يحتاج تشغيل | بيئتك |
| **٢ الجرد** | ✅ **مكتمل — هذا الملف** | — |
| ٣ المرجع الذهبي | ⬜ الأداة تُكتب · التشغيل يحتاج قاعدة بيانات إنتاج | بيئتك |
| ٤ قرار المحرك | ⬜ الأدلة جاهزة (§١·§٤) · **القرار قرارك** | قرار مهني |
| ٥ وثائق القواعد | ⬜ تعتمد على ٤ | ٤ |
| ٦ التفكيك | ⬜ تعتمد على ٣ و٤ | ٣·٤ |
| ٧ الفراغات | ⬜ تعتمد على ٤ · والبندان 7 و19 يحتاجان نموذج بيانات | ٤ |

---

## ٧. قرار الحلقة ٤ — الأدلة والخيارات

**ما نعرفه الآن بالأرقام:**

- أربع منظومات حيّة · 191 قاعدة منفَّذة · أربعة مخططات ترجيح
- المقاييس **معاكسة** (المرتفع جيّد في واحدة، سيّئ في أخرى)
- الفاتورة لا تستطيع أن تكون `critical`
- 19 من 30 قاعدة مكرّرة، بعضها 5–6 مرات
- ثلاثة تصادمات رموز مؤكَّدة، أحدها بين مفهومين مختلفين

**الخيارات:**

| # | الخيار | الجدوى | الأثر |
|---|---|---|---|
| **أ** | تقاعد `AuditEngine` (18) بربط `pipeline.py` بالراية أو بالمحرك النشط | **الأعلى — ابدأ هنا** | يُسقط منظومة كاملة وأحد مخططات الترجيح · تغيير في موضع واحد |
| ب | تقاعد المدقق القديم (34) بعد تغطية الـ34 في المحرك | متوسطة | يزيل المقياس المعاكس · يتطلب مصفوفة تغطية كاملة |
| ج | إبقاء `journal_analytics` (8) منفصلًا | **موصى به** | نطاق مختلف (دفتر أستاذ لا مستندات) · نمطه هو النمط المستهدف |
| د | حسم `CTL-004/CTL-04` و`CTL-005/CTL-05` و`CTL-006/CTL-06` | **إلزامي قبل أي ML** | مفتاح التسمية معطوب بدونه |

**التسلسل الموصى به:** أ → د → ب. والبند **أ** هو الأرخص والأكبر أثرًا: تغيير واحد في `core/services/pipeline.py` يُسقط منظومة كاملة من الأربع.

---

## ٨. الأوامر التي تعيد توليد هذا الجرد

```bash
# منظومة 1
grep -oE '"(INV|DUP|VAT|ANO|CTL|DOC)-[0-9]{3}"' core/services/invoice_validator.py | sort -u | wc -l

# منظومة 2
grep -rhoE '^\s+rule_code\s*=\s*"[^"]+"' apps/rule_engine/rules/ \
  | grep -oE '"[^"]+"' | tr -d '"' | sort -u | wc -l

# منظومة 3
grep -c 'RuleSpec("' apps/audit/services/journal_analytics.py

# منظومة 4
sed -n '/^REGISTERED_RULES/,/^\]/p' apps/audit/audit_engine.py | grep -c "Rule,"

# منظومة 5
grep -c "^    _r(" apps/rule_engine/catalog/document_rules.py

# المحرك القديم حيّ على مسار المستندات؟
grep -c "USE_NEW_RULE_ENGINE" core/services/pipeline.py     # 0 = بلا حماية
grep -n "AuditEngine" core/services/pipeline.py
```
