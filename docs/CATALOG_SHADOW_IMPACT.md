# أثر وصل كتالوج القواعد المحجوب — قياس

> **قياس خالص · صفر تعديل شيفرة · لا اقتراح وصل ولا حذف.**
> القرار لِـCTO بعد الأرقام.
> قِيس على جهاز تطوير، 2026‑08‑18، على الفرع `fix/executive-report-scope`.

---

## ١. هل عمل الكتالوج يومًا؟ — نعم، عشرين يومًا

```
apps/rule_engine/catalog.py          أُنشئ  2026-04-12   9a94bd6  "fixed 26 bugs in the system"
apps/rule_engine/catalog/__init__.py أُنشئ  2026-05-02   decd8e1  "feat: 20-document-type catalog…"
```

- `resolve_rule_catalog_metadata` أُضيفت في **نفس commit** الملف — `9a94bd6`.
- مستدعوها ظهروا في **نفس الـcommit** أيضًا.
- `catalog/__init__.py` حجمه **صفر بايت منذ يوم إنشائه** (مؤكَّد بـ`git show decd8e1:…`).

⇒ **الكتالوج كان يعمل من 2026‑04‑12 إلى 2026‑05‑02، ثم أسكته ملف فارغ.**

🔴 **أثر رجعي:** أحكام صدرت في تلك النافذة استعملت الكتالوج؛ وما بعدها لم يستعمله.
**هذا يُبلَّغ للمدققين — لا يُصلَح صامتًا.**

---

## ٢. ماذا يفعل الحلّ فعلًا

`resolve_rule_catalog_metadata(rule_identifier, *, rule_name, rule_type, severity, supported_doc_types)`

| السؤال | الجواب |
|---|---|
| المُدخَل | الرمز الخام — `self.legacy_rule_code or self.rule_code` |
| **عند عدم التطابق** | 🔴 **لا يرفع استثناءً ولا يعيد None — بل يُصنّع مدخلًا جديدًا ويُسجّله** |
| الحقول المستهلَكة (٤) | `rule_code` · `is_blocking` — ولا شيء غيرهما في المواضع السبعة |
| اعتماد خارجي | لا شيء. لا جدول ولا إعداد ولا بيانات — استنتاج نصّي بحت |

**سلوكه عند عدم التطابق (٥)** هو المفتاح، وهو ثالث الاحتمالات لا أوّلها:

```python
if resolved_code in RULE_CATALOG:
    return RULE_CATALOG[resolved_code]        # 12 مدخلة مسجَّلة فقط
category = _infer_category(identifier, rule_name, rule_type)   # استنتاج من كلمات مفتاحية
entry = RuleCatalogEntry(..., is_blocking=_infer_blocking(category, severity), ...)
return _register(entry)                        # ويُسجَّل ويصير دائمًا
```

و`_infer_blocking`: `critical` ⇒ منع · `high` + إحدى خمس فئات ⇒ منع · وإلا لا.

⇒ **الأثر لا يقتصر على الاثنتي عشرة المسجَّلة.** كل قاعدة غير مطابِقة تحصل على
رمز مُصنَّع و`is_blocking` مستنتَج.

**واتجاه الأثر يختلف بين المستهلكين:**

```python
rule_engine/rules/base.py:79    self.is_blocking = bool(self.is_blocking or entry.is_blocking)   # أُحادي
audit/rules/base_rule.py:68     self.is_blocking = bool(self.is_blocking or entry.is_blocking)   # أُحادي
audit/rules/base_rule.py:134    cls.is_blocking  = entry.is_blocking                             # إسناد مباشر
```

المسار الصنفي (`134`) وحده يستطيع قلب `True→False` — **وهو خامل**: `rule_id = "..."`
لا يوجد في المستودع كلّه (صفر موضع)، و`__init_subclass__` يخرج مبكرًا بلا معرّف.

---

## ٣. القياس — 236 قاعدة حيّة

استُورد `catalog.py` بمسار صريح عبر `importlib`. **لم يُنشأ `__init__.py` ولم يُعدَّل ملف.**

| # | القياس | العدد |
|---|---|---|
| ٦ | `catalog_code` يختلف عن الرمز اليوم | 🔴 **236 / 236** — كلّها |
| ٧ | **تبدأ بمنع الاعتماد** (`False→True`) | 🔴 **115** |
| ٨ | تتوقّف عن المنع (`True→False`) | **0** — والمسار الأُحادي لا يسمح بها بنيويًّا |
| ٩ | ترفع استثناءً | **0** |

**كل الـ115 خطورتها `high`.** ولا واحدة `critical` — لأن الحرجة تمنع اليوم بالفعل.

**والبند ٦ لا يقلّ خطورة عن ٧:** كل رمز يُستبدل برمز مُصنَّع (`SI-001` ⇒ `completeness-###`)،
فأي مرجع مخزَّن أو مصدَّر أو موثَّق بالرمز القديم ينفصل عن قاعدته.

| نوع المستند | قواعد تبدأ بالمنع |
|---|---|
| `supplier_statement` | 9 |
| `customer_statement` | 9 |
| `bank_statement` | 8 |
| `purchase_order` | 7 |
| `contract` | 7 |
| `tax_vat_document` | 7 |
| `purchase_invoice` | 6 |
| `sales_order` | 6 |
| `cash_voucher` | 6 |
| `general_ledger` | 6 |
| `payroll` | 6 |
| `quotation` | 5 |
| `grn` | 5 |
| `payment_voucher` | 5 |
| `receipt_voucher` | 5 |
| `expense_report` | 5 |
| `proforma_invoice` | 4 |
| `ledger` | 4 |
| `journal_entry` | 3 |
| `sales_invoice` | 2 |
| **المجموع** | **115** |

| الفئة | عدد |
|---|---|
| `completeness` | 31 |
| `matching` | 28 |
| `date_validation` | 15 |
| `approval_control` | 9 |
| `duplicate_detection` | 8 |
| `amount_validation` | 8 |
| `vat_validation` | 4 |
| `policy_compliance` | 3 |
| `bank_reconciliation` | 3 |
| `anomaly_detection` | 3 |
| `contract_compliance` | 2 |
| `vendor_customer_risk` | 1 |

<details><summary>القائمة الكاملة — 115 قاعدة</summary>

| الرمز | الخطورة | الفئة | المستند | الاسم |
|---|---|---|---|---|
| `BS-001` | high | completeness | bank_statement | رقم الحساب البنكي مطلوب |
| `BS-003` | high | date_validation | bank_statement | تاريخ العملية مطلوب |
| `BS-005` | high | amount_validation | bank_statement | يجب وجود مدين أو دائن وليس كلاهما فارغ |
| `BS-008` | high | matching | bank_statement | كشف دفعات بدون فاتورة |
| `BS-009` | high | matching | bank_statement | كشف قبض بدون فاتورة |
| `BS-010` | high | matching | bank_statement | مطابقة الدفعات مع Payment Voucher |
| `BS-011` | high | matching | bank_statement | مطابقة المقبوضات مع Receipt Voucher |
| `BS-014` | high | anomaly_detection | bank_statement | كشف تغير غير طبيعي في الرصيد |
| `CS-001` | high | completeness | customer_statement | اسم العميل مطلوب |
| `CS-002` | high | completeness | customer_statement | رقم العميل أو الرقم الضريبي مطلوب |
| `CS-003` | high | completeness | customer_statement | الفترة مطلوبة |
| `CS-004` | high | completeness | customer_statement | الرصيد الافتتاحي مطلوب |
| `CS-007` | high | matching | customer_statement | مطابقة فواتير العميل مع النظام |
| `CS-008` | high | matching | customer_statement | مطابقة المقبوضات مع Receipt Vouchers |
| `CS-009` | high | matching | customer_statement | فواتير في كشف العميل غير موجودة في النظام |
| `CS-010` | high | matching | customer_statement | مقبوضات في النظام غير موجودة في كشف العميل |
| `CS-011` | high | amount_validation | customer_statement | كشف فروقات الرصيد |
| `CTR-003` | high | date_validation | contract | تاريخ البداية مطلوب |
| `CTR-004` | high | date_validation | contract | تاريخ النهاية مطلوب |
| `CTR-005` | high | completeness | contract | قيمة العقد مطلوبة |
| `CTR-007` | high | contract_compliance | contract | العقد المنتهي لا يرتبط بفواتير جديدة |
| `CTR-009` | high | contract_compliance | contract | إجمالي الفواتير لا يتجاوز قيمة العقد |
| `CTR-012` | high | approval_control | contract | تعديل قيمة العقد معتمد |
| `CTR-013` | high | matching | contract | الطرف المقابل يطابق الفاتورة |
| `CV-002` | high | completeness | cash_voucher | نوع الحركة مطلوب: قبض أو صرف |
| `CV-004` | high | date_validation | cash_voucher | التاريخ مطلوب |
| `CV-005` | high | completeness | cash_voucher | سبب الحركة مطلوب |
| `CV-006` | high | completeness | cash_voucher | المرفق أو الإيصال مطلوب |
| `CV-007` | high | approval_control | cash_voucher | الحركة النقدية فوق الحد تحتاج موافقة |
| `CV-008` | high | duplicate_detection | cash_voucher | لا توجد حركة نقدية مكررة |
| `ER-005` | high | date_validation | expense_report | التاريخ مطلوب |
| `ER-007` | high | completeness | expense_report | الإيصال أو المرفق مطلوب |
| `ER-008` | high | policy_compliance | expense_report | ضمن سياسة الشركة |
| `ER-009` | high | approval_control | expense_report | فوق الحد يحتاج موافقة |
| `ER-010` | high | duplicate_detection | expense_report | مصروف مكرر |
| `GL-001` | high | completeness | general_ledger | الحساب مطلوب |
| `GL-002` | high | completeness | general_ledger | الرصيد الافتتاحي مطلوب |
| `GL-005` | high | matching | general_ledger | كل حركة مرتبطة بقيد يومية |
| `GL-006` | high | matching | general_ledger | كشف حركات بدون قيد يومية |
| `GL-007` | high | anomaly_detection | general_ledger | حسابات ذات أرصدة غير طبيعية |
| `GL-008` | high | amount_validation | general_ledger | كشف فروقات Rollforward |
| `GRN-002` | high | matching | grn | يجب أن يرتبط بأمر شراء |
| `GRN-003` | high | date_validation | grn | تاريخ الاستلام مطلوب |
| `GRN-005` | high | completeness | grn | البنود المستلمة مطلوبة |
| `GRN-006` | high | matching | grn | الكمية المستلمة لا تتجاوز الكمية المطلوبة في PO |
| `GRN-008` | high | duplicate_detection | grn | لا توجد GRN مكررة |
| `JE-002` | high | date_validation | journal_entry | تاريخ القيد مطلوب |
| `JE-008` | high | duplicate_detection | journal_entry | لا توجد قيود مكررة |
| `JE-010` | high | completeness | journal_entry | الحسابات موجودة في دليل الحسابات |
| `LDG-001` | high | completeness | ledger | رقم الحساب مطلوب |
| `LDG-003` | high | completeness | ledger | الرصيد الافتتاحي مطلوب |
| `LDG-009` | high | matching | ledger | تحقق من ارتباط الحركات بقيود يومية |
| `LDG-010` | high | amount_validation | ledger | لا توجد أرصدة سالبة غير مبررة |
| `PF-003` | high | date_validation | proforma_invoice | التاريخ مطلوب |
| `PF-004` | high | date_validation | proforma_invoice | تاريخ الصلاحية مطلوب |
| `PF-005` | high | policy_compliance | proforma_invoice | لا يتم تسجيلها كإيراد فعلي |
| `PF-007` | high | amount_validation | proforma_invoice | الإجمالي والضريبة محسوبان بشكل صحيح |
| `PI-004` | high | vat_validation | purchase_invoice | الرقم الضريبي للمورد مطلوب |
| `PI-008` | high | duplicate_detection | purchase_invoice | فاتورة مكرّرة بنفس المبلغ والتاريخ والمورد |
| `PI-009` | high | matching | purchase_invoice | الفاتورة مرتبطة بأمر شراء |
| `PI-010` | high | matching | purchase_invoice | مبلغ الفاتورة لا يتجاوز أمر الشراء |
| `PI-011` | high | matching | purchase_invoice | الفاتورة مرتبطة بـ GRN عند وجود بضائع مستلمة |
| `PI-012` | high | approval_control | purchase_invoice | لا يتم الدفع بدون موافقة |
| `PO-003` | high | date_validation | purchase_order | تاريخ أمر الشراء مطلوب |
| `PO-004` | high | completeness | purchase_order | أمر الشراء يجب أن يحتوي على بنود |
| `PO-005` | high | amount_validation | purchase_order | الكميات والأسعار أكبر من صفر |
| `PO-006` | high | approval_control | purchase_order | أمر الشراء يحتاج اعتماداً حسب القيمة |
| `PO-007` | high | approval_control | purchase_order | ضمن الميزانية المعتمدة |
| `PO-009` | high | matching | purchase_order | لا يسمح بإصدار فاتورة على PO مغلق |
| `PO-010` | high | matching | purchase_order | الكمية المستلمة لا تتجاوز الكمية المطلوبة |
| `PR-002` | high | completeness | payroll | فترة الرواتب مطلوبة |
| `PR-003` | high | completeness | payroll | كل موظف له رقم وظيفي |
| `PR-004` | high | completeness | payroll | الراتب الأساسي مطلوب |
| `PR-008` | high | anomaly_detection | payroll | تغير غير طبيعي في الراتب |
| `PR-011` | high | matching | payroll | إجمالي الرواتب يطابق القيد المحاسبي |
| `PR-012` | high | bank_reconciliation | payroll | الدفع البنكي يطابق صافي الرواتب |
| `PV-004` | high | completeness | payment_voucher | طريقة الدفع مطلوبة |
| `PV-005` | high | date_validation | payment_voucher | تاريخ الدفع مطلوب |
| `PV-006` | high | matching | payment_voucher | يجب أن يرتبط الدفع بفاتورة أو سبب واضح |
| `PV-009` | high | approval_control | payment_voucher | الدفع النقدي فوق حد معين يحتاج موافقة |
| `PV-010` | high | bank_reconciliation | payment_voucher | تحقق من مطابقة الدفع مع كشف البنك |
| `QT-003` | high | date_validation | quotation | تاريخ العرض مطلوب |
| `QT-004` | high | date_validation | quotation | تاريخ انتهاء العرض مطلوب |
| `QT-006` | high | completeness | quotation | البنود والأسعار مطلوبة |
| `QT-007` | high | policy_compliance | quotation | الخصم لا يتجاوز الحد المسموح |
| `QT-010` | high | approval_control | quotation | تحقق من الموافقة إذا كان الخصم عالياً |
| `RV-004` | high | completeness | receipt_voucher | طريقة القبض مطلوبة |
| `RV-005` | high | date_validation | receipt_voucher | تاريخ القبض مطلوب |
| `RV-006` | high | matching | receipt_voucher | يجب أن يرتبط القبض بفاتورة أو سبب واضح |
| `RV-007` | high | duplicate_detection | receipt_voucher | لا توجد سندات قبض مكررة |
| `RV-008` | high | bank_reconciliation | receipt_voucher | تحقق من مطابقة القبض مع كشف البنك |
| `SI-005` | high | vat_validation | sales_invoice | الرقم الضريبي للعميل مطلوب إذا كان خاضعاً للضريبة |
| `SI-009` | high | duplicate_detection | sales_invoice | لا توجد فاتورة بيع مكررة بنفس المبلغ والتاريخ والعميل |
| `SO-003` | high | date_validation | sales_order | تاريخ أمر البيع مطلوب |
| `SO-004` | high | completeness | sales_order | أمر البيع يجب أن يحتوي على بنود |
| `SO-005` | high | amount_validation | sales_order | الكميات والأسعار صحيحة |
| `SO-006` | high | duplicate_detection | sales_order | لا توجد أوامر بيع مكررة |
| `SO-007` | high | vendor_customer_risk | sales_order | تحقق من حد ائتمان العميل |
| `SO-008` | high | approval_control | sales_order | لا يتم إصدار فاتورة إذا تجاوز العميل حد الائتمان |
| `SS-001` | high | completeness | supplier_statement | اسم المورد مطلوب |
| `SS-002` | high | completeness | supplier_statement | رقم المورد أو الرقم الضريبي مطلوب |
| `SS-003` | high | completeness | supplier_statement | الفترة مطلوبة |
| `SS-004` | high | completeness | supplier_statement | الرصيد الافتتاحي مطلوب |
| `SS-007` | high | matching | supplier_statement | مطابقة فواتير المورد مع النظام |
| `SS-008` | high | matching | supplier_statement | مطابقة المدفوعات مع Payment Vouchers |
| `SS-009` | high | matching | supplier_statement | فواتير في كشف المورد غير موجودة في النظام |
| `SS-010` | high | matching | supplier_statement | مدفوعات في النظام غير موجودة في كشف المورد |
| `SS-011` | high | amount_validation | supplier_statement | كشف فروقات الرصيد |
| `VATD-002` | high | completeness | tax_vat_document | الفترة الضريبية مطلوبة |
| `VATD-003` | high | completeness | tax_vat_document | إجمالي المبيعات الخاضعة للضريبة مطلوب |
| `VATD-004` | high | completeness | tax_vat_document | إجمالي المشتريات الخاضعة للضريبة مطلوب |
| `VATD-008` | high | vat_validation | tax_vat_document | كشف فواتير بدون رقم ضريبي |
| `VATD-009` | high | vat_validation | tax_vat_document | كشف فواتير بضريبة غير صحيحة |
| `VATD-010` | high | matching | tax_vat_document | فواتير خارج الفترة الضريبية |
| `VATD-012` | high | matching | tax_vat_document | تقرير VAT يطابق فواتير البيع والشراء |

</details>

---

## ٤. الأثر على مستندات حقيقية

⚠️ **قِيس على قاعدة التطوير المحلية، لا على الإنتاج.** الأرقام أدناه لا تصف `tadgeeg.com`.

```
rule_engine.AuditResult   60 صفًّا · 20 رمزًا مميّزًا (أغلبها GAAP-*)
rule_engine.AuditRun       3
invoices                  84
```

| # | القياس | قاعدة التطوير |
|---|---|---|
| ١٠ | نتائج فاشلة لقواعد من الـ115 | **0** — وُجدت 6 نتائج ضمن الـ115، **جميعها `skipped`** |
| ١١ | مستندات كانت ستُحجَب ولم تُحجَب | **0** |
| ١٢ | ومنها مُعتمَد بالفعل | **0** |

**لم أقِسها على الإنتاج.** الاستعلام المكافئ للتشغيل هناك — قراءة فقط:

```sql
SELECT r.rule_code, r.status, COUNT(*)
FROM rule_engine_auditresult r
WHERE r.rule_code IN (/* الـ115 من الجدول أعلاه */)
GROUP BY r.rule_code, r.status;
```

🔴 والبند ١٢ يبقى **غير معروف على الإنتاج** — وهو أخطر ما في هذا التقرير:
مستند اعتُمد وكان سيُحجَب لو عمل الكتالوج.

---

## ٥. `except Exception` — قِيس ولم يُصلَح

**سبعة مواضع لا ستّة.** أعدت العدّ؛ الرقم السابق كان خاطئًا.

| # | الملف | السطر | الالتقاط |
|---|---|---|---|
| ١٣ | `apps/frontend/page_views.py` | 3794 | `except Exception` |
| | `apps/rule_engine/rules/base.py` | 72 | `except Exception` |
| | `apps/rule_engine/rules/base.py` | 202 | `except Exception` |
| | `apps/audit/rules/base_rule.py` | 61 | `except Exception` |
| | `apps/audit/rules/base_rule.py` | 126 | `except Exception` |
| | `apps/auditing/accounting_rules/base.py` | 38 | `except Exception` |
| | `apps/auditing/accounting_rules/result.py` | 31 | `except Exception` |

**١٤ — أيّها يبتلع أكثر من `ImportError`؟ السبعة جميعًا.**
لا واحد منها يلتقط `ImportError` بعينه. فأي عطل داخل الحلّ — لا الاستيراد فقط —
يُبتلع بنفس الصمت.

**لم أُصلحها**: إصلاحها اليوم يجعل السبعة تصرخ قبل أن يُحسم مصير الكتالوج،
وقد يوقف المنتج. **بند مسجَّل، أولويته تلي القرار مباشرةً.**

---

## ٦. ما لم أستطع قياسه، ولماذا

| | |
|---|---|
| أثر الوصل على الإنتاج | لا قياس على `tadgeeg.com` — يحتاج تشغيل الاستعلام أعلاه هناك |
| البند ١٢ (مستندات مُعتمَدة كانت ستُحجَب) | نفس السبب. **وهو الرقم الذي يحدّد ما يُبلَّغ للمدققين** |
| المنظومات الخمس التي يذكرها `CLAUDE.md` | قِست منظومة القواعد المستندية (236). المنظومات الأخرى لم أُعدّها هنا |
| سلوك الوصل تحت التشغيل الحقيقي | القياس استدعى الحلّ مباشرةً؛ لم أُشغّل تدقيقًا كاملًا موصولًا |
| أثر تغيّر 236 رمزًا على البيانات المخزَّنة | لم أفحص أين تُخزَّن الرموز خارج `AuditResult.rule_code` |

---

## ٧. أخطائي في هذه السلسلة

| الخطأ | التصحيح |
|---|---|
| قلت **ستّة** مواضع تبتلع `ImportError` | **سبعة** |
| قلت الملف المحجوب فيه **14 تسجيلًا** | **12** — `grep -c "_register("` عدّ التعريف والاستدعاء داخل الحلّ |
| توقّعت أن الوصل يمسّ الاثنتي عشرة المسجَّلة | يمسّ **236** — الحلّ يُصنّع مدخلًا لكل غير مطابِق |
| توقّعت أن عدم التطابق قد يرفع استثناءً | **لا يرفع** — يُصنّع ويُسجّل |
| «نقل حرفي، صفر تغيير سطر» لملف التقارير | استحال — الاستيراد النسبي كُتب لعمق قديم |
| تحكّم إيجابي `not in (403, 404)` | يقبل **400**، والنقطة كانت مكسورة. صُحّح إلى `== 200` |
| أداة فحص المتصفّح | كذبت مرّتين: انتظار ثابت بدل تحقّق شرط · ونقر أصاب «Arabic» لا «Sign In» |
| عملتُ على `main` مباشرةً | مخالفة §2. نُقل العمل إلى فرع، و`main` سليم |

**وأرقام نُقلت في هذه السلسلة بلا إعادة قياس، وأُعيد قياسها الآن:** عدد التسجيلات (14→12) ·
عدد مواضع الابتلاع (6→7) · نطاق الأثر (12→236) · حالات التظليل (1→3) · وسلوك عدم التطابق.

---

## ٨. الخلاصة — بلا توصية

- الكتالوج **عمل** 20 يومًا ثم صُمِت بملف فارغ. **أثر رجعي قائم.**
- الوصل يجعل **115 قاعدة** تبدأ بمنع الاعتماد، و**236 رمزًا** يتغيّر.
- ولا قاعدة تتوقّف عن المنع.
- والأثر على مستندات الإنتاج **غير مقيس**.

**لا اقتراح وصل ولا حذف.** الأرقام أعلاه، والقرار لك.
