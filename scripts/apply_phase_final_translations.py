"""Apply Arabic translations for all Phase-2/3/4/Final pending msgids.

For EN: msgstr = msgid (English source).
For AR: explicit translations dict.
"""
import polib

AR_PATH = '/home/mohamed/tadgeeg/locale/ar/LC_MESSAGES/django.po'
EN_PATH = '/home/mohamed/tadgeeg/locale/en/LC_MESSAGES/django.po'

AR = {
    # Session detail
    'Audit Session': 'جلسة التدقيق',
    'Duplicate': 'مكرّرة',
    'Highest Risk': 'أعلى مخاطرة',
    'Linked Batch': 'الدفعة المرتبطة',
    'Open batch details': 'فتح تفاصيل الدفعة',
    'Summary built from session data': 'ملخّص مبني على بيانات الجلسة',
    'Top Findings': 'أبرز الاكتشافات',
    'No open findings currently': 'لا توجد اكتشافات مفتوحة حالياً',
    'Invoices in Session': 'الفواتير داخل الجلسة',
    'No invoices linked to this session': 'لا توجد فواتير مرتبطة بهذه الجلسة',
    'Audit session': 'جلسة تدقيق',
    'Created by': 'أُنشئت بواسطة',

    # CMS About page
    'About Page': 'صفحة من نحن',
    'Content Management': 'إدارة المحتوى',
    'Edit About Page': 'تحرير صفحة من نحن',
    'Edit company about page content': 'تعديل محتوى صفحة التعريف بالشركة',

    # Bilingual labels
    'Title (EN)': 'العنوان (إنجليزي)',
    'Title (Arabic)': 'العنوان (عربي)',
    'Subtitle (EN)': 'العنوان الفرعي (إنجليزي)',
    'Subtitle (Arabic)': 'العنوان الفرعي (عربي)',
    'Main Content (EN)': 'المحتوى الرئيسي (إنجليزي)',
    'Main Content (Arabic)': 'المحتوى الرئيسي (عربي)',
    'Description (EN)': 'الوصف (إنجليزي)',
    'Content (EN)': 'المحتوى (إنجليزي)',
    'Content (Arabic)': 'المحتوى (عربي)',
    'Mission (EN)': 'الرسالة (إنجليزي)',
    'Vision (EN)': 'الرؤية (إنجليزي)',
    'Question (EN)': 'السؤال (إنجليزي)',
    'Question (Arabic)': 'السؤال (عربي)',
    'Answer (EN)': 'الجواب (إنجليزي)',
    'Answer (Arabic)': 'الجواب (عربي)',
    'Plan Name (EN)': 'اسم الخطة (إنجليزي)',
    'Plan Name (Arabic)': 'اسم الخطة (عربي)',
    'Meta Title (EN)': 'Meta Title (إنجليزي)',
    'Meta Title (Arabic)': 'Meta Title (عربي)',
    'Meta Description (EN)': 'Meta Description (إنجليزي)',
    'Meta Description (Arabic)': 'Meta Description (عربي)',
    'Keywords (EN)': 'Keywords (إنجليزي)',

    # Team / about
    'Founded Date': 'تاريخ التأسيس',
    'Employee Count': 'عدد الموظفين',
    'Add Member': 'إضافة عضو',
    'Role / Title': 'الدور / المسمّى',
    'No team members yet.': 'لا يوجد أعضاء فريق بعد.',
    'Save Team': 'حفظ الفريق',
    'Failed to load page data': 'تعذّر تحميل بيانات الصفحة',
    'Content saved': 'تم حفظ المحتوى',
    'Team saved': 'تم حفظ الفريق',

    # FAQ CMS
    'Manage questions and answers shown on the site': 'إدارة الأسئلة والأجوبة المعروضة على الموقع',
    'All Categories': 'جميع الفئات',
    'Search in questions...': 'البحث في الأسئلة...',
    'questions': 'سؤال',
    'No questions. Click "Add Question" to start.': 'لا توجد أسئلة. انقر "إضافة سؤال" للبدء.',
    'Question in English?': 'Question in English?',
    'Question in Arabic?': 'السؤال بالعربية؟',
    'Answer in English...': 'Answer in English...',
    'Answer in Arabic...': 'الجواب بالعربية...',

    # Homepage CMS
    'Edit homepage content for the platform': 'تعديل محتوى الصفحة الرئيسية للمنصّة',
    'Smart financial auditing': 'تدقيق مالي ذكي',
    'Automate compliance...': 'أتمتة الامتثال...',
    'Primary CTA Text (EN)': 'نص CTA الرئيسي (إنجليزي)',
    'Primary CTA URL': 'رابط CTA الرئيسي',
    'Secondary CTA Text (EN)': 'نص CTA الثانوي (إنجليزي)',
    'Secondary CTA URL': 'رابط CTA الثانوي',
    'Partners & Customers': 'الشركاء والعملاء',
    'Partners': 'الشركاء',
    'Values': 'القيم',
    'See how it works': 'شاهد كيف يعمل',

    # Intro Video CMS
    'Manage the platform intro video shown on the site': 'إدارة الفيديو التعريفي للمنصّة المعروض في الموقع',
    'Video Settings': 'إعدادات الفيديو',
    'Video URL (YouTube / Vimeo)': 'رابط الفيديو (YouTube / Vimeo)',
    'Short description in Arabic...': 'وصف مختصر بالعربية...',
    'Video Duration': 'مدّة الفيديو',
    'Play Button Text (Arabic)': 'نص زر التشغيل (عربي)',
    'Watch the video': 'شاهد الفيديو',
    'Show intro video on the site': 'عرض الفيديو التعريفي في الموقع',
    'Preview': 'معاينة',
    'Add the thumbnail URL': 'أضف رابط الصورة المصغّرة',
    'Video Status': 'حالة الفيديو',
    'Shown on site': 'معروض في الموقع',
    'Hidden': 'مخفي',
    'Open Video': 'فتح الفيديو',
    'Failed to load video data': 'تعذّر تحميل بيانات الفيديو',
    'Intro video saved': 'تم حفظ الفيديو التعريفي',

    # Pages CMS
    'Page Management': 'إدارة الصفحات',
    'All CMS pages and published content': 'جميع صفحات CMS والمحتوى المنشور',
    'Search by title or URL...': 'البحث بالعنوان أو الرابط...',
    'No matching pages': 'لا توجد صفحات مطابقة',
    'URL': 'الرابط',
    'URL (Slug)': 'الرابط (Slug)',
    'Page saved': 'تم حفظ الصفحة',
    'Are you sure you want to delete this page?': 'هل أنت متأكد من حذف هذه الصفحة؟',

    # Pricing CMS
    'Manage subscription plans and displayed pricing': 'إدارة خطط الاشتراك والأسعار المعروضة',
    'Most Popular': 'الأكثر شيوعاً',
    'Add new plan': 'إضافة خطة جديدة',
    'Advanced Plan': 'الخطة المتقدّمة',
    'Price (SAR)': 'السعر (ريال سعودي)',
    'Billing Period': 'فترة الفوترة',
    'Monthly': 'شهرياً',
    'Annual': 'سنوياً',
    'Features (one per line)': 'الميزات (سطر لكل ميزة)',
    'File upload': 'رفع الملفات',
    'Automatic reports': 'التقارير التلقائية',
    'ZATCA support': 'دعم ZATCA',
    'Are you sure you want to delete this plan?': 'هل أنت متأكد من حذف هذه الخطة؟',

    # Services CMS
    'Service Management': 'إدارة الخدمات',
    'Edit list of services and features shown': 'تحرير قائمة الخدمات والميزات المعروضة',
    'Service Name': 'اسم الخدمة',
    'Service description...': 'وصف الخدمة...',
    'Icon (Lucide)': 'الأيقونة (Lucide)',
    'No services. Click "Add Service" to start.': 'لا توجد خدمات. انقر "إضافة خدمة" للبدء.',

    # Media
    'Upload and manage images and files': 'رفع وإدارة الصور والملفات',
    'Add URL': 'إضافة رابط',
    'Search by name...': 'البحث بالاسم...',
    'Upload Date': 'تاريخ الرفع',
    'File uploaded:': 'تم رفع الملف:',
    'URL copied': 'تم نسخ الرابط',

    # Monitoring
    'Server and service status in real time': 'حالة الخوادم والخدمات في الوقت الفعلي',
    'CPU': 'المعالج',
    'cores': 'أنوية',
    'RAM': 'الذاكرة',
    'Disk': 'القرص',
    'Recent errors and warnings': 'آخر الأخطاء والتحذيرات',
    'View all logs': 'عرض كل السجلات',
    'No recent errors': 'لا توجد أخطاء مؤخراً',

    # Organizations
    'Organization Management': 'إدارة المؤسسات',
    'Manage all organizations registered on the platform': 'إدارة جميع المؤسسات المسجّلة في المنصّة',
    'Add Organization': 'إضافة مؤسسة',
    'Search by name or email...': 'البحث بالاسم أو البريد الإلكتروني...',
    'No matching organizations': 'لا توجد مؤسسات مطابقة',
    'Registration Date': 'تاريخ التسجيل',
    'Failed to load organizations': 'تعذّر تحميل المؤسسات',
    'This feature will be added soon': 'سيتم إضافة هذه الميزة قريباً',
    'Deactivate': 'تعطيل',
    'Activate': 'تفعيل',
    'Are you sure you want to': 'هل أنت متأكد من',
    'organization': 'المؤسسة',
    'successfully': 'بنجاح',

    # SEO
    'Search Engine Optimization': 'تحسين محركات البحث',
    'SEO settings and metadata for each page': 'إعدادات SEO وبيانات التعريف لكل صفحة',
    'Open Graph / Social': 'Open Graph / وسائل التواصل',
    'OG Type': 'نوع OG',
    'Checklist': 'قائمة التحقّق',
    'OG Image': 'صورة OG',
    'Title length ≤ 60': 'طول العنوان ≤ 60',
    'Description length ≤ 160': 'طول الوصف ≤ 160',
    'Page title': 'عنوان الصفحة',
    'Page description appears here...': 'وصف الصفحة يظهر هنا...',

    # Settings
    'General settings for the Get Solution platform': 'الإعدادات العامة لمنصّة Get Solution',
    'Sensitive': 'حساس',
    'No settings in this group': 'لا توجد إعدادات في هذه المجموعة',

    # Document audit report
    'Tadgeeg — Document Audit Report': 'تدقيق — تقرير تدقيق المستند',
    'Print / PDF': 'طباعة / PDF',
    '%(v0)s': '%(v0)s',
    'Document #:': 'رقم المستند:',
    'Date:': 'التاريخ:',
    'Generated:': 'أُنشئ:',
    'Clean': 'نظيف',
    'Not Audited': 'لم يُدقَّق',
    'Risk Level:': 'مستوى المخاطرة:',
    'Risk Score:': 'درجة المخاطرة:',
    'Auditor:': 'المدقق:',
    'Blocks Approval': 'يحجب الاعتماد',
    'Manual Review Required': 'يتطلّب مراجعة يدوية',
    'Total (%(v0)s)': 'الإجمالي (%(v0)s)',
    'Rules Passed': 'القواعد المُجتازة',
    'Rules Failed': 'القواعد الفاشلة',
    'Block Approval': 'حجب الاعتماد',
    'Error Rate': 'معدّل الخطأ',
    'Total Documents': 'إجمالي المستندات',
    'Critical Risk': 'مخاطرة حرجة',
    'High-Risk Documents (%(v0)s)': 'المستندات عالية المخاطرة (%(v0)s)',
    'ID': 'المعرّف',
    'Most Frequent Violations': 'أكثر المخالفات تكراراً',
    'Document List (%(v0)s)': 'قائمة المستندات (%(v0)s)',
    'Key Fields': 'الحقول الرئيسية',
    'Vendor / Customer': 'المورد / العميل',
    'Opening Balance': 'الرصيد الافتتاحي',
    'Closing Balance': 'الرصيد الختامي',
    'Net VAT Payable': 'صافي الضريبة المستحقّة',
    'QR Code Valid': 'رمز QR صالح',
    'QR Code Invalid': 'رمز QR غير صالح',
    'QR Code Missing': 'رمز QR مفقود',
    'Rule Evaluation Results (%(v0)s rules)': 'نتائج تقييم القواعد (%(v0)s قاعدة)',
    'Code': 'الرمز',
    'Severity': 'الشدّة',
    'Blocks': 'يحجب',
    'Expected': 'المتوقّع',
    'Actual': 'الفعلي',
    'No audit results available': 'لا توجد نتائج تدقيق متاحة',
    'Violations (%(v0)s)': 'المخالفات (%(v0)s)',
    'Financial Impact:': 'الأثر المالي:',
    'AI Insights': 'رؤى الذكاء الاصطناعي',
    'Risk Factors': 'عوامل المخاطرة',
    'Scope and Methodology': 'النطاق والمنهجية',
    'Management Response': 'استجابة الإدارة',
    'Required Fields Missing': 'حقول إلزامية مفقودة',
    'VAT Breakdown': 'تفصيل ضريبة القيمة المضافة',
    'Expected VAT:': 'الضريبة المتوقّعة:',
    '— Discrepancy may indicate calculation error': '— الفارق قد يدل على خطأ حسابي',
    'Balance Reconciliation': 'تسوية الرصيد',
    'Opening': 'افتتاحي',
    'Credits': 'دائن',
    'Debits': 'مدين',
    'Closing': 'ختامي',
    '%(v0)s suspicious transactions near AML reporting threshold': '%(v0)s معاملة مشبوهة قرب حد الإبلاغ AML',
    'Payroll Breakdown': 'تفصيل كشف الرواتب',
    'Total Gross': 'الإجمالي قبل الخصم',
    'Total Deductions': 'إجمالي الخصومات',
    'Total Net': 'الصافي الإجمالي',
    '%(v0)s potential ghost employees |\n        %(v1)s duplicate IDs': '%(v0)s موظف وهمي محتمل |\n        %(v1)s معرّف مكرّر',
    'VAT Net Calculation': 'احتساب صافي الضريبة',
    'Output VAT': 'ضريبة المخرجات',
    'Input VAT': 'ضريبة المدخلات',
    'Arithmetic error — discrepancy: %(v0)s SAR': 'خطأ حسابي — الفارق: %(v0)s ريال',
    'Calculation correct': 'الحساب صحيح',
    'Depreciation Summary': 'ملخّص الإهلاك',
    'Total Cost': 'التكلفة الإجمالية',
    'Accumulated Dep.': 'مجمع الإهلاك',
    'Book Value': 'القيمة الدفترية',
    'Negative BV': 'قيمة دفترية سالبة',
    'Vendor Validation': 'التحقّق من المورد',
    'CR Number': 'رقم السجل التجاري',
    'Budget Validation': 'التحقّق من الميزانية',
    'Budget Limit': 'حد الميزانية',
    'PO Amount': 'مبلغ أمر الشراء',
    'Within Budget ✓': 'ضمن الميزانية ✓',
    'Over Budget ✗': 'تجاوز الميزانية ✗',
    'Approved by:': 'اعتمدها:',
    'Cost Center:': 'مركز التكلفة:',
    'Receipt Validation': 'التحقّق من الإيصال',
    'Total Lines': 'إجمالي البنود',
    'With Receipt': 'مع إيصال',
    'Missing Receipt': 'إيصال مفقود',
    '%(v0)s line(s) exceeded policy limit': '%(v0)s بند تجاوز حد السياسة',
    '| Self-approval detected': '| تم اكتشاف اعتماد ذاتي',
    'Expense Category Breakdown': 'تفصيل فئات المصروفات',
    'Payment Validation': 'التحقّق من الدفع',
    'Payment Method': 'طريقة الدفع',
    'AML Cash Limit': 'حد النقدية AML',
    'Within Limit': 'ضمن الحد',
    'Exceeds Limit': 'تجاوز الحد',
    'Receipt No.:': 'رقم الإيصال:',
    'ZATCA Ref.:': 'مرجع ZATCA:',
    'QR Valid': 'QR صالح',
    'QR Invalid': 'QR غير صالح',
    'QR Missing': 'QR مفقود',
    'Line Items (%(v0)s)': 'بنود المستند (%(v0)s)',
    'Qty': 'الكمية',
    'VAT %%': 'الضريبة %%',
    'Recommendations & Action Plan': 'التوصيات وخطة العمل',
    'Est. Financial Impact:': 'الأثر المالي المُقدَّر:',
    'Scope & Methodology': 'النطاق والمنهجية',
    'Audit Date': 'تاريخ التدقيق',
    'Automatic': 'آلي',
    'Manual': 'يدوي',
    'Engine Version': 'إصدار المحرّك',
    'Tadgeeg Audit Platform — AI-Powered Financial Auditing': 'منصّة تدقيق — التدقيق المالي بالذكاء الاصطناعي',
    'Executive Audit Report': 'التقرير التنفيذي الشامل',
    'Overall Risk Score': 'درجة المخاطرة الإجمالية',
    'Prepared by': 'إعداد',
    'Top Issues': 'أبرز المشاكل',
    'Formal Auditor\\': 'مدقق رسمي\\',
    'Key Risks': 'أبرز المخاطر',
    'Financial Overview': 'نظرة عامة مالية',
    'Total Revenue': 'إجمالي الإيرادات',
    'Total Expenses': 'إجمالي المصروفات',
    'VAT Payable': 'الضريبة المستحقّة',
    'Audit Overview': 'نظرة عامة على التدقيق',
    'Documents Audited': 'المستندات المُدقَّقة',
    'Clean Documents': 'المستندات النظيفة',
    'With Issues': 'بها مشاكل',
    'Blocking Approval': 'تحجب الاعتماد',
    'Pass vs Failure Rate': 'نسبة النجاح مقابل الفشل',
    'Rules Run': 'القواعد المُشغَّلة',
    'Top Failed Rules': 'أكثر القواعد فشلاً',
    '× %(v0)s': '× %(v0)s',
    'Critical:': 'حرج:',
    'High:': 'عالي:',
    'High-Risk Documents': 'المستندات عالية المخاطرة',
    'score': 'درجة',
    'No high-risk documents': 'لا توجد مستندات عالية المخاطرة',
    'ZATCA Compliance Rate': 'معدّل امتثال ZATCA',
    'Needs Improvement': 'يحتاج تحسيناً',
    'VAT Failures': 'إخفاقات الضريبة',
    'out of': 'من أصل',
    'checks': 'فحوصات',
    'VAT Failure Rate': 'معدّل إخفاق الضريبة',
    'left': 'متبقّي',
    'Occurrences': 'التكرارات',
    'AI-Powered Insights': 'رؤى مدعومة بالذكاء الاصطناعي',
    'Fraud Indicators': 'مؤشّرات الاحتيال',
    'Structuring Alerts': 'تنبيهات التركيب',
    'Ghost Employees': 'موظفون وهميون',
    'Duplicate Alerts': 'تنبيهات التكرار',
    'Self-Approvals': 'اعتمادات ذاتية',
    'Alert: Risks Detected Requiring Immediate Review': 'تنبيه: تم اكتشاف مخاطر تتطلّب مراجعة فورية',
    'Internal audit team should review all flagged documents immediately.': 'على فريق التدقيق الداخلي مراجعة كل المستندات المعلَّمة فوراً.',
    'AI detected no fraud indicators or critical violations in this period.': 'لم يكتشف الذكاء الاصطناعي مؤشّرات احتيال أو مخالفات حرجة في هذه الفترة.',
    'Anomaly Pattern Analysis — AI Interpretation': 'تحليل أنماط الشذوذ — تفسير الذكاء الاصطناعي',
    '×%(v0)s occurrences': '×%(v0)s تكرارات',
    'Document Breakdown by Type': 'تفصيل المستندات حسب النوع',
    'documents': 'مستندات',
    'avg risk': 'متوسط المخاطرة',
    'Failures:': 'الإخفاقات:',
    'AI-Powered Financial Auditing Platform': 'منصّة التدقيق المالي بالذكاء الاصطناعي',
    'right': 'يمين',
    'By:': 'بواسطة:',
    'Confidential — Internal Use Only': 'سرّي — للاستخدام الداخلي فقط',
}


def main():
    ar = polib.pofile(AR_PATH)
    applied, missing = 0, []
    for entry in ar:
        if entry.obsolete or entry.msgid_plural:
            continue
        is_fuzzy = 'fuzzy' in entry.flags
        is_empty = not entry.msgstr and entry.msgid != ""
        if not (is_fuzzy or is_empty):
            continue
        if entry.msgid in AR:
            entry.msgstr = AR[entry.msgid]
            if is_fuzzy:
                entry.flags = [f for f in entry.flags if f != 'fuzzy']
                entry.previous_msgid = None
                entry.previous_msgctxt = None
            applied += 1
        else:
            missing.append(entry.msgid)
    ar.save(AR_PATH)
    print(f"AR applied: {applied}, missing: {len(missing)}")
    for m in missing[:20]:
        print(f"  MISS: {m!r}")

    en = polib.pofile(EN_PATH)
    fixed = 0
    for entry in en:
        if entry.obsolete or entry.msgid_plural:
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
        print(f"{name}: empty={e}, fuzzy={f}")


if __name__ == '__main__':
    main()
