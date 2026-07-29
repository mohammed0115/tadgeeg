#!/usr/bin/env python
"""Batch 2: remaining Arabic UI translations (short CRM/misc + long help/advisory)."""
import os
import subprocess

PO = "locale/ar/LC_MESSAGES/django.po"

T = {
    # ── Remaining short (CRM / subscription / tickets / misc) ──────────────
    "95% Automation": "أتمتة 95%",
    "(95% confidence, 5% expected error)": "(ثقة 95%، خطأ متوقّع 5%)",
    "Activity Timeline": "الخط الزمني للنشاط",
    "Activity Type": "نوع النشاط",
    "Add Manual Payment": "إضافة دفعة يدوية",
    "Amount (must equal plan price)": "المبلغ (يجب أن يساوي سعر الباقة)",
    "Awaiting payment": "بانتظار الدفع",
    "Back to customers": "العودة للعملاء",
    "Back to tickets": "العودة للتذاكر",
    "Client": "العميل",
    "% completed": "% مكتمل",
    "Components (name:weight%, comma-separated)": "المكوّنات (اسم:وزن%، مفصولة بفواصل)",
    "Conversation": "المحادثة",
    "Create manual payment": "إنشاء دفعة يدوية",
    "Create Support Ticket": "إنشاء تذكرة دعم",
    "Create ticket": "إنشاء تذكرة",
    "Create Ticket": "إنشاء تذكرة",
    "Customer Notes": "ملاحظات العميل",
    "Customers": "العملاء",
    "Custom years (only for 'Custom')": "سنوات مخصّصة (لـ 'مخصّص' فقط)",
    "Disable": "تعطيل",
    "Enable": "تفعيل",
    "Downgrade unavailable": "الخفض غير متاح",
    "Extend subscription": "تمديد الاشتراك",
    "Extend Subscription": "تمديد الاشتراك",
    "Manage subscription": "إدارة الاشتراك",
    "Has active": "لديه نشط",
    "indicator(s)": "مؤشّر/مؤشّرات",
    "mitigant(s)": "مخفّف/مخفّفات",
    "Internal": "داخلي",
    "Internal only (not visible to customer)": "داخلي فقط (غير ظاهر للعميل)",
    "Invoice limit": "حدّ الفواتير",
    "JSON": "JSON",
    "Last login": "آخر دخول",
    "Last payment": "آخر دفعة",
    "Link not found": "الرابط غير موجود",
    "New Ticket": "تذكرة جديدة",
    "No active": "لا نشط",
    "No active plan": "لا باقة نشطة",
    "No activity recorded.": "لا نشاط مسجَّل.",
    "No activity recorded yet.": "لا نشاط مسجَّل بعد.",
    "No customers match your filters.": "لا عملاء يطابقون مرشّحاتك.",
    "No internal notes.": "لا ملاحظات داخلية.",
    "No messages on this ticket.": "لا رسائل على هذه التذكرة.",
    "No notes match your filters.": "لا ملاحظات تطابق مرشّحاتك.",
    "No payments on record.": "لا دفعات مسجَّلة.",
    "No payments recorded yet.": "لا دفعات مسجَّلة بعد.",
    "No subscription on record.": "لا اشتراك مسجَّل.",
    "No tickets.": "لا تذاكر.",
    "No tickets match your filters.": "لا تذاكر تطابق مرشّحاتك.",
    "No users.": "لا مستخدمين.",
    "Only platform CRM staff can be assigned.": "يُسنَد فقط لموظّفي إدارة علاقات العملاء بالمنصّة.",
    "or click to choose. Allowed:": "أو انقر للاختيار. المسموح:",
    "paid": "مدفوع",
    "Paid on": "دُفِع في",
    "Payment history": "سجلّ الدفعات",
    "Payment reference": "مرجع الدفع",
    "Platform CRM": "إدارة علاقات العملاء بالمنصّة",
    "Policy": "السياسة",
    "Primary contact": "جهة الاتصال الرئيسية",
    "Reactivate Customer": "إعادة تفعيل العميل",
    "Recently updated": "حُدِّث حديثًا",
    "Recent Payments": "الدفعات الأخيرة",
    "Reserved": "محجوز",
    "Responded": "تمّت الاستجابة",
    "shift the % within the benchmark band": "حرّك النسبة ضمن نطاق المرجع",
    "SLA": "اتفاقية مستوى الخدمة",
    "Starts": "يبدأ",
    "Suspend Customer": "تعليق العميل",
    "Tickets": "التذاكر",
    "\\u2014 Select auditor \\u2014": "— اختر مدقّقًا —",
    "VAT Rate Validity (KSA 0/5/15%)": "صحّة نسبة الضريبة (السعودية 0/5/15%)",
    "View payment history": "عرض سجلّ الدفعات",
    "View receipt": "عرض الإيصال",
    "Your current plan.": "باقتك الحالية.",
    "Your payment receipts for this organization.": "إيصالات دفعك لهذه المنظمة.",
    # ── Audit page subtitles / advisories / help ───────────────────────────
    "Accepting evidence does not close the finding — review it separately.":
        "قبول الدليل لا يُغلق الملاحظة — راجعها بشكل منفصل.",
    "Accumulated accepted misstatements compared against materiality (ISA 450).":
        "التحريفات المقبولة المتراكمة مقارنةً بالأهمية النسبية (ISA 450).",
    "Add one row per risk (ISA 315 output). Combined risk = max(inherent, control).":
        "أضف صفًّا لكل مخاطرة (مخرج ISA 315). المخاطرة المركّبة = الأعلى بين المتأصّلة والرقابية.",
    "a deterministic auditor aid to structure judgment; not an audit conclusion or opinion.":
        "معين حتمي للمدقّق لتنظيم الحكم؛ ليس استنتاج تدقيق ولا رأيًا.",
    "a deterministic ISA 240 response aid; not an audit conclusion or opinion.":
        "معين حتمي للاستجابة وفق ISA 240؛ ليس استنتاج تدقيق ولا رأيًا.",
    "a deterministic ISA 300 planning aid; not an audit conclusion or opinion.":
        "معين حتمي للتخطيط وفق ISA 300؛ ليس استنتاج تدقيق ولا رأيًا.",
    "a deterministic ISA 330 mapping aid; not an audit conclusion or opinion.":
        "معين حتمي للربط وفق ISA 330؛ ليس استنتاج تدقيق ولا رأيًا.",
    "a deterministic ISA 540 aid; not an audit conclusion or opinion.":
        "معين حتمي وفق ISA 540؛ ليس استنتاج تدقيق ولا رأيًا.",
    "A discrepancy is flagged for the auditor — never auto-posted. No ledger entry is made.":
        "يُعلَّم التباين للمدقّق — لا يُرحَّل تلقائيًا. لا يُنشأ أي قيد في دفتر الأستاذ.",
    "Advisory planning document under ISA 300 — an overall strategy and detailed plan. Not an audit conclusion or opinion.":
        "وثيقة تخطيط استشارية وفق ISA 300 — استراتيجية كلية وخطة تفصيلية. ليست استنتاج تدقيق ولا رأيًا.",
    "Ask for supporting evidence against a GL finding or a SAD item. This does not change the finding — the auditor reviews it separately.":
        "اطلب أدلة داعمة مقابل ملاحظة أستاذ أو بند فروقات. هذا لا يغيّر الملاحظة — يراجعها المدقّق بشكل منفصل.",
    "Assessed risks (ISA 315) → responsive procedures (ISA 330) → evidence. The audit traceability chain in one place.":
        "المخاطر المقيَّمة (ISA 315) ← الإجراءات المستجيبة (ISA 330) ← الأدلة. سلسلة تتبّع التدقيق في مكان واحد.",
    "Assets: add cost, salvage, useful_life_years, elapsed_years to recompute NBV.":
        "الأصول: أضف التكلفة والخردة والعمر الإنتاجي والسنوات المنقضية لإعادة احتساب القيمة الدفترية.",
    "Balance sheet and income statement derived from the trial balance and account mappings, with key ratios, a year-over-year comparison and classification-anomaly flags.":
        "قائمتا المركز المالي والدخل مشتقّتان من ميزان المراجعة وربط الحسابات، مع نسب رئيسية ومقارنة سنوية وأعلام لشذوذ التصنيف.",
    "Capture the engagement context to derive an overall audit strategy (scope, timing, direction, resourcing) and a detailed audit plan of procedures.":
        "التقط سياق الارتباط لاشتقاق استراتيجية تدقيق كلية (النطاق، التوقيت، التوجيه، الموارد) وخطة تدقيق تفصيلية للإجراءات.",
    "Choose an engagement above to set its retention policy.":
        "اختر ارتباطًا أعلاه لتعيين سياسة الاحتفاظ به.",
    "Choose an engagement to analyze its trial balance.":
        "اختر ارتباطًا لتحليل ميزان مراجعته.",
    "Choose an engagement to begin substantive testing.":
        "اختر ارتباطًا لبدء الاختبارات الأساسية.",
    "Choose an engagement to build its management letter.":
        "اختر ارتباطًا لبناء خطاب إدارته.",
    "Choose an engagement to build its risk register.":
        "اختر ارتباطًا لبناء سجلّ مخاطره.",
    "Choose an engagement to manage its external confirmations.":
        "اختر ارتباطًا لإدارة تأكيداته الخارجية.",
    "Choose an engagement to prepare its audit readiness.":
        "اختر ارتباطًا لإعداد جاهزية تدقيقه.",
    "Choose an engagement to review its financial statements.":
        "اختر ارتباطًا لمراجعة قوائمه المالية.",
    "Choose an engagement to review its general ledger.":
        "اختر ارتباطًا لمراجعة أستاذه العام.",
    "Choose an engagement to view its Summary of Audit Differences.":
        "اختر ارتباطًا لعرض ملخّص فروقات تدقيقه.",
    "Choose at least one: a GL finding or a SAD item.":
        "اختر واحدًا على الأقل: ملاحظة أستاذ أو بند فروقات.",
    "Dated, attributable planning records held on the audit file (ISA 300 §12).":
        "سجلّات تخطيط مؤرّخة ومنسوبة محفوظة على ملف التدقيق (ISA 300 §12).",
    "derived deterministically from the trial balance; not a formal opinion.":
        "مشتقّة حتميًّا من ميزان المراجعة؛ ليست رأيًا رسميًّا.",
    "Describe the estimate and score the ISA 540 A20–A24 factors.":
        "صف التقدير وقيّم عوامل ISA 540 A20–A24.",
    "Deterministic indicators for auditor consideration; not audit findings and never auto-accepted.":
        "مؤشّرات حتمية لنظر المدقّق؛ ليست ملاحظات تدقيق ولا تُقبل تلقائيًا.",
    "Deterministic ISA 315/330 register. Advisory — supports the audit file; not an opinion. No ledger writes.":
        "سجلّ حتمي وفق ISA 315/330. استشاري — يدعم ملف التدقيق؛ ليس رأيًا. بلا كتابة في دفتر الأستاذ.",
    "Deterministic journal-level analytics over the staged general ledger.":
        "تحليلات حتمية على مستوى القيود فوق الأستاذ العام المُجهَّز.",
    "Deterministic re-performance under ISA 500/501. Variances are flagged for auditor judgement — nothing is posted to the ledger.":
        "إعادة أداء حتمية وفق ISA 500/501. تُعلَّم الفروقات لحكم المدقّق — لا يُرحَّل شيء إلى دفتر الأستاذ.",
    "Deterministic rules. Disable a rule to exclude it from future runs.":
        "قواعد حتمية. عطّل قاعدة لاستبعادها من التشغيلات المقبلة.",
    "Each driver is scored 0–25. Higher inherent = worse; higher control/procedure strength = better.":
        "يُقيَّم كل محرّك من 0–25. أعلى للمتأصّلة = أسوأ؛ أعلى لقوة الرقابة/الإجراء = أفضل.",
    "Enter the assessed risks of material misstatement; the engine maps each to responsive procedures — nature, timing, extent, and staffing — escalating significant and fraud risks.":
        "أدخل مخاطر التحريف الجوهري المقيَّمة؛ يربط المحرّك كلًّا بإجراءات مستجيبة — الطبيعة والتوقيت والمدى والفريق — مع تصعيد المخاطر الهامة والاحتيالية.",
    "Enter the engagement context to build the strategy and plan.":
        "أدخل سياق الارتباط لبناء الاستراتيجية والخطة.",
    "Evidence requested from you by the audit team. Upload supporting documents and submit for review.":
        "أدلة طلبها منك فريق التدقيق. ارفع المستندات الداعمة وأرسلها للمراجعة.",
    "Execute the deterministic rule set over a staged general ledger import.":
        "شغّل مجموعة القواعد الحتمية على استيراد أستاذ عام مُجهَّز.",
    "Facts known to the auditor at planning time (ISA 300 §7–9).":
        "الحقائق المعلومة للمدقّق وقت التخطيط (ISA 300 §7–9).",
    "Findings are machine-suggested candidates for auditor review — never audit conclusions.":
        "الملاحظات مرشّحات يقترحها النظام لمراجعة المدقّق — ليست استنتاجات تدقيق.",
    "If counted qty and unit cost are provided, tested value = counted qty × unit cost.":
        "إذا وُفِّرت الكمية المعدودة وتكلفة الوحدة: القيمة المُختبَرة = الكمية المعدودة × تكلفة الوحدة.",
    "If provided, tested value = cost − accumulated straight-line depreciation.":
        "إذا وُفِّرت: القيمة المُختبَرة = التكلفة − مجمّع إهلاك القسط الثابت.",
    "If provided, tested value = gross − deductions.":
        "إذا وُفِّرت: القيمة المُختبَرة = الإجمالي − الاستقطاعات.",
    "Immutable reference listing included in exported reports. Contains no download links by design.":
        "قائمة مرجعية ثابتة تُضمَّن في التقارير المصدَّرة. لا تحتوي روابط تنزيل عمدًا.",
    "Import a GL, run deterministic risk analysis, and review candidate findings.":
        "استورد أستاذًا عامًا، شغّل تحليل مخاطر حتميًّا، وراجع الملاحظات المرشّحة.",
    "Import a prior-period trial balance to enable the year-over-year comparison.":
        "استورد ميزان مراجعة لفترة سابقة لتفعيل المقارنة السنوية.",
    "Import a trial balance, review account mappings, and flag unusual accounts.":
        "استورد ميزان مراجعة، راجع ربط الحسابات، وعلّم الحسابات غير المعتادة.",
    "Integrity, coverage and retention reporting. Reporting only — no evidence is modified or deleted.":
        "تقارير السلامة والتغطية والاحتفاظ. تقارير فقط — لا يُعدَّل أو يُحذَف أي دليل.",
    "Inventory: add quantity_counted, unit_cost to recompute value.":
        "المخزون: أضف الكمية المعدودة وتكلفة الوحدة لإعادة احتساب القيمة.",
    "Inventory (ISA 501), fixed assets and payroll — recorded value vs an independently recomputed value, with variances flagged.":
        "المخزون (ISA 501) والأصول الثابتة والرواتب — القيمة المسجَّلة مقابل قيمة مُعاد احتسابها مستقلًّا، مع تعليم الفروقات.",
    "ISA 230 — preparer · senior reviewer · partner sign-off, with tamper-evident lock on signing.":
        "ISA 230 — اعتماد المُعِدّ · المراجِع الأول · الشريك، مع قفل مقاوم للعبث عند التوقيع.",
    "ISA 230 sign-off — preparer · senior reviewer · partner, with tamper-evident lock.":
        "اعتماد ISA 230 — المُعِدّ · المراجِع الأول · الشريك، مع قفل مقاوم للعبث.",
    "Likelihood is derived from each record's risk score (0-100). Impact is scaled against performance materiality.":
        "تُشتقّ الاحتمالية من درجة مخاطرة كل سجل (0-100). ويُقاس الأثر مقابل الأهمية للأداء.",
    "List the identified fraud risk factors; the engine builds the responsive procedures and always includes the ISA 240 §32 management-override procedures — even when no specific factor is entered.":
        "اسرد عوامل خطر الاحتيال المحدَّدة؛ يبني المحرّك الإجراءات المستجيبة ويشمل دائمًا إجراءات تجاوز الإدارة (ISA 240 §32) — حتى دون إدخال عامل محدّد.",
    "Mandatory regardless of specific factors — management override is a presumed risk.":
        "إلزامية بغضّ النظر عن العوامل المحدّدة — تجاوز الإدارة مخاطرة مفترضة.",
    "Materiality benchmarks (ISA 320) and sampling strategies (ISA 530) for the engagement plan.":
        "مراجع الأهمية النسبية (ISA 320) واستراتيجيات المعاينة (ISA 530) لخطة الارتباط.",
    "Matters we determined to be of most significance during our audit (ISA 701)":
        "الأمور التي رأينا أنها الأكثر أهمية خلال تدقيقنا (ISA 701)",
    "Nature / timing / extent of planned procedures (ISA 300 §9).":
        "طبيعة/توقيت/مدى الإجراءات المخطّطة (ISA 300 §9).",
    "No assessed risks yet. Build the Risk → Procedure → Evidence chain.":
        "لا مخاطر مقيَّمة بعد. ابنِ سلسلة المخاطرة ← الإجراء ← الدليل.",
    "No assessed risks yet. Record one above to start the chain.":
        "لا مخاطر مقيَّمة بعد. سجّل واحدة أعلاه لبدء السلسلة.",
    "No evidence has been requested for this finding yet.":
        "لم يُطلب دليل لهذه الملاحظة بعد.",
    "No evidence has been requested for this SAD item yet.":
        "لم يُطلب دليل لبند الفروقات هذا بعد.",
    "No findings. Import a GL and run risk analysis.":
        "لا ملاحظات. استورد أستاذًا وشغّل تحليل المخاطر.",
    "No GL risk findings yet. Import a general ledger and run risk analysis.":
        "لا ملاحظات مخاطر أستاذ بعد. استورد أستاذًا عامًا وشغّل تحليل المخاطر.",
    "No materiality profile set for this engagement.":
        "لا ملف أهمية نسبية معرَّف لهذا الارتباط.",
    "No outstanding evidence requests for this engagement.":
        "لا طلبات أدلة معلّقة لهذا الارتباط.",
    "No planning records saved yet. Build and save a strategy, responses, or fraud plan.":
        "لا سجلّات تخطيط محفوظة بعد. ابنِ واحفظ استراتيجية أو استجابات أو خطة احتيال.",
    "No readiness workpaper yet. Recalculate the SAD, then generate.":
        "لا ورقة جاهزية بعد. أعد حساب الفروقات ثم ولّد.",
    "No SAD calculated yet. Accept some GL findings, then recalculate.":
        "لم تُحسب الفروقات بعد. اقبل بعض ملاحظات الأستاذ ثم أعد الحساب.",
    "No trial balance imported for this engagement yet.":
        "لم يُستورد ميزان مراجعة لهذا الارتباط بعد.",
    "No working papers yet. Create your first paper to start an audit engagement.":
        "لا أوراق عمل بعد. أنشئ أول ورقة لبدء ارتباط تدقيق.",
    "One workspace per engagement, tying planning, risk, testing, evidence, differences and readiness together.":
        "مساحة عمل واحدة لكل ارتباط تربط التخطيط والمخاطر والاختبار والأدلة والفروقات والجاهزية معًا.",
    "Optional — the §32 management-override procedures are always produced. Link a factor to a detection signal to pull its catalogue procedures.":
        "اختياري — تُنتَج دائمًا إجراءات تجاوز الإدارة (§32). اربط عاملًا بإشارة اكتشاف لسحب إجراءات كتالوجها.",
    "Prepare the opinion-readiness workpaper from the SAD. Subject to auditor review — not a formal audit opinion.":
        "أعِدّ ورقة جاهزية الرأي من الفروقات. خاضعة لمراجعة المدقّق — ليست رأي تدقيق رسميًّا.",
    "Profile a management estimate — complexity, subjectivity, uncertainty and disclosure — to score its estimation uncertainty and flag significant-risk estimates.":
        "صِف تقدير الإدارة — التعقيد والذاتية وعدم اليقين والإفصاح — لتقييم عدم يقين تقديره وتعليم التقديرات عالية المخاطر.",
    "Read-only view. Evidence activity never modifies this SAD item or its conclusion.":
        "عرض للقراءة فقط. نشاط الأدلة لا يعدّل بند الفروقات هذا ولا استنتاجه.",
    "Read-only view. Finding status changes go through the finding review workflow; requesting or accepting evidence never changes this finding.":
        "عرض للقراءة فقط. تغييرات حالة الملاحظة تمرّ عبر سير مراجعة الملاحظات؛ طلب الدليل أو قبوله لا يغيّر هذه الملاحظة.",
    "Record internal-control deficiencies (ISA 265), capture management responses, and generate the letter.":
        "سجّل أوجه ضعف الرقابة الداخلية (ISA 265)، والتقط استجابات الإدارة، وولّد الخطاب.",
    "Request an external party to confirm a balance (ISA 505) and reconcile the reply against the books.":
        "اطلب من طرف خارجي تأكيد رصيد (ISA 505) وسوِّ الرد مقابل الدفاتر.",
    "Request, track, and review supporting evidence for audit findings.":
        "اطلب وتتبّع وراجع الأدلة الداعمة لملاحظات التدقيق.",
    "Required vs uploaded, accepted, rejected and pending evidence per finding and SAD item.":
        "المطلوب مقابل المرفوع والمقبول والمرفوض والمعلّق من الأدلة لكل ملاحظة وبند فروقات.",
    "Review, prioritise and assign outstanding evidence requests.":
        "راجع ورتّب وأسنِد طلبات الأدلة المعلّقة.",
    "Rule code, rule text, severity, and score. Score = severity weight (critical 25 · high 15 · medium 8 · low 3).":
        "رمز القاعدة ونصّها وشدّتها ودرجتها. الدرجة = وزن الشدّة (حرجة 25 · عالية 15 · متوسّطة 8 · منخفضة 3).",
    "Rule code, rule text, severity, and weighted score. Score = severity weight × failure count.":
        "رمز القاعدة ونصّها وشدّتها ودرجتها الموزونة. الدرجة = وزن الشدّة × عدد الإخفاقات.",
    "Rules that run synchronously on every uploaded document. Each rule produces an explanatory finding when it fails.":
        "قواعد تعمل تزامنيًّا على كل مستند مرفوع. تُنتج كل قاعدة ملاحظة تفسيرية عند إخفاقها.",
    "Saved planning records on the audit file (ISA 300 §12).":
        "سجلّات تخطيط محفوظة على ملف التدقيق (ISA 300 §12).",
    "Score the inherent, control and detection risk drivers to derive the audit-risk model (IR × CR × DR) and see whether your planned work meets the target audit risk.":
        "قيّم محرّكات المخاطرة المتأصّلة والرقابية والاكتشاف لاشتقاق نموذج مخاطر التدقيق (IR × CR × DR) ومعرفة ما إذا كان عملك المخطّط يحقّق مخاطر التدقيق المستهدفة.",
    "Secure balance confirmation · powered by Tadgeeg":
        "تأكيد رصيد آمن · مُشغَّل بواسطة تدقيق",
    "Select indicators and run the assessment to see the conclusion.":
        "اختر المؤشّرات وشغّل التقييم لرؤية الاستنتاج.",
    "Send your evidence to the audit team for review.":
        "أرسل دليلك إلى فريق التدقيق للمراجعة.",
    "Set the drivers and run the assessment to see the audit-risk model.":
        "عيّن المحرّكات وشغّل التقييم لرؤية نموذج مخاطر التدقيق.",
    "Subject to auditor review — not a formal audit opinion.":
        "خاضع لمراجعة المدقّق — ليس رأي تدقيق رسميًّا.",
    "Tested value (optional — overridden by recompute)":
        "القيمة المُختبَرة (اختياري — تتجاوزها إعادة الاحتساب)",
    "Thank you — your response has been recorded.":
        "شكرًا — سُجِّلت استجابتك.",
    "There are still open evidence requests for this engagement. Review them before concluding readiness.":
        "لا تزال هناك طلبات أدلة مفتوحة لهذا الارتباط. راجعها قبل إنهاء الجاهزية.",
    "These analytics are deterministic indicators for auditor consideration. They are not audit findings, are never auto-accepted, and do not constitute an audit opinion.":
        "هذه التحليلات مؤشّرات حتمية لنظر المدقّق. ليست ملاحظات تدقيق، ولا تُقبل تلقائيًا، ولا تشكّل رأي تدقيق.",
    "This communicates deficiencies to those charged with governance (ISA 265). It is not an audit opinion.":
        "يُبلِّغ هذا أوجه الضعف للمكلَّفين بالحوكمة (ISA 265). ليس رأي تدقيق.",
    "This confirmation has already been responded to. No further action is needed.":
        "تمّت الاستجابة لهذا التأكيد مسبقًا. لا حاجة لإجراء آخر.",
    "This confirmation link is invalid or has expired.":
        "رابط التأكيد هذا غير صالح أو منتهي الصلاحية.",
    "This output is an audit-readiness aid. The final audit opinion must be prepared and approved by a licensed auditor.":
        "هذا المخرَج معين لجاهزية التدقيق. يجب أن يُعِدّ الرأي النهائي ويعتمده مدقّق مرخَّص.",
    "This page shows outstanding evidence only. It is not a formal audit opinion; the final opinion must be prepared and approved by a licensed auditor.":
        "تعرض هذه الصفحة الأدلة المعلّقة فقط. ليست رأي تدقيق رسميًّا؛ يجب أن يُعِدّ الرأي النهائي ويعتمده مدقّق مرخَّص.",
    "Tick the financial, operating and other indicators present, plus any mitigating evidence, to classify going-concern doubt and the suggested reporting response.":
        "علّم المؤشّرات المالية والتشغيلية وغيرها الموجودة، مع أي أدلة مخفِّفة، لتصنيف الشكّ في الاستمرارية والاستجابة المقترحة للتقرير.",
    "the suggested reporting response is an auditor aid and never a formal audit opinion.":
        "الاستجابة المقترحة للتقرير معين للمدقّق وليست رأي تدقيق رسميًّا أبدًا.",
    "Upload a CSV or XLSX. Headers are matched flexibly (e.g. reference/sku/asset_tag, book_value, tested_value, tolerance).":
        "ارفع ملف CSV أو XLSX. تُطابَق العناوين بمرونة (مثل reference/sku/asset_tag وbook_value وtested_value وtolerance).",
    "When the audit team requests evidence, it will appear here.":
        "عندما يطلب فريق التدقيق دليلًا، سيظهر هنا.",
}


def _esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main():
    with open(PO, "r", encoding="utf-8") as fh:
        po = fh.read()
    blocks, added = [], 0
    for en, ar in T.items():
        if f'msgid "{_esc(en)}"' in po:
            continue
        blocks.append(f'\nmsgid "{_esc(en)}"\nmsgstr "{_esc(ar)}"\n')
        added += 1
    if blocks:
        with open(PO, "a", encoding="utf-8") as fh:
            fh.write("\n# TADGEEG-G8 batch2 — audit UI Arabic translations\n")
            fh.write("".join(blocks))
    print(f"added {added} new translations ({len(T)} in dict)")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
