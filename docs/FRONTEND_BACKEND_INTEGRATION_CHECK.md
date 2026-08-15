# فحص تكامل الواجهة مع الخلفية

> **النطاق:** جهاز تطوير محلي، فحص فقط، **صفر تعديل شيفرة أو قالب أو إعداد**. أُجري بعد حذف `AuditEngine` وقبل الدمج. تغييرات هذا التقرير مقتصرة على `docs/` وأدلة القياس المرتبطة به.

| البند | القيمة |
|---|---|
| الفرع المقاس | `claude` عند `12a5e96` (`docs: add measured architecture baseline`) |
| بيئة التطبيق | `DEBUG=False`، SQLite محلي، `CompressedManifestStaticFilesStorage` |
| المستخدم | `JUNIOR_AUDITOR` عادي، `is_staff=False` و`is_superuser=False`، داخل منظمة اختبار معزولة |
| Celery / Redis | لم يشغلا؛ لا دليل على إتمام المهام الخلفية في هذا الفحص |
| نوع الفحص | متصفح حقيقي، شاشة دخول وOTP محلي، صفحة تفاعلية، رفع من واجهة المستخدم، ثم `refresh_from_db()` |
| حكم الفحص | **الواجهة جزئياً مكسورة**: التصيير والتفاعل الأساسيان يعملان، لكن رفعاً واحداً ينشئ فاتورتين، واستخراج JSON فاسد، ونقطتا API موروثتان تعيدان 404، ولا يثبت عرض `blocks_approval`. |

## 1. الغرض وحدود الإثبات

الغرض هو فحص ما لا تثبته مجموعة الاختبارات: أن الصفحة تُرسم فعلاً تحت `DEBUG=False`، وأن عناصر JavaScript تتفاعل، وأن الرفع يبدأ من واجهة مستخدم عادي وينتهي إلى ما يراه المستخدم وقاعدة البيانات. لا يثبت هذا التقرير صحة الإنتاج أو مهام Celery/Redis غير المشغلة، ولا يعالج أياً من الأعراض المسجلة.

تم إنشاء منظمة وحساب اختباريين باسمَي **Frontend Integration Check Org** و`frontend.integration.auditor@example.invalid`، واستخدمت تجربة مجانية محلية غير مدفوعة لتجاوز بوابة الحصة. نُظفت المنظمة والمستخدم بعد الفحص. حذف صفوف أحداث التدقيق التي ولّدها الاختبار أعاد تحذيرات محلية من `HashChain` عن مواضع محذوفة؛ هذه الصفوف كانت صفوف الفحص المنشأة في الجلسة فقط، لكن التحذير نفسه يثبت أن حذف بيانات تجربة من قاعدة مشتركة لا يحافظ على تسلسل السلسلة. لا يعالج التقرير هذه الملاحظة.[^cleanup]

## 2. البيئة وملفات static

طُبع الإعداد بدلاً من افتراضه. كان `DEBUG : False`، وكان مخزن static هو `CompressedManifestStaticFilesStorage`. نفذ الأمر `collectstatic --noinput` بنجاح: **434 ملفاً نُسخ و1,116 ملفاً عولج**، وظهر `staticfiles/staticfiles.json` فعلاً.[^phasezero][^static]

للوصول من المتصفح استُخدم وكيل HTTPS مؤقت ومررت متغيرات نطاق مؤقتة (`ALLOWED_HOSTS` و`CSRF_TRUSTED_ORIGINS` و`ENABLE_SECURE_PROXY_SSL_HEADER=True`) ومفتاح سر قوي للعملية فقط؛ لم يُحفظ أي إعداد. رفض Django أول تشغيل خارجي تحت `DEBUG=False` لأن `SECRET_KEY` الافتراضي غير آمن، وهو رفض حماية صحيح لا عيب واجهة.

تسجيل الدخول الفعلي يعتمد OTP بالبريد. بيانات SMTP المحلية الشكلية فشلت برسالة الخلفية الحرفية `SMTPAuthenticationError: (535, ... Username and Password not accepted)`، وعرضت الواجهة: **`Unable to send the verification code right now. Please try again shortly.`** مع HTTP 503. لاستكمال فحص واجهة محلي فقط، شغل خادم الفحص بمتجر بريد console مؤقت؛ لم يرسل أي بريد خارجي.[^email]

## 3. تتبع القوالب التي ذُكرت بوصفها متأثرة بالعقد المنقول

| القالب | مصدر العرض المقاس | نتيجة التتبع |
|---|---|---|
| `templates/invoices/detail.html` | `apps/frontend/page_views.py::_build_invoice_display()`؛ يقرأ `InvoiceValidationResult` و`RiskScoreSummary` | عرض الصفحة موجود ومقارن بالقاعدة في §5. لا يوجد `RiskScoreSummary` لعينة الرفع، لذلك لا يمكن إثبات عرض `blocks_approval`. |
| `templates/audit/detail.html` | `page_views.py` يرسمه مع `case_id` عبر `_ctx` | لا قراءة مباشرة مثبتة لـ`AuditReport` أو `rule_results` أو عدادات النجاح/الفشل؛ لا توجد `AuditCase` في منظمة الاختبار لعرض الصفحة حياً. |
| `templates/audit/engagements/workspace.html` | `_engagement_overview()` يمرر `overview` | حقل `escalated` يخص `overview.gl_findings`، لا عقد AuditEngine؛ لا توجد ارتباطات اختبار. |
| `templates/audit/evidence/create.html` | `evidence_views.py` يمرر `GeneralLedgerRiskFinding` و`AuditDifferenceItem` | `escalated` خيار لحالة اكتشاف دفتر الأستاذ؛ ليس من `AuditReport`. لا توجد اكتشافات اختبار مؤهلة. |
| `templates/audit/modules/_shared.html` | جزء CSS مشترك | لا يقرأ بيانات؛ يحوي تعريف `.fstat.escalated` فقط. |

> **الاستنتاج:** لا يثبت الفحص فراغاً سببه نقل `AuditReport`. القيد الفعلي هو أن المسار غير المتزامن لم ينشئ النتيجة/الملخص اللذين يعتمد عليهما قرار الحجب.[^template]

## 4. الصفحات والتفاعل في المتصفح

| الصفحة أو الفعل | النتيجة المرئية | Console / الشبكة | الحكم |
|---|---|---|---|
| `/dashboard/` | تصيير كامل للوحة، المنظمة والحصة والإحصاءات ظاهرة | لا مخرجات Console | سليم شكلياً |
| نافذة البداية ثم `Skip` | أُغلق الغطاء وبقيت اللوحة قابلة للاستخدام | لا مخرجات Console | **تفاعل Alpine مثبت** |
| `/dashboard/files/` | واجهة منظمة مستقلة، مرشحات و0 ملفات وزر رفع | لا مخرجات Console | سليم شكلياً |
| `/invoices/` | قائمة فارغة سليمة قبل الرفع، ثم قائمة تعرض نتيجتي رفع | لا خطأ Console مثبت | متأثر بعيب الرفع FI-01 |
| `/invoices/<pk>/` | صفحة تفصيل وقواعد ومخاطر وعناصر تصحيح ظاهرة | لا استثناء عرض؛ انظر تطابق القاعدة في §5 | متأثرة بالاستخراج والحجب FI-01/FI-04 |
| `/reports/invoice-audit/` | تقرير مرئي كامل | يعرض فواتير مكررة من الرفع الواحد | متأثر بـFI-01 |
| `/platform-admin/` | المستخدم العادي أعيد إلى `/dashboard/`؛ لم يرَ واجهة الإدارة | حماية/أسبقية مسار تعمل في هذه الجلسة | سليم للحساب العادي |
| تبديل اللغة | انتقل إلى العربية واتجاه RTL ظاهر | لا مخرجات Console | تفاعل سليم، لكن توطين جزئي FI-02 |

## 5. رفع واجهة المستخدم، العرض، وقاعدة البيانات

رُفع الملف `frontend_ui_invoice.json` من `/invoices/upload/` بضغط زر **Upload 1** واحد. أظهر المستخدم مراحل Upload وOCR وGPT-4o وZATCA وFraud Scan، ثم انتقل إلى صفحة الفاتورة. عنصر الملف مخفي في القالب؛ كشف محلياً في DOM فقط كي يستطيع مشغل المتصفح استهداف عنصر `<input type=file>` ذاته. لم يتغير القالب أو الشيفرة.

### مقارنة القيم المرئية بالسجل بعد `refresh_from_db()`

| الحقل | ما عرضه المستخدم | القيمة المقاسة في القاعدة | النتيجة |
|---|---|---|---|
| رقم الفاتورة | `oice` | `oice` | مطابق للصف، لكن خاطئ مقارنة بمدخل JSON |
| اسم المورد | `_name": "Frontend Integration Supplier",` | القيمة نفسها | مطابق للصف، لكن شظية JSON خاطئة |
| تاريخ الفاتورة | `2015-08-26` | `2015-08-26` | مطابق للصف، لكنه غير تاريخ المدخل |
| subtotal | `—` | `0.00` | تمثيل عرض فارغ للقيمة الصفرية؛ لا اختلاف بيانات |
| VAT | `—` | `0.00` | تمثيل عرض فارغ للقيمة الصفرية؛ لا اختلاف بيانات |
| الإجمالي | `—` | `0.00` | تمثيل عرض فارغ للقيمة الصفرية؛ لا اختلاف بيانات |
| المخاطر | `78% High Risk` | `78.0 / high` | مطابق بعد التنسيق |
| نتيجة التدقيق | `71%` | `70.59` | تقريب عرض متوقع |
| القواعد | 24 ناجحة و10 فاشلة، والقائمة نفسها | 24 و10 والقائمة نفسها | مطابق |
| `blocks_approval` | غير معروض | لا `RiskScoreSummary` | غير قابل للإثبات؛ انظر FI-04 |

**النتيجة العددية:** حقول عرض تخالف صف القاعدة بعد التحديث: **0**. حقول متوقعة لا تُعرض: **1** (`blocks_approval`). لا يعني الصفر أن الاستخراج سليم: مصدر الخطأ مشترك بين العرض والصف؛ الملف أدخل رقم `UI-FRONTEND-2026-001` ومبالغ 1000/150/1150، لكن المسار حفظ قيماً مشوهة/صفرية.[^parity]

## 6. نداءات API المرئية والمقاسة

| الطلب | رمز HTTP | Content-Type | النتيجة |
|---|---:|---|---|
| `GET /api/v1/notifications/unread-count/` | 200 | `application/json` | JSON صالح: `{"unread_count":0,"recent":[]}` |
| `GET /api/v1/audit/results/` | 404 | `text/html` | صفحة 404، لا JSON — FI-03 |
| `GET /api/v1/audit/jobs/stats/` | 404 | `text/html` | صفحة 404، لا JSON — FI-03 |
| `GET /api/v1/analytics/live/` | 200 | `application/json` | JSON صالح، يشمل `pending_documents` و`audits_running` |
| `GET /api/v1/reports/document/<document-id>/` | 404 | `application/json` | `{"error":"Report not found."}` — FI-04 |

الصفحة الحالية لم تطلب نقاط audit الموروثة الثلاث من سجل أداء المتصفح؛ طلبت `notifications/unread-count` المتكرر فقط. لذلك يثبت هذا الجدول أن النقطتين غير موجودتين إن استدعتهما JS لاحقاً، لا أن كل صفحة تستدعيهما الآن.[^api]

## 7. العيوب والانحرافات المسجلة — بلا إصلاح

| المعرّف | الشدة | العرض الحرفي | النطاق أو الدليل |
|---|---|---|---|
| FI-01 | حرج | ضغطة واجهة واحدة على `Upload 1` أنشأت فاتورتين متطابقتين بفارق 0.0008 ثانية؛ ظهرت `Total Invoices 2` و`Duplicate Count 2` | صفان باسم الملف نفسه، ولكل منهما أحداث `uploaded` و`processed` و`validated`؛ التقرير يتعامل معهما كتكرار حقيقي |
| FI-02 | متوسط | بعد تبديل العربية بقيت `Flagged` و`High` و`Coverage: SA` و`no_evidence` إنجليزية/رمزية | RTL والتبديل يعملان، لكن التوطين غير مكتمل |
| FI-03 | متوسط | `/api/v1/audit/results/` و`/api/v1/audit/jobs/stats/` يعيدان 404 HTML بدلاً من JSON | خطر كسر صامت إذا بقي أي مستدعٍ JavaScript لها |
| FI-04 | عالٍ | المستندان الناتجان `processing_status=pending`، ولا `AuditRun` ولا `RiskScoreSummary`؛ `blocks_approval` غير معروض، وتقرير المستند يجيب `Report not found.` | Celery وRedis لم يشغلا؛ لا يدعي هذا التقرير سبباً أعمق أو يصلحه |
| FI-05 | عالٍ | JSON المدخل يحفظ رقم `oice`، ومورد شظية JSON، ومبالغ 0.00 | العرض يطابق صف القاعدة، لكن البيانات المستخرجة لا تطابق مدخل الرفع |
| FI-06 | منخفض | طلب `/favicon.ico` سجل `404` أثناء تدفق OTP | أثر مرئي/سجل فقط، لم يوقف الصفحة |

## 8. القياس القابل لإعادة التشغيل

| السؤال | الأمر أو الدليل | المخرج المقاس |
|---|---|---|
| الرأس والحالة | `git status --short; git log --oneline -1; git fetch origin; git log --oneline origin/claude -1` | رأس محلي وبعيد `12a5e96` وشجرة نظيفة قبل الوثائق |
| تجميع الاختبارات | `DJANGO_SETTINGS_MODULE=finai_backend.settings.test pytest -q --collect-only` | 4,035 اختباراً مجمعاً؛ فحص التغطية في الجمع وحده لا يحقق حد 45% (متوقع عند `--collect-only`) |
| DEBUG والتخزين | `DEBUG=False ... manage.py shell -c ...` | `DEBUG : False` و`CompressedManifestStaticFilesStorage` |
| manifest | `DEBUG=False ... manage.py collectstatic --noinput` | 434 نسخ و1,116 معالجة و`staticfiles/staticfiles.json` موجود |
| الرفع وقاعدة البيانات | متصفح ثم `Invoice.refresh_from_db()` و`InvoiceValidationResult.refresh_from_db()` | صفا Invoice، عشر قواعد فاشلة، وتطابق العرض/الصف كما في §5 |
| API | `fetch(...)` من جلسة المتصفح | الرموز وContent-Type في §6 |
| التنظيف | `cleanup_frontend_integration_fixture.py` | المنظمة 0 والمستخدم 0 بعد التنظيف النهائي |

## 9. ما لم يُثبت

لا يثبت الفحص معالجة مهمة Celery أو بث Redis أو إنشاء `AuditRun` أو `RiskScoreSummary` أو التقرير الكامل للمستند. لم تُشغّل هذه الخدمات عمداً، ولذلك لا يجوز قبول أو رفض منطق الحجب النهائي من هذه البيئة. كذلك لم تعرض الصفحات الثلاث المرتبطة بحالات تدقيق/ارتباطات/أدلة حية، لعدم وجود بيانات من تلك الأنواع في المؤسسة المعزولة.

الحد الثاني هو أن فاتورة JSON الصغيرة اختبرت المسار المرئي والربط بالقاعدة، لا جودة جميع صيغ PDF وOCR. ظهرت فيها FI-05 تحديداً، ولذلك لا يصح تعميمها إلى كل المستندات من دون قياس منفصل.

## 10. الحكم وقرار ما قبل الدمج

**الحكم الصريح: الواجهة جزئياً مكسورة.** التصيير تحت `DEBUG=False`، static manifest، الدخول العادي مع OTP محلي، لوحة المؤسسة، صفحة الملفات، قائمة الفواتير، التقرير، RTL، وتفاعل Alpine تعمل. لكن FI-01 وحده حاجب للدمج: الرفع الواحد ينشئ فاتورتين، فيغير العدادات والتكرار والتقرير. FI-04 وFI-05 يمنعان كذلك قبول أن واجهة المستخدم تعرض مسار تدقيق موحداً كاملاً، لأن نتيجة الحجب غير موجودة للعينة والاستخراج المشوه يعرض بيانات مشوهة متطابقة مع القاعدة.

> **قرار التقرير:** لا دمج إلى `main` قبل شحنة إصلاح منفصلة تشخّص FI-01 أولاً، ثم تعالج FI-04/FI-05 وفق بيئة خدمات خلفية حقيقية. لا يحتوي هذا التقرير أي إصلاح أو تعديل شيفرة.

[^phasezero]: [فحص الرأس وDEBUG والتخزين](frontend_integration_evidence/frontend_phase_zero_and_debug_check.log)
[^static]: [بناء static وmanifest](frontend_integration_evidence/frontend_collectstatic_summary.log)
[^email]: [جرد إعداد البريد](frontend_integration_evidence/frontend_email_settings_inventory.log)
[^template]: [تتبع القوالب ومصادر العرض](frontend_integration_evidence/frontend_template_contract_trace.log)
[^parity]: [لقطة قاعدة البيانات بعد refresh](frontend_integration_evidence/frontend_ui_invoice_database_snapshot.json) و[مقارنة العرض بالقاعدة](frontend_integration_evidence/frontend_ui_display_database_parity.json)
[^api]: [ملاحظات المتصفح ونتائج API](frontend_integration_evidence/frontend_browser_findings.md)
[^cleanup]: [التنظيف النهائي](frontend_integration_evidence/frontend_integration_cleanup_final.log)
