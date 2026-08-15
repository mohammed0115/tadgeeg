# ملاحظات فحص الواجهة التفاعلي — نتائج أولية

- شغّل التطبيق في بيئة `DEBUG=False`، وأظهر الفحص أن `staticfiles` تستخدم `CompressedManifestStaticFilesStorage`، وبنى `collectstatic --noinput` ملف `staticfiles/staticfiles.json`.
- خادم التطوير لا يقبل HTTPS مباشرة؛ استُخدم وكيل HTTPS مؤقت. كان لابد من تمرير `ALLOWED_HOSTS` و`CSRF_TRUSTED_ORIGINS` و`ENABLE_SECURE_PROXY_SSL_HEADER=True` و`SECRET_KEY` قوي مؤقت كمتغيرات عملية فقط؛ لم يعدل ملف إعداد.
- شاشة الدخول تصير مرئية وسليمة شكلياً تحت DEBUG=False. تسجيل الدخول العادي يطلب OTP بريداً إلكترونياً؛ اعتمادات SMTP الخارجية غير صالحة في البيئة وأعادت 503 مع رسالة "Unable to send the verification code right now." لذلك أعيد تشغيل خادم الفحص بمتجر بريد console مؤقت مع بيانات اعتماد شكلية لتجاوز فحص بدء التشغيل، من دون إرسال بريد خارجي.
- سجّل المستخدم العادي التجريبي دخولاً عبر البريد المحلي وOTP، ثم حوّل إلى صفحة اختيار الخطة. تفعيل التجربة المجانية للحساب المعزول فقط سمح بالوصول إلى لوحة التحكم دون دفع.
- `/dashboard/`: رمز HTTP/عرض ناجحان، وتظهر بيانات المنظمة والحصة والصفر للمستندات. أغلقت نافذة البدء بزر `Skip`؛ اختفى الغطاء وبقيت اللوحة قابلة للاستخدام، وهو دليل تفاعل Alpine حقيقي لا صفحة جامدة.
- `/dashboard/files/`: يعرض صفحة ملفات المنظمة بنجاح، مع 0 ملفات ومرشحات ونقطة رفع؛ لا مخرجات Console في الفحص.
- `/invoices/`: يعرض قائمة فارغة سليمة مع 0 فواتير وزر رفع؛ لا مخرجات Console سابقة على الصفحة.
- المتصفح أعاد 404 واحداً لـ`/favicon.ico` في سجل الخادم عند تدفق OTP. لم يسجل Console المتصفح أخطاء JavaScript في فحص اللوحة أو صفحة الملفات.

## الحالة

لم يبدأ الرفع الفعلي بعد. Celery وRedis لم يشغلا؛ أي معالجة خلفية ستسجل كبند خارج نطاق إثبات المسار المتزامن.

## مصادر

- `/home/ubuntu/tadgeeg-review-artifacts/frontend_phase_zero_and_debug_check.log`
- `/home/ubuntu/tadgeeg-review-artifacts/frontend_collectstatic_summary.log`
- `/home/ubuntu/tadgeeg-review-artifacts/frontend_proxy_connectivity_diagnosis.log`
- `/home/ubuntu/tadgeeg-review-artifacts/frontend_email_settings_inventory.log`
- سجل خادم الفحص التفاعلي `frontend_integration_runserver_console_email_ready`
- لقطات المتصفح المحفوظة تحت `/home/ubuntu/screenshots/`.

## رفع الواجهة ومقارنة قاعدة البيانات

رُفع `frontend_ui_invoice.json` من صفحة `/invoices/upload/` عبر عنصر الملف الفعلي في الواجهة. العنصر مخفي في القالب؛ كُشف محلياً في DOM فقط كي يتمكن مشغل المتصفح من استهدافه، ولم يتغير أي ملف مشروع. أظهرت الواجهة مراحل Upload وOCR وGPT-4o وZATCA وFraud Scan، ثم نقلت المستخدم إلى `/invoices/b210b0d8-ed6a-47fa-828a-963bb4bf7ba0/`.

صفحة التفصيل سليمة التصيير وليست فارغة: عرضت المورد والرقم والتاريخ والنتيجة والقواعد الفاشلة ومخاطر 78% والحالة عالية. لكن استخلاص JSON عبر مسار الواجهة لم يحفظ القيم المقصودة في الملف: `invoice_number` ظهر `oice`، واسم المورد صار شظية JSON، و`subtotal` و`vat_amount` و`total_amount` صارت `0.00`. هذه القيم **تطابق صف Invoice و`extracted_data` بعد `refresh_from_db()`**؛ وبالتالي عداد الحقول المعروضة المخالفة للقاعدة هو 0 في العينة، لكن الاستخراج نفسه خاطئ مقارنة بالمدخل. هذا عرض وظيفي حيّ يُسجل ولا يُصلح في هذه الشحنة.

كما سجلت صفحة الواجهة 71% بينما قاعدة `InvoiceValidationResult.validation_score` هي `70.59`؛ هذا فرق عرض مقرب متوقع حتى خانة النسبة المئوية، وليس اختلاف قاعدة بيانات. الاستعلام في لحظة القياس لم يعثر على `AuditRun` أو `RiskScoreSummary` مرتبطين بـ`document_id`، رغم أن الفاتورة تعرض `risk_score=78.0` من صف Invoice. يجب ذكر حد الإثبات هذا في التقرير: Celery وRedis لم يشغلا، ومسار الخلفية غير المتزامن لا يُثبت هنا.

مصدر الدليل: `frontend_ui_invoice_database_snapshot.json` ولحظة العرض `/home/ubuntu/browser_html/8001-iz1529wxmqo4iepf7c9uy-23d09a65_sg1_manus_computer_b210b0d8-ed6a-47fa-828a-963bb4bf7ba0_1786781650157.html`.

### عرض تقرير التدقيق وعيب الرفع المضاعف

صفحة `/reports/invoice-audit/` تُصير بنجاح من حساب المؤسسة العادي، لكنها تعرض نتيجتين متطابقتين من الرفع نفسه: إجمالي الفواتير 2، وعدد التكرار 2، و68 قاعدة مطبقة. أثبت فحص قاعدة البيانات أن **ضغطة واحدة مرئية** على زر `Upload 1` أنشأت صفّي `Invoice` بالاسم والبصمة نفسيهما، بفارق 0.0008 ثانية في `created_at` (`b210…` و`e557…`). لكل صف أحداث `uploaded` و`processed` و`validated` مستقلة. لا توجد فاتورة سابقة في منظمة الفحص قبل التفاعل؛ إذ أن المنظمة والحساب أنشئا قبل الرفع بلا مستندات.

هذا عيب تكامل حي عالي الأثر: الواجهة تعطي المستخدم نتيجة واحدة، لكن الخلفية تنشئ فاتورتين وتفشل قواعد التكرار على بيانات ولّدتها عملية الرفع نفسها. يُسجل كـ **FI-01**، ولا يُصلح في هذه الشحنة.

المصدر: `frontend_ui_invoice_multiplicity.json` ولقطة تقرير التدقيق المرئية.

## العربية والـAPI

تبديل اللغة من لوحة التحكم نجح تفاعلياً: تغير العنوان والقائمة واتجاه العرض إلى العربية/RTL، ولم يسجل Console المتصفح خطأ JavaScript. غير أن حقول الحالة والمخاطر في بيانات الفاتورة بقيت `Flagged` و`High` بالإنجليزية، كما بقي `Coverage: SA` و`no_evidence` رموزاً/نصوصاً إنجليزية. هذا خلل توطين جزئي **FI-02**، لا كسر اتجاه.

نفذت فحوص قراءة فقط من جلسة المؤسسة العادية. نقطة `GET /api/v1/notifications/unread-count/` عادت `200 application/json` بجسم JSON سليم. أما `/api/v1/audit/results/` و`/api/v1/audit/jobs/stats/` فعادتا `404 text/html`، لا JSON؛ وهذا **FI-03** إن كانت الواجهة ما زالت تستدعيهما. في المقابل `/api/v1/analytics/live/` عاد `200 application/json` مع مؤشرات الوثيقتين و`cached:false`.

المصدر: مخرجات Console المحفوظة `exec_result_2026-08-15_08-15-54_910.txt` و`exec_result_2026-08-15_08-16-49_967.txt`، ولقطة لوحة التحكم العربية.

## التقرير الكامل للمستند وحدود المعالجة الخلفية

المسار المفترض `/documents/<uuid>/` أعاد 404 لأن هذا ليس مسار تفصيل مسجلاً للفاتورة، وليس دليلاً على رابط معروض مكسور. ثم اختُبر مسار API الفعلي `/api/v1/reports/document/<uuid>/`؛ أعاد `404 application/json` مع `{"error":"Report not found."}` للمستند الذي أنشأه رفع الواجهة. جرد قاعدة البيانات بيّن وجود مستندين بالحالة `pending` وغياب كامل لـ`AuditRun` و`RiskScoreSummary` لمنظمة الفحص.

لذلك لا توجد صفحة تقرير مستند حيّة يمكن أن تعرض `blocks_approval` لهذه العينة؛ الحقل لا يظهر في صفحة تفصيل الفاتورة، والمصدر المقابل `RiskScoreSummary` غير موجود. هذه فجوة تكامل خلفي **FI-04** مرتبطة بغياب معالجة المهام الخلفية، وتظل خارج برهان هذا الفحص لأن Celery وRedis لم يشغلا. لا يُفسَّر 404 على أنه خطأ قالب، لكنه يمنع استيفاء شرط العرض من النهاية إلى النهاية.

المصادر: `frontend_ui_audit_run_inventory.json` ومخرج Console `exec_result_2026-08-15_08-18-45_200.txt` وتعريف URL الجذري.

## تتبع القوالب المتأثرة بالعقد

| القالب | المصدر الخلفي المقاس | النتيجة |
|---|---|---|
| `templates/invoices/detail.html` | `apps/frontend/page_views.py::_build_invoice_display()`؛ يقرأ `InvoiceValidationResult` و`RiskScoreSummary` ويحولها إلى `invoice_display` | عُرضت قيم من صف `Invoice` و`InvoiceValidationResult` فعلاً؛ لم يوجد `RiskScoreSummary` للعينة، لذلك لم يثبت عرض `blocks_approval`. |
| `templates/audit/detail.html` | `page_views.py` يرسمه مع `case_id` عبر `_ctx` | البحث الساكن لم يجد قراءة مباشرة لـ`rule_results` أو `passed_count` أو `failed_count` أو `AuditReport`. لا يوجد `AuditCase` في مؤسسة العينة لفتح صفحة حية. |
| `templates/audit/engagements/workspace.html` | `engagement_workspace_views.py::_engagement_overview()` ثم `overview` | القراءة تخص `overview.gl_findings.escalated`، لا عقد `AuditReport`. لا يوجد ارتباط في مؤسسة العينة لعرضه حياً. |
| `templates/audit/evidence/create.html` | `evidence_views.py` يمرر `GeneralLedgerRiskFinding` و`AuditDifferenceItem` بنطاق المؤسسة | كلمة `escalated` جزء من خيار General Ledger Finding، لا من تقرير AuditEngine؛ لا توجد اكتشافات مؤهلة في العينة. |
| `templates/audit/modules/_shared.html` | جزء تنسيق مشترك | لا يقرأ بيانات؛ تعريف CSS للفئة `.fstat.escalated` فقط. |

الاستنتاج: النقل الحرفي لـ`AuditReport` لا يسبب فراغاً مثبتاً في هذه القوالب. القيد الحقيقي في العينة هو المعالجة الخلفية المعلقة، لا اسم العقد المنقول.
