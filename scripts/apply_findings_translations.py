"""Translations for the new Findings Register / High Risk overhaul."""
import polib
AR_PATH = 'locale/ar/LC_MESSAGES/django.po'
EN_PATH = 'locale/en/LC_MESSAGES/django.po'

AR = {
    # Recommendations
    'Reject invoices missing an invoice number; require vendors to resubmit.': 'ارفض الفواتير التي تفتقر لرقم فاتورة؛ اطلب من المورد إعادة الإصدار.',
    'Reject invoices without a date; cannot age or report without it.': 'ارفض الفواتير بلا تاريخ؛ لا يمكن احتساب عمرها أو التقرير عنها.',
    'Block any invoice with no vendor — this is a basic control failure.': 'احجب أي فاتورة بدون مورد — فشل ضبط أساسي.',
    'Withhold VAT recovery until a valid TRN is provided by the vendor.': 'أوقف استرداد الضريبة حتى يقدّم المورد رقماً ضريبياً صالحاً.',
    'Hold invoice; without a total amount it cannot be paid or audited.': 'علّق الفاتورة؛ بلا مبلغ إجمالي لا يمكن دفعها أو تدقيقها.',
    'Set a default currency at the organization level to prevent omissions.': 'حدّد عملة افتراضية على مستوى المؤسسة لمنع الإغفال.',
    'Investigate any zero/negative invoices — likely data error or refund mishandled.': 'حقّق في أي فاتورة بقيمة صفر أو سالبة — غالباً خطأ بيانات أو استرداد غير معالج.',
    'Recompute subtotal from line items or reject the invoice.': 'أعد احتساب المجموع الفرعي من البنود أو ارفض الفاتورة.',
    'Block payment until duplicate is reconciled with the vendor.': 'احجب الدفع حتى تتم تسوية التكرار مع المورد.',
    'This is an exact duplicate — verify whether it was paid before approving.': 'هذه نسخة مطابقة تماماً — تحقّق إن تم دفعها قبل الاعتماد.',
    'High double-payment risk — match against existing payments before release.': 'مخاطرة عالية للدفع المزدوج — طابق مع المدفوعات القائمة قبل الإفراج.',
    'Same file uploaded again — quarantine and notify the uploader.': 'نفس الملف رُفع مرة أخرى — اعزل الملف وأبلغ من رفعه.',
    'Confirm with the vendor whether the invoice number was reused legitimately.': 'تأكد من المورد ما إذا كان إعادة استخدام الرقم مشروعة.',
    'Correct the VAT rate to 15%% (KSA) before submitting to ZATCA.': 'صحّح نسبة الضريبة إلى 15%% (السعودية) قبل تقديمها إلى ZATCA.',
    'Recalculate VAT; the discrepancy will be rejected at e-invoicing submission.': 'أعد احتساب الضريبة؛ سيُرفض الفارق عند تقديم الفاتورة الإلكترونية.',
    'Subtotal + VAT must equal total — fix arithmetic error.': 'يجب أن يساوي (المجموع الفرعي + الضريبة) الإجمالي — صحّح الخطأ الحسابي.',
    'Request a valid TRN from the vendor; required for input VAT recovery.': 'اطلب رقماً ضريبياً صالحاً من المورد؛ مطلوب لاسترداد ضريبة المدخلات.',
    'Re-issue the invoice with a valid ZATCA Phase 2 QR code.': 'أعد إصدار الفاتورة مع رمز QR صالح وفق المرحلة الثانية لـ ZATCA.',
    'Compare to vendor history and obtain documented justification before approval.': 'قارن بسجل المورد واحصل على مبرّر موثّق قبل الاعتماد.',
    'Onboard the vendor through procurement before processing further invoices.': 'أدرج المورد عبر إدارة المشتريات قبل معالجة فواتير إضافية.',
    'Investigate possible split invoices (structuring) to bypass approval limits.': 'حقّق في احتمال تجزئة الفواتير (Structuring) لتجاوز حدود الاعتماد.',
    'Verify the price change is supported by an updated contract or quote.': 'تحقّق أن تغيير السعر مدعوم بعقد محدّث أو عرض سعر.',
    'Year-end concentration may indicate cutoff manipulation — sample for review.': 'تركّز نهاية السنة قد يشير لتلاعب بالقطع الزمني — أخذ عيّنة للمراجعة.',
    'Reduce concentration risk by qualifying additional vendors for this category.': 'قلّل مخاطر التركّز بتأهيل موردين إضافيين لهذه الفئة.',
    'Assign a cost center; required for departmental budget tracking.': 'حدّد مركز تكلفة؛ مطلوب لمتابعة ميزانية الإدارة.',
    'Map the invoice to a chart-of-accounts code before posting.': 'اربط الفاتورة برمز محاسبي قبل ترحيلها.',
    'Escalate to budget owner for approval of the overage or split into next period.': 'صعّد إلى مالك الميزانية لاعتماد التجاوز أو نقل الجزء الزائد للفترة القادمة.',
    'Investigate the post-approval edit — possible internal control breach.': 'حقّق في التعديل بعد الاعتماد — اختراق محتمل للضوابط الداخلية.',
    'Reject; every invoice must have a documented approver.': 'ارفض؛ يجب أن يكون لكل فاتورة معتمد موثّق.',
    'Audit trail must be reconstructed before this invoice can be relied on.': 'يجب إعادة بناء سجل التدقيق قبل الاعتماد على هذه الفاتورة.',
    'Request a clearer scan from the vendor to enable accurate OCR.': 'اطلب نسخة أوضح من المورد لتمكين OCR دقيق.',
    'Document appears tampered — escalate to fraud investigation.': 'يبدو أن المستند تعرّض للعبث — صعّد إلى التحقيق في الاحتيال.',
    'Alteration detected — quarantine and run a forensic review.': 'تم رصد تعديل — اعزل المستند وأجرِ مراجعة جنائية.',
    'ZATCA Phase 2 mandates a QR code — request a re-issued e-invoice.': 'تشترط المرحلة الثانية لـ ZATCA وجود رمز QR — اطلب إعادة إصدار الفاتورة الإلكترونية.',
    'Investigate and resolve before approval; contact the responsible reviewer.': 'حقّق وعالج قبل الاعتماد؛ تواصل مع المراجع المسؤول.',

    # Findings Register UI
    'Estimated financial exposure across all findings': 'التعرّض المالي المُقدَّر عبر جميع الاكتشافات',
    '%(sev)s severity · %(cnt)s invoices · %(impact)s SAR exposure': '%(sev)s الخطورة · %(cnt)s فاتورة · تعرّض %(impact)s ريال',
    'VAT & ZATCA': 'ضريبة القيمة المضافة و ZATCA',
    'Financial Controls': 'الضوابط المالية',
    'Findings Register': 'سجل الاكتشافات',
    'ISA-Aligned Findings': 'اكتشافات وفق معايير ISA',
    'Title / Description': 'العنوان / الوصف',
    'Financial Impact': 'الأثر المالي',
    'Recommendation:': 'التوصية:',
    'No specific invoices linked.': 'لا توجد فواتير محدّدة مرتبطة.',
    'Affected invoices:': 'الفواتير المتأثّرة:',
    'Priority Review': 'مراجعة عاجلة',
    'more violations': 'مخالفات إضافية',
    'Open invoice': 'فتح الفاتورة',
}

# Plural form
AR_PLURALS = {
    ('%(counter)s finding affecting %(affected)s invoice(s)',
     '%(counter)s findings affecting %(affected)s invoice(s)'):
        # Arabic has 6 plural forms (nplurals=6); Django uses these slots:
        # 0: zero, 1: one, 2: two, 3: few (3-10), 4: many (11-99), 5: other (100+)
        {
            0: 'لا توجد اكتشافات مؤثّرة على %(affected)s فاتورة',
            1: 'اكتشاف واحد مؤثّر على %(affected)s فاتورة',
            2: 'اكتشافان مؤثّران على %(affected)s فاتورة',
            3: '%(counter)s اكتشافات مؤثّرة على %(affected)s فاتورة',
            4: '%(counter)s اكتشافاً مؤثّراً على %(affected)s فاتورة',
            5: '%(counter)s اكتشاف مؤثّر على %(affected)s فاتورة',
        }
}

ar = polib.pofile(AR_PATH)
applied, missing = 0, []
for entry in ar:
    if entry.obsolete:
        continue
    if entry.msgid_plural:
        key = (entry.msgid, entry.msgid_plural)
        if key in AR_PLURALS:
            for slot, val in AR_PLURALS[key].items():
                entry.msgstr_plural[slot] = val
            if 'fuzzy' in entry.flags:
                entry.flags = [f for f in entry.flags if f != 'fuzzy']
            applied += 1
        continue
    if not (('fuzzy' in entry.flags) or (not entry.msgstr and entry.msgid != "")):
        continue
    if entry.msgid in AR:
        entry.msgstr = AR[entry.msgid]
        if 'fuzzy' in entry.flags:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        applied += 1
    else:
        missing.append(entry.msgid)
ar.save(AR_PATH)
print(f"AR applied: {applied}, missing: {len(missing)}")
for m in missing[:15]: print(f"  MISS: {m!r}")

en = polib.pofile(EN_PATH)
fixed = 0
for entry in en:
    if entry.obsolete:
        continue
    if entry.msgid_plural:
        if not entry.msgstr_plural.get(0) or 'fuzzy' in entry.flags:
            entry.msgstr_plural[0] = entry.msgid
            entry.msgstr_plural[1] = entry.msgid_plural
            if 'fuzzy' in entry.flags:
                entry.flags = [f for f in entry.flags if f != 'fuzzy']
            fixed += 1
        continue
    is_fuzzy = 'fuzzy' in entry.flags
    is_empty = not entry.msgstr and entry.msgid != ""
    if is_fuzzy or is_empty:
        entry.msgstr = entry.msgid
        if is_fuzzy:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        fixed += 1
en.save(EN_PATH)
print(f"EN fixed: {fixed}")

for path, name in [(AR_PATH, 'AR'), (EN_PATH, 'EN')]:
    p = polib.pofile(path)
    e = sum(1 for x in p if not x.msgstr and not x.obsolete and x.msgid != "" and not x.msgid_plural)
    f = sum(1 for x in p if 'fuzzy' in x.flags and not x.obsolete)
    pl = sum(1 for x in p if x.msgid_plural and not x.obsolete and (not x.msgstr_plural.get(0)))
    print(f"{name}: empty={e}, fuzzy={f}, plural_gaps={pl}")
