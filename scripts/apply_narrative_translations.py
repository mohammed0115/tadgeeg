"""Translations for narrative + per-rule recommendations introduced in this pass."""
import polib
AR_PATH = 'locale/ar/LC_MESSAGES/django.po'
EN_PATH = 'locale/en/LC_MESSAGES/django.po'

AR = {
    # ── Narrative copy ─────────────────────────────────────────
    'No rule violations were detected — controls operate as designed.': 'لم يتم اكتشاف أي مخالفات للقواعد — الضوابط تعمل بكفاءة.',
    'Critical issues were detected requiring immediate remediation; investigate the items below before final approval.':
        'تم اكتشاف مشاكل حرجة تتطلّب معالجة فورية؛ تحقّق من البنود أدناه قبل الاعتماد النهائي.',
    'Significant issues were detected. Resolve high-severity findings during the current review cycle.':
        'تم اكتشاف مشاكل جوهرية. عالج الاكتشافات عالية الخطورة خلال دورة المراجعة الحالية.',
    'Minor compliance gaps were detected. Plan remediation in the next operational sprint.':
        'تم اكتشاف فجوات امتثال طفيفة. خطّط للمعالجة في الدورة التشغيلية القادمة.',
    'Only low-severity observations were detected — controls are broadly effective; address opportunistically.':
        'تم اكتشاف ملاحظات منخفضة الخطورة فقط — الضوابط فعّالة عموماً؛ عالجها عند الإمكان.',
    '%(n)s critical finding(s) requiring immediate action': '%(n)s اكتشاف حرج يتطلّب إجراءً فورياً',
    '%(n)s high-severity finding(s) blocking approval': '%(n)s اكتشاف عالي الخطورة يحجب الاعتماد',
    '%(n)s medium-severity finding(s) for the remediation backlog': '%(n)s اكتشاف متوسط الخطورة للمعالجة لاحقاً',
    '%(n)s low-severity observation(s)': '%(n)s ملاحظة منخفضة الخطورة',
    'Affecting %(count)s %(type)s': 'تؤثّر على %(count)s %(type)s',
    'Estimated financial exposure: %(amount).2f SAR': 'التعرّض المالي المُقدَّر: %(amount).2f ريال',
    'Add real-time controls so the same rule is caught before %(type)s approval.':
        'أضِف ضوابط لحظية بحيث تُلتقط نفس القاعدة قبل اعتماد %(type)s.',
    'Train the team on the most-failed control to drive recurring failures down.':
        'درّب الفريق على القاعدة الأكثر فشلاً لتقليل الإخفاقات المتكرّرة.',
    'Close all blocking findings (critical + high) before the next reporting cycle.':
        'أغلق كل الاكتشافات الحاجبة (حرجة + عالية) قبل دورة التقرير القادمة.',
    'Address the dominant control failure (%(code)s) which accounts for most violations.':
        'عالج فشل الضبط المهيمن (%(code)s) الذي يمثّل غالبية المخالفات.',
    'Run targeted training on the controls that drove most failures across %(count)s %(type)s.':
        'أجرِ تدريباً موجّهاً على الضوابط التي تسبّبت بمعظم الإخفاقات عبر %(count)s %(type)s.',

    # ── Per-rule recommendations: Purchase Order ──
    'Reject POs missing a PO number; require resubmission.': 'ارفض أوامر الشراء بلا رقم؛ اطلب إعادة الإصدار.',
    'Reject POs with missing or future-dated dates.': 'ارفض أوامر الشراء بلا تاريخ أو ذات تاريخ مستقبلي.',
    'Block POs without a vendor name — basic control failure.': 'احجب أي أمر شراء بلا اسم مورد — فشل ضبط أساسي.',
    'Withhold processing until a valid vendor TRN is provided.': 'أوقف المعالجة حتى يقدّم المورد رقماً ضريبياً صالحاً.',
    'Recalculate VAT at 15% (KSA) before approval.': 'أعد احتساب الضريبة بنسبة 15% (السعودية) قبل الاعتماد.',
    'Subtotal + VAT must equal total — fix arithmetic error.': 'يجب أن يساوي (المجموع الفرعي + الضريبة) الإجمالي — صحّح الخطأ الحسابي.',
    'Escalate to budget owner for over-budget approval.': 'صعّد إلى مالك الميزانية لاعتماد التجاوز.',
    'Reject; every PO must have a documented approver.': 'ارفض؛ يجب أن يكون لكل أمر شراء معتمد موثّق.',
    'Investigate price variance against the related invoice or contract.': 'حقّق في فروق السعر مقابل الفاتورة أو العقد المرتبط.',
    'Assign a cost center; required for departmental tracking.': 'حدّد مركز تكلفة؛ مطلوب للمتابعة على مستوى الإدارة.',

    # ── Bank Statement ──
    'Reconcile closing balance with transactions before relying on the statement.':
        'سَوِّ رصيد الإقفال مع المعاملات قبل الاعتماد على كشف الحساب.',
    'Investigate large unjustified transactions — possible fraud signal.':
        'حقّق في المعاملات الكبيرة غير المبرّرة — إشارة احتيال محتملة.',
    'Investigate duplicate transactions — possible double-posting.':
        'حقّق في المعاملات المكرّرة — احتمال تسجيل مزدوج.',
    "Benford's-law anomaly — sample non-conforming transactions for review.":
        'شذوذ في قانون بنفورد — أخذ عيّنة من المعاملات غير المطابقة للمراجعة.',
    'Excessive rounded amounts may indicate fabricated data — sample for review.':
        'كثرة المبالغ المُدوَّرة قد تشير لبيانات مُلفّقة — أخذ عيّنة للمراجعة.',
    'Weekend transactions warrant additional approval evidence.':
        'معاملات نهاية الأسبوع تستوجب أدلّة اعتماد إضافية.',
    'Add a valid bank account number; required for reconciliation.':
        'أضِف رقم حساب بنكي صالح؛ مطلوب للتسوية.',
    'Provide explicit statement period dates.': 'قدّم تواريخ فترة الكشف بوضوح.',
    'Validate the IBAN against the Saudi format.': 'تحقّق من صيغة IBAN السعودية.',

    # ── Payroll ──
    'Investigate duplicate national IDs — possible ghost employee scheme.':
        'حقّق في تكرار أرقام الهوية الوطنية — احتمال موظفين وهميين.',
    'Confirm employees physically with HR before next payroll cycle.':
        'تحقّق من الموظفين فعلياً مع الموارد البشرية قبل دورة الرواتب القادمة.',
    'Recalculate net = gross − deductions; fix the variance.':
        'أعد احتساب الصافي = الإجمالي − الخصومات؛ عالج الفارق.',
    'Add GOSI contributions; mandatory under Saudi labor law.':
        'أضِف اشتراكات التأمينات الاجتماعية؛ إلزامي وفق نظام العمل السعودي.',
    'Document business justification for raises exceeding 30%.':
        'وثّق المبرّر التجاري للزيادات التي تتجاوز 30%.',
    'Migrate cash payments to bank transfers per AML guidance.':
        'حوّل المدفوعات النقدية إلى تحويلات بنكية وفق إرشادات مكافحة غسيل الأموال.',
    'State the explicit payroll period.': 'حدّد فترة كشف الرواتب بوضوح.',
    'Reconcile total against the per-employee detail.': 'سَوِّ الإجمالي مقابل تفاصيل كل موظف.',
    'Verify employee count matches HR master records.': 'تحقّق من تطابق عدد الموظفين مع سجلات الموارد البشرية.',

    # ── Expense Report ──
    'Require a receipt for every expense line before approval.':
        'اشترِط إيصالاً لكل بند مصروف قبل الاعتماد.',
    'Investigate duplicate expense claims — possible reimbursement fraud.':
        'حقّق في المطالبات المكرّرة — احتمال احتيال في التعويض.',
    'Escalate over-policy items to the responsible manager.': 'صعّد البنود المتجاوزة للسياسة إلى المدير المسؤول.',
    'Reject; every expense report needs documented approval.': 'ارفض؛ يحتاج كل تقرير مصروفات إلى اعتماد موثّق.',
    'Investigate possible expense splitting to bypass approval limits.':
        'حقّق في احتمال تجزئة المصروفات لتجاوز حدود الاعتماد.',
    'Confirm valid expense dates before reimbursement.': 'تأكّد من صحّة تواريخ المصروفات قبل التعويض.',
    'Recalculate VAT on each line.': 'أعد احتساب الضريبة على كل بند.',
    'Reconcile claimed total against the line-item sum.': 'سَوِّ المبلغ المطالَب به مقابل مجموع البنود.',

    # ── VAT Return ──
    'Validate the taxpayer TRN against ZATCA records.': 'تحقّق من الرقم الضريبي للمكلّف عبر سجلات ZATCA.',
    'Recalculate output VAT = standard-rated sales × 15%.': 'أعد احتساب ضريبة المخرجات = المبيعات الخاضعة × 15%.',
    'Investigate negative input VAT — likely data error.': 'حقّق في ضريبة المدخلات السالبة — غالباً خطأ بيانات.',
    'Recalculate net VAT = output − input; fix the variance.':
        'أعد احتساب صافي الضريبة = المخرجات − المدخلات؛ عالج الفارق.',
    'Reconcile output VAT against invoice ledger; investigate variance.':
        'سَوِّ ضريبة المخرجات مقابل دفتر الفواتير؛ حقّق في الفروق.',
    'Reconcile input VAT against purchase ledger; investigate variance.':
        'سَوِّ ضريبة المدخلات مقابل دفتر المشتريات؛ حقّق في الفروق.',
    'File on time — late filing triggers penalties.':
        'قدّم الإقرار في الموعد — التأخير يستوجب غرامات.',
    'Specify the explicit VAT return period.': 'حدّد فترة الإقرار الضريبي بوضوح.',

    # ── Fixed Asset ──
    'Investigate negative book values — likely posting error or impairment overshoot.':
        'حقّق في القيم الدفترية السالبة — احتمال خطأ ترحيل أو زيادة في الانخفاض.',
    'Cap accumulated depreciation at original cost; correct over-depreciation.':
        'حُدّ الإهلاك المتراكم بالتكلفة الأصلية؛ صحّح الإهلاك الزائد.',
    'Validate depreciation rates against the asset class policy.':
        'تحقّق من معدّلات الإهلاك مقابل سياسة فئة الأصول.',
    'Investigate duplicate asset IDs in the register.': 'حقّق في تكرار أرقام الأصول في السجل.',
    'Assign asset IDs to all rows for traceability.': 'أسنِد أرقام أصول لكل الصفوف للتتبّع.',
    'Recompute book value = cost − accumulated depreciation.': 'أعد احتساب القيمة الدفترية = التكلفة − الإهلاك المتراكم.',
    "Validate useful life against the asset's class (3–50 years typical).":
        'تحقّق من العمر الإنتاجي حسب فئة الأصل (3–50 سنة عادةً).',
    'Reconcile total cost against per-asset records.': 'سَوِّ إجمالي التكلفة مقابل سجلات كل أصل.',
    'Reject future-dated purchase records; possible fabrication.':
        'ارفض سجلات الشراء بتاريخ مستقبلي؛ احتمال تلفيق.',

    # ── Sales Receipt ──
    'Reject receipts missing a receipt number.': 'ارفض الإيصالات بلا رقم إيصال.',
    'Reject receipts with missing or future-dated dates.': 'ارفض الإيصالات بلا تاريخ أو ذات تاريخ مستقبلي.',
    'Correct the VAT rate to 15% (KSA).': 'صحّح نسبة الضريبة إلى 15% (السعودية).',
    'Recalculate VAT amount = subtotal × 15%.': 'أعد احتساب مبلغ الضريبة = المجموع الفرعي × 15%.',
    'Re-issue the receipt with a ZATCA QR code.': 'أعد إصدار الإيصال برمز QR من ZATCA.',
    'QR data must match receipt fields — re-issue with a corrected QR.':
        'يجب أن تطابق بيانات QR حقول الإيصال — أعد الإصدار برمز QR صحيح.',
    'Investigate duplicate receipts — possible double-recording.':
        'حقّق في الإيصالات المكرّرة — احتمال تسجيل مزدوج.',
    'Request a valid seller TRN; required for input VAT recovery.':
        'اطلب رقماً ضريبياً صالحاً للبائع؛ مطلوب لاسترداد ضريبة المدخلات.',
}

ar = polib.pofile(AR_PATH)
applied = 0; missing = []
for entry in ar:
    if entry.obsolete or entry.msgid_plural:
        continue
    if not (('fuzzy' in entry.flags) or (not entry.msgstr and entry.msgid != "")):
        continue
    if entry.msgid in AR:
        entry.msgstr = AR[entry.msgid]
        if 'fuzzy' in entry.flags:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
        applied += 1
    else:
        missing.append(entry.msgid)
ar.save(AR_PATH)
print(f"AR applied: {applied}, missing: {len(missing)}")
for m in missing[:10]: print(f"  MISS: {m!r}")

en = polib.pofile(EN_PATH)
fixed = 0
for entry in en:
    if entry.obsolete or entry.msgid_plural:
        continue
    if 'fuzzy' in entry.flags or (not entry.msgstr and entry.msgid != ""):
        entry.msgstr = entry.msgid
        if 'fuzzy' in entry.flags:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
        fixed += 1
en.save(EN_PATH)
print(f"EN fixed: {fixed}")

for path, name in [(AR_PATH, 'AR'), (EN_PATH, 'EN')]:
    p = polib.pofile(path)
    e = sum(1 for x in p if not x.msgstr and not x.obsolete and x.msgid != "" and not x.msgid_plural)
    f = sum(1 for x in p if 'fuzzy' in x.flags and not x.obsolete)
    print(f"{name}: empty={e}, fuzzy={f}")
