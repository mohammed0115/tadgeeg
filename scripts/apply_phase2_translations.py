"""Apply translations for new strings introduced in Phase 2/3.

Same logic as apply_ar_translations.py: fix fuzzy + empty entries by
applying explicit translations and clearing the fuzzy flag.

For EN: msgstr = msgid for all empty/fuzzy (English source).
For AR: explicit translations dict.
"""
import polib

AR_PATH = '/home/mohamed/tadgeeg/locale/ar/LC_MESSAGES/django.po'
EN_PATH = '/home/mohamed/tadgeeg/locale/en/LC_MESSAGES/django.po'

AR_NEW = {
    # New empty
    'Page %(current)s of %(total)s · %(count)s documents': 'صفحة %(current)s من %(total)s · %(count)s مستند',
    'Error — Executive Report': 'خطأ — التقرير التنفيذي',
    'If the problem persists, please contact technical support': 'إذا استمرت المشكلة، يرجى التواصل مع الدعم الفني',
    'Organize your files in folders': 'نظّم ملفاتك في مجلّدات',

    # Fuzzy → correct
    'Audit History': 'سجل التدقيق',
    'Total Documents:': 'إجمالي المستندات:',
    'New Document Audit': 'تدقيق مستند جديد',
    'Confidence': 'الثقة',
    'Upload your first financial document to start automated auditing': 'ارفع أوّل مستند مالي للبدء بالتدقيق الآلي',
    'Upload first document': 'رفع أوّل مستند',
    'Invoice Batch Details': 'تفاصيل دفعة الفواتير',
    'Batch Details': 'تفاصيل الدفعة',
    'Back to Batches': 'العودة إلى الدفعات',
    'Open audit session': 'فتح جلسة التدقيق',
    'Successful': 'ناجحة',
    'All Risk Levels': 'كل مستويات المخاطرة',
    'Uploaded by': 'رفعها',
    'processed of': 'معالَجة من',
    'failed': 'فشلت',
    'Batch': 'دفعة',
    'Failed to load batch details': 'تعذّر تحميل تفاصيل الدفعة',
    'We could not fetch this batch right now. Refresh the page or try again shortly.': 'لم نتمكّن من جلب بيانات هذه الدفعة الآن. حدّث الصفحة أو أعد المحاولة بعد قليل.',
    'No data': 'لا توجد بيانات',
    'file': 'ملف',
    'item': 'عنصر',
    'Executive Report Error': 'خطأ في التقرير التنفيذي',
    'Message:': 'الرسالة:',
    'An unexpected error occurred while generating the executive report': 'حدث خطأ غير متوقّع أثناء توليد التقرير التنفيذي',
    'Go Back': 'العودة للخلف',
    'Create subfolder': 'إنشاء مجلّد فرعي',
    'Folder Name': 'اسم المجلّد',
    'e.g. Invoices 2025': 'مثال: فواتير 2025',
}

# AR: apply explicit translations
ar = polib.pofile(AR_PATH)
ar_applied = 0
ar_missing = []
for entry in ar:
    if entry.obsolete or entry.msgid_plural:
        continue
    is_fuzzy = 'fuzzy' in entry.flags
    is_empty = not entry.msgstr and entry.msgid != ""
    if not is_fuzzy and not is_empty:
        continue
    if entry.msgid in AR_NEW:
        entry.msgstr = AR_NEW[entry.msgid]
        if is_fuzzy:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        ar_applied += 1
    else:
        ar_missing.append(entry.msgid)
ar.save(AR_PATH)
print(f"AR applied: {ar_applied}, missing: {len(ar_missing)}")
for m in ar_missing:
    print(f"  AR missing: {m!r}")

# EN: msgstr = msgid for all empty/fuzzy
en = polib.pofile(EN_PATH)
en_fixed = 0
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
        en_fixed += 1
en.save(EN_PATH)
print(f"EN fixed: {en_fixed}")

# Final stats
for path, name in [(AR_PATH, 'AR'), (EN_PATH, 'EN')]:
    p = polib.pofile(path)
    e = sum(1 for x in p if not x.msgstr and not x.obsolete and x.msgid != "" and not x.msgid_plural)
    f = sum(1 for x in p if 'fuzzy' in x.flags and not x.obsolete)
    print(f"{name}: empty={e}, fuzzy={f}")
